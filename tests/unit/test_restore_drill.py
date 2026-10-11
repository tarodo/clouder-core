"""scripts/restore_drill.py: PITR into a new cluster, timed, never touching production."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "restore_drill.py"


def _load():
    spec = importlib.util.spec_from_file_location("restore_drill", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeRDS:
    class exceptions:
        class DBClusterNotFoundFault(Exception):
            pass

        class DBInstanceNotFoundFault(Exception):
            pass

    def __init__(self, existing: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.existing = existing
        self.cluster_checks = 0
        self.instance_checks = 0

    def _called(self, name: str) -> bool:
        return any(c[0] == name for c in self.calls)

    def describe_db_clusters(self, DBClusterIdentifier):
        self.calls.append(("describe_db_clusters", {"id": DBClusterIdentifier}))
        if DBClusterIdentifier == "clouder-prod-aurora":
            return {
                "DBClusters": [
                    {
                        "DBSubnetGroup": "subnets",
                        "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-1"}],
                        "LatestRestorableTime": datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
                    }
                ]
            }
        if not self.existing and not self._called("restore_db_cluster_to_point_in_time"):
            raise self.exceptions.DBClusterNotFoundFault("not found")
        self.cluster_checks += 1
        managed = self.existing or self._called("modify_db_cluster")
        return {
            "DBClusters": [
                {
                    "Status": "creating" if self.cluster_checks < 2 else "available",
                    "DBClusterArn": "arn:drill",
                    "HttpEndpointEnabled": self._called("enable_http_endpoint"),
                    **({"MasterUserSecret": {"SecretArn": "arn:secret"}} if managed else {}),
                }
            ]
        }

    def describe_db_instances(self, DBInstanceIdentifier):
        self.calls.append(("describe_db_instances", {"id": DBInstanceIdentifier}))
        if not self.existing and not self._called("create_db_instance"):
            raise self.exceptions.DBInstanceNotFoundFault("not found")
        if self._called("delete_db_instance"):
            raise self.exceptions.DBInstanceNotFoundFault("gone")
        self.instance_checks += 1
        status = "creating" if self.instance_checks < 2 else "available"
        return {"DBInstances": [{"DBInstanceStatus": status}]}

    def __getattr__(self, name):
        def call(**kw):
            self.calls.append((name, kw))
            return {}

        return call


def _clock():
    t = [datetime(2026, 10, 11, 14, 0, tzinfo=UTC)]

    def now():
        t[0] += timedelta(seconds=30)
        return t[0]

    return now


def _restore(rds):
    return _load().restore(
        rds,
        source="clouder-prod-aurora",
        target="clouder-prod-aurora-drill",
        now=_clock(),
        sleep=lambda s: None,
    )


def test_restore_targets_a_new_cluster_in_the_production_network() -> None:
    rds = FakeRDS()

    timeline = _restore(rds)

    (restore,) = [kw for name, kw in rds.calls if name == "restore_db_cluster_to_point_in_time"]
    assert restore["SourceDBClusterIdentifier"] == "clouder-prod-aurora"
    assert restore["DBClusterIdentifier"] == "clouder-prod-aurora-drill"
    assert restore["UseLatestRestorableTime"] is True
    assert restore["DBSubnetGroupName"] == "subnets" and restore["VpcSecurityGroupIds"] == ["sg-1"]
    assert restore["DeletionProtection"] is False
    (writer,) = [kw for name, kw in rds.calls if name == "create_db_instance"]
    assert writer["DBClusterIdentifier"] == "clouder-prod-aurora-drill"
    assert writer["DBInstanceClass"] == "db.serverless"
    assert any(
        n == "modify_db_cluster" and kw.get("ManageMasterUserPassword") for n, kw in rds.calls
    )
    assert any(
        n == "enable_http_endpoint" and kw["ResourceArn"] == "arn:drill" for n, kw in rds.calls
    )
    for key in ("requested", "cluster_available", "writer_available", "ready", "restore_point"):
        assert key in timeline
    assert timeline["rto_seconds"] > 0 and timeline["secret_arn"] == "arn:secret"
    assert timeline["rpo_seconds"] == 3630  # requested 14:00:30, restorable up to 13:00
    for name, kw in rds.calls:  # nothing mutating ever names the production cluster alone
        if not name.startswith("describe"):
            assert "clouder-prod-aurora-drill" in str(kw) or kw.get("ResourceArn") == "arn:drill"


def test_a_resumed_restore_does_not_create_twice() -> None:
    rds = FakeRDS(existing=True)
    _restore(rds)
    assert not any(n == "restore_db_cluster_to_point_in_time" for n, _ in rds.calls)
    assert not any(n == "create_db_instance" for n, _ in rds.calls)


def test_teardown_refuses_anything_but_a_drill_cluster() -> None:
    mod = _load()
    with pytest.raises(ValueError):
        mod.teardown(FakeRDS(), target="clouder-prod-aurora", sleep=lambda s: None)
    rds = FakeRDS(existing=True)
    mod.teardown(rds, target="clouder-prod-aurora-drill", sleep=lambda s: None)
    names = [n for n, _ in rds.calls]
    assert names.index("delete_db_instance") < names.index("delete_db_cluster")
    (cluster,) = [kw for n, kw in rds.calls if n == "delete_db_cluster"]
    assert cluster["SkipFinalSnapshot"] is True


def test_compare_reports_counts_and_the_newest_row_gap() -> None:
    prod = {"clouder_tracks": {"rows": 10, "newest": "2026-10-11 13:05:00+00"}}
    drill = {"clouder_tracks": {"rows": 9, "newest": "2026-10-11 12:59:00+00"}}
    (row,) = _load().compare(prod, drill)
    assert row == {
        "table": "clouder_tracks",
        "prod_rows": 10,
        "drill_rows": 9,
        "missing_rows": 1,
        "newest_gap_seconds": 360,
    }

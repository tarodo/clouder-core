"""The S3 / lake half of user deletion: covers, tombstone, Iceberg deletes."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from collector.user_deletion import delete_covers, delete_models, purge_lake

UID = "3f2b8c1e-0000-4000-8000-000000000001"
HEX = "3f2b8c1e000040008000000000000001"  # how users.id stores it: auth mints uuid4().hex


class FakeS3:
    def __init__(self, versions: list[dict]) -> None:
        self.versions = versions
        self.deleted: list[dict] = []
        self.put: dict | None = None

    def get_paginator(self, name: str):
        assert name == "list_object_versions"
        return self

    def paginate(self, *, Bucket: str, Prefix: str):
        rows = [v for v in self.versions if v["Key"].startswith(Prefix)]
        yield {
            "Versions": [v for v in rows if not v.get("marker")],
            "DeleteMarkers": [v for v in rows if v.get("marker")],
        }

    def delete_objects(self, *, Bucket: str, Delete: dict) -> dict:
        self.deleted += Delete["Objects"]
        return {
            "Errors": [
                {"Key": o["Key"], "Code": "AccessDenied"}
                for o in Delete["Objects"]
                if o["Key"].endswith("locked.jpg")
            ]
        }

    def put_object(self, **kwargs) -> dict:
        self.put = kwargs
        return {}


class FakeAthena:
    def __init__(self, state: str = "SUCCEEDED") -> None:
        self.state = state
        self.queries: list[dict] = []

    def start_query_execution(self, **kwargs) -> dict:
        self.queries.append(kwargs)
        return {"QueryExecutionId": str(len(self.queries))}

    def get_query_execution(self, *, QueryExecutionId: str) -> dict:
        return {"QueryExecution": {"Status": {"State": self.state}}}


@pytest.mark.parametrize("uid", [UID, HEX, UID.upper()])
def test_delete_covers_removes_every_version_and_marker_of_this_user_only(uid: str) -> None:
    s3 = FakeS3(
        [
            {"Key": f"covers/{HEX}/p1/1.jpg", "VersionId": "v1"},
            {"Key": f"covers/{HEX}/p1/1.jpg", "VersionId": "v2", "marker": True},
            {"Key": f"covers/{HEX}0/p9/1.jpg", "VersionId": "v3"},  # a longer id, same prefix
        ]
    )

    assert delete_covers(s3, "raw", uid) == 2
    assert s3.deleted == [
        {"Key": f"covers/{HEX}/p1/1.jpg", "VersionId": "v1"},
        {"Key": f"covers/{HEX}/p1/1.jpg", "VersionId": "v2"},
    ]


@pytest.mark.parametrize("uid", [UID, HEX])
def test_delete_models_removes_every_version_of_this_users_models_only(uid: str) -> None:
    s3 = FakeS3(
        [
            {"Key": f"models/{HEX}/st1/v1-0a1b2c3d4e5f.npz", "VersionId": "v1"},
            {"Key": f"models/{HEX}/st1/v1-0a1b2c3d4e5f.npz", "VersionId": "v2", "marker": True},
            {"Key": f"models/{HEX}/st2/v3-ffffffffffff.npz", "VersionId": "v3"},
            {"Key": "models/someoneelse/st1/v1-000000000000.npz", "VersionId": "v4"},
            {"Key": f"features/light-1/{HEX}.f16", "VersionId": "v5"},
        ]
    )

    assert delete_models(s3, "features", uid) == 3
    assert {(o["Key"], o["VersionId"]) for o in s3.deleted} == {
        (f"models/{HEX}/st1/v1-0a1b2c3d4e5f.npz", "v1"),
        (f"models/{HEX}/st1/v1-0a1b2c3d4e5f.npz", "v2"),
        (f"models/{HEX}/st2/v3-ffffffffffff.npz", "v3"),
    }


def test_purge_lake_writes_the_tombstone_before_deleting_derived_rows() -> None:
    s3, athena = FakeS3([]), FakeAthena()
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)

    purge_lake(
        s3, athena, user_id=UID, lake_bucket="lake", workgroup="wg", now=now, sleep=lambda _: None
    )

    # Telemetry carries the stored id (the authorizer's), so the tombstone and the deletes use it too.
    assert s3.put["Key"] == f"governance/deleted_users/{HEX}.json"
    assert json.loads(s3.put["Body"]) == {"user_id": HEX, "deleted_at": "2026-10-08T12:00:00+00:00"}
    # Athena takes ExecutionParameters only for SELECT/INSERT/CTAS/UNLOAD: the
    # (UUID-validated) id is inlined.
    assert [q["QueryString"] for q in athena.queries] == [
        f"DELETE FROM clouder_silver.events WHERE user_id = '{HEX}'",
        f"DELETE FROM clouder_gold.fct_play WHERE user_id = '{HEX}'",
    ]
    assert all("ExecutionParameters" not in q and q["WorkGroup"] == "wg" for q in athena.queries)


def test_purge_lake_fails_loudly_when_athena_fails() -> None:
    with pytest.raises(RuntimeError, match="FAILED"):
        purge_lake(
            FakeS3([]),
            FakeAthena("FAILED"),
            user_id=UID,
            lake_bucket="lake",
            workgroup="wg",
            now=datetime.now(UTC),
            sleep=lambda _: None,
        )


def test_delete_covers_fails_when_s3_refuses_a_version() -> None:
    # DeleteObjects answers 200 and lists per-key failures in Errors.
    s3 = FakeS3([{"Key": f"covers/{HEX}/p1/locked.jpg", "VersionId": "v1"}])
    with pytest.raises(RuntimeError, match=r"locked\.jpg"):
        delete_covers(s3, "raw", UID)


def test_lake_steps_refuse_an_id_that_is_not_a_uuid() -> None:
    with pytest.raises(ValueError):
        delete_covers(FakeS3([]), "raw", "../")
    with pytest.raises(ValueError):
        delete_models(FakeS3([]), "features", "")

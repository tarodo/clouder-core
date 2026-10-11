#!/usr/bin/env python3
"""Aurora restore drill: point-in-time restore into a new cluster, timed (docs/ops/aurora.md).

    .venv/bin/python scripts/restore_drill.py restore --report drill.json
    PYTHONPATH=src .venv/bin/python scripts/restore_drill.py verify --report drill.json
    .venv/bin/python scripts/restore_drill.py teardown

`restore` restores the latest restorable time of the production cluster into a new one in
the same subnets and security group, adds a writer, turns on the managed master secret and
the Data API, and records a timeline; re-running it continues a half-finished restore.
`verify` compares row counts and newest timestamps on both clusters (it reads rows, so the
operator runs it). `teardown` deletes the drill cluster without a final snapshot and refuses
any identifier not ending in -drill.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

REGION = "us-east-1"
SOURCE = "clouder-prod-aurora"
TARGET = "clouder-prod-aurora-drill"
# (table, newest-timestamp column): the canonical catalog, users and ingest history.
TABLES = (
    ("clouder_tracks", "updated_at"),
    ("clouder_artists", "updated_at"),
    ("identity_map", "last_seen_at"),
    ("ingest_runs", "started_at"),
    ("users", "updated_at"),
    ("categories", "updated_at"),
    ("playlists", "updated_at"),
)


def _wait(check: Callable[[], bool], sleep: Callable[[float], None]) -> None:
    while not check():
        sleep(30)


def restore(
    rds: Any,
    *,
    source: str,
    target: str,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    src = rds.describe_db_clusters(DBClusterIdentifier=source)["DBClusters"][0]
    started = now()
    timeline: dict[str, Any] = {
        "source": source,
        "target": target,
        "requested": started.isoformat(),
        "restore_point": src["LatestRestorableTime"].isoformat(),
        # Writes after the restore point would be lost in a real incident.
        "rpo_seconds": int((started - src["LatestRestorableTime"]).total_seconds()),
    }
    try:
        rds.describe_db_clusters(DBClusterIdentifier=target)
    except rds.exceptions.DBClusterNotFoundFault:
        rds.restore_db_cluster_to_point_in_time(
            SourceDBClusterIdentifier=source,
            DBClusterIdentifier=target,
            UseLatestRestorableTime=True,
            DBSubnetGroupName=src["DBSubnetGroup"],
            VpcSecurityGroupIds=[g["VpcSecurityGroupId"] for g in src["VpcSecurityGroups"]],
            ServerlessV2ScalingConfiguration={"MinCapacity": 0, "MaxCapacity": 2},
            DeletionProtection=False,
            CopyTagsToSnapshot=False,
        )

    def cluster() -> dict[str, Any]:
        return rds.describe_db_clusters(DBClusterIdentifier=target)["DBClusters"][0]

    _wait(lambda: cluster()["Status"] == "available", sleep)
    timeline["cluster_available"] = now().isoformat()

    writer = f"{target}-writer"

    def writer_status() -> str:
        info = rds.describe_db_instances(DBInstanceIdentifier=writer)["DBInstances"][0]
        return str(info["DBInstanceStatus"])

    try:
        writer_status()
    except rds.exceptions.DBInstanceNotFoundFault:
        rds.create_db_instance(
            DBInstanceIdentifier=writer,
            DBClusterIdentifier=target,
            DBInstanceClass="db.serverless",
            Engine="aurora-postgresql",
        )
    _wait(lambda: writer_status() == "available", sleep)
    timeline["writer_available"] = now().isoformat()

    info = cluster()
    if not info.get("MasterUserSecret"):
        rds.modify_db_cluster(
            DBClusterIdentifier=target, ManageMasterUserPassword=True, ApplyImmediately=True
        )
    if not info.get("HttpEndpointEnabled"):
        rds.enable_http_endpoint(ResourceArn=info["DBClusterArn"])

    def ready() -> bool:
        c = cluster()
        return bool(c.get("HttpEndpointEnabled")) and bool(c.get("MasterUserSecret"))

    _wait(ready, sleep)
    done = now()
    final = cluster()
    timeline.update(
        ready=done.isoformat(),
        rto_seconds=int((done - started).total_seconds()),
        cluster_arn=final["DBClusterArn"],
        secret_arn=final["MasterUserSecret"]["SecretArn"],
    )
    return timeline


def snapshot_counts(db: Any) -> dict[str, dict[str, Any]]:
    out = {}
    for table, column in TABLES:
        row = db.execute(
            f'SELECT count(*) AS rows, max("{column}")::text AS newest FROM "{table}"'
        )[0]
        out[table] = {"rows": int(row["rows"]), "newest": row["newest"]}
    return out


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    if value[-3] in "+-" and value[-3:].replace("+", "").replace("-", "").isdigit():
        value += ":00"  # Postgres prints a whole-hour offset as +00
    return datetime.fromisoformat(value)


def compare(prod: dict[str, dict[str, Any]], drill: dict[str, dict[str, Any]]) -> list[dict]:
    rows = []
    for table, p in prod.items():
        d = drill[table]
        p_ts, d_ts = _ts(p["newest"]), _ts(d["newest"])
        gap = int((p_ts - d_ts).total_seconds()) if p_ts and d_ts else None
        rows.append(
            {
                "table": table,
                "prod_rows": p["rows"],
                "drill_rows": d["rows"],
                "missing_rows": p["rows"] - d["rows"],
                "newest_gap_seconds": gap,
            }
        )
    return rows


def teardown(rds: Any, *, target: str, sleep: Callable[[float], None] = time.sleep) -> None:
    if not target.endswith("-drill"):
        raise ValueError(f"refusing to delete {target!r}: only a *-drill cluster")
    writer = f"{target}-writer"
    rds.delete_db_instance(DBInstanceIdentifier=writer, SkipFinalSnapshot=True)

    def writer_gone() -> bool:
        try:
            rds.describe_db_instances(DBInstanceIdentifier=writer)
        except rds.exceptions.DBInstanceNotFoundFault:
            return True
        return False

    _wait(writer_gone, sleep)
    rds.delete_db_cluster(DBClusterIdentifier=target, SkipFinalSnapshot=True)


def _data_api(cluster_arn: str, secret_arn: str) -> Any:
    from collector.data_api import create_default_data_api_client
    from collector.data_api_retry import wake_database

    client = create_default_data_api_client(
        resource_arn=cluster_arn, secret_arn=secret_arn, database="clouder"
    )
    wake_database(client)
    return client


def main(argv: list[str] | None = None, rds: Any = None) -> int:
    parser = argparse.ArgumentParser(description="Aurora restore drill")
    parser.add_argument("command", choices=("restore", "verify", "teardown"))
    parser.add_argument("--report", default="aurora-drill.json")
    args = parser.parse_args(argv)
    if rds is None:
        import boto3

        rds = boto3.client("rds", region_name=REGION)

    if args.command == "restore":
        timeline = restore(rds, source=SOURCE, target=TARGET)
        with open(args.report, "w") as f:
            json.dump(timeline, f, indent=2)
        print(json.dumps(timeline, indent=2))
        return 0
    if args.command == "teardown":
        teardown(rds, target=TARGET)
        print(f"deleted {TARGET} (no final snapshot)")
        return 0

    with open(args.report) as f:
        report = json.load(f)
    prod = snapshot_counts(
        _data_api(os.environ["AURORA_CLUSTER_ARN"], os.environ["AURORA_SECRET_ARN"])
    )
    drill = snapshot_counts(_data_api(report["cluster_arn"], report["secret_arn"]))
    report["verify"] = compare(prod, drill)
    newest = max(filter(None, (_ts(d["newest"]) for d in drill.values())))
    report["newest_drill_row"] = newest.isoformat()  # must not be after restore_point
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ("rto_seconds", "rpo_seconds", "verify")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

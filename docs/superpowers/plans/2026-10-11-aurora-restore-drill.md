# Aurora Restore Drill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rehearse the documented Aurora recovery — point-in-time restore into a new cluster — and replace "not rehearsed yet" in the failure-modes table with a measured RTO and RPO and a game-day report.

**Architecture:** `scripts/restore_drill.py` has three subcommands. `restore` restores the latest restorable time of `clouder-prod-aurora` into `clouder-prod-aurora-drill` (same subnet group and security group, Serverless v2 0–2 ACU, no deletion protection), adds a writer, turns on the RDS-managed master secret and the Data API, and writes a timeline (request, cluster available, writer available, ready) to a JSON file. `verify` counts rows and the newest timestamps of key tables on both clusters through the Data API and reports the gap. `teardown` deletes the drill writer and cluster without a final snapshot. Nothing in Terraform changes: the drill cluster is temporary and outside it.

**Tech Stack:** Python 3.12, boto3 (rds, rds-data via the repo's Data API client), pytest with fake clients.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §8 (Backups/DR "Present but weak"), §11 Level 4 (restore drill), §0.3 phase 5; `docs/ops/failure-modes.md` ("restore + repoint, not rehearsed yet"); `docs/ops/aurora.md` ("A restore goes to a new cluster (`aws rds restore-db-cluster-to-point-in-time`), and the Terraform variables then point at it").

## Global Constraints

- Worktree `../clouder-core-loop`, branch `docs/aurora-restore-drill` from `origin/main`; tools from the main checkout's `.venv/bin/`.
- Region us-east-1; source cluster `clouder-prod-aurora`; drill cluster `clouder-prod-aurora-drill` (writer `clouder-prod-aurora-drill-writer`).
- The agent may run `restore` (creates a temporary cluster, reads no data). **`verify` (reads rows through `rds-data`) and `teardown` (deletes a database) are the owner's**: the agent has no `rds-data` access, and deleting a database is never the agent's call.
- No money figures; English in the repo; commit messages from `caveman:caveman-commit`; no AI attribution.

## Review Focus

1. **The drill must never touch the production cluster**: every mutating call names the drill identifier, and `teardown` refuses any identifier that does not end in `-drill`. Pinned in Task 1.
2. **The restore must be reachable from the Lambdas' network** (same DB subnet group and security group as production) so the repoint in a real incident works. Pinned in Task 1 (call parameters).
3. **RTO is measured from the restore request to "Data API answers"**, not to "cluster available" alone. Pinned in Task 1 (timeline keys).
4. **RPO is evidence, not an assumption**: the newest timestamps on the drill vs. the restore point. Pinned in Task 1 (`verify` report).
5. **A half-finished restore can be resumed** (re-running `restore` with the cluster already there skips creation and continues waiting). Pinned in Task 1.

---

### Task 1: The drill script

**Files:**
- Create: `scripts/restore_drill.py`, `tests/unit/test_restore_drill.py`

**Interfaces:**
- Produces: `restore(rds, *, source, target, now=..., sleep=...) -> dict` (timeline with ISO timestamps and seconds), `compare(prod: dict[str, dict], drill: dict[str, dict]) -> list[dict]`, `teardown(rds, *, target) -> None`, CLI `main(argv, rds=None, prod_db=None, drill_db=None)`.

- [ ] **Step 1: Failing tests** — `tests/unit/test_restore_drill.py` with a `FakeRDS` that records calls and reports clusters/instances as `creating` once, then `available`:

```python
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
    def __init__(self, existing: bool = False):
        self.calls: list[tuple[str, dict]] = []
        self.cluster_checks = 0
        self.instance_checks = 0
        self.existing = existing

    def describe_db_clusters(self, DBClusterIdentifier):
        self.calls.append(("describe_db_clusters", {"id": DBClusterIdentifier}))
        if DBClusterIdentifier == "clouder-prod-aurora":
            return {"DBClusters": [{
                "DBSubnetGroup": "subnets", "VpcSecurityGroups": [{"VpcSecurityGroupId": "sg-1"}],
                "LatestRestorableTime": datetime(2026, 10, 11, 13, 0, tzinfo=UTC),
                "DBClusterArn": "arn:prod",
            }]}
        if not self.existing and not any(c[0] == "restore_db_cluster_to_point_in_time" for c in self.calls):
            raise self.exceptions.DBClusterNotFoundFault({}, "x")
        self.cluster_checks += 1
        status = "creating" if self.cluster_checks < 2 else "available"
        return {"DBClusters": [{"Status": status, "DBClusterArn": "arn:drill",
                                "MasterUserSecret": {"SecretArn": "arn:secret"},
                                "HttpEndpointEnabled": self.cluster_checks > 2}]}

    def describe_db_instances(self, DBInstanceIdentifier):
        self.instance_checks += 1
        if not any(c[0] == "create_db_instance" for c in self.calls) and not self.existing:
            raise self.exceptions.DBInstanceNotFoundFault({}, "x")
        return {"DBInstances": [{"DBInstanceStatus": "creating" if self.instance_checks < 2 else "available"}]}

    def __getattr__(self, name):
        def call(**kw):
            self.calls.append((name, kw))
            return {}
        return call

    class exceptions:  # noqa: N801 — mirrors boto3's client.exceptions
        class DBClusterNotFoundFault(Exception):
            pass

        class DBInstanceNotFoundFault(Exception):
            pass


def _clock():
    t = [datetime(2026, 10, 11, 14, 0, tzinfo=UTC)]

    def now():
        t[0] += timedelta(seconds=30)
        return t[0]

    return now


def test_restore_targets_a_new_cluster_in_the_production_network() -> None:
    rds = FakeRDS()
    timeline = _load().restore(rds, source="clouder-prod-aurora", target="clouder-prod-aurora-drill",
                               now=_clock(), sleep=lambda s: None)

    (restore,) = [kw for name, kw in rds.calls if name == "restore_db_cluster_to_point_in_time"]
    assert restore["SourceDBClusterIdentifier"] == "clouder-prod-aurora"
    assert restore["DBClusterIdentifier"] == "clouder-prod-aurora-drill"
    assert restore["UseLatestRestorableTime"] is True
    assert restore["DBSubnetGroupName"] == "subnets" and restore["VpcSecurityGroupIds"] == ["sg-1"]
    assert restore["DeletionProtection"] is False
    (writer,) = [kw for name, kw in rds.calls if name == "create_db_instance"]
    assert writer["DBClusterIdentifier"] == "clouder-prod-aurora-drill"
    assert writer["DBInstanceClass"] == "db.serverless"
    assert any(name == "modify_db_cluster" and kw.get("ManageMasterUserPassword") for name, kw in rds.calls)
    assert any(name == "enable_http_endpoint" and kw["ResourceArn"] == "arn:drill" for name, kw in rds.calls)
    for key in ("requested", "cluster_available", "writer_available", "ready", "restore_point"):
        assert key in timeline
    assert timeline["rto_seconds"] > 0
    # Nothing mutating ever names the production cluster.
    for name, kw in rds.calls:
        if not name.startswith("describe"):
            assert "clouder-prod-aurora-drill" in str(kw) or kw.get("ResourceArn") == "arn:drill", name


def test_a_resumed_restore_does_not_create_twice() -> None:
    rds = FakeRDS(existing=True)
    _load().restore(rds, source="clouder-prod-aurora", target="clouder-prod-aurora-drill",
                    now=_clock(), sleep=lambda s: None)
    assert not any(name == "restore_db_cluster_to_point_in_time" for name, _ in rds.calls)
    assert not any(name == "create_db_instance" for name, _ in rds.calls)


def test_teardown_refuses_anything_but_a_drill_cluster() -> None:
    mod = _load()
    with pytest.raises(ValueError):
        mod.teardown(FakeRDS(), target="clouder-prod-aurora")
    rds = FakeRDS()
    mod.teardown(rds, target="clouder-prod-aurora-drill")
    names = [n for n, _ in rds.calls]
    assert names.index("delete_db_instance") < names.index("delete_db_cluster")
    (cluster,) = [kw for n, kw in rds.calls if n == "delete_db_cluster"]
    assert cluster["SkipFinalSnapshot"] is True


def test_compare_reports_counts_and_the_newest_row_gap() -> None:
    prod = {"clouder_tracks": {"rows": 10, "newest": "2026-10-11T13:05:00+00:00"}}
    drill = {"clouder_tracks": {"rows": 9, "newest": "2026-10-11T12:59:00+00:00"}}
    (row,) = _load().compare(prod, drill)
    assert row == {"table": "clouder_tracks", "prod_rows": 10, "drill_rows": 9, "missing_rows": 1,
                   "newest_gap_seconds": 360}
```

- [ ] **Step 2: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_restore_drill.py -q` → errors (script missing).

- [ ] **Step 3: Implement `scripts/restore_drill.py`**

```python
#!/usr/bin/env python3
"""Aurora restore drill: point-in-time restore into a new cluster, timed (docs/ops/aurora.md).

    .venv/bin/python scripts/restore_drill.py restore  --report drill.json   # agent or owner
    PYTHONPATH=src .venv/bin/python scripts/restore_drill.py verify --report drill.json  # owner: reads rows
    .venv/bin/python scripts/restore_drill.py teardown                       # owner: deletes the drill

`restore` restores the latest restorable time of the production cluster into a new one in
the same subnets and security group, adds a writer, turns on the managed master secret and
the Data API, and records a timeline. Re-running it continues a half-finished restore.
`verify` compares row counts and newest timestamps on both clusters. `teardown` deletes the
drill cluster without a final snapshot and refuses any identifier not ending in -drill.
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


def restore(rds: Any, *, source: str, target: str, now=lambda: datetime.now(UTC), sleep=time.sleep) -> dict:
    src = rds.describe_db_clusters(DBClusterIdentifier=source)["DBClusters"][0]
    timeline: dict[str, Any] = {"source": source, "target": target, "requested": now().isoformat(),
                                "restore_point": src["LatestRestorableTime"].isoformat()}
    started = datetime.fromisoformat(timeline["requested"])
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

    def cluster() -> dict:
        return rds.describe_db_clusters(DBClusterIdentifier=target)["DBClusters"][0]

    _wait(lambda: cluster()["Status"] == "available", sleep)
    timeline["cluster_available"] = now().isoformat()
    writer = f"{target}-writer"
    try:
        rds.describe_db_instances(DBInstanceIdentifier=writer)
    except rds.exceptions.DBInstanceNotFoundFault:
        rds.create_db_instance(DBInstanceIdentifier=writer, DBClusterIdentifier=target,
                               DBInstanceClass="db.serverless", Engine="aurora-postgresql")
    _wait(lambda: rds.describe_db_instances(DBInstanceIdentifier=writer)["DBInstances"][0]["DBInstanceStatus"] == "available", sleep)
    timeline["writer_available"] = now().isoformat()
    info = cluster()
    if not info.get("MasterUserSecret"):
        rds.modify_db_cluster(DBClusterIdentifier=target, ManageMasterUserPassword=True, ApplyImmediately=True)
    rds.enable_http_endpoint(ResourceArn=info["DBClusterArn"])
    _wait(lambda: bool(cluster().get("HttpEndpointEnabled")) and bool(cluster().get("MasterUserSecret")), sleep)
    ready = now()
    timeline["ready"] = ready.isoformat()
    timeline["rto_seconds"] = int((ready - started).total_seconds())
    timeline["cluster_arn"] = info["DBClusterArn"]
    timeline["secret_arn"] = cluster()["MasterUserSecret"]["SecretArn"]
    return timeline
```

(…continue with `snapshot_counts(db) -> dict[str, dict]` running `SELECT count(*) AS rows, max(<col>)::text AS newest FROM <table>` per table, `compare(prod, drill)`, `teardown(rds, *, target)` with the `-drill` guard (delete instance with `SkipFinalSnapshot=True`, wait until the instance is gone, then delete the cluster with `SkipFinalSnapshot=True`), and `main` with subcommands `restore` (writes the timeline to `--report`), `verify` (reads `--report`, builds Data API clients for prod from `AURORA_CLUSTER_ARN`/`AURORA_SECRET_ARN` and for the drill from the report, prints the comparison and RPO = restore point vs. newest drill timestamp, appends it to the report), `teardown`. Write each function so the tests in Step 1 pass; ruff-format; keep lines ≤ 100.)

- [ ] **Step 4: Run the tests** → all pass; `ruff check scripts tests`; `ruff format --check`.
- [ ] **Step 5: Commit** (e.g. `feat(ops): Aurora restore drill script`).

---

### Task 2: Run the drill

- [ ] **Step 1: Restore (agent)** — `.venv/bin/python scripts/restore_drill.py restore --report <scratchpad>/aurora-drill-2026-10-11.json` (in the background; it polls every 30 s). Record the timeline.
- [ ] **Step 2: Owner — verify and tear down.** Stop and give the owner:

```bash
cd <main checkout> && git fetch && git switch --detach origin/docs/aurora-restore-drill
export AURORA_CLUSTER_ARN=$(aws rds describe-db-clusters --db-cluster-identifier clouder-prod-aurora --query 'DBClusters[0].DBClusterArn' --output text)
export AURORA_SECRET_ARN=$(aws rds describe-db-clusters --db-cluster-identifier clouder-prod-aurora --query 'DBClusters[0].MasterUserSecret.SecretArn' --output text)
PYTHONPATH=src .venv/bin/python scripts/restore_drill.py verify --report <report path>
.venv/bin/python scripts/restore_drill.py teardown
```

and ask for the `verify` output.

### Task 3: Write it down

- [ ] `docs/postmortems/2026-10-11-game-day-aurora-restore.md` (blameless game-day format: goal, setup, timeline, what worked, what surprised, RTO/RPO, follow-ups) and an index row in `docs/postmortems/README.md`.
- [ ] `docs/ops/failure-modes.md`: replace both "not rehearsed yet" with the measured RTO (request → Data API ready) and observed RPO; delete the "Aurora restore has not been rehearsed" gap bullet.
- [ ] `docs/ops/aurora.md`: the restore paragraph points at `scripts/restore_drill.py` and lists the repoint steps (the Terraform cluster identifier/ARN variables and the secret).
- [ ] README *Production readiness* → Reliability: `[failure modes](…) with RPO/RTO` → `… with RPO/RTO, an Aurora point-in-time restore rehearsed on 2026-10-11 (<RTO>)`; `five blameless` → the current count (six after phase 1) stays unless a game-day row counts — it does not (it is a drill, listed separately in the index).
- [ ] Guards + full suite; commit; PR; merge; deploy (docs only).
- [ ] Board: phase 5 → `done` with RTO/RPO.

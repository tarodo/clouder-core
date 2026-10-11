# Telemetry Retention, Lake Protection and Data-Subject Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pseudonymous telemetry is kept 400 days in bronze and silver (it was kept forever), the analytics lake cannot be emptied by a Terraform destroy, and one command gives a user a copy of everything CLOUDER holds about them; `docs/privacy.md` states the legal basis and the data-subject rights with the tools that serve them.

**Architecture:** An S3 lifecycle rule expires `bronze/events/` after 400 days (and Firehose error records after 30). A dbt post-hook on `silver.events` deletes partitions older than 400 days before the newest one — anchored on `max(dt)`, not on today, so CI fixtures never age out — and `gold.fct_play` follows on its nightly rebuild. `collector.user_export` walks the same catalog-derived table graph as `user_deletion` (every `*user_id` column, foreign-key children), redacts credential columns, and adds cover keys and the user's silver events from Athena.

**Tech Stack:** Terraform, dbt (Athena prod / DuckDB CI), Python 3.12 + Data API client, Athena, pytest (unit + real PostgreSQL).

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §9 Europe (retention, legal basis, DSAR), §6 S3 (`force_destroy`), §0.3 phase 4. Evidence: `docs/privacy.md` lists bronze telemetry as "Kept"; `infra/telemetry.tf` has `force_destroy = true` on `clouder-prod-analytics-lake` and only an IA transition for `bronze/`; `scripts/delete_user.py` exists, an export does not.

## Global Constraints

- Worktree `../clouder-core-loop`, branch `feat/data-retention-dsar` from `origin/main`. Tools from the main checkout's `.venv/bin/`. Real-PostgreSQL tests on a throwaway `postgres:16` at port 55511.
- Retention: **400 days** for telemetry in bronze and silver; **30 days** for Firehose error records.
- Athena: never bind `'YYYY-MM-DD'` literals as parameters — inline validated literals (CLAUDE.md gotcha 13). User ids are validated UUIDs before they go into SQL or S3 prefixes (as in `user_deletion._checked`).
- Runtime DB access only through the Data API; the export script runs from an operator machine like `delete_user.py`.
- No money figures; English in the repo; commit messages from `caveman:caveman-commit`; no AI attribution.
- `README.md` counts are guarded (Terraform resources: unchanged — lifecycle rules live inside an existing resource).

## Review Focus

1. **The retention delete must not erase the analytics history in CI or prod by accident** — anchored on `max(dt)` of the table; an empty table skips the delete. Pinned in Task 1 (fixture row older than the window is gone, the rest stays).
2. **The S3 rule and the dbt window must agree** (400 days both) — a guard test compares them.
3. **Credential columns never reach the export file** (`*_enc`, `*token*`, `*hash*`, `*secret*`, `*password*`). Pinned in Task 2 (unit + real PostgreSQL).
4. **A user's children rows (category_tracks, triage_bucket_tracks, playlist_tracks, …) are exported**, not just rows with a `user_id` column — same graph as deletion. Pinned in Task 2 (DB test against the deletion seed).
5. **Athena result paging** (header row on the first page only, `NextToken`) for users with more than 1,000 events. Pinned in Task 2 (unit test with a two-page fake).

---

### Task 1: Retention and lake protection

**Files:**
- Modify: `infra/telemetry.tf` (lifecycle rules, `force_destroy`)
- Modify: `dbt/dbt_project.yml` (var `events_retention_days: 400`), `dbt/models/silver/events.sql` (post-hook), `dbt/macros/retention.sql` (new), `dbt/seeds/fixtures/bronze_events.csv` (one old row), `dbt/tests/assert_events_within_retention.sql` (new)
- Create: `tests/unit/test_retention_infra.py`

- [ ] **Step 1: Failing guard test** — `tests/unit/test_retention_infra.py`:

```python
"""Telemetry is kept 400 days in bronze and silver; the lake survives a destroy (privacy.md)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TELEMETRY = (ROOT / "infra" / "telemetry.tf").read_text()


def _rule(rule_id: str) -> str:
    m = re.search(rf'id\s*=\s*"{rule_id}"(.*?)\n  \}}', TELEMETRY, re.S)
    assert m, rule_id
    return m.group(1)


def test_bronze_events_expire_with_the_silver_window() -> None:
    days = int(re.search(r"expiration \{ days = (\d+) \}", _rule("expire-bronze-events")).group(1))
    assert 'prefix = "bronze/events/"' in _rule("expire-bronze-events")
    dbt_days = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text())["vars"][
        "events_retention_days"
    ]
    assert days == dbt_days == 400


def test_firehose_error_records_expire() -> None:
    rule = _rule("expire-firehose-errors")
    assert 'prefix = "bronze/_errors/"' in rule and "expiration { days = 30 }" in rule


def test_silver_events_delete_past_the_window() -> None:
    model = (ROOT / "dbt" / "models" / "silver" / "events.sql").read_text()
    assert "delete_expired_events()" in model


def test_lake_bucket_survives_a_destroy() -> None:
    bucket = TELEMETRY[TELEMETRY.index('resource "aws_s3_bucket" "analytics_lake"') :]
    bucket = bucket[: bucket.index("\n}\n")]
    assert re.search(r"force_destroy\s*=\s*false", bucket)
```

- [ ] **Step 2: Run** — `PYTHONPATH=src .venv/bin/pytest tests/unit/test_retention_infra.py -q` → Expected: 4 failed.

- [ ] **Step 3: Terraform** — in `infra/telemetry.tf`:
  - bucket: replace the comment and `force_destroy = true` with
    ```hcl
      # Holds the only copy of telemetry history (silver/gold are rebuilt from it within the
      # retention window): a destroy must fail instead of emptying it.
      bucket        = "clouder-prod-analytics-lake"
      force_destroy = false
    ```
  - lifecycle: add two rules after `expire-catalog-snapshots`:
    ```hcl
      rule {
        # Pseudonymous telemetry: 400 days, the same window silver.events keeps
        # (dbt var events_retention_days; docs/privacy.md).
        id     = "expire-bronze-events"
        status = "Enabled"
        filter { prefix = "bronze/events/" }
        expiration { days = 400 }
      }

      rule {
        # Records Firehose could not convert; only useful while debugging a delivery.
        id     = "expire-firehose-errors"
        status = "Enabled"
        filter { prefix = "bronze/_errors/" }
        expiration { days = 30 }
      }
    ```

- [ ] **Step 4: dbt** —
  - `dbt/dbt_project.yml` `vars:` add
    ```yaml
      # Telemetry retention in silver (and gold, rebuilt from it), counted back from the
      # newest partition; the S3 rule on bronze/events/ uses the same number (privacy.md).
      events_retention_days: 400
    ```
  - `dbt/macros/retention.sql`:
    ```sql
    {#- Deletes silver partitions older than the retention window, counted back from the
        newest partition (in production that is today; in CI it is the newest fixture, so
        fixtures never age out). An empty table deletes nothing. The cutoff is an inlined
        date literal: Athena mis-parses bound 'YYYY-MM-DD' parameters. -#}
    {% macro delete_expired_events() %}
      {%- if execute -%}
        {%- set rel = this.render_pure() if target.type == 'athena' else this -%}
        {%- set newest = run_query("select max(dt) from " ~ rel).columns[0].values()[0] -%}
        {%- if newest -%}
          {%- set cutoff = (modules.datetime.date.fromisoformat(newest | string) - modules.datetime.timedelta(days=var('events_retention_days'))).isoformat() -%}
          delete from {{ rel }} where dt < '{{ cutoff }}'
        {%- else -%}
          select 1
        {%- endif -%}
      {%- else -%}
        select 1
      {%- endif -%}
    {% endmacro %}
    ```
  - `dbt/models/silver/events.sql` config: replace the `post_hook=(...)` with
    ```python
        post_hook=["{{ delete_expired_events() }}"] + ([
            "optimize {{ this.render_pure() }} rewrite data using bin_pack",
            "vacuum {{ this.render_pure() }}",
        ] if target.type == 'athena' else []),
    ```
  - `dbt/seeds/fixtures/bronze_events.csv`: append one event 401+ days before the newest fixture dt, for user `u1`, event name `playback_play`, e.g. `e_old,s_old,u1,2025-08-01,2025-08-01T10:00:00+00:00,2025-08-01T10:00:00.000Z,playback_play,t1,triage_player,300000` (read the header first and match its column order).
  - `dbt/tests/assert_events_within_retention.sql`:
    ```sql
    -- No silver event is older than the retention window (docs/privacy.md).
    select e.event_id
    from {{ ref('events') }} e
    cross join (select max(dt) as newest from {{ ref('events') }}) m
    where e.dt < {{ dt_minus_days('m.newest', var('events_retention_days')) }}
    ```

- [ ] **Step 5: Run dbt on DuckDB and the guards** —
  ```bash
  python3 -m venv /tmp/dbt-venv-$$ && /tmp/dbt-venv-$$/bin/pip install -q -r dbt/requirements.txt
  cd dbt && DBT_PROFILES_DIR=. /tmp/dbt-venv-$$/bin/dbt seed --target ci && DBT_PROFILES_DIR=. /tmp/dbt-venv-$$/bin/dbt run --target ci --empty && DBT_PROFILES_DIR=. /tmp/dbt-venv-$$/bin/dbt build --target ci --full-refresh --exclude resource_type:seed
  ```
  (Use the scratchpad for the venv instead of `/tmp` if the session has one; if `.venv-dbt` exists in the main checkout, use it.) Expected: PASS, including `assert_events_within_retention` and `assert_deleted_users_absent`; then `PYTHONPATH=src .venv/bin/pytest tests/unit/test_retention_infra.py -q` → 4 passed; `terraform fmt -check && terraform validate`.

- [ ] **Step 6: Commit** (e.g. `feat(privacy): keep telemetry 400 days`)

---

### Task 2: Export everything about one user

**Files:**
- Create: `src/collector/user_export.py`, `scripts/export_user.py`
- Create: `tests/unit/test_user_export.py`, `tests/db/test_user_export_pg.py`

**Interfaces:**
- Consumes: `collector.user_deletion._FOREIGN_KEYS_SQL`, `_USER_COLUMNS_SQL`, `_checked`, `TOMBSTONE_PREFIX` (unchanged).
- Produces:
  - `export_aurora(data_api, user_id) -> dict[str, list[dict]]` — keys are table names, or `table.column` for `*_by_user_id` audit references.
  - `redact(row: dict) -> dict` — values of credential columns → `"[redacted]"`.
  - `list_covers(s3, bucket, user_id) -> list[str]` — current object keys under `covers/<uuid>/`.
  - `export_events(athena, *, user_id, workgroup, sleep=time.sleep) -> list[dict]` — the user's rows in `clouder_silver.events`, oldest first.

- [ ] **Step 1: Failing unit tests** — `tests/unit/test_user_export.py`:

```python
from __future__ import annotations

import pytest

from collector import user_export

UID = "11111111-1111-1111-1111-111111111111"


def test_credentials_are_redacted() -> None:
    row = {
        "user_id": UID,
        "access_token_enc": b"x",
        "refresh_token_hash": "h",
        "data_key_enc": b"k",
        "scope": "playlist-read",
    }
    out = user_export.redact(row)
    assert out["access_token_enc"] == out["refresh_token_hash"] == out["data_key_enc"] == "[redacted]"
    assert out["scope"] == "playlist-read" and out["user_id"] == UID


class FakeAthena:
    def __init__(self, pages):
        self.pages = pages
        self.queries = []

    def start_query_execution(self, **kw):
        self.queries.append(kw)
        return {"QueryExecutionId": "q"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId, NextToken=None, MaxResults=1000):
        page = self.pages[int(NextToken or 0)]
        nxt = int(NextToken or 0) + 1
        return {"ResultSet": {"Rows": page}, **({"NextToken": str(nxt)} if nxt < len(self.pages) else {})}


def _row(*values):
    return {"Data": [{"VarCharValue": v} for v in values]}


def test_events_page_through_athena_results() -> None:
    athena = FakeAthena(
        [
            [_row("event_id", "event_name"), _row("e1", "playback_play")],
            [_row("e2", "playback_pause")],
        ]
    )

    rows = user_export.export_events(athena, user_id=UID, workgroup="wg", sleep=lambda s: None)

    assert rows == [
        {"event_id": "e1", "event_name": "playback_play"},
        {"event_id": "e2", "event_name": "playback_pause"},
    ]
    sql = athena.queries[0]["QueryString"]
    assert f"user_id = '{UID}'" in sql and "clouder_silver.events" in sql
    assert athena.queries[0]["WorkGroup"] == "wg"


def test_a_non_uuid_never_reaches_sql() -> None:
    with pytest.raises(ValueError):
        user_export.export_events(FakeAthena([[]]), user_id="x' OR '1'='1", workgroup="wg")
```

- [ ] **Step 2: Run** → errors (module missing).

- [ ] **Step 3: Implement `src/collector/user_export.py`**

```python
"""Everything CLOUDER holds about one user, for an access or portability request.

Walks the same catalog-derived table graph as user_deletion (every `*user_id`
column, foreign-key children), so a new user-owned table is exported without code
changes. Credential columns are redacted: the export is for the person, not a key
backup. Adds the user's playlist cover keys and their telemetry from silver.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import Any

from collector.user_deletion import _FOREIGN_KEYS_SQL, _USER_COLUMNS_SQL, _checked

_SECRET = re.compile(r"(_enc$|token|hash|secret|password)")


def redact(row: dict[str, Any]) -> dict[str, Any]:
    return {k: ("[redacted]" if _SECRET.search(k) else v) for k, v in row.items()}


def export_aurora(data_api: Any, user_id: str) -> dict[str, list[dict[str, Any]]]:
    children: dict[str, list[tuple[str, str, str]]] = {}
    for fk in data_api.execute(_FOREIGN_KEYS_SQL):
        if fk["width"] == 1 and fk["on_delete"] != "n":
            children.setdefault(fk["parent"], []).append(
                (fk["child"], fk["child_col"], fk["parent_col"])
            )
    out: dict[str, list[dict[str, Any]]] = {}

    def collect(table: str, where: str, key: str) -> None:
        rows = data_api.execute(f'SELECT * FROM "{table}" WHERE {where}', {"user_id": user_id})
        if rows:
            out.setdefault(key, []).extend(redact(r) for r in rows)
        for child, col, ref in children.get(table, []):
            collect(child, f'"{col}" IN (SELECT "{ref}" FROM "{table}" WHERE {where})', child)

    collect("users", '"id" = :user_id', "users")
    for r in data_api.execute(_USER_COLUMNS_SQL):
        table, col = r["tbl"], r["col"]
        if col.endswith("_by_user_id"):
            rows = data_api.execute(f'SELECT * FROM "{table}" WHERE "{col}" = :user_id', {"user_id": user_id})
            if rows:
                out[f"{table}.{col}"] = [redact(x) for x in rows]
        else:
            collect(table, f'"{col}" = :user_id', table)
    return out


def list_covers(s3: Any, bucket: str, user_id: str) -> list[str]:
    prefix = f"covers/{_checked(user_id)}/"
    return [
        o["Key"]
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for o in page.get("Contents", [])
    ]


def export_events(
    athena: Any,
    *,
    user_id: str,
    workgroup: str,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    user_id = _checked(user_id)  # inlined below: Athena takes no parameters in this path
    qid = athena.start_query_execution(
        QueryString=(
            "SELECT * FROM clouder_silver.events "
            f"WHERE user_id = '{user_id}' ORDER BY ts_client, event_id"
        ),
        WorkGroup=workgroup,
    )["QueryExecutionId"]
    while True:
        state = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]["State"]
        if state not in ("QUEUED", "RUNNING"):
            break
        sleep(2)
    if state != "SUCCEEDED":
        raise RuntimeError(f"Athena export of events {state}")
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    token: str | None = None
    while True:
        kw = {"QueryExecutionId": qid, "MaxResults": 1000, **({"NextToken": token} if token else {})}
        page = athena.get_query_results(**kw)
        for raw in page["ResultSet"]["Rows"]:
            values = [d.get("VarCharValue") for d in raw["Data"]]
            if header is None:
                header = values
                continue
            rows.append(dict(zip(header, values, strict=True)))
        token = page.get("NextToken")
        if not token:
            return rows
```

(Run `ruff format` after; wrap the long lines it flags.)

- [ ] **Step 4: Run the unit tests** → 3 passed.

- [ ] **Step 5: DB test** — `tests/db/test_user_export_pg.py`:

```python
"""export_aurora on real PostgreSQL: every owned and child row of the user, nobody else's."""

from __future__ import annotations

import uuid

from test_user_deletion_pg import _CATALOG, _OWNED, _seed_user

from collector.user_export import export_aurora


def test_exports_every_owned_table_and_nothing_of_others(pg) -> None:
    for sql in _CATALOG:
        pg.execute(sql)
    me, other = str(uuid.uuid4()), str(uuid.uuid4())
    _seed_user(pg, me, "a_")
    _seed_user(pg, other, "b_")

    out = export_aurora(pg, me)

    assert {t: len(out.get(t, [])) for t in _OWNED} == _OWNED
    flat = [row for rows in out.values() for row in rows]
    assert not any(other in str(v) for row in flat for v in row.values())
    (token,) = out["user_vendor_tokens"]
    assert token["access_token_enc"] == token["data_key_enc"] == "[redacted]"
    (session,) = out["user_sessions"]
    assert session["refresh_token_hash"] == "[redacted]"
    assert "clouder_label_enrichment_runs.created_by_user_id" in out
```

Read `tests/db/test_user_deletion_pg.py` first: if `_CATALOG` rows already exist after its own test (truncate covers canonical tables via the `pg` fixture), keep as is; if the audit rows need cleanup, call its `_cleanup`. Run on postgres:16 (migrate, then `pytest tests/db/test_user_export_pg.py tests/db/test_user_deletion_pg.py -q`). Expected: pass.

- [ ] **Step 6: CLI `scripts/export_user.py`** — mirror `scripts/delete_user.py` (read it; reuse its `require`, `_data_api`, `REGION`):
  - args `--user-id` (validated UUID), `--out` (required path), `--cluster-arn`, `--secret-arn`, `--database` (default `postgres`), `--raw-bucket`, `--workgroup` (default `clouder-prod-analytics`? read the real workgroup name from `infra/analytics_routes.tf`/`variables.tf` default), and env fallbacks like delete_user;
  - writes `{"user_id", "exported_at", "aurora", "covers", "events"}` as JSON (`default=str`, `indent=2`) to `--out` with mode 0600, prints only the path and counts per section.
  - Unit test in `tests/unit/test_user_export.py`: `main` with injected fakes writes the file with 0600 and prints no row values (inject via a `clients` parameter like `rotate_jwt_key.main(ssm=...)`).

- [ ] **Step 7: Commit** (e.g. `feat(privacy): export one user's data`)

---

### Task 3: privacy.md and README

**Files:** `docs/privacy.md`, `README.md` (Production readiness → Data governance line)

- [ ] **Step 1: Retention table** — rows:
  - `S3 lake bronze/events/`: Retention → `400 days (lifecycle rule; infrequent access after 90)`.
  - `Iceberg clouder_silver.events, clouder_gold.fct_play`: Retention → `400 days back from the newest partition (dbt post-hook), and until the user is deleted`.
  - add `S3 lake bronze/_errors/` — `Records Firehose could not convert (may include the pseudonymous fields)` — `Debugging a delivery` — `30 days`.
- [ ] **Step 2: "What is left after deletion"** — bronze bullet: replace `Bronze telemetry keeps the raw, pseudonymous events. … rewriting the affected Parquet partitions.` with `**Bronze telemetry** keeps the raw, pseudonymous events for up to 400 days. Once the \`users\` row is gone, nothing links the user id to a person, and every table built from bronze excludes it (tombstone).`
- [ ] **Step 3: New sections** after the deletion section:

```markdown
## Exporting a user's data (access and portability)

`scripts/export_user.py` writes one JSON file with everything CLOUDER holds about a user: their rows in every Aurora table the deletion walks (same catalog-derived graph, children included), audit references to them, their playlist cover keys and their telemetry from `clouder_silver.events`. Credential columns (encrypted OAuth tokens, refresh-token hashes) are redacted. The file is created with mode 0600; send it to the user over a private channel and delete it afterwards.

```bash
PYTHONPATH=src .venv/bin/python scripts/export_user.py --user-id <uuid> --out export-<uuid>.json
```

Telemetry from the last day may still be only in bronze (silver is built nightly).

## Legal basis and data-subject rights

CLOUDER is run by one person for a closed group of DJs who asked to use it.

| Purpose | Data | Basis (GDPR Art. 6(1)) |
|---|---|---|
| Account and sign-in | `users`, `user_sessions` | (b) needed to provide the service the user asked for |
| Curation and publishing | the overlay tables, `user_vendor_tokens`, covers | (b) |
| Account security: refresh-token rotation, replay detection, logs | sessions (IP, user agent), CloudWatch | (f) legitimate interest in keeping accounts safe |
| Listening analytics shown back to the user | pseudonymous telemetry, 400 days | (f) the cards are part of the product; no third party sees the data |

| Right | How |
|---|---|
| Access, portability (Art. 15, 20) | `scripts/export_user.py` — one JSON file |
| Erasure (Art. 17) | `scripts/delete_user.py` — Aurora, covers, lake (tombstone + Iceberg deletes) |
| Rectification (Art. 16) | Display name and email come from Spotify at sign-in; the owner corrects them on request |
| Objection to analytics (Art. 21) | No in-app switch yet; on request the owner tombstones the user (`purge_lake`), which keeps their events out of silver and gold |

**Known gaps.** There is no privacy notice inside the app yet: users learn the above from the owner and this page. All data is in AWS us-east-1; for users in the EU that is a transfer outside the EEA, which a public launch would need to address (an EU region or a documented transfer mechanism). There is no consent banner because the app sets no third-party cookies and runs no third-party tracking.
```

- [ ] **Step 4: README** — Production readiness, **Data governance**: `documented retention;` → `telemetry kept 400 days;` and `one command erases a user from Aurora, S3 and the Iceberg tables` → `one command exports everything about a user and one erases them from Aurora, S3 and the Iceberg tables`.
- [ ] **Step 5: Guards, full suite, commit** (e.g. `docs(privacy): legal basis, rights, retention`).

---

### Task 4: Ship and verify

- [ ] PR (title/body from `caveman:caveman-commit`); checks green; plan: `aws_s3_bucket.analytics_lake` and `aws_s3_bucket_lifecycle_configuration.analytics_lake` updated in place, Lambda code updated, **0 to destroy**.
- [ ] Merge, deploy green; `aws s3api get-bucket-lifecycle-configuration --bucket clouder-prod-analytics-lake` shows both new rules.
- [ ] Run the transform by hand; the CodeBuild log shows the `delete from … where dt < '<cutoff>'` post-hook succeeding (nothing older than 400 days exists yet, so 0 rows).
- [ ] Owner (optional): run `export_user.py` for their own user id and look at the file (the agent has no `rds-data` read access).
- [ ] Board: phase 4 → `done` with plan path and PR.

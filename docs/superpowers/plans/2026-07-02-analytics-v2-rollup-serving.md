# Analytics v2 — Rollup Runner + Serving Implementation Plan (Plan 3 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Materialize the Plan-2 marts on a daily schedule and serve them. A new scheduled `analytics-rollup` Lambda runs the Trino sessionization SQL as Athena `INSERT INTO` (idempotent per-partition overwrite of the last 3 days), and the existing `analytics-api` Lambda is rewritten to serve `mart_user_daily` + `fact_session` for the per-user daily dashboard — deleting the 5 dead dashboards (triage/taste/funnel/playback/ops) whose SQL queries the removed dbt gold tables.

**Architecture:** Two Lambdas, two least-privilege roles (§13): `analytics-rollup` (write: Athena + Glue partition write + S3 read bronze/write marts, EventBridge daily) and read-only `analytics-api` (serve). The rollup composes `analytics_rollup.sessions_sql/mart_sql(TRINO)`; the serving handler reads the built marts. Both are unit-tested by mocking boto3 (Athena/S3), the codebase's established analytics-test pattern.

**Tech Stack:** Python 3 (boto3 mocked in tests), Trino/Athena SQL, Terraform (Lambda + EventBridge + IAM), pytest.

**Cadence (decided):** EventBridge daily ~03:00 UTC; recompute the last 3 `dt` partitions (idempotent). Bronze scan reads last 4 days (3 + 1 for cross-midnight sessions starting late the prior day); output filtered to the 3 target dts.

**Plan series:** Plans 1 (envelope) & 2 (marts) DONE. This is Plan 3. Plan 4 = frontend dashboard (deletes the 5 old dashboard pages, builds the per-user daily view). Plan F = beatport→clouder rename. Spec: `docs/superpowers/specs/2026-06-30-analytics-v2-user-daily-design.md`.

**Worktree:** branch `feat/analytics-v2`. pytest = `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`. `PYTHONPATH=src` set by pytest.ini.

---

## Key mechanics

**Athena partition overwrite (Hive external table):** Athena `INSERT INTO` appends. To make a daily run idempotent, the runner first deletes the S3 objects under each target partition prefix (`marts/<table>/dt=<d>/`) via boto3 S3, then `INSERT INTO`. Partition projection is already enabled (Plan 2), so no `ADD PARTITION`/`MSCK` is needed — Athena reads any dt in the projection range.

**Column order for INSERT INTO:** Athena requires the partition column (`dt`) LAST in the SELECT, and data columns in Glue-table order. The runner wraps each builder in an outer projection: `INSERT INTO <table> SELECT <data cols in Glue order>, dt FROM (<builder(TRINO, source)>) WHERE dt IN (<target dts>)`.

**Date literals (gotcha #13):** all `dt` values are computed in Python as validated `YYYY-MM-DD` strings and inlined into the SQL — never bound via ExecutionParameters (Athena mis-parses a bound date string as arithmetic).

**bronze scan window:** the runner passes `source="(SELECT * FROM bronze_events WHERE dt >= '<lookback_start>')"` into the builders so only the needed partitions are scanned.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `src/collector/analytics_rollup.py` | add `ts_start`/`ts_end` to `sessions_sql`; expose ordered column lists | Modify |
| `tests/unit/test_analytics_rollup.py` | assert the new fact_session columns | Modify |
| `src/collector/analytics_rollup_runner.py` | scheduled Athena INSERT-INTO runner (S3 overwrite + inline dts) | Create |
| `tests/unit/test_analytics_rollup_runner.py` | mock Athena+S3, assert SQL shape / S3 deletes / target dts | Create |
| `src/collector/analytics_handler.py` | replace `_ROUTE_QUERIES` with user-daily/sessions; add `user_id` param | Modify |
| `tests/unit/test_analytics_handler.py` | rewrite for the new routes | Modify |
| `scripts/generate_openapi.py` | swap the 5 `_analytics_route` calls for the 2 new ones | Modify |
| `infra/analytics_routes.tf` | update `local.analytics_routes`; serving IAM read on marts | Modify |
| `infra/analytics_rollup.tf` | new rollup Lambda + write role + EventBridge daily | Create |

---

### Task 1: Extend `sessions_sql` with `ts_start` / `ts_end` + ordered column lists

**Files:** `src/collector/analytics_rollup.py`, `tests/unit/test_analytics_rollup.py`

- [ ] **Step 1: Add the fact_session assertion (TDD)**

In `tests/unit/test_analytics_rollup.py`, update `_sessions` cols to include `ts_start`,`ts_end` (append after `dt`... — NO: match the SELECT order you choose). Add to `test_fact_session_metrics`:
```python
    assert t0["ts_start"] == "2026-06-29T10:00:00Z" or t0["ts_start"].startswith("2026-06-29 10:00:00")
    assert t0["ts_end"].startswith("2026-06-29 10:02:00") or t0["ts_end"] == "2026-06-29T10:02:00Z"
```
(DuckDB casts the ISO string to TIMESTAMP then back to VARCHAR as `YYYY-MM-DD HH:MM:SS`; assert on that shape. The prod Trino path uses `cast(... as varchar)` similarly — the exact string format is not load-bearing, it's a drill-down display value.)

Update the `_sessions` helper's `cols` list to the new projection order: `["user_id","activity_type","session_seq","dt","ts_start","ts_end","duration_ms","tracks_listened","tracks_promoted","tracks_deleted"]`.

- [ ] **Step 2: Run → fails** (`ts_start` KeyError).
Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_rollup.py -q`

- [ ] **Step 3: Add ts_start/ts_end to `sessions_sql`**

In `sessions_sql`, add to the SELECT (after `dt`): `cast(min(ts) as varchar) AS ts_start, cast(max(ts) as varchar) AS ts_end`. Expose a module constant `FACT_SESSION_COLUMNS = ["user_id","activity_type","session_seq","ts_start","ts_end","duration_ms","tracks_listened","tracks_promoted","tracks_deleted"]` (the Glue data-column order, dt excluded — used by the runner's INSERT) and `MART_USER_DAILY_COLUMNS = ["user_id","activity_type","sessions","avg_tracks_listened","avg_tracks_promoted","avg_tracks_deleted","p50_duration_ms","p90_duration_ms","p50_time_per_track_ms","p90_time_per_track_ms"]`.

- [ ] **Step 4: Run → passes.** Then full file: `pytest tests/unit/test_analytics_rollup.py -q`.

- [ ] **Step 5: Commit**
```bash
git add src/collector/analytics_rollup.py tests/unit/test_analytics_rollup.py
git commit -m "$(cat <<'EOF'
feat(analytics): project ts_start/ts_end + ordered column lists

fact_session gains ts_start/ts_end for drill-down; FACT_SESSION_COLUMNS
and MART_USER_DAILY_COLUMNS (Glue order) drive the rollup INSERT.
EOF
)"
```

---

### Task 2: The scheduled rollup runner

**Files:** `src/collector/analytics_rollup_runner.py` (create), `tests/unit/test_analytics_rollup_runner.py` (create)

- [ ] **Step 1: Write the test (mock Athena + S3)**

Create `tests/unit/test_analytics_rollup_runner.py`:
```python
from __future__ import annotations
import datetime as dt
from unittest.mock import MagicMock
import pytest
from collector import analytics_rollup_runner as r


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ATHENA_DATABASE", "clouder_analytics")
    monkeypatch.setenv("ATHENA_WORKGROUP", "wg")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://lake/athena-results/")
    monkeypatch.setenv("ANALYTICS_LAKE_BUCKET", "lake")


def _athena_ok():
    a = MagicMock()
    a.start_query_execution.return_value = {"QueryExecutionId": "q1"}
    a.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
    return a


def test_target_dts_are_last_3_days():
    assert r._target_dts(dt.date(2026, 6, 30)) == ["2026-06-28", "2026-06-29", "2026-06-30"]


def test_lookback_start_is_one_day_before_window():
    assert r._lookback_start(dt.date(2026, 6, 30)) == "2026-06-27"


def test_run_overwrites_partitions_then_inserts():
    athena, s3 = _athena_ok(), MagicMock()
    s3.list_objects_v2.return_value = {"Contents": [{"Key": "marts/mart_user_daily/dt=2026-06-30/f.parquet"}]}
    r.run(dt.date(2026, 6, 30), athena_client=athena, s3_client=s3)

    # S3 partitions deleted before insert: 2 tables x 3 dts = 6 prefixes listed
    assert s3.list_objects_v2.call_count == 6
    assert s3.delete_objects.called
    # one INSERT per table (2), each mentioning INSERT INTO + a validated date + WHERE dt IN
    inserts = [c.kwargs["QueryString"] for c in athena.start_query_execution.call_args_list]
    assert len(inserts) == 2
    for q in inserts:
        assert q.strip().upper().startswith("INSERT INTO")
        assert "2026-06-30" in q and "2026-06-27" in q  # target + lookback inlined
        assert "?" not in q                              # no bound params (gotcha #13)


def test_bad_date_never_reaches_sql():
    # dates are Python-formatted, never user input — but assert the guard exists
    with pytest.raises(ValueError):
        r._validate_dt("2026-6-30")  # not zero-padded / not YYYY-MM-DD
```

- [ ] **Step 2: Run → fails** (module missing).

- [ ] **Step 3: Implement `analytics_rollup_runner.py`**

Create it with: `_DATE_RE`/`_validate_dt`, `_target_dts(today)` (returns `[today-2, today-1, today]` as `YYYY-MM-DD`), `_lookback_start(today)` (`today-3`), `create_default_athena_client`/`create_default_s3_client` (lazy boto3), `_delete_partition(s3, bucket, prefix)` (list_objects_v2 + delete_objects, paginated), `_execute(athena, sql)` (start + poll SUCCEEDED/FAILED, raise on non-success — mirror `analytics_handler._run_athena` minus result fetch), and `run(today, *, athena_client=None, s3_client=None)`:

```python
def run(today, *, athena_client=None, s3_client=None):
    athena = athena_client or create_default_athena_client()
    s3 = s3_client or create_default_s3_client()
    bucket = os.environ["ANALYTICS_LAKE_BUCKET"]
    dts = _target_dts(today)                 # validated YYYY-MM-DD
    lookback = _lookback_start(today)
    source = f"(SELECT * FROM bronze_events WHERE dt >= '{lookback}')"
    dt_list = ", ".join(f"'{d}'" for d in dts)
    targets = [
        ("mart_user_daily", mart_sql(TRINO, source=source), MART_USER_DAILY_COLUMNS),
        ("fact_session",    sessions_sql(TRINO, source=source), FACT_SESSION_COLUMNS),
    ]
    for table, builder_sql, cols in targets:
        for d in dts:
            _delete_partition(s3, bucket, f"marts/{table}/dt={d}/")
        select = ", ".join(cols) + ", dt"
        insert = f"INSERT INTO {table} SELECT {select} FROM ({builder_sql}) WHERE dt IN ({dt_list})"
        _execute(athena, insert)


def lambda_handler(event, context):
    del event, context
    run(datetime.now(timezone.utc).date())
    return {"ok": True}
```
Import `TRINO, sessions_sql, mart_sql, FACT_SESSION_COLUMNS, MART_USER_DAILY_COLUMNS` from `.analytics_rollup`. `_execute` uses `os.environ["ATHENA_DATABASE"|"ATHENA_WORKGROUP"|"ATHENA_OUTPUT_LOCATION"]`.

- [ ] **Step 4: Run → passes.** Then full suite: `pytest -q`.

- [ ] **Step 5: Commit**
```bash
git add src/collector/analytics_rollup_runner.py tests/unit/test_analytics_rollup_runner.py
git commit -m "$(cat <<'EOF'
feat(analytics): add scheduled rollup runner

Overwrites the last 3 dt partitions of fact_session + mart_user_daily
via S3 delete + Athena INSERT INTO, scanning a 4-day bronze window.
Dates inlined as validated literals (gotcha #13).
EOF
)"
```

---

### Task 3: Rewrite the serving handler for the per-user daily dashboard

**Files:** `src/collector/analytics_handler.py`, `tests/unit/test_analytics_handler.py`

- [ ] **Step 1: Rewrite the handler tests**

Replace the dashboard-specific tests in `tests/unit/test_analytics_handler.py` (the ones referencing triage/taste/funnel/playback/ops routes and their SQL) with tests for the two new routes. Keep the admin-gate tests. New behavior:
- `_ROUTE_QUERIES` has exactly two keys: `user-daily` and `sessions`.
- Both require `user_id` (non-empty) plus `from`/`to` (YYYY-MM-DD). Missing/invalid `user_id` → 400 `invalid_params`.
- `user_id` is passed as an ExecutionParameters bind (`?`), NOT inlined; `from`/`to` are inlined validated literals.
- Response: `{ "user-daily": [...rows], "correlation_id": ... }` (route name keys the payload, as today).

Example tests (mock Athena via `monkeypatch.setattr(ah, "_run_athena", fake)`):
```python
def test_user_daily_binds_user_id_and_inlines_dates(monkeypatch):
    captured = {}
    def fake(client, sql, params):
        captured["sql"] = sql; captured["params"] = params; return []
    monkeypatch.setattr(ah, "_run_athena", fake)
    monkeypatch.setattr(ah, "_cached_rows", lambda sql, pk: tuple(fake(None, sql, list(pk))))
    resp = ah.lambda_handler(_event("/v1/analytics/user-daily", is_admin=True,
                                     qs={"user_id": "u1", "from": "2026-06-01", "to": "2026-06-30"}), None)
    assert resp["statusCode"] == 200
    assert "mart_user_daily" in captured["sql"]
    assert "'2026-06-01'" in captured["sql"] and "'2026-06-30'" in captured["sql"]
    assert captured["params"] == ["u1"]          # user_id bound, not inlined
    assert "u1" not in captured["sql"]

def test_missing_user_id_400(monkeypatch):
    resp = ah.lambda_handler(_event("/v1/analytics/user-daily", is_admin=True,
                                     qs={"from": "2026-06-01", "to": "2026-06-30"}), None)
    assert resp["statusCode"] == 400

def test_sessions_route_queries_fact_session(monkeypatch):
    captured = {}
    monkeypatch.setattr(ah, "_cached_rows", lambda sql, pk: captured.setdefault("sql", sql) and ())
    ah.lambda_handler(_event("/v1/analytics/sessions", is_admin=True,
                             qs={"user_id": "u1", "from": "2026-06-01", "to": "2026-06-30"}), None)
    assert "fact_session" in captured["sql"]
```
(Adjust to the repo's actual `_event` helper + how `_cached_rows` is invoked — read the current test file first.)

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Rewrite the handler**

- Replace `_ROUTE_QUERIES` with:
```python
_ROUTE_QUERIES = {
    "user-daily": {"user-daily": (
        "SELECT user_id, activity_type, dt, sessions, "
        "avg_tracks_listened, avg_tracks_promoted, avg_tracks_deleted, "
        "p50_duration_ms, p90_duration_ms, p50_time_per_track_ms, p90_time_per_track_ms "
        "FROM mart_user_daily WHERE user_id = ? "
        "AND dt BETWEEN {frm} AND {to} ORDER BY dt, activity_type"
    )},
    "sessions": {"sessions": (
        "SELECT user_id, activity_type, dt, session_seq, ts_start, ts_end, "
        "duration_ms, tracks_listened, tracks_promoted, tracks_deleted "
        "FROM fact_session WHERE user_id = ? "
        "AND dt BETWEEN {frm} AND {to} ORDER BY dt, activity_type, session_seq"
    )},
}
```
- Extend `_validate_params` to also read+require `user_id` (non-empty, length-capped e.g. ≤128, else 400) and return `(date_from, date_to, user_id)`.
- Extend `build_queries(route, date_from, date_to, user_id)`: inline `{frm}/{to}` as today, and return `(sql, [user_id])` so the `?` binds via ExecutionParameters.
- Update `lambda_handler` to unpack the new 3-tuple and pass `user_id`. Drop the `freshness`/`_freshness` special-case (no longer used) — remove the dead `_freshness` function.

- [ ] **Step 4: Run the handler tests + full suite → pass.**

- [ ] **Step 5: Commit**
```bash
git add src/collector/analytics_handler.py tests/unit/test_analytics_handler.py
git commit -m "$(cat <<'EOF'
feat(analytics): serve per-user daily marts

Replace the 5 dead dbt-gold dashboards with user-daily + sessions
routes over mart_user_daily / fact_session. user_id binds via
ExecutionParameters; from/to inline as validated literals.
EOF
)"
```

---

### Task 4: Route registration (openapi) + infra (routes, rollup Lambda, schedule)

**Files:** `scripts/generate_openapi.py`, `infra/analytics_routes.tf`, `infra/analytics_rollup.tf` (create)

- [ ] **Step 1: OpenAPI** — in `scripts/generate_openapi.py`, replace the five `_analytics_route("triage"...)`…`("ops"...)` calls with two: `_analytics_route("user-daily", "Per-user daily analytics.", "...")` and `_analytics_route("sessions", "Per-user session drill-down.", "...")`. If `_analytics_route` hardcodes only `from`/`to` query params, extend it (or add params) so both new routes document a required `user_id` query param plus `from`/`to`.

- [ ] **Step 2: Regenerate + verify OpenAPI**
Run: `PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py`
Then confirm the generated `docs/api/openapi.yaml` contains `/v1/analytics/user-daily` and `/v1/analytics/sessions` and no longer the 5 old paths: `grep -E "analytics/(triage|taste|funnel|playback|ops|user-daily|sessions)" docs/api/openapi.yaml`.

- [ ] **Step 3: infra routes** — in `infra/analytics_routes.tf`, replace `local.analytics_routes` with:
```hcl
  analytics_routes = [
    "GET /v1/analytics/user-daily",
    "GET /v1/analytics/sessions",
  ]
```
Leave the serving Lambda/role/workgroup as-is (it already has Glue read + S3 read on `marts/*`, which is what serving needs). The stale `gold/*` and `bronze/events/*` read statements may remain (harmless) or be trimmed to `marts/*` + `athena-results/*` — trimming is preferred but not required.

- [ ] **Step 4: infra rollup Lambda** — create `infra/analytics_rollup.tf`: a `${local.name_prefix}-analytics-rollup` Lambda (handler `collector.analytics_rollup_runner.lambda_handler`, shares `local.lambda_zip_file`, timeout ~300s, memory ~256MB), its own role + policy allowing: Athena (StartQueryExecution/GetQueryExecution/GetQueryResults/GetWorkGroup on the analytics workgroup), Glue read+write on the analytics DB/tables (`GetTable`,`GetPartitions`,`BatchCreatePartition`,`CreatePartition`,`GetDatabase`), S3 read on `bronze/events/*` + `athena-results/*`, S3 read+write+delete on `marts/*` (`GetObject`,`ListBucket`,`PutObject`,`DeleteObject`,`GetBucketLocation`), and CloudWatch Logs. Env: `ATHENA_DATABASE`, `ATHENA_WORKGROUP`, `ATHENA_OUTPUT_LOCATION`, `ANALYTICS_LAKE_BUCKET`, `LOG_LEVEL`. Add an `aws_cloudwatch_event_rule` (`schedule_expression = "cron(0 3 * * ? *)"`) + `aws_cloudwatch_event_target` → the rollup Lambda + `aws_lambda_permission` for events.amazonaws.com. Mirror the IAM/log-group idioms in `analytics_routes.tf`.

- [ ] **Step 5: Validate**
Run: `cd infra && terraform fmt && terraform validate` → `Success!` (init `-backend=false` if needed; if terraform unavailable, brace-check + note).
Run the full suite once more: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`.

- [ ] **Step 6: Commit**
```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml infra/analytics_routes.tf infra/analytics_rollup.tf
git commit -m "$(cat <<'EOF'
feat(infra): wire per-user-daily routes + rollup schedule

OpenAPI + API Gateway routes swap the 5 old dashboards for
user-daily + sessions. New analytics-rollup Lambda on a daily
EventBridge schedule with a dedicated write role.
EOF
)"
```

---

### Task 5: Refresh graphify + verify

- [ ] **Step 1: Full suite** — `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q` → PASS.
- [ ] **Step 2: Confirm no dead dbt-gold table names remain in serving** — `grep -nE "fact_track_decision|dim_date|fact_playback|fact_funnel_step|dim_category|dim_track|dim_label|fact_seek|fact_triage_session" src/collector/analytics_handler.py` → empty.
- [ ] **Step 3: graphify** — `graphify . --update` (doc-key error expected/non-fatal; code topology rebuilds via the watcher), then `git add -A graphify-out` and commit if changed:
```bash
git commit -m "$(cat <<'EOF'
chore(graphify): refresh graph after rollup + serving
EOF
)"
```

---

## Self-Review

**Spec coverage:** scheduled rollup (Part D) → Tasks 1-2, 4. Serving the marts + deleting the 5 dead dashboards (Part D) → Task 3. Route registration three-places (handler `_ROUTE_QUERIES` + openapi + infra) → Tasks 3-4. Daily/3-day cadence → Task 2 + the EventBridge cron in Task 4. Least-privilege split (write rollup vs read serving) → Task 4.

**Deferred:** frontend (Plan 4), rename (Plan F). Freshness endpoint dropped (was tied to the deleted ops dashboard; re-add later if the dashboard needs a staleness badge).

**Type/name consistency:** `FACT_SESSION_COLUMNS`/`MART_USER_DAILY_COLUMNS` defined in Task 1, imported by the runner in Task 2, and their order matches the Glue tables (Plan 2 Task 4) with `dt` appended last in the runner's INSERT SELECT. Route names `user-daily`/`sessions` are identical across `_ROUTE_QUERIES` (Task 3), OpenAPI (Task 4), and infra routes (Task 4). `build_queries` gains a `user_id` arg — every caller (only `lambda_handler`) is updated in Task 3.

**Risks:** Athena `INSERT INTO` partition overwrite correctness is verified by unit-mocking the SQL/S3 calls; real execution is validated in staging (unavoidable for warehouse SQL). If `INSERT INTO` a Hive external table proves unreliable at deploy time, the fallback is Iceberg tables (change the Plan-2 Glue defs to Iceberg + use `INSERT OVERWRITE`) — note but do not pre-build. The rollup Lambda timeout (300s) assumes small-circle volume; raise if the 4-day scan grows.

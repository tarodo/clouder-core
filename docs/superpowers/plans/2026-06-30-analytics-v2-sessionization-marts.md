# Analytics v2 — Sessionization Marts Implementation Plan (Plan 2 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the gaps-and-islands sessionization SQL that turns the typed `bronze_events` raw layer into two marts — `fact_session` (one row per derived session) and `mart_user_daily` (per user × dt × activity_type rollup with session counts, averages, duration percentiles, and time-per-track percentiles) — developed test-first against DuckDB fixtures.

**Architecture:** One SQL source rendered for two dialects via a tiny shim: Trino/Athena for production, DuckDB for tests (so the real gaps-and-islands logic runs locally against fixtures). The SQL lives in `src/collector/analytics_rollup.py` as dialect-rendered builder functions. This plan produces the SQL + Glue mart tables + tests; the scheduled runner and the serving endpoints come in Plan 3.

**Tech Stack:** Python 3, DuckDB (new dev-dep) for SQL logic tests, Trino/Athena SQL, Terraform (Glue), pytest.

**Plan series:** Plan 1 (envelope redesign) is DONE. This is Plan 2. Plan 3 = scheduled rollup runner + rewrite `analytics_handler._ROUTE_QUERIES` to serve these marts + new GET routes (the old 5 dashboards — triage/taste/funnel/playback/ops — and their SQL are deleted there, since they query the now-deleted dbt gold tables). Plan 4 = frontend dashboard. Plan F = beatport→clouder rename. Spec: `docs/superpowers/specs/2026-06-30-analytics-v2-user-daily-design.md`.

**Worktree:** branch `feat/analytics-v2` at `.claude/worktrees/correct_reports`. Run pytest as `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest` (`.venv` at MAIN repo root). `PYTHONPATH=src` is set by pytest.ini.

---

## Activity model (the contract the SQL implements)

Each `bronze_events` row maps to exactly one `activity_type` (rows that match nothing are dropped):

```
CASE
  WHEN event_name = 'track_categorized' AND action = 'removed_from_category' THEN 'category'
  WHEN event_name = 'playlist_add'      AND source_category_id IS NOT NULL    THEN 'category'
  WHEN event_name IN ('triage_session_start','triage_session_end','track_view',
                      'track_categorized','hotkey_used')                       THEN 'triage'
  WHEN source = 'triage_player'   THEN 'triage'
  WHEN source = 'category_player' THEN 'category'
  WHEN source = 'playlist_player' THEN 'playlist'
  ELSE NULL
END
```
(Order matters: `removed_from_category` is checked before the generic `track_categorized → triage`.)

**Session** = within a `(user_id, activity_type)` stream ordered by `ts_server`, a gap > 300s starts a new session (`session_seq`, 0-indexed). A session's `dt` is the date of its first event (sessions are NOT reset at midnight; a cross-midnight session is attributed to its start day).

**Per-session metrics:**
- `duration_ms` = (max ts − min ts) × 1000.
- `tracks_listened` = count(distinct `track_id`) over `playback_play` rows; NULL for `playlist`.
- `tracks_promoted` / `tracks_deleted` (NULL for `playlist`), per-row contributions summed:
  - triage promoted: `+1` when `track_categorized` & `action IN ('moved_to_bucket','categorized_curate')` & `category_key <> 'DISCARD'`; `−1` when `action='undo'` & `category_key <> 'DISCARD'`.
  - triage deleted: `+1` when `track_categorized` & `action IN ('moved_to_bucket','categorized_curate')` & `category_key = 'DISCARD'`; `−1` when `action='undo'` & `category_key = 'DISCARD'`.
  - category promoted: `+ track_count` when `playlist_add` & `source_category_id IS NOT NULL`.
  - category deleted: `+1` when `track_categorized` & `action='removed_from_category'`.

**Daily metrics (`mart_user_daily`, grain user × dt × activity_type):**
- `sessions` = count of sessions.
- `avg_tracks_listened` / `avg_tracks_promoted` / `avg_tracks_deleted` = mean over the day's sessions (NULL for playlist).
- `p50_duration_ms`, `p90_duration_ms` = percentiles of session `duration_ms`.
- `p50_time_per_track_ms`, `p90_time_per_track_ms` = percentiles of per-track time: triage uses `track_categorized.decision_ms`; category/playlist use wall-clock (ms) from each `playback_play` to the next event in the same session (last play of a session, which has no following event, is excluded).

> **ponytail note:** On sparse days a percentile ≈ the few raw values — expected for a small-circle DJ tool. Tests use DuckDB `quantile_cont` (exact) so expected values are deterministic; production uses Trino `approx_percentile`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `requirements-dev.txt` | add `duckdb` dev-dep | Modify |
| `src/collector/analytics_rollup.py` | dialect shim + `sessions_sql(d)` / `mart_sql(d)` builders | Create |
| `tests/unit/test_analytics_rollup.py` | DuckDB fixture tests for both marts | Create |
| `infra/analytics_marts.tf` | Glue `fact_session` + `mart_user_daily` external tables + `marts/` S3 layout | Create |

---

### Task 1: Add DuckDB + the dialect shim and test harness

**Files:**
- Modify: `requirements-dev.txt`
- Create: `src/collector/analytics_rollup.py`
- Create: `tests/unit/test_analytics_rollup.py`

- [ ] **Step 1: Add the dev-dep**

Append `duckdb>=1.0` to `requirements-dev.txt` (one line, after the existing entries). Then install it into the project venv:
Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pip install 'duckdb>=1.0'`
Expected: installs cleanly. Confirm: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -c "import duckdb; print(duckdb.__version__)"` prints a version.

- [ ] **Step 2: Write the dialect shim + builder skeleton**

Create `src/collector/analytics_rollup.py`:

```python
"""Sessionization rollup SQL for the analytics v2 marts.

One SQL source, two dialects: Trino/Athena in production, DuckDB in tests.
The gaps-and-islands logic (5-min idle splits a session) and all metrics are
identical across dialects; only timestamp parsing, epoch conversion, and the
percentile function differ — isolated in the DIALECT dicts. See the activity
model in the plan / spec.
"""

from __future__ import annotations

from typing import Mapping

# Dialect-specific function fragments. {} is the single positional arg.
TRINO: Mapping[str, str] = {
    "to_ts": "from_iso8601_timestamp({})",
    "epoch": "to_unixtime({})",
    "to_date": "date({})",
    "pctl": "approx_percentile({}, {})",
}
DUCKDB: Mapping[str, str] = {
    "to_ts": "CAST({} AS TIMESTAMP)",
    "epoch": "epoch({})",
    "to_date": "CAST({} AS DATE)",
    "pctl": "quantile_cont({}, {})",
}

# Columns the activity classifier / metrics read off bronze_events.
_NEW_SESSION_GAP_S = 300


def sessions_sql(d: Mapping[str, str], *, source: str = "bronze_events") -> str:
    """SQL selecting one row per derived session (the fact_session grain)."""
    ts = d["to_ts"].format("ts_server")
    epoch_ts = d["epoch"].format("ts")
    to_date = d["to_date"].format("min(ts)")
    return f"""
WITH classified AS (
  SELECT
    user_id, {ts} AS ts, event_name, track_id, source, action,
    category_key, track_count, source_category_id, decision_ms,
    CASE
      WHEN event_name = 'track_categorized' AND action = 'removed_from_category' THEN 'category'
      WHEN event_name = 'playlist_add' AND source_category_id IS NOT NULL THEN 'category'
      WHEN event_name IN ('triage_session_start','triage_session_end','track_view','track_categorized','hotkey_used') THEN 'triage'
      WHEN source = 'triage_player' THEN 'triage'
      WHEN source = 'category_player' THEN 'category'
      WHEN source = 'playlist_player' THEN 'playlist'
      ELSE NULL
    END AS activity_type
  FROM {source}
  WHERE user_id IS NOT NULL
),
events AS (SELECT * FROM classified WHERE activity_type IS NOT NULL),
gapped AS (
  SELECT *,
    CASE WHEN {epoch_ts} - lag({epoch_ts}) OVER (
           PARTITION BY user_id, activity_type ORDER BY ts) > {_NEW_SESSION_GAP_S}
         THEN 1 ELSE 0 END AS is_new
  FROM events
),
sessioned AS (
  SELECT *,
    SUM(is_new) OVER (PARTITION BY user_id, activity_type ORDER BY ts
                      ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS session_seq
  FROM gapped
)
SELECT
  user_id, activity_type, session_seq,
  {to_date} AS dt,
  CAST(({epoch_max} - {epoch_min}) * 1000 AS BIGINT) AS duration_ms,
  CASE WHEN activity_type = 'playlist' THEN NULL
       ELSE count(DISTINCT CASE WHEN event_name = 'playback_play' THEN track_id END) END AS tracks_listened,
  CASE WHEN activity_type = 'playlist' THEN NULL ELSE sum({promoted}) END AS tracks_promoted,
  CASE WHEN activity_type = 'playlist' THEN NULL ELSE sum({deleted}) END AS tracks_deleted
FROM sessioned
GROUP BY user_id, activity_type, session_seq
""".format(
        to_date=to_date,
        epoch_max=d["epoch"].format("max(ts)"),
        epoch_min=d["epoch"].format("min(ts)"),
        promoted=_PROMOTED_CONTRIB,
        deleted=_DELETED_CONTRIB,
    )


_PROMOTED_CONTRIB = """CASE
  WHEN activity_type='triage' AND event_name='track_categorized' AND action IN ('moved_to_bucket','categorized_curate') AND category_key <> 'DISCARD' THEN 1
  WHEN activity_type='triage' AND event_name='track_categorized' AND action='undo' AND category_key <> 'DISCARD' THEN -1
  WHEN activity_type='category' AND event_name='playlist_add' AND source_category_id IS NOT NULL THEN track_count
  ELSE 0 END"""

_DELETED_CONTRIB = """CASE
  WHEN activity_type='triage' AND event_name='track_categorized' AND action IN ('moved_to_bucket','categorized_curate') AND category_key='DISCARD' THEN 1
  WHEN activity_type='triage' AND event_name='track_categorized' AND action='undo' AND category_key='DISCARD' THEN -1
  WHEN activity_type='category' AND event_name='track_categorized' AND action='removed_from_category' THEN 1
  ELSE 0 END"""
```

> NOTE TO IMPLEMENTER: the `sessions_sql` above is a working reference but the `.format()` mixing f-string and `.format` is fiddly — you may restructure to build the whole string with one f-string and module-level `_PROMOTED_CONTRIB`/`_DELETED_CONTRIB`/epoch fragments, as long as the rendered SQL is equivalent and BOTH dialects render. The TESTS in the next tasks are the contract — make them pass. `mart_sql(d)` is added in Task 3.

- [ ] **Step 3: Write the shared DuckDB fixture + harness in the test file**

Create `tests/unit/test_analytics_rollup.py` with the fixture loader and a sanity test:

```python
from __future__ import annotations

import duckdb
import pytest

from collector.analytics_rollup import DUCKDB, sessions_sql

# (event_id, user_id, ts_server, event_name, track_id, source, action,
#  category_key, track_count, source_category_id, decision_ms)
# One user (u1), one day. Covers: 2 triage sessions split by a >5min gap
# (promote/delete/undo/listen), 1 category session (listen x2 + promote 3 +
# delete 1), 1 playlist session (2 plays).
_ROWS = [
    ("e01", "u1", "2026-06-29T10:00:00Z", "triage_session_start", None, None, None, None, None, None, None),
    ("e02", "u1", "2026-06-29T10:00:30Z", "track_view", "t1", None, None, None, None, None, None),
    ("e03", "u1", "2026-06-29T10:00:40Z", "track_categorized", "t1", None, "moved_to_bucket", "NEW", None, None, 10000),
    ("e04", "u1", "2026-06-29T10:01:00Z", "track_view", "t2", None, None, None, None, None, None),
    ("e05", "u1", "2026-06-29T10:01:10Z", "track_categorized", "t2", None, "moved_to_bucket", "DISCARD", None, None, 8000),
    ("e06", "u1", "2026-06-29T10:02:00Z", "playback_play", "t1", "triage_player", None, None, None, None, None),
    # >5min gap -> new triage session
    ("e07", "u1", "2026-06-29T10:10:00Z", "track_view", "t3", None, None, None, None, None, None),
    ("e08", "u1", "2026-06-29T10:10:20Z", "track_categorized", "t3", None, "categorized_curate", "PEAK", None, None, 12000),
    ("e09", "u1", "2026-06-29T10:10:25Z", "track_categorized", "t3", None, "undo", "PEAK", None, None, None),
    # category session
    ("e10", "u1", "2026-06-29T11:00:00Z", "playback_play", "t5", "category_player", None, None, None, None, None),
    ("e11", "u1", "2026-06-29T11:00:50Z", "playback_play", "t6", "category_player", None, None, None, None, None),
    ("e12", "u1", "2026-06-29T11:01:30Z", "playback_ended", "t6", "category_player", None, None, None, None, None),
    ("e13", "u1", "2026-06-29T11:02:00Z", "playlist_add", None, None, None, None, 3, "c1", None),
    ("e14", "u1", "2026-06-29T11:02:30Z", "track_categorized", "t7", None, "removed_from_category", "c1", None, None, None),
    # playlist session
    ("e15", "u1", "2026-06-29T12:00:00Z", "playback_play", "t8", "playlist_player", None, None, None, None, None),
    ("e16", "u1", "2026-06-29T12:00:40Z", "playback_play", "t9", "playlist_player", None, None, None, None, None),
]

_COLS = ["event_id", "user_id", "ts_server", "event_name", "track_id", "source",
         "action", "category_key", "track_count", "source_category_id", "decision_ms"]


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE bronze_events (event_id VARCHAR, user_id VARCHAR, ts_server VARCHAR, "
        "event_name VARCHAR, track_id VARCHAR, source VARCHAR, action VARCHAR, "
        "category_key VARCHAR, track_count INTEGER, source_category_id VARCHAR, decision_ms BIGINT)"
    )
    c.executemany(
        "INSERT INTO bronze_events VALUES (?,?,?,?,?,?,?,?,?,?,?)", _ROWS
    )
    yield c
    c.close()


def _sessions(con):
    cols = ["user_id", "activity_type", "session_seq", "dt", "duration_ms",
            "tracks_listened", "tracks_promoted", "tracks_deleted"]
    rows = con.execute(sessions_sql(DUCKDB)).fetchall()
    return [dict(zip(cols, r)) for r in rows]


def test_fixture_loads_and_sql_runs(con):
    rows = _sessions(con)
    assert len(rows) == 4  # 2 triage + 1 category + 1 playlist sessions
```

- [ ] **Step 4: Run the harness test**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_rollup.py -q`
Expected: PASS (4 sessions). If `sessions_sql(DUCKDB)` errors in DuckDB, fix the dialect rendering until the query runs and returns 4 rows.

- [ ] **Step 5: Commit** (conventional subject; hook blocks non-conventional + strips AI trailer)
```bash
git add requirements-dev.txt src/collector/analytics_rollup.py tests/unit/test_analytics_rollup.py
git commit -m "$(cat <<'EOF'
feat(analytics): add sessionization rollup SQL scaffold

DuckDB dev-dep + dialect-shimmed sessions_sql (Trino prod / DuckDB
tests) + fixture harness. Gaps-and-islands runs locally against a
fixture covering triage/category/playlist sessions.
EOF
)"
```

---

### Task 2: Assert the full `fact_session` grain

**Files:**
- Modify: `tests/unit/test_analytics_rollup.py`
- Modify: `src/collector/analytics_rollup.py` (only if a metric is wrong)

- [ ] **Step 1: Add the fact_session assertions**

Append to `tests/unit/test_analytics_rollup.py`:

```python
def _by_key(rows):
    return {(r["activity_type"], r["session_seq"]): r for r in rows}


def test_fact_session_metrics(con):
    s = _by_key(_sessions(con))

    t0 = s[("triage", 0)]
    assert str(t0["dt"]) == "2026-06-29"
    assert t0["duration_ms"] == 120000          # 10:00:00 -> 10:02:00
    assert t0["tracks_listened"] == 1           # t1 played
    assert t0["tracks_promoted"] == 1           # t1 -> NEW
    assert t0["tracks_deleted"] == 1            # t2 -> DISCARD

    t1 = s[("triage", 1)]
    assert t1["duration_ms"] == 25000           # 10:10:00 -> 10:10:25
    assert t1["tracks_listened"] == 0
    assert t1["tracks_promoted"] == 0           # curate PEAK (+1) then undo (-1)
    assert t1["tracks_deleted"] == 0

    c0 = s[("category", 0)]
    assert c0["duration_ms"] == 150000          # 11:00:00 -> 11:02:30
    assert c0["tracks_listened"] == 2           # t5, t6
    assert c0["tracks_promoted"] == 3           # playlist_add track_count=3
    assert c0["tracks_deleted"] == 1            # removed_from_category

    p0 = s[("playlist", 0)]
    assert p0["duration_ms"] == 40000           # 12:00:00 -> 12:00:40
    assert p0["tracks_listened"] is None
    assert p0["tracks_promoted"] is None
    assert p0["tracks_deleted"] is None
```

- [ ] **Step 2: Run it**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_rollup.py -q`
Expected: PASS. If any assertion fails, the SQL metric logic is wrong — fix `sessions_sql` (the promote/delete CASEs, the playlist NULLing, or the duration cast) until all pass. Do NOT change the expected values (they are hand-derived from the fixture per the activity model).

- [ ] **Step 3: Commit**
```bash
git add src/collector/analytics_rollup.py tests/unit/test_analytics_rollup.py
git commit -m "$(cat <<'EOF'
test(analytics): pin fact_session metrics on fixture

Locks duration, listened, promoted (net of undo), deleted across
triage/category/playlist sessions.
EOF
)"
```

---

### Task 3: `mart_user_daily` aggregation (averages, duration + time-per-track percentiles)

**Files:**
- Modify: `src/collector/analytics_rollup.py` (add `mart_sql`)
- Modify: `tests/unit/test_analytics_rollup.py`

- [ ] **Step 1: Write the mart test with hand-derived expected values**

Append to `tests/unit/test_analytics_rollup.py`:

```python
from collector.analytics_rollup import mart_sql


def _mart(con):
    cols = ["user_id", "dt", "activity_type", "sessions",
            "avg_tracks_listened", "avg_tracks_promoted", "avg_tracks_deleted",
            "p50_duration_ms", "p90_duration_ms",
            "p50_time_per_track_ms", "p90_time_per_track_ms"]
    rows = con.execute(mart_sql(DUCKDB)).fetchall()
    return {r[2]: dict(zip(cols, r)) for r in rows}  # keyed by activity_type


def test_mart_user_daily(con):
    m = _mart(con)

    tr = m["triage"]
    assert tr["sessions"] == 2
    assert tr["avg_tracks_listened"] == pytest.approx(0.5)
    assert tr["avg_tracks_promoted"] == pytest.approx(0.5)
    assert tr["avg_tracks_deleted"] == pytest.approx(0.5)
    # session durations [120000, 25000]
    assert tr["p50_duration_ms"] == pytest.approx(72500)
    assert tr["p90_duration_ms"] == pytest.approx(110500)
    # triage time-per-track = decision_ms [10000, 8000, 12000]
    assert tr["p50_time_per_track_ms"] == pytest.approx(10000)
    assert tr["p90_time_per_track_ms"] == pytest.approx(11600)

    ca = m["category"]
    assert ca["sessions"] == 1
    assert ca["avg_tracks_listened"] == pytest.approx(2)
    assert ca["avg_tracks_promoted"] == pytest.approx(3)
    assert ca["avg_tracks_deleted"] == pytest.approx(1)
    assert ca["p50_duration_ms"] == pytest.approx(150000)
    # category time-per-track = wall-clock [50000 (t5->t6), 40000 (t6->ended)]
    assert ca["p50_time_per_track_ms"] == pytest.approx(45000)
    assert ca["p90_time_per_track_ms"] == pytest.approx(49000)

    pl = m["playlist"]
    assert pl["sessions"] == 1
    assert pl["avg_tracks_listened"] is None
    assert pl["avg_tracks_promoted"] is None
    assert pl["avg_tracks_deleted"] is None
    assert pl["p50_duration_ms"] == pytest.approx(40000)
    # playlist time-per-track = wall-clock [40000 (t8->t9)]; last play excluded
    assert pl["p50_time_per_track_ms"] == pytest.approx(40000)
```

- [ ] **Step 2: Run it (expect failure — `mart_sql` undefined)**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_rollup.py::test_mart_user_daily -q`
Expected: FAIL — `ImportError: cannot import name 'mart_sql'`.

- [ ] **Step 3: Implement `mart_sql(d)`**

Add to `src/collector/analytics_rollup.py`. It reuses the `sessioned` CTE (factor the WITH-block out of `sessions_sql` into a shared `_sessioned_cte(d, source)` returning the `WITH ... sessioned AS (...)` text, used by both builders). `mart_sql` then:
1. derives `fact_session` (same SELECT as `sessions_sql`) as a CTE `fs`;
2. derives `time_rows` (per-track time): triage `decision_ms`, and category/playlist wall-clock = `(lead(epoch(ts)) OVER (PARTITION BY user_id, activity_type, session_seq ORDER BY ts) − epoch(ts)) * 1000` filtered to `event_name='playback_play'` rows with a non-null lead, attributed to the session's `dt`;
3. aggregates per `(user_id, dt, activity_type)`: `count(*)` sessions, the three `avg(...)`, `pctl(duration_ms, 0.5/0.9)`, and `pctl(time_ms, 0.5/0.9)` joined from `time_rows`.

Reference shape (render via the dialect dict like `sessions_sql`):
```sql
WITH /* shared sessioned CTE */,
fs AS ( /* the sessions_sql SELECT, grouped by user_id, activity_type, session_seq,
          also exposing dt */ ),
play_gap AS (
  SELECT user_id, activity_type, dt_session AS dt,
         (lead(<epoch ts>) OVER (PARTITION BY user_id, activity_type, session_seq ORDER BY ts)
          - <epoch ts>) * 1000 AS gap_ms, event_name
  FROM sessioned_with_session_dt
),
time_rows AS (
  SELECT user_id, dt, activity_type, decision_ms AS t_ms
  FROM sessioned_with_session_dt
  WHERE activity_type='triage' AND event_name='track_categorized' AND decision_ms IS NOT NULL
  UNION ALL
  SELECT user_id, dt, activity_type, gap_ms AS t_ms
  FROM play_gap
  WHERE activity_type IN ('category','playlist') AND event_name='playback_play' AND gap_ms IS NOT NULL
),
daily_time AS (
  SELECT user_id, dt, activity_type,
         <pctl t_ms 0.5> AS p50_time_per_track_ms,
         <pctl t_ms 0.9> AS p90_time_per_track_ms
  FROM time_rows GROUP BY user_id, dt, activity_type
)
SELECT fs.user_id, fs.dt, fs.activity_type,
       count(*) AS sessions,
       avg(fs.tracks_listened) AS avg_tracks_listened,
       avg(fs.tracks_promoted) AS avg_tracks_promoted,
       avg(fs.tracks_deleted)  AS avg_tracks_deleted,
       <pctl fs.duration_ms 0.5> AS p50_duration_ms,
       <pctl fs.duration_ms 0.9> AS p90_duration_ms,
       max(dt2.p50_time_per_track_ms) AS p50_time_per_track_ms,
       max(dt2.p90_time_per_track_ms) AS p90_time_per_track_ms
FROM fs
LEFT JOIN daily_time dt2 ON dt2.user_id=fs.user_id AND dt2.dt=fs.dt AND dt2.activity_type=fs.activity_type
GROUP BY fs.user_id, fs.dt, fs.activity_type
```
`sessioned_with_session_dt` = `sessioned` joined to each session's `dt` (min ts date) so time_rows attribute to the start day. `avg()` over a NULL column (playlist's listened/promoted/deleted) yields NULL — matching the expected output. Adjust until the Step-1 test passes; do NOT edit the expected values.

- [ ] **Step 4: Run the full rollup test file**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_rollup.py -q`
Expected: PASS (all three tests).

- [ ] **Step 5: Confirm the Trino render is well-formed**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -c "import sys; sys.path.insert(0,'src'); from collector.analytics_rollup import TRINO, sessions_sql, mart_sql; print(sessions_sql(TRINO)[:80]); print(mart_sql(TRINO)[:80])"`
Expected: prints two SQL prefixes with `from_iso8601_timestamp` / `approx_percentile` (no `KeyError`/format error). This is a render smoke-check only — the Trino SQL runs on Athena in Plan 3.

- [ ] **Step 6: Commit**
```bash
git add src/collector/analytics_rollup.py tests/unit/test_analytics_rollup.py
git commit -m "$(cat <<'EOF'
feat(analytics): add mart_user_daily rollup SQL

Per user/dt/activity rollup: session count, count averages, session
duration percentiles, and time-per-track percentiles (triage
decision_ms; category/playlist play-to-next wall-clock).
EOF
)"
```

---

### Task 4: Glue tables for the marts

**Files:**
- Create: `infra/analytics_marts.tf`

- [ ] **Step 1: Define the two external tables**

Create `infra/analytics_marts.tf` with `aws_glue_catalog_table` resources for `fact_session` and `mart_user_daily`, both EXTERNAL, Parquet, located under the existing analytics lake bucket (`aws_s3_bucket.analytics_lake`) at `marts/fact_session/` and `marts/mart_user_daily/`, partitioned by `dt` (date) with partition projection (`projection.enabled=true`, `projection.dt.type=date`, format `yyyy-MM-dd`, range `2026-01-01,NOW`). Mirror the column/SerDe style of `aws_glue_catalog_table.bronze_events` in `infra/telemetry.tf` (parquet input/output format + `parquet.hive.serde`). Columns:

`fact_session`: `user_id` string, `activity_type` string, `session_seq` bigint, `ts_start` string, `ts_end` string, `duration_ms` bigint, `tracks_listened` bigint, `tracks_promoted` bigint, `tracks_deleted` bigint. Partition key: `dt` (date) — NOT a data column.

`mart_user_daily`: `user_id` string, `activity_type` string, `sessions` bigint, `avg_tracks_listened` double, `avg_tracks_promoted` double, `avg_tracks_deleted` double, `p50_duration_ms` double, `p90_duration_ms` double, `p50_time_per_track_ms` double, `p90_time_per_track_ms` double. Partition key: `dt` (date).

(`ts_start`/`ts_end` are kept as strings for the drill-down; `session_seq` lives in `fact_session` for uniqueness within a day. The rollup SELECTs in Plan 3's CTAS will project these columns in this order.)

- [ ] **Step 2: Validate Terraform**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `Success! The configuration is valid.` (init `-backend=false` if needed; if terraform is unavailable, brace-balance + visual-check and note it).

- [ ] **Step 3: Commit**
```bash
git add infra/analytics_marts.tf
git commit -m "$(cat <<'EOF'
feat(infra): add Glue tables for analytics v2 marts

fact_session + mart_user_daily external Parquet tables under
marts/, dt partition projection. Populated by the Plan 3 rollup.
EOF
)"
```

---

### Task 5: Refresh graphify + verify the increment

- [ ] **Step 1: Full suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS (the new rollup tests + all prior).

- [ ] **Step 2: Refresh the graph**

Run: `graphify . --update` then `git add -A graphify-out`.
NOTE: `graphify . --update` may print a non-fatal error about doc/paper files needing an LLM key — that is expected in this environment; the code topology is rebuilt by the background watcher regardless. If `graphify-out` has staged changes, commit them; if not, skip the commit.

- [ ] **Step 3: Commit (if graph changed)**
```bash
git commit -m "$(cat <<'EOF'
chore(graphify): refresh graph after sessionization marts
EOF
)"
```

---

## Self-Review

**Spec coverage:** activity classification (Part C) → Task 1 CASE. Gaps-and-islands 5-min → Task 1 `gapped`/`sessioned`. `fact_session` grain + metrics (duration, listened, promoted/deleted net of undo, playlist NULLs) → Tasks 1-2. `mart_user_daily` (sessions, averages, duration percentiles, time-per-track percentiles; triage decision_ms vs category/playlist wall-clock) → Task 3. Glue marts → Task 4. Percentiles via DuckDB exact in tests / Trino approx in prod → dialect shim. graphify → Task 5.

**Deferred to Plan 3 (correctly):** the scheduled CTAS runner that materializes these tables, rewriting `analytics_handler._ROUTE_QUERIES` to serve the marts (deleting the 5 dead dashboards), the GET routes, and date-range param handling (inline validated literals, gotcha #13).

**Type/name consistency:** `sessions_sql(d)` / `mart_sql(d)` both take a dialect Mapping and are imported by name in the tests. Column orders in `_sessions`/`_mart` test helpers match the SELECT projections. `fact_session` Glue columns (Task 4) match the `sessions_sql` projection plus `ts_start`/`ts_end` (which Plan 3's CTAS adds — note: Task 1's `sessions_sql` does not yet project `ts_start`/`ts_end`; Plan 3 extends the projection when wiring CTAS, OR add them now as `min(ts)`/`max(ts)` cast to string — implementer may add them in Task 1 for forward-compat, they are harmless to the current tests).

**Risk:** cross-midnight sessions are attributed to their start day (documented). Wall-clock time-per-track inflates on long pauses — blunted by using percentiles, per spec. The DuckDB↔Trino dialect boundary is isolated to four function fragments; the Trino render is smoke-checked (Task 3 Step 5) but only runs for real on Athena in Plan 3.

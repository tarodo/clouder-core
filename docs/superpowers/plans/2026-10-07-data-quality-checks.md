# Data Quality Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn "the pipeline ran" into "the data is right": a nightly job that measures freshness, completeness, integrity and plausibility of the catalog, publishes the numbers to CloudWatch and raises an alarm when a check fails.

**Architecture:** `collector.data_quality` holds the checks — each is one read-only SQL statement returning a single `value` plus a threshold. A new scheduled Lambda (`data_quality_handler`, own least-privilege role) runs them through the RDS Data API at 00:10 UTC, right after the nightly catalog export has woken Aurora, logs each result and publishes metrics to the `CLOUDER/DataQuality` namespace; an alarm fires on `FailedChecks ≥ 1`. `docs/data/data-quality.md` defines the SLOs and records before/after.

**Tech Stack:** Python 3.12, RDS Data API, CloudWatch metrics and alarms, EventBridge, Terraform, PostgreSQL 16 (`tests/db/` stand-in), pytest.

**Spec:** inline — "Spec" section below (source: hiring audit §15.3 "F").

## Global Constraints

- Runtime DB access only through the RDS Data API (ADR-0001); checks are read-only `SELECT`s.
- The new Lambda gets its own role: Data API on the cluster, read of the cluster secret, `cloudwatch:PutMetricData` limited to namespace `CLOUDER/DataQuality`, its own log group. No shared `collector_lambda` role.
- `log_event` keeps only `ALLOWED_LOG_FIELDS`; new fields must be added there.
- Schedule `cron(10 0 * * ? *)` (after the 00:00 UTC catalog export, which already wakes the auto-paused Aurora).
- Alarm actions follow the existing `var.alarm_sns_topic_arn` pattern (empty = no actions).
- No schema migrations; no money figures in docs.
- Branch `feat/data-quality-checks` from `origin/main`; commits and PR text via `caveman:caveman-commit`; `$VENV` = main repo `.venv/bin`; `terraform fmt` must pass (CI runs `fmt -check`).

## Spec

**Problem.** Pipeline health is watched (Lambda errors, DLQ depth, latency), data health is not. Nothing notices a style that silently stopped being ingested, a week with half the usual releases, ISRC or Spotify coverage sliding, identity rows pointing at nothing, or an ingest run stuck without a final status — on 2026-10-06 one such run was found only by a manual query.

**Checks** (value → pass rule):

| Check | Value | Pass |
|---|---|---|
| `stuck_ingest_runs` | runs not COMPLETED/FAILED, started > 2 h ago | ≤ 0 |
| `styles_behind` | active styles (ingested within 8 weeks) whose latest completed week ends before the latest Saturday-week that should be in (week end + 3 days grace) | ≤ 0 |
| `weekly_volume_anomalies` | styles whose latest week has < 50 % or > 200 % of the median of their previous 8 weeks (needs ≥ 4 weeks of history) | ≤ 0 |
| `isrc_coverage_pct` | % of tracks created in the last 30 days that have an ISRC | ≥ 99 |
| `spotify_match_pct` | % of tracks searched on Spotify in the last 30 days that were found | ≥ 95 |
| `spotify_unsearched_stale` | tracks older than 1 day never searched and without a Spotify id | ≤ 0 |
| `orphan_identities` | `identity_map` rows whose canonical row does not exist | ≤ 0 |
| `artists_without_identity` | canonical artists with no identity row (duplicate suspects) | recorded only |
| `bpm_out_of_range` | tracks with BPM outside 40–250 | ≤ 0 |
| `length_out_of_range` | tracks with length ≤ 0 or > 60 min | ≤ 0 |
| `review_backlog_days` | age of the oldest pending match review, days | ≤ 14 |

A check with nothing to measure (e.g. no tracks in the window) passes and publishes no metric. A check whose SQL fails counts as failed and is logged.

**Goals.** Checks + runner (tested on real Postgres); Lambda + metrics + alarm in Terraform; SLO doc with before/after; "after" = the first nightly run's published values (readable from CloudWatch without prod DB access).

**Non-goals.** A DQ framework (Great Expectations, dbt tests) — see ADR-0023; per-row reports; UI; schema changes.

**Success criteria.** All checks tested on Postgres; deploy creates the Lambda, schedule and alarm; first nightly run publishes all measurable checks; docs record the values.

## Review Focus

1. **A check's SQL fails at runtime** (e.g. Data API timeout) → that check is recorded as failed, the others still run. Test: `test_failing_check_is_recorded_and_others_run` (Task 1).
2. **Empty catalog / empty windows** → percentages are `None`, pass, and no metric is published. Tests: `test_empty_database_passes_with_nothing_to_measure` (Task 1), `test_publish_skips_checks_without_value` (Task 2).
3. **Saturday-week boundary** — the expected week end on a Friday, inside the grace days, and right after them. Test: `test_expected_week_end_respects_grace_days` (Task 1).
4. **Data API returns numbers as strings** (`round(numeric)`) → values become floats. Test: `test_values_are_floats_even_when_the_driver_returns_strings` (Task 1).
5. **Retried or custom-range runs** for the same week → counted once per (style, week end) in the volume check. Test: covered by `test_weekly_volume_anomalies_compares_latest_week_with_median` seeding a duplicate run (Task 1).

---

### Task 0: Branch and database

- [ ] Worktree `../clouder-core-dq` on `feat/data-quality-checks` from `origin/main`; copy this plan; Postgres `er-pg` on :55433 migrated (`$VENV/alembic upgrade head`); `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres`; commit the plan (`docs(plans): data quality checks plan`).

---

### Task 1: Checks and runner

**Files:**
- Create: `src/collector/data_quality.py`
- Test: `tests/db/test_data_quality_pg.py`, `tests/unit/test_data_quality.py`

**Interfaces:**
- Produces: `NAMESPACE = "CLOUDER/DataQuality"`; `Check(name, description, sql, comparison, threshold, params=())`; `CheckResult(name, value, threshold, comparison, passed)`; `CHECKS: tuple[Check, ...]`; `expected_week_end(today: date, grace_days: int = 3) -> date`; `run_checks(client, today: date, checks: Sequence[Check] = CHECKS) -> list[CheckResult]`; `check_by_name(name) -> Check`.

- [ ] **Step 1: Failing unit tests** — `tests/unit/test_data_quality.py`:

```python
"""Data-quality runner logic that needs no database."""

from __future__ import annotations

from datetime import date

from collector.data_quality import CHECKS, Check, expected_week_end, run_checks


def test_expected_week_end_respects_grace_days() -> None:
    # Saturday-weeks run Sat..Fri; a week is due 3 days after its Friday.
    assert expected_week_end(date(2026, 10, 5)) == date(2026, 10, 2)  # Mon: Fri + 3
    assert expected_week_end(date(2026, 10, 4)) == date(2026, 9, 25)  # Sun: still in grace
    assert expected_week_end(date(2026, 10, 9)) == date(2026, 10, 2)  # next Friday


class FakeClient:
    def __init__(self, values: dict[str, object], fail: set[str] = frozenset()) -> None:
        self.values, self.fail, self.calls = values, fail, []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append(params)
        name = next(n for n in self.values if f"/* {n} */" in sql)
        if name in self.fail:
            raise RuntimeError("boom")
        return [{"value": self.values[name]}]


def _check(name: str, comparison: str = "max", threshold: float | None = 0) -> Check:
    return Check(name=name, description=name, sql=f"/* {name} */ SELECT 1 AS value",
                 comparison=comparison, threshold=threshold)


def test_failing_check_is_recorded_and_others_run() -> None:
    client = FakeClient({"a": 0, "b": 0}, fail={"a"})

    results = run_checks(client, date(2026, 10, 7), checks=[_check("a"), _check("b")])

    assert [(r.name, r.passed, r.value) for r in results] == [("a", False, None), ("b", True, 0.0)]


def test_values_are_floats_even_when_the_driver_returns_strings() -> None:
    client = FakeClient({"pct": "99.50"})

    (result,) = run_checks(client, date(2026, 10, 7), checks=[_check("pct", "min", 99)])

    assert result.value == 99.5 and result.passed


def test_recorded_only_checks_never_fail() -> None:
    client = FakeClient({"info": 42})

    (result,) = run_checks(client, date(2026, 10, 7), checks=[_check("info", threshold=None)])

    assert result.passed and result.value == 42.0


def test_only_declared_params_are_sent() -> None:
    client = FakeClient({"p": 0})
    check = Check(name="p", description="p", sql="/* p */ SELECT 1 AS value",
                  comparison="max", threshold=0, params=("expected_end",))

    run_checks(client, date(2026, 10, 7), checks=[check])

    assert client.calls == [{"expected_end": date(2026, 10, 2)}]


def test_every_check_has_a_unique_name_and_a_known_comparison() -> None:
    names = [c.name for c in CHECKS]
    assert len(names) == len(set(names))
    assert {c.comparison for c in CHECKS} <= {"max", "min"}
```

- [ ] **Step 2: Failing PG tests** — `tests/db/test_data_quality_pg.py`:

```python
"""Each data-quality check's SQL against a real Postgres."""

from __future__ import annotations

from datetime import date

from collector.data_quality import CHECKS, check_by_name, run_checks

TODAY = date(2026, 10, 7)  # Wednesday; latest due Saturday-week ends Fri 2026-10-02


def _value(pg, name: str):
    (result,) = run_checks(pg, TODAY, checks=[check_by_name(name)])
    return result


def _run(pg, run_id, style_id, status="COMPLETED", items=100, period_end="2026-10-02",
         started="now()"):
    pg.execute(
        "INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, item_count, "
        f"started_at, period_end) VALUES (:id, 'beatport', :style, 'k', :status, :items, {started}, "
        "CAST(:end AS date))",
        {"id": run_id, "style": style_id, "status": status, "items": items, "end": period_end},
    )


def _track(pg, tid, *, created="now()", isrc="ISRC", searched="now()", spotify_id=None,
           bpm=None, length_ms=None):
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, isrc, bpm, length_ms, "
        f"spotify_id, spotify_searched_at, created_at, updated_at) VALUES (:id, 'T', 't', :isrc, "
        f":bpm, :len, :sp, {searched}, {created}, now())",
        {"id": tid, "isrc": isrc, "bpm": bpm, "len": length_ms, "sp": spotify_id},
    )


def test_stuck_ingest_runs(pg) -> None:
    _run(pg, "stuck", 1, status="RAW_SAVED", started="now() - INTERVAL '3 hours'")
    _run(pg, "fresh", 1, status="RAW_SAVED")
    _run(pg, "done", 1, started="now() - INTERVAL '3 hours'")

    result = _value(pg, "stuck_ingest_runs")

    assert result.value == 1.0 and not result.passed


def test_styles_behind(pg) -> None:
    _run(pg, "s1", 1, period_end="2026-10-02")   # up to date
    _run(pg, "s2", 2, period_end="2026-09-25")   # one week behind
    _run(pg, "s3", 3, period_end="2026-06-05")   # inactive: older than 8 weeks

    assert _value(pg, "styles_behind").value == 1.0


def test_weekly_volume_anomalies_compares_latest_week_with_median(pg) -> None:
    weeks = ["2026-08-28", "2026-09-04", "2026-09-11", "2026-09-18", "2026-09-25"]
    for i, end in enumerate(weeks):
        _run(pg, f"a{i}", 7, items=100, period_end=end)
        _run(pg, f"b{i}", 8, items=100, period_end=end)
    _run(pg, "a-retry", 7, items=90, period_end="2026-09-25")   # same week twice: counted once
    _run(pg, "a-latest", 7, items=30, period_end="2026-10-02")  # collapse: anomaly
    _run(pg, "b-latest", 8, items=110, period_end="2026-10-02")  # normal
    _run(pg, "c0", 9, items=100, period_end="2026-09-25")
    _run(pg, "c-latest", 9, items=5, period_end="2026-10-02")    # < 4 weeks of history: skipped

    assert _value(pg, "weekly_volume_anomalies").value == 1.0


def test_isrc_coverage_pct(pg) -> None:
    for i in range(3):
        _track(pg, f"ok{i}")
    _track(pg, "no-isrc", isrc=None)
    _track(pg, "old", isrc=None, created="now() - INTERVAL '60 days'")

    result = _value(pg, "isrc_coverage_pct")

    assert result.value == 75.0 and not result.passed


def test_spotify_match_pct(pg) -> None:
    _track(pg, "f1", spotify_id="sp1")
    _track(pg, "f2", spotify_id="sp2")
    _track(pg, "n1")
    _track(pg, "n2")

    assert _value(pg, "spotify_match_pct").value == 50.0


def test_spotify_unsearched_stale(pg) -> None:
    _track(pg, "stale", searched="NULL", created="now() - INTERVAL '2 days'")
    _track(pg, "new", searched="NULL")
    _track(pg, "imported", searched="NULL", spotify_id="sp", created="now() - INTERVAL '2 days'")

    assert _value(pg, "spotify_unsearched_stale").value == 1.0


def test_orphan_identities_and_artists_without_identity(pg) -> None:
    _track(pg, "t1")
    for aid in ("a1", "a2", "a3"):
        pg.execute(
            "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
            "VALUES (:id, 'A', 'a', now(), now())", {"id": aid},
        )
    for ext, kind, cid in (("1", "track", "t1"), ("2", "track", "missing"), ("3", "artist", "a1")):
        pg.execute(
            "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, "
            "clouder_id, match_type, confidence, first_seen_at, last_seen_at) VALUES "
            "('beatport', :kind, :ext, :kind, :cid, 'auto_create', 0.6, now(), now())",
            {"kind": kind, "ext": ext, "cid": cid},
        )

    assert _value(pg, "orphan_identities").value == 1.0
    info = _value(pg, "artists_without_identity")
    assert info.value == 2.0 and info.passed  # recorded only


def test_bpm_and_length_out_of_range(pg) -> None:
    _track(pg, "fast", bpm=300)
    _track(pg, "normal", bpm=128, length_ms=300000)
    _track(pg, "empty", length_ms=0)

    assert _value(pg, "bpm_out_of_range").value == 1.0
    assert _value(pg, "length_out_of_range").value == 1.0


def test_review_backlog_days(pg) -> None:
    _track(pg, "t1")
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
        "VALUES ('q1', 't1', 'ytmusic', '[]'::jsonb, 'pending', now() - INTERVAL '20 days')"
    )

    result = _value(pg, "review_backlog_days")

    assert result.value == 20.0 and not result.passed


def test_empty_database_passes_with_nothing_to_measure(pg) -> None:
    results = run_checks(pg, TODAY)

    assert all(r.passed for r in results)
    assert {r.name for r in results if r.value is None} >= {
        "isrc_coverage_pct", "spotify_match_pct", "review_backlog_days"}
    assert len(results) == len(CHECKS)
```

- [ ] **Step 3: Run both — RED**

Run: `TEST_DATABASE_URL=$TEST_DATABASE_URL PYTHONPATH=src $VENV/python -m pytest tests/unit/test_data_quality.py tests/db/test_data_quality_pg.py -q`
Expected: collection errors — `No module named 'collector.data_quality'`.

- [ ] **Step 4: Implement** — `src/collector/data_quality.py`:

```python
"""Nightly data-quality checks (docs/data/data-quality.md).

Each check is one read-only SQL statement returning a single `value`, compared
with a threshold: `max` passes when value <= threshold, `min` when value >=
threshold, `None` threshold is recorded only. A `None` value means there was
nothing to measure and passes. A check whose SQL fails is recorded as failed so
a broken check cannot hide behind a green run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Sequence

from .logging_utils import log_event

NAMESPACE = "CLOUDER/DataQuality"
FRESHNESS_GRACE_DAYS = 3
ACTIVE_STYLE_WINDOW_DAYS = 56  # 8 Saturday-weeks
_FRIDAY = 4


@dataclass(frozen=True)
class Check:
    name: str
    description: str
    sql: str
    comparison: str  # "max" | "min"
    threshold: float | None
    params: tuple[str, ...] = ()


@dataclass(frozen=True)
class CheckResult:
    name: str
    value: float | None
    threshold: float | None
    comparison: str
    passed: bool


CHECKS: tuple[Check, ...] = (
    Check(
        "stuck_ingest_runs",
        "Ingest runs without a final status two hours after they started.",
        """
        SELECT count(*) AS value
        FROM ingest_runs
        WHERE status NOT IN ('COMPLETED', 'FAILED')
          AND started_at < now() - INTERVAL '2 hours'
        """,
        "max", 0,
    ),
    Check(
        "styles_behind",
        "Active styles whose latest completed week ends before the week that is due.",
        """
        WITH active AS (
            SELECT style_id, max(period_end) AS last_end
            FROM ingest_runs
            WHERE status = 'COMPLETED' AND period_end IS NOT NULL
            GROUP BY style_id
            HAVING max(period_end) >= :since
        )
        SELECT count(*) AS value FROM active WHERE last_end < :expected_end
        """,
        "max", 0, ("since", "expected_end"),
    ),
    Check(
        "weekly_volume_anomalies",
        "Styles whose latest week has under half or over twice their 8-week median volume.",
        """
        WITH weekly AS (
            SELECT style_id, period_end, max(item_count) AS items
            FROM ingest_runs
            WHERE status = 'COMPLETED' AND period_end IS NOT NULL
            GROUP BY style_id, period_end
        ),
        ranked AS (
            SELECT style_id, items,
                   row_number() OVER (PARTITION BY style_id ORDER BY period_end DESC) AS rn
            FROM weekly
        ),
        baseline AS (
            SELECT style_id,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY items) AS median_items,
                   count(*) AS weeks
            FROM ranked
            WHERE rn BETWEEN 2 AND 9
            GROUP BY style_id
        )
        SELECT count(*) AS value
        FROM ranked l
        JOIN baseline b ON b.style_id = l.style_id
        WHERE l.rn = 1
          AND b.weeks >= 4
          AND (l.items < 0.5 * b.median_items OR l.items > 2 * b.median_items)
        """,
        "max", 0,
    ),
    Check(
        "isrc_coverage_pct",
        "Share of tracks created in the last 30 days that carry an ISRC.",
        """
        SELECT round(100.0 * count(*) FILTER (WHERE isrc IS NOT NULL) / nullif(count(*), 0), 2) AS value
        FROM clouder_tracks
        WHERE created_at >= now() - INTERVAL '30 days'
        """,
        "min", 99,
    ),
    Check(
        "spotify_match_pct",
        "Share of tracks searched on Spotify in the last 30 days that were found.",
        """
        SELECT round(100.0 * count(*) FILTER (WHERE spotify_id IS NOT NULL) / nullif(count(*), 0), 2) AS value
        FROM clouder_tracks
        WHERE spotify_searched_at >= now() - INTERVAL '30 days'
        """,
        "min", 95,
    ),
    Check(
        "spotify_unsearched_stale",
        "Tracks older than a day that were never searched on Spotify.",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE spotify_searched_at IS NULL
          AND spotify_id IS NULL
          AND created_at < now() - INTERVAL '1 day'
        """,
        "max", 0,
    ),
    Check(
        "orphan_identities",
        "identity_map rows whose canonical row does not exist.",
        """
        SELECT count(*) AS value
        FROM identity_map im
        WHERE NOT EXISTS (
            SELECT 1 FROM clouder_tracks t WHERE im.clouder_entity_type = 'track' AND t.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_artists a WHERE im.clouder_entity_type = 'artist' AND a.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_albums al WHERE im.clouder_entity_type = 'album' AND al.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_labels l WHERE im.clouder_entity_type = 'label' AND l.id = im.clouder_id
            UNION ALL
            SELECT 1 FROM clouder_styles s WHERE im.clouder_entity_type = 'style' AND s.id = im.clouder_id
        )
        """,
        "max", 0,
    ),
    Check(
        "artists_without_identity",
        "Canonical artists no source maps to — duplicate suspects (recorded only).",
        """
        SELECT count(*) AS value
        FROM clouder_artists a
        WHERE NOT EXISTS (
            SELECT 1 FROM identity_map im
            WHERE im.clouder_entity_type = 'artist' AND im.clouder_id = a.id
        )
        """,
        "max", None,
    ),
    Check(
        "bpm_out_of_range",
        "Tracks with a BPM outside 40-250.",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE bpm IS NOT NULL AND (bpm < 40 OR bpm > 250)
        """,
        "max", 0,
    ),
    Check(
        "length_out_of_range",
        "Tracks with a length of zero or over an hour.",
        """
        SELECT count(*) AS value
        FROM clouder_tracks
        WHERE length_ms IS NOT NULL AND (length_ms <= 0 OR length_ms > 3600000)
        """,
        "max", 0,
    ),
    Check(
        "review_backlog_days",
        "Age in days of the oldest pending match review.",
        """
        SELECT round(CAST(EXTRACT(EPOCH FROM now() - min(created_at)) / 86400.0 AS numeric), 1) AS value
        FROM match_review_queue
        WHERE status = 'pending'
        """,
        "max", 14,
    ),
)


def check_by_name(name: str) -> Check:
    return next(c for c in CHECKS if c.name == name)


def expected_week_end(today: date, grace_days: int = FRESHNESS_GRACE_DAYS) -> date:
    """End (Friday) of the latest Saturday-week that should already be ingested."""
    d = today - timedelta(days=grace_days)
    return d - timedelta(days=(d.weekday() - _FRIDAY) % 7)


def _passes(check: Check, value: float | None) -> bool:
    if value is None or check.threshold is None:
        return True
    return value <= check.threshold if check.comparison == "max" else value >= check.threshold


def run_checks(
    client: Any, today: date, checks: Sequence[Check] = CHECKS
) -> list[CheckResult]:
    expected_end = expected_week_end(today)
    context = {
        "expected_end": expected_end,
        "since": expected_end - timedelta(days=ACTIVE_STYLE_WINDOW_DAYS),
    }
    results: list[CheckResult] = []
    for check in checks:
        params = {name: context[name] for name in check.params} or None
        try:
            rows = client.execute(check.sql, params)
        except Exception as exc:  # a broken check must surface as a failure
            log_event(
                "ERROR", "dq_check_failed_to_run",
                check=check.name, error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            results.append(CheckResult(check.name, None, check.threshold, check.comparison, False))
            continue
        raw = rows[0].get("value") if rows else None
        value = float(raw) if raw is not None else None
        results.append(
            CheckResult(check.name, value, check.threshold, check.comparison, _passes(check, value))
        )
    return results
```

Add to `ALLOWED_LOG_FIELDS` in `src/collector/logging_utils.py` (after `"released_count",`):

```python
    # Data-quality checks (collector.data_quality).
    "check",
    "value",
    "threshold",
    "passed",
    "failed_checks",
```

- [ ] **Step 5: GREEN + SQL grammar** — `TEST_DATABASE_URL=$TEST_DATABASE_URL PYTHONPATH=src $VENV/python -m pytest tests/unit/test_data_quality.py tests/db/test_data_quality_pg.py tests/unit/test_raw_sql_parses.py -q` → all pass. (The raw-SQL test only collects literal first arguments of `execute`; the checks pass SQL through a variable, so the PG tests are their grammar check.)

- [ ] **Step 6: Commit** — `feat(data-quality): nightly catalog checks`

---

### Task 2: Lambda handler and metric publishing

**Files:**
- Create: `src/collector/data_quality_handler.py`
- Test: `tests/unit/test_data_quality_handler.py`

**Interfaces:**
- Consumes: `run_checks`, `CheckResult`, `NAMESPACE` (Task 1); `collector.settings.get_data_api_settings()`; `collector.data_api.create_default_data_api_client`.
- Produces: `publish(results, cloudwatch, *, now) -> int` (failed count); `lambda_handler(event, context) -> dict` with keys `failed_checks`, `results`.

- [ ] **Step 1: Failing tests** — `tests/unit/test_data_quality_handler.py`:

```python
"""Publishing data-quality results and the Lambda entry point."""

from __future__ import annotations

from datetime import datetime, timezone

from collector import data_quality_handler
from collector.data_quality import CheckResult
from collector.settings import reset_settings_cache

NOW = datetime(2026, 10, 7, 0, 10, tzinfo=timezone.utc)


class FakeCloudWatch:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def put_metric_data(self, **kwargs) -> None:
        self.calls.append(kwargs)


def _results() -> list[CheckResult]:
    return [
        CheckResult("stuck_ingest_runs", 1.0, 0, "max", False),
        CheckResult("isrc_coverage_pct", None, 99, "min", True),
        CheckResult("spotify_match_pct", 96.9, 95, "min", True),
    ]


def test_publish_skips_checks_without_value() -> None:
    cw = FakeCloudWatch()

    failed = data_quality_handler.publish(_results(), cw, now=NOW)

    (call,) = cw.calls
    assert call["Namespace"] == "CLOUDER/DataQuality"
    assert [(m["MetricName"], m["Value"]) for m in call["MetricData"]] == [
        ("stuck_ingest_runs", 1.0), ("spotify_match_pct", 96.9), ("FailedChecks", 1)]
    assert failed == 1


def test_handler_runs_checks_publishes_and_reports(monkeypatch) -> None:
    cw = FakeCloudWatch()
    monkeypatch.setenv("AURORA_CLUSTER_ARN", "arn:aws:rds:us-east-1:000000000000:cluster:c")
    monkeypatch.setenv("AURORA_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:000000000000:secret:s")
    monkeypatch.setenv("AURORA_DATABASE", "clouder")
    reset_settings_cache()  # get_data_api_settings is lru_cached
    monkeypatch.setattr(data_quality_handler, "create_default_data_api_client", lambda **_: object())
    monkeypatch.setattr(data_quality_handler, "run_checks", lambda client, today: _results())
    monkeypatch.setattr(data_quality_handler, "_cloudwatch", lambda: cw)

    out = data_quality_handler.lambda_handler({}, None)

    assert out["failed_checks"] == 1
    assert [r["name"] for r in out["results"]] == ["stuck_ingest_runs", "isrc_coverage_pct", "spotify_match_pct"]
    assert len(cw.calls) == 1
    reset_settings_cache()
```

- [ ] **Step 2: RED** — `PYTHONPATH=src $VENV/python -m pytest tests/unit/test_data_quality_handler.py -q` → `ImportError` (no `data_quality_handler`).

- [ ] **Step 3: Implement** — `src/collector/data_quality_handler.py`:

```python
"""Scheduled Lambda: run the data-quality checks and publish them to CloudWatch.

EventBridge triggers it nightly at 00:10 UTC, right after the catalog export
has woken Aurora. Read-only; its own role may only call the Data API, read the
cluster secret and put metrics into the CLOUDER/DataQuality namespace.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from .data_api import create_default_data_api_client
from .data_quality import NAMESPACE, CheckResult, run_checks
from .logging_utils import log_event
from .settings import get_data_api_settings


def _cloudwatch() -> Any:
    import boto3

    return boto3.client("cloudwatch")


def publish(results: Sequence[CheckResult], cloudwatch: Any, *, now: datetime) -> int:
    failed = sum(1 for r in results if not r.passed)
    metric_data = [
        {"MetricName": r.name, "Value": r.value, "Unit": "None", "Timestamp": now}
        for r in results
        if r.value is not None
    ]
    metric_data.append({"MetricName": "FailedChecks", "Value": failed, "Unit": "Count", "Timestamp": now})
    cloudwatch.put_metric_data(Namespace=NAMESPACE, MetricData=metric_data)
    return failed


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    now = datetime.now(timezone.utc)
    results = run_checks(client, now.date())
    for r in results:
        log_event(
            "INFO" if r.passed else "WARNING", "dq_check_result",
            check=r.name, value=r.value, threshold=r.threshold, passed=r.passed,
        )
    failed = publish(results, _cloudwatch(), now=now)
    log_event("INFO", "dq_run_completed", failed_checks=failed, count=len(results))
    return {"failed_checks": failed, "results": [asdict(r) for r in results]}
```

- [ ] **Step 4: GREEN** — same command → 2 passed. Full suite green.

- [ ] **Step 5: Commit** — `feat(data-quality): scheduled lambda and metrics`

---

### Task 3: Infrastructure

**Files:**
- Create: `infra/data_quality.tf`
- Modify: `infra/alarms.tf` (`local.worker_lambdas` gets `data_quality`)

- [ ] **Step 1: Write `infra/data_quality.tf`**

```hcl
# ── Nightly data-quality checks (docs/data/data-quality.md) ──
# Own least-privilege role: Data API on the cluster, the cluster secret, and
# PutMetricData only into the CLOUDER/DataQuality namespace.

locals {
  data_quality_lambda_name = "${local.name_prefix}-data-quality"
  data_quality_namespace   = "CLOUDER/DataQuality"
}

resource "aws_cloudwatch_log_group" "data_quality" {
  name              = "/aws/lambda/${local.data_quality_lambda_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "data_quality" {
  name               = "${local.name_prefix}-data-quality-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "data_quality" {
  statement {
    sid       = "AllowOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.data_quality.arn}:*"]
  }
  statement {
    sid       = "AllowRdsDataApiRead"
    effect    = "Allow"
    actions   = ["rds-data:ExecuteStatement"]
    resources = [aws_rds_cluster.aurora.arn]
  }
  statement {
    sid       = "AllowReadDatabaseSecret"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "*")]
  }
  statement {
    sid       = "AllowPutDataQualityMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [local.data_quality_namespace]
    }
  }
}

resource "aws_iam_role_policy" "data_quality" {
  name   = "${local.name_prefix}-data-quality-policy"
  role   = aws_iam_role.data_quality.id
  policy = data.aws_iam_policy_document.data_quality.json
}

resource "aws_lambda_function" "data_quality" {
  function_name    = local.data_quality_lambda_name
  role             = aws_iam_role.data_quality.arn
  runtime          = "python3.12"
  handler          = "collector.data_quality_handler.lambda_handler"
  filename         = local.lambda_zip_file
  timeout          = 120
  memory_size      = 256
  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN  = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE    = var.aurora_database_name
      LOG_LEVEL          = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.data_quality]
}

# 00:10 UTC: ten minutes after the catalog export, which already wakes Aurora.
resource "aws_cloudwatch_event_rule" "data_quality_daily" {
  name                = "${local.name_prefix}-data-quality-daily"
  schedule_expression = "cron(10 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "data_quality_daily" {
  rule      = aws_cloudwatch_event_rule.data_quality_daily.name
  target_id = "data-quality"
  arn       = aws_lambda_function.data_quality.arn
}

resource "aws_lambda_permission" "data_quality_events" {
  statement_id  = "AllowExecutionFromEventBridgeDataQuality"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.data_quality.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.data_quality_daily.arn
}

resource "aws_cloudwatch_metric_alarm" "data_quality_failed_checks" {
  alarm_name          = "${local.name_prefix}-data-quality-failed-checks"
  alarm_description   = "At least one nightly data-quality check failed — see docs/data/data-quality.md"
  namespace           = local.data_quality_namespace
  metric_name         = "FailedChecks"
  statistic           = "Maximum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "missing"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}
```

In `infra/alarms.tf`, add to `worker_lambdas`: `data_quality = aws_lambda_function.data_quality.function_name` (keeps the existing alignment).

- [ ] **Step 2: Format** — `terraform -chdir=infra fmt` (if terraform is installed locally); then `terraform -chdir=infra fmt -check` → no output. If terraform is not installed, CI's `fmt -check` is the gate — keep the alignment exactly as shown.

- [ ] **Step 3: Commit** — `feat(infra): nightly data-quality lambda and alarm`

---

### Task 4: Docs and ADR

**Files:**
- Create: `docs/data/data-quality.md`, `docs/adr/0023-sql-data-quality-checks.md`
- Modify: `docs/data/README.md` (link), `docs/adr/README.md` (index row, next free → `0024`)

- [ ] **Step 1: `docs/data/data-quality.md`** — sections: **Why** (pipeline health is watched, data health was not; the stuck run found by hand on 2026-10-06); **Checks** (the table from the Spec, plus "why it matters" per row); **SLOs** (freshness: every active style's week ingested within 3 days of its close; completeness: ISRC ≥ 99 %, Spotify match ≥ 95 % over 30 days; integrity: 0 orphan identities, 0 stuck runs; plausibility: 0 out-of-range BPM/length; operations: oldest pending review ≤ 14 days); **How it runs** (EventBridge 00:10 UTC → Lambda → Data API → `CLOUDER/DataQuality` metrics + `dq_check_result` logs → alarm `clouder-prod-data-quality-failed-checks` on `FailedChecks ≥ 1`; SNS only if `alarm_sns_topic_arn` is set); **Before** (no data checks; known by hand: 1 ingest run without a final status); **After** ("filled from the first nightly run (CloudWatch metrics)"); **What it buys**; **How to read the numbers** (`aws cloudwatch get-metric-statistics --namespace CLOUDER/DataQuality --metric-name <check> ...`; Logs Insights on `dq_check_result`). No money figures.

- [ ] **Step 2: ADR-0023** — Context (need data checks; options: Great Expectations / dbt tests / Deequ vs plain SQL checks), Decision (SQL checks in Python, run by a scheduled Lambda through the Data API, CloudWatch as the metric store and alert channel), Consequences (no new runtime or service; checks live next to the code and are tested on Postgres; trends come from CloudWatch's 15-month retention; revisit if E brings dbt — its tests could absorb row-level checks).

- [ ] **Step 3: Links, money check, commit** — README rows; `grep -nE '\$[0-9]|USD|/month' docs/data/data-quality.md docs/adr/0023-sql-data-quality-checks.md` prints nothing; commit `docs(data): data quality SLOs and ADR-0023`.

---

### Task 5: Ship and measure

- [ ] Final whole-branch review (fresh reviewer), fix Critical/Important; graphify refresh commit.
- [ ] PR (via `caveman:caveman-commit`), checks (incl. terraform plan), merge, Deploy green, cleanup.
- [ ] Confirm deploy: `aws lambda get-function-configuration --function-name clouder-prod-data-quality`, `aws events describe-rule --name clouder-prod-data-quality-daily`.
- [ ] After the first nightly run (≥ 00:10 UTC next day): read `CLOUDER/DataQuality` metrics and `dq_run_completed` logs; fill "After" in `docs/data/data-quality.md` via a docs PR; audit §15.3 F status.

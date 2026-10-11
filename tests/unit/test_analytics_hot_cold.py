"""History from silver, the last day live from bronze: each event counted once."""

from __future__ import annotations

from datetime import UTC, date, datetime

import duckdb
import pytest

from collector import analytics_handler as ah
from collector.analytics_handler import DUCKDB

COLS = (
    "event_id VARCHAR, user_id VARCHAR, dt VARCHAR, ts_client VARCHAR, event_name VARCHAR, "
    "track_id VARCHAR, duration_ms BIGINT, source VARCHAR"
)
ROWS = [
    ("e1", "u1", "2026-10-03", "2026-10-03T10:00:00.000Z", "playback_play", "t1", 60000, "triage_player"),
    ("e2", "u1", "2026-10-03", "2026-10-03T10:00:30.000Z", "playback_pause", "t1", None, "triage_player"),
    ("e3", "u1", "2026-10-04", "2026-10-04T10:00:00.000Z", "playback_play", "t2", 60000, "triage_player"),
    ("e4", "u1", "2026-10-04", "2026-10-04T10:00:20.000Z", "playback_pause", "t2", None, "triage_player"),
]


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA clouder_silver")
    c.execute(f"CREATE TABLE bronze_events ({COLS})")
    c.execute(f"CREATE TABLE clouder_silver.events ({COLS})")
    c.executemany("INSERT INTO bronze_events VALUES (?,?,?,?,?,?,?,?)", ROWS)
    # as in production, silver also holds the cutoff day; bronze has everything
    c.executemany("INSERT INTO clouder_silver.events VALUES (?,?,?,?,?,?,?,?)", ROWS)
    yield c
    c.close()


def _listening(con, table: str) -> dict:
    w = ah.listening_windows(datetime(2026, 10, 4, 12, tzinfo=UTC), 0)
    sql = ah.listening_sql(
        DUCKDB,
        scan_from=w["scan_from"].isoformat(),
        week_from=w["week_from"].isoformat(),
        month_from=w["month_from"].isoformat(),
        tz_offset_min=0,
        table=table,
    )
    cur = con.execute(sql, ["u1"])
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, (None if v is None else str(v) for v in r))) for r in cur.fetchall()]
    return ah.shape_listening(rows, w["today"])


def test_hot_cold_source_counts_each_event_once(con) -> None:
    bronze_only = _listening(con, "bronze_events")

    hot_cold = _listening(con, ah.events_source("clouder_silver.events", "2026-10-04"))

    assert hot_cold == bronze_only
    assert hot_cold["totals"]["week"] == {"listened_ms": 50000, "tracks": 2}


@pytest.mark.parametrize(
    "table, cutoff", [("events; drop", "2026-10-04"), ("clouder_silver.events", "10/04")]
)
def test_events_source_rejects_unsafe_input(table, cutoff) -> None:
    with pytest.raises(ah.AnalyticsError):
        ah.events_source(table, cutoff)


def test_events_table_defaults_to_bronze(monkeypatch) -> None:
    monkeypatch.delenv("SILVER_EVENTS_TABLE", raising=False)
    assert ah.events_table(date(2026, 10, 4)) == "bronze_events"


def test_events_table_reads_a_three_day_bronze_tail(monkeypatch) -> None:
    # The nightly build may miss nights; the tail covers its lookback plus two
    # missed builds instead of silently dropping days from the cards.
    monkeypatch.setenv("SILVER_EVENTS_TABLE", "clouder_silver.events")
    assert ah.events_table(date(2026, 10, 4)) == ah.events_source("clouder_silver.events", "2026-10-01")

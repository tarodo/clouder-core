from __future__ import annotations

import duckdb
import pytest

from collector.analytics_rollup import DUCKDB, mart_sql, sessions_sql

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
    # non-boundary event mid-play: must NOT cut t6's listen window (boundary = play/ended/skip).
    ("e11b", "u1", "2026-06-29T11:01:00Z", "playback_pause", "t6", "category_player", None, None, None, None, None),
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


# ---------------------------------------------------------------------------
# Task 2: fact_session metrics
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Task 3: mart_user_daily aggregation
# ---------------------------------------------------------------------------

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
    # category time-per-track = wall-clock to next TERMINAL event:
    # t5->t6 play = 50000; t6->ended = 40000 (the 11:01:00 pause is non-boundary,
    # so it does NOT cut t6's window to 10000). [50000, 40000] -> p50 45000.
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

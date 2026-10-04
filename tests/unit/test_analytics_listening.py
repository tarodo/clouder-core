from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from collector import analytics_handler as ah
from collector.analytics_rollup import DUCKDB

# (event_id, user_id, dt, ts_server, ts_client, event_name, track_id, duration_ms)
# ts_server is per SDK batch; gaps must come from ts_client.
_B = "2026-10-04T10:12:00+00:00"  # one batch stamp shared by e1..e4
_ROWS = [
    # t1: next play 2 min later -> 120s
    ("e1", "u1", "2026-10-04", _B, "2026-10-04T10:00:00.000Z", "playback_play", "t1", 300000),
    # t2: next play 8 min later -> capped at its 60s duration
    ("e2", "u1", "2026-10-04", _B, "2026-10-04T10:02:00.000Z", "playback_play", "t2", 60000),
    ("e3", "u1", "2026-10-04", _B, "2026-10-04T10:05:00.000Z", "playback_seek", "t2", None),
    # t1 again: next play is days later -> capped at 300s
    ("e4", "u1", "2026-10-04", _B, "2026-10-04T10:10:00.000Z", "playback_play", "t1", 300000),
    # unknown duration, last play -> 10-min fallback; 23:30Z = next local day at +180
    ("e5", "u1", "2026-10-05", "2026-10-05T23:30:05+00:00", "2026-10-05T23:30:00.000Z", "playback_play", "t3", 0),
    # other user: excluded
    ("e6", "u2", "2026-10-04", _B, "2026-10-04T10:00:00.000Z", "playback_play", "t9", 300000),
    # before the month window: excluded from totals
    ("e7", "u1", "2026-08-01", "2026-08-01T10:00:00+00:00", "2026-08-01T10:00:00.000Z", "playback_play", "t8", 300000),
]


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE bronze_events (event_id VARCHAR, user_id VARCHAR, dt VARCHAR, "
        "ts_server VARCHAR, ts_client VARCHAR, event_name VARCHAR, track_id VARCHAR, "
        "duration_ms BIGINT)"
    )
    c.executemany("INSERT INTO bronze_events VALUES (?,?,?,?,?,?,?,?)", _ROWS)
    yield c
    c.close()


def _run(con, today: date, off: int) -> dict:
    w = ah.listening_windows(datetime(today.year, today.month, today.day, 12, tzinfo=timezone.utc), 0)
    sql = ah.listening_sql(
        DUCKDB,
        scan_from=w["scan_from"].isoformat(),
        week_from=w["week_from"].isoformat(),
        month_from=w["month_from"].isoformat(),
        tz_offset_min=off,
    )
    cur = con.execute(sql, ["u1"])
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, (None if v is None else str(v) for v in r))) for r in cur.fetchall()]
    return ah.shape_listening(rows, w["today"])


def test_listening_minutes_and_tracks_per_window(con):
    out = _run(con, date(2026, 10, 6), 180)
    by_dt = {d["dt"]: d for d in out["daily"]}
    assert by_dt["2026-10-04"] == {"dt": "2026-10-04", "listened_ms": 480000, "tracks": 2}
    # 23:30Z + 3h lands on the local 6th
    assert by_dt["2026-10-06"] == {"dt": "2026-10-06", "listened_ms": 600000, "tracks": 1}
    assert out["totals"]["day"] == {"listened_ms": 600000, "tracks": 1}
    assert out["totals"]["week"] == {"listened_ms": 1080000, "tracks": 3}
    assert out["totals"]["month"] == {"listened_ms": 1080000, "tracks": 3}
    assert len(out["daily"]) == 30
    assert out["daily"][-1]["dt"] == "2026-10-06"


def test_utc_offset_zero_keeps_late_play_on_utc_day(con):
    out = _run(con, date(2026, 10, 6), 0)
    by_dt = {d["dt"]: d for d in out["daily"]}
    assert by_dt["2026-10-05"]["listened_ms"] == 600000
    assert out["totals"]["day"] == {"listened_ms": 0, "tracks": 0}


def test_listening_windows_use_local_today():
    w = ah.listening_windows(datetime(2026, 10, 5, 22, 30, tzinfo=timezone.utc), 180)
    assert w["today"] == date(2026, 10, 6)
    assert w["week_from"] == date(2026, 9, 30)
    assert w["month_from"] == date(2026, 9, 7)
    assert w["scan_from"] == date(2026, 9, 6)


@pytest.mark.parametrize("raw", ["abc", "900", "-841", "1.5", "180;--"])
def test_tz_offset_rejects_bad_input(raw):
    with pytest.raises(ah.AnalyticsError) as exc:
        ah.parse_tz_offset(raw)
    assert exc.value.status_code == 400


def test_tz_offset_defaults_to_utc():
    assert ah.parse_tz_offset(None) == 0
    assert ah.parse_tz_offset("-300") == -300

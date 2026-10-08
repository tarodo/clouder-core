from __future__ import annotations

import duckdb
import pytest

from collector import analytics_handler as ah

_D = "2026-10-05"
# (event_id, track_id, source, ts_client, duration_ms) — all playback_play, user u1.
# Listen time = gap to the next play (no pause events here), last one capped by duration.
_PLAYS = [
    ("e1", "t1", "triage_player", "10:00:00", 600000),    # -> 6s   House
    ("e2", "t2", "triage_player", "10:00:06", 600000),    # -> 10s  House
    ("e3", "t3", "triage_player", "10:00:16", 600000),    # -> 44s  Techno
    ("e4", "t1", "category_player", "10:01:00", 600000),  # -> 60s  House
    ("e5", "t9", "playlist_player", "10:02:00", 600000),  # -> 180s no style in dict
    ("e6", "t2", "playlist_player", "10:05:00", 200000),  # -> 200s House (last: duration)
]


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE bronze_events (event_id VARCHAR, user_id VARCHAR, dt VARCHAR, "
        "ts_server VARCHAR, ts_client VARCHAR, event_name VARCHAR, track_id VARCHAR, "
        "source VARCHAR, duration_ms BIGINT)"
    )
    c.executemany(
        "INSERT INTO bronze_events VALUES (?,?,?,?,?,?,?,?,?)",
        [(e, "u1", _D, f"{_D}T10:10:00+00:00", f"{_D}T{t}.000Z", "playback_play", tr, src, dur)
         for e, tr, src, t, dur in _PLAYS]
        + [("x1", "u2", _D, f"{_D}T10:10:00+00:00", f"{_D}T10:00:00.000Z", "playback_play", "t1", "triage_player", 1)],
    )
    c.execute(
        "CREATE TABLE bronze_catalog_export (id VARCHAR, style_id VARCHAR, name VARCHAR, "
        "tbl VARCHAR, snapshot_dt VARCHAR)"
    )
    c.executemany(
        "INSERT INTO bronze_catalog_export VALUES (?,?,?,?,?)",
        [
            ("t1", "H", None, "clouder_tracks", _D),
            ("t2", "H", None, "clouder_tracks", _D),
            ("t3", "T", None, "clouder_tracks", _D),
            ("H", None, "House", "clouder_styles", _D),
            ("T", None, "Techno", "clouder_styles", _D),
        ],
    )
    yield c
    c.close()


def _run(con) -> dict:
    sql = ah.time_per_track_sql(ah.DUCKDB, scan_from="2026-09-06", dict_from="2026-10-03")
    cur = con.execute(sql, ["u1"])
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, (None if v is None else str(v) for v in r))) for r in cur.fetchall()]
    return ah.shape_time_per_track(rows, days=30)


def test_stage_by_style_percentiles(con):
    out = _run(con)
    assert out["days"] == 30
    by = {r["style_id"]: r for r in out["rows"]}
    # all styles first, then by total plays desc, unknown style last
    assert [r["style_id"] for r in out["rows"]] == ["*", "H", "T", None]
    assert by["H"]["style_name"] == "House"
    assert by["H"]["cells"]["triage"] == {"n": 2, "p50_ms": 8000, "p90_ms": 9600}
    assert by["H"]["cells"]["category"] == {"n": 1, "p50_ms": 60000, "p90_ms": 60000}
    assert by["H"]["cells"]["playlist"] == {"n": 1, "p50_ms": 200000, "p90_ms": 200000}
    assert by["T"]["cells"]["triage"]["n"] == 1
    assert by["T"]["cells"]["category"] is None
    assert by[None]["cells"]["playlist"] == {"n": 1, "p50_ms": 180000, "p90_ms": 180000}
    assert by["*"]["cells"]["triage"] == {"n": 3, "p50_ms": 10000, "p90_ms": 37200}
    assert by["*"]["cells"]["playlist"]["n"] == 2


def test_days_param_is_validated():
    assert ah.parse_days(None) == 30
    assert ah.parse_days("90") == 90
    for bad in ("7", "abc", "-30"):
        with pytest.raises(ah.AnalyticsError):
            ah.parse_days(bad)


def _event(*, is_admin=False, qs=None):
    return {
        "rawPath": "/v1/analytics/time-per-track",
        "requestContext": {
            "requestId": "r",
            "routeKey": "GET /v1/analytics/time-per-track",
            "authorizer": {"lambda": {"user_id": "me", "is_admin": is_admin}},
        },
        "headers": {},
        "queryStringParameters": qs,
    }


def test_route_is_personal(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(ah, "_client", lambda: None)
    monkeypatch.setattr(ah, "_run_athena", lambda c, sql, params, **kw: seen.extend(params) or [])
    ok = ah.lambda_handler(_event(qs={"days": "90"}), None)
    assert ok["statusCode"] == 200 and seen == ["me"]
    assert ah.lambda_handler(_event(qs={"user_id": "other"}), None)["statusCode"] == 403
    assert ah.lambda_handler(_event(is_admin=True, qs={"user_id": "other"}), None)["statusCode"] == 200
    assert seen == ["me", "other"]

"""The play rule lives twice: analytics_handler._plays_cte (the cards, live) and
dbt's gold.fct_play (nightly). The dbt unit test fct_play_follows_the_play_rule is
their shared contract: dbt runs its rows in CI, this test runs them through the
Lambda SQL, and both must produce the same plays."""

from __future__ import annotations

from pathlib import Path

import duckdb
import yaml

from collector import analytics_handler as ah
from collector.analytics_handler import DUCKDB

ROOT = Path(__file__).resolve().parents[2]
_CONTRACT = "fct_play_follows_the_play_rule"
_COLS = (
    "event_id",
    "user_id",
    "dt",
    "ts_client",
    "event_name",
    "track_id",
    "duration_ms",
    "source",
)


def _contract() -> tuple[list[dict], list[dict]]:
    spec = yaml.safe_load((ROOT / "dbt/models/gold/_gold.yml").read_text(encoding="utf-8"))
    test = next(t for t in spec["unit_tests"] if t["name"] == _CONTRACT)
    events = next(g["rows"] for g in test["given"] if g["input"] == "ref('events')")
    return events, test["expect"]["rows"]


def test_lambda_plays_match_the_dbt_contract() -> None:
    events, expected = _contract()
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE events (event_id VARCHAR, user_id VARCHAR, dt VARCHAR, ts_client VARCHAR, "
        "event_name VARCHAR, track_id VARCHAR, duration_ms BIGINT, source VARCHAR)"
    )
    con.executemany(
        f"INSERT INTO events VALUES ({', '.join('?' * len(_COLS))})",
        [tuple(e[c] for c in _COLS) for e in events],
    )
    sql = f"WITH {ah._plays_cte(DUCKDB, scan_from='2026-10-01', table='events')} SELECT track_id, stage, ts, ms FROM plays"
    got = [
        {
            "user_id": user,
            "track_id": track_id,
            "stage": stage,
            "played_at": ts and ts.strftime("%Y-%m-%d %H:%M:%S"),
            "ms": int(ms),
        }
        for user in sorted({e["user_id"] for e in events})
        for track_id, stage, ts, ms in con.execute(sql, [user]).fetchall()
    ]
    key = lambda p: (p["user_id"], p["played_at"] or "")  # noqa: E731
    assert sorted(got, key=key) == sorted(expected, key=key)

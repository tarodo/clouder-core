"""Auto-ingest settings, lease, attempts and planning state on a real Postgres."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from collector.auto_ingest_repository import AutoIngestRepository

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def repo(pg):
    pg.execute("TRUNCATE auto_ingest_attempts")
    pg.execute("DELETE FROM auto_ingest_settings")
    pg.execute("INSERT INTO auto_ingest_settings (id, updated_at) VALUES (1, now())")
    return AutoIngestRepository(pg)


def _style(pg, clouder_id: str, bp_id: int, *, hidden: bool = False) -> None:
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at, is_hidden) "
        "VALUES (:id, :n, :n, now(), now(), :h)",
        {"id": clouder_id, "n": f"style {bp_id}", "h": hidden},
    )
    pg.execute(
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, clouder_id, "
        "match_type, confidence, first_seen_at, last_seen_at) "
        "VALUES ('beatport', 'style', :ext, 'style', :id, 'auto_create', 0.6, now(), now())",
        {"ext": str(bp_id), "id": clouder_id},
    )


def _run(pg, run_id, style, week, status, started_at, *, custom=False, week_year=2026):
    pg.execute(
        "INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, started_at, "
        "week_year, week_number, is_custom_range) "
        "VALUES (:r, 'beatport', :s, 'k', :st, CAST(:t AS TIMESTAMPTZ), :wy, :wn, :c)",
        {"r": run_id, "s": style, "st": status, "t": started_at.isoformat(), "wy": week_year,
         "wn": week, "c": custom},
    )


def test_settings_default_and_round_trip(repo) -> None:
    s = repo.get_settings()
    assert (s["enabled"], s["mode"], s["runs_per_day"], s["periods_per_run"]) == (False, "random", 3, 3)
    assert s["fixed_times"] == ["09:00", "15:00", "21:00"] and s["backfill_floor"] == "2026-01-03"

    saved = repo.save_settings(
        {"enabled": True, "mode": "fixed", "fixed_times": ["08:30", "20:00"], "runs_per_day": 5,
         "timezone": "Asia/Dubai", "periods_per_run": 4, "backfill_floor": date(2025, 6, 1)},
        user_id="u1", now=NOW,
    )

    assert saved["mode"] == "fixed" and saved["fixed_times"] == ["08:30", "20:00"]
    assert saved["timezone"] == "Asia/Dubai" and saved["backfill_floor"] == "2025-06-01"
    repo.set_plan(["2026-10-07T13:00:00+00:00"], NOW)
    repo.set_last_run({"pairs": [{"style_id": 1, "ok": True}]})
    again = repo.get_settings()
    assert again["planned_runs"] == ["2026-10-07T13:00:00+00:00"]
    assert again["last_run"] == {"pairs": [{"style_id": 1, "ok": True}]}


def test_lease_is_exclusive_until_it_expires(repo) -> None:
    assert repo.acquire_lease(NOW) is True
    assert repo.acquire_lease(NOW + timedelta(minutes=5)) is False
    assert repo.acquire_lease(NOW + timedelta(minutes=16)) is True
    repo.release_lease()
    assert repo.acquire_lease(NOW + timedelta(minutes=17)) is True


def test_planning_state_counts_only_what_is_ingested_or_pending(pg, repo) -> None:
    _style(pg, "s-81", 81)
    _style(pg, "s-96", 96)
    _style(pg, "s-5", 5, hidden=True)
    _run(pg, "done", 81, 39, "COMPLETED", NOW - timedelta(days=2))
    _run(pg, "pending", 81, 38, "RAW_SAVED", NOW - timedelta(hours=1))
    _run(pg, "stale", 81, 37, "RAW_SAVED", NOW - timedelta(hours=8))
    _run(pg, "failed", 96, 39, "FAILED", NOW - timedelta(hours=1))
    _run(pg, "custom", 96, 38, "COMPLETED", NOW - timedelta(hours=1), custom=True)

    state = repo.planning_state(NOW)

    assert state.styles == (81, 96)
    assert state.loaded == frozenset({(81, 2026, 39), (81, 2026, 38)})


def test_three_failed_attempts_make_a_pair_stuck(repo) -> None:
    for minutes in (0, 1):
        repo.record_attempt(81, 2026, 30, ok=False, run_id=None, error="UpstreamUnavailableError",
                            at=NOW + timedelta(minutes=minutes))
    assert repo.planning_state(NOW).stuck == frozenset()

    repo.record_attempt(81, 2026, 30, ok=False, run_id=None, error="UpstreamUnavailableError",
                        at=NOW + timedelta(minutes=2))
    assert repo.planning_state(NOW).stuck == frozenset({(81, 2026, 30)})
    (pair,) = repo.stuck_pairs()
    assert (pair["style_id"], pair["last_error"]) == (81, "UpstreamUnavailableError")

    repo.record_attempt(81, 2026, 30, ok=True, run_id="r1", error=None, at=NOW + timedelta(minutes=3))
    assert repo.planning_state(NOW).stuck == frozenset()

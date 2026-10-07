"""The planner replays the run behind each raw object — the latest one written to its key."""

from __future__ import annotations

from datetime import date

from collector.repositories import ClouderRepository


def _run(pg, run_id, key, started_at, style_id, period_end, status="COMPLETED"):
    pg.execute(
        """
        INSERT INTO ingest_runs (run_id, source, style_id, raw_s3_key, status, started_at, period_end)
        VALUES (:run_id, 'beatport', :style_id, :key, :status, CAST(:started_at AS TIMESTAMPTZ),
                CAST(:period_end AS DATE))
        """,
        {
            "run_id": run_id, "style_id": style_id, "key": key, "status": status,
            "started_at": started_at, "period_end": period_end,
        },
    )


def test_list_replayable_runs_picks_latest_run_per_raw_object(pg) -> None:
    _run(pg, "a-old", "k/a", "2026-09-01 10:00+00", 1, "2026-08-28")
    _run(pg, "a-new", "k/a", "2026-09-05 10:00+00", 1, "2026-08-28", status="FAILED")
    _run(pg, "b", "k/b", "2026-09-10 10:00+00", 13, "2026-09-04")
    _run(pg, "c", "k/c", "2026-09-20 10:00+00", 1, "2026-09-18")
    repo = ClouderRepository(pg)

    assert [r["run_id"] for r in repo.list_replayable_runs()] == ["a-new", "b", "c"]
    assert [r["run_id"] for r in repo.list_replayable_runs(style_ids=[1])] == ["a-new", "c"]
    assert [
        r["run_id"]
        for r in repo.list_replayable_runs(since=date(2026, 9, 1), until=date(2026, 9, 10))
    ] == ["b"]

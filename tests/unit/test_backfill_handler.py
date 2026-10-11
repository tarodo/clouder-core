from __future__ import annotations

from datetime import date

import pytest

from collector import backfill_handler
from collector.backfill_handler import lambda_handler, plan, replay, summarize
from collector.models import CanonicalizationResult


class PlanRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def list_replayable_runs(self, **kwargs):
        self.calls.append(kwargs)
        return self.rows


ROW = {
    "run_id": "r-1",
    "raw_s3_key": "raw/bp/releases/style_id=1/year=2026/week=38/releases.json.gz",
    "started_at": "2026-09-20 09:15:00.5",  # Data API string
    "status": "COMPLETED",
    "style_id": 1,
    "period_end": "2026-09-18",
}


def test_plan_defaults_to_dry_run_and_shapes_runs() -> None:
    repo = PlanRepo([ROW])

    out = plan({}, repo)

    assert out["dry_run"] is True
    assert out["runs"] == [
        {
            "run_id": "r-1",
            "s3_key": ROW["raw_s3_key"],
            "observed_at": "2026-09-20T09:15:00.500000+00:00",
            "status": "COMPLETED",
            "style_id": 1,
            "period_end": "2026-09-18",
        }
    ]
    assert repo.calls == [{"style_ids": None, "since": None, "until": None}]


def test_plan_passes_filters() -> None:
    repo = PlanRepo([])

    plan(
        {"dry_run": False, "style_ids": [1, 13], "since": "2026-08-01", "until": "2026-09-30"}, repo
    )

    assert repo.calls == [
        {"style_ids": [1, 13], "since": date(2026, 8, 1), "until": date(2026, 9, 30)}
    ]


@pytest.mark.parametrize(
    "params",
    [
        {"dry_run": "yes"},
        {"style_ids": "1"},
        {"style_ids": [True]},
        {"since": "2026-13-01"},
        {"dry_run": False, "style_id": [1]},  # a typo must not widen an apply to every style
    ],
)
def test_plan_rejects_bad_input(params) -> None:
    with pytest.raises(ValueError):
        plan(params, PlanRepo([]))


class RunRepo:
    def __init__(self):
        self.completed = []

    def set_run_completed(self, run_id, processed_count, finished_at):
        self.completed.append((run_id, processed_count))


class Storage:
    def read_releases(self, key):
        return [{"id": 1, "name": "T", "artists": []}]


def _stub_canonicalizer(monkeypatch, created: int):
    seen = {}

    class Stub:
        def __init__(self, repository, *, dry_run=False):
            seen["dry_run"] = dry_run

        def process_run(self, run_id, bundle, observed_at=None):
            seen["observed_at"] = observed_at
            return CanonicalizationResult(
                run_id=run_id,
                tracks_total=1,
                tracks_processed=1,
                artists_total=0,
                labels_total=0,
                albums_total=0,
                styles_total=0,
                tracks_created=created,
                tracks_changed=2,
                track_field_changes={"bpm": 2},
            )

    monkeypatch.setattr(backfill_handler, "Canonicalizer", Stub)
    enqueued = []
    monkeypatch.setattr(
        backfill_handler,
        "_enqueue_spotify_search_after_canonicalization",
        lambda settings, correlation_id: enqueued.append(correlation_id),
    )
    monkeypatch.setattr(backfill_handler, "get_worker_settings", lambda: object())
    return seen, enqueued


RUN = {
    "run_id": "r-1",
    "s3_key": "k",
    "observed_at": "2026-09-20T09:15:00+00:00",
    "status": "FAILED",
    "style_id": 1,
    "period_end": "2026-09-18",
}


def test_replay_dry_run_neither_marks_nor_enqueues(monkeypatch) -> None:
    seen, enqueued = _stub_canonicalizer(monkeypatch, created=1)
    repo = RunRepo()

    out = replay(RUN, dry_run=True, repository=repo, storage=Storage())

    assert seen["dry_run"] is True
    assert seen["observed_at"].isoformat() == "2026-09-20T09:15:00+00:00"
    assert (repo.completed, enqueued) == ([], [])
    assert (out["tracks_created"], out["tracks_changed"]) == (1, 2)
    assert out["track_field_changes"] == {"bpm": 2}


def test_replay_apply_recovers_unfinished_runs_and_enqueues_search(monkeypatch) -> None:
    _, enqueued = _stub_canonicalizer(monkeypatch, created=1)
    repo = RunRepo()

    replay(RUN, dry_run=False, repository=repo, storage=Storage())

    assert repo.completed == [("r-1", 1)]
    assert enqueued == ["r-1"]


def test_replay_apply_keeps_completed_run_history(monkeypatch) -> None:
    _, enqueued = _stub_canonicalizer(monkeypatch, created=0)
    repo = RunRepo()

    replay({**RUN, "status": "COMPLETED"}, dry_run=False, repository=repo, storage=Storage())

    assert (repo.completed, enqueued) == ([], [])


def test_summarize_adds_counts_and_lists_failures() -> None:
    ok = {"run_id": "a", "tracks_total": 10, "tracks_changed": 2, "track_field_changes": {"bpm": 2}}
    ok2 = {
        "run_id": "b",
        "tracks_total": 5,
        "tracks_created": 1,
        "track_field_changes": {"bpm": 1, "isrc": 1},
    }
    bad = {"run_id": "c", "failed": True, "error": "RuntimeError"}

    out = summarize([ok, ok2, bad], dry_run=True)

    assert out["runs"] == 3
    assert (out["runs_failed"], out["failed_run_ids"]) == (1, ["c"])
    assert (out["tracks_total"], out["tracks_changed"], out["tracks_created"]) == (15, 2, 1)
    assert out["track_field_changes"] == {"bpm": 3, "isrc": 1}


def test_lambda_handler_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        lambda_handler({"action": "drop"}, None)


class QuarantineStorage:
    def __init__(self) -> None:
        self.written: list = []

    def read_releases(self, key):
        return [{"id": 1, "name": "T", "artists": []}, {"id": 2, "name": ""}]

    def write_quarantine(self, run_id, quarantined):
        self.written.append((run_id, len(quarantined)))


def test_replay_dry_run_does_not_write_quarantine(monkeypatch) -> None:
    _stub_canonicalizer(monkeypatch, created=0)
    storage = QuarantineStorage()

    out = replay(RUN, dry_run=True, repository=RunRepo(), storage=storage)

    assert storage.written == []
    assert out["records_quarantined"] == 1


def test_replay_apply_writes_quarantine(monkeypatch) -> None:
    _stub_canonicalizer(monkeypatch, created=0)
    storage = QuarantineStorage()

    out = replay(RUN, dry_run=False, repository=RunRepo(), storage=storage)

    assert storage.written == [("r-1", 1)]
    assert out["records_quarantined"] == 1


def test_summarize_adds_quarantine_and_unions_drift() -> None:
    out = summarize(
        [
            {"run_id": "a", "records_quarantined": 1, "drift_fields": ["bpm"]},
            {"run_id": "b", "records_quarantined": 2, "drift_fields": ["isrc", "bpm"]},
        ],
        dry_run=True,
    )

    assert out["records_quarantined"] == 3
    assert out["drift_fields"] == ["bpm", "isrc"]

"""Dry run on a real Postgres: writes nothing, predicts what apply does."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from pg_data_api import CANONICAL_TABLES, count_rows, seed_run
from synthetic import synthetic_week

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

T1 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T2 = T1 + timedelta(days=7)
COUNTS = (
    "labels_created", "styles_created", "artists_created", "albums_created",
    "tracks_created", "tracks_changed", "tracks_stale",
)


def _fingerprint(pg) -> dict:
    out = {t: count_rows(pg, t) for t in CANONICAL_TABLES}
    out["tracks"] = pg.execute(
        "SELECT id, bpm, album_id, updated_at FROM clouder_tracks ORDER BY id"
    )
    out["sources"] = pg.execute(
        "SELECT external_id, payload_hash, last_run_id, last_seen_at FROM source_entities"
        " ORDER BY entity_type, external_id"
    )
    return out


def _counts(result) -> dict:
    return {**{c: getattr(result, c) for c in COUNTS}, "fields": dict(result.track_field_changes)}


def _second_week():
    first = synthetic_week(80)
    second = copy.deepcopy(first)
    second[0]["bpm"] = 99
    second[1]["release"] = {
        "id": 2_999_999, "name": "New Release",
        "label": {"id": 3_999_999, "name": "New Label"},
    }  # an existing track moves to a release that does not exist yet
    second.append({**copy.deepcopy(first[2]), "id": 9_999, "name": "Brand New"})
    return first, second


def _setup(pg):
    first, second = _second_week()
    repo = ClouderRepository(pg)
    seed_run(pg, "run-1")
    seed_run(pg, "run-2")
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(first), observed_at=T1)
    return repo, second


def test_dry_run_writes_nothing(pg) -> None:
    repo, second = _setup(pg)
    before = _fingerprint(pg)

    Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _fingerprint(pg) == before


def test_dry_run_predicts_what_apply_does(pg) -> None:
    repo, second = _setup(pg)

    dry = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )
    applied = Canonicalizer(repo).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _counts(dry) == _counts(applied)
    assert dry.tracks_created == 1
    assert (dry.albums_created, dry.labels_created) == (1, 1)
    assert dry.track_field_changes == {"bpm": 1, "album_id": 1}


def test_dry_run_after_apply_reports_nothing(pg) -> None:
    repo, second = _setup(pg)
    Canonicalizer(repo).process_run(run_id="run-2", bundle=normalize_tracks(second), observed_at=T2)

    again = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-2", bundle=normalize_tracks(second), observed_at=T2
    )

    assert _counts(again) == {**{c: 0 for c in COUNTS}, "fields": {}}

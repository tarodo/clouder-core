"""Canonical tracks fed by two Beatport tracks (the early ISRC heuristic, 2026-03,
mapped several Beatport ids to one canonical track): replays must converge."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

from pg_data_api import seed_run
from synthetic import synthetic_week

T1 = datetime(2026, 3, 1, 16, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(hours=1)


def _process(pg, run_id, raw, observed_at, *, dry_run=False):
    seed_run(pg, run_id)
    return Canonicalizer(ClouderRepository(pg), dry_run=dry_run).process_run(
        run_id=run_id, bundle=normalize_tracks(raw), observed_at=observed_at
    )


def _merge(pg, into_external_id: str, external_id: str) -> None:
    """Point a second Beatport id at an existing canonical track (legacy heuristic)."""
    pg.execute(
        """
        INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type,
                                  clouder_id, match_type, confidence, first_seen_at, last_seen_at)
        SELECT 'beatport', 'track', :ext, 'track', clouder_id, 'heuristic', 0.800, now(), now()
        FROM identity_map
        WHERE source = 'beatport' AND entity_type = 'track' AND external_id = :into
        """,
        {"ext": external_id, "into": into_external_id},
    )


def _album_of(pg, external_id: str):
    return pg.execute(
        """
        SELECT a.title FROM clouder_tracks t
        JOIN identity_map i ON i.clouder_id = t.id AND i.entity_type = 'track'
        JOIN clouder_albums a ON a.id = t.album_id
        WHERE i.external_id = :ext
        """,
        {"ext": external_id},
    )[0]["title"]


def _two_releases():
    """bp 1 on an EP (week 1), bp 9001 = the same recording on a compilation (week 2)."""
    week1 = synthetic_week(20)
    original = week1[0]
    original["release"] = {"id": 7_000_001, "name": "Original EP", "label": {"id": 1, "name": "L"}}
    compilation = copy.deepcopy(original)
    compilation["id"] = 9001
    compilation["release"] = {"id": 7_000_002, "name": "Compilation", "label": {"id": 1, "name": "L"}}
    return week1, [compilation]


def test_merged_track_takes_the_newest_source_whatever_the_order(pg) -> None:
    week1, week2 = _two_releases()
    _process(pg, "run-1", week1, T1)
    _merge(pg, "1", "9001")
    _process(pg, "run-2", week2, T2)
    assert _album_of(pg, "1") == "Compilation"

    replay_old = _process(pg, "run-1", week1, T1)

    assert _album_of(pg, "1") == "Compilation"
    assert replay_old.tracks_changed == 0
    assert _process(pg, "run-2", week2, T2, dry_run=True).tracks_changed == 0


def test_merged_track_within_one_run_is_stable(pg) -> None:
    week1, week2 = _two_releases()
    _process(pg, "run-1", week1, T1)
    _merge(pg, "1", "9001")
    both = week1 + week2

    _process(pg, "run-2", both, T2)
    again = _process(pg, "run-2", both, T2, dry_run=True)

    assert again.tracks_changed == 0

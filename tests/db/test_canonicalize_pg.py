"""Canonical output on a real Postgres. Must pass unchanged before and after the
set-based rewrite (docs/superpowers/plans/2026-10-07-set-based-canonicalization.md)."""

from __future__ import annotations

from pg_data_api import CANONICAL_TABLES, count_rows, seed_run
from synthetic import synthetic_week

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

# 1,200 tracks -> ~720 artists and ~545 albums: phases larger than one 500-id lookup.
TRACKS = 1200


def _snapshot(pg) -> dict[str, int]:
    return {table: count_rows(pg, table) for table in CANONICAL_TABLES}


def test_cold_run_creates_one_canonical_row_per_source_entity(pg) -> None:
    bundle = normalize_tracks(synthetic_week(TRACKS))
    seed_run(pg, "run-cold")

    Canonicalizer(ClouderRepository(pg)).process_run(run_id="run-cold", bundle=bundle)

    assert count_rows(pg, "clouder_tracks") == len(bundle.tracks)
    assert count_rows(pg, "clouder_artists") == len(bundle.artists)
    assert count_rows(pg, "clouder_labels") == len(bundle.labels)
    assert count_rows(pg, "clouder_albums") == len(bundle.albums)
    assert count_rows(pg, "clouder_styles") == len(bundle.styles)
    assert count_rows(pg, "identity_map") == (
        len(bundle.tracks)
        + len(bundle.artists)
        + len(bundle.labels)
        + len(bundle.albums)
        + len(bundle.styles)
    )
    assert count_rows(pg, "clouder_track_artists") == sum(
        len(track.bp_artist_ids) for track in bundle.tracks
    )


def test_warm_rerun_reuses_identities_and_applies_conservative_updates(pg) -> None:
    raw = synthetic_week(TRACKS)
    repo = ClouderRepository(pg)
    seed_run(pg, "run-1")
    seed_run(pg, "run-2")
    Canonicalizer(repo).process_run(run_id="run-1", bundle=normalize_tracks(raw))
    before = _snapshot(pg)

    raw[0]["bpm"] = 99
    Canonicalizer(repo).process_run(run_id="run-2", bundle=normalize_tracks(raw))

    assert _snapshot(pg) == before
    rows = pg.execute(
        """
        SELECT t.bpm FROM clouder_tracks t
        JOIN identity_map i ON i.clouder_id = t.id
        WHERE i.source = 'beatport' AND i.entity_type = 'track' AND i.external_id = :ext
        """,
        {"ext": str(raw[0]["id"])},
    )
    assert rows[0]["bpm"] == 99


def test_album_points_at_its_label(pg) -> None:
    raw = synthetic_week(50)
    seed_run(pg, "run-labels")
    Canonicalizer(ClouderRepository(pg)).process_run(
        run_id="run-labels", bundle=normalize_tracks(raw)
    )

    rows = pg.execute(
        """
        SELECT count(*) AS n FROM clouder_albums a
        JOIN identity_map il ON il.clouder_id = a.label_id AND il.entity_type = 'label'
        """
    )
    assert rows[0]["n"] == count_rows(pg, "clouder_albums")

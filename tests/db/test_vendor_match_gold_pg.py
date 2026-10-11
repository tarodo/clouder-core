"""Gold-set extraction against a real Postgres."""

from __future__ import annotations

import json

from collector.curation.playlists_repository import PlaylistsRepository
from collector.vendor_match.gold import (
    auto_population,
    auto_sample,
    duplicate_artists,
    review_accepts,
)


def _seed(pg) -> None:
    for sql in (
        "INSERT INTO clouder_albums (id, title, normalized_title, created_at, updated_at) "
        "VALUES ('al1', 'Album One', 'album one', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, length_ms, album_id, created_at, updated_at) "
        "VALUES ('t1', 'Night Drive', 'night drive', 300000, 'al1', now(), now()), "
        "('t2', 'Day Ride', 'day ride', NULL, NULL, now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
        "VALUES ('ar1', 'Zeta', 'zeta', now(), now()), ('ar2', 'Alpha', 'alpha', now(), now()), "
        "('ar3', 'Alpha', 'alpha', now(), now())",
        "INSERT INTO clouder_track_artists (track_id, artist_id) "
        "VALUES ('t1', 'ar1'), ('t1', 'ar2'), ('t2', 'ar1')",
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type, clouder_id, "
        "match_type, confidence, first_seen_at, last_seen_at) "
        "VALUES ('beatport', 'artist', '1', 'artist', 'ar1', 'auto_create', 0.6, now(), now()), "
        "('beatport', 'artist', '2', 'artist', 'ar2', 'auto_create', 0.6, now(), now())",
    ):
        pg.execute(sql)
    candidates = json.dumps(
        [
            {"ref": {"videoId": "v1", "title": "Night"}, "score": 0.7},
            {"ref": {"videoId": "v2", "title": "Night Drive"}, "score": 0.9},
        ]
    )
    for qid, resolved_at, cands in (
        ("q-old", "2026-01-01", "[]"),
        ("q-new", "2026-02-01", candidates),
    ):
        pg.execute(
            "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at, resolved_at) "
            "VALUES (:id, 't1', 'ytmusic', CAST(:c AS jsonb), 'resolved', now(), CAST(:r AS timestamptz))",
            {"id": qid, "c": cands, "r": resolved_at},
        )
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
        "VALUES ('q-pending', 't2', 'ytmusic', '[]'::jsonb, 'pending', now())"
    )
    pg.execute(
        """
        INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type, confidence, matched_at, payload)
        VALUES ('t1', 'ytmusic', 'v2', 'manual', 1.0, now(), '{"videoId": "v2"}'::jsonb),
               ('t2', 'ytmusic', 'y9', 'fuzzy', 0.973, now(), '{"videoId": "y9", "title": "Day Ride"}'::jsonb)
        """
    )


def test_review_accepts_keeps_latest_resolution_per_track(pg) -> None:
    _seed(pg)

    (record,) = review_accepts(pg)

    assert record["kind"] == "review_accept"
    assert record["track_id"] == "t1"
    assert record["chosen_id"] == "v2"
    assert [c["videoId"] for c in record["candidates"]] == ["v1", "v2"]
    assert record["stored_top_score"] == 0.9
    assert (record["artist"], record["title"], record["duration_ms"], record["album"]) == (
        "Alpha, Zeta",
        "Night Drive",
        300000,
        "Album One",
    )


def test_auto_sample_returns_fuzzy_matches_with_query_fields(pg) -> None:
    _seed(pg)

    (record,) = auto_sample(pg, 10)

    assert record["kind"] == "auto_sample"
    assert (record["track_id"], record["candidate"]["videoId"], record["confidence"]) == (
        "t2",
        "y9",
        0.973,
    )
    assert (record["artist"], record["duration_ms"], record["album"]) == ("Zeta", None, None)


def test_duplicate_artists_counts_name_groups(pg) -> None:
    _seed(pg)

    summary = duplicate_artists(pg)

    assert summary == {
        "kind": "duplicate_artists",
        "name_groups": 1,
        "artists_in_groups": 2,
        "groups_with_non_beatport_artist": 1,
    }


def test_auto_population_counts_fuzzy_matches(pg) -> None:
    _seed(pg)

    assert auto_population(pg) == {"kind": "auto_population", "fuzzy": 1}


def test_gold_query_fields_match_vendor_match_inputs(pg) -> None:
    """The export must rebuild exactly the input the vendor-match worker scored."""
    _seed(pg)
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, length_ms, album_id, created_at, updated_at) "
        "VALUES ('t3', 'Third', 'third', 245000, 'al1', now(), now())"
    )
    pg.execute(
        "INSERT INTO clouder_track_artists (track_id, artist_id) VALUES ('t3', 'ar3'), ('t3', 'ar1')"
    )
    (expected,) = PlaylistsRepository(pg).fetch_unmatched_match_inputs(
        track_ids=["t3"], vendor="ytmusic"
    )
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type, confidence, matched_at, payload) "
        "VALUES ('t3', 'ytmusic', 'v9', 'manual', 1.0, now(), '{}'::jsonb)"
    )
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at, resolved_at) "
        "VALUES ('q3', 't3', 'ytmusic', '[]'::jsonb, 'resolved', now(), now())"
    )

    (record,) = [r for r in review_accepts(pg) if r["track_id"] == "t3"]

    assert (record["artist"], record["title"], record["duration_ms"], record["album"]) == (
        expected.artist,
        expected.title,
        expected.duration_ms,
        expected.album,
    )

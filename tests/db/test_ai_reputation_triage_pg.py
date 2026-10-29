"""Block creation sends AI labels' / artists' tracks to NOT from the chosen level (spec: after DISCARD
for flagged tracks and FAV for likes, in the dislikes' tier; off by default)."""

from __future__ import annotations

from datetime import date

import pytest

from collector.curation.triage_repository import TriageRepository
from collector.user_deletion import delete_user

# track -> (album, artists with roles)
TRACKS = {
    "on_lvl2_label": ("alb2", [("plain", "main")]),
    "remixed": ("alb0", [("plain", "main"), ("ai_remixer", "remixer")]),
    "nolabel": (None, [("plain", "main")]),
}


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        # lvl2: 1 of 4 checked flagged; clean: nothing flagged
        "INSERT INTO clouder_labels (id, name, normalized_name, ai_total, ai_checked, ai_tracks,"
        " created_at, updated_at) VALUES ('lvl2', 'L2', 'l2', 9, 4, 1, now(), now()),"
        " ('clean', 'C', 'c', 9, 4, 0, now(), now())",
        "INSERT INTO clouder_albums (id, title, normalized_title, label_id, created_at, updated_at)"
        " VALUES ('alb2', 'A', 'a', 'lvl2', now(), now()), ('alb0', 'B', 'b', 'clean', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, ai_total, ai_checked, ai_tracks,"
        " created_at, updated_at) VALUES ('plain', 'P', 'p', 5, 5, 0, now(), now()),"
        " ('ai_remixer', 'R', 'r', 3, 3, 3, now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, album_id, publish_date,"
        " spotify_release_date, created_at, updated_at) VALUES "
        + ", ".join(
            f"('{t}', '{t}', '{t}', 'st', {f"'{alb}'" if alb else 'NULL'}, '2026-10-03',"
            " '2026-10-03', now(), now())"
            for t, (alb, _) in TRACKS.items()
        ),
        "INSERT INTO clouder_track_artists (track_id, artist_id, role) VALUES "
        + ", ".join(
            f"('{t}', '{a}', '{role}')" for t, (_, artists) in TRACKS.items() for a, role in artists
        ),
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


def _buckets(pg, **options) -> dict[str, str]:
    block = TriageRepository(pg).create_block(
        user_id="u1",
        style_id="st",
        name="W",
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        **options,
    )
    rows = pg.execute(
        "SELECT x.track_id, b.bucket_type FROM triage_bucket_tracks x"
        " JOIN triage_buckets b ON b.id = x.triage_bucket_id WHERE b.triage_block_id = :blk",
        {"blk": block.id},
    )
    return {r["track_id"]: r["bucket_type"] for r in rows}


def test_off_by_default(world) -> None:
    assert set(_buckets(world).values()) == {"NEW"}


def test_ai_label_level_sends_to_not(world) -> None:
    assert _buckets(world, ai_labels_min_level=2)["on_lvl2_label"] == "NOT"
    assert _buckets(world, ai_labels_min_level=3)["on_lvl2_label"] == "NEW"


def test_ai_artist_in_any_role(world) -> None:
    got = _buckets(world, ai_artists_min_level=1)
    assert got["remixed"] == "NOT"
    assert got["on_lvl2_label"] == "NEW"  # the artist rule ignores the label


def test_track_without_label(world) -> None:
    assert _buckets(world, ai_labels_min_level=1)["nolabel"] == "NEW"


def test_likes_and_discard_win(world) -> None:
    world.execute(
        "INSERT INTO clouder_user_label_prefs (user_id, label_id, status, updated_at)"
        " VALUES ('u1', 'lvl2', 'liked', now())"
    )
    world.execute(
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result)"
        " VALUES ('remixed', 'ai_lofcz', 'ok', 'v1', '{\"ai_detected\": true}')"
    )
    got = _buckets(world, ai_labels_min_level=1, ai_artists_min_level=1)
    assert got["on_lvl2_label"] == "FAV"
    assert got["remixed"] == "DISCARD"


def test_block_keeps_the_levels(world) -> None:
    block = TriageRepository(world).create_block(
        user_id="u1",
        style_id="st",
        name="W",
        date_from=date(2026, 10, 1),
        date_to=date(2026, 10, 7),
        ai_labels_min_level=3,
    )
    assert (block.ai_labels_min_level, block.ai_artists_min_level) == (3, None)

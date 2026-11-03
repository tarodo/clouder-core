"""The category and playlist track lists carry the YouTube comment_count.

A collected / empty collection gives its count (the collector reads one page: 100 at most);
disabled, failed, pending or no collection gives null.
"""

from __future__ import annotations

import pytest

from collector.curation.categories_repository import CategoriesRepository
from collector.curation.playlists_repository import PlaylistsRepository
from collector.user_deletion import delete_user

COLLECTIONS = {
    "few": ("collected", 12),
    "full": ("collected", 100),
    "empty": ("empty", 0),
    "off": ("disabled", 0),
    "failed": ("failed", 0),
    "pending": ("pending", 0),
}
TRACKS = (*COLLECTIONS, "none")
EXPECTED = {
    "few": 12,
    "full": 100,
    "empty": 0,
    "off": None,
    "failed": None,
    "pending": None,
    "none": None,
}


@pytest.fixture
def world(pg):
    tracks = ", ".join(f"('{t}', '{t}', '{t}', 'st', now(), now())" for t in TRACKS)
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        f" VALUES {tracks}",
        "INSERT INTO comment_collections (id, track_id, platform, external_video_id, status,"
        " comment_count, created_at, updated_at) VALUES "
        + ", ".join(
            f"('cc-{t}', '{t}', 'youtube', 'v-{t}', '{s}', {n}, now(), now())"
            for t, (s, n) in COLLECTIONS.items()
        ),
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES "
        + ", ".join(f"('cat', '{t}', now())" for t in TRACKS),
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('pl', 'u1', 'P', 'p', now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) VALUES "
        + ", ".join(f"('pl', '{t}', {i}, now())" for i, t in enumerate(TRACKS)),
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


def test_category_tracks(world) -> None:
    page = CategoriesRepository(world).list_tracks(
        user_id="u1", category_id="cat", limit=50, offset=0, search=None
    )
    assert {r.track["id"]: r.track["comment_count"] for r in page.items} == EXPECTED


def test_playlist_tracks(world) -> None:
    rows, _ = PlaylistsRepository(world).list_tracks(
        user_id="u1", playlist_id="pl", limit=50, offset=0
    )
    assert {r.track_id: r.comment_count for r in rows} == EXPECTED

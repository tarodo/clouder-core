"""The category, bucket and playlist track lists carry ai_detected from track_analyses."""

from __future__ import annotations

import pytest

from collector.curation.categories_repository import CategoriesRepository
from collector.curation.playlists_repository import PlaylistsRepository
from collector.curation.triage_repository import TriageRepository
from collector.user_deletion import delete_user


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " VALUES ('ai', 'AI', 'ai', 'st', now(), now()), ('human', 'H', 'h', 'st', now(), now()),"
        " ('clean', 'C', 'c', 'st', now(), now())",
        # flagged, analyzed-not-flagged, and a non-ok row that must not count
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result)"
        " VALUES ('ai', 'ai_detect', 'ok', 'v1', '{\"ai_detected\": true, \"score\": 0.9}'),"
        " ('human', 'ai_detect', 'ok', 'v1', '{\"ai_detected\": false, \"score\": 0.0}'),"
        " ('clean', 'embed', 'ok', 'v1', '{\"ai_detected\": true}')",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO category_tracks (category_id, track_id, added_at)"
        " VALUES ('cat', 'ai', now()), ('cat', 'human', now()), ('cat', 'clean', now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('blk', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('bkt', 'blk', 'NEW', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)"
        " VALUES ('bkt', 'ai', now()), ('bkt', 'human', now()), ('bkt', 'clean', now())",
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('pl', 'u1', 'P', 'p', now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at)"
        " VALUES ('pl', 'ai', 0, now()), ('pl', 'human', 1, now()), ('pl', 'clean', 2, now())",
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


EXPECTED = {"ai": True, "human": False, "clean": False}


def test_category_tracks(world) -> None:
    page = CategoriesRepository(world).list_tracks(
        user_id="u1", category_id="cat", limit=10, offset=0, search=None
    )
    assert {t.track["id"]: t.track["ai_detected"] for t in page.items} == EXPECTED


def test_bucket_tracks(world) -> None:
    rows, _ = TriageRepository(world).list_bucket_tracks(
        user_id="u1", block_id="blk", bucket_id="bkt", limit=10, offset=0
    )
    assert {r.track_id: r.ai_detected for r in rows} == EXPECTED


def test_playlist_tracks(world) -> None:
    rows, _ = PlaylistsRepository(world).list_tracks(
        user_id="u1", playlist_id="pl", limit=10, offset=0
    )
    assert {r.track_id: r.ai_detected for r in rows} == EXPECTED

"""A finalized block's comment fan-out: the block's promoted tracks plus every other track in the
user's categories with no collection yet (added directly, or before collection existed)."""

from __future__ import annotations

import pytest

from collector.comments.repository import CommentsRepository
from collector.user_deletion import delete_user


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at) VALUES"
        " ('u1', 'sp1', 'A', 'u1@example.com', now(), now()),"
        " ('u2', 'sp2', 'B', 'u2@example.com', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " SELECT t, t, t, 'st', now(), now() FROM unnest(ARRAY['blk', 'direct', 'done', 'twice',"
        " 'theirs']) AS t",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('b1', 'u1', 'st', 'W', '2026-01-03', '2026-01-09',"
        " 'FINALIZED', now(), now())",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('c1', 'u1', 'st', 'C1', 'c1', now(), now()),"
        " ('c2', 'u1', 'st', 'C2', 'c2', now(), now()),"
        " ('c3', 'u2', 'st', 'C3', 'c3', now(), now())",
        "INSERT INTO category_tracks (category_id, track_id, added_at, source_triage_block_id)"
        " VALUES ('c1', 'blk', now(), 'b1'), ('c1', 'direct', now(), NULL),"
        " ('c1', 'done', now(), NULL), ('c1', 'twice', now(), NULL),"
        " ('c2', 'twice', now(), NULL), ('c3', 'theirs', now(), NULL)",
        # the block's own track is re-sent even with a collection: start_collection skips it
        "INSERT INTO comment_collections (id, track_id, platform, external_video_id, status,"
        " comment_count, created_at, updated_at) VALUES"
        " ('cc1', 'blk', 'youtube', 'v', 'disabled', 0, now(), now()),"
        " ('cc2', 'done', 'youtube', 'v', 'disabled', 0, now(), now())",
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")
    delete_user(pg, "u2")


def test_track_ids_to_collect(world):
    ids = CommentsRepository(world).track_ids_to_collect(block_id="b1", user_id="u1")

    assert ids == ["blk", "direct", "twice"]

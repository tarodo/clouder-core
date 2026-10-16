"""The category, bucket and playlist track lists carry the AI level as ai_verdict.

Both ai_lofcz and ai_deezer flagged -> "high"; only lofcz -> "medium";
only deezer -> "low"; else null.
"""

from __future__ import annotations

import pytest

from collector.curation.categories_repository import CategoriesRepository
from collector.curation.playlists_repository import PlaylistsRepository
from collector.curation.triage_repository import TriageRepository
from collector.user_deletion import delete_user

TRACKS = ("both", "lofcz", "deezer", "human", "clean", "old", "none")


def _flag(track: str, analyzer: str, ai: bool) -> str:
    return f"('{track}', '{analyzer}', 'ok', 'v1', '{{\"ai_detected\": {str(ai).lower()}, \"score\": 0.5}}')"


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
        # the pair drives the verdict; a flag from the retired ai_detect (ArtifactNet)
        # model or a non-AI analyzer counts for nothing
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result) VALUES "
        + ", ".join(
            [
                _flag("both", "ai_lofcz", True),
                _flag("both", "ai_deezer", True),
                _flag("lofcz", "ai_lofcz", True),
                _flag("lofcz", "ai_deezer", False),
                _flag("deezer", "ai_deezer", True),
                _flag("human", "ai_lofcz", False),
                _flag("human", "ai_deezer", False),
                _flag("human", "ai_detect", True),
                _flag("clean", "embed", True),
                _flag("old", "ai_detect", True),
            ]
        ),
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES "
        + ", ".join(f"('cat', '{t}', now())" for t in TRACKS),
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('blk', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('bkt', 'blk', 'NEW', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES "
        + ", ".join(f"('bkt', '{t}', now())" for t in TRACKS),
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('pl', 'u1', 'P', 'p', now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) VALUES "
        + ", ".join(f"('pl', '{t}', {i}, now())" for i, t in enumerate(TRACKS)),
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


EXPECTED = {
    "both": "high",
    "lofcz": "medium",
    "deezer": "low",
    "human": None,
    "clean": None,
    "old": None,
    "none": None,
}


def test_category_tracks(world) -> None:
    page = CategoriesRepository(world).list_tracks(
        user_id="u1", category_id="cat", limit=10, offset=0, search=None
    )
    assert {t.track["id"]: t.track["ai_verdict"] for t in page.items} == EXPECTED


def test_bucket_tracks(world) -> None:
    rows, _ = TriageRepository(world).list_bucket_tracks(
        user_id="u1", block_id="blk", bucket_id="bkt", limit=10, offset=0
    )
    assert {r.track_id: r.ai_verdict for r in rows} == EXPECTED


def test_playlist_tracks(world) -> None:
    rows, _ = PlaylistsRepository(world).list_tracks(
        user_id="u1", playlist_id="pl", limit=10, offset=0
    )
    assert {r.track_id: r.ai_verdict for r in rows} == EXPECTED

"""Bucket track rows say whether the AI pair checked a track and whether it has a light profile
(the curate / bucket player's meta line)."""

from __future__ import annotations

import pytest

from collector.curation.triage_repository import TriageRepository
from collector.user_deletion import delete_user

TRACKS = ("plain", "checked", "deezer_only", "failed", "profiled")


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " VALUES " + ", ".join(f"('{t}', '{t}', '{t}', 'st', now(), now())" for t in TRACKS),
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result) VALUES"
        " ('checked', 'ai_lofcz', 'ok', 'v1', '{\"ai_detected\": false}'),"
        " ('deezer_only', 'ai_deezer', 'ok', 'v1', '{\"ai_detected\": false}'),"
        " ('failed', 'ai_lofcz', 'failed', 'v1', NULL),"
        " ('profiled', 'light_profile', 'ok', 'light-1', '{}')",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('blk', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('bkt', 'blk', 'NEW', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES "
        + ", ".join(f"('bkt', '{t}', now())" for t in TRACKS),
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


def test_bucket_rows_flag_the_ai_check_and_the_profile(world) -> None:
    rows, _ = TriageRepository(world).list_bucket_tracks(
        user_id="u1", block_id="blk", bucket_id="bkt", limit=10, offset=0
    )
    got = {r.track_id: (r.ai_checked, r.profiled) for r in rows}
    assert got == {
        "plain": (False, False),
        "checked": (True, False),
        "deezer_only": (True, False),
        "failed": (False, False),  # a failed check is not a check
        "profiled": (False, True),
    }

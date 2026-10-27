"""Undecided buckets play the model's sure keeps first, then its discards, then the unscored;
decided buckets (a category's staging, DISCARD) keep the latest move on top."""

from __future__ import annotations

import pytest

from collector.curation.triage_repository import TriageRepository
from collector.user_deletion import delete_user

# (track, keep, keep_score); None = no prediction row at all
PREDICTIONS = {
    "keep_hi": (True, 0.9),
    "keep_lo": (True, 0.6),
    "discard_hi": (False, 0.4),
    "discard_lo": (False, 0.1),
    "no_head": (None, None),  # scored by a model without a keep head
    "unscored": None,
}


def _sql(v) -> str:
    return "NULL" if v is None else str(v).lower()


@pytest.fixture
def world(pg):
    tracks = [*PREDICTIONS, "moved_early", "moved_late"]
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " VALUES " + ", ".join(f"('{t}', '{t}', '{t}', 'st', now(), now())" for t in tracks),
        "INSERT INTO ml_models (user_id, style_id) VALUES ('u1', 'st')",
        "INSERT INTO track_predictions"
        " (user_id, style_id, track_id, model_version, keep, keep_score, categories, scored_at)"
        " VALUES "
        + ", ".join(
            f"('u1', 'st', '{t}', 1, {_sql(p[0])}, {_sql(p[1])}, '[]', now())"
            for t, p in [*PREDICTIONS.items(), ("moved_early", (True, 0.99))]
            if p is not None
        ),
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('blk', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, category_id, created_at)"
        " VALUES ('new', 'blk', 'NEW', NULL, now()), ('stg', 'blk', 'STAGING', 'cat', now())",
        # the block creation adds every track at the same moment
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES "
        + ", ".join(f"('new', '{t}', '2026-10-27T10:00:00Z')" for t in reversed(PREDICTIONS)),
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES"
        " ('stg', 'moved_early', '2026-10-27T11:00:00Z'),"
        " ('stg', 'moved_late', '2026-10-27T12:00:00Z')",
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


def _order(pg, bucket: str, limit: int = 10, offset: int = 0) -> list[str]:
    rows, _ = TriageRepository(pg).list_bucket_tracks(
        user_id="u1", block_id="blk", bucket_id=bucket, limit=limit, offset=offset
    )
    return [r.track_id for r in rows]


def test_undecided_bucket_puts_sure_keeps_first(world) -> None:
    assert _order(world, "new") == list(PREDICTIONS)


def test_pages_follow_the_same_order(world) -> None:
    assert _order(world, "new", limit=3) + _order(world, "new", limit=3, offset=3) == list(
        PREDICTIONS
    )


def test_staging_keeps_the_latest_move_on_top(world) -> None:
    # moved_early is a sure keep, yet a category lists what was moved last first
    assert _order(world, "stg") == ["moved_late", "moved_early"]

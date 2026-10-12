"""Track tagging on real PostgreSQL: which tracks a user may tag."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from test_user_deletion_pg import _CATALOG

from collector.curation import TrackNotInAnyCategoryError
from collector.curation.tags_repository import TagsRepository
from collector.user_deletion import delete_user

_NOW = datetime(2026, 10, 12, tzinfo=UTC)


def _seed(pg, uid: str, p: str, *, status: str = "IN_PROGRESS", deleted: bool = False) -> None:
    """User + tag + a triage block whose NEW bucket holds track 'tr' (no category)."""
    params = {"uid": uid, "p": p, "status": status, "deleted": deleted}
    for sql in [
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES (:uid, :p || 'sp', 'Name', :p || '@example.com', now(), now())",
        "INSERT INTO user_tags (id, user_id, name, normalized_name, created_at, updated_at)"
        " VALUES (:p || 'tag', :uid, 'G', 'g', now(), now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at, deleted_at)"
        " VALUES (:p || 'blk', :uid, 'st', 'B', '2026-10-03', '2026-10-09', :status, now(), now(),"
        " CASE WHEN :deleted THEN now() END)",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES (:p || 'bkt', :p || 'blk', 'NEW', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)"
        " VALUES (:p || 'bkt', 'tr', now())",
    ]:
        pg.execute(sql, params)


@pytest.fixture
def users(pg):
    for sql in _CATALOG:
        pg.execute(sql)
    made: list[str] = []
    yield made
    for uid in made:
        delete_user(pg, uid)


def _new_user(users, pg, **kw) -> tuple[str, str]:
    uid, p = str(uuid.uuid4()), f"u{len(users)}_"
    _seed(pg, uid, p, **kw)
    users.append(uid)
    return uid, p


def test_track_in_own_active_triage_block_is_taggable(pg, users) -> None:
    uid, p = _new_user(users, pg)
    out = TagsRepository(data_api=pg).add_track_tag(
        user_id=uid, track_id="tr", tag_id=p + "tag", now=_NOW
    )
    assert [t.id for t in out] == [p + "tag"]


@pytest.mark.parametrize(
    "block", [{"status": "FINALIZED"}, {"deleted": True}], ids=["finalized", "deleted"]
)
def test_track_only_in_closed_triage_block_is_not_taggable(pg, users, block) -> None:
    uid, p = _new_user(users, pg, **block)
    with pytest.raises(TrackNotInAnyCategoryError):
        TagsRepository(data_api=pg).add_track_tag(
            user_id=uid, track_id="tr", tag_id=p + "tag", now=_NOW
        )


def test_another_users_triage_block_does_not_count(pg, users) -> None:
    _new_user(users, pg)  # owns the active block with 'tr'
    uid, p = _new_user(users, pg, status="FINALIZED")
    with pytest.raises(TrackNotInAnyCategoryError):
        TagsRepository(data_api=pg).set_track_tags(
            user_id=uid, track_id="tr", tag_ids=[p + "tag"], now=_NOW
        )

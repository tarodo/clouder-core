"""Undoing a category removal on real PostgreSQL puts the row back in place."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from collector.curation.categories_repository import CategoriesRepository
from collector.user_deletion import delete_user

_SEED = [
    "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
    " VALUES ('st', 'Techno', 'techno', now(), now()) ON CONFLICT DO NOTHING",
    "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
    " VALUES ('ta', 'A', 'a', 'st', now(), now()), ('tb', 'B', 'b', 'st', now(), now()),"
    " ('tc', 'C', 'c', 'st', now(), now()) ON CONFLICT DO NOTHING",
    "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
    " VALUES (:uid, :uid, 'N', :uid || '@example.com', now(), now())",
    "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at, updated_at)"
    " VALUES (:p || 'cat', :uid, 'st', 'C', 'c', now(), now())",
    "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, created_at,"
    " updated_at) VALUES (:p || 'blk', :uid, 'st', 'B', '2026-10-03', '2026-10-09', now(), now())",
]


def test_restore_puts_the_row_back_in_place(pg) -> None:
    uid = str(uuid.uuid4())
    repo = CategoriesRepository(data_api=pg)
    cat, blk = uid[:8] + "cat", uid[:8] + "blk"
    try:
        for sql in _SEED:
            pg.execute(sql, {"uid": uid, "p": uid[:8]})
        for tid, day in [("ta", 1), ("tb", 2), ("tc", 3)]:
            repo.add_track(
                user_id=uid,
                category_id=cat,
                track_id=tid,
                source_triage_block_id=blk,
                now=datetime(2026, 10, day, 12, tzinfo=UTC),
            )

        def order() -> list[str]:
            page = repo.list_tracks(user_id=uid, category_id=cat, limit=10, offset=0, search=None)
            return [it.track["id"] for it in page.items]

        assert order() == ["tc", "tb", "ta"]
        assert repo.owns_triage_block(user_id=uid, block_id=blk)
        assert not repo.owns_triage_block(user_id=str(uuid.uuid4()), block_id=blk)

        removed = next(
            it
            for it in repo.list_tracks(
                user_id=uid, category_id=cat, limit=10, offset=0, search=None
            ).items
            if it.track["id"] == "tb"
        )
        repo.remove_track(user_id=uid, category_id=cat, track_id="tb")
        # Undo: the original string from the list goes back as added_at.
        restored_at = datetime.fromisoformat(removed.added_at).replace(tzinfo=UTC)
        info, _ = repo.add_track(
            user_id=uid,
            category_id=cat,
            track_id="tb",
            source_triage_block_id=removed.source_triage_block_id,
            now=restored_at,
        )
        assert order() == ["tc", "tb", "ta"]
        assert info["source_triage_block_id"] == blk
    finally:
        delete_user(pg, uid)

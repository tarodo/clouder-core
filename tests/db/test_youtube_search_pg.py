"""YouTube search state on real PostgreSQL: who is searched, claims, release."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from collector.repositories import ClouderRepository
from collector.user_deletion import delete_user

SINCE = datetime(2026, 10, 15, tzinfo=UTC)
T0 = datetime(2026, 10, 16, 12, tzinfo=UTC)


def _seed(pg) -> None:
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('open', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now()), ('done', 'u1', 'st', 'B2', '2026-09-26', '2026-10-02',"
        " 'FINALIZED', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('b-open', 'open', 'NEW', now()), ('b-done', 'done', 'NEW', now())",
    ]:
        pg.execute(sql)


def _track(pg, tid: str, created: datetime) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " created_at, updated_at) VALUES (:id, :id, :id, 'st', 200000, :c, :c)",
        {"id": tid, "c": created},
    )


@pytest.fixture(autouse=True)
def _cleanup_user(pg):
    # The pg fixture refuses to truncate a database that still has users.
    yield
    delete_user(pg, "u1")


def _world(pg) -> ClouderRepository:
    _seed(pg)
    old = SINCE - timedelta(days=30)
    _track(pg, "new-1", SINCE + timedelta(hours=1))
    _track(pg, "new-2", SINCE + timedelta(hours=2))
    _track(pg, "in-cat", old)
    _track(pg, "in-open", old)
    _track(pg, "in-done", old)
    _track(pg, "archive", old)
    pg.execute(
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES ('cat', 'in-cat', now())"
    )
    pg.execute(
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)"
        " VALUES ('b-open', 'in-open', now()), ('b-done', 'in-done', now())"
    )
    return ClouderRepository(pg)


def test_claim_takes_new_and_needed_old_newest_first(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    assert [r["id"] for r in rows][:2] == ["new-2", "new-1"]
    assert {r["id"] for r in rows} == {"new-1", "new-2", "in-cat", "in-open"}


def test_claim_takes_at_most_the_limit(pg) -> None:
    # `IN (... LIMIT n FOR UPDATE SKIP LOCKED)` may be re-run per row and lock a
    # new row each time; the claim must stamp exactly `limit` rows.
    repo = _world(pg)
    # Steer the planner to the per-row SubPlan that re-runs the locking subquery
    # (what a tiny or freshly analysed table may get anyway).
    pg.execute("SET enable_hashagg = off")
    pg.execute("SET enable_hashjoin = off")
    pg.execute("SET enable_mergejoin = off")
    try:
        rows = repo.claim_tracks_for_youtube_search(limit=1, claimed_at=T0, since=SINCE)
    finally:
        pg.execute("RESET ALL")
    stamped = pg.execute(
        "SELECT count(*) AS n FROM clouder_tracks WHERE youtube_searched_at IS NOT NULL"
    )
    assert [r["id"] for r in rows] == ["new-2"]
    assert stamped[0]["n"] == 1


def test_claim_skips_the_archive(pg) -> None:
    repo = _world(pg)
    ids = {
        r["id"] for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    }
    assert "archive" not in ids and "in-done" not in ids


def test_second_claim_takes_nothing_already_claimed(pg) -> None:
    repo = _world(pg)
    first = repo.claim_tracks_for_youtube_search(limit=2, claimed_at=T0, since=SINCE)
    second = repo.claim_tracks_for_youtube_search(
        limit=10, claimed_at=T0 + timedelta(seconds=1), since=SINCE
    )
    assert not {r["id"] for r in first} & {r["id"] for r in second}


def test_release_hands_back_only_unfinished_rows(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    repo.mark_youtube_searched(track_id=rows[0]["id"], at=T0 + timedelta(seconds=5))
    released = repo.release_youtube_search_claim(claimed_at=T0)
    assert released == len(rows) - 1
    again = repo.claim_tracks_for_youtube_search(
        limit=10, claimed_at=T0 + timedelta(minutes=1), since=SINCE
    )
    assert rows[0]["id"] not in {r["id"] for r in again}
    assert len(again) == len(rows) - 1


def test_has_tracks_and_ytmusic_flag(pg) -> None:
    repo = _world(pg)
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at)"
        " VALUES ('r1', 'new-1', 'ytmusic', '[]'::jsonb, 'no_match', now())"
    )
    assert repo.has_tracks_needing_youtube_search(since=SINCE)
    rows = {
        r["id"]: r
        for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    }
    assert rows["new-1"]["has_ytmusic"] is True
    assert rows["new-2"]["has_ytmusic"] is False
    assert rows["new-1"]["artists"] == ""
    assert not repo.has_tracks_needing_youtube_search(since=SINCE)


def test_comment_meta_carries_the_stored_video(pg) -> None:
    from collector.comments.repository import CommentsRepository

    _world(pg)
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES ('new-1', 'youtube', 'vidY', 'token', 1.0,"
        " now(), '{}'::jsonb)"
    )
    meta = CommentsRepository(pg).fetch_track_meta(["new-1", "new-2"])
    assert meta["new-1"].youtube_video_id == "vidY"
    assert meta["new-2"].youtube_video_id is None


def test_status_counts(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=1, claimed_at=T0, since=SINCE)
    repo.mark_youtube_searched(track_id=rows[0]["id"], at=T0 + timedelta(seconds=5))
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES"
        " ('new-2', 'ytmusic', 's1', 'fuzzy', 0.95, now(), '{}'::jsonb),"
        " ('new-2', 'youtube', 'v1', 'token', 1.0, now(), '{}'::jsonb)"
    )
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at)"
        " VALUES ('r1', 'in-cat', 'ytmusic', '[]'::jsonb, 'pending', now()),"
        " ('r2', 'in-open', 'ytmusic', '[]'::jsonb, 'no_match', now())"
    )
    counts = repo.youtube_search_counts(since=SINCE, recent_since=T0)
    assert counts == {
        "waiting": 3,
        "searched_recently": 1,
        "searched_total": 1,
        "matched": 1,
        "needs_review": 1,
        "not_found": 1,
        "videos": 1,
    }


PUBLISHED_SINCE = date(2026, 10, 3)  # Saturday-week W40


def test_recent_releases_are_searched_whatever_their_ingest_date(pg) -> None:
    # W40 tracks ingested before the launch would otherwise never be searched.
    repo = _world(pg)
    old = SINCE - timedelta(days=30)
    _track(pg, "w40", old)
    _track(pg, "w39", old)
    pg.execute("UPDATE clouder_tracks SET publish_date = '2026-10-05' WHERE id = 'w40'")
    pg.execute("UPDATE clouder_tracks SET publish_date = '2026-09-28' WHERE id = 'w39'")
    without = {
        r["id"] for r in repo.claim_tracks_for_youtube_search(limit=20, claimed_at=T0, since=SINCE)
    }
    assert "w40" not in without
    repo.release_youtube_search_claim(claimed_at=T0)
    assert (
        repo.youtube_search_counts(since=SINCE, recent_since=T0, published_since=PUBLISHED_SINCE)[
            "waiting"
        ]
        == len(without) + 1
    )
    assert repo.has_tracks_needing_youtube_search(since=SINCE, published_since=PUBLISHED_SINCE)
    rows = repo.claim_tracks_for_youtube_search(
        limit=20, claimed_at=T0, since=SINCE, published_since=PUBLISHED_SINCE
    )
    ids = {r["id"] for r in rows}
    assert "w40" in ids and "w39" not in ids and "archive" not in ids

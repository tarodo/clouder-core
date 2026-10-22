"""YouTube search state on real PostgreSQL: who is searched, claims, release."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from collector.repositories import ClouderRepository
from collector.user_deletion import delete_user

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


def _track(pg, tid: str, published: date | None, created: datetime = T0) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " publish_date, created_at, updated_at) VALUES (:id, :id, :id, 'st', 200000, :p, :c, :c)",
        {"id": tid, "p": published, "c": created},
    )


@pytest.fixture(autouse=True)
def _cleanup_user(pg):
    # The pg fixture refuses to truncate a database that still has users.
    yield
    delete_user(pg, "u1")


def _world(pg) -> ClouderRepository:
    # Ingest order differs from release order on purpose: the claim follows
    # the release date, newest first, over the whole catalog.
    _seed(pg)
    _track(pg, "w41", date(2026, 10, 12), created=T0 - timedelta(days=60))
    _track(pg, "w40", date(2026, 10, 5), created=T0)
    _track(pg, "w40-late", date(2026, 10, 5), created=T0 + timedelta(hours=1))
    _track(pg, "w01", date(2026, 1, 3), created=T0 + timedelta(hours=2))
    _track(pg, "undated", None, created=T0 + timedelta(hours=3))
    return ClouderRepository(pg)


def test_claim_goes_newest_release_first_over_the_whole_catalog(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0)
    assert [r["id"] for r in rows] == ["w41", "w40-late", "w40", "w01", "undated"]


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
        rows = repo.claim_tracks_for_youtube_search(limit=1, claimed_at=T0)
    finally:
        pg.execute("RESET ALL")
    stamped = pg.execute(
        "SELECT count(*) AS n FROM clouder_tracks WHERE youtube_searched_at IS NOT NULL"
    )
    assert [r["id"] for r in rows] == ["w41"]
    assert stamped[0]["n"] == 1


def test_second_claim_takes_the_next_releases(pg) -> None:
    repo = _world(pg)
    first = repo.claim_tracks_for_youtube_search(limit=2, claimed_at=T0)
    second = repo.claim_tracks_for_youtube_search(limit=2, claimed_at=T0 + timedelta(seconds=1))
    assert [r["id"] for r in first] == ["w41", "w40-late"]
    assert [r["id"] for r in second] == ["w40", "w01"]


def test_release_hands_back_only_unfinished_rows(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0)
    repo.mark_youtube_searched(track_id=rows[0]["id"], at=T0 + timedelta(seconds=5))
    released = repo.release_youtube_search_claim(claimed_at=T0)
    assert released == len(rows) - 1
    again = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0 + timedelta(minutes=1))
    assert rows[0]["id"] not in {r["id"] for r in again}
    assert len(again) == len(rows) - 1


def test_ytmusic_flag_and_inputs(pg) -> None:
    repo = _world(pg)
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at)"
        " VALUES ('r1', 'w41', 'ytmusic', '[]'::jsonb, 'no_match', now())"
    )
    pg.execute("UPDATE clouder_tracks SET mix_name = 'Extended Mix' WHERE id = 'w41'")
    rows = {r["id"]: r for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0)}
    assert rows["w41"]["has_ytmusic"] is True
    assert rows["w40"]["has_ytmusic"] is False
    assert rows["w41"]["artists"] == ""
    assert (rows["w41"]["mix_name"], rows["w40"]["mix_name"]) == ("Extended Mix", None)


def test_comment_meta_carries_the_stored_video(pg) -> None:
    from collector.comments.repository import CommentsRepository

    _world(pg)
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES ('w41', 'youtube', 'vidY', 'token', 1.0,"
        " now(), '{}'::jsonb)"
    )
    meta = CommentsRepository(pg).fetch_track_meta(["w41", "w40"])
    assert meta["w41"].youtube_video_id == "vidY"
    assert meta["w40"].youtube_video_id is None


def _outcomes(pg, repo) -> None:
    # w41 found, w40 in review, w40-late not found; w01 and undated wait.
    for tid in ("w41", "w40", "w40-late"):
        repo.mark_youtube_searched(track_id=tid, at=T0 + timedelta(seconds=5))
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES"
        " ('w41', 'ytmusic', 's1', 'fuzzy', 0.95, now(), '{}'::jsonb),"
        " ('w41', 'youtube', 'v1', 'token', 1.0, now(), '{}'::jsonb)"
    )
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at)"
        " VALUES ('r1', 'w40', 'ytmusic', '[]'::jsonb, 'pending', now()),"
        " ('r2', 'w40-late', 'ytmusic', '[]'::jsonb, 'no_match', now())"
    )


def test_status_counts(pg) -> None:
    repo = _world(pg)
    _outcomes(pg, repo)
    assert repo.youtube_search_counts(recent_since=T0) == {
        "waiting": 2,
        "searched_recently": 3,
        "searched_total": 3,
        "matched": 1,
        "needs_review": 1,
        "not_found": 1,
        "videos": 1,
    }


def test_week_stats_split_each_style_week_into_outcomes(pg) -> None:
    repo = _world(pg)
    _outcomes(pg, repo)
    pg.execute(
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type,"
        " clouder_id, match_type, confidence, first_seen_at, last_seen_at) VALUES"
        " ('beatport', 'style', '90', 'style', 'st', 'auto_create', 1.0, now(), now())"
    )
    rows = sorted(repo.youtube_stats_for_year(2026), key=lambda r: r["week_number"])
    assert [
        (int(r["week_number"]), r["total"], r["found"], r["review"], r["not_found"], r["pending"])
        for r in rows
    ] == [(1, 1, 0, 0, 0, 1), (40, 2, 0, 1, 1, 0), (41, 1, 1, 0, 0, 0)]
    assert {r["beatport_style_id"] for r in rows} == {"90"}


def _review(pg, tid: str, *, status: str = "pending") -> None:
    candidates = [
        {"ref": {"videoId": "low", "title": "Other", "artists": [{"name": "X"}]}, "score": 0.5},
        {
            "ref": {
                "videoId": f"v-{tid}",
                "title": tid,
                "artists": [{"name": "A"}],
                "duration_seconds": 200,
                "album": {"name": "Alb"},
                "thumbnails": [{"url": "https://i.ytimg.com/" + "x" * 500}],
            },
            "score": 0.9,
        },
    ]
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
        " created_at) VALUES (:id, :t, 'ytmusic', CAST(:c AS jsonb), :s, now())",
        {"id": f"q-{tid}-{status}", "t": tid, "c": json.dumps(candidates), "s": status},
    )


def test_review_tracks_of_one_style_week(pg) -> None:
    repo = _world(pg)
    pg.execute(
        "INSERT INTO identity_map (source, entity_type, external_id, clouder_entity_type,"
        " clouder_id, match_type, confidence, first_seen_at, last_seen_at) VALUES"
        " ('beatport', 'style', '90', 'style', 'st', 'auto_create', 1.0, now(), now())"
    )
    pg.execute(
        "UPDATE clouder_tracks SET spotify_id = 'sp40', mix_name = 'Extended Mix' WHERE id = 'w40'"
    )
    _review(pg, "w40")
    _review(pg, "w40-late", status="no_match")  # not open
    _review(pg, "w41")  # another week
    rows = repo.youtube_review_tracks(
        beatport_style_id="90", date_from=date(2026, 10, 3), date_to=date(2026, 10, 9)
    )
    assert [r["track_id"] for r in rows] == ["w40"]
    (row,) = rows
    assert (row["title"], row["mix_name"], row["spotify_id"]) == ("w40", "Extended Mix", "sp40")
    assert row["style_name"] == "S"
    # Best first, trimmed to what the page shows (no thumbnails: pages stay small).
    assert [c["ref"]["videoId"] for c in row["candidates"]] == ["v-w40", "low"]
    assert row["candidates"][0]["ref"] == {
        "videoId": "v-w40",
        "title": "w40",
        "artists": [{"name": "A"}],
        "duration_seconds": 200,
        "album": {"name": "Alb"},
    }
    assert (
        repo.youtube_review_tracks(
            beatport_style_id="131", date_from=date(2026, 10, 3), date_to=date(2026, 10, 9)
        )
        == []
    )


def _yt_row(pg, tid: str, status: str, candidates: list) -> None:
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
        " created_at) VALUES (:id, :t, 'ytmusic', CAST(:c AS jsonb), :s, now())",
        {"id": f"q-{tid}-{status}", "t": tid, "c": json.dumps(candidates), "s": status},
    )


def _yt_status(pg, tid: str) -> list:
    return [
        (r["status"], len(json.loads(r["c"]) if isinstance(r["c"], str) else r["c"]))
        for r in pg.execute(
            "SELECT status, candidates AS c FROM match_review_queue"
            " WHERE clouder_track_id = :t AND vendor = 'ytmusic'",
            {"t": tid},
        )
    ]


CANDS = [{"ref": {"videoId": "v1", "title": "x"}, "score": 0.8}]


def test_reviews_of_tracks_missing_on_spotify_become_not_on_youtube(pg) -> None:
    repo = _world(pg)
    pg.execute("UPDATE clouder_tracks SET spotify_searched_at = now() WHERE id IN ('w41', 'w40')")
    pg.execute("UPDATE clouder_tracks SET spotify_id = 'sp40' WHERE id = 'w40'")
    for tid in ("w41", "w40", "w01"):  # not on Spotify, on Spotify, not searched yet
        _yt_row(pg, tid, "pending", CANDS)
    assert repo.close_youtube_reviews_without_spotify(now=T0) == 1
    assert _yt_status(pg, "w41") == [("no_match", 1)]  # candidates kept to reopen
    assert _yt_status(pg, "w40") == [("pending", 1)]
    assert _yt_status(pg, "w01") == [("pending", 1)]
    assert repo.close_youtube_reviews_without_spotify(now=T0) == 0


def test_tracks_found_on_spotify_later_are_searched_on_youtube_again(pg) -> None:
    repo = _world(pg)
    pg.execute(
        "UPDATE clouder_tracks SET youtube_searched_at = :t, spotify_id = 'sp', "
        "spotify_searched_at = :t WHERE id IN ('w41', 'w40', 'w01')",
        {"t": T0},
    )
    _yt_row(pg, "w41", "no_match", CANDS)  # closed because Spotify had missed it
    _yt_row(pg, "w40", "no_match", [])  # YouTube found nothing / a person said no
    pg.execute("UPDATE clouder_tracks SET spotify_id = NULL WHERE id = 'w01'")
    _yt_row(pg, "w01", "no_match", CANDS)  # still not on Spotify
    assert repo.reopen_youtube_for_spotify_found() == 1
    assert _yt_status(pg, "w41") == []
    assert _yt_status(pg, "w40") == [("no_match", 0)]
    assert _yt_status(pg, "w01") == [("no_match", 1)]
    claimed = [r["id"] for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0)]
    assert "w41" in claimed and "w40" not in claimed


def test_an_early_search_gets_one_second_chance_four_days_later(pg) -> None:
    # Searched days after the release, YouTube may not carry the track yet.
    repo = _world(pg)  # w40 released 2026-10-05, w41 2026-10-12, w01 2026-01-03
    pg.execute("UPDATE clouder_tracks SET youtube_searched_at = :t", {"t": T0})
    for tid, searched in (
        ("w40", datetime(2026, 10, 7, tzinfo=UTC)),  # 2 days after release
        ("w41", datetime(2026, 10, 15, tzinfo=UTC)),  # 3 days after, only 1 day ago
        ("w01", datetime(2026, 2, 1, tzinfo=UTC)),  # weeks after: not a timing miss
    ):
        pg.execute(
            "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
            " created_at) VALUES (:id, :t, 'ytmusic', CAST(:c AS jsonb), 'pending', :at)",
            {"id": f"q-{tid}", "t": tid, "c": json.dumps(CANDS), "at": searched},
        )
    now = datetime(2026, 10, 16, tzinfo=UTC)
    assert repo.reopen_youtube_second_chance(now=now) == 1
    assert _yt_status(pg, "w40") == []
    assert _yt_status(pg, "w41") == [("pending", 1)]
    assert _yt_status(pg, "w01") == [("pending", 1)]
    assert [r["id"] for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=now)] == [
        "w40"
    ]
    # The second search lands after the window: no third chance for w40, while
    # w41 gets its own once four days have passed.
    repo.mark_youtube_searched(track_id="w40", at=now)
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
        " created_at) VALUES ('q-w40-2', 'w40', 'ytmusic', CAST(:c AS jsonb), 'pending', :at)",
        {"c": json.dumps(CANDS), "at": now},
    )
    assert repo.reopen_youtube_second_chance(now=now + timedelta(days=30)) == 1
    assert _yt_status(pg, "w40") == [("pending", 1)]
    assert _yt_status(pg, "w41") == []

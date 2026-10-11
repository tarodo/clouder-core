"""Backlog counters behind the admin Spotify search status, on real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from collector.repositories import ClouderRepository

NOW = datetime(2026, 10, 10, 15, 0, tzinfo=UTC)


def _track(pg, tid, *, isrc="ISRC", searched_at=None, spotify_id=None):
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, isrc, style_id, spotify_id,"
        " spotify_searched_at, created_at, updated_at)"
        " VALUES (:id, 'T', 't', :isrc, 'st', :sid, :at, now(), now())",
        {"id": tid, "isrc": isrc, "sid": spotify_id, "at": searched_at},
    )


def test_waiting_not_found_and_recent(pg) -> None:
    pg.execute("INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
               " VALUES ('st', 'S', 's', now(), now())")
    _track(pg, "w1")
    _track(pg, "w2")
    _track(pg, "no-isrc", isrc=None)                                                # never searched
    _track(pg, "nf-old", searched_at=NOW - timedelta(days=2))                       # not found
    _track(pg, "nf-new", searched_at=NOW - timedelta(minutes=3))                    # not found, recent
    _track(pg, "found", searched_at=NOW - timedelta(minutes=5), spotify_id="sp1")   # found, recent

    counts = ClouderRepository(pg).spotify_search_counts(since=NOW - timedelta(minutes=10))

    assert counts == {"waiting": 2, "not_found": 2, "searched_recently": 2}

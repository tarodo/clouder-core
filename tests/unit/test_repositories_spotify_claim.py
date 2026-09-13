"""Tests for the atomic Spotify-search claim repository method.

Two spotify-search workers used to run `find_tracks_needing_spotify_search`
concurrently and get overlapping candidate sets, because `spotify_searched_at`
was only stamped once the whole batch finished. The claim below stamps the
rows as it selects them, so a second worker cannot pick them up.
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository

CLAIMED_AT = datetime(2026, 9, 13, 13, 50, 19, tzinfo=timezone.utc)


def _repo(rows):
    fake = MagicMock()
    fake.execute.return_value = rows
    return ClouderRepository(data_api=fake), fake


def test_claim_stamps_searched_at_and_returns_projection() -> None:
    repo, fake = _repo(
        [
            {
                "id": "t1",
                "isrc": "ZZ1",
                "title": "Move On",
                "normalized_title": "move on",
                "length_ms": 180_000,
                "artists": "Guri, Eider",
            }
        ]
    )

    rows = repo.claim_tracks_for_spotify_search(limit=10, claimed_at=CLAIMED_AT)

    assert rows == [
        {
            "id": "t1",
            "isrc": "ZZ1",
            "title": "Move On",
            "normalized_title": "move on",
            "length_ms": 180_000,
            "artists": "Guri, Eider",
        }
    ]
    _, params = fake.execute.call_args[0]
    assert params == {"limit": 10, "claimed_at": CLAIMED_AT}


def test_claim_sql_is_a_single_atomic_statement() -> None:
    repo, fake = _repo([])

    repo.claim_tracks_for_spotify_search(limit=200, claimed_at=CLAIMED_AT)

    sql, _ = fake.execute.call_args[0]
    # One data-modifying CTE, not a SELECT followed by a separate UPDATE:
    # anything less leaves a window for a second worker to grab the same rows.
    assert fake.execute.call_count == 1
    assert sql.count("UPDATE clouder_tracks") == 1
    assert "WITH claimed AS (" in sql
    assert "SET spotify_searched_at = :claimed_at" in sql
    assert "RETURNING" in sql


def test_claim_selects_only_unsearched_tracks_with_isrc() -> None:
    repo, fake = _repo([])

    repo.claim_tracks_for_spotify_search(limit=200, claimed_at=CLAIMED_AT)

    sql, _ = fake.execute.call_args[0]
    assert "isrc IS NOT NULL" in sql
    assert "spotify_searched_at IS NULL" in sql


def test_claim_skips_rows_locked_by_a_concurrent_worker() -> None:
    repo, fake = _repo([])

    repo.claim_tracks_for_spotify_search(limit=200, claimed_at=CLAIMED_AT)

    sql, _ = fake.execute.call_args[0]
    # SKIP LOCKED lets a parallel claim take a disjoint set instead of blocking.
    assert "FOR UPDATE SKIP LOCKED" in sql
    # Re-checking the predicate on the outer UPDATE closes the READ COMMITTED
    # window where the sub-select's ids were chosen before the lock was taken.
    outer_update = sql.split("FOR UPDATE SKIP LOCKED", 1)[1]
    assert "spotify_searched_at IS NULL" in outer_update


def test_claim_still_projects_artists_for_metadata_fallback() -> None:
    repo, fake = _repo([])

    repo.claim_tracks_for_spotify_search(limit=200, claimed_at=CLAIMED_AT)

    sql, _ = fake.execute.call_args[0]
    # The metadata fallback matches on title+artists+duration, so the claim has
    # to return the same projection the old read-only query did.
    assert "string_agg(DISTINCT a.name" in sql
    assert "LEFT JOIN clouder_track_artists ta" in sql
    assert "LEFT JOIN clouder_artists a" in sql
    assert "length_ms" in sql


def test_peek_query_does_not_claim() -> None:
    """The follow-up check must stay read-only or it would strand a track."""
    repo, fake = _repo([{"id": "t1"}])

    repo.find_tracks_needing_spotify_search(limit=1)

    sql, _ = fake.execute.call_args[0]
    assert "UPDATE" not in sql.upper()
    assert sql.strip().upper().startswith("SELECT")

"""Tests for Spotify not-found retry repository methods."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def _repo(rows):
    fake = MagicMock()
    fake.execute.return_value = rows
    return ClouderRepository(data_api=fake), fake


def test_reset_spotify_not_found_counts_returned_rows() -> None:
    repo, fake = _repo([{"id": "t1"}, {"id": "t2"}])
    now = datetime(2026, 7, 13, 12, 0, tzinfo=timezone.utc)

    count = repo.reset_spotify_not_found(date(2026, 6, 1), date(2026, 6, 30), now)

    assert count == 2
    sql, params = fake.execute.call_args[0]
    assert "SET spotify_searched_at = NULL" in sql
    assert "updated_at = :now" in sql
    assert "isrc IS NOT NULL" in sql
    assert "spotify_id IS NULL" in sql
    assert "spotify_searched_at IS NOT NULL" in sql
    assert "publish_date BETWEEN :date_from AND :date_to" in sql
    assert "RETURNING id" in sql
    assert params == {
        "now": now,
        "date_from": date(2026, 6, 1),
        "date_to": date(2026, 6, 30),
    }


def test_count_spotify_pending_in_range() -> None:
    repo, fake = _repo([{"cnt": 7}])

    count = repo.count_spotify_pending_in_range(date(2026, 6, 1), date(2026, 6, 30))

    assert count == 7
    sql, params = fake.execute.call_args[0]
    assert "spotify_searched_at IS NULL" in sql
    assert "isrc IS NOT NULL" in sql
    assert "publish_date BETWEEN :date_from AND :date_to" in sql
    assert params == {"date_from": date(2026, 6, 1), "date_to": date(2026, 6, 30)}


def test_find_not_found_applies_date_filters() -> None:
    repo, fake = _repo([])

    repo.find_tracks_not_found_on_spotify(
        limit=50,
        offset=0,
        search=None,
        publish_date_from=date(2026, 6, 1),
        publish_date_to=date(2026, 6, 30),
    )

    sql, params = fake.execute.call_args[0]
    assert "t.publish_date >= :date_from" in sql
    assert "t.publish_date <= :date_to" in sql
    assert params["date_from"] == date(2026, 6, 1)
    assert params["date_to"] == date(2026, 6, 30)


def test_find_not_found_without_dates_keeps_old_sql() -> None:
    repo, fake = _repo([])

    repo.find_tracks_not_found_on_spotify(limit=50, offset=0)

    sql, params = fake.execute.call_args[0]
    assert ":date_from" not in sql
    assert ":date_to" not in sql
    assert params == {"limit": 50, "offset": 0}


def test_count_not_found_applies_date_filters() -> None:
    repo, fake = _repo([{"cnt": 3}])

    count = repo.count_tracks_not_found_on_spotify(
        search=None,
        publish_date_from=date(2026, 6, 1),
        publish_date_to=date(2026, 6, 30),
    )

    assert count == 3
    sql, params = fake.execute.call_args[0]
    assert "publish_date >= :date_from" in sql
    assert "publish_date <= :date_to" in sql
    assert params == {"date_from": date(2026, 6, 1), "date_to": date(2026, 6, 30)}

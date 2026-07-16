"""Tests for the per-week Spotify stats aggregate."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def test_spotify_stats_for_year_sql_and_bounds() -> None:
    fake_data_api = MagicMock()
    fake_data_api.execute.return_value = [
        {
            "beatport_style_id": "90",
            "week_number": 27,
            "total": 50,
            "found": 45,
            "not_found": 3,
            "pending": 1,
            "no_isrc": 1,
        }
    ]
    repo = ClouderRepository(data_api=fake_data_api)

    rows = repo.spotify_stats_for_year(2026)

    assert rows == fake_data_api.execute.return_value
    sql, params = fake_data_api.execute.call_args[0]
    # 2026-01-01 is a Thursday -> first Saturday is Jan 3; 52 weeks end 2027-01-01.
    assert params == {
        "year_start": date(2026, 1, 3),
        "year_end": date(2027, 1, 1),
    }
    assert "(t.publish_date - :year_start) / 7 + 1" in sql
    assert "FILTER (WHERE t.spotify_id IS NOT NULL)" in sql
    assert "im.source = 'beatport'" in sql
    assert "t.publish_date BETWEEN :year_start AND :year_end" in sql
    assert "GROUP BY 1, 2" in sql

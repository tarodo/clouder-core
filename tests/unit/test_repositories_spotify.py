"""Tests for Spotify-search repository methods."""

from __future__ import annotations

from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def test_find_tracks_needing_spotify_search_projects_artists_and_length() -> None:
    fake_data_api = MagicMock()
    fake_data_api.execute.return_value = [
        {
            "id": "t1",
            "isrc": "ZZ1",
            "title": "Move On",
            "normalized_title": "move on",
            "length_ms": 180_000,
            "artists": "Guri, Eider",
        }
    ]
    repo = ClouderRepository(data_api=fake_data_api)

    rows = repo.find_tracks_needing_spotify_search(limit=10)

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
    sql, params = fake_data_api.execute.call_args[0]
    assert "length_ms" in sql
    assert "string_agg(DISTINCT a.name" in sql
    assert "LEFT JOIN clouder_track_artists ta" in sql
    assert "LEFT JOIN clouder_artists a" in sql
    assert "GROUP BY t.id" in sql
    assert "spotify_searched_at IS NULL" in sql
    assert params == {"limit": 10}

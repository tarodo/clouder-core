"""Unit tests for PlaylistsRepository.

DataAPIClient is stubbed with a MagicMock that returns canned rows per
SQL fragment match — same pattern as test_categories_repository.py.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
)
from collector.curation.playlists_repository import (
    PlaylistRow,
    PlaylistsRepository,
)


def _utc() -> datetime:
    return datetime(2026, 5, 12, 10, 0, 0, tzinfo=timezone.utc)


def _make_repo(data_api: MagicMock) -> PlaylistsRepository:
    return PlaylistsRepository(data_api=data_api)


def _make_data_api(rows_by_sql_substring: dict[str, list[dict]]) -> MagicMock:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx-1"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql: str, params=None, transaction_id=None):
        for needle, rows in rows_by_sql_substring.items():
            if needle in sql:
                return rows
        return []

    api.execute.side_effect = _execute
    return api


def test_create_inserts_row_and_returns_playlist() -> None:
    api = _make_data_api({
        "SELECT COUNT(*) AS cnt FROM playlists": [{"cnt": 5}],
        "INSERT INTO playlists": [{
            "id": "p-1",
            "user_id": "u-1",
            "name": "My Set",
            "normalized_name": "my set",
            "description": None,
            "is_public": False,
            "cover_s3_key": None,
            "cover_uploaded_at": None,
            "spotify_playlist_id": None,
            "last_published_at": None,
            "needs_republish": False,
            "track_count": 0,
            "created_at": _utc().isoformat(),
            "updated_at": _utc().isoformat(),
        }],
    })
    repo = _make_repo(api)
    row = repo.create(
        user_id="u-1", playlist_id="p-1", name="My Set",
        normalized_name="my set", description=None, is_public=False, now=_utc(),
    )
    assert isinstance(row, PlaylistRow)
    assert row.id == "p-1"
    assert row.track_count == 0


def test_create_raises_limit_reached_at_200() -> None:
    api = _make_data_api({
        "SELECT COUNT(*) AS cnt FROM playlists": [{"cnt": 200}],
    })
    repo = _make_repo(api)
    with pytest.raises(PlaylistLimitReachedError):
        repo.create(
            user_id="u-1", playlist_id="p-x", name="N",
            normalized_name="n", description=None, is_public=False, now=_utc(),
        )


def test_create_translates_unique_violation_to_name_conflict() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx-1"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT COUNT(*) AS cnt FROM playlists" in sql:
            return [{"cnt": 0}]
        if "INSERT INTO playlists" in sql:
            raise RuntimeError(
                "duplicate key value violates unique constraint "
                "\"uq_playlists_user_normname\""
            )
        return []

    api.execute.side_effect = _execute
    repo = _make_repo(api)
    with pytest.raises(PlaylistNameConflictError):
        repo.create(
            user_id="u-1", playlist_id="p-x", name="dup",
            normalized_name="dup", description=None, is_public=False, now=_utc(),
        )


def test_get_returns_none_for_unknown_id() -> None:
    api = _make_data_api({})
    repo = _make_repo(api)
    assert repo.get(user_id="u-1", playlist_id="missing") is None


def test_get_filters_soft_deleted() -> None:
    api = MagicMock()
    captured = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["sql"] = sql
        captured["params"] = params
        return []

    api.execute.side_effect = _execute
    api.transaction.return_value.__enter__.return_value = "tx"
    repo = _make_repo(api)
    repo.get(user_id="u-1", playlist_id="p-1")
    assert "deleted_at IS NULL" in captured["sql"]
    assert captured["params"]["user_id"] == "u-1"


def test_soft_delete_returns_false_when_no_row_affected() -> None:
    api = _make_data_api({"UPDATE playlists SET deleted_at": []})
    repo = _make_repo(api)
    assert repo.soft_delete(user_id="u-1", playlist_id="p-1", now=_utc()) is False


def test_soft_delete_returns_true_when_row_affected() -> None:
    api = _make_data_api({
        "UPDATE playlists SET deleted_at": [{"id": "p-1"}],
    })
    repo = _make_repo(api)
    assert repo.soft_delete(user_id="u-1", playlist_id="p-1", now=_utc()) is True


def test_patch_raises_not_found_when_missing() -> None:
    api = _make_data_api({})
    repo = _make_repo(api)
    with pytest.raises(PlaylistNotFoundError):
        repo.patch(
            user_id="u-1", playlist_id="missing",
            name="new", normalized_name="new",
            description=None, is_public=None, now=_utc(),
        )

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


from collector.curation import (
    OrderMismatchError,
    PlaylistTrackLimitError,
)
from collector.curation.playlists_repository import PlaylistTrackRow


def test_append_tracks_uses_max_position_plus_one() -> None:
    captured_inserts: list[dict] = []
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 3}]
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 4}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return []  # no duplicates yet
        return []

    def _batch_execute(sql, parameter_sets, transaction_id=None):
        captured_inserts.extend(parameter_sets)

    api.execute.side_effect = _execute
    api.batch_execute.side_effect = _batch_execute

    repo = PlaylistsRepository(api)
    result = repo.append_tracks(
        user_id="u-1",
        playlist_id="p-1",
        track_ids=["t-a", "t-b"],
        now=_utc(),
    )
    assert result.added_track_ids == ["t-a", "t-b"]
    assert result.skipped_duplicates == []
    assert result.position_after == 7
    assert [p["position"] for p in captured_inserts] == [5, 6]


def test_append_tracks_dedups_against_existing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 1}]
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 0}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-a"}]
        return []

    api.execute.side_effect = _execute
    api.batch_execute = MagicMock()

    repo = PlaylistsRepository(api)
    result = repo.append_tracks(
        user_id="u-1", playlist_id="p-1",
        track_ids=["t-a", "t-b"], now=_utc(),
    )
    assert result.added_track_ids == ["t-b"]
    assert result.skipped_duplicates == ["t-a"]


def test_append_tracks_rejects_when_over_limit() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 999}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return []
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": 998}]
        return []

    api.execute.side_effect = _execute
    api.batch_execute = MagicMock()
    repo = PlaylistsRepository(api)
    with pytest.raises(PlaylistTrackLimitError):
        repo.append_tracks(
            user_id="u-1", playlist_id="p-1",
            track_ids=["a", "b"], now=_utc(),
        )


def test_remove_track_redenses_positions() -> None:
    captured = []
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        captured.append((sql.strip().split()[0], params))
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT position FROM playlist_tracks" in sql:
            return [{"position": 2}]
        if "DELETE FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    removed = repo.remove_track(
        user_id="u-1", playlist_id="p-1", track_id="t-1", now=_utc()
    )
    assert removed is True
    assert any("UPDATE" in op for op, _ in captured)


def test_remove_track_returns_false_when_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT position FROM playlist_tracks" in sql:
            return []
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    assert (
        repo.remove_track(
            user_id="u-1", playlist_id="p-1", track_id="x", now=_utc()
        )
        is False
    )


def test_reorder_rejects_mismatched_set() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}, {"track_id": "t-2"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    with pytest.raises(OrderMismatchError):
        repo.reorder_tracks(
            user_id="u-1", playlist_id="p-1",
            ordered_track_ids=["t-1", "t-2", "t-3"], now=_utc(),
        )


def test_reorder_accepts_permutation_and_emits_updates() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return [{"track_id": "t-1"}, {"track_id": "t-2"}]
        return []

    batched = []
    api.execute.side_effect = _execute
    api.batch_execute.side_effect = (
        lambda sql, parameter_sets, transaction_id=None: batched.extend(parameter_sets)
    )
    repo = PlaylistsRepository(api)
    repo.reorder_tracks(
        user_id="u-1", playlist_id="p-1",
        ordered_track_ids=["t-2", "t-1"], now=_utc(),
    )
    assert {(p["track_id"], p["position"]) for p in batched} == {
        ("t-2", 0), ("t-1", 1),
    }


def test_list_tracks_returns_rows_with_position() -> None:
    api = _make_data_api({
        "SELECT 1 AS ok FROM playlists": [{"ok": 1}],
        # Check the COUNT needle before the JOIN needle: the JOIN needle
        # "FROM playlist_tracks pt" is also a substring of the COUNT SQL
        # (which uses alias "pt2"), so insertion order matters here.
        "SELECT COUNT(*) AS total FROM playlist_tracks pt2": [{"total": 1}],
        "FROM playlist_tracks pt": [
            {
                "track_id": "t-1", "position": 0, "added_at": _utc().isoformat(),
                "title": "Title A", "spotify_id": "s-a", "isrc": None,
                "length_ms": 200000, "origin": "beatport",
            },
        ],
    })
    repo = PlaylistsRepository(api)
    rows, total = repo.list_tracks(
        user_id="u-1", playlist_id="p-1", limit=50, offset=0,
    )
    assert total == 1
    assert isinstance(rows[0], PlaylistTrackRow)
    assert rows[0].position == 0


def test_set_cover_updates_row_and_marks_dirty() -> None:
    captured = {}
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        captured.setdefault("calls", []).append((sql, params))
        if "RETURNING" in sql:
            return [{"id": "p-1"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    ok = repo.set_cover(
        user_id="u-1", playlist_id="p-1",
        s3_key="covers/u-1/p-1/123.jpg", now=_utc(),
    )
    assert ok is True
    sqls = " | ".join(s for s, _ in captured["calls"])
    assert "cover_s3_key" in sqls
    assert "needs_republish" in sqls


def test_set_cover_returns_false_when_playlist_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = lambda *a, **k: []
    repo = PlaylistsRepository(api)
    assert repo.set_cover(
        user_id="u-1", playlist_id="p-1",
        s3_key="x", now=_utc(),
    ) is False


def test_clear_cover_returns_true_when_affected() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = lambda *a, **k: [{"id": "p-1"}]
    repo = PlaylistsRepository(api)
    assert repo.clear_cover(user_id="u-1", playlist_id="p-1", now=_utc()) is True


def test_set_publish_state_persists_and_clears_dirty() -> None:
    api = MagicMock()
    captured = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["sql"] = sql
        captured["params"] = params
        return [{"id": "p-1"}]

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.set_publish_state(
        user_id="u-1", playlist_id="p-1",
        spotify_playlist_id="spt-abc", now=_utc(),
    )
    assert captured["params"]["spotify_playlist_id"] == "spt-abc"
    # Default mark_dirty=False → needs_republish bound to False.
    assert captured["params"]["needs_republish"] is False


def test_set_publish_state_mark_dirty_keeps_republish_true() -> None:
    api = MagicMock()
    captured = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["params"] = params
        return [{"id": "p-1"}]

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.set_publish_state(
        user_id="u-1", playlist_id="p-1",
        spotify_playlist_id="spt", now=_utc(), mark_dirty=True,
    )
    assert captured["params"]["needs_republish"] is True


def test_validate_tracks_in_scope_returns_subset() -> None:
    api = _make_data_api({
        "SELECT t.id": [{"id": "t-1"}, {"id": "t-3"}],
    })
    repo = PlaylistsRepository(api)
    visible = repo.validate_tracks_in_scope(
        user_id="u-1", track_ids=["t-1", "t-2", "t-3"],
    )
    assert visible == {"t-1", "t-3"}


def test_validate_tracks_in_scope_empty_input() -> None:
    api = MagicMock()
    repo = PlaylistsRepository(api)
    assert repo.validate_tracks_in_scope(user_id="u-1", track_ids=[]) == set()
    api.execute.assert_not_called()


def test_upsert_imported_track_uses_existing_when_spotify_id_matches() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            return [{"id": "existing-track-id"}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=200_000, now=_utc(),
    )
    assert track_id == "existing-track-id"


def test_upsert_imported_track_inserts_new_when_missing() -> None:
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    calls = []

    def _execute(sql, params=None, transaction_id=None):
        calls.append(sql)
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            return []
        if "INSERT INTO clouder_tracks" in sql:
            return [{"id": params["id"]}]
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=None, now=_utc(),
    )
    assert track_id
    assert any("INSERT INTO clouder_tracks" in s for s in calls)
    assert any("INSERT INTO user_imported_tracks" in s for s in calls)


def test_upsert_imported_track_handles_race_on_conflict() -> None:
    """ON CONFLICT skipped → repository re-SELECTs the winner's id."""
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    state = {"selected": 0}

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            state["selected"] += 1
            if state["selected"] == 1:
                return []  # first check: not there
            return [{"id": "winner"}]  # second check after ON CONFLICT
        if "INSERT INTO clouder_tracks" in sql:
            return []  # conflict, nothing returned
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=None, now=_utc(),
    )
    assert track_id == "winner"

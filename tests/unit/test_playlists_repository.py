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
            description=None, is_public=None, status=None, now=_utc(),
        )


from collector.curation import (
    OrderMismatchError,
    PlaylistTrackLimitError,
)
from collector.curation.playlists_repository import PlaylistTrackRow
from collector.curation.tags_repository import TrackTagRow


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


def test_validate_tracks_in_scope_uses_parametric_in_list_not_any() -> None:
    """Regression: Aurora Data API rejects PostgreSQL arrays passed as JSON
    (`op ANY/ALL (array) requires array on right side`). The repository must
    expand `track_ids` into per-id placeholders inside an `IN (...)` clause.
    """
    captured: dict[str, object] = {}

    def _execute(sql, params=None, transaction_id=None):
        captured["sql"] = sql
        captured["params"] = params
        return [{"id": "t-1"}]

    api = MagicMock()
    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.validate_tracks_in_scope(user_id="u-1", track_ids=["t-1", "t-2"])
    sql = captured["sql"]
    assert "ANY(" not in sql, f"ANY() must not be used: {sql!r}"
    assert ":t0" in sql and ":t1" in sql
    assert captured["params"] == {"user_id": "u-1", "t0": "t-1", "t1": "t-2"}


def test_append_tracks_uses_parametric_in_list_for_dedup_check() -> None:
    """Regression: same Data API constraint as scope-check — the dedup SELECT
    inside append_tracks must build `IN (:t0, :t1)`, not `ANY(:ids)`.
    """
    seen_sqls: list[str] = []
    seen_params: list[dict] = []

    def _execute(sql, params=None, transaction_id=None):
        seen_sqls.append(sql)
        seen_params.append(params or {})
        if "SELECT 1 AS ok FROM playlists" in sql:
            return [{"ok": 1}]
        if "SELECT COUNT(*) AS cnt FROM playlist_tracks" in sql:
            return [{"cnt": 0}]
        if "SELECT COALESCE(MAX(position), -1)" in sql:
            return [{"max_pos": -1}]
        if "SELECT track_id FROM playlist_tracks" in sql:
            return []
        return []

    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False
    api.execute.side_effect = _execute
    api.batch_execute = MagicMock()
    repo = PlaylistsRepository(api)
    repo.append_tracks(
        user_id="u-1", playlist_id="p-1",
        track_ids=["t-a", "t-b"], now=_utc(),
    )
    dedup_sql = next(
        s for s in seen_sqls if "SELECT track_id FROM playlist_tracks" in s
    )
    assert "ANY(" not in dedup_sql, f"ANY() must not be used: {dedup_sql!r}"
    assert ":t0" in dedup_sql and ":t1" in dedup_sql


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
    # spotify_id is intentionally not unique → no ON CONFLICT clause on it
    assert not any("ON CONFLICT (spotify_id)" in s for s in calls)


def test_upsert_imported_track_returns_existing_winner_under_race() -> None:
    """If multiple clouder_tracks rows share spotify_id (legitimate prod
    state), upsert reuses whichever one SELECT happens to return first
    and adds the user-imported marker against it."""
    api = MagicMock()
    api.transaction.return_value.__enter__.return_value = "tx"
    api.transaction.return_value.__exit__.return_value = False

    def _execute(sql, params=None, transaction_id=None):
        if "SELECT id FROM clouder_tracks WHERE spotify_id" in sql:
            return [{"id": "existing-1"}]  # picks first
        return []

    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    track_id = repo.upsert_imported_track(
        user_id="u-1",
        spotify_id="spt-abc",
        title="X", isrc=None, length_ms=None, now=_utc(),
    )
    assert track_id == "existing-1"


# ---- status filter / patch ----------------------------------------------


def test_list_all_filters_by_status_when_requested() -> None:
    captured: dict[str, object] = {}

    def _execute(sql, params=None, transaction_id=None):
        captured.setdefault("sqls", []).append(sql)
        captured.setdefault("params", []).append(params)
        if "COUNT(*) AS total" in sql:
            return [{"total": 0}]
        return []

    api = MagicMock()
    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.list_all(user_id="u-1", limit=20, offset=0, status="active")
    sqls = captured["sqls"]
    assert any("p.status = :status" in s for s in sqls)
    params_list = captured["params"]
    assert all(p.get("status") == "active" for p in params_list)


def test_list_all_omits_status_clause_when_none() -> None:
    captured: dict[str, object] = {}

    def _execute(sql, params=None, transaction_id=None):
        captured.setdefault("sqls", []).append(sql)
        captured.setdefault("params", []).append(params)
        if "COUNT(*) AS total" in sql:
            return [{"total": 0}]
        return []

    api = MagicMock()
    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    repo.list_all(user_id="u-1", limit=20, offset=0, status=None)
    sqls = captured["sqls"]
    # _PLAYLIST_SELECT projects p.status (column read), but the WHERE
    # clause must NOT include a status filter.
    assert all("p.status = " not in s for s in sqls)
    assert all("AND status = " not in s for s in sqls)
    # And no `status` param bound to either query.
    params_list = captured["params"]
    assert all("status" not in (p or {}) for p in params_list)


def test_patch_status_does_not_set_needs_republish() -> None:
    """Status flip is organizational, not Spotify-visible — must not mark drift."""
    captured: dict[str, object] = {"sqls": []}

    def _execute(sql, params=None, transaction_id=None):
        captured["sqls"].append(sql)
        if "UPDATE playlists SET" in sql:
            return [{
                "id": "p-1", "user_id": "u-1", "name": "n",
                "normalized_name": "n", "description": None, "is_public": False,
                "cover_s3_key": None, "cover_uploaded_at": None,
                "spotify_playlist_id": "sp-1",
                "last_published_at": "2026-05-12T00:00:00",
                "needs_republish": False,
                "status": "completed",
                "created_at": "2026-05-12T00:00:00",
                "updated_at": "2026-05-12T00:00:00",
            }]
        if "SELECT" in sql and "FROM playlists p" in sql:
            return [{
                "id": "p-1", "user_id": "u-1", "name": "n",
                "normalized_name": "n", "description": None, "is_public": False,
                "cover_s3_key": None, "cover_uploaded_at": None,
                "spotify_playlist_id": "sp-1",
                "last_published_at": "2026-05-12T00:00:00",
                "needs_republish": False,
                "status": "completed",
                "track_count": 0,
                "created_at": "2026-05-12T00:00:00",
                "updated_at": "2026-05-12T00:00:00",
            }]
        return []

    api = MagicMock()
    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    out = repo.patch(
        user_id="u-1", playlist_id="p-1",
        name=None, normalized_name=None,
        description=None, is_public=None, status="completed",
        now=_utc(),
    )
    assert out.status == "completed"
    # Sanity: the UPDATE SQL gates needs_republish on name/desc/is_public,
    # not on status.
    update_sql = next(s for s in captured["sqls"] if "UPDATE playlists SET" in s)
    assert "spotify_playlist_id IS NOT NULL" in update_sql
    # Drift gate references name / description_set / is_public — casts
    # are explicit so status-only patches don't trip Data API type inference.
    assert ":name::text IS NOT NULL" in update_sql
    assert ":description_set::boolean" in update_sql
    assert ":is_public::boolean IS NOT NULL" in update_sql


def test_patch_sql_has_explicit_param_casts() -> None:
    """Regression: Aurora Data API failed status-only patches with
    `could not determine data type of parameter $N` because params
    appear in both COALESCE and IS NOT NULL contexts. Every param the
    UPDATE binds must carry an explicit ::type cast."""
    captured: dict[str, object] = {"sqls": []}

    def _execute(sql, params=None, transaction_id=None):
        captured["sqls"].append(sql)
        if "UPDATE playlists SET" in sql:
            return [{
                "id": "p-1", "user_id": "u-1", "name": "n",
                "normalized_name": "n", "description": None, "is_public": False,
                "cover_s3_key": None, "cover_uploaded_at": None,
                "spotify_playlist_id": None, "last_published_at": None,
                "needs_republish": False, "status": "completed",
                "created_at": "2026-05-12T00:00:00",
                "updated_at": "2026-05-12T00:00:00",
            }]
        if "SELECT" in sql and "FROM playlists p" in sql:
            return [{
                "id": "p-1", "user_id": "u-1", "name": "n",
                "normalized_name": "n", "description": None, "is_public": False,
                "cover_s3_key": None, "cover_uploaded_at": None,
                "spotify_playlist_id": None, "last_published_at": None,
                "needs_republish": False, "status": "completed",
                "track_count": 0,
                "created_at": "2026-05-12T00:00:00",
                "updated_at": "2026-05-12T00:00:00",
            }]
        return []

    api = MagicMock()
    api.execute.side_effect = _execute
    repo = PlaylistsRepository(api)
    # Status-only patch — all other inputs None.
    repo.patch(
        user_id="u-1", playlist_id="p-1",
        name=None, normalized_name=None,
        description=None, is_public=None, status="completed",
        now=_utc(),
    )
    update_sql = next(s for s in captured["sqls"] if "UPDATE playlists SET" in s)
    for cast in (":name::text", ":normalized_name::text",
                 ":description::text", ":description_set::boolean",
                 ":is_public::boolean", ":status::text"):
        assert cast in update_sql, f"missing explicit cast {cast}"


# ---- enrich list_tracks (artists, label, bpm, tags) ---------------------


def test_list_tracks_enrich_returns_artists_label_bpm_and_tags() -> None:
    """list_tracks with tags_repo attaches artists, label, bpm, mix_name,
    spotify_release_date, is_ai_suspected, and tags from the fan-in repo."""
    api = _make_data_api({
        "SELECT 1 AS ok FROM playlists": [{"ok": 1}],
        "SELECT COUNT(*) AS total FROM playlist_tracks pt2": [{"total": 1}],
        "FROM playlist_tracks pt": [
            {
                "track_id": "tr1",
                "position": 0,
                "added_at": _utc().isoformat(),
                "title": "Acid Trip",
                "spotify_id": "sp1",
                "isrc": "USABC123456",
                "length_ms": 360000,
                "origin": "beatport",
                "mix_name": "Original Mix",
                "bpm": 140,
                "spotify_release_date": "2026-01-15",
                "is_ai_suspected": False,
                "artists_json": '[{"id": "a1", "name": "Artist"}]',
                "label_id": "l1",
                "label_name": "Label",
            },
        ],
    })

    tags_repo = MagicMock()
    tags_repo.list_tags_for_tracks.return_value = {
        "tr1": [TrackTagRow(track_id="tr1", tag_id="tg1", name="acid", color="#ff0000")]
    }

    repo = PlaylistsRepository(api)
    rows, total = repo.list_tracks(
        user_id="u-1", playlist_id="p-1", limit=50, offset=0, tags_repo=tags_repo,
    )

    assert total == 1
    row = rows[0]
    assert isinstance(row, PlaylistTrackRow)
    assert row.mix_name == "Original Mix"
    assert row.bpm == 140
    assert row.spotify_release_date == "2026-01-15"
    assert row.is_ai_suspected is False
    assert row.artists == ({"id": "a1", "name": "Artist"},)
    assert row.label == {"id": "l1", "name": "Label"}
    assert len(row.tags) == 1
    assert row.tags[0].tag_id == "tg1"
    assert row.tags[0].name == "acid"
    assert row.tags[0].color == "#ff0000"

    tags_repo.list_tags_for_tracks.assert_called_once_with(
        user_id="u-1", track_ids=["tr1"],
    )


def test_list_tracks_enrich_no_tags_repo_returns_empty_tags_tuple() -> None:
    """When tags_repo is omitted, tags field defaults to empty tuple."""
    api = _make_data_api({
        "SELECT 1 AS ok FROM playlists": [{"ok": 1}],
        "SELECT COUNT(*) AS total FROM playlist_tracks pt2": [{"total": 1}],
        "FROM playlist_tracks pt": [
            {
                "track_id": "tr1",
                "position": 0,
                "added_at": _utc().isoformat(),
                "title": "Acid Trip",
                "spotify_id": None,
                "isrc": None,
                "length_ms": None,
                "origin": "beatport",
                "mix_name": None,
                "bpm": None,
                "spotify_release_date": None,
                "is_ai_suspected": False,
                "artists_json": "[]",
                "label_id": None,
                "label_name": None,
            },
        ],
    })

    repo = PlaylistsRepository(api)
    rows, total = repo.list_tracks(
        user_id="u-1", playlist_id="p-1", limit=50, offset=0,
    )
    assert total == 1
    assert rows[0].tags == ()
    assert rows[0].artists == ()
    assert rows[0].label is None

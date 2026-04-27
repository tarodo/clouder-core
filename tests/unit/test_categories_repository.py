from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from collector.curation import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
)
from collector.curation.categories_repository import (
    CategoriesRepository,
    CategoryRow,
    TrackInCategoryRow,
)


def _make() -> tuple[CategoriesRepository, MagicMock]:
    data_api = MagicMock()
    return CategoriesRepository(data_api=data_api), data_api


def _now() -> datetime:
    return datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)


def test_repository_constructs() -> None:
    repo, _ = _make()
    assert repo is not None


def test_category_row_dataclass_shape() -> None:
    row = CategoryRow(
        id="c1",
        user_id="u1",
        style_id="s1",
        style_name="House",
        name="Tech",
        normalized_name="tech",
        position=0,
        track_count=5,
        created_at="2026-04-27T12:00:00Z",
        updated_at="2026-04-27T12:00:00Z",
    )
    assert row.id == "c1"
    assert row.style_name == "House"
    assert row.track_count == 5


def test_track_in_category_row_dataclass_shape() -> None:
    row = TrackInCategoryRow(
        track={"id": "t1", "title": "X", "artists": ["A"]},
        added_at="2026-04-27T12:00:00Z",
        source_triage_block_id=None,
    )
    assert row.track["id"] == "t1"
    assert row.source_triage_block_id is None


def test_create_starts_transaction_and_inserts() -> None:
    repo, data_api = _make()

    # data_api.transaction() is a contextmanager yielding tx_id
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # First call: style existence -> 1 row.
    # Second call: max(position) -> [{"max_pos": 2}].
    # Third call: insert returning row.
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"max_pos": 2}],
        [
            {
                "id": "c1",
                "user_id": "u1",
                "style_id": "s1",
                "style_name": "House",
                "name": "Tech",
                "normalized_name": "tech",
                "position": 3,
                "track_count": 0,
                "created_at": "2026-04-27T12:00:00Z",
                "updated_at": "2026-04-27T12:00:00Z",
            }
        ],
    ]

    row = repo.create(
        user_id="u1",
        style_id="s1",
        category_id="c1",
        name="Tech",
        normalized_name="tech",
        now=_now(),
    )

    assert row.id == "c1"
    assert row.position == 3
    # Three execute calls: style check, max-position, insert
    assert data_api.execute.call_count == 3
    style_sql = data_api.execute.call_args_list[0].args[0]
    assert "FROM clouder_styles" in style_sql
    max_sql = data_api.execute.call_args_list[1].args[0]
    assert "MAX(position)" in max_sql
    assert "deleted_at IS NULL" in max_sql
    insert_sql = data_api.execute.call_args_list[2].args[0]
    assert "INSERT INTO categories" in insert_sql
    assert "RETURNING" in insert_sql
    # All three calls must run inside the same transaction
    for call in data_api.execute.call_args_list:
        assert call.kwargs.get("transaction_id") == "tx-1"


def test_create_raises_style_not_found() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [[]]  # style lookup empty
    with pytest.raises(NotFoundError) as exc:
        repo.create(
            user_id="u1",
            style_id="missing",
            category_id="c1",
            name="Tech",
            normalized_name="tech",
            now=_now(),
        )
    assert exc.value.error_code == "style_not_found"


def test_create_maps_unique_violation_to_name_conflict() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False

    class FakeUniqueViolation(Exception):
        def __str__(self) -> str:
            return (
                "duplicate key value violates unique constraint "
                '"uq_categories_user_style_normname"'
            )

    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"max_pos": -1}],
        FakeUniqueViolation(),
    ]
    with pytest.raises(NameConflictError):
        repo.create(
            user_id="u1",
            style_id="s1",
            category_id="c1",
            name="Tech",
            normalized_name="tech",
            now=_now(),
        )


def test_get_returns_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [
        {
            "id": "c1",
            "user_id": "u1",
            "style_id": "s1",
            "style_name": "House",
            "name": "Tech",
            "normalized_name": "tech",
            "position": 0,
            "track_count": 4,
            "created_at": "2026-04-27T12:00:00Z",
            "updated_at": "2026-04-27T12:00:00Z",
        }
    ]
    row = repo.get(user_id="u1", category_id="c1")
    assert row is not None
    assert row.track_count == 4
    sql = data_api.execute.call_args.args[0]
    assert "WHERE c.id = :category_id" in sql
    assert "c.user_id = :user_id" in sql
    assert "c.deleted_at IS NULL" in sql


def test_get_returns_none_when_missing() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    row = repo.get(user_id="u1", category_id="missing")
    assert row is None


def test_list_by_style_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [
            {
                "id": "c1", "user_id": "u1", "style_id": "s1",
                "style_name": "House", "name": "Tech",
                "normalized_name": "tech", "position": 0,
                "track_count": 0,
                "created_at": "x", "updated_at": "x",
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_by_style(
        user_id="u1", style_id="s1", limit=50, offset=0
    )
    assert result.total == 1
    assert len(result.items) == 1
    list_sql = data_api.execute.call_args_list[0].args[0]
    list_params = data_api.execute.call_args_list[0].args[1]
    assert "ORDER BY c.position ASC, c.created_at DESC, c.id ASC" in list_sql
    assert "c.deleted_at IS NULL" in list_sql
    assert "c.style_id = :style_id" in list_sql
    assert "LIMIT :limit OFFSET :offset" in list_sql
    assert list_params == {
        "user_id": "u1", "style_id": "s1", "limit": 50, "offset": 0,
    }
    count_sql = data_api.execute.call_args_list[1].args[0]
    assert "COUNT(*)" in count_sql
    assert "deleted_at IS NULL" in count_sql
    assert "style_id = :style_id" in count_sql


def test_list_all_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[], [{"total": 0}]]
    result = repo.list_all(user_id="u1", limit=50, offset=0)
    assert result.total == 0
    list_sql = data_api.execute.call_args_list[0].args[0]
    list_params = data_api.execute.call_args_list[0].args[1]
    assert "ORDER BY c.created_at DESC, c.id ASC" in list_sql
    assert "c.deleted_at IS NULL" in list_sql
    assert "LIMIT :limit OFFSET :offset" in list_sql
    # No style_id filter in cross-style list
    assert "c.style_id" not in list_sql.split("WHERE")[1].split("ORDER BY")[0]
    assert list_params == {"user_id": "u1", "limit": 50, "offset": 0}
    count_sql = data_api.execute.call_args_list[1].args[0]
    assert "COUNT(*)" in count_sql
    assert "deleted_at IS NULL" in count_sql
    assert "style_id" not in count_sql


def test_rename_updates_and_returns_row() -> None:
    repo, data_api = _make()
    # First execute is the UPDATE ... RETURNING; second is the SELECT for shape.
    data_api.execute.side_effect = [
        [{"id": "c1"}],  # UPDATE returning at least one row -> success
        [
            {
                "id": "c1", "user_id": "u1", "style_id": "s1",
                "style_name": "House", "name": "Deep",
                "normalized_name": "deep", "position": 0,
                "track_count": 0,
                "created_at": "x", "updated_at": "x",
            }
        ],
    ]
    row = repo.rename(
        user_id="u1",
        category_id="c1",
        name="Deep",
        normalized_name="deep",
        now=_now(),
    )
    assert row.name == "Deep"
    update_sql = data_api.execute.call_args_list[0].args[0]
    update_params = data_api.execute.call_args_list[0].args[1]
    assert "UPDATE categories" in update_sql
    assert "user_id = :user_id" in update_sql
    assert "deleted_at IS NULL" in update_sql
    assert "SET name = :name" in update_sql
    assert "normalized_name = :normalized_name" in update_sql
    assert update_params["user_id"] == "u1"
    assert update_params["category_id"] == "c1"


def test_rename_raises_not_found_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.rename(
            user_id="u1", category_id="missing",
            name="x", normalized_name="x", now=_now(),
        )
    assert exc.value.error_code == "category_not_found"


def test_rename_maps_unique_violation_to_name_conflict() -> None:
    repo, data_api = _make()

    class FakeUniqueViolation(Exception):
        def __str__(self) -> str:
            return (
                "duplicate key value violates unique constraint "
                "\"uq_categories_user_style_normname\""
            )

    data_api.execute.side_effect = [FakeUniqueViolation()]
    with pytest.raises(NameConflictError):
        repo.rename(
            user_id="u1", category_id="c1",
            name="x", normalized_name="x", now=_now(),
        )


def test_soft_delete_updates_deleted_at() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = [{"id": "c1"}]
    deleted = repo.soft_delete(
        user_id="u1", category_id="c1", now=_now()
    )
    assert deleted is True
    sql = data_api.execute.call_args.args[0]
    params = data_api.execute.call_args.args[1]
    assert "UPDATE categories" in sql
    assert "user_id = :user_id" in sql
    assert "deleted_at = :now" in sql
    assert "deleted_at IS NULL" in sql
    assert params["user_id"] == "u1"
    assert params["category_id"] == "c1"


def test_soft_delete_returns_false_when_no_row() -> None:
    repo, data_api = _make()
    data_api.execute.return_value = []
    deleted = repo.soft_delete(
        user_id="u1", category_id="missing", now=_now()
    )
    assert deleted is False


def test_reorder_validates_set_and_updates_positions() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # First execute: style existence check
    # Second execute: SELECT current alive ids -> three rows
    # N execute calls: UPDATE per id (3 here)
    # Last call: SELECT updated rows with full shape (list_by_style equivalent)
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],
        [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        [{"id": "c"}],
        [{"id": "a"}],
        [{"id": "b"}],
        [
            {"id": "c", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "C", "normalized_name": "c",
             "position": 0, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
            {"id": "a", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "A", "normalized_name": "a",
             "position": 1, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
            {"id": "b", "user_id": "u1", "style_id": "s1",
             "style_name": "House", "name": "B", "normalized_name": "b",
             "position": 2, "track_count": 0,
             "created_at": "x", "updated_at": "x"},
        ],
    ]
    result = repo.reorder(
        user_id="u1",
        style_id="s1",
        ordered_ids=["c", "a", "b"],
        now=_now(),
    )
    assert [r.id for r in result] == ["c", "a", "b"]
    select_sql = data_api.execute.call_args_list[1].args[0]
    assert "SELECT id FROM categories" in select_sql
    assert "deleted_at IS NULL" in select_sql
    update_sql = data_api.execute.call_args_list[2].args[0]
    assert "UPDATE categories" in update_sql
    assert "SET position = :position" in update_sql
    assert "user_id = :user_id" in update_sql
    assert "style_id = :style_id" in update_sql
    assert "deleted_at IS NULL" in update_sql
    # All 6 execute calls (style + alive ids + 3 updates + final select) inside same TX
    for call in data_api.execute.call_args_list:
        assert call.kwargs.get("transaction_id") == "tx-1"


def test_reorder_raises_when_style_missing() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    # First call: style lookup -> empty
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.reorder(
            user_id="u1",
            style_id="missing",
            ordered_ids=[],
            now=_now(),
        )
    assert exc.value.error_code == "style_not_found"


def test_reorder_raises_order_mismatch_on_extra_id() -> None:
    repo, data_api = _make()
    data_api.transaction.return_value.__enter__.return_value = "tx-1"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        [{"id": "s1", "name": "House"}],   # style lookup
        [{"id": "a"}, {"id": "b"}],         # current set
    ]
    with pytest.raises(OrderMismatchError):
        repo.reorder(
            user_id="u1", style_id="s1",
            ordered_ids=["a", "b", "c"], now=_now(),
        )


def test_add_tracks_bulk_validates_category_ownership() -> None:
    repo, data_api = _make()
    # Category lookup returns empty -> not_found
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.add_tracks_bulk(
            user_id="u1",
            category_id="c1",
            items=[("t1", None)],
            now=_now(),
        )
    assert exc.value.error_code == "category_not_found"


def test_add_tracks_bulk_inserts_and_returns_count() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],            # category exists
        [{"id": "t1"}, {"id": "t2"}],  # track existence
        [{"track_id": "t1"}, {"track_id": "t2"}],  # INSERT ON CONFLICT RETURNING
    ]
    inserted = repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", None), ("t2", "block-1")],
        now=_now(),
    )
    assert inserted == 2
    insert_sql = data_api.execute.call_args_list[2].args[0]
    assert "INSERT INTO category_tracks" in insert_sql
    assert "ON CONFLICT (category_id, track_id) DO NOTHING" in insert_sql


def test_add_tracks_bulk_raises_track_not_found() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],       # category exists
        [{"id": "t1"}],       # only one of the requested tracks exists
    ]
    with pytest.raises(NotFoundError) as exc:
        repo.add_tracks_bulk(
            user_id="u1", category_id="c1",
            items=[("t1", None), ("t-missing", None)], now=_now(),
        )
    assert exc.value.error_code == "track_not_found"


def test_add_tracks_bulk_passes_transaction_id() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [{"track_id": "t1"}],
    ]
    repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", "block-1")],
        now=_now(),
        transaction_id="external-tx",
    )
    for call in data_api.execute.call_args_list:
        assert call.kwargs.get("transaction_id") == "external-tx"


def test_add_tracks_bulk_dedups_duplicate_track_ids_in_items() -> None:
    """Same track_id twice with different source_triage_block_id must not
    abort the INSERT. First-src-wins."""
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],            # category exists
        [{"id": "t1"}],            # only one unique track to check
        [{"track_id": "t1"}],       # one INSERT row returned
    ]
    inserted = repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", "first-block"), ("t1", "second-block")],
        now=_now(),
    )
    assert inserted == 1
    insert_sql = data_api.execute.call_args_list[2].args[0]
    insert_params = data_api.execute.call_args_list[2].args[1]
    # Only one VALUES tuple, with first-src-wins
    assert insert_sql.count("(:category_id, :tid_") == 1
    assert insert_params["tid_0"] == "t1"
    assert insert_params["src_0"] == "first-block"


def test_add_tracks_bulk_idempotent_returns_zero_when_all_existing() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [],  # ON CONFLICT DO NOTHING -> RETURNING is empty
    ]
    inserted = repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", None)],
        now=_now(),
    )
    assert inserted == 0


def test_add_track_returns_added_when_newly_inserted() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],            # category lookup (inside add_tracks_bulk)
        [{"id": "t1"}],            # track lookup
        [{"track_id": "t1"}],       # INSERT returning -> newly inserted
        [
            {
                "added_at": "2026-04-27T12:00:00+00:00",
                "source_triage_block_id": None,
            }
        ],                          # post-insert SELECT for canonical shape
    ]
    result, was_new = repo.add_track(
        user_id="u1",
        category_id="c1",
        track_id="t1",
        source_triage_block_id=None,
        now=_now(),
    )
    assert was_new is True
    assert result["added_at"] == "2026-04-27T12:00:00+00:00"
    assert result["source_triage_block_id"] is None


def test_add_track_with_source_block_round_trips() -> None:
    """source_triage_block_id round-trips correctly on newly-added path
    (used by spec-D's triage finalize)."""
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [{"track_id": "t1"}],
        [
            {
                "added_at": "2026-04-27T12:00:00+00:00",
                "source_triage_block_id": "block-d-7",
            }
        ],
    ]
    result, was_new = repo.add_track(
        user_id="u1",
        category_id="c1",
        track_id="t1",
        source_triage_block_id="block-d-7",
        now=_now(),
    )
    assert was_new is True
    assert result["source_triage_block_id"] == "block-d-7"


def test_add_track_returns_existing_when_already_present() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"id": "t1"}],
        [],   # ON CONFLICT DO NOTHING -> empty
        [
            {
                "added_at": "2026-04-01T00:00:00Z",
                "source_triage_block_id": "tb-1",
            }
        ],
    ]
    result, was_new = repo.add_track(
        user_id="u1",
        category_id="c1",
        track_id="t1",
        source_triage_block_id=None,
        now=_now(),
    )
    assert was_new is False
    assert result["added_at"] == "2026-04-01T00:00:00Z"
    assert result["source_triage_block_id"] == "tb-1"


def test_remove_track_returns_true_on_delete() -> None:
    repo, data_api = _make()
    # Validate category ownership first (one execute), then delete
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [{"track_id": "t1"}],   # DELETE RETURNING
    ]
    deleted = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t1"
    )
    assert deleted is True
    cat_sql = data_api.execute.call_args_list[0].args[0]
    cat_params = data_api.execute.call_args_list[0].args[1]
    assert "user_id = :user_id" in cat_sql
    assert "deleted_at IS NULL" in cat_sql
    assert cat_params["user_id"] == "u1"
    delete_sql = data_api.execute.call_args_list[1].args[0]
    assert "DELETE FROM category_tracks" in delete_sql


def test_remove_track_raises_category_not_found() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.remove_track(
            user_id="u1", category_id="missing", track_id="t1"
        )
    assert exc.value.error_code == "category_not_found"
    cat_sql = data_api.execute.call_args_list[0].args[0]
    cat_params = data_api.execute.call_args_list[0].args[1]
    assert "user_id = :user_id" in cat_sql
    assert cat_params["user_id"] == "u1"


def test_remove_track_returns_false_when_not_in_category() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],   # DELETE RETURNING -> empty
    ]
    deleted = repo.remove_track(
        user_id="u1", category_id="c1", track_id="t-missing"
    )
    assert deleted is False


def test_list_tracks_validates_category() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [[]]
    with pytest.raises(NotFoundError) as exc:
        repo.list_tracks(
            user_id="u1", category_id="missing",
            limit=50, offset=0, search=None,
        )
    assert exc.value.error_code == "category_not_found"


def test_list_tracks_returns_rows_and_total() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [
            {
                "id": "t1", "title": "Song", "mix_name": None,
                "isrc": "X", "bpm": 124, "length_ms": 360000,
                "publish_date": None, "spotify_id": None,
                "release_type": "single", "is_ai_suspected": False,
                "artist_names": "Artist A,Artist B",
                "added_at": "2026-04-27T12:00:00Z",
                "source_triage_block_id": None,
            }
        ],
        [{"total": 1}],
    ]
    result = repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search=None,
    )
    assert result.total == 1
    item = result.items[0]
    assert item.track["id"] == "t1"
    assert item.track["artists"] == ["Artist A", "Artist B"]
    assert item.added_at == "2026-04-27T12:00:00Z"
    assert item.source_triage_block_id is None


def test_list_tracks_applies_search_lowercased() -> None:
    repo, data_api = _make()
    data_api.execute.side_effect = [
        [{"id": "c1"}],
        [],
        [{"total": 0}],
    ]
    repo.list_tracks(
        user_id="u1", category_id="c1",
        limit=50, offset=0, search="  Tech  ",
    )
    list_sql = data_api.execute.call_args_list[1].args[0]
    list_params = data_api.execute.call_args_list[1].args[1]
    assert "ILIKE" in list_sql
    assert list_params["search"] == "%tech%"

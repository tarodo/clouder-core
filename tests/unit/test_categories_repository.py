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

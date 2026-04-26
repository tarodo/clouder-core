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

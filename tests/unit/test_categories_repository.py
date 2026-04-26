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

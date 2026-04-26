from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.curation.schemas import (
    AddTrackIn,
    CreateCategoryIn,
    RenameCategoryIn,
    ReorderCategoriesIn,
)


def test_create_category_in_accepts_name() -> None:
    obj = CreateCategoryIn.model_validate({"name": "Tech House"})
    assert obj.name == "Tech House"


def test_create_category_in_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        CreateCategoryIn.model_validate({"name": "x", "style_id": "y"})


def test_rename_category_in_accepts_name() -> None:
    obj = RenameCategoryIn.model_validate({"name": "Deep"})
    assert obj.name == "Deep"


def test_reorder_in_accepts_id_array() -> None:
    obj = ReorderCategoriesIn.model_validate(
        {"category_ids": ["a", "b", "c"]}
    )
    assert obj.category_ids == ["a", "b", "c"]


def test_reorder_in_rejects_non_string_ids() -> None:
    with pytest.raises(ValidationError):
        ReorderCategoriesIn.model_validate({"category_ids": [1, 2]})


def test_reorder_in_rejects_missing_field() -> None:
    with pytest.raises(ValidationError):
        ReorderCategoriesIn.model_validate({})


def test_add_track_in_accepts_track_id() -> None:
    obj = AddTrackIn.model_validate({"track_id": "track-uuid"})
    assert obj.track_id == "track-uuid"

"""Request schemas for curation HTTP endpoints (spec-C)."""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field


class CreateCategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class RenameCategoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)


class ReorderCategoriesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_ids: List[str]


class AddTrackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_id: str = Field(min_length=1)

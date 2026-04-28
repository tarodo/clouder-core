"""Request schemas for curation HTTP endpoints (spec-C)."""

from __future__ import annotations

from datetime import date
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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


# ----------------------- spec-D triage schemas -----------------------


class CreateTriageBlockIn(BaseModel):
    style_id: str = Field(..., min_length=36, max_length=36)
    name: str = Field(..., min_length=1, max_length=128)
    date_from: date
    date_to: date

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("name must not be blank")
        return v

    @model_validator(mode="after")
    def _check_date_range(self) -> "CreateTriageBlockIn":
        if self.date_to < self.date_from:
            raise ValueError("date_to must be >= date_from")
        return self


class MoveTracksIn(BaseModel):
    from_bucket_id: str = Field(..., min_length=36, max_length=36)
    to_bucket_id: str = Field(..., min_length=36, max_length=36)
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)

    @field_validator("track_ids")
    @classmethod
    def _all_uuid_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 36:
                raise ValueError(f"track_id must be 36 chars: {t!r}")
        return v


class TransferTracksIn(BaseModel):
    target_bucket_id: str = Field(..., min_length=36, max_length=36)
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)

    @field_validator("track_ids")
    @classmethod
    def _all_uuid_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 36:
                raise ValueError(f"track_id must be 36 chars: {t!r}")
        return v

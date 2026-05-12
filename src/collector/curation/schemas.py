"""Request schemas for curation HTTP endpoints (spec-C)."""

from __future__ import annotations

from datetime import date
from typing import List, Literal

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
    model_config = ConfigDict(extra="forbid")
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
    model_config = ConfigDict(extra="forbid")
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
    model_config = ConfigDict(extra="forbid")
    target_bucket_id: str = Field(..., min_length=36, max_length=36)
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)

    @field_validator("track_ids")
    @classmethod
    def _all_uuid_shape(cls, v: list[str]) -> list[str]:
        for t in v:
            if len(t) != 36:
                raise ValueError(f"track_id must be 36 chars: {t!r}")
        return v


# ----------------------- Playlists (spec 2026-05-11) -----------------------


class CreatePlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_public: bool = False


class PatchPlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=300)
    is_public: bool | None = None
    status: Literal["active", "completed"] | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "PatchPlaylistIn":
        if (
            self.name is None
            and self.description is None
            and self.is_public is None
            and self.status is None
        ):
            raise ValueError(
                "At least one of name/description/is_public/status must be set"
            )
        return self


class AddTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_ids: list[str] = Field(..., min_length=1, max_length=1000)


class ReorderPlaylistTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track_ids: list[str]


class ImportSpotifyTracksIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spotify_refs: list[str] = Field(..., min_length=1, max_length=50)


class PublishPlaylistIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_overwrite: bool = False


class CoverUploadUrlIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content_type: str = Field(..., pattern=r"^image/jpeg$")

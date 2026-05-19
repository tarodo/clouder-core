"""Pydantic schemas for external input boundaries."""

from __future__ import annotations

from datetime import date

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    ValidationError as PydanticValidationError,
    field_validator,
    model_validator,
)


class CollectRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bp_token: str = Field(min_length=1)
    style_id: StrictInt = Field(gt=0)
    iso_year: StrictInt = Field(ge=2000, le=2100)
    iso_week: StrictInt = Field(ge=1, le=53)

    @field_validator("bp_token")
    @classmethod
    def _normalize_bp_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("bp_token is required and must be a non-empty string")
        return normalized

    @model_validator(mode="after")
    def _validate_iso_week_pair(self) -> CollectRequestIn:
        try:
            date.fromisocalendar(self.iso_year, self.iso_week, 1)
        except ValueError as exc:
            raise ValueError("iso_year/iso_week combination is invalid") from exc
        return self


class CanonicalizationMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: str
    source: str = "beatport"
    s3_key: str
    style_id: int | None = None
    iso_year: int | None = None
    iso_week: int | None = None
    attempt: int = Field(default=1, ge=1)

    @field_validator("run_id", "s3_key")
    @classmethod
    def _validate_non_empty_fields(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must be a non-empty string")
        return normalized


class MigrationCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")

    action: str = "upgrade"
    revision: str = "head"

    @field_validator("action")
    @classmethod
    def _validate_action(cls, value: str) -> str:
        action = value.strip().lower()
        if action != "upgrade":
            raise ValueError("Unsupported action. Only 'upgrade' is allowed.")
        return action

    @field_validator("revision")
    @classmethod
    def _normalize_revision(cls, value: str) -> str:
        normalized = value.strip()
        return normalized or "head"


class VendorMatchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    clouder_track_id: str
    vendor: str
    isrc: str | None = None
    artist: str
    title: str
    duration_ms: int | None = None
    album: str | None = None
    attempt: StrictInt = Field(default=1, ge=1)

    @field_validator("clouder_track_id", "vendor", "artist", "title")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must be a non-empty string")
        return normalized


class SpotifySearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    batch_size: StrictInt = Field(default=2000, ge=1, le=5000)
    auto_continue: bool = Field(default=True)


class AdminIngestRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style_id: StrictInt = Field(gt=0)
    week_year: StrictInt = Field(ge=2000, le=2100)
    week_number: StrictInt = Field(ge=1, le=53)
    period_start: date | None = None
    period_end: date | None = None
    bp_token: str = Field(min_length=1)

    @field_validator("bp_token")
    @classmethod
    def _normalize_bp_token(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("bp_token is required and must be a non-empty string")
        return normalized

    @model_validator(mode="after")
    def _validate_range_constraints(self) -> "AdminIngestRequestIn":
        from .saturday_week import weeks_in_year

        if (self.period_start is None) != (self.period_end is None):
            raise ValueError(
                "period_start and period_end must both be present or both absent"
            )
        if self.period_start is not None and self.period_end is not None:
            if self.period_end < self.period_start:
                raise ValueError("period_end must be on or after period_start")
        limit = weeks_in_year(self.week_year)
        if self.week_number > limit:
            raise ValueError(
                f"week_number {self.week_number} exceeds weeks_in_year({self.week_year}) = {limit}"
            )
        return self


def validation_error_message(exc: PydanticValidationError) -> str:
    if not exc.errors():
        return "Validation failed"
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "Validation failed"))
    return f"{location}: {message}" if location else message

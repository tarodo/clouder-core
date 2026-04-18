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
    search_label_count: StrictInt | None = Field(default=None, ge=1, le=200)

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


class LabelSearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label_id: str
    label_name: str
    styles: str
    prompt_slug: str = "label_info"
    prompt_version: str = "v1"

    @field_validator("label_id", "label_name", "styles")
    @classmethod
    def _validate_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must be a non-empty string")
        return normalized


class EntitySearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    entity_type: str
    entity_id: str
    prompt_slug: str
    prompt_version: str
    context: dict[str, object] = Field(default_factory=dict)

    @field_validator("entity_type", "entity_id", "prompt_slug", "prompt_version")
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


def validation_error_message(exc: PydanticValidationError) -> str:
    if not exc.errors():
        return "Validation failed"
    first = exc.errors()[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "Validation failed"))
    return f"{location}: {message}" if location else message

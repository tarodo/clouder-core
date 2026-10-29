"""Pydantic schemas for external input boundaries."""

from __future__ import annotations

import json
import math
import re
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StringConstraints,
    field_validator,
    model_validator,
)
from pydantic import (
    ValidationError as PydanticValidationError,
)
from pydantic.config import JsonDict


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
    # The one delayed message that carries a search over a Spotify ban.
    resume: bool = Field(default=False)


class YoutubeSearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    batch_size: StrictInt = Field(default=250, ge=1, le=500)


AnalyzerName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,31}$")]
_RESULT_MAX_BYTES = 32_768
# AI detectors: an ok result is {ai_detected: bool, score: number in [0, 1], ...}.
AI_ANALYZERS = ("ai_detect", "ai_lofcz", "ai_deezer")


class AnalysisClaimRequest(BaseModel):
    """POST /v1/analysis/claim: lease tracks missing any of *analyzers*."""

    model_config = ConfigDict(extra="forbid")

    limit: StrictInt = Field(default=20, ge=1, le=50)
    analyzers: list[AnalyzerName] = Field(min_length=1, max_length=8)
    # 30 min for a claim posted right away; a batch run holds its tracks for hours.
    lease_seconds: StrictInt = Field(default=1800, ge=60, le=86400)
    # The client's id for this claim, the same on its retries: a retry gets the tracks the
    # first attempt leased (a gateway timeout does not stop the Lambda). None = server mints one.
    lease_id: UUID | None = None

    @field_validator("analyzers")
    @classmethod
    def _unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("analyzers must be distinct")
        return value


# The status rule of _shape below, also published in the schema so the
# analyzer's contract test sees it.
_RESULT_STATUS_RULE: JsonDict = {
    "allOf": [
        {
            "if": {"properties": {"status": {"const": "ok"}}},
            "then": {"required": ["result"], "properties": {"result": {"type": "object"}}},
            "else": {
                "required": ["error"],
                "properties": {
                    "error": {"type": "string", "minLength": 1},
                    "result": {"type": "null"},
                },
            },
        }
    ]
}


class AnalysisResultItem(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra=_RESULT_STATUS_RULE)

    track_id: str = Field(min_length=1, max_length=36)
    analyzer: AnalyzerName
    version: str = Field(min_length=1, max_length=64, pattern=r"^[\x20-\x7e]+$")
    status: Literal["ok", "failed", "unusable_source"]
    result: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=500)
    audio_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    video_id: str | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def _shape(self) -> AnalysisResultItem:
        if self.status == "ok":
            if self.result is None:
                raise ValueError("result is required when status is ok")
        else:
            if not self.error:
                raise ValueError("error is required unless status is ok")
            if self.result is not None:
                raise ValueError("result must be null unless status is ok")
        if self.result is not None:
            try:
                size = len(json.dumps(self.result, allow_nan=False).encode())
            except ValueError as exc:
                raise ValueError("result must be valid JSON (no NaN)") from exc
            if size > _RESULT_MAX_BYTES:
                raise ValueError(f"result must be at most {_RESULT_MAX_BYTES} bytes")
        if self.analyzer in AI_ANALYZERS and self.status == "ok" and self.result is not None:
            flag, score = self.result.get("ai_detected"), self.result.get("score")
            if not isinstance(flag, bool):
                raise ValueError(f"{self.analyzer} result.ai_detected must be a boolean")
            if (
                isinstance(score, bool)
                or not isinstance(score, int | float)
                or not math.isfinite(score)
                or not 0 <= score <= 1
            ):
                raise ValueError(f"{self.analyzer} result.score must be a number in [0, 1]")
        return self


class AnalysisResultsRequest(BaseModel):
    """POST /v1/analysis/results: results under one lease."""

    model_config = ConfigDict(extra="forbid")

    lease_id: UUID
    results: list[AnalysisResultItem] = Field(min_length=1, max_length=100)

    @field_validator("results")
    @classmethod
    def _unique_pairs(cls, value: list[AnalysisResultItem]) -> list[AnalysisResultItem]:
        pairs = {(r.track_id, r.analyzer) for r in value}
        if len(pairs) != len(value):
            raise ValueError("each (track_id, analyzer) may appear once")
        return value


class AnalysisFeatureItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{6,32}$")
    version: Literal["light-1"]
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # 33 556 bytes of float16 are 44 744 base64 chars.
    vector_b64: str = Field(max_length=44_800)


class AnalysisFeaturesRequest(BaseModel):
    """POST /v1/analysis/features: light-1 profiles, one per YouTube video."""

    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisFeatureItem] = Field(min_length=1, max_length=50)

    @field_validator("items")
    @classmethod
    def _unique_videos(cls, value: list[AnalysisFeatureItem]) -> list[AnalysisFeatureItem]:
        if len({i.video_id for i in value}) != len(value):
            raise ValueError("each video_id may appear once")
        return value


# wave-1: 3 bands (20-250 Hz, 250 Hz-4 kHz, 4-16 kHz), each 600 time bins of u8 dB
# against the band's loudest bin (0 = 36 dB below it or quieter), band after band.
WAVEFORM_BANDS, WAVEFORM_BINS = 3, 600
WAVEFORM_BYTES = WAVEFORM_BANDS * WAVEFORM_BINS


class AnalysisWaveformItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_id: str = Field(pattern=r"^[A-Za-z0-9_-]{6,32}$")
    version: Literal["wave-1"]
    audio_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    duration_ms: StrictInt = Field(ge=1, le=86_400_000)
    # 1 800 bytes are 2 400 base64 chars.
    data_b64: str = Field(max_length=2_400)


class AnalysisWaveformsRequest(BaseModel):
    """POST /v1/analysis/waveforms: wave-1 waveforms, one per YouTube video."""

    model_config = ConfigDict(extra="forbid")

    items: list[AnalysisWaveformItem] = Field(min_length=1, max_length=100)

    @field_validator("items")
    @classmethod
    def _unique_videos(cls, value: list[AnalysisWaveformItem]) -> list[AnalysisWaveformItem]:
        if len({i.video_id for i in value}) != len(value):
            raise ValueError("each video_id may appear once")
        return value


class AnalysisRequeueRequest(BaseModel):
    """POST /admin/analysis/requeue: hand finished tracks out again."""

    model_config = ConfigDict(extra="forbid")

    analyzer: AnalyzerName
    scope: Literal["all", "categories", "recent"]
    days: StrictInt | None = Field(default=None, ge=1, le=365)
    include_failed: StrictBool = False

    @model_validator(mode="after")
    def _days_for_recent(self) -> AnalysisRequeueRequest:
        if (self.scope == "recent") != (self.days is not None):
            raise ValueError("days is required for scope recent and only for it")
        return self


class AdminIngestRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style_id: StrictInt = Field(gt=0)
    week_year: StrictInt = Field(ge=2000, le=2100)
    week_number: StrictInt = Field(ge=1, le=53)
    period_start: date | None = None
    period_end: date | None = None

    @model_validator(mode="after")
    def _validate_range_constraints(self) -> AdminIngestRequestIn:
        from .saturday_week import weeks_in_year

        if (self.period_start is None) != (self.period_end is None):
            raise ValueError("period_start and period_end must both be present or both absent")
        if (
            self.period_start is not None
            and self.period_end is not None
            and self.period_end < self.period_start
        ):
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


_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class AutoIngestSettingsIn(BaseModel):
    """PUT /admin/auto-ingest (docs/data/auto-ingest.md)."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    mode: Literal["fixed", "random"]
    fixed_times: list[str] = Field(min_length=1, max_length=12)
    runs_per_day: StrictInt = Field(ge=1, le=12)
    timezone: str = Field(min_length=1)
    periods_per_run: StrictInt = Field(ge=1, le=10)
    backfill_floor: date

    @field_validator("fixed_times")
    @classmethod
    def _times(cls, value: list[str]) -> list[str]:
        if any(not _HHMM.match(t) for t in value):
            raise ValueError("times must be HH:MM (00:00-23:59)")
        if len(set(value)) != len(value):
            raise ValueError("times must be unique")
        return sorted(value)

    @field_validator("timezone")
    @classmethod
    def _zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        return value

    @field_validator("backfill_floor")
    @classmethod
    def _floor(cls, value: date) -> date:
        if not date(2000, 1, 1) <= value <= datetime.now(UTC).date():
            raise ValueError("backfill_floor must be between 2000-01-01 and today")
        return value

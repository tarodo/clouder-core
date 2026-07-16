"""LabelInfo + AI signal data models for label enrichment."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ActivityLevel(str, Enum):
    UNKNOWN = "unknown"
    DORMANT = "dormant"
    LOW = "low"
    STEADY = "steady"
    HIGH = "high"
    FIRE_HOSE = "fire_hose"


class AIContentStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class AISignalKind(str, Enum):
    VOLUME = "volume"
    ARTIST_GENERIC_NAMES = "artist_generic_names"
    COVER_ART = "cover_art"
    NAMED_IN_PRESS = "named_in_press"
    CREDITED_TOOL = "credited_tool"
    OTHER = "other"


class AISignal(BaseModel):
    kind: AISignalKind
    description: str
    source_url: str | None = None


class LabelInfo(BaseModel):
    label_name: str
    aliases: list[str] = Field(default_factory=list)
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    country: str | None = None
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    tagline: str | None = None

    catalog_size_estimate: int | None = None
    roster_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None
    activity: ActivityLevel = ActivityLevel.UNKNOWN

    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None

    notable_artists: list[str] = Field(default_factory=list)
    primary_styles: list[str] = Field(default_factory=list)
    distribution: str | None = None

    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = Field(default_factory=list)
    ai_reasoning: str = ""

    summary: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class LabelInfoRequest(BaseModel):
    """Vendor-facing schema: LabelInfo minus AI-detection fields.

    Structured output forces the model to fill every schema field, so the
    ai_* fields must be absent here, not just unmentioned in the prompt.
    Kept as an explicit copy (not generated) so the diff is reviewable;
    test_enrichment_request_schemas pins it to LabelInfo field-for-field.
    """

    label_name: str
    aliases: list[str] = Field(default_factory=list)
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    country: str | None = None
    founded_year: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    tagline: str | None = None

    catalog_size_estimate: int | None = None
    roster_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None
    activity: ActivityLevel = ActivityLevel.UNKNOWN

    website: str | None = None
    bandcamp_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    beatport_url: str | None = None
    soundcloud_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None

    notable_artists: list[str] = Field(default_factory=list)
    primary_styles: list[str] = Field(default_factory=list)
    distribution: str | None = None

    summary: str
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None

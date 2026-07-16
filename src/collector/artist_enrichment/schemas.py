"""Data models for artist enrichment."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ArtistType(str, Enum):
    SOLO = "solo"
    DUO = "duo"
    GROUP = "group"
    ALIAS_PROJECT = "alias_project"
    UNKNOWN = "unknown"


class AIContentStatus(str, Enum):
    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class AISignalKind(str, Enum):
    NO_LIVE_PRESENCE = "no_live_presence"
    AI_GENERATED_IMAGERY = "ai_generated_imagery"
    SUSPICIOUS_RELEASE_VELOCITY = "suspicious_release_velocity"
    NO_SOCIAL_FOOTPRINT = "no_social_footprint"
    TEMPLATED_BIO = "templated_bio"
    DISTRIBUTOR_ONLY_NO_LABEL = "distributor_only_no_label"
    VOICE_CLONING_INDICATORS = "voice_cloning_indicators"
    AI_FARM_NAME_PATTERN = "ai_farm_name_pattern"
    REVERSE_IMAGE_NO_RESULTS = "reverse_image_no_results"
    NAMED_IN_PRESS = "named_in_press"
    CREDITED_TOOL = "credited_tool"
    OTHER = "other"


class AISignal(BaseModel):
    kind: AISignalKind
    description: str
    source_url: str | None = None


class ArtistInfo(BaseModel):
    # Identity
    artist_name: str
    aliases: list[str] = Field(default_factory=list)
    real_name: str | None = None
    artist_type: ArtistType = ArtistType.UNKNOWN
    members: list[str] = Field(default_factory=list)

    # Origin
    country: str | None = None
    city: str | None = None
    active_since: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"

    # Music
    primary_styles: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    notable_collaborators: list[str] = Field(default_factory=list)
    notable_releases: list[str] = Field(default_factory=list)

    # Links
    spotify_url: str | None = None
    soundcloud_url: str | None = None
    bandcamp_url: str | None = None
    beatport_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    website: str | None = None

    # Narrative
    tagline: str | None = None
    bio: str | None = None
    summary: str

    # AI detection
    ai_content: AIContentStatus = AIContentStatus.UNKNOWN
    ai_signals: list[AISignal] = Field(default_factory=list)
    ai_reasoning: str = ""

    # Meta
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class ArtistInfoRequest(BaseModel):
    """Vendor-facing schema: ArtistInfo minus AI-detection fields.

    Structured output forces the model to fill every schema field, so the
    ai_* fields must be absent here, not just unmentioned in the prompt.
    Kept as an explicit copy (not generated) so the diff is reviewable;
    test_enrichment_request_schemas pins it to ArtistInfo field-for-field.
    """

    # Identity
    artist_name: str
    aliases: list[str] = Field(default_factory=list)
    real_name: str | None = None
    artist_type: ArtistType = ArtistType.UNKNOWN
    members: list[str] = Field(default_factory=list)

    # Origin
    country: str | None = None
    city: str | None = None
    active_since: int | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"

    # Music
    primary_styles: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    notable_collaborators: list[str] = Field(default_factory=list)
    notable_releases: list[str] = Field(default_factory=list)

    # Links
    spotify_url: str | None = None
    soundcloud_url: str | None = None
    bandcamp_url: str | None = None
    beatport_url: str | None = None
    residentadvisor_url: str | None = None
    discogs_url: str | None = None
    instagram_url: str | None = None
    twitter_url: str | None = None
    website: str | None = None

    # Narrative
    tagline: str | None = None
    bio: str | None = None
    summary: str

    # Meta
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None

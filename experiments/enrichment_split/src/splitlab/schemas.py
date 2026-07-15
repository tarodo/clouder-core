"""Request schemas for the two passes. Narrative = fuzzy/descriptive only;
Facts = sourced numerics/strings only. URLs are never LLM-produced."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

URL_FIELDS = (
    "website", "bandcamp_url", "residentadvisor_url", "discogs_url",
    "beatport_url", "soundcloud_url", "instagram_url", "twitter_url",
)


class LabelNarrative(BaseModel):
    label_name: str
    aliases: list[str] = Field(default_factory=list)
    country: str | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    tagline: str | None = None
    summary: str
    primary_styles: list[str] = Field(default_factory=list)
    notable_artists: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class ArtistNarrative(BaseModel):
    artist_name: str
    aliases: list[str] = Field(default_factory=list)
    real_name: str | None = None
    artist_type: Literal["solo", "duo", "group", "alias_project", "unknown"] = "unknown"
    members: list[str] = Field(default_factory=list)
    country: str | None = None
    city: str | None = None
    status: Literal["active", "inactive", "unknown"] = "unknown"
    primary_styles: list[str] = Field(default_factory=list)
    notable_collaborators: list[str] = Field(default_factory=list)
    notable_releases: list[str] = Field(default_factory=list)
    tagline: str | None = None
    summary: str
    bio: str | None = None
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class LabelFacts(BaseModel):
    founded_year: int | None = None
    catalog_size_estimate: int | None = None
    releases_last_12_months: int | None = None
    last_release_date: str | None = None
    distribution: str | None = None
    parent_label: str | None = None
    sublabels: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None


class ArtistFacts(BaseModel):
    active_since: int | None = None
    labels: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    notes: str | None = None

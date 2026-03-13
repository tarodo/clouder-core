"""Pydantic models for AI search results."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class LabelSize(str, Enum):
    """How big the label is in the industry."""

    UNKNOWN = "unknown"
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    MAJOR = "major"


class LabelAge(str, Enum):
    """How long the label has been active."""

    UNKNOWN = "unknown"
    NEW = "new"
    YOUNG = "young"
    ESTABLISHED = "established"
    VETERAN = "veteran"


class AIContentStatus(str, Enum):
    """Whether the label has AI-generated releases."""

    UNKNOWN = "unknown"
    NONE_DETECTED = "none_detected"
    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"


class LabelSearchResult(BaseModel):
    """Structured result of a label search."""

    label_name: str = Field(description="Official name of the label")
    style: str = Field(description="Music style/genre queried")

    size: LabelSize = Field(description="How big the label is")
    size_details: str = Field(
        description="Details about label size: approximate number of releases, "
        "artists roster size, etc."
    )

    age: LabelAge = Field(description="How mature/old the label is")
    founded_year: int | None = Field(
        default=None, description="Year the label was founded, if known"
    )
    age_details: str = Field(description="Details about label history and longevity")

    ai_content: AIContentStatus = Field(
        description="Whether the label has AI-generated releases"
    )
    ai_content_details: str = Field(description="Details about AI content findings")

    country: str | None = Field(default=None, description="Country of origin")
    website: str | None = Field(default=None, description="Official website URL")
    notable_artists: list[str] = Field(
        default_factory=list, description="Notable artists on the label"
    )
    summary: str = Field(description="Brief overall summary about the label")
    confidence: float = Field(
        ge=0,
        le=1,
        description="Confidence score 0-1 in the accuracy of the gathered info",
    )
    sources: list[str] = Field(
        default_factory=list, description="URLs or references used"
    )

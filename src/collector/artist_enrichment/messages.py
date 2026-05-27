"""SQS message schema for artist enrichment (HTTP request models added in 1B)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ArtistEnrichmentMessage(BaseModel):
    """Body of one SQS message — one per artist, one Lambda invocation.

    The disambiguation context (style, sample_tracks, known_labels) is NOT
    carried here — the worker derives it from the artist's tracks.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(min_length=1)
    artist_id: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)


class EnrichArtistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artist_id: str | None = Field(default=None, min_length=1)
    artist_name: str | None = Field(default=None, min_length=1, max_length=256)
    style: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _id_or_name_required(self) -> "EnrichArtistInput":
        if not self.artist_id and not self.artist_name:
            raise ValueError("either artist_id or artist_name is required")
        if not self.artist_id and not self.style:
            raise ValueError("style is required when using artist_name")
        return self


class EnrichArtistsRequestIn(BaseModel):
    """POST /admin/artists/enrich body."""

    model_config = ConfigDict(extra="forbid")

    artists: list[EnrichArtistInput] = Field(min_length=1, max_length=100)
    vendors: list[Literal["gemini", "openai", "tavily_deepseek"]] = Field(min_length=1)
    models: dict[str, str]
    prompt_slug: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    merge_vendor: Literal["deepseek"]
    merge_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _every_vendor_has_a_model(self) -> "EnrichArtistsRequestIn":
        for vendor in self.vendors:
            if vendor not in self.models or not self.models[vendor].strip():
                raise ValueError(f"model missing for vendor {vendor!r}")
        return self

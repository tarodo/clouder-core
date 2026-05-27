"""SQS message schema for artist enrichment (HTTP request models added in 1B)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ArtistEnrichmentMessage(BaseModel):
    """Body of one SQS message — one per artist, one Lambda invocation.

    The disambiguation context (style, sample_tracks, known_labels) is NOT
    carried here — the worker derives it from the artist's tracks.
    """

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(min_length=1)
    artist_id: str = Field(min_length=1)
    artist_name: str = Field(min_length=1)

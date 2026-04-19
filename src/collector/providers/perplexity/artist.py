"""PerplexityArtistEnricher — stub. Wire to a real prompt when artist research lands."""

from __future__ import annotations

from typing import Any

from ..base import EnrichResult


class PerplexityArtistEnricher:
    vendor_name = "perplexity_artist"
    entity_types = ("artist",)
    prompt_slug = "artist_info"
    prompt_version = "v1"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        raise NotImplementedError(
            "artist enrichment not yet wired to a prompt"
        )

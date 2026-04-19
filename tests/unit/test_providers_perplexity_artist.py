"""Unit tests for PerplexityArtistEnricher stub."""
from __future__ import annotations

import pytest

from collector.providers.base import EnrichProvider
from collector.providers.perplexity.artist import PerplexityArtistEnricher


def test_artist_enricher_implements_protocol() -> None:
    enricher = PerplexityArtistEnricher(api_key="k")
    assert isinstance(enricher, EnrichProvider)
    assert enricher.vendor_name == "perplexity_artist"
    assert enricher.entity_types == ("artist",)


def test_artist_enricher_not_implemented() -> None:
    enricher = PerplexityArtistEnricher(api_key="k")
    with pytest.raises(NotImplementedError):
        enricher.enrich(
            entity_type="artist",
            entity_id="a",
            context={},
            correlation_id="c",
        )

"""Unit tests for SpotifyEnricher (release_type extraction)."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import EnrichProvider, EnrichResult
from collector.providers.spotify.enrich import SpotifyEnricher
from collector.providers.spotify.lookup import SpotifyLookup
from collector.spotify_client import SpotifySearchResult


class _FakeLookup:
    vendor_name = "spotify"

    def __init__(self, result: SpotifySearchResult | None) -> None:
        self._result = result

    def lookup_batch_by_isrc(
        self, tracks: list[dict[str, str]], correlation_id: str
    ) -> list[SpotifySearchResult]:
        return [self._result] if self._result else []


def test_enricher_implements_protocol() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    assert isinstance(enricher, EnrichProvider)
    assert enricher.entity_types == ("track",)
    assert enricher.prompt_slug == "spotify_release_type"


def test_enricher_returns_album_type_when_found() -> None:
    fake = _FakeLookup(
        SpotifySearchResult(
            isrc="USRC00000001",
            clouder_track_id="t1",
            spotify_track={"id": "sp1", "album": {"album_type": "single"}},
            spotify_id="sp1",
        )
    )
    enricher = SpotifyEnricher(lookup=fake)
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={"isrc": "USRC00000001"},
        correlation_id="corr",
    )
    assert isinstance(result, EnrichResult)
    assert result.payload == {"spotify_id": "sp1", "album_type": "single"}


def test_enricher_returns_no_isrc_when_missing() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={},
        correlation_id="corr",
    )
    assert result.payload == {"status": "no_isrc"}


def test_enricher_returns_not_found() -> None:
    fake = _FakeLookup(
        SpotifySearchResult(
            isrc="USRC00000001",
            clouder_track_id="t1",
            spotify_track=None,
            spotify_id=None,
        )
    )
    enricher = SpotifyEnricher(lookup=fake)
    result = enricher.enrich(
        entity_type="track",
        entity_id="t1",
        context={"isrc": "USRC00000001"},
        correlation_id="corr",
    )
    assert result.payload == {"status": "not_found"}


def test_enricher_rejects_wrong_entity_type() -> None:
    enricher = SpotifyEnricher(lookup=_FakeLookup(None))
    with pytest.raises(ValueError, match="entity_type=track"):
        enricher.enrich(
            entity_type="label",
            entity_id="x",
            context={},
            correlation_id="corr",
        )

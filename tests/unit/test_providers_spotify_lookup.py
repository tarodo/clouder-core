"""Unit tests for SpotifyLookup adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import LookupProvider
from collector.providers.spotify.lookup import SpotifyLookup


def test_spotify_lookup_implements_protocol() -> None:
    lookup = SpotifyLookup(client_id="cid", client_secret="csec")
    assert isinstance(lookup, LookupProvider)
    assert lookup.vendor_name == "spotify"


def test_spotify_lookup_delegates_to_client(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector.spotify_client import SpotifyClient, SpotifySearchResult

    captured: dict[str, Any] = {}

    def fake_search(
        self: Any,
        tracks: list[dict[str, Any]],
        correlation_id: str,
        **kwargs: Any,
    ) -> list[SpotifySearchResult]:
        captured["tracks"] = tracks
        captured["correlation_id"] = correlation_id
        captured["kwargs"] = kwargs
        return [
            SpotifySearchResult(
                isrc="USRC00000001",
                clouder_track_id="t1",
                spotify_track={"id": "sp1"},
                spotify_id="sp1",
            )
        ]

    monkeypatch.setattr(SpotifyClient, "search_tracks_by_isrc", fake_search)

    lookup = SpotifyLookup(client_id="cid", client_secret="csec")
    results = lookup.lookup_batch_by_isrc(
        tracks=[{"clouder_track_id": "t1", "isrc": "USRC00000001"}],
        correlation_id="corr-9",
    )

    assert len(results) == 1
    assert results[0].spotify_id == "sp1"
    assert captured["tracks"] == [
        {"clouder_track_id": "t1", "isrc": "USRC00000001"}
    ]
    assert captured["correlation_id"] == "corr-9"


def test_spotify_lookup_forwards_metadata_fallback_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    from collector.spotify_client import SpotifyClient

    captured: dict[str, Any] = {}

    def fake_search(self: Any, **kwargs: Any) -> list:
        captured.update(kwargs)
        return []

    monkeypatch.setattr(SpotifyClient, "search_tracks_by_isrc", fake_search)

    lookup = SpotifyLookup(client_id="cid", client_secret="csec")
    lookup.lookup_batch_by_isrc(
        tracks=[{"clouder_track_id": "t1", "isrc": "USRC00000001"}],
        correlation_id="cid",
        metadata_fallback_enabled=True,
        title_min=0.90,
        artist_min=0.85,
        duration_tolerance_ms=3000,
    )

    assert captured["metadata_fallback_enabled"] is True
    assert captured["title_min"] == 0.90
    assert captured["artist_min"] == 0.85
    assert captured["duration_tolerance_ms"] == 3000

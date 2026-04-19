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
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[SpotifySearchResult]:
        captured["tracks"] = tracks
        captured["correlation_id"] = correlation_id
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

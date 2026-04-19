"""Per-track LookupProvider API tests (Plan 4 Task 0a)."""

from __future__ import annotations

import pytest

from collector.errors import VendorDisabledError
from collector.providers.base import LookupProvider, VendorTrackRef
from collector.providers.apple.lookup import AppleLookup
from collector.providers.deezer.lookup import DeezerLookup
from collector.providers.spotify.lookup import SpotifyLookup
from collector.providers.tidal.lookup import TidalLookup
from collector.providers.ytmusic.lookup import YTMusicLookup
from collector.spotify_client import SpotifySearchResult


class _FakeSpotifyClient:
    def __init__(self, by_isrc: dict[str, dict | None]) -> None:
        self._by_isrc = by_isrc
        self.calls: list[tuple[str, str]] = []

    def search_tracks_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[SpotifySearchResult]:
        results: list[SpotifySearchResult] = []
        for t in tracks:
            isrc = t["isrc"]
            self.calls.append((isrc, correlation_id))
            track = self._by_isrc.get(isrc)
            results.append(
                SpotifySearchResult(
                    isrc=isrc,
                    clouder_track_id=t["clouder_track_id"],
                    spotify_track=track,
                    spotify_id=track["id"] if track else None,
                )
            )
        return results


def test_spotify_lookup_by_isrc_hit_returns_vendor_track_ref() -> None:
    track = {
        "id": "sp123",
        "name": "Bar",
        "duration_ms": 200_000,
        "artists": [{"name": "Foo"}],
        "album": {"name": "Baz"},
        "external_ids": {"isrc": "US1234567890"},
    }
    fake = _FakeSpotifyClient({"US1234567890": track})
    lookup = SpotifyLookup(client_id="x", client_secret="y", client=fake)  # type: ignore[arg-type]

    ref = lookup.lookup_by_isrc("US1234567890")

    assert isinstance(ref, VendorTrackRef)
    assert ref.vendor == "spotify"
    assert ref.vendor_track_id == "sp123"
    assert ref.isrc == "US1234567890"
    assert ref.artist_names == ("Foo",)
    assert ref.title == "Bar"
    assert ref.duration_ms == 200_000
    assert ref.album_name == "Baz"
    assert ref.raw_payload == track


def test_spotify_lookup_by_isrc_miss_returns_none() -> None:
    fake = _FakeSpotifyClient({"US0000000000": None})
    lookup = SpotifyLookup(client_id="x", client_secret="y", client=fake)  # type: ignore[arg-type]

    assert lookup.lookup_by_isrc("US0000000000") is None


def test_spotify_lookup_by_metadata_returns_empty_for_now() -> None:
    """Spotify fuzzy metadata search is a follow-up — returns [] today."""
    fake = _FakeSpotifyClient({})
    lookup = SpotifyLookup(client_id="x", client_secret="y", client=fake)  # type: ignore[arg-type]

    assert lookup.lookup_by_metadata("Foo", "Bar", 200_000, "Baz") == []


@pytest.mark.parametrize(
    "cls",
    [YTMusicLookup, DeezerLookup, AppleLookup, TidalLookup],
)
def test_stub_lookup_by_isrc_raises_vendor_disabled(cls) -> None:
    lookup = cls()
    with pytest.raises(VendorDisabledError) as exc:
        lookup.lookup_by_isrc("US1234567890")
    assert exc.value.reason == "not_implemented"


@pytest.mark.parametrize(
    "cls",
    [YTMusicLookup, DeezerLookup, AppleLookup, TidalLookup],
)
def test_stub_lookup_by_metadata_raises_vendor_disabled(cls) -> None:
    lookup = cls()
    with pytest.raises(VendorDisabledError) as exc:
        lookup.lookup_by_metadata("Foo", "Bar", 200_000, "Baz")
    assert exc.value.reason == "not_implemented"


def test_spotify_lookup_is_lookup_provider() -> None:
    fake = _FakeSpotifyClient({})
    lookup = SpotifyLookup(client_id="x", client_secret="y", client=fake)  # type: ignore[arg-type]
    assert isinstance(lookup, LookupProvider)

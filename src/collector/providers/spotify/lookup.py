"""SpotifyLookup — LookupProvider adapter over SpotifyClient."""

from __future__ import annotations

from typing import Any

from ..base import VendorTrackRef
from ...spotify_client import SpotifyClient, SpotifySearchResult


class SpotifyLookup:
    """Thin adapter — delegates batch ISRC search to SpotifyClient.

    The underlying client caches its OAuth token across calls; we keep
    the client instance on self so spotify_handler reuses one auth handshake
    per worker invocation, exactly as before this refactor.
    """

    vendor_name = "spotify"

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        client: SpotifyClient | None = None,
    ) -> None:
        self._client = client or SpotifyClient(
            client_id=client_id,
            client_secret=client_secret,
        )

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[SpotifySearchResult]:
        return self._client.search_tracks_by_isrc(
            tracks=tracks,
            correlation_id=correlation_id,
        )

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        results = self._client.search_tracks_by_isrc(
            tracks=[{"clouder_track_id": "_", "isrc": isrc}],
            correlation_id="",
        )
        if not results:
            return None
        result = results[0]
        if result.spotify_track is None or not result.spotify_id:
            return None
        return _track_to_ref(result.spotify_track)

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]:
        # Spotify fuzzy search via q= is a follow-up. Beatport payloads
        # always carry ISRC so lookup_by_isrc covers real usage today.
        return []


def _track_to_ref(track: dict[str, Any]) -> VendorTrackRef:
    artists = track.get("artists")
    if isinstance(artists, list):
        artist_names = tuple(
            str(a.get("name", "")) for a in artists if isinstance(a, dict) and a.get("name")
        )
    else:
        artist_names = ()

    album = track.get("album")
    album_name = album.get("name") if isinstance(album, dict) else None

    external_ids = track.get("external_ids")
    isrc = None
    if isinstance(external_ids, dict):
        raw_isrc = external_ids.get("isrc")
        if isinstance(raw_isrc, str) and raw_isrc:
            isrc = raw_isrc

    duration = track.get("duration_ms")
    duration_ms = int(duration) if isinstance(duration, (int, float)) else None

    return VendorTrackRef(
        vendor="spotify",
        vendor_track_id=str(track.get("id") or ""),
        isrc=isrc,
        artist_names=artist_names,
        title=str(track.get("name") or ""),
        duration_ms=duration_ms,
        album_name=str(album_name) if album_name else None,
        raw_payload=track,
    )

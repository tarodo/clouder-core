"""SpotifyLookup — LookupProvider adapter over SpotifyClient."""

from __future__ import annotations

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

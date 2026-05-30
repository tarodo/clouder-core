"""YTMusicLookup — LookupProvider over ytmusicapi (unauthenticated search).

YT Music exposes no public ISRC search, so lookup_by_isrc always returns
None and matching relies entirely on lookup_by_metadata + the shared fuzzy
scorer in vendor_match_handler. The ytmusicapi client is built lazily via an
injectable factory: the module imports cleanly without the package, and tests
inject a fake.
"""

from __future__ import annotations

from typing import Any

from ...errors import VendorDisabledError
from ..base import VendorTrackRef
from .normalize import build_query, result_to_ref

_SEARCH_LIMIT = 10


def _default_client_factory() -> Any:
    from ytmusicapi import YTMusic  # lazy: only when a search actually runs

    return YTMusic()


class YTMusicLookup:
    vendor_name = "ytmusic"

    def __init__(
        self,
        client: Any | None = None,
        client_factory: Any = _default_client_factory,
        search_limit: int = _SEARCH_LIMIT,
    ) -> None:
        self._client = client
        self._client_factory = client_factory
        self._search_limit = search_limit

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    def lookup_batch_by_isrc(
        self, tracks: list[dict[str, str]], correlation_id: str
    ) -> list[Any]:
        # Consumed only by the Spotify worker's batch path.
        raise VendorDisabledError(self.vendor_name, reason="not_implemented")

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        # YT Music has no ISRC search; the worker's ISRC fast-path is skipped.
        return None

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]:
        query = build_query(artist, title)
        client = self._get_client()
        candidates = self._search(client, query, "songs")
        if not candidates:
            candidates = self._search(client, query, "videos")
        return candidates

    def _search(self, client: Any, query: str, filter_name: str) -> list[VendorTrackRef]:
        raw_results = client.search(query, filter=filter_name, limit=self._search_limit)
        refs: list[VendorTrackRef] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict):
                continue
            ref = result_to_ref(raw)
            if ref is not None:
                refs.append(ref)
        return refs

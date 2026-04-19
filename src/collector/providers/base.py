"""Provider Protocols and shared dataclasses for vendor integrations.

Variant A note: Protocol method signatures match the existing call sites
(batch + correlation_id), not the long-term per-track ideal. New methods
will be added when first consumed (e.g. per-track lookup for playlist
export in Plan 4).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class VendorTrackRef:
    vendor: str
    vendor_track_id: str
    isrc: str | None
    artist_names: tuple[str, ...]
    title: str
    duration_ms: int | None
    album_name: str | None
    raw_payload: dict[str, Any]


@dataclass(frozen=True)
class VendorPlaylistRef:
    vendor: str
    vendor_playlist_id: str
    url: str | None


@dataclass(frozen=True)
class EnrichResult:
    entity_type: str
    entity_id: str
    prompt_slug: str
    prompt_version: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class RawIngestPayload:
    source: str
    items: list[dict[str, Any]]
    meta: dict[str, Any]


@runtime_checkable
class IngestProvider(Protocol):
    source_name: str

    def fetch_weekly_releases(
        self,
        bp_token: str,
        style_id: int,
        week_start: str,
        week_end: str,
        correlation_id: str,
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (items, pages_fetched). Signature matches BeatportClient."""
        ...


@runtime_checkable
class LookupProvider(Protocol):
    vendor_name: str

    def lookup_batch_by_isrc(
        self,
        tracks: list[dict[str, str]],
        correlation_id: str,
    ) -> list[Any]:
        """Batch ISRC search. Returns provider-specific result objects."""
        ...

    def lookup_by_isrc(self, isrc: str) -> "VendorTrackRef | None":
        """Single-ISRC lookup. Returns None on miss."""
        ...

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list["VendorTrackRef"]:
        """Fuzzy metadata search. Returns up to ~10 candidates."""
        ...


@runtime_checkable
class EnrichProvider(Protocol):
    vendor_name: str
    entity_types: tuple[str, ...]
    prompt_slug: str
    prompt_version: str

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult: ...


@runtime_checkable
class ExportProvider(Protocol):
    vendor_name: str

    def create_playlist(
        self,
        user_token: str,
        name: str,
        track_refs: list[VendorTrackRef],
    ) -> VendorPlaylistRef: ...


@dataclass(frozen=True)
class ProviderBundle:
    ingest: IngestProvider | None = None
    lookup: LookupProvider | None = None
    enrich: EnrichProvider | None = None
    export: ExportProvider | None = None

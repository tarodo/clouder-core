"""Commands and value objects the repository takes and returns."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from ..models import RunStatus


@dataclass(frozen=True)
class IdentityMapEntry:
    clouder_entity_type: str
    clouder_id: str


@dataclass(frozen=True)
class CreateIngestRunCmd:
    run_id: str
    source: str
    style_id: int
    raw_s3_key: str
    status: RunStatus
    item_count: int
    meta: Mapping[str, Any]
    started_at: datetime
    iso_year: int | None = None
    iso_week: int | None = None
    week_year: int | None = None
    week_number: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    is_custom_range: bool = False


@dataclass(frozen=True)
class UpsertSourceEntityCmd:
    source: str
    entity_type: str
    external_id: str
    name: str | None
    normalized_name: str | None
    payload: Mapping[str, Any]
    payload_hash: str
    last_run_id: str | None
    observed_at: datetime


@dataclass(frozen=True)
class UpsertSourceRelationCmd:
    source: str
    from_entity_type: str
    from_external_id: str
    relation_type: str
    to_entity_type: str
    to_external_id: str
    last_run_id: str


@dataclass(frozen=True)
class UpsertIdentityCmd:
    source: str
    entity_type: str
    external_id: str
    clouder_entity_type: str
    clouder_id: str
    match_type: str
    confidence: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class CreateTrackCmd:
    track_id: str
    title: str
    normalized_title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    key_name: str | None
    key_camelot: str | None
    publish_date: date | None
    album_id: str | None
    style_id: str | None
    at: datetime


@dataclass(frozen=True)
class TrackState:
    """A track's mergeable columns, and whether this run's observation is older
    than the stored one (from another run)."""

    stale: bool
    values: Mapping[str, Any]


@dataclass(frozen=True)
class ConservativeUpdateTrackCmd:
    track_id: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    key_name: str | None
    key_camelot: str | None
    publish_date: date | None
    album_id: str | None
    style_id: str | None
    at: datetime


@dataclass(frozen=True)
class CreateNamedEntityCmd:
    entity_id: str
    name: str
    normalized_name: str
    at: datetime


@dataclass(frozen=True)
class CreateAlbumCmd:
    album_id: str
    title: str
    normalized_title: str
    release_date: date | None
    label_id: str | None
    at: datetime


@dataclass(frozen=True)
class UpdateSpotifyResultCmd:
    track_id: str
    spotify_id: str | None
    searched_at: datetime
    release_type: str | None = None
    spotify_release_date: date | None = None


@dataclass(frozen=True)
class UpsertTrackArtistCmd:
    track_id: str
    artist_id: str
    role: str = "main"


@dataclass(frozen=True)
class VendorTrackMatch:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str
    confidence: Decimal
    matched_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class UpsertVendorMatchCmd:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str
    confidence: Decimal
    matched_at: datetime
    payload: Mapping[str, Any]

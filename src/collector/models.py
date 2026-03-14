"""Domain models and input validation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping, Tuple

from pydantic import ValidationError as PydanticValidationError

from .errors import ValidationError
from .schemas import CollectRequestIn, validation_error_message


@dataclass(frozen=True)
class CollectRequest:
    bp_token: str
    style_id: int
    iso_year: int
    iso_week: int


class RunStatus(str, Enum):
    RAW_SAVED = "RAW_SAVED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProcessingStatus(str, Enum):
    QUEUED = "QUEUED"
    FAILED_TO_QUEUE = "FAILED_TO_QUEUE"


class ProcessingOutcome(str, Enum):
    ENQUEUED = "ENQUEUED"
    DISABLED = "DISABLED"
    ENQUEUE_FAILED = "ENQUEUE_FAILED"


class ProcessingReason(str, Enum):
    CONFIG_DISABLED = "config_disabled"
    QUEUE_MISSING = "queue_missing"
    ENQUEUE_EXCEPTION = "enqueue_exception"


class EntityType(str, Enum):
    TRACK = "track"
    ARTIST = "artist"
    ALBUM = "album"
    LABEL = "label"
    STYLE = "style"


class RelationType(str, Enum):
    TRACK_ARTIST = "track_artist"
    TRACK_ALBUM = "track_album"
    ALBUM_LABEL = "album_label"
    TRACK_STYLE = "track_style"


@dataclass(frozen=True)
class NormalizedArtist:
    bp_artist_id: int
    name: str
    normalized_name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedLabel:
    bp_label_id: int
    name: str
    normalized_name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedStyle:
    bp_genre_id: int
    name: str
    normalized_name: str
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedAlbum:
    bp_release_id: int
    title: str
    normalized_title: str
    release_date: str | None
    bp_label_id: int | None
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedTrack:
    bp_track_id: int
    title: str
    normalized_title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: str | None
    bp_release_id: int | None
    bp_genre_id: int | None
    bp_artist_ids: tuple[int, ...]
    payload: Mapping[str, Any]


@dataclass(frozen=True)
class CanonicalizationResult:
    run_id: str
    tracks_total: int
    tracks_processed: int
    artists_total: int
    labels_total: int
    albums_total: int
    styles_total: int


def validate_collect_request(payload: Mapping[str, Any]) -> CollectRequest:
    try:
        parsed = CollectRequestIn.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc)) from exc

    return CollectRequest(
        bp_token=parsed.bp_token,
        style_id=parsed.style_id,
        iso_year=parsed.iso_year,
        iso_week=parsed.iso_week,
    )


def compute_iso_week_date_range(iso_year: int, iso_week: int) -> Tuple[str, str]:
    """Return ISO week boundaries as date strings (YYYY-MM-DD)."""

    week_start = date.fromisocalendar(iso_year, iso_week, 1)
    week_end = date.fromisocalendar(iso_year, iso_week, 7)
    return week_start.isoformat(), week_end.isoformat()


def normalize_text(value: str) -> str:
    return " ".join(value.strip().lower().split())

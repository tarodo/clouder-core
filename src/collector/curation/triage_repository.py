"""Aurora Data API repository for spec-D triage."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_type, datetime
from typing import Any, Iterable, Mapping, Sequence

from collector.curation import (
    InactiveBucketError,
    InactiveStagingFinalizeError,
    InvalidStateError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
    ValidationError,
    utc_now,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_STAGING,
    BUCKET_TYPE_UNCLASSIFIED,
    TECHNICAL_BUCKET_DISPLAY_ORDER,
    TECHNICAL_BUCKET_TYPES,
    TRACK_IDS_MAX,
)
from collector.data_api import DataAPIClient


@dataclass(frozen=True)
class TriageBucketRow:
    id: str
    bucket_type: str
    category_id: str | None
    category_name: str | None
    inactive: bool
    track_count: int


@dataclass(frozen=True)
class TriageBlockRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str  # ISO YYYY-MM-DD as returned by Data API
    date_to: str
    status: str
    created_at: str  # ISO datetime
    updated_at: str
    finalized_at: str | None
    buckets: Sequence[TriageBucketRow] = field(default_factory=tuple)


@dataclass(frozen=True)
class TriageBlockSummaryRow:
    id: str
    user_id: str
    style_id: str
    style_name: str
    name: str
    date_from: str
    date_to: str
    status: str
    created_at: str
    updated_at: str
    finalized_at: str | None
    track_count: int


@dataclass(frozen=True)
class BucketTrackRowOut:
    """Row returned by GET /triage/blocks/{id}/buckets/{bucket_id}/tracks."""

    track_id: str
    title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: str | None
    spotify_release_date: str | None
    spotify_id: str | None
    release_type: str | None
    is_ai_suspected: bool
    artists: tuple[str, ...]
    added_at: str


@dataclass(frozen=True)
class MoveResult:
    moved: int


@dataclass(frozen=True)
class TransferResult:
    transferred: int


@dataclass(frozen=True)
class FinalizeResult:
    block: TriageBlockRow
    promoted: dict[str, int]


class TriageRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    # --- writes -------------------------------------------------------

    def create_block(
        self,
        *,
        user_id: str,
        style_id: str,
        name: str,
        date_from: date_type,
        date_to: date_type,
    ) -> TriageBlockRow:
        raise NotImplementedError

    def move_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        from_bucket_id: str,
        to_bucket_id: str,
        track_ids: Sequence[str],
    ) -> MoveResult:
        raise NotImplementedError

    def transfer_tracks(
        self,
        *,
        user_id: str,
        src_block_id: str,
        target_bucket_id: str,
        track_ids: Sequence[str],
    ) -> TransferResult:
        raise NotImplementedError

    def finalize_block(
        self,
        *,
        user_id: str,
        block_id: str,
        categories_repository: Any,
    ) -> FinalizeResult:
        raise NotImplementedError

    def soft_delete_block(
        self, *, user_id: str, block_id: str
    ) -> bool:
        raise NotImplementedError

    def snapshot_category_into_active_blocks(
        self,
        *,
        user_id: str,
        style_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    def mark_staging_inactive_for_category(
        self,
        *,
        user_id: str,
        category_id: str,
        transaction_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    # --- reads --------------------------------------------------------

    def get_block(
        self, *, user_id: str, block_id: str
    ) -> TriageBlockRow | None:
        raise NotImplementedError

    def list_blocks_by_style(
        self,
        *,
        user_id: str,
        style_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        raise NotImplementedError

    def list_blocks_all(
        self,
        *,
        user_id: str,
        limit: int,
        offset: int,
        status: str | None = None,
    ) -> tuple[list[TriageBlockSummaryRow], int]:
        raise NotImplementedError

    def list_bucket_tracks(
        self,
        *,
        user_id: str,
        block_id: str,
        bucket_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
    ) -> tuple[list[BucketTrackRowOut], int]:
        raise NotImplementedError

"""Curation user-overlay package: categories (spec-C), triage (spec-D), release-playlists (spec-E).

This module exposes only the cross-cutting types and errors shared by
all curation specs. Per-spec implementation lives in sibling modules
(`categories_repository.py`, `categories_service.py`, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CurationError(Exception):
    """Base for curation-domain errors raised by repositories/services."""

    error_code: str = "curation_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(CurationError):
    error_code = "validation_error"
    http_status = 422


class NotFoundError(CurationError):
    http_status = 404

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class NameConflictError(CurationError):
    error_code = "name_conflict"
    http_status = 409


class OrderMismatchError(CurationError):
    error_code = "order_mismatch"
    http_status = 422


class InvalidStateError(CurationError):
    """Operation rejected because target entity is in the wrong state."""

    error_code = "invalid_state"
    http_status = 422


class InactiveBucketError(CurationError):
    """Move/transfer target is an inactive staging bucket."""

    error_code = "target_bucket_inactive"
    http_status = 422


class InactiveStagingFinalizeError(CurationError):
    """Finalize blocked because at least one inactive staging bucket has tracks."""

    error_code = "inactive_buckets_have_tracks"
    http_status = 409

    def __init__(
        self, message: str, inactive_buckets: list[dict[str, object]]
    ) -> None:
        super().__init__(message)
        self.inactive_buckets = inactive_buckets


class TracksNotInSourceError(CurationError):
    """Move/transfer references track ids absent from the source bucket/block."""

    error_code = "tracks_not_in_source"
    http_status = 422

    def __init__(
        self, message: str, not_in_source: list[str]
    ) -> None:
        super().__init__(message)
        self.not_in_source = not_in_source


class StyleMismatchError(CurationError):
    """Cross-style transfer attempt."""

    error_code = "target_block_style_mismatch"
    http_status = 422

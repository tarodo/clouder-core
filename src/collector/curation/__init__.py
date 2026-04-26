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

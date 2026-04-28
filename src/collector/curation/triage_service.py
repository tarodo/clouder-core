"""Pure helpers for spec-D triage. No DB access here."""

from __future__ import annotations

from datetime import date
from typing import Any, Mapping

from collector.curation import (
    InactiveBucketError,
    InvalidStateError,
    StyleMismatchError,
    ValidationError,
)


# Bucket type constants -- mirror the CHECK constraint values.
BUCKET_TYPE_NEW = "NEW"
BUCKET_TYPE_OLD = "OLD"
BUCKET_TYPE_NOT = "NOT"
BUCKET_TYPE_DISCARD = "DISCARD"
BUCKET_TYPE_UNCLASSIFIED = "UNCLASSIFIED"
BUCKET_TYPE_STAGING = "STAGING"

# The five technical bucket types created at block-create time.
TECHNICAL_BUCKET_TYPES: tuple[str, ...] = (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_UNCLASSIFIED,
)

# UI sort order for technical buckets in detail responses.
TECHNICAL_BUCKET_DISPLAY_ORDER: tuple[str, ...] = (
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_UNCLASSIFIED,
    BUCKET_TYPE_DISCARD,
)

NAME_MAX_LEN = 128
TRACK_IDS_MAX = 1000


def validate_block_input(name: str, date_from: date, date_to: date) -> None:
    if not name or not name.strip():
        raise ValidationError("name must not be blank")
    if len(name) > NAME_MAX_LEN:
        raise ValidationError(f"name length must be <= {NAME_MAX_LEN}")
    if date_to < date_from:
        raise ValidationError("date_to must be >= date_from")


def validate_track_ids(ids: list[str]) -> None:
    if not ids:
        raise ValidationError("track_ids must not be empty")
    if len(ids) > TRACK_IDS_MAX:
        raise ValidationError(
            f"track_ids length must be <= {TRACK_IDS_MAX}"
        )
    for t in ids:
        if not isinstance(t, str) or len(t) != 36:
            raise ValidationError(
                f"track_id must be a 36-char UUID string: {t!r}"
            )


def validate_target_for_transfer(
    *,
    src_block: Mapping[str, Any],
    target_bucket: Mapping[str, Any],
    target_block: Mapping[str, Any],
) -> None:
    if target_block.get("status") != "IN_PROGRESS":
        raise InvalidStateError(
            "target triage block is not IN_PROGRESS"
        )
    if target_bucket.get("inactive") is True:
        raise InactiveBucketError(
            "target bucket is inactive (its category was soft-deleted)"
        )
    if src_block.get("style_id") != target_block.get("style_id"):
        raise StyleMismatchError(
            "source and target triage blocks belong to different styles"
        )


def classify_bucket_type(
    *,
    spotify_release_date: date | None,
    release_type: str | None,
    date_from: date,
) -> str:
    """R4 classification mirror of the SQL CASE.

    Matches the ordering in §6.1 of the spec:
        NULL date -> UNCLASSIFIED
        date < date_from -> OLD
        release_type == 'compilation' -> NOT
        else -> NEW
    """
    if spotify_release_date is None:
        return BUCKET_TYPE_UNCLASSIFIED
    if spotify_release_date < date_from:
        return BUCKET_TYPE_OLD
    if release_type == "compilation":
        return BUCKET_TYPE_NOT
    return BUCKET_TYPE_NEW

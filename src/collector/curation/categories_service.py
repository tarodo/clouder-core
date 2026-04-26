"""Pure helpers for spec-C categories: normalization, validation, reorder checks."""

from __future__ import annotations

from typing import Iterable, Sequence

from . import OrderMismatchError, ValidationError


_MAX_NAME_LENGTH = 64


def normalize_category_name(name: str) -> str:
    """Lowercase + trim + collapse internal whitespace.

    Used for the UNIQUE check on (user_id, style_id, normalized_name).
    The original `name` is preserved separately for display.
    """
    return " ".join(name.strip().lower().split())


def validate_category_name(name: str) -> None:
    """Raise ValidationError if the name is unacceptable.

    Rules:
        - Non-empty after trim
        - No more than 64 chars after trim
        - No control characters (ord < 0x20 or ord == 0x7F)
    """
    trimmed = name.strip()
    if not trimmed:
        raise ValidationError("Name must be non-empty")
    if len(trimmed) > _MAX_NAME_LENGTH:
        raise ValidationError(
            f"Name must be at most {_MAX_NAME_LENGTH} characters"
        )
    for ch in trimmed:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValidationError("Name must not contain control characters")


def validate_reorder_set(
    *, actual: Iterable[str], requested: Sequence[str]
) -> None:
    """Ensure the requested id list equals the actual alive set, no dups.

    Used by PUT /styles/{style_id}/categories/order. Either:
        - missing id (some current category not listed)
        - extra id (foreign / soft-deleted / wrong style)
        - duplicates within `requested`
    yields OrderMismatchError.
    """
    actual_set = set(actual)
    requested_set = set(requested)
    if len(requested) != len(requested_set):
        raise OrderMismatchError(
            "category_ids contains duplicates"
        )
    if actual_set != requested_set:
        raise OrderMismatchError(
            "category_ids must equal the current set of categories"
        )

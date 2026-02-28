"""Input models and date computations for weekly collection."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping, Tuple

from .errors import ValidationError


@dataclass(frozen=True)
class CollectRequest:
    bp_token: str
    style_id: int
    iso_year: int
    iso_week: int


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_collect_request(payload: Mapping[str, Any]) -> CollectRequest:
    if not isinstance(payload, Mapping):
        raise ValidationError("Request body must be a JSON object")

    bp_token = payload.get("bp_token")
    style_id = payload.get("style_id")
    iso_year = payload.get("iso_year")
    iso_week = payload.get("iso_week")

    if not isinstance(bp_token, str) or not bp_token.strip():
        raise ValidationError("bp_token is required and must be a non-empty string")

    if not _is_int(style_id) or style_id <= 0:
        raise ValidationError("style_id must be a positive integer")

    if not _is_int(iso_year) or iso_year < 2000 or iso_year > 2100:
        raise ValidationError("iso_year must be an integer in range 2000..2100")

    if not _is_int(iso_week) or iso_week < 1 or iso_week > 53:
        raise ValidationError("iso_week must be an integer in range 1..53")

    # Validates true ISO year/week combinations (e.g. rejects nonexistent week 53).
    try:
        date.fromisocalendar(iso_year, iso_week, 1)
    except ValueError as exc:
        raise ValidationError("iso_year/iso_week combination is invalid") from exc

    return CollectRequest(
        bp_token=bp_token.strip(),
        style_id=style_id,
        iso_year=iso_year,
        iso_week=iso_week,
    )


def compute_iso_week_date_range(iso_year: int, iso_week: int) -> Tuple[str, str]:
    """Return ISO week boundaries as date strings (YYYY-MM-DD)."""

    week_start = date.fromisocalendar(iso_year, iso_week, 1)
    week_end = date.fromisocalendar(iso_year, iso_week, 7)
    return week_start.isoformat(), week_end.isoformat()

"""Shared base and time helpers of the repository mixins."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..data_api import DataAPIClient

# ponytail: ids per `IN (...)` identity lookup. 500 rows of (external_id, clouder_id)
# stay far under the Data API 1 MB response cap; raise only with a measured reason.
_LOOKUP_CHUNK = 500


class RepositoryBase:
    """Every mixin talks to Aurora only through this client."""

    _data_api: DataAPIClient


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(UTC)


def as_utc_datetime(value: str | datetime | None) -> datetime | None:
    """A timestamp from the Data API ('YYYY-MM-DD HH:MM:SS[.fff]', UTC) or the
    driver, as an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=UTC)

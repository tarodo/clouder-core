"""Shared base and time helpers of the repository mixins."""

from __future__ import annotations

from datetime import UTC, date, datetime

from ..data_api import DataAPIClient

# ponytail: ids per `IN (...)` identity lookup. 500 rows of (external_id, clouder_id)
# stay far under the Data API 1 MB response cap; raise only with a measured reason.
_LOOKUP_CHUNK = 500

# Tracks a user has labeled: in a live category, or in a DISCARD / FAV bucket of
# any live triage block (a finalized block keeps its buckets). Auto buckets
# (NEW, OLD, NOT, UNCLASSIFIED) are no label. Used inside `IN (...)` or a UNION.
LABELED_TRACK_IDS = """
    SELECT ct.track_id FROM category_tracks ct
    JOIN categories c ON c.id = ct.category_id
    WHERE c.deleted_at IS NULL
    UNION
    SELECT tbt.track_id FROM triage_bucket_tracks tbt
    JOIN triage_buckets b ON b.id = tbt.triage_bucket_id
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
    WHERE b.bucket_type IN ('DISCARD', 'FAV') AND tb.deleted_at IS NULL
"""


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

"""Daily Aurora catalog snapshot to the analytics lake (bronze/catalog_export/).

Runs the dim read queries through the RDS Data API (ADR-0001: Aurora is reached
only via the Data API at runtime), pages by primary key (keyset) and writes
line-delimited JSON to S3. Intentionally lightweight: no columnar or DataFrame
dependency is bundled, so the collector zip stays small — a Glue table types the
columns and Athena casts on read (spec section 6).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from .data_api import DataAPIClient, create_default_data_api_client
from .logging_utils import log_event
from .settings import get_data_api_settings

# (table, columns, primary key). Pages continue after the last row's key, so each
# page is an index range scan and a row inserted or deleted mid-export cannot shift
# the pages. OFFSET paging cost grew with every page: at ~430k rows the export hit
# its 300 s timeout two nights running (2026-10-10, 10-11).
_EXPORTS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "clouder_tracks",
        "id, title, bpm, key_name, key_camelot, spotify_release_date, publish_date, "
        "album_id, style_id, isrc, release_type, is_ai_suspected, origin, created_at, "
        "updated_at",
        ("id",),
    ),
    (
        "clouder_artists",
        "id, name, normalized_name, is_ai_suspected, created_at, updated_at",
        ("id",),
    ),
    ("clouder_track_artists", "track_id, artist_id, role", ("track_id", "artist_id", "role")),
    (
        "clouder_labels",
        "id, name, normalized_name, is_ai_suspected, created_at, updated_at",
        ("id",),
    ),
    (
        "clouder_albums",
        "id, title, label_id, release_date, release_type, created_at, updated_at",
        ("id",),
    ),
    (
        "categories",
        "id, user_id, style_id, name, normalized_name, position, created_at, updated_at, "
        "deleted_at",
        ("id",),
    ),
    (
        "category_tracks",
        "category_id, track_id, added_at, source_triage_block_id",
        ("category_id", "track_id"),
    ),
    # Style names for the per-style analytics (incl. hidden styles). Written last: the
    # nightly freshness check treats its presence as a complete snapshot.
    ("clouder_styles", "id, name, normalized_name, created_at, updated_at", ("id",)),
)

# The Data API caps a response at ~1 MB: 500 rows of the widest dim (clouder_tracks,
# 15 columns) stay well under it. If a wider dim ever raises "Database response
# exceeded size limit", halve this.
_PAGE = 500


def _sql(table: str, columns: str, keys: tuple[str, ...], after: tuple[Any, ...] | None) -> str:
    order = ", ".join(keys)
    where = ""
    if after is not None:
        marks = ", ".join(f":k{i}" for i in range(len(keys)))
        where = f" WHERE ({order}) > ({marks})"
    return f"SELECT {columns} FROM {table}{where} ORDER BY {order} LIMIT :limit"


def _ndjson(rows: Iterable[dict[str, Any]]) -> bytes:
    # default=str renders datetime/date/Decimal deterministically (ISO-ish);
    # Athena/dbt cast on read.
    return "".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=str) + "\n" for r in rows
    ).encode("utf-8")


def export_catalog(
    data_api: DataAPIClient,
    s3_client: Any,
    bucket: str,
    snapshot_dt: str,
    page: int = _PAGE,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, columns, keys in _EXPORTS:
        started = time.monotonic()
        after: tuple[Any, ...] | None = None
        part = total = 0
        while True:
            params: dict[str, Any] = {"limit": page}
            if after is not None:
                params.update({f"k{i}": v for i, v in enumerate(after)})
            rows = data_api.execute(_sql(table, columns, keys, after), params)
            if not rows:
                break
            key = f"bronze/catalog_export/snapshot_dt={snapshot_dt}/{table}/part-{part:05d}.json"
            s3_client.put_object(
                Bucket=bucket,
                Key=key,
                Body=_ndjson(rows),
                ContentType="application/x-ndjson",
            )
            total += len(rows)
            part += 1
            if len(rows) < page:
                break
            after = tuple(rows[-1][k] for k in keys)
        counts[table] = total
        log_event(
            "INFO",
            "catalog_export_table_written",
            s3_bucket=bucket,
            table_name=table,
            total_count=total,
            api_pages_fetched=part,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
    return counts


def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
    import boto3

    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    bucket = os.environ["ANALYTICS_LAKE_BUCKET"]
    snapshot_dt = (event or {}).get("snapshot_dt") or datetime.now(UTC).strftime("%Y-%m-%d")
    counts = export_catalog(data_api, boto3.client("s3"), bucket, snapshot_dt)
    log_event("INFO", "catalog_export_completed", item_count=sum(counts.values()))
    return {"snapshot_dt": snapshot_dt, "counts": counts}

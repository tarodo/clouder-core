"""Daily Aurora catalog snapshot to the analytics lake (bronze/catalog_export/).

Runs the dim read queries through the RDS Data API (ADR-0001: Aurora is reached
only via the Data API at runtime), pages with LIMIT/OFFSET ordered by primary
key, and writes line-delimited JSON to S3. Intentionally lightweight: no
columnar or DataFrame dependency is bundled, so the collector zip stays small —
a Glue table types the columns and Athena casts on read (spec section 6).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Iterable

from .data_api import DataAPIClient, create_default_data_api_client
from .logging_utils import log_event
from .settings import get_data_api_settings

# (table, sql). Each SQL takes :limit/:offset and ORDERs BY primary key so paging
# is stable and keyset-upgradeable. Columns are the real db_models.py /
# categories-migration names. See _PAGE for the page-size constraint.
_EXPORTS: tuple[tuple[str, str], ...] = (
    ("clouder_tracks",
     "SELECT id, title, bpm, key_name, key_camelot, spotify_release_date, "
     "publish_date, album_id, style_id, isrc, release_type, is_ai_suspected, "
     "origin, created_at, updated_at "
     "FROM clouder_tracks ORDER BY id LIMIT :limit OFFSET :offset"),
    ("clouder_artists",
     "SELECT id, name, normalized_name, is_ai_suspected, created_at, updated_at "
     "FROM clouder_artists ORDER BY id LIMIT :limit OFFSET :offset"),
    ("clouder_track_artists",
     "SELECT track_id, artist_id, role "
     "FROM clouder_track_artists ORDER BY track_id, artist_id, role "
     "LIMIT :limit OFFSET :offset"),
    ("clouder_labels",
     "SELECT id, name, normalized_name, is_ai_suspected, created_at, updated_at "
     "FROM clouder_labels ORDER BY id LIMIT :limit OFFSET :offset"),
    ("clouder_albums",
     "SELECT id, title, label_id, release_date, release_type, created_at, "
     "updated_at FROM clouder_albums ORDER BY id LIMIT :limit OFFSET :offset"),
    ("categories",
     "SELECT id, user_id, style_id, name, normalized_name, position, "
     "created_at, updated_at, deleted_at "
     "FROM categories ORDER BY id LIMIT :limit OFFSET :offset"),
    ("category_tracks",
     "SELECT category_id, track_id, added_at, source_triage_block_id "
     "FROM category_tracks ORDER BY category_id, track_id "
     "LIMIT :limit OFFSET :offset"),
)

# ponytail: the BINDING constraint on page size is the RDS Data API ~1MB
# per-ExecuteStatement response cap, NOT OFFSET scan cost. 500 rows of the
# widest dim (clouder_tracks, ~15 columns) stays well under 1MB at the stated
# daily-snapshot volume (spec section 6). If a wider dim ever raises "Database
# response exceeded size limit", halve this. OFFSET cost is a non-issue at
# this volume; switch to PK-range keyset only if that ever changes.
_PAGE = 500


def _ndjson(rows: Iterable[dict[str, Any]]) -> bytes:
    # default=str renders datetime/date/Decimal deterministically (ISO-ish);
    # Athena/dbt cast on read.
    return "".join(
        json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=str) + "\n"
        for r in rows
    ).encode("utf-8")


def export_catalog(
    data_api: DataAPIClient,
    s3_client: Any,
    bucket: str,
    snapshot_dt: str,
    page: int = _PAGE,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table, sql in _EXPORTS:
        offset = part = total = 0
        while True:
            rows = data_api.execute(sql, {"limit": page, "offset": offset})
            if not rows:
                break
            key = (
                f"bronze/catalog_export/snapshot_dt={snapshot_dt}/{table}/"
                f"part-{part:05d}.json"
            )
            s3_client.put_object(
                Bucket=bucket, Key=key, Body=_ndjson(rows),
                ContentType="application/x-ndjson",
            )
            total += len(rows)
            part += 1
            if len(rows) < page:
                break
            offset += page
        counts[table] = total
        log_event("INFO", "catalog_export_table_written",
                  s3_bucket=bucket, total_count=total)
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
    snapshot_dt = (event or {}).get("snapshot_dt") or datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d")
    counts = export_catalog(data_api, boto3.client("s3"), bucket, snapshot_dt)
    log_event("INFO", "catalog_export_completed", item_count=sum(counts.values()))
    return {"snapshot_dt": snapshot_dt, "counts": counts}

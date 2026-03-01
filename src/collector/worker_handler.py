"""SQS worker that canonicalizes Beatport raw data."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping

from .canonicalize import Canonicalizer
from .logging_utils import log_event
from .normalize import normalize_tracks
from .repositories import create_clouder_repository_from_env, utc_now
from .storage import S3Storage, create_default_s3_client


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    processed = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        payload = json.loads(body)
        run_id = str(payload.get("run_id", "")).strip()
        s3_key = str(payload.get("s3_key", "")).strip()
        if not run_id or not s3_key:
            continue

        correlation_id = _extract_message_attribute(record, "correlation_id")
        if not correlation_id:
            correlation_id = run_id

        repository = create_clouder_repository_from_env()
        if repository is None:
            raise RuntimeError("AURORA Data API configuration is required for canonicalization worker")

        storage = S3Storage(
            s3_client=create_default_s3_client(),
            bucket_name=_required_env("RAW_BUCKET_NAME"),
            raw_prefix=_required_env("RAW_PREFIX", default="raw/bp/releases"),
        )

        try:
            raw_tracks = storage.read_releases(s3_key)
            bundle = normalize_tracks(raw_tracks)
            canonicalizer = Canonicalizer(repository)
            result = canonicalizer.process_run(run_id=run_id, bundle=bundle)
            repository.set_run_completed(run_id=run_id, processed_count=result.tracks_processed, finished_at=utc_now())
            processed += 1
            log_event(
                "INFO",
                "canonicalization_completed",
                correlation_id=correlation_id,
                run_id=run_id,
                item_count=result.tracks_processed,
                status_code=200,
            )
        except Exception as exc:
            repository.set_run_failed(
                run_id=run_id,
                error_code="canonicalization_failed",
                error_message=str(exc),
                finished_at=utc_now(),
            )
            log_event(
                "ERROR",
                "canonicalization_failed",
                correlation_id=correlation_id,
                run_id=run_id,
                error_code="canonicalization_failed",
                error_type=exc.__class__.__name__,
                status_code=500,
            )
            raise

    return {"processed": processed}


def _extract_message_attribute(record: Mapping[str, Any], key: str) -> str | None:
    attributes = record.get("messageAttributes")
    if not isinstance(attributes, Mapping):
        return None
    value = attributes.get(key)
    if isinstance(value, Mapping):
        candidate = value.get("stringValue")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _required_env(name: str, default: str | None = None) -> str:
    value = default if default is not None else ""
    value = str(os.getenv(name, value)).strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

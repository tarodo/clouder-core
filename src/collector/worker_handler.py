"""SQS worker that canonicalizes Beatport raw data."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .canonicalize import Canonicalizer
from .logging_utils import log_event
from .normalize import normalize_tracks
from .repositories import create_clouder_repository_from_env, utc_now
from .schemas import CanonicalizationMessage, validation_error_message
from .settings import get_worker_settings
from .storage import S3Storage, create_default_s3_client


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    log_event(
        "INFO",
        "canonicalization_worker_invoked",
        sqs_record_count=len(records),
    )

    settings = get_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for canonicalization worker"
        )

    storage = S3Storage(
        s3_client=create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            payload = CanonicalizationMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "canonicalization_message_invalid",
                sqs_record_index=index,
                error_code="validation_error",
                error_message=validation_error_message(exc),
            )
            continue

        run_id = payload.run_id
        s3_key = payload.s3_key
        correlation_id = _extract_message_attribute(record, "correlation_id") or run_id

        log_event(
            "INFO",
            "canonicalization_run_started",
            correlation_id=correlation_id,
            run_id=run_id,
            s3_key=s3_key,
        )

        try:
            raw_tracks = storage.read_releases(s3_key)
            log_event(
                "INFO",
                "canonicalization_raw_loaded",
                correlation_id=correlation_id,
                run_id=run_id,
                item_count=len(raw_tracks),
                s3_key=s3_key,
            )

            bundle = normalize_tracks(raw_tracks)
            log_event(
                "INFO",
                "canonicalization_normalized",
                correlation_id=correlation_id,
                run_id=run_id,
                tracks_total=len(bundle.tracks),
                artists_total=len(bundle.artists),
                labels_total=len(bundle.labels),
                albums_total=len(bundle.albums),
                relations_total=len(bundle.relations),
            )

            canonicalizer = Canonicalizer(repository)
            result = canonicalizer.process_run(run_id=run_id, bundle=bundle)
            repository.set_run_completed(
                run_id=run_id,
                processed_count=result.tracks_processed,
                finished_at=utc_now(),
            )
            processed += 1

            log_event(
                "INFO",
                "canonicalization_completed",
                correlation_id=correlation_id,
                run_id=run_id,
                item_count=result.tracks_processed,
                tracks_total=result.tracks_total,
                tracks_processed=result.tracks_processed,
                artists_total=result.artists_total,
                labels_total=result.labels_total,
                albums_total=result.albums_total,
                run_status="COMPLETED",
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
                error_message=str(exc)[:500],
                run_status="FAILED",
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

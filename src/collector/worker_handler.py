"""SQS worker that canonicalizes Beatport raw data."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .canonicalize import Canonicalizer
from .errors import StorageError
from .logging_utils import log_event
from .normalize import normalize_tracks
from .repositories import ClouderRepository, create_clouder_repository_from_env, utc_now
from .schemas import CanonicalizationMessage, validation_error_message
from .search.prompts import get_latest as get_latest_prompt
from .settings import get_worker_settings
from .storage import S3Storage, create_default_s3_client

# Permanent errors: data is corrupted / malformed — retrying is pointless.
# Message is deleted from queue (not re-raised) so it won't cycle to DLQ.
_PERMANENT_ERRORS = (ValueError, TypeError, KeyError, StorageError)


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

            _enqueue_label_search_after_canonicalization(
                repository=repository,
                settings=settings,
                correlation_id=correlation_id,
            )
            _enqueue_spotify_search_after_canonicalization(
                settings=settings,
                correlation_id=correlation_id,
            )
        except Exception as exc:
            is_permanent = isinstance(exc, _PERMANENT_ERRORS)
            error_code = (
                "canonicalization_permanent_failure"
                if is_permanent
                else "canonicalization_transient_failure"
            )
            repository.set_run_failed(
                run_id=run_id,
                error_code=error_code,
                error_message=str(exc),
                finished_at=utc_now(),
            )
            log_event(
                "ERROR",
                "canonicalization_failed",
                correlation_id=correlation_id,
                run_id=run_id,
                error_code=error_code,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
                run_status="FAILED",
                status_code=500,
            )
            if is_permanent:
                # Permanent errors: don't re-raise → SQS deletes the message.
                # Avoids 5 pointless retries for corrupted/malformed data.
                continue
            raise

    return {"processed": processed}


def _enqueue_label_search_after_canonicalization(
    repository: ClouderRepository,
    settings: Any,
    correlation_id: str,
) -> None:
    """Enqueue labels for AI search after canonicalization completes."""
    queue_url = settings.ai_search_queue_url.strip()
    if not queue_url:
        return

    try:
        prompt = get_latest_prompt("label_info")
    except KeyError:
        return

    labels = repository.find_labels_needing_search(
        prompt_slug=prompt.slug,
        prompt_version=prompt.version,
        limit=500,
    )

    if not labels:
        return

    import boto3

    sqs = boto3.client("sqs")
    enqueued = 0
    for label in labels:
        payload = {
            "label_id": str(label["id"]),
            "label_name": str(label["name"]),
            "styles": str(label.get("styles") or ""),
            "prompt_slug": prompt.slug,
            "prompt_version": prompt.version,
        }
        try:
            sqs.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    payload, ensure_ascii=False, separators=(",", ":")
                ),
                MessageAttributes={
                    "correlation_id": {
                        "DataType": "String",
                        "StringValue": correlation_id,
                    }
                },
            )
            enqueued += 1
        except Exception as exc:  # pragma: no cover
            log_event(
                "ERROR",
                "label_search_enqueue_message_failed",
                correlation_id=correlation_id,
                label_id=str(label["id"]),
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )

    if enqueued:
        log_event(
            "INFO",
            "label_search_enqueued_after_canonicalization",
            correlation_id=correlation_id,
            labels_found=len(labels),
            labels_enqueued=enqueued,
            prompt_slug=prompt.slug,
            prompt_version=prompt.version,
        )


def _enqueue_spotify_search_after_canonicalization(
    settings: Any,
    correlation_id: str,
) -> None:
    """Enqueue Spotify ISRC search after canonicalization completes."""
    queue_url = settings.spotify_search_queue_url.strip()
    if not queue_url:
        return

    import boto3

    sqs = boto3.client("sqs")
    message = {"batch_size": 2000}
    try:
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(message, ensure_ascii=False, separators=(",", ":")),
            MessageAttributes={
                "correlation_id": {
                    "DataType": "String",
                    "StringValue": correlation_id,
                }
            },
        )
        log_event(
            "INFO",
            "spotify_search_enqueued_after_canonicalization",
            correlation_id=correlation_id,
        )
    except Exception as exc:  # pragma: no cover
        log_event(
            "ERROR",
            "spotify_search_enqueue_failed",
            correlation_id=correlation_id,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
        )


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

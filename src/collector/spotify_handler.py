"""SQS worker that searches Spotify for tracks by ISRC."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .errors import SpotifyAuthError, SpotifyUnavailableError, StorageError
from .logging_utils import log_event
from .repositories import (
    ClouderRepository,
    UpdateSpotifyResultCmd,
    UpsertIdentityCmd,
    UpsertSourceEntityCmd,
    create_clouder_repository_from_env,
    utc_now,
)
from .schemas import SpotifySearchMessage, validation_error_message
from .settings import get_spotify_worker_settings
from .spotify_client import SpotifyClient, SpotifySearchResult
from .storage import S3Storage, create_default_s3_client

_PERMANENT_ERRORS = (ValueError, TypeError, KeyError, StorageError)
_CHUNK_SIZE = 200


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    log_event(
        "INFO",
        "spotify_worker_invoked",
        sqs_record_count=len(records),
    )

    settings = get_spotify_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for Spotify search worker"
        )

    storage = S3Storage(
        s3_client=create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.spotify_raw_prefix,
    )

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            payload = SpotifySearchMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "spotify_message_invalid",
                sqs_record_index=index,
                error_code="validation_error",
                error_message=validation_error_message(exc),
            )
            continue

        correlation_id = _extract_message_attribute(record, "correlation_id") or str(
            uuid4()
        )

        log_event(
            "INFO",
            "spotify_search_started",
            correlation_id=correlation_id,
            batch_size=payload.batch_size,
        )

        try:
            _process_spotify_search(
                repository=repository,
                storage=storage,
                settings=settings,
                message=payload,
                correlation_id=correlation_id,
            )
            processed += 1
        except Exception as exc:
            is_permanent = isinstance(exc, _PERMANENT_ERRORS)
            error_code = (
                "spotify_permanent_failure"
                if is_permanent
                else "spotify_transient_failure"
            )
            log_event(
                "ERROR",
                "spotify_search_failed",
                correlation_id=correlation_id,
                error_code=error_code,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            if is_permanent:
                continue
            raise

    return {"processed": processed}


def _process_spotify_search(
    repository: ClouderRepository,
    storage: S3Storage,
    settings: Any,
    message: SpotifySearchMessage,
    correlation_id: str,
) -> None:
    tracks = repository.find_tracks_needing_spotify_search(limit=message.batch_size)
    if not tracks:
        log_event(
            "INFO",
            "spotify_search_skipped",
            correlation_id=correlation_id,
            reason="no_tracks_need_search",
        )
        return

    log_event(
        "INFO",
        "spotify_search_tracks_loaded",
        correlation_id=correlation_id,
        track_count=len(tracks),
    )

    client = SpotifyClient(
        client_id=settings.spotify_client_id,
        client_secret=settings.spotify_client_secret,
    )

    search_input = [
        {"clouder_track_id": str(t["id"]), "isrc": str(t["isrc"])}
        for t in tracks
    ]

    results = client.search_tracks_by_isrc(
        tracks=search_input,
        correlation_id=correlation_id,
    )

    now = utc_now()
    found_count = sum(1 for r in results if r.spotify_id)
    not_found_count = len(results) - found_count

    # Write batch results to S3.
    s3_results = [
        {
            "isrc": r.isrc,
            "clouder_track_id": r.clouder_track_id,
            "spotify_id": r.spotify_id,
            "spotify_track": r.spotify_track,
        }
        for r in results
    ]
    meta = {
        "correlation_id": correlation_id,
        "searched_at_utc": now.replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "total_tracks": len(results),
        "found": found_count,
        "not_found": not_found_count,
    }
    results_key, _ = storage.write_spotify_results(
        results=s3_results,
        meta=meta,
        spotify_prefix=settings.spotify_raw_prefix,
    )

    # Process in chunks: upsert source_entities + identity_map + update tracks.
    for chunk_start in range(0, len(results), _CHUNK_SIZE):
        chunk = results[chunk_start : chunk_start + _CHUNK_SIZE]
        _process_results_chunk(repository, chunk, now)

    log_event(
        "INFO",
        "spotify_search_completed",
        correlation_id=correlation_id,
        total_tracks=len(results),
        found=found_count,
        not_found=not_found_count,
        s3_key=results_key,
    )

    # If more tracks remain and auto_continue is enabled, enqueue a follow-up message.
    if message.auto_continue:
        _enqueue_follow_up_if_needed(
            repository=repository,
            settings=settings,
            batch_size=message.batch_size,
            correlation_id=correlation_id,
        )
    else:
        log_event(
            "INFO",
            "spotify_follow_up_skipped",
            correlation_id=correlation_id,
            reason="auto_continue_disabled",
        )


def _process_results_chunk(
    repository: ClouderRepository,
    chunk: list[SpotifySearchResult],
    now: datetime,
) -> None:
    """Persist a chunk of Spotify search results to the database."""
    # 1. Upsert source_entities for found tracks.
    source_entity_cmds = []
    identity_cmds = []
    for r in chunk:
        if r.spotify_id and r.spotify_track:
            payload = r.spotify_track
            payload_hash = hashlib.sha256(
                json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
            ).hexdigest()

            name = payload.get("name", "")
            source_entity_cmds.append(
                UpsertSourceEntityCmd(
                    source="spotify",
                    entity_type="track",
                    external_id=r.spotify_id,
                    name=name,
                    normalized_name=name.lower().strip() if name else None,
                    payload=payload,
                    payload_hash=payload_hash,
                    last_run_id=None,
                    observed_at=now,
                )
            )
            identity_cmds.append(
                UpsertIdentityCmd(
                    source="spotify",
                    entity_type="track",
                    external_id=r.spotify_id,
                    clouder_entity_type="track",
                    clouder_id=r.clouder_track_id,
                    match_type="isrc_match",
                    confidence=Decimal("1.000"),
                    observed_at=now,
                )
            )

    if source_entity_cmds:
        repository.batch_upsert_source_entities(source_entity_cmds)
    if identity_cmds:
        repository.batch_upsert_identities(identity_cmds)

    # 2. Batch update clouder_tracks with spotify_id and searched_at.
    update_cmds = [
        UpdateSpotifyResultCmd(
            track_id=r.clouder_track_id,
            spotify_id=r.spotify_id,
            searched_at=now,
        )
        for r in chunk
    ]
    repository.batch_update_spotify_results(update_cmds)


def _enqueue_follow_up_if_needed(
    repository: ClouderRepository,
    settings: Any,
    batch_size: int,
    correlation_id: str,
) -> None:
    """Send a follow-up SQS message if more tracks still need searching."""
    remaining = repository.find_tracks_needing_spotify_search(limit=1)
    if not remaining:
        return

    queue_url = settings.spotify_search_queue_url.strip()
    if not queue_url:
        log_event(
            "WARNING",
            "spotify_follow_up_skipped",
            correlation_id=correlation_id,
            reason="no_queue_url",
        )
        return

    message = {"batch_size": batch_size}
    try:
        import boto3

        sqs = boto3.client("sqs")
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
            "spotify_follow_up_enqueued",
            correlation_id=correlation_id,
            batch_size=batch_size,
        )
    except Exception as exc:
        log_event(
            "ERROR",
            "spotify_follow_up_enqueue_failed",
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

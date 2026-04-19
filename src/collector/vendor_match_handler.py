"""SQS-triggered worker that matches a canonical track to a vendor."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .errors import VendorDisabledError
from .logging_utils import log_event
from .providers import registry
from .providers.base import LookupProvider, VendorTrackRef
from .repositories import (
    ClouderRepository,
    UpsertVendorMatchCmd,
    create_clouder_repository_from_env,
)
from .schemas import VendorMatchMessage, validation_error_message
from .settings import get_vendor_match_settings
from .vendor_match.retry import retry_vendor
from .vendor_match.scorer import FuzzyScore, score_candidate


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "vendor_match_worker_invoked", sqs_record_count=len(records))

    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for vendor_match worker"
        )

    processed = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            payload = json.loads(body)
            message = VendorMatchMessage.model_validate(payload)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            log_event(
                "ERROR",
                "vendor_match_message_invalid",
                error_message=validation_error_message(exc)
                if isinstance(exc, PydanticValidationError)
                else str(exc),
            )
            continue

        if _process_one(message, repository):
            processed += 1

    return {"processed": processed}


def _process_one(
    message: VendorMatchMessage, repository: ClouderRepository
) -> bool:
    log_event(
        "INFO",
        "vendor_match_started",
        track_id=message.clouder_track_id,
        vendor=message.vendor,
    )

    cached = repository.get_vendor_match(message.clouder_track_id, message.vendor)
    if cached is not None:
        log_event(
            "INFO",
            "vendor_match_cache_hit",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
        )
        return True

    try:
        lookup = registry.get_lookup(message.vendor)
    except VendorDisabledError:
        log_event(
            "WARNING",
            "vendor_match_vendor_disabled",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
        )
        return False

    now = datetime.now(timezone.utc)

    if message.isrc:
        ref = _try_isrc(lookup, message)
        if ref is not None:
            repository.upsert_vendor_match(
                UpsertVendorMatchCmd(
                    clouder_track_id=message.clouder_track_id,
                    vendor=message.vendor,
                    vendor_track_id=ref.vendor_track_id,
                    match_type="isrc",
                    confidence=Decimal("1.000"),
                    matched_at=now,
                    payload=ref.raw_payload,
                )
            )
            log_event(
                "INFO",
                "vendor_match_cached",
                track_id=message.clouder_track_id,
                vendor=message.vendor,
                match_type="isrc",
                confidence=1.0,
            )
            return True

    candidates = _try_metadata(lookup, message) or []
    scored: list[tuple[VendorTrackRef, FuzzyScore]] = [
        (
            c,
            score_candidate(
                candidate=c,
                artist=message.artist,
                title=message.title,
                duration_ms=message.duration_ms,
                album=message.album,
            ),
        )
        for c in candidates
    ]
    scored.sort(key=lambda t: t[1].total, reverse=True)

    threshold = get_vendor_match_settings().fuzzy_match_threshold
    if scored and scored[0][1].total >= threshold:
        best_cand, best_score = scored[0]
        repository.upsert_vendor_match(
            UpsertVendorMatchCmd(
                clouder_track_id=message.clouder_track_id,
                vendor=message.vendor,
                vendor_track_id=best_cand.vendor_track_id,
                match_type="fuzzy",
                confidence=Decimal(str(best_score.total)),
                matched_at=now,
                payload=best_cand.raw_payload,
            )
        )
        log_event(
            "INFO",
            "vendor_match_cached",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
            match_type="fuzzy",
            confidence=float(best_score.total),
        )
        return True

    top5 = [
        {
            "ref": c.raw_payload,
            "score": s.total,
            "title_sim": s.title_sim,
            "artist_sim": s.artist_sim,
            "duration_ok": s.duration_ok,
            "album_bonus": s.album_bonus,
        }
        for c, s in scored[:5]
    ]
    if top5:
        repository.insert_review_candidate(
            review_id=str(uuid4()),
            clouder_track_id=message.clouder_track_id,
            vendor=message.vendor,
            candidates=top5,
            created_at=now,
        )
        log_event(
            "INFO",
            "vendor_match_review_queued",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
            candidate_count=len(top5),
        )
    else:
        log_event(
            "WARNING",
            "vendor_match_no_candidates",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
        )
    return True


@retry_vendor(max_retries=3)
def _try_isrc(
    lookup: LookupProvider, message: VendorMatchMessage
) -> VendorTrackRef | None:
    return lookup.lookup_by_isrc(message.isrc or "")


@retry_vendor(max_retries=3)
def _try_metadata(
    lookup: LookupProvider, message: VendorMatchMessage
) -> list[VendorTrackRef]:
    return lookup.lookup_by_metadata(
        message.artist, message.title, message.duration_ms, message.album
    )

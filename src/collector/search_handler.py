"""SQS worker that performs AI-powered entity research via Perplexity."""

from __future__ import annotations

import json
from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .errors import VendorDisabledError
from .logging_utils import log_event
from .providers import registry
from .providers.base import EnrichResult
from .repositories import create_clouder_repository_from_env, utc_now
from .schemas import (
    EntitySearchMessage,
    coerce_search_message,
    validation_error_message,
)
from .search.schemas import AIContentStatus, LabelSearchResult
from .settings import get_search_worker_settings


def propagate_ai_flag(
    repository: Any,
    *,
    entity_type: str,
    entity_id: str,
    result: LabelSearchResult,
    threshold: float,
) -> None:
    """Set/clear is_ai_suspected on the canonical row based on an AI search result.

    Rules:
      - confidence < threshold → no-op (result too weak to act on).
      - ai_content in {suspected, confirmed} → set True.
      - ai_content == none_detected → set False (explicit clear).
      - ai_content == unknown → no-op (no signal).
    """
    if result.confidence < threshold:
        return
    status = result.ai_content
    if status in (AIContentStatus.SUSPECTED, AIContentStatus.CONFIRMED):
        repository.update_entity_is_ai_suspected(entity_type, entity_id, True)
    elif status == AIContentStatus.NONE_DETECTED:
        repository.update_entity_is_ai_suspected(entity_type, entity_id, False)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}

    log_event(
        "INFO",
        "search_worker_invoked",
        sqs_record_count=len(records),
    )

    settings = get_search_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError(
            "AURORA Data API configuration is required for search worker"
        )

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue

        try:
            payload = json.loads(body)
            message = coerce_search_message(payload)
        except (json.JSONDecodeError, PydanticValidationError) as exc:
            log_event(
                "ERROR",
                "search_message_invalid",
                sqs_record_index=index,
                error_code="validation_error",
                error_message=(
                    validation_error_message(exc)
                    if isinstance(exc, PydanticValidationError)
                    else str(exc)[:500]
                ),
            )
            continue

        correlation_id = (
            _extract_message_attribute(record, "correlation_id") or message.entity_id
        )

        if not _dispatch_entity_search(message, settings, repository, correlation_id):
            continue

        processed += 1

    return {"processed": processed}


def _dispatch_entity_search(
    message: EntitySearchMessage,
    settings: Any,
    repository: Any,
    correlation_id: str,
) -> bool:
    try:
        enricher = registry.get_enricher_for_prompt(message.prompt_slug)
    except VendorDisabledError:
        log_event(
            "WARNING",
            "search_entity_type_unsupported",
            correlation_id=correlation_id,
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
        )
        return False

    log_event(
        "INFO",
        "label_search_started"
        if message.entity_type == "label"
        else "entity_search_started",
        correlation_id=correlation_id,
        entity_id=message.entity_id,
        entity_type=message.entity_type,
        prompt_slug=message.prompt_slug,
        prompt_version=message.prompt_version,
    )

    try:
        result: EnrichResult = enricher.enrich(
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            context=dict(message.context),
            correlation_id=correlation_id,
        )
        repository.save_search_result(
            result_id=str(uuid4()),
            entity_type=message.entity_type,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            result=result.payload,
            searched_at=utc_now(),
        )
        if message.entity_type == "label":
            propagate_ai_flag(
                repository,
                entity_type="label",
                entity_id=message.entity_id,
                result=LabelSearchResult.model_validate(result.payload),
                threshold=settings.ai_flag_confidence_threshold,
            )
        log_event(
            "INFO",
            "label_search_completed"
            if message.entity_type == "label"
            else "entity_search_completed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
            status_code=200,
        )
        return True
    except Exception as exc:
        is_permanent = isinstance(
            exc, (ValueError, TypeError, KeyError, NotImplementedError)
        )
        error_code = (
            "search_permanent_failure"
            if is_permanent
            else "search_transient_failure"
        )
        log_event(
            "ERROR",
            "label_search_failed"
            if message.entity_type == "label"
            else "entity_search_failed",
            correlation_id=correlation_id,
            entity_id=message.entity_id,
            error_code=error_code,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            status_code=500,
        )
        if is_permanent:
            return False
        raise


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

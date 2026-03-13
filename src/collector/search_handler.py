"""SQS worker that performs AI-powered label research via Perplexity."""

from __future__ import annotations

from typing import Any, Mapping
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .repositories import create_clouder_repository_from_env, utc_now
from .schemas import LabelSearchMessage, validation_error_message
from .search.perplexity_client import search_label
from .search.prompts import get_prompt
from .settings import get_search_worker_settings


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
            message = LabelSearchMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "search_message_invalid",
                sqs_record_index=index,
                error_code="validation_error",
                error_message=validation_error_message(exc),
            )
            continue

        correlation_id = (
            _extract_message_attribute(record, "correlation_id") or message.label_id
        )

        log_event(
            "INFO",
            "label_search_started",
            correlation_id=correlation_id,
            label_id=message.label_id,
            label_name=message.label_name,
            styles=message.styles,
            prompt_slug=message.prompt_slug,
            prompt_version=message.prompt_version,
        )

        try:
            prompt_config = get_prompt(message.prompt_slug, message.prompt_version)

            result = search_label(
                label_name=message.label_name,
                style=message.styles,
                config=prompt_config,
                api_key=settings.perplexity_api_key,
            )

            repository.save_search_result(
                result_id=str(uuid4()),
                entity_type="label",
                entity_id=message.label_id,
                prompt_slug=message.prompt_slug,
                prompt_version=message.prompt_version,
                result=result.model_dump(),
                searched_at=utc_now(),
            )
            processed += 1

            log_event(
                "INFO",
                "label_search_completed",
                correlation_id=correlation_id,
                label_id=message.label_id,
                label_name=message.label_name,
                prompt_slug=message.prompt_slug,
                prompt_version=message.prompt_version,
                status_code=200,
            )
        except Exception as exc:
            is_permanent = isinstance(exc, (ValueError, TypeError, KeyError))
            error_code = (
                "search_permanent_failure"
                if is_permanent
                else "search_transient_failure"
            )
            log_event(
                "ERROR",
                "label_search_failed",
                correlation_id=correlation_id,
                label_id=message.label_id,
                label_name=message.label_name,
                error_code=error_code,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
                status_code=500,
            )
            if is_permanent:
                continue
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

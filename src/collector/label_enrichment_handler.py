"""SQS-driven Lambda that enriches a single label per invocation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .data_api import create_default_data_api_client
from .label_enrichment.messages import LabelEnrichmentMessage
from .label_enrichment.orchestrator import (
    build_adapters_from_run_config,
    enrich_label_for_run,
)
from .label_enrichment.prompts import get_prompt, load_builtin_prompts
from .label_enrichment.repository import LabelEnrichmentRepository
from .label_enrichment.settings_provider import LabelEnrichmentSecrets
from .logging_utils import log_event
from .settings import get_label_enrichment_worker_settings

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover — module imported lazily in tests
    OpenAI = None  # type: ignore[assignment]


def _build_repository() -> LabelEnrichmentRepository:
    client = create_default_data_api_client()
    if client is None:
        raise RuntimeError("Aurora Data API not configured")
    return LabelEnrichmentRepository(data_api=client)


def _build_merge_client(api_key: str, timeout_s: float):
    if OpenAI is None:
        raise RuntimeError("openai SDK not installed")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=timeout_s)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records") or []
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "label_enrichment_worker_invoked", sqs_record_count=len(records))
    load_builtin_prompts()

    settings = get_label_enrichment_worker_settings()
    repository = _build_repository()
    secrets = LabelEnrichmentSecrets(
        gemini_api_key=settings.gemini_api_key,
        openai_api_key=settings.openai_api_key,
        tavily_api_key=settings.tavily_api_key,
        deepseek_api_key=settings.deepseek_api_key,
    )
    merge_client = _build_merge_client(settings.deepseek_api_key, settings.request_timeout_s)

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            msg = LabelEnrichmentMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "label_enrichment_message_invalid",
                sqs_record_index=index,
                error_message=str(exc)[:500],
            )
            continue

        run_row = repository.get_run(msg.run_id)
        if run_row is None:
            raise RuntimeError(f"run not found: {msg.run_id}")

        vendors = list(run_row.get("vendors") or [])
        models = dict(run_row.get("models") or {})
        adapters = build_adapters_from_run_config(
            vendor_names=vendors,
            models=models,
            secrets=secrets,
            request_timeout_s=settings.request_timeout_s,
        )
        prompt = get_prompt(run_row["prompt_slug"])

        enrich_label_for_run(
            run_id=msg.run_id,
            label_id=msg.label_id,
            label_name=msg.label_name,
            style=msg.style,
            release_name=msg.release_name,
            adapters=adapters,
            merge_client=merge_client,
            merge_model=run_row["merge_model"],
            prompt=prompt,
            repository=repository,
            ai_flag_threshold=settings.ai_flag_confidence_threshold,
        )
        processed += 1
        log_event(
            "INFO",
            "label_enrichment_completed",
            run_id=msg.run_id,
            label_id=msg.label_id,
            label_name=msg.label_name,
        )

    return {"processed": processed}

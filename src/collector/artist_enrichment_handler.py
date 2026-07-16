"""SQS-driven Lambda that enriches a single artist per invocation."""

from __future__ import annotations

import json
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .data_api import create_default_data_api_client
from .artist_enrichment.messages import ArtistEnrichmentMessage
from .artist_enrichment.orchestrator import (
    build_adapters_from_run_config,
    enrich_artist_for_run,
)
from .artist_enrichment.prompts import get_prompt, load_builtin_prompts
from .artist_enrichment.repository import ArtistEnrichmentRepository
from .artist_enrichment.settings_provider import ArtistEnrichmentSecrets
from .logging_utils import log_event
from .settings import get_data_api_settings, get_artist_enrichment_worker_settings
from .social_links import SocialsResolver

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover — module imported lazily in tests
    OpenAI = None  # type: ignore[assignment]


def _build_clients() -> tuple[ArtistEnrichmentRepository, Any]:
    settings = get_data_api_settings()
    if not settings.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    from .artist_enrichment.auto_repository import AutoEnrichRepository  # lazy — not in 1A
    return ArtistEnrichmentRepository(data_api=client), AutoEnrichRepository(data_api=client)


def _build_merge_client(api_key: str, timeout_s: float):
    if OpenAI is None:
        raise RuntimeError("openai SDK not installed")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=timeout_s)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records") or []
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "artist_enrichment_worker_invoked", sqs_record_count=len(records))
    load_builtin_prompts()

    settings = get_artist_enrichment_worker_settings()
    repository, auto_repository = _build_clients()
    secrets = ArtistEnrichmentSecrets(
        gemini_api_key=settings.gemini_api_key,
        openai_api_key=settings.openai_api_key,
        tavily_api_key=settings.tavily_api_key,
        deepseek_api_key=settings.deepseek_api_key,
    )
    merge_client = _build_merge_client(settings.deepseek_api_key, settings.request_timeout_s)
    socials_resolver = (
        SocialsResolver(settings.tavily_api_key) if settings.tavily_api_key else None
    )

    processed = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            msg = ArtistEnrichmentMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "artist_enrichment_message_invalid",
                sqs_record_index=index,
                error_message=str(exc)[:500],
            )
            continue

        run_row = repository.get_run(msg.run_id)
        if run_row is None:
            raise RuntimeError(f"run not found: {msg.run_id}")

        # Data API returns JSONB columns as JSON-encoded strings, while
        # tests pass Python list/dict directly — handle both shapes.
        vendors_raw = run_row.get("vendors") or []
        models_raw = run_row.get("models") or {}
        vendors = json.loads(vendors_raw) if isinstance(vendors_raw, str) else list(vendors_raw)
        models = json.loads(models_raw) if isinstance(models_raw, str) else dict(models_raw)
        adapters = build_adapters_from_run_config(
            vendor_names=vendors,
            models=models,
            secrets=secrets,
            request_timeout_s=settings.request_timeout_s,
            openai_max_tool_calls=settings.openai_max_tool_calls,
            openai_reasoning_effort=settings.openai_reasoning_effort,
        )
        prompt = get_prompt(run_row["prompt_slug"])

        enrich_artist_for_run(
            run_id=msg.run_id,
            artist_id=msg.artist_id,
            artist_name=msg.artist_name,
            adapters=adapters,
            merge_client=merge_client,
            merge_model=run_row["merge_model"],
            prompt=prompt,
            repository=repository,
            ai_flag_threshold=settings.ai_flag_confidence_threshold,
            on_outcome=auto_repository.mark_auto_enrich_outcome,
            socials_resolver=socials_resolver,
        )
        processed += 1
        log_event(
            "INFO",
            "artist_enrichment_completed",
            run_id=msg.run_id,
            artist_id=msg.artist_id,
            artist_name=msg.artist_name,
        )

    return {"processed": processed}

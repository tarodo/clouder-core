"""PerplexityLabelEnricher — EnrichProvider adapter over search_label()."""

from __future__ import annotations

from typing import Any

from ...search.perplexity_client import search_label
from ...search.prompts import get_prompt
from ..base import EnrichResult


class PerplexityLabelEnricher:
    vendor_name = "perplexity_label"
    entity_types = ("label",)
    prompt_slug = "label_info"
    prompt_version = "v1"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def enrich(
        self,
        entity_type: str,
        entity_id: str,
        context: dict[str, Any],
        correlation_id: str,
    ) -> EnrichResult:
        if entity_type != "label":
            raise ValueError(
                f"PerplexityLabelEnricher supports entity_type=label, got {entity_type}"
            )

        label_name = str(context.get("label_name", "")).strip()
        styles = str(context.get("styles", "")).strip()
        if not label_name:
            raise ValueError("context.label_name is required")
        if not styles:
            raise ValueError("context.styles is required")

        config = get_prompt(self.prompt_slug, self.prompt_version)
        result = search_label(
            label_name=label_name,
            style=styles,
            config=config,
            api_key=self._api_key,
        )
        return EnrichResult(
            entity_type=entity_type,
            entity_id=entity_id,
            prompt_slug=self.prompt_slug,
            prompt_version=self.prompt_version,
            payload=result.model_dump(),
        )

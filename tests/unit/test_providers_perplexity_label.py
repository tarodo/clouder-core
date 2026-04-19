"""Unit tests for PerplexityLabelEnricher adapter."""
from __future__ import annotations

from typing import Any

import pytest

from collector.providers.base import EnrichProvider, EnrichResult
from collector.providers.perplexity.label import PerplexityLabelEnricher
from collector.search.schemas import AIContentStatus, LabelSearchResult


def _make_label_result() -> LabelSearchResult:
    return LabelSearchResult(
        label_name="Foo Records",
        style="Techno",
        size="small",
        size_details="100 releases",
        age="established",
        age_details="Founded 2010",
        ai_content=AIContentStatus.NONE_DETECTED,
        ai_content_details="No AI content",
        summary="A small techno label",
        confidence=0.85,
    )


def test_enricher_implements_protocol() -> None:
    enricher = PerplexityLabelEnricher(api_key="key")
    assert isinstance(enricher, EnrichProvider)
    assert enricher.vendor_name == "perplexity_label"
    assert enricher.entity_types == ("label",)
    assert enricher.prompt_slug == "label_info"


def test_enricher_calls_search_label(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(label_name: str, style: str, config: Any, api_key: str) -> LabelSearchResult:
        captured["label_name"] = label_name
        captured["style"] = style
        captured["api_key"] = api_key
        captured["prompt_slug"] = config.slug
        return _make_label_result()

    monkeypatch.setattr(
        "collector.providers.perplexity.label.search_label", fake_search
    )

    enricher = PerplexityLabelEnricher(api_key="my-key")
    result = enricher.enrich(
        entity_type="label",
        entity_id="lbl-1",
        context={"label_name": "FooRec", "styles": "Techno"},
        correlation_id="corr",
    )

    assert isinstance(result, EnrichResult)
    assert result.entity_id == "lbl-1"
    assert result.prompt_slug == "label_info"
    assert result.payload["confidence"] == 0.85
    assert captured == {
        "label_name": "FooRec",
        "style": "Techno",
        "api_key": "my-key",
        "prompt_slug": "label_info",
    }


def test_enricher_rejects_non_label_entity() -> None:
    enricher = PerplexityLabelEnricher(api_key="k")
    with pytest.raises(ValueError, match="entity_type=label"):
        enricher.enrich(
            entity_type="track",
            entity_id="x",
            context={},
            correlation_id="c",
        )


def test_enricher_validates_context() -> None:
    enricher = PerplexityLabelEnricher(api_key="k")
    with pytest.raises(ValueError, match="label_name"):
        enricher.enrich(
            entity_type="label",
            entity_id="x",
            context={"styles": "Techno"},
            correlation_id="c",
        )

# tests/unit/test_label_enrichment_messages.py
import pytest
from pydantic import ValidationError

from collector.label_enrichment.messages import (
    EnrichLabelInput,
    EnrichLabelsRequestIn,
    LabelEnrichmentMessage,
)


def test_message_round_trip():
    msg = LabelEnrichmentMessage.model_validate({
        "run_id": "r1", "label_id": "l1",
        "label_name": "Drumcode", "style": "techno",
        "release_name": None,
    })
    assert msg.run_id == "r1"
    assert msg.release_name is None


def test_request_minimal_valid():
    req = EnrichLabelsRequestIn.model_validate({
        "labels": [{"label_name": "Drumcode", "style": "techno"}],
        "vendors": ["gemini"],
        "models": {"gemini": "gemini-3-flash-preview"},
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    })
    assert len(req.labels) == 1
    assert req.vendors == ["gemini"]


def test_request_rejects_unknown_vendor():
    with pytest.raises(ValidationError):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": "x", "style": "y"}],
            "vendors": ["anthropic"],
            "models": {"anthropic": "claude"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


def test_request_rejects_label_list_overflow():
    with pytest.raises(ValidationError):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": str(i), "style": "y"} for i in range(101)],
            "vendors": ["gemini"],
            "models": {"gemini": "x"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


def test_request_rejects_missing_model_for_vendor():
    with pytest.raises(ValidationError, match="model missing for vendor"):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": "x", "style": "y"}],
            "vendors": ["gemini", "openai"],
            "models": {"gemini": "g"},  # openai missing
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })

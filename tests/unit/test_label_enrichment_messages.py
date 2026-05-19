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
    })
    assert msg.run_id == "r1"
    assert msg.label_id == "l1"
    assert msg.label_name == "Drumcode"
    assert msg.style == "techno"


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


def test_request_accepts_label_id_without_style():
    req = EnrichLabelsRequestIn.model_validate({
        "labels": [{"label_id": "lbl-1"}],
        "vendors": ["gemini"],
        "models": {"gemini": "x"},
        "prompt_slug": "label_v3_app_fields",
        "prompt_version": "v1",
        "merge_vendor": "deepseek",
        "merge_model": "deepseek-v4-flash",
    })
    assert req.labels[0].label_id == "lbl-1"
    assert req.labels[0].label_name is None
    assert req.labels[0].style is None


def test_request_rejects_label_name_without_style():
    with pytest.raises(ValidationError, match="style is required"):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{"label_name": "Drumcode"}],
            "vendors": ["gemini"],
            "models": {"gemini": "x"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


def test_request_rejects_empty_label():
    with pytest.raises(ValidationError, match="either label_id or label_name"):
        EnrichLabelsRequestIn.model_validate({
            "labels": [{}],
            "vendors": ["gemini"],
            "models": {"gemini": "x"},
            "prompt_slug": "label_v3_app_fields",
            "prompt_version": "v1",
            "merge_vendor": "deepseek",
            "merge_model": "deepseek-v4-flash",
        })


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

import pytest
from pydantic import ValidationError

from collector.label_enrichment.auto_messages import AutoEnrichConfigIn


def test_disabled_config_allows_empty_fields():
    cfg = AutoEnrichConfigIn.model_validate({"enabled": False})
    assert cfg.enabled is False
    assert cfg.vendors == []
    assert cfg.models == {}


def test_enabled_requires_vendors():
    with pytest.raises(ValidationError, match="vendors required"):
        AutoEnrichConfigIn.model_validate({"enabled": True, "vendors": []})


def test_enabled_requires_model_per_vendor():
    with pytest.raises(ValidationError, match="model missing for vendor 'gemini'"):
        AutoEnrichConfigIn.model_validate({
            "enabled": True, "vendors": ["gemini"], "models": {},
            "prompt_slug": "s", "prompt_version": "v", "merge_model": "m",
        })


def test_enabled_requires_prompt_and_merge_model():
    with pytest.raises(ValidationError, match="prompt required"):
        AutoEnrichConfigIn.model_validate({
            "enabled": True, "vendors": ["gemini"],
            "models": {"gemini": "g"}, "merge_model": "m",
        })


def test_enabled_full_config_ok():
    cfg = AutoEnrichConfigIn.model_validate({
        "enabled": True, "vendors": ["gemini", "openai"],
        "models": {"gemini": "g", "openai": "o"},
        "prompt_slug": "label_v3", "prompt_version": "v1",
        "merge_vendor": "deepseek", "merge_model": "deepseek-v4-flash",
    })
    assert cfg.vendors == ["gemini", "openai"]
    assert cfg.merge_vendor == "deepseek"

import os

import pytest

from collector.settings import (
    LabelEnrichmentWorkerSettings,
    get_label_enrichment_worker_settings,
    reset_settings_cache,
)


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    for key in (
        "GEMINI_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY", "DEEPSEEK_API_KEY",
        "AI_FLAG_CONFIDENCE_THRESHOLD",
        "GEMINI_API_KEY_SECRET_ARN", "OPENAI_API_KEY_SECRET_ARN",
        "TAVILY_API_KEY_SECRET_ARN", "DEEPSEEK_API_KEY_SECRET_ARN",
    ):
        monkeypatch.delenv(key, raising=False)
    reset_settings_cache()
    yield
    reset_settings_cache()


def test_settings_resolve_from_direct_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("TAVILY_API_KEY", "t")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    s = get_label_enrichment_worker_settings()
    assert s.gemini_api_key == "g"
    assert s.openai_api_key == "o"
    assert s.tavily_api_key == "t"
    assert s.deepseek_api_key == "d"
    assert s.ai_flag_confidence_threshold == 0.5
    assert s.request_timeout_s == 120.0


def test_threshold_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("TAVILY_API_KEY", "x")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "x")
    monkeypatch.setenv("AI_FLAG_CONFIDENCE_THRESHOLD", "0.75")
    s = get_label_enrichment_worker_settings()
    assert s.ai_flag_confidence_threshold == 0.75

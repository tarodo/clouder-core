import pytest

from lab.config import Settings, available_vendor_names


def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    s = Settings()
    assert s.anthropic_model == "claude-sonnet-4-6"
    assert s.xai_model == "grok-4"
    assert s.perplexity_model == "sonar"
    assert s.concurrency == 4
    assert s.request_timeout == 60


def test_available_vendor_names(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("PERPLEXITY_API_KEY", "y")
    s = Settings()
    assert available_vendor_names(s) == ["anthropic", "perplexity"]

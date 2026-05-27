import pytest

from artlab.config import Settings, available_vendor_names

_KEY_ENVS = [
    "ANTHROPIC_API_KEY", "XAI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY",
    "TAVILY_API_KEY", "DEEPSEEK_API_KEY", "PERPLEXITY_API_KEY",
    "MOONSHOT_API_KEY", "KIMI_API_KEY",
]
_MODEL_ENVS = [
    "ANTHROPIC_MODEL", "XAI_MODEL", "GEMINI_MODEL", "OPENAI_MODEL",
    "DEEPSEEK_MODEL", "PERPLEXITY_MODEL", "KIMI_MODEL",
    "CONCURRENCY", "REQUEST_TIMEOUT",
]


@pytest.fixture
def clean_env(monkeypatch):
    for k in _KEY_ENVS + _MODEL_ENVS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_default_openai_model_is_gpt54_mini(clean_env):
    s = Settings(_env_file=None)
    assert s.openai_model == "gpt-5.4-mini"
    assert s.concurrency == 8
    assert s.request_timeout == 180


def test_available_vendor_names_empty(clean_env):
    s = Settings(_env_file=None)
    assert available_vendor_names(s) == []


def test_available_vendor_names_with_keys(clean_env):
    s = Settings(_env_file=None, openai_api_key="x", gemini_api_key="y")
    names = available_vendor_names(s)
    assert "openai" in names
    assert "gemini" in names


def test_tavily_deepseek_requires_both_keys(clean_env):
    s1 = Settings(_env_file=None, tavily_api_key="t")
    assert "tavily_deepseek" not in available_vendor_names(s1)
    s2 = Settings(_env_file=None, tavily_api_key="t", deepseek_api_key="d")
    assert "tavily_deepseek" in available_vendor_names(s2)

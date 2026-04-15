from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from collector.settings import get_api_settings, reset_settings_cache


def test_api_settings_require_raw_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAW_BUCKET_NAME", raising=False)
    reset_settings_cache()

    with pytest.raises(ValidationError):
        get_api_settings()

    reset_settings_cache()


def test_perplexity_api_key_resolved_from_secret_arn(monkeypatch):
    """When env var is absent but *_SECRET_ARN is set, fetch from SecretsManager."""
    from collector import settings as s

    calls = {"n": 0, "arn": None}

    def fake_fetch(arn: str) -> str:
        calls["n"] += 1
        calls["arn"] = arn
        return "pplx-secret-value"

    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:p-abc",
    )
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setattr(s, "_fetch_secret_string", fake_fetch)

    if hasattr(s, "reset_settings_cache"):
        s.reset_settings_cache()
    if hasattr(s, "_fetch_secret_string") and hasattr(
        s._fetch_secret_string, "cache_clear"
    ):
        s._fetch_secret_string.cache_clear()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "pplx-secret-value"
    assert calls["n"] == 1
    assert calls["arn"] == "arn:aws:secretsmanager:us-east-1:123:secret:p-abc"

    s.reset_settings_cache()


def test_perplexity_direct_env_var_wins_over_secret_arn(monkeypatch):
    from collector import settings as s

    monkeypatch.setenv("PERPLEXITY_API_KEY", "direct-key")
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:p-abc",
    )

    def must_not_call(_arn: str) -> str:
        raise AssertionError("should not fetch when direct env var set")

    monkeypatch.setattr(s, "_fetch_secret_string", must_not_call)

    if hasattr(s, "reset_settings_cache"):
        s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "direct-key"

    s.reset_settings_cache()


def test_spotify_credentials_resolved_from_secret_arn(monkeypatch):
    """Spotify creds stored as JSON {client_id, client_secret} in Secrets Manager."""
    from collector import settings as s

    def fake_fetch(arn: str) -> str:
        assert "spotify" in arn.lower() or "SpotifyCreds" in arn
        return json.dumps({"client_id": "cid", "client_secret": "csecret"})

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv(
        "SPOTIFY_CREDENTIALS_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:SpotifyCreds-xyz",
    )
    monkeypatch.setattr(s, "_fetch_secret_string", fake_fetch)
    if hasattr(s, "reset_settings_cache"):
        s.reset_settings_cache()
    if hasattr(s, "_fetch_secret_string") and hasattr(
        s._fetch_secret_string, "cache_clear"
    ):
        s._fetch_secret_string.cache_clear()

    settings = s.get_spotify_worker_settings()
    assert settings.spotify_client_id == "cid"
    assert settings.spotify_client_secret == "csecret"

    s.reset_settings_cache()

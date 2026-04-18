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


def test_spotify_malformed_json_raises_clear_error(monkeypatch):
    from collector import settings as s

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv(
        "SPOTIFY_CREDENTIALS_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:SpotifyCreds-xyz",
    )
    monkeypatch.setattr(s, "_fetch_secret_string", lambda _arn: "not json at all")
    if hasattr(s, "reset_settings_cache"):
        s.reset_settings_cache()

    with pytest.raises(RuntimeError, match="not valid JSON"):
        s.get_spotify_worker_settings()

    s.reset_settings_cache()


def test_spotify_json_must_be_object(monkeypatch):
    from collector import settings as s

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv(
        "SPOTIFY_CREDENTIALS_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:SpotifyCreds-xyz",
    )
    monkeypatch.setattr(
        s, "_fetch_secret_string", lambda _arn: '["not", "an", "object"]'
    )
    if hasattr(s, "reset_settings_cache"):
        s.reset_settings_cache()

    with pytest.raises(RuntimeError, match="must be an object"):
        s.get_spotify_worker_settings()

    s.reset_settings_cache()


def test_perplexity_resolved_from_ssm_when_env_absent(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("PERPLEXITY_API_KEY_SECRET_ARN", raising=False)
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    fetched = {"names": []}

    def fake_ssm(name: str) -> str:
        fetched["names"].append(name)
        return "pplx-ssm-value"

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "pplx-ssm-value"
    assert fetched["names"] == ["/clouder/perplexity/api_key"]

    s.reset_settings_cache()


def test_perplexity_direct_env_wins_over_ssm(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.setenv("PERPLEXITY_API_KEY", "direct-key")
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    def must_not_call(_name: str) -> str:
        raise AssertionError("should not fetch SSM when direct env set")

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", must_not_call)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "direct-key"

    s.reset_settings_cache()


def test_perplexity_ssm_wins_over_secrets_manager_fallback(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SECRET_ARN",
        "arn:aws:secretsmanager:us-east-1:123:secret:p-abc",
    )
    monkeypatch.setenv(
        "PERPLEXITY_API_KEY_SSM_PARAMETER", "/clouder/perplexity/api_key"
    )

    def fake_ssm(_name: str) -> str:
        return "ssm-wins"

    def must_not_call(_arn: str) -> str:
        raise AssertionError("should not fall back to Secrets Manager when SSM set")

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    monkeypatch.setattr(s, "_fetch_secret_string", must_not_call)
    s.reset_settings_cache()

    settings = s.get_search_worker_settings()
    assert settings.perplexity_api_key == "ssm-wins"

    s.reset_settings_cache()


def test_spotify_creds_from_ssm(monkeypatch):
    from collector import settings as s
    from collector import secrets

    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv(
        "SPOTIFY_CLIENT_ID_SSM_PARAMETER", "/clouder/spotify/client_id"
    )
    monkeypatch.setenv(
        "SPOTIFY_CLIENT_SECRET_SSM_PARAMETER", "/clouder/spotify/client_secret"
    )

    def fake_ssm(name: str) -> str:
        return {
            "/clouder/spotify/client_id": "cid-ssm",
            "/clouder/spotify/client_secret": "csecret-ssm",
        }[name]

    monkeypatch.setattr(secrets, "_fetch_ssm_parameter", fake_ssm)
    s.reset_settings_cache()

    settings = s.get_spotify_worker_settings()
    assert settings.spotify_client_id == "cid-ssm"
    assert settings.spotify_client_secret == "csecret-ssm"

    s.reset_settings_cache()

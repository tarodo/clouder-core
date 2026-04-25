from __future__ import annotations

import pytest

from collector.auth import auth_settings as mod


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    mod.reset_auth_settings_cache()
    yield
    mod.reset_auth_settings_cache()


def test_admin_ids_parsed_to_set(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "alice, bob ,charlie")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/,/dashboard")

    settings = mod.get_auth_settings()

    assert settings.admin_spotify_ids == {"alice", "bob", "charlie"}
    assert settings.is_admin("alice") is True
    assert settings.is_admin("dave") is False


def test_default_token_ttls(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")

    settings = mod.get_auth_settings()

    assert settings.access_token_ttl_seconds == 1800
    assert settings.refresh_token_ttl_seconds == 604800


def test_overridden_ttls(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("JWT_ACCESS_TOKEN_TTL_SECONDS", "60")
    monkeypatch.setenv("JWT_REFRESH_TOKEN_TTL_SECONDS", "120")

    settings = mod.get_auth_settings()

    assert settings.access_token_ttl_seconds == 60
    assert settings.refresh_token_ttl_seconds == 120


def test_allowed_redirect_check(monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://x/cb")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard, /me")

    settings = mod.get_auth_settings()

    assert settings.allows_redirect("/") is True
    assert settings.allows_redirect("/dashboard") is True
    assert settings.allows_redirect("/evil") is False


def test_resolve_jwt_signing_key_via_env(monkeypatch) -> None:
    monkeypatch.setenv("JWT_SIGNING_KEY", "raw-secret-32-bytes-here-please-ok")

    assert mod.resolve_jwt_signing_key() == "raw-secret-32-bytes-here-please-ok"


def test_resolve_jwt_signing_key_via_ssm(monkeypatch) -> None:
    monkeypatch.delenv("JWT_SIGNING_KEY", raising=False)
    monkeypatch.setenv("JWT_SIGNING_KEY_SSM_PARAMETER", "/clouder/auth/jwt_signing_key")

    fetched = {}

    def fake_fetch(name: str) -> str:
        fetched["name"] = name
        return "from-ssm"

    monkeypatch.setattr("collector.secrets._fetch_ssm_parameter", fake_fetch)

    assert mod.resolve_jwt_signing_key() == "from-ssm"
    assert fetched["name"] == "/clouder/auth/jwt_signing_key"


def test_resolve_oauth_client_credentials_env(monkeypatch) -> None:
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid-env")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec-env")

    cid, csec = mod.resolve_oauth_client_credentials()
    assert cid == "cid-env"
    assert csec == "csec-env"


def test_resolve_oauth_client_credentials_ssm(monkeypatch) -> None:
    monkeypatch.delenv("SPOTIFY_OAUTH_CLIENT_ID", raising=False)
    monkeypatch.delenv("SPOTIFY_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID_SSM_PARAMETER", "/c/id")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET_SSM_PARAMETER", "/c/secret")

    fetched = []

    def fake_fetch(name: str) -> str:
        fetched.append(name)
        return {"/c/id": "cid-ssm", "/c/secret": "csec-ssm"}[name]

    monkeypatch.setattr("collector.secrets._fetch_ssm_parameter", fake_fetch)

    cid, csec = mod.resolve_oauth_client_credentials()
    assert cid == "cid-ssm"
    assert csec == "csec-ssm"
    assert sorted(fetched) == ["/c/id", "/c/secret"]

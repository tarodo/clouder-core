from __future__ import annotations

import json
import urllib.parse
from types import SimpleNamespace

import pytest

from collector.auth import auth_settings
from collector.auth_handler import lambda_handler


def _event(query: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-login",
            "routeKey": "GET /auth/login",
        },
        "headers": {"x-correlation-id": "cid-login"},
        "queryStringParameters": query,
        "body": None,
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/, /dashboard")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def test_login_returns_302_with_state_and_verifier_cookies() -> None:
    response = lambda_handler(_event(), SimpleNamespace(aws_request_id="L"))

    assert response["statusCode"] == 302
    location = response["headers"]["location"]
    assert location.startswith("https://accounts.spotify.com/authorize?")

    parsed = urllib.parse.urlparse(location)
    qs = urllib.parse.parse_qs(parsed.query)
    assert qs["client_id"] == ["cid"]
    assert qs["redirect_uri"] == ["https://app.x/auth/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["code_challenge_method"] == ["S256"]
    assert "code_challenge" in qs
    assert "state" in qs
    assert "user-read-email" in qs["scope"][0]
    assert "streaming" in qs["scope"][0]

    cookies = response.get("cookies") or []
    cookie_pairs = {c.split("=")[0]: c for c in cookies}
    assert "oauth_state" in cookie_pairs
    assert "oauth_verifier" in cookie_pairs
    assert "HttpOnly" in cookie_pairs["oauth_state"]
    assert "Secure" in cookie_pairs["oauth_state"]
    assert "SameSite=Lax" in cookie_pairs["oauth_state"]


def test_login_rejects_unknown_redirect_uri() -> None:
    response = lambda_handler(
        _event({"redirect_uri": "/evil"}),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_login_unknown_route_returns_404() -> None:
    event = _event()
    event["requestContext"]["routeKey"] = "GET /unknown"
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 404

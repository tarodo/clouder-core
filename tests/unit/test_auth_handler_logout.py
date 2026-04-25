from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.jwt_utils import issue_refresh_token
from collector import auth_handler


SECRET = "0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _event(*, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "POST /auth/logout"},
        "headers": {"x-correlation-id": "cid"},
        "cookies": cookies,
        "body": "",
    }


def test_logout_revokes_session_and_clears_cookie(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_refresh_token(
        secret=SECRET, user_id="u", session_id="s", ttl_seconds=600, now=now,
    )
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={token}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_called_once_with("s", revoked_at=now)
    cookies = response.get("cookies") or []
    assert any(c.startswith("refresh_token=;") and "Max-Age=0" in c for c in cookies)


def test_logout_without_cookie_still_returns_204(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=[]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_not_called()


def test_logout_invalid_token_silently_succeeds(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(cookies=["refresh_token=garbage"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_not_called()

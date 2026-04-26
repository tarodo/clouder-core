from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import UserRow
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyOAuthError,
    SpotifyProfile,
    SpotifyTokenSet,
)
from collector import auth_handler


def _event(*, code: str, state: str, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "GET /auth/callback"},
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": {"code": code, "state": state},
        "cookies": cookies,
        "body": None,
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "sp-admin")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", "0" * 32)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _wire(monkeypatch, *, oauth, repo, envelope, now):
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: envelope)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def test_callback_premium_user_creates_session_and_returns_jwt(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600,
        scope="user-read-email",
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-user", display_name="Roman", email="r@x", product="premium",
    )
    repo = MagicMock()
    envelope = MagicMock()
    envelope.encrypt.return_value = EnvelopePayload(
        data_key_enc=b"K", nonce=b"n" * 12, ciphertext=b"C",
    )
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["spotify_access_token"] == "AT"
    assert body["expires_in"] == 1800
    assert body["user"]["spotify_id"] == "sp-user"
    assert body["user"]["is_admin"] is False
    assert "access_token" in body

    cookies = response.get("cookies") or []
    refresh_cookie = next(c for c in cookies if c.startswith("refresh_token="))
    assert "HttpOnly" in refresh_cookie
    assert "Secure" in refresh_cookie
    assert "SameSite=Strict" in refresh_cookie
    assert "Path=/auth/refresh" in refresh_cookie

    repo.upsert_user.assert_called_once()
    repo.create_session.assert_called_once()
    repo.upsert_vendor_token.assert_called_once()


def test_callback_admin_user_gets_is_admin_true(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600, scope=None,
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-admin", display_name=None, email=None, product="premium",
    )
    repo = MagicMock()
    envelope = MagicMock()
    envelope.encrypt.return_value = EnvelopePayload(
        data_key_enc=b"K", nonce=b"n" * 12, ciphertext=b"C",
    )
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    body = json.loads(response["body"])
    assert body["user"]["is_admin"] is True
    upsert_cmd = repo.upsert_user.call_args.args[0]
    assert upsert_cmd.is_admin is True


def test_callback_non_premium_returns_403_without_db_writes(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.return_value = SpotifyTokenSet(
        access_token="AT", refresh_token="RT", expires_in=3600, scope=None,
    )
    oauth.get_me.return_value = SpotifyProfile(
        spotify_id="sp-free", display_name="Free", email="f@x", product="free",
    )
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "premium_required"
    assert body["upgrade_url"].startswith("https://")
    repo.upsert_user.assert_not_called()
    repo.create_session.assert_not_called()
    repo.upsert_vendor_token.assert_not_called()


def test_callback_state_mismatch_returns_400(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="WRONG", cookies=["oauth_state=RIGHT", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "csrf_state_mismatch"
    oauth.exchange_code.assert_not_called()


def test_callback_oauth_exchange_failure_returns_502(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    oauth = MagicMock()
    oauth.exchange_code.side_effect = SpotifyOAuthError("boom")
    repo = MagicMock()
    envelope = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(code="X", state="STATE", cookies=["oauth_state=STATE", "oauth_verifier=V"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 502
    body = json.loads(response["body"])
    assert body["error_code"] == "oauth_exchange_failed"

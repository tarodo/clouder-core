from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import SessionRow, VendorTokenRow
from collector.auth.jwt_utils import issue_refresh_token
from collector.auth.kms_envelope import EnvelopePayload
from collector.auth.spotify_oauth import (
    SpotifyTokenRevokedError,
    SpotifyTokenSet,
)
from collector import auth_handler


SECRET = "0" * 32


def _event(*, cookies: list[str]) -> dict:
    return {
        "version": "2.0",
        "requestContext": {"requestId": "req", "routeKey": "POST /auth/refresh"},
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": None,
        "cookies": cookies,
        "body": "",
    }


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


def _wire(monkeypatch, *, oauth, repo, envelope, now):
    monkeypatch.setattr(auth_handler, "_build_oauth_client", lambda: oauth)
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_build_kms_envelope", lambda: envelope)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)


def _refresh_jwt(now: datetime, *, user_id: str = "u-1", session_id: str = "s-1") -> str:
    return issue_refresh_token(
        secret=SECRET,
        user_id=user_id,
        session_id=session_id,
        ttl_seconds=604800,
        now=now,
    )


def _stored_session(now: datetime, *, hash_str: str) -> SessionRow:
    return SessionRow(
        id="s-1", user_id="u-1", refresh_token_hash=hash_str,
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=(now + timedelta(days=7)).isoformat(),
        revoked_at=None,
    )


def _vendor_token(now: datetime) -> VendorTokenRow:
    return VendorTokenRow(
        user_id="u-1", vendor="spotify",
        access_token_enc=EnvelopePayload(b"K", b"n" * 12, b"OLD-AT").serialize(),
        refresh_token_enc=EnvelopePayload(b"K", b"n" * 12, b"OLD-RT").serialize(),
        data_key_enc=b"K", scope=None,
        expires_at=now.isoformat(), updated_at=now.isoformat(),
    )


def test_refresh_happy_path_rotates_tokens(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = _stored_session(
        now, hash_str=hashlib.sha256(refresh.encode()).hexdigest()
    )
    repo.get_vendor_token.return_value = _vendor_token(now)

    envelope = MagicMock()
    envelope.decrypt.return_value = b"OLD-RT"
    envelope.encrypt.return_value = EnvelopePayload(b"K2", b"n" * 12, b"NEW")

    oauth = MagicMock()
    oauth.refresh.return_value = SpotifyTokenSet(
        access_token="NEW-AT", refresh_token="NEW-RT", expires_in=3600, scope=None,
    )

    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["spotify_access_token"] == "NEW-AT"
    assert "access_token" in body

    repo.rotate_session.assert_called_once()
    rotate_kwargs = repo.rotate_session.call_args.kwargs
    assert rotate_kwargs["session_id"] == "s-1"
    assert rotate_kwargs["new_hash"] != hashlib.sha256(refresh.encode()).hexdigest()


def test_refresh_missing_cookie_returns_401(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[]), SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_invalid"


def test_refresh_replay_revokes_session_family(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    # Stored hash does NOT match the inbound refresh — replay signal.
    repo.get_active_session.return_value = _stored_session(now, hash_str="WRONG")

    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_replay_detected"
    repo.revoke_all_user_sessions.assert_called_once()


def test_refresh_spotify_invalid_grant_clears_vendor_token(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = _stored_session(
        now, hash_str=hashlib.sha256(refresh.encode()).hexdigest()
    )
    repo.get_vendor_token.return_value = _vendor_token(now)
    envelope = MagicMock()
    envelope.decrypt.return_value = b"OLD-RT"

    oauth = MagicMock()
    oauth.refresh.side_effect = SpotifyTokenRevokedError("invalid_grant")

    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "spotify_revoked"
    repo.revoke_session.assert_called_once()
    repo.delete_vendor_token.assert_called_once()


def test_refresh_session_not_found_returns_401(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    refresh = _refresh_jwt(now)
    repo = MagicMock()
    repo.get_active_session.return_value = None
    envelope = MagicMock()
    oauth = MagicMock()
    _wire(monkeypatch, oauth=oauth, repo=repo, envelope=envelope, now=now)

    response = auth_handler.lambda_handler(
        _event(cookies=[f"refresh_token={refresh}"]),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 401
    body = json.loads(response["body"])
    assert body["error_code"] == "refresh_invalid"

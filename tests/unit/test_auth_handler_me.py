from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector.auth import auth_settings
from collector.auth.auth_repository import SessionRow, UserRow
from collector import auth_handler


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("KMS_USER_TOKENS_KEY_ARN", "arn:k")
    monkeypatch.setenv("SPOTIFY_OAUTH_REDIRECT_URI", "https://app.x/auth/callback")
    monkeypatch.setenv("ALLOWED_FRONTEND_REDIRECTS", "/")
    monkeypatch.setenv("ADMIN_SPOTIFY_IDS", "")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_ID", "cid")
    monkeypatch.setenv("SPOTIFY_OAUTH_CLIENT_SECRET", "csec")
    monkeypatch.setenv("JWT_SIGNING_KEY", "0" * 32)
    auth_settings.reset_auth_settings_cache()
    yield
    auth_settings.reset_auth_settings_cache()


def _event(*, route: str, user_id: str, session_id: str, is_admin: bool,
           path_params: dict | None = None) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route,
            "authorizer": {
                "lambda": {
                    "user_id": user_id,
                    "session_id": session_id,
                    "is_admin": is_admin,
                }
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "pathParameters": path_params,
        "body": None,
    }


def test_get_me_returns_user_and_sessions(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_user_by_id.return_value = UserRow(
        id="u-1", spotify_id="sp-1", display_name="Roman",
        email="r@x", is_admin=False,
        created_at=now.isoformat(), updated_at=now.isoformat(),
    )
    repo.list_active_sessions.return_value = [
        SessionRow(
            id="s-1", user_id="u-1", refresh_token_hash="h",
            user_agent="ua", ip_address="1.2.3.4",
            created_at=now.isoformat(), last_used_at=now.isoformat(),
            expires_at=now.isoformat(), revoked_at=None,
        ),
        SessionRow(
            id="s-2", user_id="u-1", refresh_token_hash="h",
            user_agent=None, ip_address=None,
            created_at=now.isoformat(), last_used_at=now.isoformat(),
            expires_at=now.isoformat(), revoked_at=None,
        ),
    ]
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(route="GET /me", user_id="u-1", session_id="s-1", is_admin=False),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["id"] == "u-1"
    assert body["display_name"] == "Roman"
    assert body["is_admin"] is False
    sessions = body["sessions"]
    assert len(sessions) == 2
    current = next(s for s in sessions if s["id"] == "s-1")
    other = next(s for s in sessions if s["id"] == "s-2")
    assert current["current"] is True
    assert other["current"] is False


def test_delete_session_revokes_non_current(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_active_session.return_value = SessionRow(
        id="s-2", user_id="u-1", refresh_token_hash="h",
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=now.isoformat(), revoked_at=None,
    )
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-2"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 204
    repo.revoke_session.assert_called_once_with("s-2", revoked_at=now)


def test_delete_session_current_returns_400(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-1"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "cannot_revoke_current"
    repo.revoke_session.assert_not_called()


def test_delete_session_belonging_to_other_user_returns_404(monkeypatch) -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    repo = MagicMock()
    repo.get_active_session.return_value = SessionRow(
        id="s-2", user_id="u-OTHER", refresh_token_hash="h",
        user_agent=None, ip_address=None,
        created_at=now.isoformat(), last_used_at=now.isoformat(),
        expires_at=now.isoformat(), revoked_at=None,
    )
    monkeypatch.setattr(auth_handler, "_build_auth_repository", lambda: repo)
    monkeypatch.setattr(auth_handler, "_now", lambda: now)

    response = auth_handler.lambda_handler(
        _event(
            route="DELETE /me/sessions/{session_id}",
            user_id="u-1",
            session_id="s-1",
            is_admin=False,
            path_params={"session_id": "s-2"},
        ),
        SimpleNamespace(aws_request_id="L"),
    )

    assert response["statusCode"] == 404
    repo.revoke_session.assert_not_called()

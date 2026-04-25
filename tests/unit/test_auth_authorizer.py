from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from collector.auth.jwt_utils import issue_access_token
from collector import auth_authorizer


SECRET = "0" * 32


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("JWT_SIGNING_KEY", SECRET)
    auth_authorizer._reset_signing_key_cache()
    monkeypatch.setattr(auth_authorizer, "_now", lambda: datetime(
        2026, 4, 26, 12, 0, tzinfo=timezone.utc
    ))
    yield
    auth_authorizer._reset_signing_key_cache()


def _event(*, header: str | None) -> dict:
    return {
        "type": "REQUEST",
        "routeKey": "GET /me",
        "headers": {"authorization": header} if header is not None else {},
    }


def test_valid_token_authorized() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u-1", session_id="s-1", is_admin=True,
        ttl_seconds=1800, now=now,
    )
    response = auth_authorizer.lambda_handler(
        _event(header=f"Bearer {token}"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {
        "isAuthorized": True,
        "context": {
            "user_id": "u-1",
            "session_id": "s-1",
            "is_admin": True,
        },
    }


def test_missing_authorization_header_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header=None), SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_non_bearer_scheme_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header="Basic xyz"), SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_invalid_token_unauthorized() -> None:
    response = auth_authorizer.lambda_handler(
        _event(header="Bearer not.a.token"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}


def test_wrong_secret_unauthorized() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret="X" * 32, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=1800, now=now,
    )
    response = auth_authorizer.lambda_handler(
        _event(header=f"Bearer {token}"),
        SimpleNamespace(aws_request_id="A"),
    )
    assert response == {"isAuthorized": False}

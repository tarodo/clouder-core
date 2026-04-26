from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from collector.handler import lambda_handler
from collector.providers import registry
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _collect_event(*, is_admin: bool | None) -> dict:
    authorizer: dict | None = None
    if is_admin is not None:
        authorizer = {"lambda": {"user_id": "u", "session_id": "s", "is_admin": is_admin}}
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /collect_bp_releases",
            **({"authorizer": authorizer} if authorizer is not None else {}),
        },
        "headers": {"x-correlation-id": "cid"},
        "body": json.dumps(
            {"bp_token": "x", "style_id": 5, "iso_year": 2026, "iso_week": 9}
        ),
    }


def test_collect_without_authorizer_context_returns_403(monkeypatch) -> None:
    response = lambda_handler(
        _collect_event(is_admin=None),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_collect_non_admin_returns_403(monkeypatch) -> None:
    response = lambda_handler(
        _collect_event(is_admin=False),
        SimpleNamespace(aws_request_id="L"),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_spotify_not_found_route_requires_admin(monkeypatch) -> None:
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /tracks/spotify-not-found",
            "authorizer": {
                "lambda": {"user_id": "u", "session_id": "s", "is_admin": False}
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "body": None,
    }
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 403


def test_list_tracks_does_not_require_admin(monkeypatch) -> None:
    class FakeRepo:
        def list_tracks(self, limit, offset, search):
            return []

        def count_tracks(self, search):
            return 0

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: FakeRepo()
    )

    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /tracks",
            "authorizer": {
                "lambda": {"user_id": "u", "session_id": "s", "is_admin": False}
            },
        },
        "headers": {"x-correlation-id": "cid"},
        "queryStringParameters": None,
        "body": None,
    }
    response = lambda_handler(event, SimpleNamespace(aws_request_id="L"))
    assert response["statusCode"] == 200

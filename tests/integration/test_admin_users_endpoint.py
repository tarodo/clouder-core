"""Integration tests for GET /admin/users."""

from __future__ import annotations

import json

import pytest

from collector import handler
from collector.settings import reset_settings_cache
from collector.providers import registry


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(*, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /admin/users",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/users",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


def test_users_requires_admin():
    response = handler.lambda_handler(_event(is_admin=False), _ctx())
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_users_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(_event(), _ctx())
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert body["error_code"] == "db_not_configured"


def test_users_returns_list(monkeypatch):
    rows = [
        {"id": "u1", "display_name": "Alice"},
        {"id": "u2", "display_name": "Bob"},
    ]

    class FakeRepo:
        def list_users(self):
            return rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(),
    )
    response = handler.lambda_handler(_event(), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["users"] == rows

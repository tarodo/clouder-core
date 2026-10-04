"""Integration tests for PATCH /admin/styles/{style_id}."""

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


def _event(body, *, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "PATCH /admin/styles/{style_id}",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/styles/uuid-bf",
        "pathParameters": {"style_id": "uuid-bf"},
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body) if body is not None else None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, found: bool = True):
        self._found = found
        self.calls: list[tuple[str, bool]] = []

    def set_style_hidden(self, style_id, is_hidden, now):
        self.calls.append((style_id, is_hidden))
        return self._found


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: fake
    )
    return fake


def test_requires_admin(repo):
    response = handler.lambda_handler(
        _event({"is_hidden": True}, is_admin=False), _ctx()
    )
    assert response["statusCode"] == 403
    assert json.loads(response["body"])["error_code"] == "admin_required"
    assert repo.calls == []


@pytest.mark.parametrize("is_hidden", [True, False])
def test_sets_visibility(repo, is_hidden):
    response = handler.lambda_handler(_event({"is_hidden": is_hidden}), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["style_id"] == "uuid-bf"
    assert body["is_hidden"] is is_hidden
    assert repo.calls == [("uuid-bf", is_hidden)]


@pytest.mark.parametrize(
    "body", [None, {}, {"is_hidden": "true"}, {"is_hidden": 1}, ["x"]]
)
def test_rejects_invalid_body(repo, body):
    response = handler.lambda_handler(_event(body), _ctx())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"
    assert repo.calls == []


def test_unknown_style_404(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(found=False),
    )
    response = handler.lambda_handler(_event({"is_hidden": True}), _ctx())
    assert response["statusCode"] == 404
    assert json.loads(response["body"])["error_code"] == "style_not_found"


def test_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(_event({"is_hidden": True}), _ctx())
    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error_code"] == "db_not_configured"

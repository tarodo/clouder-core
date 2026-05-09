"""Integration tests for GET /admin/runs."""

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


def _event(qs: dict[str, str] | None, *, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /admin/runs",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/runs",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


def test_admin_runs_requires_admin():
    response = handler.lambda_handler(
        _event(
            {"style_id": "1", "week_year": "2026", "week_number": "5"},
            is_admin=False,
        ),
        _ctx(),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_admin_runs_missing_param_400():
    # style_id is missing
    response = handler.lambda_handler(
        _event({"week_year": "2026", "week_number": "5"}),
        _ctx(),
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_admin_runs_negative_param_rejected():
    response = handler.lambda_handler(
        _event({"style_id": "-1", "week_year": "2026", "week_number": "5"}),
        _ctx(),
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_admin_runs_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(
        _event({"style_id": "1", "week_year": "2026", "week_number": "5"}),
        _ctx(),
    )
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert body["error_code"] == "db_not_configured"


def test_admin_runs_returns_repo_rows_in_received_order(monkeypatch):
    rows = [
        {
            "run_id": "r2",
            "status": "completed",
            "started_at": "2026-02-03T10:00:00Z",
            "finished_at": "2026-02-03T10:01:00Z",
            "item_count": 100,
            "processed_count": 100,
            "error_code": None,
            "error_message": None,
            "is_custom_range": False,
            "period_start": "2026-01-31",
            "period_end": "2026-02-06",
        },
        {
            "run_id": "r1",
            "status": "failed",
            "started_at": "2026-02-02T10:00:00Z",
            "finished_at": "2026-02-02T10:00:30Z",
            "item_count": 0,
            "processed_count": 0,
            "error_code": "bp_token_invalid",
            "error_message": "Beatport token rejected",
            "is_custom_range": False,
            "period_start": "2026-01-31",
            "period_end": "2026-02-06",
        },
    ]

    class FakeRepo:
        def list_runs_for_cell(self, style_id, week_year, week_number):
            assert (style_id, week_year, week_number) == (1, 2026, 5)
            return rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(),
    )

    response = handler.lambda_handler(
        _event({"style_id": "1", "week_year": "2026", "week_number": "5"}),
        _ctx(),
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert [it["run_id"] for it in body["items"]] == ["r2", "r1"]
    assert body["items"][1]["error_code"] == "bp_token_invalid"
    assert body["items"][0]["is_custom_range"] is False
    assert body["items"][0]["period_start"] == "2026-01-31"

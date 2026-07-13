"""Integration tests for GET /admin/coverage."""

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
            "routeKey": "GET /admin/coverage",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/coverage",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


def test_coverage_requires_admin():
    response = handler.lambda_handler(
        _event({"week_year": "2026"}, is_admin=False), _ctx()
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_coverage_missing_week_year_400():
    response = handler.lambda_handler(_event(None), _ctx())
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def test_coverage_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(_event({"week_year": "2026"}), _ctx())
    assert response["statusCode"] == 503
    body = json.loads(response["body"])
    assert body["error_code"] == "db_not_configured"


def test_coverage_returns_grouped_styles(monkeypatch):
    rows = [
        {
            "clouder_style_id": "uuid-s1",
            "style_name": "Tech House",
            "beatport_style_id": "90",
            "run_id": "r1",
            "week_number": 1,
            "status": "completed",
            "item_count": 147,
            "is_custom_range": False,
            "period_start": "2026-01-03",
            "period_end": "2026-01-09",
            "started_at": "2026-01-04T09:12:00Z",
            "finished_at": "2026-01-04T09:14:00Z",
        },
        {
            "clouder_style_id": "uuid-s1",
            "style_name": "Tech House",
            "beatport_style_id": "90",
            "run_id": None,
            "week_number": None,
            "status": None,
            "item_count": None,
            "is_custom_range": None,
            "period_start": None,
            "period_end": None,
            "started_at": None,
            "finished_at": None,
        },
        {
            "clouder_style_id": "uuid-s2",
            "style_name": "Melodic",
            "beatport_style_id": "131",
            "run_id": "r2",
            "week_number": 4,
            "status": "completed",
            "item_count": 50,
            "is_custom_range": True,
            "period_start": "2026-01-25",
            "period_end": "2026-02-02",
            "started_at": "2026-02-03T10:00:00Z",
            "finished_at": "2026-02-03T10:01:00Z",
        },
    ]

    class FakeRepo:
        def coverage_for_year(self, week_year):
            assert week_year == 2026
            return rows

        def spotify_stats_for_year(self, week_year):
            return []

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: FakeRepo(),
    )
    response = handler.lambda_handler(_event({"week_year": "2026"}), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["week_year"] == 2026
    assert body["weeks_in_year"] == 52
    styles = {s["style_id"]: s for s in body["styles"]}
    assert {90, 131} == set(styles.keys())
    # Row with run_id=None is skipped; style 90 has one cell
    assert len(styles[90]["cells"]) == 1
    assert styles[90]["cells"][0]["week_number"] == 1
    assert styles[131]["cells"][0]["is_custom_range"] is True
    assert styles[90]["style_name"] == "Tech House"
    assert styles[131]["style_name"] == "Melodic"


def test_coverage_merges_spotify_weeks(monkeypatch):
    coverage_rows = [
        {
            "clouder_style_id": "uuid-s1",
            "style_name": "Tech House",
            "beatport_style_id": "90",
            "run_id": "r1",
            "week_number": 1,
            "status": "completed",
            "item_count": 147,
            "is_custom_range": False,
            "period_start": "2026-01-03",
            "period_end": "2026-01-09",
            "started_at": "2026-01-04T09:12:00Z",
            "finished_at": "2026-01-04T09:14:00Z",
        },
        {
            "clouder_style_id": "uuid-s2",
            "style_name": "Melodic",
            "beatport_style_id": "131",
            "run_id": None,
            "week_number": None,
            "status": None,
            "item_count": None,
            "is_custom_range": None,
            "period_start": None,
            "period_end": None,
            "started_at": None,
            "finished_at": None,
        },
    ]
    stats_rows = [
        {
            "beatport_style_id": "90",
            "week_number": 1,
            "total": 50,
            "found": 45,
            "not_found": 3,
            "pending": 1,
            "no_isrc": 1,
        },
        {
            "beatport_style_id": "90",
            "week_number": 2,
            "total": 10,
            "found": 10,
            "not_found": 0,
            "pending": 0,
            "no_isrc": 0,
        },
    ]

    class FakeRepo:
        def coverage_for_year(self, week_year):
            return coverage_rows

        def spotify_stats_for_year(self, week_year):
            assert week_year == 2026
            return stats_rows

    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: FakeRepo()
    )
    response = handler.lambda_handler(_event({"week_year": "2026"}), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    by_id = {s["style_id"]: s for s in body["styles"]}
    assert by_id[90]["spotify_weeks"] == [
        {"week_number": 1, "total": 50, "found": 45, "not_found": 3,
         "pending": 1, "no_isrc": 1},
        {"week_number": 2, "total": 10, "found": 10, "not_found": 0,
         "pending": 0, "no_isrc": 0},
    ]
    assert by_id[131]["spotify_weeks"] == []

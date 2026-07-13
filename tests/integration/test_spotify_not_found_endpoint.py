"""Integration tests for GET /tracks/spotify-not-found date filters."""

from __future__ import annotations

import json
from datetime import date

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
            "routeKey": "GET /tracks/spotify-not-found",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/tracks/spotify-not-found",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self):
        self.find_kwargs = None
        self.count_kwargs = None

    def find_tracks_not_found_on_spotify(self, limit, offset, search=None,
                                         publish_date_from=None,
                                         publish_date_to=None):
        self.find_kwargs = {
            "limit": limit, "offset": offset, "search": search,
            "publish_date_from": publish_date_from,
            "publish_date_to": publish_date_to,
        }
        return []

    def count_tracks_not_found_on_spotify(self, search=None,
                                          publish_date_from=None,
                                          publish_date_to=None):
        self.count_kwargs = {
            "search": search,
            "publish_date_from": publish_date_from,
            "publish_date_to": publish_date_to,
        }
        return 0


def _install(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: repo
    )
    return repo


def test_not_found_passes_date_range(monkeypatch):
    repo = _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "2026-06-01",
                "publish_date_to": "2026-06-30"}),
        _ctx(),
    )
    assert response["statusCode"] == 200
    assert repo.find_kwargs["publish_date_from"] == date(2026, 6, 1)
    assert repo.find_kwargs["publish_date_to"] == date(2026, 6, 30)
    assert repo.count_kwargs["publish_date_from"] == date(2026, 6, 1)


def test_not_found_without_dates_passes_none(monkeypatch):
    repo = _install(monkeypatch)
    response = handler.lambda_handler(_event(None), _ctx())
    assert response["statusCode"] == 200
    assert repo.find_kwargs["publish_date_from"] is None
    assert repo.find_kwargs["publish_date_to"] is None


def test_not_found_bad_date_400(monkeypatch):
    _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "06/01/2026"}), _ctx()
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"


def test_not_found_from_after_to_400(monkeypatch):
    _install(monkeypatch)
    response = handler.lambda_handler(
        _event({"publish_date_from": "2026-07-01",
                "publish_date_to": "2026-06-01"}),
        _ctx(),
    )
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"

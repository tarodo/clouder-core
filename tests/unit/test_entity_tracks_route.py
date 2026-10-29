"""GET /labels/{label_id}/tracks and GET /artists/{artist_id}/tracks (the entity page's player)."""

from __future__ import annotations

import json

import pytest

from collector import entity_tracks, handler
from collector.providers import registry
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    yield
    reset_settings_cache()
    registry.reset_cache()


class FakeRepo:
    def __init__(self):
        self.calls: list[dict] = []

    def list_tracks(self, **kw):
        self.calls.append(kw)
        return [{"id": "t1"}], 7


def _call(monkeypatch, route, path, qs=None):
    repo = FakeRepo()
    monkeypatch.setattr(entity_tracks, "_build_repository", lambda: repo)
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route,
            "authorizer": {"lambda": {"user_id": "u1", "is_admin": False}},
        },
        "rawPath": "/x",
        "pathParameters": path,
        "queryStringParameters": qs,
        "headers": {},
        "body": None,
    }
    response = handler.lambda_handler(event, type("C", (), {"aws_request_id": "x"})())
    return response["statusCode"], json.loads(response["body"]), repo.calls


def test_label_tracks_page(monkeypatch):
    status, body, calls = _call(
        monkeypatch, "GET /labels/{label_id}/tracks", {"label_id": "lbl"}, {"offset": "50"}
    )
    assert (status, body["items"], body["total"]) == (200, [{"id": "t1"}], 7)
    assert (body["limit"], body["offset"]) == (50, 50)
    assert calls == [
        {"kind": "label", "entity_id": "lbl", "user_id": "u1", "limit": 50, "offset": 50}
    ]


def test_artist_tracks_page(monkeypatch):
    status, _, calls = _call(
        monkeypatch, "GET /artists/{artist_id}/tracks", {"artist_id": "art"}, {"limit": "20"}
    )
    assert status == 200
    assert calls[0]["kind"] == "artist" and calls[0]["limit"] == 20


@pytest.mark.parametrize("qs", [{"limit": "0"}, {"limit": "201"}, {"offset": "-1"}, {"limit": "x"}])
def test_bad_paging_is_400(monkeypatch, qs):
    status, body, calls = _call(
        monkeypatch, "GET /labels/{label_id}/tracks", {"label_id": "lbl"}, qs
    )
    assert (status, body["error_code"], calls) == (400, "validation_error", [])

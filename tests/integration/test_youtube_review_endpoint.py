"""Admin YouTube review of one Coverage cell: list the open reviews, resolve one."""

from __future__ import annotations

import json
from datetime import date

import pytest

from collector import handler
from collector.providers import registry
from collector.settings import reset_settings_cache

VIDEO = "dQw4w9WgXcQ"  # 11 chars, as YT_VIDEO_ID_RE wants


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(route, *, query=None, path=None, body=None, is_admin=True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route,
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/youtube/review",
        "queryStringParameters": query,
        "pathParameters": path,
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body) if body is not None else None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class Catalog:
    def __init__(self, rows):
        self.rows, self.asked = rows, None

    def youtube_review_tracks(self, *, beatport_style_id, date_from, date_to):
        self.asked = (beatport_style_id, date_from, date_to)
        return self.rows


ROW = {
    "track_id": "t1",
    "title": "Night Drive",
    "mix_name": "Extended Mix",
    "length_ms": 390000,
    "spotify_id": "sp1",
    "style_name": "Tech House",
    "artists": "Zeta",
    "candidates": [
        {
            "ref": {
                "videoId": VIDEO,
                "title": "Night Drive",
                "artists": [{"name": "Zeta"}],
                "duration_seconds": 201,
            },
            "score": 0.9,
        },
        {"ref": {"title": "no video id"}, "score": 0.4},
    ],
}


def _list(monkeypatch, catalog, query, **kw):
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: catalog)
    response = handler.lambda_handler(
        _event("GET /admin/youtube/review", query=query, **kw), _ctx()
    )
    return response["statusCode"], json.loads(response["body"])


def test_lists_the_cell_reviews_with_spotify_and_youtube_links(monkeypatch):
    catalog = Catalog([ROW])
    status, body = _list(
        monkeypatch, catalog, {"style_id": "90", "week_year": "2026", "week_number": "40"}
    )
    assert status == 200
    assert catalog.asked == ("90", date(2026, 10, 3), date(2026, 10, 9))
    assert body["style_name"] == "Tech House"
    (track,) = body["tracks"]
    assert track == {
        "track_id": "t1",
        "title": "Night Drive",
        "mix_name": "Extended Mix",
        "artists": "Zeta",
        "length_ms": 390000,
        "spotify_url": "https://open.spotify.com/track/sp1",
        "candidates": [
            {
                "vendor_track_id": VIDEO,
                "title": "Night Drive",
                "artists": ["Zeta"],
                "album": None,
                "duration_ms": 201000,
                "url": f"https://music.youtube.com/watch?v={VIDEO}",
                "score": 0.9,
            }
        ],
    }


@pytest.mark.parametrize(
    "query",
    [
        None,
        {"style_id": "90", "week_year": "2026"},
        {"style_id": "x", "week_year": "2026", "week_number": "40"},
        {"style_id": "90", "week_year": "2026", "week_number": "54"},
    ],
)
def test_list_needs_a_valid_cell(monkeypatch, query):
    status, body = _list(monkeypatch, Catalog([]), query)
    assert (status, body["error_code"]) == (400, "validation_error")


def test_list_is_admin_only(monkeypatch):
    status, body = _list(
        monkeypatch,
        Catalog([]),
        {"style_id": "90", "week_year": "2026", "week_number": "40"},
        is_admin=False,
    )
    assert (status, body["error_code"]) == (403, "admin_required")


class Reviews:
    def __init__(self):
        self.accepted = self.rejected = None

    def get_open_review(self, *, track_id, vendor):
        return type("R", (), {"candidates": ROW["candidates"]})()

    def resolve_review_accept(self, **kw):
        self.accepted = kw

    def resolve_review_reject(self, **kw):
        self.rejected = kw


def _resolve(monkeypatch, body, **kw):
    reviews = Reviews()
    monkeypatch.setattr(
        "collector.api.routes_youtube.create_default_playlists_repository", lambda: reviews
    )
    monkeypatch.setattr(
        "collector.curation.match_review.try_dispatch_comment_collection", lambda **k: None
    )
    event = _event(
        "POST /admin/youtube/review/{track_id}", path={"track_id": "t1"}, body=body, **kw
    )
    response = handler.lambda_handler(event, _ctx())
    return response["statusCode"], json.loads(response["body"]), reviews


def test_accept_links_the_picked_candidate(monkeypatch):
    status, body, reviews = _resolve(monkeypatch, {"action": "accept", "vendor_track_id": VIDEO})
    assert (status, body) == (200, {"track_id": "t1", "action": "accept"})
    assert reviews.accepted["vendor_track_id"] == VIDEO
    assert reviews.accepted["vendor"] == "ytmusic"
    assert reviews.accepted["payload"]["title"] == "Night Drive"  # the stored candidate


def test_reject_marks_not_on_youtube(monkeypatch):
    status, _, reviews = _resolve(monkeypatch, {"action": "reject"})
    assert status == 200 and reviews.rejected["clouder_track_id"] == "t1"


def test_accept_needs_a_video_id(monkeypatch):
    status, body, reviews = _resolve(monkeypatch, {"action": "accept"})
    assert (status, body["error_code"]) == (400, "validation_error")
    assert reviews.accepted is None


def test_resolve_is_admin_only(monkeypatch):
    status, body, _ = _resolve(monkeypatch, {"action": "reject"}, is_admin=False)
    assert (status, body["error_code"]) == (403, "admin_required")

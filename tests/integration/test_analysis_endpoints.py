"""/v1/analysis/* (service token) and /admin/analysis/* (admin) through the collector handler."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from collector import handler
from collector.providers import registry
from collector.settings import reset_settings_cache

NOW = datetime(2026, 10, 16, 3, tzinfo=UTC)
LEASE = "6f1c2a4e-0000-4000-8000-000000000000"
SERVICE = {"service": "analyzer"}
ADMIN = {"user_id": "u1", "is_admin": True}
USER = {"user_id": "u1", "is_admin": False}


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr("collector.api.deps.utc_now", lambda: NOW)
    yield
    reset_settings_cache()
    registry.reset_cache()


class FakeRepo:
    def __init__(self, rejected=None):
        self.calls: list[tuple[str, dict]] = []
        self.rejected = rejected or []

    def claim_analysis(self, **kw):
        self.calls.append(("claim", kw))
        return [
            {"track_id": "t1", "video_id": "v1", "length_ms": 200000, "analyzers": ["ai_detect"]}
        ]

    def record_analysis_results(self, **kw):
        self.calls.append(("results", kw))
        return self.rejected

    def analysis_status(self, **kw):
        self.calls.append(("status", kw))
        return {
            "last_claim_at": NOW,
            "last_result_at": None,
            "analyzers": [],
            "pair": {"high": 2, "medium": 5, "low": 3, "clean": 40},
            "queue": {"waiting": 9, "analyzed": 50, "failed": 4, "unusable": 1},
            "profile": {"waiting": 6, "profiled": 20, "failed": 2, "unusable": 1},
            "models": {"count": 2, "last_trained_at": NOW},
        }

    def requeue_analysis(self, **kw):
        self.calls.append(("requeue", kw))
        return 7


def _call(monkeypatch, repo, route_key: str, ctx: dict, body: dict | None = None):
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    _, path = route_key.split(" ", 1)
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route_key,
            "authorizer": {"lambda": ctx},
        },
        "rawPath": path,
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": None if body is None else json.dumps(body),
    }
    response = handler.lambda_handler(event, type("C", (), {"aws_request_id": "x"})())
    return response["statusCode"], json.loads(response["body"])


def _item(**over):
    return {
        "track_id": "t1",
        "analyzer": "ai_detect",
        "version": "v1",
        "status": "ok",
        "result": {"ai_detected": True, "score": 0.8},
        "error": None,
        "audio_sha256": None,
        "video_id": "v1",
    } | over


def test_claim_leases_for_the_service(monkeypatch):
    repo = FakeRepo()
    status, body = _call(
        monkeypatch,
        repo,
        "POST /v1/analysis/claim",
        SERVICE,
        {"limit": 5, "analyzers": ["ai_detect"]},
    )
    assert status == 200
    assert body["lease_expires_at"] == "2026-10-16T03:30:00+00:00"
    assert body["tracks"] == [
        {"track_id": "t1", "video_id": "v1", "length_ms": 200000, "analyzers": ["ai_detect"]}
    ]
    (_, kw), *_ = repo.calls
    assert (kw["limit"], kw["analyzers"], kw["now"]) == (5, ["ai_detect"], NOW)
    assert kw["lease_id"] == body["lease_id"]


@pytest.mark.parametrize("ctx", [USER, ADMIN, {}])
def test_claim_refuses_anything_but_the_service(monkeypatch, ctx):
    status, body = _call(
        monkeypatch, FakeRepo(), "POST /v1/analysis/claim", ctx, {"analyzers": ["ai_detect"]}
    )
    assert (status, body["error_code"]) == (401, "service_required")


def test_claim_validates_the_body(monkeypatch):
    status, body = _call(
        monkeypatch, FakeRepo(), "POST /v1/analysis/claim", SERVICE, {"analyzers": []}
    )
    assert (status, body["error_code"]) == (400, "validation_error")


def test_results_count_accepted_and_rejected(monkeypatch):
    lost = [{"track_id": "t2", "analyzer": "ai_detect", "reason": "lease_lost"}]
    repo = FakeRepo(rejected=lost)
    status, body = _call(
        monkeypatch,
        repo,
        "POST /v1/analysis/results",
        SERVICE,
        {"lease_id": LEASE, "results": [_item(), _item(track_id="t2")]},
    )
    assert status == 200
    assert body == {"accepted": 1, "rejected": lost}
    (_, kw), *_ = repo.calls
    assert kw["lease_id"] == LEASE
    assert kw["items"][0]["result"] == {"ai_detected": True, "score": 0.8}


def test_results_reject_a_bad_ai_detect_result(monkeypatch):
    status, body = _call(
        monkeypatch,
        FakeRepo(),
        "POST /v1/analysis/results",
        SERVICE,
        {"lease_id": LEASE, "results": [_item(result={"score": 0.8})]},
    )
    assert (status, body["error_code"]) == (400, "validation_error")


def test_admin_status(monkeypatch):
    status, body = _call(monkeypatch, FakeRepo(), "GET /admin/analysis/status", ADMIN)
    assert status == 200
    assert body == {
        "last_claim_at": NOW.isoformat(),
        "last_result_at": None,
        "analyzers": [],
        "pair": {"high": 2, "medium": 5, "low": 3, "clean": 40},
        "queue": {"waiting": 9, "analyzed": 50, "failed": 4, "unusable": 1},
        "profile": {"waiting": 6, "profiled": 20, "failed": 2, "unusable": 1},
        "models": {"count": 2, "last_trained_at": NOW.isoformat()},
    }


def test_admin_requeue(monkeypatch):
    repo = FakeRepo()
    status, body = _call(
        monkeypatch,
        repo,
        "POST /admin/analysis/requeue",
        ADMIN,
        {"analyzer": "ai_detect", "scope": "recent", "days": 7},
    )
    assert (status, body) == (200, {"requeued": 7})
    (_, kw), *_ = repo.calls
    assert kw == {
        "analyzer": "ai_detect",
        "scope": "recent",
        "days": 7,
        "include_failed": False,
        "now": NOW,
    }


@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("GET /admin/analysis/status", None),
        ("POST /admin/analysis/requeue", {"analyzer": "ai_detect", "scope": "all"}),
    ],
)
def test_admin_routes_need_an_admin(monkeypatch, route, body):
    for ctx in (USER, SERVICE):
        status, payload = _call(monkeypatch, FakeRepo(), route, ctx, body)
        assert (status, payload["error_code"]) == (403, "admin_required")

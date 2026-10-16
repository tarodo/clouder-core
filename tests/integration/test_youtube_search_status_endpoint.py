"""GET /admin/youtube/search-status: is the YouTube search running, what it found."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from collector import handler
from collector.providers import registry
from collector.settings import reset_settings_cache

QUEUE = "https://sqs.test/youtube-search"
COUNTS = {
    "waiting": 120,
    "searched_recently": 210,
    "searched_total": 4600,
    "matched": 3400,
    "needs_review": 940,
    "not_found": 3,
    "videos": 1200,
}


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("YOUTUBE_SEARCH_QUEUE_URL", QUEUE)
    monkeypatch.setenv("YOUTUBE_SEARCH_SINCE", "2026-10-15T00:00:00Z")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(*, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /admin/youtube/search-status",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/youtube/search-status",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, blocked_until=None):
        self.blocked_until = blocked_until
        self.args = None

    def get_vendor_blocked_until(self, vendor):
        assert vendor == "ytmusic"
        return self.blocked_until

    def youtube_search_counts(self, since, recent_since, published_since=None):
        self.args = (since, recent_since)
        self.published_since = published_since
        return dict(COUNTS)


class FakeSqs:
    def __init__(self, visible=0, in_flight=0, delayed=0):
        self.attrs = {
            "ApproximateNumberOfMessages": str(visible),
            "ApproximateNumberOfMessagesNotVisible": str(in_flight),
            "ApproximateNumberOfMessagesDelayed": str(delayed),
        }
        self.asked = None

    def get_queue_attributes(self, *, QueueUrl, AttributeNames):
        self.asked = QueueUrl
        return {"Attributes": self.attrs}


def _call(monkeypatch, repo, sqs, **kwargs):
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr("collector.api.deps.create_default_sqs_client", lambda: sqs)
    response = handler.lambda_handler(_event(**kwargs), _ctx())
    return response["statusCode"], json.loads(response["body"])


def test_running_with_counts_and_outcomes(monkeypatch):
    repo, sqs = FakeRepo(), FakeSqs(in_flight=1)
    status, body = _call(monkeypatch, repo, sqs)

    assert status == 200
    assert body["status"] == "running"
    assert body["queue"] == {"waiting_messages": 0, "in_flight": 1, "delayed": 0}
    assert body["tracks"] == {"waiting": 120, "searched_last_10_min": 210, "searched_total": 4600}
    assert body["results"] == {"matched": 3400, "needs_review": 940, "not_found": 3, "videos": 1200}
    assert sqs.asked == QUEUE
    since, recent = repo.args
    assert since == datetime(2026, 10, 15, tzinfo=UTC)
    assert datetime.now(UTC) - recent == pytest.approx(
        timedelta(minutes=10), abs=timedelta(seconds=5)
    )


def test_queued_and_idle(monkeypatch):
    _, body = _call(monkeypatch, FakeRepo(), FakeSqs(visible=1))
    assert body["status"] == "queued"
    _, body = _call(monkeypatch, FakeRepo(), FakeSqs())
    assert body["status"] == "idle"


def test_paused_during_a_youtube_ban(monkeypatch):
    until = datetime.now(UTC) + timedelta(minutes=40)
    _, body = _call(monkeypatch, FakeRepo(blocked_until=until), FakeSqs(delayed=1))
    assert (body["status"], body["paused_until"]) == ("paused", until.isoformat())


def test_admin_only(monkeypatch):
    status, body = _call(monkeypatch, FakeRepo(), FakeSqs(), is_admin=False)
    assert (status, body["error_code"]) == (403, "admin_required")


def test_waiting_counts_recent_releases_when_configured(monkeypatch):
    monkeypatch.setenv("YOUTUBE_SEARCH_PUBLISHED_SINCE", "2026-10-03")
    reset_settings_cache()
    repo = FakeRepo()
    _call(monkeypatch, repo, FakeSqs())
    assert str(repo.published_since) == "2026-10-03"


def test_empty_published_since_switches_it_off(monkeypatch):
    from collector.settings import YoutubeSearchWorkerSettings

    monkeypatch.setenv("YOUTUBE_SEARCH_PUBLISHED_SINCE", "")
    assert YoutubeSearchWorkerSettings().published_since is None

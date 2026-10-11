"""GET /admin/spotify/search-status: is the Spotify search running, how much is left."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from collector import handler
from collector.providers import registry
from collector.settings import reset_settings_cache

QUEUE = "https://sqs.test/spotify-search"


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", QUEUE)
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(*, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /admin/spotify/search-status",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/spotify/search-status",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, blocked_until=None):
        self.blocked_until = blocked_until
        self.since = None

    def get_vendor_blocked_until(self, vendor):
        assert vendor == "spotify"
        return self.blocked_until

    def spotify_search_counts(self, since):
        self.since = since
        return {"waiting": 4120, "not_found": 3051, "searched_recently": 600}


class FakeSqs:
    def __init__(self, visible=0, in_flight=0, delayed=0):
        self.attrs = {"ApproximateNumberOfMessages": str(visible),
                      "ApproximateNumberOfMessagesNotVisible": str(in_flight),
                      "ApproximateNumberOfMessagesDelayed": str(delayed)}
        self.asked = None

    def get_queue_attributes(self, *, QueueUrl, AttributeNames):
        self.asked = (QueueUrl, sorted(AttributeNames))
        return {"Attributes": self.attrs}


def _call(monkeypatch, repo, sqs, **kwargs):
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr("collector.api.deps.create_default_sqs_client", lambda: sqs)
    response = handler.lambda_handler(_event(**kwargs), _ctx())
    return response["statusCode"], json.loads(response["body"])


def test_running_when_a_worker_holds_a_message(monkeypatch):
    repo, sqs = FakeRepo(), FakeSqs(in_flight=1)
    status, body = _call(monkeypatch, repo, sqs)

    assert status == 200
    assert body["status"] == "running"
    assert body["tracks"] == {"waiting": 4120, "not_found": 3051, "searched_last_10_min": 600}
    assert body["queue"] == {"waiting_messages": 0, "in_flight": 1, "delayed": 0}
    assert body["paused_until"] is None
    assert sqs.asked[0] == QUEUE
    assert datetime.now(UTC) - repo.since == pytest.approx(timedelta(minutes=10), abs=timedelta(seconds=5))


def test_queued_when_a_message_waits_for_a_worker(monkeypatch):
    _, body = _call(monkeypatch, FakeRepo(), FakeSqs(visible=2))
    assert body["status"] == "queued"


def test_idle_when_the_queue_is_empty(monkeypatch):
    _, body = _call(monkeypatch, FakeRepo(), FakeSqs())
    assert body["status"] == "idle"


def test_paused_during_a_spotify_ban(monkeypatch):
    until = datetime.now(UTC) + timedelta(hours=3)
    _, body = _call(monkeypatch, FakeRepo(blocked_until=until), FakeSqs(delayed=1))
    assert body["status"] == "paused"
    assert body["paused_until"] == until.isoformat()


def test_an_expired_ban_is_not_a_pause(monkeypatch):
    _, body = _call(monkeypatch, FakeRepo(blocked_until=datetime.now(UTC) - timedelta(minutes=1)),
                    FakeSqs())
    assert (body["status"], body["paused_until"]) == ("idle", None)


def test_admin_only(monkeypatch):
    status, body = _call(monkeypatch, FakeRepo(), FakeSqs(), is_admin=False)
    assert (status, body["error_code"]) == (403, "admin_required")

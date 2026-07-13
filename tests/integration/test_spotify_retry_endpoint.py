"""Integration tests for POST /admin/spotify/retry-not-found."""

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
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "https://sqs.test/queue")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(body: dict | None, *, is_admin: bool = True):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /admin/spotify/retry-not-found",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/spotify/retry-not-found",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body) if body is not None else None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, reset_count=2, pending_count=0):
        self._reset_count = reset_count
        self._pending_count = pending_count
        self.reset_args = None
        self.reset_called = False

    def reset_spotify_not_found(self, publish_date_from, publish_date_to, now):
        self.reset_called = True
        self.reset_args = (publish_date_from, publish_date_to)
        return self._reset_count

    def count_spotify_pending_in_range(self, publish_date_from, publish_date_to):
        return self._pending_count


class FakeSqs:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, **kwargs):
        if self.fail:
            raise RuntimeError("sqs down")
        self.sent.append(kwargs)


def _install(monkeypatch, repo, sqs):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        "collector.handler.create_default_sqs_client", lambda: sqs
    )


BODY = {"publish_date_from": "2026-06-01", "publish_date_to": "2026-06-30"}


def test_retry_requires_admin(monkeypatch):
    _install(monkeypatch, FakeRepo(), FakeSqs())
    response = handler.lambda_handler(_event(BODY, is_admin=False), _ctx())
    assert response["statusCode"] == 403


def test_retry_resets_and_enqueues(monkeypatch):
    repo, sqs = FakeRepo(reset_count=2), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["queued_count"] == 2
    assert repo.reset_args == (date(2026, 6, 1), date(2026, 6, 30))
    assert len(sqs.sent) == 1
    message = json.loads(sqs.sent[0]["MessageBody"])
    assert message == {"batch_size": 200, "auto_continue": True}
    assert sqs.sent[0]["QueueUrl"] == "https://sqs.test/queue"


def test_retry_zero_reset_zero_pending_skips_enqueue(monkeypatch):
    repo, sqs = FakeRepo(reset_count=0, pending_count=0), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    assert json.loads(response["body"])["queued_count"] == 0
    assert sqs.sent == []


def test_retry_zero_reset_with_pending_still_enqueues(monkeypatch):
    repo, sqs = FakeRepo(reset_count=0, pending_count=5), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 200
    assert len(sqs.sent) == 1


def test_retry_sqs_failure_500(monkeypatch):
    _install(monkeypatch, FakeRepo(reset_count=2), FakeSqs(fail=True))
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error_code"] == "enqueue_failed"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"publish_date_from": "2026-06-01"},
        {"publish_date_from": "bad", "publish_date_to": "2026-06-30"},
        {"publish_date_from": "2026-07-01", "publish_date_to": "2026-06-01"},
    ],
)
def test_retry_validation_400(monkeypatch, body):
    _install(monkeypatch, FakeRepo(), FakeSqs())
    response = handler.lambda_handler(_event(body), _ctx())
    assert response["statusCode"] == 400
    assert json.loads(response["body"])["error_code"] == "validation_error"


def test_retry_db_not_configured_503(monkeypatch):
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env", lambda: None
    )
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 503


def test_retry_missing_queue_url_500_before_reset(monkeypatch):
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "")
    reset_settings_cache()
    repo, sqs = FakeRepo(reset_count=2), FakeSqs()
    _install(monkeypatch, repo, sqs)
    response = handler.lambda_handler(_event(BODY), _ctx())
    assert response["statusCode"] == 500
    assert json.loads(response["body"])["error_code"] == "enqueue_failed"
    assert repo.reset_called is False
    assert sqs.sent == []

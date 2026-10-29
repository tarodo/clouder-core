"""POST /v1/analysis/waveforms (service token) and GET /tracks/{track_id}/waveform (user)."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from collector import handler
from collector.providers import registry
from collector.settings import reset_settings_cache

NOW = datetime(2026, 10, 29, 22, tzinfo=UTC)
SERVICE = {"service": "analyzer"}
USER = {"user_id": "u1", "is_admin": False}
SHA = "a" * 64
VID = "dQw4w9WgXcQ"
DATA = base64.b64encode(bytes(range(200)) * 9).decode()  # 1 800 bytes


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
    def __init__(self, waveform=None):
        self.recorded: list[dict] = []
        self.waveform = waveform
        self.asked: list[str] = []

    def record_audio_waveforms(self, *, items, now):
        assert now == NOW
        self.recorded.extend(items)
        return len(items)

    def track_waveform(self, *, track_id):
        self.asked.append(track_id)
        return self.waveform


def _item(video_id: str = VID, **over) -> dict:
    return {
        "video_id": video_id,
        "version": "wave-1",
        "audio_sha256": SHA,
        "duration_ms": 322_000,
        "data_b64": DATA,
    } | over


def _call(monkeypatch, repo, route, *, body=None, ctx=SERVICE, path=None):
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": route,
            "authorizer": {"lambda": ctx},
        },
        "rawPath": route.split(" ", 1)[1],
        "pathParameters": path,
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body) if body is not None else None,
    }
    response = handler.lambda_handler(event, type("C", (), {"aws_request_id": "x"})())
    return response["statusCode"], json.loads(response["body"])


def _post(monkeypatch, repo, items, ctx=SERVICE):
    return _call(monkeypatch, repo, "POST /v1/analysis/waveforms", body={"items": items}, ctx=ctx)


def test_waveforms_stores_valid_items(monkeypatch):
    repo = FakeRepo()
    status, body = _post(monkeypatch, repo, [_item()])
    assert (status, body) == (200, {"accepted": 1, "rejected": []})
    assert repo.recorded == [_item()]


@pytest.mark.parametrize(
    "data",
    [base64.b64encode(b"\0" * 1799).decode(), "not base64!"],
    ids=["short", "not_base64"],
)
def test_waveforms_rejects_bad_data(monkeypatch, data):
    repo = FakeRepo()
    items = [_item(), _item("other_video", data_b64=data)]
    status, body = _post(monkeypatch, repo, items)
    assert (status, body) == (
        200,
        {"accepted": 1, "rejected": [{"video_id": "other_video", "reason": "bad_waveform"}]},
    )
    assert [r["video_id"] for r in repo.recorded] == [VID]


def test_waveforms_all_rejected_never_touches_the_db(monkeypatch):
    monkeypatch.setattr(
        "collector.api.deps.create_clouder_repository_from_env",
        lambda: pytest.fail("no DB call for an all-bad batch"),
    )
    event_items = [_item(data_b64="AAAA")]
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /v1/analysis/waveforms",
            "authorizer": {"lambda": SERVICE},
        },
        "rawPath": "/v1/analysis/waveforms",
        "headers": {},
        "body": json.dumps({"items": event_items}),
    }
    response = handler.lambda_handler(event, type("C", (), {"aws_request_id": "x"})())
    assert json.loads(response["body"])["accepted"] == 0


@pytest.mark.parametrize("ctx", [USER, {}])
def test_waveforms_requires_service(monkeypatch, ctx):
    repo = FakeRepo()
    status, body = _post(monkeypatch, repo, [_item()], ctx=ctx)
    assert (status, body["error_code"]) == (401, "service_required")
    assert repo.recorded == []


@pytest.mark.parametrize(
    "items",
    [
        [],
        [_item(), _item()],  # duplicate video_id
        [_item(version="wave-2")],
        [_item(duration_ms=0)],
        [_item(audio_sha256="ABC")],
        [_item(data_b64="A" * 2401)],
    ],
    ids=["empty", "duplicate", "version", "duration", "sha", "too_long"],
)
def test_waveforms_validates_the_body(monkeypatch, items):
    status, body = _post(monkeypatch, FakeRepo(), items)
    assert (status, body["error_code"]) == (400, "validation_error")


def test_track_waveform_returns_the_waveform(monkeypatch):
    repo = FakeRepo(waveform={"duration_ms": 322_000, "data": DATA})
    status, body = _call(
        monkeypatch, repo, "GET /tracks/{track_id}/waveform", ctx=USER, path={"track_id": "t1"}
    )
    assert (status, body) == (200, {"waveform": {"duration_ms": 322_000, "data": DATA}})
    assert repo.asked == ["t1"]


def test_track_waveform_without_one_is_null(monkeypatch):
    status, body = _call(
        monkeypatch,
        FakeRepo(),
        "GET /tracks/{track_id}/waveform",
        ctx=USER,
        path={"track_id": "t1"},
    )
    assert (status, body) == (200, {"waveform": None})

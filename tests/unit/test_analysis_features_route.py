"""POST /v1/analysis/features: the analyzer uploads light-1 profiles (service token)."""

from __future__ import annotations

import base64
import json
import struct
from datetime import UTC, datetime

import pytest

from collector import audio_profile, handler
from collector.providers import registry
from collector.settings import reset_settings_cache

NOW = datetime(2026, 10, 23, 3, tzinfo=UTC)
SERVICE = {"service": "analyzer"}
SHA = "a" * 64
VID = "dQw4w9WgXcQ"


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("AUDIO_FEATURES_BUCKET", "features-bucket")
    monkeypatch.setenv("ML_JOBS_QUEUE_URL", "https://sqs/ml-jobs")
    monkeypatch.setattr("collector.api.deps.utc_now", lambda: NOW)
    yield
    reset_settings_cache()
    registry.reset_cache()


class FakeRepo:
    def __init__(self, known=None):
        self.known = known or {}
        self.recorded: list[dict] = []

    def known_audio_features(self, *, video_ids):
        return {v: self.known[v] for v in video_ids if v in self.known}

    def record_audio_features(self, *, items, now):
        assert now == NOW
        self.recorded.extend(items)
        return len(items)


class FakeS3:
    def __init__(self):
        self.puts: list[dict] = []

    def put_object(self, **kw):
        self.puts.append(kw)


class FakeSQS:
    def __init__(self, fail=False):
        self.fail = fail
        self.messages: list[dict] = []

    def send_message(self, **kw):
        if self.fail:
            raise RuntimeError("sqs down")
        self.messages.append(kw)


def _vector(value: float = 0.5) -> str:
    return base64.b64encode(
        struct.pack(f"<{audio_profile.DIMS}e", *[value] * audio_profile.DIMS)
    ).decode()


def _item(video_id: str = VID, **over) -> dict:
    return {
        "video_id": video_id,
        "version": "light-1",
        "audio_sha256": SHA,
        "vector_b64": _vector(),
    } | over


def _call(monkeypatch, repo, body, *, ctx=SERVICE, sqs=None):
    s3, sqs = FakeS3(), sqs or FakeSQS()
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr("collector.api.routes_analysis._build_s3_client", lambda: s3)
    monkeypatch.setattr("collector.ml_jobs._build_sqs_client", lambda: sqs)
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "POST /v1/analysis/features",
            "authorizer": {"lambda": ctx},
        },
        "rawPath": "/v1/analysis/features",
        "queryStringParameters": None,
        "headers": {"x-correlation-id": "c"},
        "body": json.dumps(body),
    }
    response = handler.lambda_handler(event, type("C", (), {"aws_request_id": "x"})())
    return response["statusCode"], json.loads(response["body"]), s3, sqs


def test_features_accepts_valid_vector(monkeypatch):
    repo = FakeRepo()
    status, body, s3, sqs = _call(monkeypatch, repo, {"items": [_item()]})
    assert (status, body) == (200, {"accepted": 1, "rejected": []})
    (put,) = s3.puts
    assert put["Bucket"] == "features-bucket"
    assert put["Key"] == f"features/light-1/{VID}.f16"
    assert len(put["Body"]) == 33556
    assert repo.recorded == [{"video_id": VID, "version": "light-1", "audio_sha256": SHA}]
    (msg,) = sqs.messages
    assert msg["QueueUrl"] == "https://sqs/ml-jobs"
    assert json.loads(msg["MessageBody"]) == {"type": "score", "video_ids": [VID]}


@pytest.mark.parametrize(
    "vector",
    [
        _vector(float("nan")),
        base64.b64encode(b"\0" * 100).decode(),  # wrong length
        "not base64!",
    ],
    ids=["nan", "short", "not_base64"],
)
def test_features_rejects_bad_vector(monkeypatch, vector):
    repo = FakeRepo()
    status, body, s3, sqs = _call(monkeypatch, repo, {"items": [_item(vector_b64=vector)]})
    assert status == 200
    assert body == {"accepted": 0, "rejected": [{"video_id": VID, "reason": "bad_vector"}]}
    assert s3.puts == [] and repo.recorded == [] and sqs.messages == []


def test_features_same_sha_is_noop_put(monkeypatch):
    repo = FakeRepo(known={VID: ("light-1", SHA), "other_video": ("light-1", "b" * 64)})
    items = [_item(), _item("other_video")]
    status, body, s3, sqs = _call(monkeypatch, repo, {"items": items})
    assert (status, body["accepted"]) == (200, 2)
    # Only the changed one is written again; both are recorded and scored.
    assert [p["Key"] for p in s3.puts] == ["features/light-1/other_video.f16"]
    assert [r["video_id"] for r in repo.recorded] == [VID, "other_video"]
    assert json.loads(sqs.messages[0]["MessageBody"])["video_ids"] == [VID, "other_video"]


def test_features_enqueue_failure_does_not_fail_the_request(monkeypatch):
    status, body, _, _ = _call(monkeypatch, FakeRepo(), {"items": [_item()]}, sqs=FakeSQS(True))
    assert (status, body["accepted"]) == (200, 1)


@pytest.mark.parametrize("ctx", [{"user_id": "u1", "is_admin": True}, {}])
def test_features_requires_service(monkeypatch, ctx):
    status, body, s3, _ = _call(monkeypatch, FakeRepo(), {"items": [_item()]}, ctx=ctx)
    assert (status, body["error_code"]) == (401, "service_required")
    assert s3.puts == []


@pytest.mark.parametrize(
    "items",
    [
        [],
        [_item(), _item()],  # duplicate video_id
        [_item(version="light-2")],
        [_item(audio_sha256="ABC")],
        [_item(video_id="bad id!")],
    ],
    ids=["empty", "duplicate", "version", "sha", "video_id"],
)
def test_features_validates_the_body(monkeypatch, items):
    status, body, _, _ = _call(monkeypatch, FakeRepo(), {"items": items})
    assert (status, body["error_code"]) == (400, "validation_error")

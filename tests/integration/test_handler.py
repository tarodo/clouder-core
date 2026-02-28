import json
import os
from types import SimpleNamespace

import pytest

from collector.errors import UpstreamAuthError
from collector.handler import lambda_handler


class FakeS3Client:
    def __init__(self) -> None:
        self.calls = []
        self.objects = {}

    def put_object(self, **kwargs):
        self.calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]


@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-1")


def _event(body: dict, correlation_id: str | None = None) -> dict:
    headers = {}
    if correlation_id:
        headers["x-correlation-id"] = correlation_id
    return {
        "version": "2.0",
        "requestContext": {"requestId": "api-req-1"},
        "headers": headers,
        "body": json.dumps(body),
    }


def test_happy_path_writes_three_objects_and_returns_ids(monkeypatch, context) -> None:
    fake_s3 = FakeS3Client()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")

    def fake_s3_factory():
        return fake_s3

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def fetch_weekly_releases(self, bp_token, style_id, week_start, week_end, correlation_id):
            assert bp_token == "secret"
            assert style_id == 5
            assert week_start == "2026-02-23"
            assert week_end == "2026-03-01"
            assert correlation_id == "cid-123"
            return [{"id": 1}, {"id": 2}], 2

    monkeypatch.setattr("collector.handler.create_default_s3_client", fake_s3_factory)
    monkeypatch.setattr("collector.handler.BeatportClient", FakeClient)

    response = lambda_handler(
        _event(
            {
                "bp_token": "secret",
                "style_id": 5,
                "iso_year": 2026,
                "iso_week": 9,
            },
            correlation_id="cid-123",
        ),
        context,
    )

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["correlation_id"] == "cid-123"
    assert body["api_request_id"] == "api-req-1"
    assert body["lambda_request_id"] == "lambda-req-1"
    assert body["item_count"] == 2
    assert body["s3_object_key"].endswith("/releases.json.gz")

    keys = [call["Key"] for call in fake_s3.calls]
    assert any(key.endswith("releases.json.gz") for key in keys)
    assert any(key.endswith("meta.json") for key in keys)
    assert any("/runs/run_id=" in key for key in keys)


def test_rerun_same_week_overwrites_latest_and_keeps_archives(monkeypatch, context) -> None:
    fake_s3 = FakeS3Client()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")

    def fake_s3_factory():
        return fake_s3

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def fetch_weekly_releases(self, bp_token, style_id, week_start, week_end, correlation_id):
            return [{"id": 1}], 1

    monkeypatch.setattr("collector.handler.create_default_s3_client", fake_s3_factory)
    monkeypatch.setattr("collector.handler.BeatportClient", FakeClient)

    payload = {
        "bp_token": "secret",
        "style_id": 5,
        "iso_year": 2026,
        "iso_week": 9,
    }

    response1 = lambda_handler(_event(payload), context)
    response2 = lambda_handler(_event(payload), context)

    assert response1["statusCode"] == 200
    assert response2["statusCode"] == 200

    keys = [call["Key"] for call in fake_s3.calls]
    releases_writes = [key for key in keys if key.endswith("releases.json.gz")]
    meta_writes = [key for key in keys if key.endswith("meta.json")]
    run_writes = [key for key in keys if "/runs/run_id=" in key]

    assert len(releases_writes) == 2
    assert len(meta_writes) == 2
    assert len(run_writes) == 2
    assert len(set(run_writes)) == 2


def test_beatport_auth_error_returns_sanitized_payload(monkeypatch, context) -> None:
    fake_s3 = FakeS3Client()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")

    def fake_s3_factory():
        return fake_s3

    class FakeClient:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def fetch_weekly_releases(self, bp_token, style_id, week_start, week_end, correlation_id):
            raise UpstreamAuthError()

    monkeypatch.setattr("collector.handler.create_default_s3_client", fake_s3_factory)
    monkeypatch.setattr("collector.handler.BeatportClient", FakeClient)

    response = lambda_handler(
        _event(
            {
                "bp_token": "secret",
                "style_id": 5,
                "iso_year": 2026,
                "iso_week": 9,
            }
        ),
        context,
    )

    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "beatport_auth_failed"
    assert "bp_token" not in json.dumps(body)
    assert body["api_request_id"] == "api-req-1"
    assert body["lambda_request_id"] == "lambda-req-1"
    assert len(fake_s3.calls) == 0


def test_invalid_body_returns_validation_error(monkeypatch, context) -> None:
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    response = lambda_handler(
        {
            "version": "2.0",
            "requestContext": {"requestId": "api-req-1"},
            "headers": {},
            "body": "{bad-json}",
        },
        context,
    )

    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"

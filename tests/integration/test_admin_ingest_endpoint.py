"""Integration tests for POST /admin/beatport/ingest."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from collector import handler
from collector.models import ProcessingOutcome, ProcessingStatus
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


def _event(body: dict[str, Any], *, is_admin: bool = True) -> dict[str, Any]:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req-1",
            "routeKey": "POST /admin/beatport/ingest",
            "authorizer": {"lambda": {"is_admin": is_admin}},
        },
        "rawPath": "/admin/beatport/ingest",
        "body": json.dumps(body),
        "isBase64Encoded": False,
        "headers": {"x-correlation-id": "test-corr"},
    }


def _ctx() -> Any:
    return type("Ctx", (), {"aws_request_id": "lr-1"})()


def test_admin_ingest_rejects_non_admin():
    response = handler.lambda_handler(
        _event(
            {"style_id": 1, "week_year": 2026, "week_number": 5, "bp_token": "tok"},
            is_admin=False,
        ),
        _ctx(),
    )
    assert response["statusCode"] == 403
    body = json.loads(response["body"])
    assert body["error_code"] == "admin_required"


def test_admin_ingest_validation_only_period_start():
    response = handler.lambda_handler(
        _event(
            {
                "style_id": 1,
                "week_year": 2026,
                "week_number": 5,
                "bp_token": "tok",
                "period_start": "2026-01-31",
            }
        ),
        _ctx(),
    )
    assert response["statusCode"] == 400
    body = json.loads(response["body"])
    assert body["error_code"] == "validation_error"


def _stub_pipeline(monkeypatch):
    """Patch out the side-effecting parts of `_run_beatport_ingest`."""
    fake_repo = MagicMock()
    monkeypatch.setattr(
        "collector.handler.create_clouder_repository_from_env",
        lambda: fake_repo,
    )

    class FakeS3Storage:
        def __init__(self, *args, **kwargs):
            pass

        def write_run_artifacts(self, releases, meta):
            return ("s3-key", None)

    monkeypatch.setattr("collector.handler.S3Storage", FakeS3Storage)
    monkeypatch.setattr(
        "collector.handler.create_default_s3_client", lambda: MagicMock()
    )

    fake_client = MagicMock()
    fake_client.fetch_weekly_releases.return_value = ([], 1)
    monkeypatch.setattr(
        "collector.handler.registry.get_ingest",
        lambda name: fake_client,
    )

    enqueue_stub = handler.EnqueueResult(
        processing_status=ProcessingStatus.QUEUED,
        processing_outcome=ProcessingOutcome.ENQUEUED,
        processing_reason=None,
    )
    monkeypatch.setattr(
        "collector.handler._enqueue_canonicalization",
        lambda **kw: enqueue_stub,
    )

    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")

    return fake_repo, fake_client


def test_admin_ingest_happy_path_default_range(monkeypatch):
    fake_repo, _ = _stub_pipeline(monkeypatch)
    response = handler.lambda_handler(
        _event(
            {
                "style_id": 7,
                "week_year": 2026,
                "week_number": 5,
                "bp_token": "tok",
            }
        ),
        _ctx(),
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["is_custom_range"] is False
    assert body["week_year"] == 2026
    assert body["week_number"] == 5
    assert body["period_start"] == "2026-01-31"
    assert body["period_end"] == "2026-02-06"

    cmd = fake_repo.create_ingest_run.call_args[0][0]
    assert cmd.is_custom_range is False
    assert cmd.period_start.isoformat() == "2026-01-31"
    assert cmd.period_end.isoformat() == "2026-02-06"
    assert cmd.week_year == 2026
    assert cmd.week_number == 5


def test_admin_ingest_happy_path_with_override(monkeypatch):
    fake_repo, _ = _stub_pipeline(monkeypatch)
    response = handler.lambda_handler(
        _event(
            {
                "style_id": 7,
                "week_year": 2026,
                "week_number": 5,
                "bp_token": "tok",
                "period_start": "2026-01-25",
                "period_end": "2026-02-02",
            }
        ),
        _ctx(),
    )
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["is_custom_range"] is True
    assert body["period_start"] == "2026-01-25"
    assert body["period_end"] == "2026-02-02"

    cmd = fake_repo.create_ingest_run.call_args[0][0]
    assert cmd.is_custom_range is True
    assert cmd.period_start.isoformat() == "2026-01-25"
    assert cmd.period_end.isoformat() == "2026-02-02"

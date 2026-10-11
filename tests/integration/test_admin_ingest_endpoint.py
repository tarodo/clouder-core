"""Integration tests for POST /admin/beatport/ingest."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from collector import handler
from collector.api import routes_ingest
from collector.models import ProcessingOutcome, ProcessingStatus
from collector.providers import registry
from collector.settings import reset_settings_cache


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
            {"style_id": 1, "week_year": 2026, "week_number": 5},
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
        "collector.api.deps.create_clouder_repository_from_env",
        lambda: fake_repo,
    )

    class FakeS3Storage:
        def __init__(self, *args, **kwargs):
            pass

        def write_run_artifacts(self, releases, meta):
            return ("s3-key", None)

    monkeypatch.setattr("collector.api.deps.S3Storage", FakeS3Storage)
    monkeypatch.setattr(
        "collector.api.deps.create_default_s3_client", lambda: MagicMock()
    )

    fake_client = MagicMock()
    fake_client.fetch_weekly_releases.return_value = ([], 1)
    monkeypatch.setattr(
        "collector.api.deps.registry.get_ingest",
        lambda name: fake_client,
    )

    enqueue_stub = routes_ingest.EnqueueResult(
        processing_status=ProcessingStatus.QUEUED,
        processing_outcome=ProcessingOutcome.ENQUEUED,
        processing_reason=None,
    )
    monkeypatch.setattr(
        "collector.api.routes_ingest._enqueue_canonicalization",
        lambda **kw: enqueue_stub,
    )

    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr("collector.api.deps.read_beatport_credentials", lambda: ("user", "pass"))
    monkeypatch.setattr("collector.api.deps.fetch_access_token", lambda username, password: "srv-tok")

    return fake_repo, fake_client


def test_admin_ingest_happy_path_default_range(monkeypatch):
    fake_repo, _ = _stub_pipeline(monkeypatch)
    response = handler.lambda_handler(
        _event(
            {
                "style_id": 7,
                "week_year": 2026,
                "week_number": 5,
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
    assert body["processing_status"] == "QUEUED"
    assert body["processing_outcome"] == "ENQUEUED"

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
    assert body["processing_status"] == "QUEUED"
    assert body["processing_outcome"] == "ENQUEUED"

    cmd = fake_repo.create_ingest_run.call_args[0][0]
    assert cmd.is_custom_range is True
    assert cmd.period_start.isoformat() == "2026-01-25"
    assert cmd.period_end.isoformat() == "2026-02-02"


def test_collect_period_marks_auto_runs(monkeypatch):
    fake_repo, fake_client = _stub_pipeline(monkeypatch)
    params = routes_ingest.IngestParams(
        style_id=7, bp_token="tok", period_start="2026-01-31", period_end="2026-02-06",
        iso_year=None, iso_week=None, week_year=2026, week_number=5, is_custom_range=False,
    )

    result = routes_ingest.collect_period(
        params, "corr-1", api_request_id="auto-ingest", lambda_request_id="lr-2", trigger="auto"
    )

    assert (result["week_year"], result["week_number"], result["run_status"]) == (2026, 5, "RAW_SAVED")
    assert fake_repo.create_ingest_run.call_args[0][0].meta["trigger"] == "auto"
    assert fake_client.fetch_weekly_releases.call_args.kwargs["bp_token"] == "tok"


def test_manual_admin_ingest_is_marked_manual(monkeypatch):
    fake_repo, _ = _stub_pipeline(monkeypatch)

    handler.lambda_handler(
        _event({"style_id": 7, "week_year": 2026, "week_number": 5}), _ctx()
    )

    assert fake_repo.create_ingest_run.call_args[0][0].meta["trigger"] == "manual"


def test_admin_ingest_logs_in_server_side(monkeypatch):
    # The SPA no longer handles a Beatport token: the API logs in with the SSM
    # credentials auto-ingest uses, and the token goes only to the fetch.
    _, fake_client = _stub_pipeline(monkeypatch)
    logins = []
    monkeypatch.setattr("collector.api.deps.fetch_access_token",
                        lambda username, password: logins.append((username, password)) or "srv-tok")

    response = handler.lambda_handler(_event({"style_id": 7, "week_year": 2026, "week_number": 5}), _ctx())

    assert response["statusCode"] == 200
    assert logins == [("user", "pass")]
    assert fake_client.fetch_weekly_releases.call_args.kwargs["bp_token"] == "srv-tok"
    assert "srv-tok" not in response["body"]


def test_admin_ingest_rejects_a_token_from_the_browser(monkeypatch):
    _stub_pipeline(monkeypatch)
    response = handler.lambda_handler(
        _event({"style_id": 7, "week_year": 2026, "week_number": 5, "bp_token": "tok"}), _ctx()
    )
    assert response["statusCode"] == 400


def test_admin_ingest_reports_missing_credentials(monkeypatch):
    _, fake_client = _stub_pipeline(monkeypatch)

    def missing():
        raise KeyError("BEATPORT_USERNAME_SSM_PARAMETER")

    monkeypatch.setattr("collector.api.deps.read_beatport_credentials", missing)

    response = handler.lambda_handler(_event({"style_id": 7, "week_year": 2026, "week_number": 5}), _ctx())

    assert response["statusCode"] == 503
    assert json.loads(response["body"])["error_code"] == "beatport_credentials_unavailable"
    fake_client.fetch_weekly_releases.assert_not_called()


def test_admin_ingest_reports_a_rejected_login(monkeypatch):
    from collector.beatport_auth import BeatportAuthError

    _, fake_client = _stub_pipeline(monkeypatch)

    def rejected(username, password):
        raise BeatportAuthError("login", 401)

    monkeypatch.setattr("collector.api.deps.fetch_access_token", rejected)

    response = handler.lambda_handler(_event({"style_id": 7, "week_year": 2026, "week_number": 5}), _ctx())

    body = json.loads(response["body"])
    assert (response["statusCode"], body["error_code"]) == (502, "beatport_login_failed")
    assert "login" in body["message"]
    fake_client.fetch_weekly_releases.assert_not_called()


def test_invalid_request_is_rejected_before_logging_in(monkeypatch):
    _stub_pipeline(monkeypatch)
    monkeypatch.setattr("collector.api.deps.fetch_access_token",
                        lambda username, password: pytest.fail("logged in for an invalid request"))
    response = handler.lambda_handler(
        _event({"style_id": 7, "week_year": 2026, "week_number": 5, "period_start": "2026-01-31"}), _ctx()
    )
    assert response["statusCode"] == 400

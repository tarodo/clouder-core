"""One request must carry one correlation_id across every log line.

`_extract_correlation_id` mints a fresh uuid4 when the caller sends no
x-correlation-id header. It used to be called both in `lambda_handler` and
again inside each route handler, so a failed request logged `request_received`
under one id and `request_failed` under a different one — the error path could
not be traced back to the request that caused it.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from collector import handler
from collector.errors import UpstreamAuthError
from collector.providers import registry
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    # Enough config to get past _load_api_settings and reach the upstream call,
    # so the test exercises the real 403 path seen in production.
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event_without_correlation_header() -> dict[str, Any]:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req-1",
            "routeKey": "POST /admin/beatport/ingest",
            "authorizer": {"lambda": {"is_admin": True}},
        },
        "rawPath": "/admin/beatport/ingest",
        "body": json.dumps(
            {"style_id": 1, "week_year": 2026, "week_number": 5, "bp_token": "tok"}
        ),
        "isBase64Encoded": False,
        "headers": {},
    }


def _ctx() -> Any:
    return type("Ctx", (), {"aws_request_id": "lr-1"})()


def _log_lines(captured: str) -> list[dict[str, Any]]:
    out = []
    for line in captured.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _correlation_for(lines: list[dict[str, Any]], message: str) -> str:
    for entry in lines:
        if entry.get("message") == message:
            return entry["correlation_id"]
    raise AssertionError(f"no {message!r} log line in {[e.get('message') for e in lines]}")


def test_failed_ingest_logs_one_correlation_id(monkeypatch, capsys) -> None:
    class FailingClient:
        def fetch_weekly_releases(self, **_kwargs):
            raise UpstreamAuthError()

    monkeypatch.setattr(registry, "get_ingest", lambda _name: FailingClient())

    response = handler.lambda_handler(_event_without_correlation_header(), _ctx())
    assert response["statusCode"] == 403

    lines = _log_lines(capsys.readouterr().out)
    received = _correlation_for(lines, "request_received")
    failed = _correlation_for(lines, "request_failed")

    assert received == failed


def test_failed_ingest_response_matches_logged_correlation_id(
    monkeypatch, capsys
) -> None:
    class FailingClient:
        def fetch_weekly_releases(self, **_kwargs):
            raise UpstreamAuthError()

    monkeypatch.setattr(registry, "get_ingest", lambda _name: FailingClient())

    response = handler.lambda_handler(_event_without_correlation_header(), _ctx())

    lines = _log_lines(capsys.readouterr().out)
    body = json.loads(response["body"])

    assert body["correlation_id"] == _correlation_for(lines, "request_received")


def test_supplied_correlation_header_is_preserved(monkeypatch, capsys) -> None:
    class FailingClient:
        def fetch_weekly_releases(self, **_kwargs):
            raise UpstreamAuthError()

    monkeypatch.setattr(registry, "get_ingest", lambda _name: FailingClient())

    event = _event_without_correlation_header()
    event["headers"] = {"x-correlation-id": "caller-supplied"}

    response = handler.lambda_handler(event, _ctx())

    lines = _log_lines(capsys.readouterr().out)
    assert _correlation_for(lines, "request_received") == "caller-supplied"
    assert _correlation_for(lines, "request_failed") == "caller-supplied"
    assert json.loads(response["body"])["correlation_id"] == "caller-supplied"

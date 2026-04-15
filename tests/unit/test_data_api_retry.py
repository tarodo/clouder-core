"""Tests for Data API retry wrapper."""
from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from collector.data_api_retry import retry_data_api, TRANSIENT_ERROR_CODES


def _client_error(code: str) -> ClientError:
    return ClientError(
        error_response={"Error": {"Code": code, "Message": "boom"}},
        operation_name="ExecuteStatement",
    )


def test_retry_succeeds_on_second_attempt(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(
        "collector.data_api_retry.time.sleep", lambda s: sleeps.append(s)
    )
    calls = {"n": 0}

    @retry_data_api(max_attempts=3, base_delay=0.1)
    def op() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise _client_error("DatabaseResumingException")
        return "ok"

    assert op() == "ok"
    assert calls["n"] == 2
    assert len(sleeps) == 1
    # base_delay=0.1, with up to 10% jitter
    assert 0.1 <= sleeps[0] <= 0.11


def test_retry_exhausts_and_reraises(monkeypatch):
    monkeypatch.setattr("collector.data_api_retry.time.sleep", lambda s: None)

    @retry_data_api(max_attempts=3, base_delay=0.01)
    def op() -> None:
        raise _client_error("DatabaseResumingException")

    with pytest.raises(ClientError):
        op()


def test_retry_skips_permanent_errors(monkeypatch):
    monkeypatch.setattr("collector.data_api_retry.time.sleep", lambda s: None)
    calls = {"n": 0}

    @retry_data_api(max_attempts=3, base_delay=0.01)
    def op() -> None:
        calls["n"] += 1
        raise _client_error("BadRequestException")

    with pytest.raises(ClientError):
        op()
    assert calls["n"] == 1  # no retry


def test_transient_codes_include_resuming_and_statement_timeout():
    assert "DatabaseResumingException" in TRANSIENT_ERROR_CODES
    assert "StatementTimeoutException" in TRANSIENT_ERROR_CODES

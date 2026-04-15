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
    # Full jitter: sleep is in [0, base_delay] for first attempt
    assert 0.0 <= sleeps[0] <= 0.1


def test_retry_propagates_non_client_error(monkeypatch):
    monkeypatch.setattr("collector.data_api_retry.time.sleep", lambda s: None)
    calls = {"n": 0}

    @retry_data_api(max_attempts=3, base_delay=0.01)
    def op() -> None:
        calls["n"] += 1
        raise ValueError("not a ClientError")

    with pytest.raises(ValueError):
        op()
    assert calls["n"] == 1  # no retry for non-ClientError


def test_retry_respects_max_delay_cap(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(
        "collector.data_api_retry.time.sleep", lambda s: sleeps.append(s)
    )

    @retry_data_api(max_attempts=6, base_delay=10.0, max_delay=15.0)
    def op() -> None:
        raise _client_error("DatabaseResumingException")

    with pytest.raises(ClientError):
        op()

    # 5 sleeps (6 attempts - 1). All must be capped at max_delay=15.
    assert len(sleeps) == 5
    for s in sleeps:
        assert 0.0 <= s <= 15.0


def test_transient_error_codes_full_set():
    expected = {
        "DatabaseResumingException",
        "StatementTimeoutException",
        "InternalServerErrorException",
        "ServiceUnavailableError",
        "ThrottlingException",
    }
    assert TRANSIENT_ERROR_CODES == expected


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

"""retry_vendor decorator tests (Plan 4 Task 3)."""

from __future__ import annotations

import pytest

from collector.errors import VendorAuthError, VendorQuotaError, VendorUnavailableError
from collector.vendor_match.retry import retry_vendor


def test_retry_on_unavailable_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _: None)
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise VendorUnavailableError("spotify", "timeout")
        return "ok"

    assert flaky() == "ok"
    assert calls["n"] == 3


def test_retry_honours_quota_retry_after(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("collector.vendor_match.retry.time.sleep", lambda s: slept.append(s))
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def limited() -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise VendorQuotaError("spotify", retry_after=5)
        return "ok"

    assert limited() == "ok"
    assert slept and slept[0] >= 5


def test_no_retry_on_auth_error(monkeypatch) -> None:
    monkeypatch.setattr("collector.vendor_match.retry.time.sleep", lambda _: None)
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def unauth() -> None:
        calls["n"] += 1
        raise VendorAuthError("spotify")

    with pytest.raises(VendorAuthError):
        unauth()
    assert calls["n"] == 1


def test_raises_after_exhausting_retries(monkeypatch) -> None:
    monkeypatch.setattr("collector.vendor_match.retry.time.sleep", lambda _: None)
    calls = {"n": 0}

    @retry_vendor(max_retries=3)
    def always_fail() -> None:
        calls["n"] += 1
        raise VendorUnavailableError("x", "down")

    with pytest.raises(VendorUnavailableError):
        always_fail()
    assert calls["n"] == 3

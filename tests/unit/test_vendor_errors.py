"""Vendor error class tests (Plan 4 Task 2)."""

from __future__ import annotations

import pytest

from collector.errors import (
    MatchFailedError,
    UserTokenMissingError,
    VendorAuthError,
    VendorQuotaError,
    VendorUnavailableError,
)


def test_vendor_unavailable_error_code() -> None:
    e = VendorUnavailableError("spotify", "timeout")
    assert e.status_code == 502
    assert e.error_code == "vendor_unavailable"
    assert "spotify" in e.message
    assert e.vendor == "spotify"
    assert e.reason == "timeout"


def test_vendor_auth_error_code() -> None:
    e = VendorAuthError("ytmusic")
    assert e.status_code == 403
    assert e.error_code == "vendor_auth_failed"
    assert e.vendor == "ytmusic"


def test_vendor_quota_error_includes_retry_after() -> None:
    e = VendorQuotaError("deezer", retry_after=60)
    assert e.status_code == 429
    assert e.error_code == "vendor_quota"
    assert e.retry_after == 60


def test_vendor_quota_error_retry_after_optional() -> None:
    e = VendorQuotaError("deezer")
    assert e.retry_after is None


def test_match_failed_error_non_http() -> None:
    e = MatchFailedError("apple", "low_confidence")
    assert e.error_code == "match_failed"
    assert e.vendor == "apple"
    assert e.reason == "low_confidence"
    assert isinstance(e, Exception)


def test_user_token_missing_error() -> None:
    e = UserTokenMissingError("user-1", "spotify")
    assert e.status_code == 400
    assert e.error_code == "user_token_missing"
    assert e.user_id == "user-1"
    assert e.vendor == "spotify"

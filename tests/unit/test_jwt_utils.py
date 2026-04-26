from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from collector.auth.jwt_utils import (
    AccessClaims,
    InvalidTokenError,
    RefreshClaims,
    issue_access_token,
    issue_refresh_token,
    verify_access_token,
    verify_refresh_token,
)


SECRET = "0" * 32


def test_access_token_round_trip() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET,
        user_id="u-1",
        session_id="s-1",
        is_admin=True,
        ttl_seconds=1800,
        now=now,
    )
    claims = verify_access_token(token=token, secret=SECRET, now=now)
    assert isinstance(claims, AccessClaims)
    assert claims.user_id == "u-1"
    assert claims.session_id == "s-1"
    assert claims.is_admin is True


def test_access_token_expired_rejected() -> None:
    issued_at = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET,
        user_id="u-1",
        session_id="s-1",
        is_admin=False,
        ttl_seconds=60,
        now=issued_at,
    )
    later = issued_at + timedelta(seconds=120)
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=token, secret=SECRET, now=later)


def test_access_token_tampered_signature_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    tampered = token[:-4] + "AAAA"
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=tampered, secret=SECRET, now=now)


def test_access_token_wrong_secret_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    with pytest.raises(InvalidTokenError):
        verify_access_token(token=token, secret="X" * 32, now=now)


def test_refresh_token_round_trip() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    token = issue_refresh_token(
        secret=SECRET, user_id="u", session_id="s", ttl_seconds=604800, now=now,
    )
    claims = verify_refresh_token(token=token, secret=SECRET, now=now)
    assert isinstance(claims, RefreshClaims)
    assert claims.user_id == "u"
    assert claims.session_id == "s"


def test_refresh_token_token_type_mismatch_rejected() -> None:
    now = datetime(2026, 4, 26, 12, 0, tzinfo=timezone.utc)
    access = issue_access_token(
        secret=SECRET, user_id="u", session_id="s", is_admin=False,
        ttl_seconds=60, now=now,
    )
    with pytest.raises(InvalidTokenError):
        verify_refresh_token(token=access, secret=SECRET, now=now)

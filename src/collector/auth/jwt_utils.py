"""HS256 JWT issue / verify helpers for spec-A access and refresh tokens."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt


_ALGO = "HS256"
_TYPE_ACCESS = "access"
_TYPE_REFRESH = "refresh"


class InvalidTokenError(Exception):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    is_admin: bool


@dataclass(frozen=True)
class RefreshClaims:
    user_id: str
    session_id: str


def issue_access_token(
    *,
    secret: str,
    user_id: str,
    session_id: str,
    is_admin: bool,
    ttl_seconds: int,
    now: datetime,
) -> str:
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "is_admin": is_admin,
        "typ": _TYPE_ACCESS,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def issue_refresh_token(
    *,
    secret: str,
    user_id: str,
    session_id: str,
    ttl_seconds: int,
    now: datetime,
) -> str:
    payload = {
        "sub": user_id,
        "session_id": session_id,
        "typ": _TYPE_REFRESH,
        "jti": uuid.uuid4().hex,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def verify_access_token(
    *, token: str, secret: str, now: datetime
) -> AccessClaims:
    payload = _decode(token=token, secret=secret, now=now, expected_type=_TYPE_ACCESS)
    try:
        return AccessClaims(
            user_id=str(payload["sub"]),
            session_id=str(payload["session_id"]),
            is_admin=bool(payload.get("is_admin", False)),
        )
    except KeyError as exc:
        raise InvalidTokenError(f"missing claim: {exc}") from exc


def verify_refresh_token(
    *, token: str, secret: str, now: datetime
) -> RefreshClaims:
    payload = _decode(token=token, secret=secret, now=now, expected_type=_TYPE_REFRESH)
    try:
        return RefreshClaims(
            user_id=str(payload["sub"]),
            session_id=str(payload["session_id"]),
        )
    except KeyError as exc:
        raise InvalidTokenError(f"missing claim: {exc}") from exc


def _decode(
    *, token: str, secret: str, now: datetime, expected_type: str
) -> dict:
    now_ts = int(now.astimezone(timezone.utc).timestamp())
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[_ALGO],
            options={
                "require": ["exp", "iat", "sub", "typ", "session_id"],
                "verify_exp": False,  # we check expiry manually below
                "verify_iat": False,  # iat may be in the future in tests
            },
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("typ") != expected_type:
        raise InvalidTokenError(
            f"token type mismatch: expected {expected_type}, got {payload.get('typ')}"
        )

    exp = int(payload["exp"])
    if now_ts >= exp:
        raise InvalidTokenError("token expired")

    return payload

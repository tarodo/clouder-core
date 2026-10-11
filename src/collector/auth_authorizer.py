"""API Gateway HTTP API Lambda Authorizer (simple-format) for spec-A JWTs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .auth.auth_settings import resolve_jwt_signing_key
from .auth.jwt_utils import InvalidTokenError, verify_access_token
from .logging_utils import log_event


def _now() -> datetime:
    return datetime.now(UTC)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    auth_header = _read_authorization(event)
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return {"isAuthorized": False}
    token = auth_header.split(" ", 1)[1].strip()
    if not token:
        return {"isAuthorized": False}

    try:
        secret = resolve_jwt_signing_key()  # cached with a TTL in auth_settings
        claims = verify_access_token(token=token, secret=secret, now=_now())
    except (InvalidTokenError, RuntimeError) as exc:
        log_event(
            "INFO",
            "authorizer_rejected",
            error_type=exc.__class__.__name__,
        )
        return {"isAuthorized": False}

    return {
        "isAuthorized": True,
        "context": {
            "user_id": claims.user_id,
            "session_id": claims.session_id,
            "is_admin": claims.is_admin,
        },
    }


def _read_authorization(event: Mapping[str, Any]) -> str | None:
    headers = event.get("headers") or {}
    if not isinstance(headers, Mapping):
        return None
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == "authorization" and isinstance(v, str):
            return v
    return None

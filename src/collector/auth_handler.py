"""Auth Lambda — /auth/login, /auth/callback, /auth/refresh, /auth/logout, /me."""

from __future__ import annotations

import json
import uuid
from typing import Any, Mapping

from .auth.auth_settings import (
    get_auth_settings,
    resolve_oauth_client_credentials,
)
from .auth.pkce import derive_code_challenge, generate_code_verifier
from .auth.spotify_oauth import SpotifyOAuthClient
from .errors import AppError, ValidationError
from .logging_utils import log_event


SPOTIFY_SCOPES = (
    "user-read-email user-read-private "
    "playlist-modify-public playlist-modify-private "
    "streaming user-read-playback-state user-modify-playback-state"
)


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    correlation_id = _correlation_id(event)
    try:
        return _route(event, context, correlation_id)
    except AppError as exc:
        log_event(
            "ERROR",
            "auth_request_failed",
            correlation_id=correlation_id,
            error_code=exc.error_code,
            status_code=exc.status_code,
            error_type=exc.__class__.__name__,
        )
        return _error_response(exc, correlation_id)
    except Exception as exc:  # pragma: no cover
        log_event(
            "ERROR",
            "auth_request_failed_unexpected",
            correlation_id=correlation_id,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
        )
        return _json_response(
            500,
            {"error_code": "internal_error", "message": "Internal server error",
             "correlation_id": correlation_id},
            correlation_id,
        )


def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route = _route_key(event)
    if route == "GET /auth/login":
        return _handle_login(event, correlation_id)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found",
         "correlation_id": correlation_id},
        correlation_id,
    )


def _handle_login(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    settings = get_auth_settings()
    query = event.get("queryStringParameters") or {}
    redirect = query.get("redirect_uri") if isinstance(query, Mapping) else None
    if redirect is not None and not settings.allows_redirect(redirect):
        raise ValidationError("redirect_uri not in allow-list")

    state = uuid.uuid4().hex
    verifier = generate_code_verifier()
    challenge = derive_code_challenge(verifier)

    cid, csec = resolve_oauth_client_credentials()
    oauth = SpotifyOAuthClient(
        client_id=cid,
        client_secret=csec,
        redirect_uri=settings.spotify_oauth_redirect_uri,
    )
    location = oauth.authorize_url(
        state=state, code_challenge=challenge, scopes=SPOTIFY_SCOPES
    )

    log_event(
        "INFO",
        "auth_login_redirect_issued",
        correlation_id=correlation_id,
    )

    cookies = [
        _short_cookie("oauth_state", state, max_age=600),
        _short_cookie("oauth_verifier", verifier, max_age=600),
    ]
    if redirect:
        cookies.append(_short_cookie("oauth_redirect", redirect, max_age=600))

    return {
        "statusCode": 302,
        "headers": {
            "location": location,
            "x-correlation-id": correlation_id,
        },
        "cookies": cookies,
        "body": "",
    }


def _short_cookie(name: str, value: str, *, max_age: int) -> str:
    return (
        f"{name}={value}; Path=/; HttpOnly; Secure; SameSite=Lax; "
        f"Max-Age={max_age}"
    )


def _correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers") or {}
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == "x-correlation-id" and isinstance(v, str) and v:
                return v
    return uuid.uuid4().hex


def _route_key(event: Mapping[str, Any]) -> str:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        rk = rc.get("routeKey")
        if isinstance(rk, str):
            return rk
    return ""


def _error_response(exc: AppError, correlation_id: str) -> dict[str, Any]:
    body = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    upgrade_url = getattr(exc, "upgrade_url", None)
    if upgrade_url is not None:
        body["upgrade_url"] = upgrade_url
    return _json_response(exc.status_code, body, correlation_id)


def _json_response(
    status_code: int, payload: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }

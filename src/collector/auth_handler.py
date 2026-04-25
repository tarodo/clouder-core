"""Auth Lambda — /auth/login, /auth/callback, /auth/refresh, /auth/logout, /me."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .auth.auth_repository import (
    AuthRepository,
    UpsertUserCmd,
    UpsertVendorTokenCmd,
)
from .auth.auth_settings import (
    get_auth_settings,
    resolve_jwt_signing_key,
    resolve_oauth_client_credentials,
)
from .auth.jwt_utils import (
    InvalidTokenError,
    issue_access_token,
    issue_refresh_token,
    verify_refresh_token,
)
from .auth.kms_envelope import EnvelopePayload, KmsEnvelope
from .auth.pkce import derive_code_challenge, generate_code_verifier
from .auth.spotify_oauth import (
    SpotifyOAuthClient,
    SpotifyOAuthError,
    SpotifyTokenRevokedError,
)
from .data_api import create_default_data_api_client
from .errors import (
    AppError,
    CsrfStateMismatchError,
    OAuthExchangeFailedError,
    PremiumRequiredError,
    RefreshInvalidError,
    RefreshReplayDetectedError,
    SpotifyRevokedError,
    ValidationError,
)
from .logging_utils import log_event
from .settings import get_data_api_settings


SPOTIFY_SCOPES = (
    "user-read-email user-read-private "
    "playlist-modify-public playlist-modify-private "
    "streaming user-read-playback-state user-modify-playback-state"
)


def _build_oauth_client() -> SpotifyOAuthClient:
    settings = get_auth_settings()
    cid, csec = resolve_oauth_client_credentials()
    return SpotifyOAuthClient(
        client_id=cid,
        client_secret=csec,
        redirect_uri=settings.spotify_oauth_redirect_uri,
    )


def _build_auth_repository() -> AuthRepository:
    db = get_data_api_settings()
    if not db.is_configured:
        raise RuntimeError("Aurora Data API not configured")
    return AuthRepository(
        data_api=create_default_data_api_client(
            resource_arn=str(db.aurora_cluster_arn),
            secret_arn=str(db.aurora_secret_arn),
            database=db.aurora_database,
        )
    )


def _build_kms_envelope() -> KmsEnvelope:
    import boto3

    settings = get_auth_settings()
    return KmsEnvelope(
        kms_client=boto3.client("kms"),
        key_arn=settings.kms_user_tokens_key_arn,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    if route == "GET /auth/callback":
        return _handle_callback(event, correlation_id)
    if route == "POST /auth/refresh":
        return _handle_refresh(event, correlation_id)
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


def _parse_cookies(event: Mapping[str, Any]) -> dict[str, str]:
    raw = event.get("cookies") or []
    out: dict[str, str] = {}
    for entry in raw:
        if isinstance(entry, str) and "=" in entry:
            k, v = entry.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _handle_callback(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    settings = get_auth_settings()
    query = event.get("queryStringParameters") or {}
    code = query.get("code") if isinstance(query, Mapping) else None
    state = query.get("state") if isinstance(query, Mapping) else None
    if not code or not state:
        raise ValidationError("code and state are required")

    cookies = _parse_cookies(event)
    if cookies.get("oauth_state") != state:
        raise CsrfStateMismatchError()
    verifier = cookies.get("oauth_verifier")
    if not verifier:
        raise CsrfStateMismatchError("missing oauth_verifier cookie")

    oauth = _build_oauth_client()
    try:
        tokens = oauth.exchange_code(code=code, code_verifier=verifier)
        profile = oauth.get_me(access_token=tokens.access_token)
    except SpotifyOAuthError as exc:
        raise OAuthExchangeFailedError(str(exc)) from exc

    if profile.product != "premium":
        raise PremiumRequiredError()

    repo = _build_auth_repository()
    envelope = _build_kms_envelope()
    now = _now()

    user_id = _resolve_user_id(repo, profile.spotify_id)
    is_admin = settings.is_admin(profile.spotify_id)
    repo.upsert_user(
        UpsertUserCmd(
            id=user_id,
            spotify_id=profile.spotify_id,
            display_name=profile.display_name,
            email=profile.email,
            is_admin=is_admin,
            now=now,
        )
    )

    access_payload = envelope.encrypt(tokens.access_token.encode("utf-8"))
    refresh_payload = envelope.encrypt(tokens.refresh_token.encode("utf-8"))
    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id=user_id,
            vendor="spotify",
            access_token_enc=access_payload.serialize(),
            refresh_token_enc=refresh_payload.serialize(),
            data_key_enc=access_payload.data_key_enc,
            scope=tokens.scope,
            expires_at=now + timedelta(seconds=tokens.expires_in),
            updated_at=now,
        )
    )

    session_id = uuid.uuid4().hex
    secret = resolve_jwt_signing_key()
    refresh_jwt = issue_refresh_token(
        secret=secret,
        user_id=user_id,
        session_id=session_id,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        now=now,
    )
    refresh_hash = _sha256_hex(refresh_jwt)
    repo.create_session(
        session_id=session_id,
        user_id=user_id,
        refresh_token_hash=refresh_hash,
        user_agent=_header(event, "user-agent"),
        ip_address=_source_ip(event),
        created_at=now,
        expires_at=now + timedelta(seconds=settings.refresh_token_ttl_seconds),
    )

    access_jwt = issue_access_token(
        secret=secret,
        user_id=user_id,
        session_id=session_id,
        is_admin=is_admin,
        ttl_seconds=settings.access_token_ttl_seconds,
        now=now,
    )

    response_body = {
        "access_token": access_jwt,
        "spotify_access_token": tokens.access_token,
        "expires_in": settings.access_token_ttl_seconds,
        "user": {
            "id": user_id,
            "spotify_id": profile.spotify_id,
            "display_name": profile.display_name,
            "is_admin": is_admin,
        },
        "correlation_id": correlation_id,
    }

    log_event(
        "INFO",
        "auth_callback_success",
        correlation_id=correlation_id,
        user_id=user_id,
        is_admin=is_admin,
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "cookies": [
            _refresh_cookie(refresh_jwt, max_age=settings.refresh_token_ttl_seconds),
            _short_cookie("oauth_state", "", max_age=0),
            _short_cookie("oauth_verifier", "", max_age=0),
        ],
        "body": json.dumps(response_body, ensure_ascii=False),
    }


def _handle_refresh(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    cookies = _parse_cookies(event)
    refresh_token = cookies.get("refresh_token")
    if not refresh_token:
        raise RefreshInvalidError()

    secret = resolve_jwt_signing_key()
    now = _now()
    try:
        claims = verify_refresh_token(token=refresh_token, secret=secret, now=now)
    except InvalidTokenError as exc:
        raise RefreshInvalidError() from exc

    repo = _build_auth_repository()
    session = repo.get_active_session(claims.session_id, now=now)
    if session is None or session.user_id != claims.user_id:
        raise RefreshInvalidError()

    inbound_hash = _sha256_hex(refresh_token)
    if session.refresh_token_hash != inbound_hash:
        repo.revoke_all_user_sessions(claims.user_id, revoked_at=now)
        raise RefreshReplayDetectedError()

    vendor_token = repo.get_vendor_token(user_id=claims.user_id, vendor="spotify")
    if vendor_token is None or vendor_token.refresh_token_enc is None:
        repo.revoke_session(claims.session_id, revoked_at=now)
        raise SpotifyRevokedError()

    envelope = _build_kms_envelope()
    refresh_payload = EnvelopePayload.deserialize(vendor_token.refresh_token_enc)
    spotify_refresh_token = envelope.decrypt(refresh_payload).decode("utf-8")

    oauth = _build_oauth_client()
    settings = get_auth_settings()
    try:
        new_tokens = oauth.refresh(refresh_token=spotify_refresh_token)
    except SpotifyTokenRevokedError as exc:
        repo.revoke_session(claims.session_id, revoked_at=now)
        repo.delete_vendor_token(user_id=claims.user_id, vendor="spotify")
        raise SpotifyRevokedError() from exc
    except SpotifyOAuthError as exc:
        raise OAuthExchangeFailedError(str(exc)) from exc

    user = repo.get_user_by_id(claims.user_id)
    is_admin = bool(user.is_admin) if user is not None else False

    new_access_payload = envelope.encrypt(new_tokens.access_token.encode("utf-8"))
    new_refresh_payload = envelope.encrypt(new_tokens.refresh_token.encode("utf-8"))
    repo.upsert_vendor_token(
        UpsertVendorTokenCmd(
            user_id=claims.user_id,
            vendor="spotify",
            access_token_enc=new_access_payload.serialize(),
            refresh_token_enc=new_refresh_payload.serialize(),
            data_key_enc=new_access_payload.data_key_enc,
            scope=new_tokens.scope or vendor_token.scope,
            expires_at=now + timedelta(seconds=new_tokens.expires_in),
            updated_at=now,
        )
    )

    new_refresh_jwt = issue_refresh_token(
        secret=secret,
        user_id=claims.user_id,
        session_id=claims.session_id,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        now=now,
    )
    repo.rotate_session(
        session_id=claims.session_id,
        new_hash=_sha256_hex(new_refresh_jwt),
        last_used_at=now,
    )

    new_access_jwt = issue_access_token(
        secret=secret,
        user_id=claims.user_id,
        session_id=claims.session_id,
        is_admin=is_admin,
        ttl_seconds=settings.access_token_ttl_seconds,
        now=now,
    )

    log_event(
        "INFO",
        "auth_refresh_success",
        correlation_id=correlation_id,
        user_id=claims.user_id,
    )

    return {
        "statusCode": 200,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "cookies": [
            _refresh_cookie(new_refresh_jwt, max_age=settings.refresh_token_ttl_seconds),
        ],
        "body": json.dumps(
            {
                "access_token": new_access_jwt,
                "spotify_access_token": new_tokens.access_token,
                "expires_in": settings.access_token_ttl_seconds,
                "correlation_id": correlation_id,
            },
            ensure_ascii=False,
        ),
    }


def _resolve_user_id(repo: AuthRepository, spotify_id: str) -> str:
    existing = repo.get_user_by_spotify_id(spotify_id)
    return str(existing.id) if existing else uuid.uuid4().hex


def _refresh_cookie(value: str, *, max_age: int) -> str:
    return (
        f"refresh_token={value}; Path=/auth/refresh; HttpOnly; Secure; "
        f"SameSite=Strict; Max-Age={max_age}"
    )


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _header(event: Mapping[str, Any], name: str) -> str | None:
    headers = event.get("headers") or {}
    if isinstance(headers, Mapping):
        for k, v in headers.items():
            if isinstance(k, str) and k.lower() == name and isinstance(v, str):
                return v
    return None


def _source_ip(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        http = rc.get("http")
        if isinstance(http, Mapping):
            ip = http.get("sourceIp")
            if isinstance(ip, str):
                return ip
    return None

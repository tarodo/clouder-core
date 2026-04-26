#!/usr/bin/env python3
"""Generate docs/openapi.yaml from pydantic schemas + a manual route table.

Usage:
    PYTHONPATH=src python scripts/generate_openapi.py

Strategy:
    - Import CollectRequestIn from collector.schemas; embed its JSON Schema.
    - For all other request/response bodies, declare inline schemas here
      because they're not (yet) backed by pydantic models.
    - Routes are declared as a single ROUTES table — keep in sync with
      infra/api_gateway.tf and infra/auth.tf when adding new endpoints.

Output: docs/openapi.yaml (OpenAPI 3.1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from collector.schemas import CollectRequestIn


# ── shared response schemas ────────────────────────────────────────────────

ERROR_RESPONSE = {
    "type": "object",
    "required": ["error_code", "message"],
    "properties": {
        "error_code": {"type": "string"},
        "message": {"type": "string"},
        "correlation_id": {"type": "string"},
        "upgrade_url": {
            "type": "string",
            "description": "Present only on premium_required (HTTP 403).",
        },
    },
}

PAGINATION_PARAMS = [
    {
        "name": "limit",
        "in": "query",
        "schema": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
    },
    {
        "name": "offset",
        "in": "query",
        "schema": {"type": "integer", "minimum": 0, "default": 0},
    },
    {
        "name": "search",
        "in": "query",
        "schema": {"type": "string"},
        "description": "Substring match on normalized name/title (case-insensitive).",
    },
]

LIST_RESPONSE_TEMPLATE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": {"type": "object"}},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

USER_PROFILE = {
    "type": "object",
    "required": ["id", "spotify_id", "is_admin"],
    "properties": {
        "id": {"type": "string"},
        "spotify_id": {"type": "string"},
        "display_name": {"type": "string", "nullable": True},
        "email": {"type": "string", "nullable": True},
        "is_admin": {"type": "boolean"},
    },
}

SESSION_ROW = {
    "type": "object",
    "required": ["id", "created_at", "last_used_at", "current"],
    "properties": {
        "id": {"type": "string"},
        "created_at": {"type": "string", "format": "date-time"},
        "last_used_at": {"type": "string", "format": "date-time"},
        "user_agent": {"type": "string", "nullable": True},
        "current": {"type": "boolean"},
    },
}

TOKEN_RESPONSE = {
    "type": "object",
    "required": ["access_token", "spotify_access_token", "expires_in"],
    "properties": {
        "access_token": {
            "type": "string",
            "description": "HS256 JWT; pass as `Authorization: Bearer <token>`.",
        },
        "spotify_access_token": {
            "type": "string",
            "description": "Spotify Web Playback SDK access token (Spotify-issued).",
        },
        "expires_in": {
            "type": "integer",
            "description": "Lifetime of access_token in seconds.",
        },
        "user": {"$ref": "#/components/schemas/UserProfile"},
        "correlation_id": {"type": "string"},
    },
}

RUN_RESPONSE = {
    "type": "object",
    "required": ["run_id", "status"],
    "properties": {
        "run_id": {"type": "string", "format": "uuid"},
        "status": {
            "type": "string",
            "enum": [
                "RAW_SAVED",
                "QUEUED",
                "PROCESSING",
                "COMPLETED",
                "FAILED",
            ],
        },
        "processed_counts": {
            "type": "object",
            "properties": {
                "processed": {"type": "integer"},
                "total": {"type": "integer"},
            },
        },
        "error": {
            "type": "object",
            "nullable": True,
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "phase": {"type": "string"},
            },
        },
        "started_at": {"type": "string", "format": "date-time", "nullable": True},
        "finished_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

COLLECT_RESPONSE = {
    "type": "object",
    "properties": {
        "run_id": {"type": "string", "format": "uuid"},
        "iso_year": {"type": "integer"},
        "iso_week": {"type": "integer"},
        "s3_object_key": {"type": "string"},
        "item_count": {"type": "integer"},
        "duration_ms": {"type": "integer"},
        "run_status": {"type": "string"},
        "processing_status": {
            "type": "string",
            "enum": ["QUEUED", "FAILED_TO_QUEUE"],
        },
        "processing_outcome": {"type": "string"},
        "processing_reason": {"type": "string", "nullable": True},
        "search_labels_enqueued": {
            "type": "integer",
            "description": "Count of labels sent to AI search SQS. Zero if `search_label_count` was omitted.",
        },
    },
}

ME_RESPONSE = {
    "allOf": [
        {"$ref": "#/components/schemas/UserProfile"},
        {
            "type": "object",
            "required": ["sessions"],
            "properties": {
                "sessions": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/SessionRow"},
                },
            },
        },
    ]
}

REFRESH_RESPONSE = {
    "type": "object",
    "required": ["access_token", "spotify_access_token", "expires_in"],
    "properties": {
        "access_token": {"type": "string"},
        "spotify_access_token": {"type": "string"},
        "expires_in": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}


# ── routes ────────────────────────────────────────────────────────────────

PUBLIC = "public"
AUTH = "user"
ADMIN = "admin"


def _make_response(status: int, description: str, schema: dict | None = None) -> dict:
    response: dict[str, Any] = {"description": description}
    if schema is not None:
        response["content"] = {"application/json": {"schema": schema}}
    return response


def _error(code: int, description: str) -> dict:
    return _make_response(code, description, {"$ref": "#/components/schemas/ErrorResponse"})


COMMON_AUTH_ERRORS = {
    "401": _error(401, "Missing or invalid bearer token."),
    "403": _error(403, "Authenticated but lacks required role (admin)."),
}


ROUTES: list[dict[str, Any]] = [
    # ── auth ───────────────────────────────────────────────────────────
    {
        "method": "get",
        "path": "/auth/login",
        "auth": PUBLIC,
        "summary": "Start Spotify OAuth flow.",
        "description": (
            "Generates PKCE state + verifier cookies, then 302-redirects to "
            "`accounts.spotify.com/authorize`. Cookies are HttpOnly Secure SameSite=Lax, max_age=600."
        ),
        "parameters": [
            {
                "name": "redirect_uri",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Optional frontend-relative path to bounce back to after successful login. Must be in ALLOWED_FRONTEND_REDIRECTS.",
            }
        ],
        "responses": {
            "302": {
                "description": "Redirect to Spotify consent.",
                "headers": {
                    "Location": {"schema": {"type": "string", "format": "uri"}},
                    "Set-Cookie": {
                        "schema": {"type": "string"},
                        "description": "Sets oauth_state and oauth_verifier cookies.",
                    },
                },
            },
            "400": _error(400, "redirect_uri not in allow-list."),
        },
    },
    {
        "method": "get",
        "path": "/auth/callback",
        "auth": PUBLIC,
        "summary": "Complete Spotify OAuth flow.",
        "description": (
            "Validates state cookie, exchanges code for Spotify tokens, blocks non-Premium users, "
            "creates session, issues JWT access+refresh tokens. Sets refresh_token cookie "
            "(HttpOnly Secure SameSite=Strict, Path=/auth/refresh, max_age=7d)."
        ),
        "parameters": [
            {"name": "code", "in": "query", "required": True, "schema": {"type": "string"}},
            {"name": "state", "in": "query", "required": True, "schema": {"type": "string"}},
        ],
        "responses": {
            "200": _make_response(
                200,
                "Login succeeded. Returns JWT and Spotify access token.",
                {"$ref": "#/components/schemas/TokenResponse"},
            ),
            "400": _error(400, "csrf_state_mismatch."),
            "403": _error(
                403,
                "premium_required. Body includes upgrade_url. No DB write performed.",
            ),
            "502": _error(502, "oauth_exchange_failed (Spotify HTTP error)."),
        },
    },
    {
        "method": "post",
        "path": "/auth/refresh",
        "auth": PUBLIC,
        "summary": "Rotate access + refresh tokens.",
        "description": (
            "Reads refresh-JWT from cookie, verifies session, decrypts stored Spotify "
            "refresh-token via KMS, calls Spotify refresh-grant, re-encrypts new tokens, "
            "rotates session. Sets new refresh_token cookie."
        ),
        "responses": {
            "200": _make_response(
                200,
                "New JWT and Spotify access token issued.",
                {"$ref": "#/components/schemas/RefreshResponse"},
            ),
            "401": _error(
                401,
                "refresh_invalid (missing/expired/invalid cookie), refresh_replay_detected "
                "(old refresh token reused — all sessions revoked), or spotify_revoked "
                "(Spotify returned invalid_grant; vendor token deleted, re-OAuth required).",
            ),
        },
    },
    {
        "method": "post",
        "path": "/auth/logout",
        "auth": PUBLIC,
        "summary": "Log out current session.",
        "description": (
            "Reads refresh-JWT cookie, marks session as revoked. Idempotent: returns 204 "
            "even if cookie is missing or invalid."
        ),
        "responses": {
            "204": {"description": "Logged out (or no-op if no valid session)."}
        },
    },
    # ── /me + session management ────────────────────────────────────
    {
        "method": "get",
        "path": "/me",
        "auth": AUTH,
        "summary": "Current user profile + active sessions.",
        "responses": {
            "200": _make_response(
                200,
                "User and active sessions.",
                {"$ref": "#/components/schemas/MeResponse"},
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/me/sessions/{session_id}",
        "auth": AUTH,
        "summary": "Revoke one of the current user's sessions.",
        "description": "Cannot revoke the current session (use /auth/logout instead).",
        "parameters": [
            {
                "name": "session_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "responses": {
            "204": {"description": "Session revoked."},
            "400": _error(400, "cannot_revoke_current."),
            "404": _error(
                404,
                "Session does not belong to the calling user (or does not exist).",
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── ingest (admin only) ────────────────────────────────────────
    {
        "method": "post",
        "path": "/collect_bp_releases",
        "auth": ADMIN,
        "summary": "Trigger Beatport weekly releases ingest.",
        "description": (
            "Fetches Beatport releases for the given ISO week + style, writes raw "
            "snapshot to S3, enqueues canonicalization (and optionally AI label search "
            "if `search_label_count` provided)."
        ),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/CollectRequestIn"},
                }
            },
        },
        "responses": {
            "200": _make_response(
                200,
                "Run created. Ingest enqueued (or skipped if disabled).",
                {"$ref": "#/components/schemas/CollectResponse"},
            ),
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
            "502": _error(502, "beatport_unavailable / spotify_unavailable."),
        },
    },
    {
        "method": "get",
        "path": "/runs/{run_id}",
        "auth": AUTH,
        "summary": "Get status of an ingest run.",
        "parameters": [
            {
                "name": "run_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Run status.",
                {"$ref": "#/components/schemas/RunResponse"},
            ),
            "404": _error(404, "Run not found."),
            "503": _error(503, "db_not_configured (AURORA_* env vars missing)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── canonical core (any authenticated user) ───────────────────
    *[
        {
            "method": "get",
            "path": f"/{entity}",
            "auth": AUTH,
            "summary": f"List {entity} (paginated).",
            "parameters": PAGINATION_PARAMS,
            "responses": {
                "200": _make_response(
                    200,
                    "Paginated items.",
                    LIST_RESPONSE_TEMPLATE,
                ),
                "400": _error(400, "validation_error (limit/offset out of range)."),
                "503": _error(503, "db_not_configured."),
                **COMMON_AUTH_ERRORS,
            },
        }
        for entity in ("tracks", "artists", "albums", "labels", "styles")
    ],
    {
        "method": "get",
        "path": "/tracks/spotify-not-found",
        "auth": ADMIN,
        "summary": "List tracks searched on Spotify but not matched.",
        "parameters": PAGINATION_PARAMS,
        "responses": {
            "200": _make_response(200, "Paginated items.", LIST_RESPONSE_TEMPLATE),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
]


# ── builder ───────────────────────────────────────────────────────────

def _security_for(auth: str) -> list[dict[str, Any]]:
    if auth == PUBLIC:
        return []
    return [{"BearerAuth": []}]


def _operation(route: dict) -> dict:
    op: dict[str, Any] = {
        "summary": route["summary"],
        "responses": route["responses"],
    }
    if "description" in route:
        op["description"] = route["description"]
    if "parameters" in route:
        op["parameters"] = route["parameters"]
    if "requestBody" in route:
        op["requestBody"] = route["requestBody"]
    op["security"] = _security_for(route["auth"])
    op["tags"] = {
        PUBLIC: ["auth"],
        AUTH: ["user"],
        ADMIN: ["admin"],
    }[route["auth"]]
    return op


def _collect_pydantic_schemas() -> dict[str, Any]:
    """Pull JSON Schemas from pydantic models, rewriting refs into the OpenAPI namespace."""
    collect_schema = CollectRequestIn.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    schemas = {"CollectRequestIn": collect_schema}
    # Promote any nested $defs into top-level components.schemas.
    if "$defs" in collect_schema:
        for name, sub in collect_schema.pop("$defs").items():
            schemas[name] = sub
    return schemas


def build_openapi() -> dict[str, Any]:
    pyd_schemas = _collect_pydantic_schemas()

    paths: dict[str, dict[str, dict]] = {}
    for route in ROUTES:
        path = route["path"]
        method = route["method"]
        paths.setdefault(path, {})[method] = _operation(route)

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "Clouder Core API",
            "version": "1.0.0",
            "description": (
                "Beatport ingest pipeline + Spotify OAuth user auth (spec-A).\n\n"
                "Authorization: most routes require a Bearer JWT issued by `/auth/callback` "
                "or `/auth/refresh`. Admin-only routes additionally require `is_admin=true` "
                "on the JWT (set from `ADMIN_SPOTIFY_IDS` env var on each login).\n\n"
                "**Generated** by `scripts/generate_openapi.py` — do not edit by hand."
            ),
        },
        "servers": [
            {
                "url": "https://{api_id}.execute-api.{region}.amazonaws.com",
                "variables": {
                    "api_id": {"default": "<api-id>"},
                    "region": {"default": "us-east-1"},
                },
            }
        ],
        "tags": [
            {"name": "auth", "description": "Public OAuth + session-cookie endpoints."},
            {"name": "user", "description": "Routes for any authenticated user."},
            {"name": "admin", "description": "Admin-gated ingest endpoints."},
        ],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                    "bearerFormat": "JWT",
                    "description": "HS256 JWT issued by /auth/callback or /auth/refresh.",
                }
            },
            "schemas": {
                **pyd_schemas,
                "ErrorResponse": ERROR_RESPONSE,
                "UserProfile": USER_PROFILE,
                "SessionRow": SESSION_ROW,
                "TokenResponse": TOKEN_RESPONSE,
                "RefreshResponse": REFRESH_RESPONSE,
                "MeResponse": ME_RESPONSE,
                "RunResponse": RUN_RESPONSE,
                "CollectResponse": COLLECT_RESPONSE,
            },
        },
    }


def main() -> int:
    spec = build_openapi()
    out = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# AUTO-GENERATED by scripts/generate_openapi.py — do not edit by hand.\n"
        + yaml.safe_dump(spec, sort_keys=False, default_flow_style=False, allow_unicode=True)
    )
    print(f"wrote {out}  ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

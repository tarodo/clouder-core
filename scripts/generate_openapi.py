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

import os
from pathlib import Path
from typing import Any

import yaml

from collector.curation.schemas import (
    CreateTriageBlockIn,
    MoveTracksIn,
    TransferTracksIn,
)
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

CATEGORY_RESPONSE = {
    "type": "object",
    "required": [
        "id", "style_id", "style_name", "name",
        "position", "track_count", "created_at", "updated_at",
    ],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "style_id": {"type": "string", "format": "uuid"},
        "style_name": {"type": "string"},
        "name": {"type": "string"},
        "position": {"type": "integer"},
        "track_count": {"type": "integer"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "correlation_id": {"type": "string"},
    },
}

CATEGORY_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": CATEGORY_RESPONSE},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

CATEGORY_TRACK_RESPONSE = {
    "type": "object",
    "description": (
        "Full clouder_tracks row plus added_at and source_triage_block_id "
        "(NULL for direct adds, set by spec-D triage finalize)."
    ),
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "title": {"type": "string"},
        "mix_name": {"type": ["string", "null"]},
        "isrc": {"type": ["string", "null"]},
        "bpm": {"type": ["integer", "null"]},
        "length_ms": {"type": ["integer", "null"]},
        "publish_date": {"type": ["string", "null"]},
        "spotify_id": {"type": ["string", "null"]},
        "release_type": {"type": ["string", "null"]},
        "is_ai_suspected": {"type": "boolean"},
        "artists": {"type": "array", "items": {"type": "string"}},
        "added_at": {"type": "string"},
        "source_triage_block_id": {"type": ["string", "null"]},
    },
}

CATEGORY_TRACKS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": CATEGORY_TRACK_RESPONSE},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

ADD_TRACK_RESPONSE = {
    "type": "object",
    "required": ["result", "added_at"],
    "properties": {
        "result": {
            "type": "string",
            "enum": ["added", "already_present"],
        },
        "added_at": {"type": "string"},
        "source_triage_block_id": {"type": ["string", "null"]},
        "correlation_id": {"type": "string"},
    },
}

REORDER_RESPONSE = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {"type": "array", "items": CATEGORY_RESPONSE},
        "correlation_id": {"type": "string"},
    },
}

# ── triage (spec-D) response shapes ───────────────────────────────────────

TRIAGE_BUCKET_ROW = {
    "type": "object",
    "required": ["id", "bucket_type", "inactive", "track_count"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "bucket_type": {
            "type": "string",
            "enum": [
                "NEW",
                "OLD",
                "NOT",
                "DISCARD",
                "UNCLASSIFIED",
                "STAGING",
            ],
        },
        "category_id": {
            "type": ["string", "null"],
            "format": "uuid",
            "description": (
                "NULL for the five technical buckets; populated for STAGING "
                "buckets that mirror a clouder_categories row."
            ),
        },
        "category_name": {"type": ["string", "null"]},
        "inactive": {
            "type": "boolean",
            "description": (
                "True when the linked category was soft-deleted after the "
                "STAGING bucket was created."
            ),
        },
        "track_count": {"type": "integer"},
    },
}

TRIAGE_BLOCK_DETAIL = {
    "type": "object",
    "required": [
        "id", "style_id", "style_name", "name",
        "date_from", "date_to", "status",
        "created_at", "updated_at", "buckets",
    ],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "style_id": {"type": "string", "format": "uuid"},
        "style_name": {"type": "string"},
        "name": {"type": "string"},
        "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "status": {
            "type": "string",
            "enum": ["IN_PROGRESS", "FINALIZED"],
        },
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "finalized_at": {"type": ["string", "null"]},
        "buckets": {
            "type": "array",
            "items": TRIAGE_BUCKET_ROW,
        },
        "correlation_id": {"type": "string"},
    },
}

TRIAGE_BLOCK_SUMMARY = {
    "type": "object",
    "required": [
        "id", "style_id", "style_name", "name",
        "date_from", "date_to", "status",
        "created_at", "updated_at", "track_count",
    ],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "style_id": {"type": "string", "format": "uuid"},
        "style_name": {"type": "string"},
        "name": {"type": "string"},
        "date_from": {"type": "string", "format": "date"},
        "date_to": {"type": "string", "format": "date"},
        "status": {
            "type": "string",
            "enum": ["IN_PROGRESS", "FINALIZED"],
        },
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
        "finalized_at": {"type": ["string", "null"]},
        "track_count": {"type": "integer"},
    },
}

TRIAGE_BLOCK_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": TRIAGE_BLOCK_SUMMARY},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

BUCKET_TRACK_ROW = {
    "type": "object",
    "required": [
        "track_id", "title", "is_ai_suspected", "artists", "added_at",
    ],
    "properties": {
        "track_id": {"type": "string", "format": "uuid"},
        "title": {"type": "string"},
        "mix_name": {"type": ["string", "null"]},
        "isrc": {"type": ["string", "null"]},
        "bpm": {"type": ["integer", "null"]},
        "length_ms": {"type": ["integer", "null"]},
        "publish_date": {"type": ["string", "null"]},
        "spotify_release_date": {"type": ["string", "null"]},
        "spotify_id": {"type": ["string", "null"]},
        "release_type": {"type": ["string", "null"]},
        "is_ai_suspected": {"type": "boolean"},
        "artists": {"type": "array", "items": {"type": "string"}},
        "added_at": {"type": "string"},
    },
}

BUCKET_TRACKS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": BUCKET_TRACK_ROW},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

MOVE_TRACKS_OUT = {
    "type": "object",
    "required": ["moved"],
    "properties": {
        "moved": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

TRANSFER_TRACKS_OUT = {
    "type": "object",
    "required": ["transferred"],
    "properties": {
        "transferred": {"type": "integer"},
        "correlation_id": {"type": "string"},
    },
}

FINALIZE_OUT = {
    "type": "object",
    "required": ["block", "promoted"],
    "properties": {
        "block": TRIAGE_BLOCK_DETAIL,
        "promoted": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
            "description": (
                "Per-category promoted track counts keyed by category_id."
            ),
        },
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
        "request_example": {
            "iso_year": 2026,
            "iso_week": 17,
            "style_id": 90,
            "bp_token": "REDACTED",
            "search_label_count": 10,
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
    # ── curation: categories (spec-C) ──────────────────────────────
    {
        "method": "post",
        "path": "/styles/{style_id}/categories",
        "auth": AUTH,
        "summary": "Create a category in a style (spec-C Layer 1).",
        "description": (
            "Aurora-only. UUID issued server-side. position assigned at MAX(position)+1 "
            "within (user_id, style_id, deleted_at IS NULL)."
        ),
        "parameters": [
            {"name": "style_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 64}},
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Tribal essentials"},
        "responses": {
            "201": _make_response(201, "Category created.", CATEGORY_RESPONSE),
            "404": _error(404, "style_not_found."),
            "409": _error(409, "name_conflict (normalized name already exists in style)."),
            "422": _error(422, "validation_error (empty/whitespace/>64/control chars)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/styles/{style_id}/categories",
        "auth": AUTH,
        "summary": "List categories of a style (paginated, ordered by position).",
        "parameters": [
            {"name": "style_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            *PAGINATION_PARAMS,
        ],
        "responses": {
            "200": _make_response(200, "Paginated categories.", CATEGORY_LIST_RESPONSE),
            "404": _error(404, "style_not_found."),
            "422": _error(422, "validation_error (limit/offset out of range)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "put",
        "path": "/styles/{style_id}/categories/order",
        "auth": AUTH,
        "summary": "Replace category order in a style (full-list).",
        "description": (
            "Body must be the exact set of non-deleted categories in this style. "
            "422 order_mismatch on extra/missing/duplicate ids."
        ),
        "parameters": [
            {"name": "style_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["category_ids"],
                "properties": {"category_ids": {"type": "array", "items": {"type": "string", "format": "uuid"}}},
                "additionalProperties": False,
            }}},
        },
        "request_example": {
            "category_ids": [
                "11111111-1111-1111-1111-111111111111",
                "22222222-2222-2222-2222-222222222222",
                "33333333-3333-3333-3333-333333333333",
            ]
        },
        "responses": {
            "200": _make_response(200, "Reordered categories in their new order.", REORDER_RESPONSE),
            "404": _error(404, "style_not_found."),
            "422": _error(422, "order_mismatch (set of ids does not equal the alive set)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/categories",
        "auth": AUTH,
        "summary": "List all of the user's categories across styles.",
        "parameters": PAGINATION_PARAMS,
        "responses": {
            "200": _make_response(200, "Paginated categories.", CATEGORY_LIST_RESPONSE),
            "422": _error(422, "validation_error (limit/offset out of range)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/categories/{id}",
        "auth": AUTH,
        "summary": "Get one category.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Category.", CATEGORY_RESPONSE),
            "404": _error(404, "category_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "patch",
        "path": "/categories/{id}",
        "auth": AUTH,
        "summary": "Rename category. style_id is immutable.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 64}},
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Renamed category"},
        "responses": {
            "200": _make_response(200, "Renamed category.", CATEGORY_RESPONSE),
            "404": _error(404, "category_not_found."),
            "409": _error(409, "name_conflict."),
            "422": _error(422, "validation_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/categories/{id}",
        "auth": AUTH,
        "summary": "Soft-delete category. Tracks remain in category_tracks but are filtered.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Soft-deleted."},
            "404": _error(404, "category_not_found (or already deleted)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/categories/{id}/tracks",
        "auth": AUTH,
        "summary": "List tracks in a category.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            *PAGINATION_PARAMS,
            {
                "name": "search",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Lowercased + trimmed before matching against clouder_tracks.normalized_title (ILIKE %term%).",
            },
        ],
        "responses": {
            "200": _make_response(200, "Paginated tracks.", CATEGORY_TRACKS_LIST_RESPONSE),
            "404": _error(404, "category_not_found."),
            "422": _error(422, "validation_error (limit/offset out of range)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/categories/{id}/tracks",
        "auth": AUTH,
        "summary": "Add a track to a category. Idempotent on (category_id, track_id).",
        "description": (
            "201 with result='added' if newly inserted; 200 with result='already_present' "
            "if the (category, track) pair already exists. First-write-wins on added_at + source."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["track_id"],
                "properties": {"track_id": {"type": "string", "format": "uuid"}},
                "additionalProperties": False,
            }}},
        },
        "request_example": {"track_id": "aaaaaaaa-1111-1111-1111-111111111111"},
        "responses": {
            "201": _make_response(201, "Track added.", ADD_TRACK_RESPONSE),
            "200": _make_response(200, "Track already in category (no change).", ADD_TRACK_RESPONSE),
            "404": _error(404, "category_not_found or track_not_found."),
            "422": _error(422, "validation_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/categories/{id}/tracks/{track_id}",
        "auth": AUTH,
        "summary": "Remove a track from a category (hard delete of the membership row).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Track removed."},
            "404": _error(404, "category_not_found or track_not_in_category."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── curation: triage blocks (spec-D) ───────────────────────────
    {
        "method": "post",
        "path": "/triage/blocks",
        "auth": AUTH,
        "summary": "Create a triage block + 5 technical buckets + STAGING per category.",
        "description": (
            "Aurora-only. Snapshots `clouder_categories` for the style into STAGING "
            "buckets at create time; subsequent category renames/deletes do not "
            "retroactively mutate the block. Tracks are classified into "
            "NEW/OLD/NOT/UNCLASSIFIED by `spotify_release_date` + `release_type` "
            "vs `date_from` (R4 in the spec)."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/CreateTriageBlockIn",
            }}},
        },
        "request_example": {
            "style_id": "11111111-1111-1111-1111-111111111111",
            "name": "House — week 17",
            "date_from": "2026-04-21",
            "date_to": "2026-04-28",
        },
        "responses": {
            "201": _make_response(201, "Block created.", TRIAGE_BLOCK_DETAIL),
            "404": _error(404, "style_not_found."),
            "422": _error(422, "validation_error (blank name, date_to < date_from, etc.)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/triage/blocks",
        "auth": AUTH,
        "summary": "List the user's triage blocks across styles (paginated).",
        "parameters": [
            *PAGINATION_PARAMS,
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string", "enum": ["IN_PROGRESS", "FINALIZED"]},
                "description": "Optional status filter.",
            },
        ],
        "responses": {
            "200": _make_response(
                200, "Paginated triage block summaries.", TRIAGE_BLOCK_LIST_RESPONSE
            ),
            "422": _error(422, "validation_error (limit/offset/status invalid)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/styles/{style_id}/triage/blocks",
        "auth": AUTH,
        "summary": "List the user's triage blocks for a style (paginated).",
        "parameters": [
            {"name": "style_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            *PAGINATION_PARAMS,
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string", "enum": ["IN_PROGRESS", "FINALIZED"]},
                "description": "Optional status filter.",
            },
        ],
        "responses": {
            "200": _make_response(
                200, "Paginated triage block summaries.", TRIAGE_BLOCK_LIST_RESPONSE
            ),
            "422": _error(422, "validation_error (limit/offset/status invalid)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/triage/blocks/{id}",
        "auth": AUTH,
        "summary": "Get one triage block with its buckets + per-bucket counts.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Triage block detail.", TRIAGE_BLOCK_DETAIL),
            "404": _error(404, "triage_block_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/triage/blocks/{id}/buckets/{bucket_id}/tracks",
        "auth": AUTH,
        "summary": "List tracks in a bucket (paginated, optional search).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            {"name": "bucket_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            *PAGINATION_PARAMS,
        ],
        "responses": {
            "200": _make_response(
                200, "Paginated bucket tracks.", BUCKET_TRACKS_LIST_RESPONSE
            ),
            "404": _error(404, "triage_block_not_found or bucket_not_found."),
            "422": _error(422, "validation_error (limit/offset out of range)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/triage/blocks/{id}/move",
        "auth": AUTH,
        "summary": "Move tracks between two buckets within one triage block.",
        "description": (
            "Both buckets must belong to the same block. Capped at "
            "1000 track_ids per call. Idempotent: tracks already in `to_bucket_id` "
            "are silently no-op (counted in `moved` only when actually moved)."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/MoveTracksIn",
            }}},
        },
        "request_example": {
            "from_bucket_id": "11111111-1111-1111-1111-111111111111",
            "to_bucket_id": "22222222-2222-2222-2222-222222222222",
            "track_ids": [
                "aaaaaaaa-1111-1111-1111-111111111111",
                "bbbbbbbb-2222-2222-2222-222222222222",
            ],
        },
        "responses": {
            "200": _make_response(200, "Tracks moved.", MOVE_TRACKS_OUT),
            "404": _error(404, "triage_block_not_found / bucket_not_found / tracks_not_in_source."),
            "409": _error(409, "invalid_state (block is FINALIZED) or inactive_bucket."),
            "422": _error(422, "validation_error (track_ids empty / >1000 / non-uuid)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/triage/blocks/{src_id}/transfer",
        "auth": AUTH,
        "summary": "Transfer tracks from one IN_PROGRESS block to a bucket in another.",
        "description": (
            "Source and target blocks must share the same style. Target block must "
            "be IN_PROGRESS and the target bucket must not be inactive. Tracks "
            "leave the source block entirely (deleted from source bucket membership)."
        ),
        "parameters": [
            {"name": "src_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "$ref": "#/components/schemas/TransferTracksIn",
            }}},
        },
        "request_example": {
            "target_bucket_id": "44444444-4444-4444-4444-444444444444",
            "track_ids": ["aaaaaaaa-1111-1111-1111-111111111111"],
        },
        "responses": {
            "200": _make_response(200, "Tracks transferred.", TRANSFER_TRACKS_OUT),
            "404": _error(404, "triage_block_not_found / bucket_not_found / tracks_not_in_source."),
            "409": _error(
                409,
                "invalid_state (target block not IN_PROGRESS), "
                "inactive_bucket, or style_mismatch.",
            ),
            "422": _error(422, "validation_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/triage/blocks/{id}/finalize",
        "auth": AUTH,
        "summary": "Finalize triage block and promote STAGING tracks into clouder_categories.",
        "description": (
            "Promotes every track in each STAGING bucket into the linked "
            "`clouder_categories` row via category_tracks (idempotent insert). "
            "Sets `source_triage_block_id` on each newly added category_tracks "
            "row. Block status flips to FINALIZED. Idempotent on repeated calls."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Triage block finalized.", FINALIZE_OUT),
            "404": _error(404, "triage_block_not_found."),
            "409": _error(
                409,
                "inactive_staging_finalize (one or more STAGING buckets reference "
                "a soft-deleted category — UI must transfer/empty them first).",
            ),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/triage/blocks/{id}",
        "auth": AUTH,
        "summary": "Soft-delete a triage block.",
        "description": (
            "Sets `deleted_at` on the triage_blocks row; bucket and track-membership "
            "rows are filtered by the join, not hard-deleted. Idempotent: returns "
            "404 only if the block never existed for this user."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Triage block soft-deleted."},
            "404": _error(404, "triage_block_not_found (or already deleted)."),
            **COMMON_AUTH_ERRORS,
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
        if "request_example" in route:
            op["requestBody"]["content"]["application/json"]["example"] = route[
                "request_example"
            ]
    op["security"] = _security_for(route["auth"])
    op["tags"] = {
        PUBLIC: ["auth"],
        AUTH: ["user"],
        ADMIN: ["admin"],
    }[route["auth"]]
    return op


def _collect_pydantic_schemas() -> dict[str, Any]:
    """Pull JSON Schemas from pydantic models, rewriting refs into the OpenAPI namespace."""
    schemas: dict[str, Any] = {}
    for name, model in (
        ("CollectRequestIn", CollectRequestIn),
        ("CreateTriageBlockIn", CreateTriageBlockIn),
        ("MoveTracksIn", MoveTracksIn),
        ("TransferTracksIn", TransferTracksIn),
    ):
        js = model.model_json_schema(
            ref_template="#/components/schemas/{model}"
        )
        # Promote any nested $defs into top-level components.schemas.
        if "$defs" in js:
            for sub_name, sub in js.pop("$defs").items():
                schemas[sub_name] = sub
        schemas[name] = js
    return schemas


_DEFAULT_SERVER_URL = "https://{api_id}.execute-api.{region}.amazonaws.com"


def _build_server() -> dict[str, Any]:
    url = os.environ.get("OPENAPI_SERVER_URL", _DEFAULT_SERVER_URL)
    is_template = url == _DEFAULT_SERVER_URL
    server: dict[str, Any] = {
        "url": url,
        "description": (
            "Default API Gateway invoke URL template. Override via the "
            "OPENAPI_SERVER_URL env var when regenerating to embed a concrete "
            "staging or prod URL (`terraform output -raw api_invoke_url`)."
            if is_template
            else "API Gateway invoke URL embedded at spec generation time."
        ),
    }
    if is_template:
        server["variables"] = {
            "api_id": {"default": "<api-id>"},
            "region": {"default": "us-east-1"},
        }
    return server


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
                "Beatport ingest pipeline + Spotify OAuth user auth (spec-A) "
                "+ category/triage curation (spec-C/D).\n\n"
                "## Authentication\n\n"
                "All endpoints except `/auth/login` and `/auth/callback` require a "
                "JWT Bearer token in `Authorization: Bearer <token>`.\n\n"
                "**How to get a token (manual / Postman flow):**\n"
                "1. Open `GET /auth/login` in a browser → redirects to Spotify consent.\n"
                "2. After approve, Spotify redirects to `/auth/callback?code=...&state=...`.\n"
                "3. Callback returns JSON `{access_token, refresh_token, expires_in}`.\n"
                "4. Use `access_token` in `Authorization: Bearer ...` for every subsequent call.\n"
                "5. When `access_token` expires (default ~1h), `POST /auth/refresh` "
                "with `{\"refresh_token\": \"...\"}` → new pair.\n\n"
                "## Admin endpoints\n\n"
                "`POST /collect_bp_releases` and `GET /tracks/spotify-not-found` require "
                "`is_admin=true` on the JWT, set from the `ADMIN_SPOTIFY_IDS` env var on each login.\n\n"
                "## Error envelope\n\n"
                "All domain errors return `{error_code, message, correlation_id}`. "
                "API Gateway 503 (cold-start timeout) returns `{\"message\":\"Service Unavailable\"}` "
                "(capital S/U) — retry the request after a few seconds.\n\n"
                "**Generated** by `scripts/generate_openapi.py` — do not edit by hand."
            ),
        },
        "servers": [_build_server()],
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

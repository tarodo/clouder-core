#!/usr/bin/env python3
"""Generate docs/api/openapi.yaml from pydantic schemas + a manual route table.

Usage:
    PYTHONPATH=src python scripts/generate_openapi.py

Strategy:
    - Import CollectRequestIn from collector.schemas; embed its JSON Schema.
    - For all other request/response bodies, declare inline schemas here
      because they're not (yet) backed by pydantic models.
    - Routes are declared as a single ROUTES table — keep in sync with
      infra/api_gateway.tf and infra/auth.tf when adding new endpoints.

Output: docs/api/openapi.yaml (OpenAPI 3.1).
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
from collector.schemas import AdminIngestRequestIn, CollectRequestIn


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
        "key_name": {"type": ["string", "null"]},
        "key_camelot": {"type": ["string", "null"]},
        "publish_date": {"type": ["string", "null"]},
        "spotify_id": {"type": ["string", "null"]},
        "release_type": {"type": ["string", "null"]},
        "is_ai_suspected": {"type": "boolean"},
        "artists": {"type": "array", "items": {"type": "string"}},
        "added_at": {"type": "string"},
        "source_triage_block_id": {"type": ["string", "null"]},
        "used_in_playlist": {
            "type": "boolean",
            "description": "True if this track is already in at least one of the user's playlists.",
        },
        "tags": {
            "type": "array",
            "description": "User-tags attached to this track (always present, may be empty).",
            "items": {
                "type": "object",
                "required": ["id", "name", "color"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "color": {
                        "type": ["string", "null"],
                        "pattern": "^#[0-9A-Fa-f]{6}$",
                    },
                },
            },
        },
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

TAG_RESPONSE = {
    "type": "object",
    "required": ["id", "name", "color", "created_at", "updated_at"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "name": {"type": "string"},
        "color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
        "created_at": {"type": "string"},
        "updated_at": {"type": "string"},
    },
}

COMMENT_RESPONSE: dict[str, Any] = {
    "type": "object",
    "required": ["author_name", "text", "like_count"],
    "properties": {
        "author_name": {"type": "string"},
        "author_avatar_url": {"type": "string", "nullable": True},
        "text": {"type": "string"},
        "like_count": {"type": "integer"},
        "published_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

TRACK_COMMENTS_RESPONSE: dict[str, Any] = {
    "type": "object",
    "required": ["status", "comment_count", "comments"],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pending", "collected", "empty", "disabled", "failed"],
        },
        "comment_count": {"type": "integer"},
        "video_url": {"type": "string", "nullable": True},
        "comments": {"type": "array", "items": COMMENT_RESPONSE},
    },
}

TAG_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": TAG_RESPONSE},
        "total": {"type": "integer"},
        "limit": {"type": "integer"},
        "offset": {"type": "integer"},
    },
}

TRACK_TAGS_RESPONSE = {
    "type": "object",
    "required": ["tags"],
    "properties": {
        "tags": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "color"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
                },
            },
        },
    },
}

SET_TRACK_TAGS_RESPONSE = {
    "type": "object",
    "required": ["tags"],
    "properties": {
        "tags": {"type": "array", "items": TAG_RESPONSE},
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
        "old_offset_weeks": {"type": "integer"},
        "include_disliked_labels": {"type": "boolean"},
        "include_disliked_artists": {"type": "boolean"},
        "compilations_to_not": {"type": "boolean"},
        "include_favorites": {"type": "boolean"},
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
        "key_name": {"type": ["string", "null"]},
        "key_camelot": {"type": ["string", "null"]},
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

PLAYLIST_TRACK_RESPONSE = {
    "type": "object",
    "required": [
        "track_id", "title", "is_ai_suspected", "artists", "added_at",
    ],
    "properties": {
        "track_id": {"type": "string", "format": "uuid"},
        "position": {"type": "integer"},
        "title": {"type": "string"},
        "mix_name": {"type": ["string", "null"]},
        "isrc": {"type": ["string", "null"]},
        "bpm": {"type": ["integer", "null"]},
        "length_ms": {"type": ["integer", "null"]},
        "key_name": {"type": ["string", "null"]},
        "key_camelot": {"type": ["string", "null"]},
        "spotify_release_date": {"type": ["string", "null"]},
        "spotify_id": {"type": ["string", "null"]},
        "origin": {"type": "string"},
        "is_ai_suspected": {"type": "boolean"},
        "artists": {"type": "array", "items": {"type": "object"}},
        "added_at": {"type": "string"},
        "label": {
            "type": "object",
            "nullable": True,
        },
        "beatport_track_id": {"type": ["string", "null"]},
        "beatport_slug": {"type": ["string", "null"]},
        "tags": {
            "type": "array",
            "description": "User-tags attached to this track (always present, may be empty).",
            "items": {
                "type": "object",
                "required": ["id", "name", "color"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "color": {
                        "type": ["string", "null"],
                        "pattern": "^#[0-9A-Fa-f]{6}$",
                    },
                },
            },
        },
        "ytmusic": {
            "type": "object",
            "nullable": True,
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["matched", "pending", "needs_review", "not_found"],
                },
                "video_id": {"type": "string", "nullable": True},
                "url": {"type": "string", "nullable": True},
                "confidence": {"type": "number", "nullable": True},
            },
            "required": ["status"],
        },
    },
}

PLAYLIST_TRACKS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "limit", "offset"],
    "properties": {
        "items": {"type": "array", "items": PLAYLIST_TRACK_RESPONSE},
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
    },
}

ME_RESPONSE = {
    "allOf": [
        {"$ref": "#/components/schemas/UserProfile"},
        {
            "type": "object",
            "required": ["sessions", "ytmusic_connected"],
            "properties": {
                "sessions": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/SessionRow"},
                },
                "ytmusic_connected": {"type": "boolean"},
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

LABEL_ENRICH_REQUEST = {
    "type": "object",
    "required": ["labels", "vendors", "models", "prompt_slug",
                 "prompt_version", "merge_vendor", "merge_model"],
    "properties": {
        "labels": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "label_id": {"type": "string"},
                    "label_name": {"type": "string", "minLength": 1, "maxLength": 256},
                    "style": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "additionalProperties": False,
                "description": "Either label_id (resolves from clouder_labels) or label_name+style (creates if missing).",
            },
        },
        "vendors": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": ["gemini", "openai", "tavily_deepseek"]},
        },
        "models": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "prompt_slug": {"type": "string", "minLength": 1},
        "prompt_version": {"type": "string", "minLength": 1},
        "merge_vendor": {"type": "string", "enum": ["deepseek"]},
        "merge_model": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

LABEL_ENRICH_ACCEPTED_RESPONSE = {
    "type": "object",
    "required": ["run_id", "queued_labels"],
    "properties": {
        "run_id": {"type": "string", "format": "uuid"},
        "queued_labels": {"type": "integer", "minimum": 1},
    },
}

LABEL_ENRICH_RUN_RESPONSE = {
    "type": "object",
    "required": ["id", "status", "cells_total", "cells_ok", "cells_error"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "status": {"type": "string", "enum": ["queued", "running", "completed", "failed"]},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "vendors": {"type": "array", "items": {"type": "string"}},
        "models": {"type": "object", "additionalProperties": {"type": "string"}},
        "merge_vendor": {"type": "string"},
        "merge_model": {"type": "string"},
        "requested_labels": {"type": "integer"},
        "cells_total": {"type": "integer"},
        "cells_ok": {"type": "integer"},
        "cells_error": {"type": "integer"},
        "cost_usd": {"type": "number"},
        "source": {"type": "string", "enum": ["manual", "auto"]},
        "created_at": {"type": "string", "format": "date-time"},
        "started_at": {"type": ["string", "null"], "format": "date-time"},
        "finished_at": {"type": ["string", "null"], "format": "date-time"},
        "cells": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "cell_id", "label_id", "label_name", "vendor",
                    "status", "latency_ms", "cost_usd",
                ],
                "properties": {
                    "cell_id": {"type": "string"},
                    "label_id": {"type": "string"},
                    "label_name": {"type": "string"},
                    "vendor": {"type": "string"},
                    "status": {"type": "string", "enum": ["ok", "error"]},
                    "latency_ms": {"type": "integer"},
                    "cost_usd": {"type": "number"},
                    "error_message": {"type": ["string", "null"]},
                },
            },
        },
    },
}

LABEL_SUMMARY = {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["none", "queued", "running", "completed", "failed", "outdated"],
        },
        "track_count": {"type": "integer"},
        "info": {
            "type": ["object", "null"],
            "properties": {
                "tagline": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
                "founded_year": {"type": ["integer", "null"]},
                "primary_styles": {"type": "array", "items": {"type": "string"}},
                "activity": {
                    "type": "string",
                    "enum": ["unknown", "dormant", "low", "steady", "high", "fire_hose"],
                },
                "ai_content": {
                    "type": ["string", "null"],
                    "enum": ["unknown", "none_detected", "suspected", "confirmed", None],
                },
                "updated_at": {"type": "string", "format": "date-time"},
            },
        },
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
}

LABELS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "page", "limit"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/LabelSummary"},
        },
        "total": {"type": "integer"},
        "page": {"type": "integer"},
        "limit": {"type": "integer"},
    },
}

LABEL_DETAIL_RESPONSE = {
    "type": "object",
    "description": "Sanitized LabelInfo (admin-only fields stripped) plus my_preference.",
    "properties": {
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
    "additionalProperties": True,
}

MY_LABEL_PREFERENCES_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "page", "limit"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "my_preference"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "my_preference": {
                        "type": "string",
                        "enum": ["liked", "disliked"],
                    },
                },
            },
        },
        "total": {"type": "integer"},
        "page": {"type": "integer"},
        "limit": {"type": "integer"},
    },
}

BACKLOG_LABEL = {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {"type": "string", "enum": ["none", "completed", "outdated"]},
        "track_count": {"type": "integer"},
        "last_attempted_at": {"type": ["string", "null"], "format": "date-time"},
    },
}

BACKLOG_RESPONSE = {
    "type": "object",
    "required": ["items", "total_estimate"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/BacklogLabel"},
        },
        "next_cursor": {"type": ["string", "null"]},
        "total_estimate": {"type": "integer"},
    },
}

RUNS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/LabelEnrichRunResponse"},
        },
        "next_cursor": {"type": ["string", "null"]},
    },
}

LABEL_HISTORY_CELL = {
    "type": "object",
    "required": ["cell_id", "run_id", "vendor", "status"],
    "properties": {
        "cell_id": {"type": "string", "format": "uuid"},
        "run_id": {"type": "string", "format": "uuid"},
        "run_status": {"type": "string"},
        "run_created_at": {"type": "string", "format": "date-time"},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "vendor": {"type": "string"},
        "model": {"type": "string"},
        "status": {"type": "string", "enum": ["ok", "error"]},
        "latency_ms": {"type": ["integer", "null"]},
        "cost_usd": {"type": ["number", "null"]},
        "error_message": {"type": ["string", "null"]},
        "parsed": {"type": ["object", "null"], "additionalProperties": True},
        "citations": {"type": ["array", "null"], "items": {"type": "object", "additionalProperties": True}},
    },
}

LABEL_HISTORY_RESPONSE = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/LabelHistoryCell"},
        },
    },
}

ENRICHMENT_OPTIONS = {
    "type": "object",
    "required": ["vendors", "prompt_versions", "default_models", "merge"],
    "properties": {
        "vendors": {"type": "array", "items": {"type": "string"}},
        "prompt_versions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "version": {"type": "string"},
                    "is_default": {"type": "boolean"},
                },
            },
        },
        "default_models": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "merge": {
            "type": "object",
            "properties": {
                "vendor": {"type": "string"},
                "default_model": {"type": "string"},
            },
        },
    },
}

LABEL_INFO_RESPONSE = {
    "type": "object",
    "required": ["label_id", "label_name", "merged", "status",
                 "ai_content", "ai_confidence", "updated_at"],
    "properties": {
        "label_id": {"type": "string", "format": "uuid"},
        "label_name": {"type": "string"},
        "last_run_id": {"type": "string", "format": "uuid"},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "merged": {"type": "object"},
        "provenance": {"type": "object"},
        "ai_content": {"type": "string"},
        "ai_confidence": {"type": "number"},
        "status": {"type": "string"},
        "primary_styles": {"type": "array", "items": {"type": "string"}},
        "tagline": {"type": ["string", "null"]},
        "country": {"type": ["string", "null"]},
        "founded_year": {"type": ["integer", "null"]},
        "activity": {"type": ["string", "null"]},
        "last_release_date": {"type": ["string", "null"], "format": "date"},
        "updated_at": {"type": "string", "format": "date-time"},
    },
}

# ── artist enrichment schemas ──────────────────────────────────────────────

ARTIST_ENRICH_REQUEST = {
    "type": "object",
    "required": ["artists", "vendors", "models", "prompt_slug",
                 "prompt_version", "merge_vendor", "merge_model"],
    "properties": {
        "artists": {
            "type": "array",
            "minItems": 1,
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "artist_id": {"type": "string"},
                    "artist_name": {"type": "string", "minLength": 1, "maxLength": 256},
                    "style": {"type": "string", "minLength": 1, "maxLength": 128},
                },
                "additionalProperties": False,
                "description": "Either artist_id (resolves from clouder_artists) or artist_name+style (creates if missing).",
            },
        },
        "vendors": {
            "type": "array",
            "minItems": 1,
            "items": {"type": "string", "enum": ["gemini", "openai", "tavily_deepseek"]},
        },
        "models": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
        "prompt_slug": {"type": "string", "minLength": 1},
        "prompt_version": {"type": "string", "minLength": 1},
        "merge_vendor": {"type": "string", "enum": ["deepseek"]},
        "merge_model": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

ARTIST_ENRICH_ACCEPTED_RESPONSE = {
    "type": "object",
    "required": ["run_id", "queued_artists"],
    "properties": {
        "run_id": {"type": "string", "format": "uuid"},
        "queued_artists": {"type": "integer", "minimum": 1},
    },
}

ARTIST_ENRICH_RUN_RESPONSE = {
    "type": "object",
    "required": ["id", "status", "cells_total", "cells_ok", "cells_error"],
    "properties": {
        "id": {"type": "string", "format": "uuid"},
        "status": {"type": "string", "enum": ["queued", "running", "completed", "failed"]},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "vendors": {"type": "array", "items": {"type": "string"}},
        "models": {"type": "object", "additionalProperties": {"type": "string"}},
        "merge_vendor": {"type": "string"},
        "merge_model": {"type": "string"},
        "requested_artists": {"type": "integer"},
        "cells_total": {"type": "integer"},
        "cells_ok": {"type": "integer"},
        "cells_error": {"type": "integer"},
        "cost_usd": {"type": "number"},
        "source": {"type": "string", "enum": ["manual", "auto"]},
        "created_at": {"type": "string", "format": "date-time"},
        "started_at": {"type": ["string", "null"], "format": "date-time"},
        "finished_at": {"type": ["string", "null"], "format": "date-time"},
        "cells": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "cell_id", "artist_id", "artist_name", "vendor",
                    "status", "latency_ms", "cost_usd",
                ],
                "properties": {
                    "cell_id": {"type": "string"},
                    "artist_id": {"type": "string"},
                    "artist_name": {"type": "string"},
                    "vendor": {"type": "string"},
                    "status": {"type": "string", "enum": ["ok", "error"]},
                    "latency_ms": {"type": "integer"},
                    "cost_usd": {"type": "number"},
                    "error_message": {"type": ["string", "null"]},
                },
            },
        },
    },
}

ARTIST_SUMMARY = {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {
            "type": "string",
            "enum": ["none", "queued", "running", "completed", "failed", "outdated"],
        },
        "track_count": {"type": "integer"},
        "info": {
            "type": ["object", "null"],
            "properties": {
                "tagline": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
                "active_since": {"type": ["integer", "null"]},
                "primary_styles": {"type": "array", "items": {"type": "string"}},
                "artist_type": {
                    "type": "string",
                    "enum": ["solo", "duo", "group", "alias_project", "unknown"],
                },
                "ai_content": {
                    "type": ["string", "null"],
                    "enum": ["unknown", "none_detected", "suspected", "confirmed", None],
                },
                "updated_at": {"type": "string", "format": "date-time"},
            },
        },
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
}

ARTISTS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "page", "limit"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/ArtistSummary"},
        },
        "total": {"type": "integer"},
        "page": {"type": "integer"},
        "limit": {"type": "integer"},
    },
}

ARTIST_DETAIL_RESPONSE = {
    "type": "object",
    "description": "Sanitized ArtistInfo (admin-only fields stripped) plus my_preference.",
    "properties": {
        "my_preference": {
            "type": ["string", "null"],
            "enum": ["liked", "disliked", None],
        },
    },
    "additionalProperties": True,
}

MY_ARTIST_PREFERENCES_RESPONSE = {
    "type": "object",
    "required": ["items", "total", "page", "limit"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name", "my_preference"],
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "my_preference": {
                        "type": "string",
                        "enum": ["liked", "disliked"],
                    },
                },
            },
        },
        "total": {"type": "integer"},
        "page": {"type": "integer"},
        "limit": {"type": "integer"},
    },
}

BACKLOG_ARTIST = {
    "type": "object",
    "required": ["id", "name", "style", "status", "track_count"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "style": {"type": "string"},
        "status": {"type": "string", "enum": ["none", "completed", "outdated"]},
        "track_count": {"type": "integer"},
        "last_attempted_at": {"type": ["string", "null"], "format": "date-time"},
    },
}

BACKLOG_ARTIST_RESPONSE = {
    "type": "object",
    "required": ["items", "total_estimate"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/BacklogArtist"},
        },
        "next_cursor": {"type": ["string", "null"]},
        "total_estimate": {"type": "integer"},
    },
}

ARTIST_RUNS_LIST_RESPONSE = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/ArtistEnrichRunResponse"},
        },
        "next_cursor": {"type": ["string", "null"]},
    },
}

ARTIST_HISTORY_CELL = {
    "type": "object",
    "required": ["cell_id", "run_id", "vendor", "status"],
    "properties": {
        "cell_id": {"type": "string", "format": "uuid"},
        "run_id": {"type": "string", "format": "uuid"},
        "run_status": {"type": "string"},
        "run_created_at": {"type": "string", "format": "date-time"},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "vendor": {"type": "string"},
        "model": {"type": "string"},
        "status": {"type": "string", "enum": ["ok", "error"]},
        "latency_ms": {"type": ["integer", "null"]},
        "cost_usd": {"type": ["number", "null"]},
        "error_message": {"type": ["string", "null"]},
        "parsed": {"type": ["object", "null"], "additionalProperties": True},
        "citations": {"type": ["array", "null"], "items": {"type": "object", "additionalProperties": True}},
    },
}

ARTIST_HISTORY_RESPONSE = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {"$ref": "#/components/schemas/ArtistHistoryCell"},
        },
    },
}

ARTIST_INFO_RESPONSE = {
    "type": "object",
    "required": ["artist_id", "artist_name", "merged", "status",
                 "ai_content", "ai_confidence", "updated_at"],
    "properties": {
        "artist_id": {"type": "string", "format": "uuid"},
        "artist_name": {"type": "string"},
        "last_run_id": {"type": "string", "format": "uuid"},
        "prompt_slug": {"type": "string"},
        "prompt_version": {"type": "string"},
        "merged": {"type": "object"},
        "provenance": {"type": "object"},
        "ai_content": {"type": "string"},
        "ai_confidence": {"type": "number"},
        "status": {"type": "string"},
        "primary_styles": {"type": "array", "items": {"type": "string"}},
        "tagline": {"type": ["string", "null"]},
        "country": {"type": ["string", "null"]},
        "active_since": {"type": ["integer", "null"]},
        "artist_type": {"type": ["string", "null"]},
        "updated_at": {"type": "string", "format": "date-time"},
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
    {
        "method": "post",
        "path": "/auth/ytmusic/device-code",
        "auth": AUTH,
        "summary": "Start YouTube Music device-flow OAuth.",
        "description": "Returns a user_code + verification_url; client shows it and polls /auth/ytmusic/poll.",
        "responses": {
            "200": _make_response(200, "Device code issued.", {"type": "object"}),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/auth/ytmusic/poll",
        "auth": AUTH,
        "summary": "Poll for YouTube Music device-flow completion.",
        "description": "Exchanges the device_code. 202 while pending; 200 once the account is linked.",
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {"device_code": {"type": "string"}},
                "required": ["device_code"],
                "additionalProperties": False,
            }}},
        },
        "responses": {
            "200": _make_response(200, "Account linked.", {"type": "object"}),
            "202": {"description": "authorization_pending or slow_down — keep polling."},
            "422": _error(422, "device code expired — restart."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/auth/ytmusic",
        "auth": AUTH,
        "summary": "Disconnect the user's YouTube Music account.",
        "responses": {
            "200": _make_response(200, "Disconnected.", {"type": "object"}),
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
            "snapshot to S3, enqueues canonicalization."
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
        "method": "post",
        "path": "/admin/beatport/ingest",
        "auth": ADMIN,
        "summary": "Admin: trigger Beatport ingest with Saturday-week or custom range.",
        "description": (
            "Saturday-week semantics. If `period_start` and `period_end` are "
            "omitted, the server computes them from `(week_year, week_number)`. "
            "If both are present the run is recorded with `is_custom_range = true`."
        ),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AdminIngestRequestIn"},
                }
            },
        },
        "request_example": {
            "style_id": 90,
            "week_year": 2026,
            "week_number": 17,
            "bp_token": "REDACTED",
        },
        "responses": {
            "200": _make_response(
                200,
                "Run created.",
                {"$ref": "#/components/schemas/CollectResponse"},
            ),
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
            "502": _error(502, "beatport_unavailable."),
        },
    },
    {
        "method": "get",
        "path": "/admin/coverage",
        "auth": ADMIN,
        "summary": "Admin: ingest coverage matrix for one Saturday-year.",
        "parameters": [
            {
                "name": "week_year",
                "in": "query",
                "required": True,
                "schema": {"type": "integer", "minimum": 2000, "maximum": 2100},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Coverage payload.",
                {"type": "object"},
            ),
            "400": _error(400, "validation_error."),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/runs",
        "auth": ADMIN,
        "summary": "Admin: list runs for one (style, week_year, week_number) cell.",
        "parameters": [
            {"name": "style_id", "in": "query", "required": True, "schema": {"type": "integer"}},
            {"name": "week_year", "in": "query", "required": True, "schema": {"type": "integer"}},
            {"name": "week_number", "in": "query", "required": True, "schema": {"type": "integer"}},
        ],
        "responses": {
            "200": _make_response(200, "Runs (DESC by started_at).", {"type": "object"}),
            "400": _error(400, "validation_error."),
            "503": _error(503, "db_not_configured."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
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
    # ── label enrichment (admin only) ──────────────────────────────
    {
        "method": "post",
        "path": "/admin/labels/enrich",
        "auth": ADMIN,
        "summary": "Admin: enqueue label enrichment for up to 100 labels.",
        "description": (
            "Creates a `label_enrich_runs` row, fans out per-(label, vendor) cells "
            "onto the label-enrichment SQS queue. Returns 202 with the run id and "
            "the count of queued labels."
        ),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": LABEL_ENRICH_REQUEST,
                }
            },
        },
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                LABEL_ENRICH_ACCEPTED_RESPONSE,
            ),
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "post",
        "path": "/admin/labels/{label_id}/enrich-auto",
        "auth": ADMIN,
        "summary": "Admin: enqueue one label using saved auto-search settings.",
        "description": (
            "Reads the registered auto-enrich config for labels, creates a run, "
            "and enqueues this label onto the label-enrichment SQS queue. Returns "
            "202 with the run id. 409 if no auto-enrich config is set up."
        ),
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                LABEL_ENRICH_ACCEPTED_RESPONSE,
            ),
            "404": _error(404, "label_not_found."),
            "409": _error(409, "auto_config_missing."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/enrich-runs/{run_id}",
        "auth": ADMIN,
        "summary": "Admin: get status + counters for a label-enrichment run.",
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
                "Run row with progress counters.",
                LABEL_ENRICH_RUN_RESPONSE,
            ),
            "404": _error(404, "Run not found."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/{label_id}",
        "auth": ADMIN,
        "summary": "Admin: get enriched label info (merged AI content + provenance).",
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Label info with merged enrichment fields.",
                LABEL_INFO_RESPONSE,
            ),
            "404": _error(404, "Label not found."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/{label_id}/history",
        "auth": ADMIN,
        "tags": ["labels-admin"],
        "summary": "Admin: per-label enrichment history (every cell across every run).",
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Per-label cells, ordered by run created_at DESC.",
                {"$ref": "#/components/schemas/LabelHistoryResponse"},
            ),
            "403": _error(403, "admin_required."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── user-facing label browse ──────────────────────────────────
    {
        "method": "get",
        "path": "/labels",
        "auth": AUTH,
        "summary": "List labels for browsing.",
        "description": (
            "Paginated label list. Filters: style (dominant style), q (name "
            "prefix), sort (name|recent). Page-based pagination."
        ),
        "parameters": [
            {"name": "style", "in": "query", "schema": {"type": "string"}},
            {"name": "q", "in": "query", "schema": {"type": "string"}},
            {
                "name": "sort",
                "in": "query",
                "schema": {"type": "string", "enum": ["name", "recent"]},
            },
            {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            {
                "name": "my",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["all", "liked", "disliked", "unrated"],
                    "default": "all",
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Paginated labels.",
                {"$ref": "#/components/schemas/LabelsListResponse"},
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/labels/{label_id}",
        "auth": AUTH,
        "summary": "Get user-facing label detail.",
        "description": (
            "Returns sanitized LabelInfo for completed enrichments. For an "
            "existing label without an enrichment row, returns a minimal "
            "{label_name, my_preference} payload so preference buttons still "
            "render. 404 only when the label does not exist."
        ),
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Label info.",
                {"$ref": "#/components/schemas/LabelDetail"},
            ),
            "404": _error(404, "label_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/backlog",
        "auth": ADMIN,
        "summary": "Admin: list labels missing enrichment.",
        "description": (
            "Labels with no info, failed, or completed-but-outdated. "
            "Cursor-paginated. Sorted by track_count DESC."
        ),
        "parameters": [
            {"name": "style", "in": "query", "schema": {"type": "string"}},
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string", "enum": ["all", "none", "completed", "outdated"]},
            },
            {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 100,
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Backlog page.",
                {"$ref": "#/components/schemas/BacklogResponse"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/enrich-runs",
        "auth": ADMIN,
        "summary": "Admin: list enrichment runs.",
        "parameters": [
            {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["queued", "running", "completed", "failed"],
                },
            },
            {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            {
                "name": "source",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["manual", "auto"]},
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Runs list.",
                {"$ref": "#/components/schemas/RunsListResponse"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/labels/enrich/options",
        "auth": ADMIN,
        "summary": "Admin: static config for the enqueue form.",
        "responses": {
            "200": _make_response(
                200,
                "Form options.",
                {"$ref": "#/components/schemas/EnrichmentOptions"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/auto-enrich/labels",
        "auth": ADMIN,
        "summary": "Admin: get auto-enrichment config for labels + form options.",
        "responses": {
            "200": _make_response(
                200,
                "Saved config (or defaults) plus the model/prompt options.",
                {
                    "type": "object",
                    "required": ["config", "options"],
                    "properties": {
                        "config": {
                            "type": "object",
                            "required": ["enabled", "vendors", "models", "merge_vendor"],
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "vendors": {"type": "array", "items": {"type": "string"}},
                                "models": {"type": "object", "additionalProperties": {"type": "string"}},
                                "prompt_slug": {"type": "string", "nullable": True},
                                "prompt_version": {"type": "string", "nullable": True},
                                "merge_vendor": {"type": "string"},
                                "merge_model": {"type": "string", "nullable": True},
                            },
                        },
                        "options": {"$ref": "#/components/schemas/EnrichmentOptions"},
                    },
                },
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "put",
        "path": "/admin/auto-enrich/labels",
        "auth": ADMIN,
        "summary": "Admin: upsert auto-enrichment config for labels.",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["enabled"],
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "vendors": {"type": "array", "items": {"type": "string"}},
                            "models": {"type": "object", "additionalProperties": {"type": "string"}},
                            "prompt_slug": {"type": "string", "nullable": True},
                            "prompt_version": {"type": "string", "nullable": True},
                            "merge_vendor": {"type": "string", "enum": ["deepseek"]},
                            "merge_model": {"type": "string", "nullable": True},
                        },
                    },
                }
            },
        },
        "responses": {
            "204": {"description": "Config saved."},
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
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
        for entity in ("tracks", "albums", "styles")
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
            {
                "name": "tags",
                "in": "query",
                "schema": {"type": "string"},
                "description": (
                    "CSV of user_tag UUIDs. Filters the page to tracks carrying "
                    "the listed tag(s) per `match`. Unknown tag ids are silently "
                    "ignored. Empty / absent → no tag filtering."
                ),
            },
            {
                "name": "match",
                "in": "query",
                "schema": {"type": "string", "enum": ["all", "any"]},
                "description": (
                    "Tag-set semantics. `all` (default) = every listed tag must "
                    "be present on the track. `any` = at least one match suffices."
                ),
            },
            {
                "name": "fresh",
                "in": "query",
                "schema": {"type": "integer", "enum": [0, 1]},
                "description": "Hide tracks already used in any playlist. 1=on, 0/absent=off.",
            },
        ],
        "responses": {
            "200": _make_response(200, "Paginated tracks.", CATEGORY_TRACKS_LIST_RESPONSE),
            "400": _error(400, "invalid_match (match must be 'all' or 'any')."),
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
    # ── track-tags: vocabulary CRUD (spec 2026-05-11) ───────────────
    {
        "method": "post",
        "path": "/tags",
        "auth": AUTH,
        "summary": "Create a user tag.",
        "description": (
            "Per-user vocabulary entry. `name` is preserved as entered; "
            "`normalized_name` (server-derived `lower(trim(name))`) is unique "
            "per user."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 64},
                    "color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Vocal", "color": "#ff8800"},
        "responses": {
            "201": _make_response(201, "Tag created.", TAG_RESPONSE),
            "400": _error(400, "invalid_name or invalid_color."),
            "409": _error(409, "tag_name_conflict (case-insensitive duplicate)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/tags",
        "auth": AUTH,
        "summary": "List the user's tags (paginated, optional prefix search).",
        "parameters": [
            *PAGINATION_PARAMS,
            {
                "name": "search",
                "in": "query",
                "schema": {"type": "string"},
                "description": "Lowercased prefix match against normalized_name.",
            },
        ],
        "responses": {
            "200": _make_response(200, "Paginated tags.", TAG_LIST_RESPONSE),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "patch",
        "path": "/tags/{tag_id}",
        "auth": AUTH,
        "summary": "Rename or recolour a tag (partial update).",
        "parameters": [
            {"name": "tag_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 64},
                    "color": {"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Vocal F"},
        "responses": {
            "200": _make_response(200, "Tag updated.", TAG_RESPONSE),
            "400": _error(400, "invalid_name, invalid_color, or invalid_payload."),
            "404": _error(404, "tag_not_found."),
            "409": _error(409, "tag_name_conflict."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/tags/{tag_id}",
        "auth": AUTH,
        "summary": "Delete a tag (cascades to all track_tags rows).",
        "parameters": [
            {"name": "tag_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Tag deleted."},
            "404": _error(404, "tag_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── track-tags: per-track ops (spec 2026-05-11) ─────────────────
    {
        "method": "get",
        "path": "/tracks/{track_id}/tags",
        "auth": AUTH,
        "summary": "List the user's tags attached to a track.",
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Tag list (may be empty).", TRACK_TAGS_RESPONSE),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/tracks/{track_id}/comments",
        "auth": AUTH,
        "summary": "List collected external comments for a track (first N).",
        "description": (
            "Returns YouTube comments collected for the track's matched video. "
            "`status` is pending until collection completes. Query: `platform` "
            "(default youtube), `limit` (default 5, max 100)."
        ),
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            {"name": "platform", "in": "query", "required": False, "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
        ],
        "responses": {
            "200": _make_response(200, "Track comments.", TRACK_COMMENTS_RESPONSE),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "put",
        "path": "/tracks/{track_id}/tags",
        "auth": AUTH,
        "summary": "Replace all tags on a track (transactional set).",
        "description": (
            "Empty array `[]` clears all tags. Track must currently sit in at "
            "least one of the user's active categories — tracks inside triage "
            "blocks cannot be tagged."
        ),
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["tag_ids"],
                "properties": {
                    "tag_ids": {
                        "type": "array",
                        "maxItems": 50,
                        "uniqueItems": True,
                        "items": {"type": "string", "format": "uuid"},
                    },
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"tag_ids": [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]},
        "responses": {
            "200": _make_response(200, "Updated tag set.", SET_TRACK_TAGS_RESPONSE),
            "400": _error(400, "invalid_tag_ids or too_many_tags."),
            "404": _error(404, "tag_not_found (one of tag_ids is foreign)."),
            "422": _error(422, "track_not_in_any_category."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/tracks/{track_id}/tags",
        "auth": AUTH,
        "summary": "Attach a single tag to a track (idempotent).",
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["tag_id"],
                "properties": {"tag_id": {"type": "string", "format": "uuid"}},
                "additionalProperties": False,
            }}},
        },
        "request_example": {"tag_id": "11111111-1111-1111-1111-111111111111"},
        "responses": {
            "201": _make_response(201, "Updated tag set (idempotent on conflict).", SET_TRACK_TAGS_RESPONSE),
            "400": _error(400, "invalid_tag_ids."),
            "404": _error(404, "tag_not_found."),
            "422": _error(422, "track_not_in_any_category."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/tracks/{track_id}/tags/{tag_id}",
        "auth": AUTH,
        "summary": "Detach a tag from a track (idempotent — 204 either way).",
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            {"name": "tag_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Tag detached (or was already absent)."},
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── playlists (spec 2026-05-11) ─────────────────────────────────
    {
        "method": "post",
        "path": "/playlists",
        "auth": AUTH,
        "summary": "Create a playlist.",
        "description": (
            "Creates a new playlist for the authenticated user. `name` must be "
            "unique per user (case-insensitive after trim). Hard cap on the "
            "number of playlists per user enforced server-side."
        ),
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "description": {"type": ["string", "null"], "maxLength": 300},
                    "is_public": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Saturday techno", "description": "rolling weekly mix", "is_public": False},
        "responses": {
            "201": _make_response(201, "Playlist created.", {"type": "object"}),
            "400": _error(400, "validation_error."),
            "409": _error(409, "playlist_name_conflict (case-insensitive duplicate)."),
            "429": _error(429, "playlist_limit_reached."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/playlists",
        "auth": AUTH,
        "summary": "List the user's playlists (paginated, optional status filter).",
        "parameters": PAGINATION_PARAMS + [
            {
                "name": "status",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["active", "completed"]},
                "description": "Optional status filter. Omit to return all.",
            },
        ],
        "responses": {
            "200": _make_response(200, "Paginated playlists.", LIST_RESPONSE_TEMPLATE),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/playlists/{id}",
        "auth": AUTH,
        "summary": "Fetch a single playlist by id.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Playlist found.", {"type": "object"}),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "patch",
        "path": "/playlists/{id}",
        "auth": AUTH,
        "summary": "Rename or update playlist metadata (partial update).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1, "maxLength": 100},
                    "description": {"type": ["string", "null"], "maxLength": 300},
                    "is_public": {"type": "boolean"},
                    "status": {"type": "string", "enum": ["active", "completed"]},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"name": "Saturday techno v2"},
        "responses": {
            "200": _make_response(200, "Playlist updated.", {"type": "object"}),
            "400": _error(400, "validation_error or invalid_payload."),
            "404": _error(404, "playlist_not_found."),
            "409": _error(409, "playlist_name_conflict."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/playlists/{id}",
        "auth": AUTH,
        "summary": "Delete a playlist (cascades to tracks/cover/publish state).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Playlist deleted."},
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/playlists/{id}/tracks",
        "auth": AUTH,
        "summary": "List tracks in a playlist (paginated, ordered by position).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            *PAGINATION_PARAMS,
        ],
        "responses": {
            "200": _make_response(200, "Paginated playlist tracks.", PLAYLIST_TRACKS_LIST_RESPONSE),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/tracks",
        "auth": AUTH,
        "summary": "Append a track to the playlist.",
        "description": (
            "Track must be in the user's scope (category or triage block). "
            "Adds at the end of the playlist; idempotent on duplicate add."
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
        "request_example": {"track_id": "11111111-1111-1111-1111-111111111111"},
        "responses": {
            "201": _make_response(201, "Track appended.", {"type": "object"}),
            "400": _error(400, "validation_error."),
            "404": _error(404, "playlist_not_found or track_not_in_user_scope."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/playlists/{id}/tracks/{track_id}",
        "auth": AUTH,
        "summary": "Remove a track from a playlist (idempotent — 204 either way).",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "204": {"description": "Track removed (or was already absent)."},
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/tracks/order",
        "auth": AUTH,
        "summary": "Reorder all tracks in a playlist (full-list reorder).",
        "description": (
            "Body must list every current track_id in the new desired order. "
            "Rejected with 400 `order_mismatch` if the set of ids does not "
            "match the current membership exactly."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["track_ids"],
                "properties": {
                    "track_ids": {
                        "type": "array",
                        "uniqueItems": True,
                        "items": {"type": "string", "format": "uuid"},
                    },
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"track_ids": [
            "11111111-1111-1111-1111-111111111111",
            "22222222-2222-2222-2222-222222222222",
        ]},
        "responses": {
            "200": _make_response(200, "Reorder applied.", {"type": "object"}),
            "400": _error(400, "validation_error or order_mismatch."),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/cover/upload-url",
        "auth": AUTH,
        "summary": "Issue a presigned S3 PUT URL for cover upload.",
        "description": (
            "Returns a short-lived presigned PUT URL targeting `covers/<user>/<playlist>/...` "
            "in the raw bucket. Client must follow up with `POST /cover/confirm` once the "
            "upload completes."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["content_type"],
                "properties": {
                    "content_type": {"type": "string", "enum": ["image/jpeg", "image/png"]},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"content_type": "image/jpeg"},
        "responses": {
            "200": _make_response(200, "Presigned upload URL issued.", {"type": "object"}),
            "400": _error(400, "validation_error (invalid content_type)."),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/cover/confirm",
        "auth": AUTH,
        "summary": "Confirm cover upload completed; persist S3 key on playlist.",
        "description": (
            "HEADs the S3 object to verify size/content-type, then stores the "
            "cover key on the playlist. Rejects oversized or missing objects."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["s3_key"],
                "properties": {"s3_key": {"type": "string"}},
                "additionalProperties": False,
            }}},
        },
        "responses": {
            "200": _make_response(200, "Cover persisted.", {"type": "object"}),
            "400": _error(400, "cover_missing or cover_too_large."),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "delete",
        "path": "/playlists/{id}/cover",
        "auth": AUTH,
        "summary": "Clear the playlist cover.",
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "responses": {
            "200": _make_response(200, "Cover cleared (idempotent).", {"type": "object"}),
            "404": _error(404, "playlist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/tracks/import-spotify",
        "auth": AUTH,
        "summary": "Import tracks from a Spotify playlist URL/URI.",
        "description": (
            "Resolves the Spotify playlist via the user's stored OAuth token, "
            "upserts vendor refs into clouder_tracks, and appends them to the "
            "target playlist (deduped against existing membership)."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["spotify_ref"],
                "properties": {
                    "spotify_ref": {
                        "type": "string",
                        "description": "Spotify playlist URL, URI, or bare id.",
                    },
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"spotify_ref": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M"},
        "responses": {
            "201": _make_response(201, "Import accepted; returns counts.", {"type": "object"}),
            "400": _error(400, "invalid_spotify_ref."),
            "404": _error(404, "playlist_not_found."),
            "412": _error(412, "spotify_not_authorized (user has no Spotify OAuth token)."),
            "502": _error(502, "spotify_upstream_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/publish",
        "auth": AUTH,
        "summary": "Publish the playlist to the user's Spotify account.",
        "description": (
            "Creates or overwrites the linked Spotify playlist with the current "
            "track list and metadata (name, description, cover). On overwrite "
            "the client must pass `confirm_overwrite=true` to acknowledge "
            "destructive replacement of remote contents."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": False,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "confirm_overwrite": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"confirm_overwrite": True},
        "responses": {
            "200": _make_response(200, "Playlist published; returns Spotify playlist id.", {"type": "object"}),
            "400": _error(400, "nothing_to_publish (playlist has no tracks)."),
            "404": _error(404, "playlist_not_found."),
            "409": _error(409, "confirm_overwrite_required."),
            "412": _error(412, "spotify_not_authorized."),
            "502": _error(502, "spotify_upstream_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/publish-ytmusic",
        "auth": AUTH,
        "summary": "Publish the playlist to the user's YouTube Music account.",
        "description": (
            "Creates or overwrites the linked YouTube Music playlist with the "
            "current matched tracks (video ids from vendor_track_map) and "
            "metadata (name, description, privacy). Unmatched tracks are "
            "skipped. On overwrite the client must pass `confirm_overwrite=true`."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
        ],
        "requestBody": {
            "required": False,
            "content": {"application/json": {"schema": {
                "type": "object",
                "properties": {
                    "confirm_overwrite": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            }}},
        },
        "request_example": {"confirm_overwrite": True},
        "responses": {
            "200": _make_response(200, "Playlist published; returns YouTube Music playlist id.", {"type": "object"}),
            "400": _error(400, "nothing_to_publish (no matched YouTube Music tracks)."),
            "404": _error(404, "playlist_not_found."),
            "409": _error(409, "confirm_overwrite_required."),
            "412": _error(412, "ytmusic_not_authorized (YouTube Music not connected)."),
            "502": _error(502, "ytmusic_api_error."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── ytmusic match review (spec 2026-05-30) ──────────────────────
    {
        "method": "get",
        "path": "/playlists/{id}/tracks/{track_id}/match-candidates",
        "auth": AUTH,
        "summary": "List YT Music match candidates for a playlist track.",
        "description": (
            "Returns vendor-specific match candidates for the given track. "
            "404 if no open match-review record exists for this track."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {
                "name": "vendor",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "default": "ytmusic"},
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Match candidates for the vendor.",
                {
                    "type": "object",
                    "required": ["vendor", "candidates"],
                    "properties": {
                        "vendor": {"type": "string"},
                        "candidates": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "required": ["vendor_track_id", "title", "artists", "url"],
                                "properties": {
                                    "vendor_track_id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "artists": {"type": "array", "items": {"type": "string"}},
                                    "album": {"type": ["string", "null"]},
                                    "duration_ms": {"type": ["integer", "null"]},
                                    "url": {"type": "string"},
                                    "score": {"type": ["number", "null"]},
                                },
                            },
                        },
                    },
                },
            ),
            "404": _error(404, "no_open_review, playlist_not_found, or track_not_in_user_scope."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "post",
        "path": "/playlists/{id}/tracks/{track_id}/match-resolve",
        "auth": AUTH,
        "summary": "Accept or reject a YT Music match candidate.",
        "description": (
            "Resolves the open match-review for the given track. "
            "`action=accept` requires `vendor_track_id`. "
            "422 on invalid payload; 404 if the playlist or track is not in scope "
            "for this user."
        ),
        "parameters": [
            {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string"}},
        ],
        "requestBody": {
            "required": True,
            "content": {"application/json": {"schema": {
                "type": "object",
                "required": ["vendor", "action"],
                "properties": {
                    "vendor": {"type": "string"},
                    "action": {"type": "string", "enum": ["accept", "reject"]},
                    "vendor_track_id": {"type": ["string", "null"]},
                },
            }}},
        },
        "request_example": {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "dQw4w9WgXcQ"},
        "responses": {
            "200": _make_response(
                200,
                "Match resolved. Returns updated ytmusic vendor link.",
                {
                    "type": "object",
                    "required": ["ytmusic"],
                    "properties": {
                        "ytmusic": {
                            "type": "object",
                            "nullable": True,
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ["matched", "pending", "needs_review", "not_found"],
                                },
                                "video_id": {"type": ["string", "null"]},
                                "url": {"type": ["string", "null"]},
                                "confidence": {"type": ["number", "null"]},
                            },
                        },
                    },
                },
            ),
            "404": _error(404, "playlist_not_found or track_not_in_user_scope."),
            "422": _error(422, "validation_error (invalid body, or missing/invalid vendor_track_id for accept)."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── user label preferences ───────────────────────────────────────
    {
        "method": "put",
        "path": "/labels/{label_id}/preference",
        "auth": AUTH,
        "summary": "Set or clear the current user's label preference.",
        "description": (
            "Body: {\"status\": \"liked\" | \"disliked\" | \"none\"}. "
            "\"none\" deletes the row. Returns 204."
        ),
        "parameters": [
            {
                "name": "label_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["status"],
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["liked", "disliked", "none"],
                            }
                        },
                    }
                }
            },
        },
        "responses": {
            "204": {"description": "Preference updated."},
            "404": _error(404, "label_not_found."),
            "422": _error(422, "invalid status."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/me/label-preferences",
        "auth": AUTH,
        "summary": "List the current user's labelled labels.",
        "parameters": [
            {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["liked", "disliked"],
                    "default": "liked",
                },
            },
            {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Paginated user label preferences.",
                {"$ref": "#/components/schemas/MyLabelPreferencesResponse"},
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── artist enrichment (admin only) ──────────────────────────────
    {
        "method": "post",
        "path": "/admin/artists/enrich",
        "auth": ADMIN,
        "summary": "Admin: enqueue artist enrichment for up to 100 artists.",
        "description": (
            "Creates an `artist_enrich_runs` row, fans out per-(artist, vendor) cells "
            "onto the artist-enrichment SQS queue. Returns 202 with the run id and "
            "the count of queued artists."
        ),
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": ARTIST_ENRICH_REQUEST,
                }
            },
        },
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                ARTIST_ENRICH_ACCEPTED_RESPONSE,
            ),
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "post",
        "path": "/admin/artists/{artist_id}/enrich-auto",
        "auth": ADMIN,
        "summary": "Admin: enqueue one artist using saved auto-search settings.",
        "description": (
            "Reads the registered auto-enrich config for artists, creates a run, "
            "and enqueues this artist onto the artist-enrichment SQS queue. Returns "
            "202 with the run id. 409 if no auto-enrich config is set up."
        ),
        "parameters": [
            {
                "name": "artist_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "202": _make_response(
                202,
                "Enrichment run accepted and queued.",
                ARTIST_ENRICH_ACCEPTED_RESPONSE,
            ),
            "404": _error(404, "artist_not_found."),
            "409": _error(409, "auto_config_missing."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/enrich-runs/{run_id}",
        "auth": ADMIN,
        "summary": "Admin: get status + counters for an artist-enrichment run.",
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
                "Run row with progress counters.",
                ARTIST_ENRICH_RUN_RESPONSE,
            ),
            "404": _error(404, "Run not found."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/{artist_id}",
        "auth": ADMIN,
        "summary": "Admin: get enriched artist info (merged AI content + provenance).",
        "parameters": [
            {
                "name": "artist_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Artist info with merged enrichment fields.",
                ARTIST_INFO_RESPONSE,
            ),
            "404": _error(404, "Artist not found."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/{artist_id}/history",
        "auth": ADMIN,
        "tags": ["artists-admin"],
        "summary": "Admin: per-artist enrichment history (every cell across every run).",
        "parameters": [
            {
                "name": "artist_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string", "format": "uuid"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Per-artist cells, ordered by run created_at DESC.",
                {"$ref": "#/components/schemas/ArtistHistoryResponse"},
            ),
            "403": _error(403, "admin_required."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/backlog",
        "auth": ADMIN,
        "summary": "Admin: list artists missing enrichment.",
        "description": (
            "Artists with no info, failed, or completed-but-outdated. "
            "Cursor-paginated. Sorted by track_count DESC."
        ),
        "parameters": [
            {"name": "style", "in": "query", "schema": {"type": "string"}},
            {
                "name": "status",
                "in": "query",
                "schema": {"type": "string", "enum": ["all", "none", "completed", "outdated"]},
            },
            {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 100,
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Backlog page.",
                {"$ref": "#/components/schemas/BacklogArtistResponse"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/enrich-runs",
        "auth": ADMIN,
        "summary": "Admin: list artist enrichment runs.",
        "parameters": [
            {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["queued", "running", "completed", "failed"],
                },
            },
            {"name": "cursor", "in": "query", "schema": {"type": "string"}},
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            {
                "name": "source",
                "in": "query",
                "required": False,
                "schema": {"type": "string", "enum": ["manual", "auto"]},
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Artist runs list.",
                {"$ref": "#/components/schemas/ArtistRunsListResponse"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/artists/enrich/options",
        "auth": ADMIN,
        "summary": "Admin: static config for the artist enqueue form.",
        "responses": {
            "200": _make_response(
                200,
                "Form options.",
                {"$ref": "#/components/schemas/EnrichmentOptions"},
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "get",
        "path": "/admin/auto-enrich/artists",
        "auth": ADMIN,
        "summary": "Admin: get auto-enrichment config for artists + form options.",
        "responses": {
            "200": _make_response(
                200,
                "Saved config (or defaults) plus the model/prompt options.",
                {
                    "type": "object",
                    "required": ["config", "options"],
                    "properties": {
                        "config": {
                            "type": "object",
                            "required": ["enabled", "vendors", "models", "merge_vendor"],
                            "properties": {
                                "enabled": {"type": "boolean"},
                                "vendors": {"type": "array", "items": {"type": "string"}},
                                "models": {"type": "object", "additionalProperties": {"type": "string"}},
                                "prompt_slug": {"type": "string", "nullable": True},
                                "prompt_version": {"type": "string", "nullable": True},
                                "merge_vendor": {"type": "string"},
                                "merge_model": {"type": "string", "nullable": True},
                            },
                        },
                        "options": {"$ref": "#/components/schemas/EnrichmentOptions"},
                    },
                },
            ),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    {
        "method": "put",
        "path": "/admin/auto-enrich/artists",
        "auth": ADMIN,
        "summary": "Admin: upsert auto-enrichment config for artists.",
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["enabled"],
                        "properties": {
                            "enabled": {"type": "boolean"},
                            "vendors": {"type": "array", "items": {"type": "string"}},
                            "models": {"type": "object", "additionalProperties": {"type": "string"}},
                            "prompt_slug": {"type": "string", "nullable": True},
                            "prompt_version": {"type": "string", "nullable": True},
                            "merge_vendor": {"type": "string", "enum": ["deepseek"]},
                            "merge_model": {"type": "string", "nullable": True},
                        },
                    },
                }
            },
        },
        "responses": {
            "204": {"description": "Config saved."},
            "400": _error(400, "validation_error."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    },
    # ── user-facing artist browse ──────────────────────────────────
    {
        "method": "get",
        "path": "/artists",
        "auth": AUTH,
        "summary": "List artists for browsing.",
        "description": (
            "Paginated artist list. Filters: style (dominant style), q (name "
            "prefix), sort (name|recent). Page-based pagination."
        ),
        "parameters": [
            {"name": "style", "in": "query", "schema": {"type": "string"}},
            {"name": "q", "in": "query", "schema": {"type": "string"}},
            {
                "name": "sort",
                "in": "query",
                "schema": {"type": "string", "enum": ["name", "recent"]},
            },
            {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
            {
                "name": "my",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["all", "liked", "disliked", "unrated"],
                    "default": "all",
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Paginated artists.",
                {"$ref": "#/components/schemas/ArtistsListResponse"},
            ),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/artists/{artist_id}",
        "auth": AUTH,
        "summary": "Get user-facing artist detail.",
        "description": (
            "Returns sanitized ArtistInfo for completed enrichments. For an "
            "existing artist without an enrichment row, returns a minimal "
            "{artist_name, my_preference} payload so preference buttons still "
            "render. 404 only when the artist does not exist."
        ),
        "parameters": [
            {
                "name": "artist_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "responses": {
            "200": _make_response(
                200,
                "Artist info.",
                {"$ref": "#/components/schemas/ArtistDetail"},
            ),
            "404": _error(404, "artist_not_found."),
            **COMMON_AUTH_ERRORS,
        },
    },
    # ── user artist preferences ───────────────────────────────────────
    {
        "method": "put",
        "path": "/artists/{artist_id}/preference",
        "auth": AUTH,
        "summary": "Set or clear the current user's artist preference.",
        "description": (
            "Body: {\"status\": \"liked\" | \"disliked\" | \"none\"}. "
            "\"none\" deletes the row. Returns 204."
        ),
        "parameters": [
            {
                "name": "artist_id",
                "in": "path",
                "required": True,
                "schema": {"type": "string"},
            }
        ],
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["status"],
                        "properties": {
                            "status": {
                                "type": "string",
                                "enum": ["liked", "disliked", "none"],
                            }
                        },
                    }
                }
            },
        },
        "responses": {
            "204": {"description": "Preference updated."},
            "404": _error(404, "artist_not_found."),
            "422": _error(422, "invalid status."),
            **COMMON_AUTH_ERRORS,
        },
    },
    {
        "method": "get",
        "path": "/me/artist-preferences",
        "auth": AUTH,
        "summary": "List the current user's rated artists.",
        "parameters": [
            {
                "name": "status",
                "in": "query",
                "schema": {
                    "type": "string",
                    "enum": ["liked", "disliked"],
                    "default": "liked",
                },
            },
            {
                "name": "page",
                "in": "query",
                "schema": {"type": "integer", "minimum": 1, "default": 1},
            },
            {
                "name": "limit",
                "in": "query",
                "schema": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
        ],
        "responses": {
            "200": _make_response(
                200,
                "Paginated user artist preferences.",
                {"$ref": "#/components/schemas/MyArtistPreferencesResponse"},
            ),
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
        ("AdminIngestRequestIn", AdminIngestRequestIn),
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
            "staging or prod URL (`terraform output -raw api_endpoint`)."
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
                "3. Callback returns JSON `{access_token, spotify_access_token, expires_in, user, correlation_id}` "
                "and sets the refresh JWT as an HttpOnly cookie scoped to `/auth/refresh`.\n"
                "4. Use `access_token` in `Authorization: Bearer ...` for every subsequent call.\n"
                "5. When `access_token` expires (default 30m), `POST /auth/refresh` (no body — "
                "the refresh JWT is read from the cookie) → new access token plus a rotated refresh cookie.\n\n"
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
                "LabelEnrichRunResponse": LABEL_ENRICH_RUN_RESPONSE,
                "LabelSummary": LABEL_SUMMARY,
                "LabelsListResponse": LABELS_LIST_RESPONSE,
                "LabelDetail": LABEL_DETAIL_RESPONSE,
                "MyLabelPreferencesResponse": MY_LABEL_PREFERENCES_RESPONSE,
                "BacklogLabel": BACKLOG_LABEL,
                "BacklogResponse": BACKLOG_RESPONSE,
                "RunsListResponse": RUNS_LIST_RESPONSE,
                "EnrichmentOptions": ENRICHMENT_OPTIONS,
                "LabelHistoryCell": LABEL_HISTORY_CELL,
                "LabelHistoryResponse": LABEL_HISTORY_RESPONSE,
                "ArtistEnrichRunResponse": ARTIST_ENRICH_RUN_RESPONSE,
                "ArtistSummary": ARTIST_SUMMARY,
                "ArtistsListResponse": ARTISTS_LIST_RESPONSE,
                "ArtistDetail": ARTIST_DETAIL_RESPONSE,
                "MyArtistPreferencesResponse": MY_ARTIST_PREFERENCES_RESPONSE,
                "BacklogArtist": BACKLOG_ARTIST,
                "BacklogArtistResponse": BACKLOG_ARTIST_RESPONSE,
                "ArtistRunsListResponse": ARTIST_RUNS_LIST_RESPONSE,
                "ArtistHistoryCell": ARTIST_HISTORY_CELL,
                "ArtistHistoryResponse": ARTIST_HISTORY_RESPONSE,
                "PlaylistTrackResponse": PLAYLIST_TRACK_RESPONSE,
            },
        },
    }


def main() -> int:
    spec = build_openapi()
    out = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        "# AUTO-GENERATED by scripts/generate_openapi.py — do not edit by hand.\n"
        + yaml.safe_dump(spec, sort_keys=False, default_flow_style=False, allow_unicode=True)
    )
    print(f"wrote {out}  ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

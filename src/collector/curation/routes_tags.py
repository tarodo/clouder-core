"""Tag routes: user tags and per-track tag sets."""

from __future__ import annotations

import re as _re
import uuid
from typing import Any

from . import (
    InvalidTagColorError,
    InvalidTagIdsError,
    InvalidTagNameError,
    InvalidTagPayloadError,
    TagNotFoundError,
    TooManyTagsError,
    ValidationError,
    utc_now,
)
from .http import _json_response, _no_content, _parse_body, _parse_pagination
from .tags_repository import (
    TagsRepository,
)

_HEX_COLOR_RE = _re.compile(r"^#[0-9A-Fa-f]{6}$")


_MAX_TAG_NAME = 64


_MAX_TAGS_PER_TRACK = 50


def _normalize_tag_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _tag_dict(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "color": row.color,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _track_tag_dict(row) -> dict[str, Any]:
    return {"id": row.tag_id, "name": row.name, "color": row.color}


def _handle_create_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    body = _parse_body(event)
    name_raw = body.get("name")
    color = body.get("color")
    if not isinstance(name_raw, str):
        raise InvalidTagNameError("name is required")
    name = name_raw.strip()
    if not name or len(name) > _MAX_TAG_NAME:
        raise InvalidTagNameError("name must be 1..64 chars")
    if color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex or null")
    row = repo.create_tag(
        user_id=user_id,
        tag_id=str(uuid.uuid4()),
        name=name,
        normalized_name=_normalize_tag_name(name),
        color=color,
        now=utc_now(),
    )
    return _json_response(201, _tag_dict(row), correlation_id)


def _handle_list_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")
    page = repo.list_tags(
        user_id=user_id, limit=limit, offset=offset, search=search,
    )
    return _json_response(
        200,
        {
            "items": [_tag_dict(r) for r in page.items],
            "total": page.total,
            "limit": page.limit,
            "offset": page.offset,
        },
        correlation_id,
    )


def _handle_rename_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    body = _parse_body(event)
    has_name = "name" in body
    has_color = "color" in body
    name = body.get("name") if has_name else None
    color = body.get("color") if has_color else None
    normalized: str | None = None
    if has_name:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > _MAX_TAG_NAME:
            raise InvalidTagNameError("name must be 1..64 chars")
        name = name.strip()
        normalized = _normalize_tag_name(name)
    if has_color and color is not None:
        if not isinstance(color, str) or not _HEX_COLOR_RE.match(color):
            raise InvalidTagColorError("color must be #RRGGBB hex or null")
    if not has_name and not has_color:
        raise InvalidTagPayloadError(
            "at least one of name|color required"
        )
    row = repo.rename_tag(
        user_id=user_id, tag_id=tag_id,
        name=name, normalized_name=normalized,
        color=color, clear_color=has_color,
        now=utc_now(),
    )
    return _json_response(200, _tag_dict(row), correlation_id)


def _handle_delete_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    tag_id = (event.get("pathParameters") or {}).get("tag_id")
    if not tag_id:
        raise ValidationError("tag_id is required in path")
    ok = repo.delete_tag(user_id=user_id, tag_id=tag_id)
    if not ok:
        raise TagNotFoundError()
    return _no_content(correlation_id)


def _handle_list_track_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    grouped = repo.list_tags_for_tracks(user_id=user_id, track_ids=[track_id])
    items = grouped.get(track_id, [])
    return _json_response(
        200, {"tags": [_track_tag_dict(r) for r in items]}, correlation_id,
    )


def _handle_set_track_tags(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_ids = body.get("tag_ids")
    if not isinstance(tag_ids, list):
        raise InvalidTagIdsError("tag_ids must be an array")
    if len(tag_ids) > _MAX_TAGS_PER_TRACK:
        raise TooManyTagsError(
            f"Maximum {_MAX_TAGS_PER_TRACK} tags per track"
        )
    if any(not isinstance(t, str) or not t for t in tag_ids):
        raise InvalidTagIdsError("tag_ids must be non-empty strings")
    if len(set(tag_ids)) != len(tag_ids):
        raise InvalidTagIdsError("Duplicate tag ids")
    out = repo.set_track_tags(
        user_id=user_id, track_id=track_id, tag_ids=tag_ids, now=utc_now(),
    )
    return _json_response(
        200, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_add_track_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    track_id = (event.get("pathParameters") or {}).get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")
    body = _parse_body(event)
    tag_id = body.get("tag_id")
    if not isinstance(tag_id, str) or not tag_id:
        raise InvalidTagIdsError("tag_id required")
    out = repo.add_track_tag(
        user_id=user_id, track_id=track_id, tag_id=tag_id, now=utc_now(),
    )
    return _json_response(
        201, {"tags": [_tag_dict(r) for r in out]}, correlation_id,
    )


def _handle_remove_track_tag(
    event, repo: TagsRepository, user_id: str, correlation_id: str
):
    pp = event.get("pathParameters") or {}
    track_id = pp.get("track_id")
    tag_id = pp.get("tag_id")
    if not track_id or not tag_id:
        raise ValidationError("track_id and tag_id are required in path")
    repo.remove_track_tag(user_id=user_id, track_id=track_id, tag_id=tag_id)
    return _no_content(correlation_id)

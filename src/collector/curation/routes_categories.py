"""Category routes (spec-C): CRUD, ordering and category tracks."""

from __future__ import annotations

import uuid
from typing import Any

from ..artist_enrichment.auto_dispatch import (
    try_dispatch_artists_for_track,
)
from ..label_enrichment.auto_dispatch import (
    try_dispatch_for_track,
)
from ..logging_utils import log_event
from . import (
    BadQueryParamError,
    InvalidMatchError,
    NotFoundError,
    ValidationError,
    deps,
    utc_now,
)
from .categories_repository import (
    CategoriesRepository,
)
from .categories_service import (
    normalize_category_name,
    validate_category_name,
)
from .http import (
    _error,
    _json_response,
    _paginated_response,
    _parse_body,
    _parse_pagination,
)
from .schemas import (
    AddTrackIn,
    CreateCategoryIn,
    RenameCategoryIn,
    ReorderCategoriesIn,
)

_SORT_VALUES = {"title", "spotify_release_date", "added_at"}
_ORDER_VALUES = {"asc", "desc"}


def _category_response(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "position": row.position,
        "track_count": row.track_count,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _handle_create_category(
    event, repo: CategoriesRepository, user_id: str, correlation_id: str
):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = CreateCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    category_id = str(uuid.uuid4())
    now = utc_now()
    row = repo.create(
        user_id=user_id,
        style_id=style_id,
        category_id=category_id,
        name=body.name.strip(),
        normalized_name=normalized,
        now=now,
        correlation_id=correlation_id,
    )
    log_event(
        "INFO",
        "category_created",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
        style_id=row.style_id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(201, payload, correlation_id)


def _handle_list_by_style(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    result = repo.list_by_style(
        user_id=user_id, style_id=style_id, limit=limit, offset=offset,
    )
    return _paginated_response(result, _category_response, correlation_id)


def _handle_list_all(event, repo, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    result = repo.list_all(user_id=user_id, limit=limit, offset=offset)
    return _paginated_response(result, _category_response, correlation_id)


def _handle_get_detail(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    row = repo.get(user_id=user_id, category_id=cid)
    if row is None:
        raise NotFoundError("category_not_found", "Category not found")
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_rename(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = RenameCategoryIn.model_validate(_parse_body(event))
    validate_category_name(body.name)
    normalized = normalize_category_name(body.name)
    if not normalized:
        raise ValidationError("Name must be non-empty")
    row = repo.rename(
        user_id=user_id,
        category_id=cid,
        name=body.name.strip(),
        normalized_name=normalized,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_renamed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=row.id,
    )
    payload = _category_response(row)
    payload["correlation_id"] = correlation_id
    return _json_response(200, payload, correlation_id)


def _handle_soft_delete(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    tags_repo = deps.create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )
    deleted = repo.soft_delete(
        user_id=user_id,
        category_id=cid,
        now=utc_now(),
        correlation_id=correlation_id,
        tags_repo=tags_repo,
    )
    if not deleted:
        raise NotFoundError("category_not_found", "Category not found")
    log_event(
        "INFO",
        "category_soft_deleted",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }


def _handle_reorder(event, repo, user_id, correlation_id):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    body = ReorderCategoriesIn.model_validate(_parse_body(event))
    rows = repo.reorder(
        user_id=user_id,
        style_id=style_id,
        ordered_ids=body.category_ids,
        now=utc_now(),
    )
    log_event(
        "INFO",
        "category_order_updated",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        size=len(rows),
    )
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in rows],
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _track_in_category_response(item) -> dict[str, Any]:
    track = dict(item.track)
    track["added_at"] = item.added_at
    track["source_triage_block_id"] = item.source_triage_block_id
    track["tags"] = [
        {"id": t.tag_id, "name": t.name, "color": t.color}
        for t in getattr(item, "tags", ())
    ]
    track["used_in_playlist"] = bool(track.get("used_in_playlist", False))
    return track


def _handle_list_tracks(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    sort = (qp.get("sort") or "added_at").lower()
    if sort not in _SORT_VALUES:
        raise BadQueryParamError(
            f"sort must be one of {sorted(_SORT_VALUES)}"
        )
    order = (qp.get("order") or "desc").lower()
    if order not in _ORDER_VALUES:
        raise BadQueryParamError("order must be 'asc' or 'desc'")

    tags_raw = qp.get("tags")
    tag_ids = [t for t in (tags_raw.split(",") if tags_raw else []) if t]
    tag_match = (qp.get("match") or "all").lower()
    if tag_match not in ("all", "any"):
        raise InvalidMatchError("match must be 'all' or 'any'")

    tags_repo = deps.create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )

    fresh_raw = (qp.get("fresh") or "").strip()
    fresh = fresh_raw == "1"

    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
        sort=sort, order=order,
        tag_ids=tag_ids or None, tag_match=tag_match, tags_repo=tags_repo,
        fresh=fresh,
    )
    return _paginated_response(
        result, _track_in_category_response, correlation_id
    )


def _handle_add_track(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    body = AddTrackIn.model_validate(_parse_body(event))
    result, was_new = repo.add_track(
        user_id=user_id, category_id=cid, track_id=body.track_id,
        source_triage_block_id=None, now=utc_now(),
    )
    log_event(
        "INFO",
        "category_track_added",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=body.track_id,
        result="added" if was_new else "already_present",
    )
    if was_new:
        try_dispatch_for_track(track_id=body.track_id, user_id=user_id)
        try_dispatch_artists_for_track(track_id=body.track_id, user_id=user_id)
    payload = {
        "result": "added" if was_new else "already_present",
        "added_at": result["added_at"],
        "source_triage_block_id": result["source_triage_block_id"],
        "correlation_id": correlation_id,
    }
    return _json_response(201 if was_new else 200, payload, correlation_id)


def _handle_remove_track(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    cid = pp.get("id")
    tid = pp.get("track_id")
    if not cid or not tid:
        raise ValidationError("id and track_id are required in path")
    tags_repo = deps.create_default_tags_repository()
    if tags_repo is None:
        return _error(
            503, "db_not_configured", "Database not configured", correlation_id,
        )
    deleted = repo.remove_track(
        user_id=user_id, category_id=cid, track_id=tid, tags_repo=tags_repo,
    )
    if not deleted:
        raise NotFoundError("track_not_in_category", "Track not in category")
    log_event(
        "INFO",
        "category_track_removed",
        correlation_id=correlation_id,
        user_id=user_id,
        category_id=cid,
        track_id=tid,
    )
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }

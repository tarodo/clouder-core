"""Lambda handler for the user-curation surface (spec-C/D/E).

`_ROUTE_TABLE` is the single source of truth: each `routeKey` maps to a
`(handler, repo_factory)` tuple. spec-D and spec-E will append entries.
Every route is JWT-gated by the API Gateway Lambda Authorizer (spec-A);
`user_id` is read from `event.requestContext.authorizer.lambda.user_id`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pydantic import ValidationError as PydanticValidationError

from .curation import (
    CurationError,
    InactiveStagingFinalizeError,
    NotFoundError,
    PaginatedResult,
    TracksNotInSourceError,
    ValidationError,
    utc_now,
)
from .curation.categories_repository import (
    CategoriesRepository,
    create_default_categories_repository,
)
from .curation.categories_service import (
    normalize_category_name,
    validate_category_name,
)
from .curation.schemas import (
    AddTrackIn,
    CreateCategoryIn,
    CreateTriageBlockIn,
    RenameCategoryIn,
    ReorderCategoriesIn,
)
from .curation.triage_repository import (
    TriageRepository,
    create_default_triage_repository,
)
from .logging_utils import log_event


def _extract_correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if isinstance(key, str) and key.lower() == "x-correlation-id":
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return str(uuid.uuid4())


def _json_response(
    status_code: int,
    payload: Mapping[str, Any],
    correlation_id: str,
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "content-type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload),
    }


def _error(
    status: int, error_code: str, message: str, correlation_id: str
) -> dict[str, Any]:
    return _json_response(
        status,
        {
            "error_code": error_code,
            "message": message,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _curation_error_response(
    exc: CurationError, correlation_id: str
) -> dict[str, Any]:
    """Map a CurationError to an HTTP envelope, attaching structured payloads
    for error subclasses that carry them (InactiveStagingFinalizeError,
    TracksNotInSourceError)."""

    payload: dict[str, Any] = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    if isinstance(exc, InactiveStagingFinalizeError):
        payload["inactive_buckets"] = list(exc.inactive_buckets)
    elif isinstance(exc, TracksNotInSourceError):
        payload["not_in_source"] = list(exc.not_in_source)
    return _json_response(exc.http_status, payload, correlation_id)


def _user_id_or_none(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authz = rc.get("authorizer")
        if isinstance(authz, Mapping):
            ctx = authz.get("lambda")
            if isinstance(ctx, Mapping):
                uid = ctx.get("user_id")
                if isinstance(uid, str) and uid:
                    return uid
    return None


def _parse_body(event: Mapping[str, Any]) -> Mapping[str, Any]:
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, str):
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Invalid JSON body: {exc}") from exc
    if isinstance(body, Mapping):
        return body
    raise ValidationError("Invalid body type")


def _parse_pagination(event: Mapping[str, Any]) -> tuple[int, int]:
    qp = event.get("queryStringParameters") or {}
    raw_limit = qp.get("limit", "50")
    raw_offset = qp.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ValidationError("offset must be an integer")
    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    if offset < 0:
        raise ValidationError("offset must be >= 0")
    return limit, offset


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


def _paginated_response(
    result, mapper, correlation_id: str
) -> dict[str, Any]:
    return _json_response(
        200,
        {
            "items": [mapper(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


# ---------- Routing ---------------------------------------------------------

def lambda_handler(
    event: Mapping[str, Any], context: Any
) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)

    user_id = _user_id_or_none(event)
    if user_id is None:
        return _error(401, "unauthorized", "Missing authorizer context", correlation_id)

    rc = event.get("requestContext") or {}
    route_key = rc.get("routeKey") if isinstance(rc, Mapping) else None
    if not isinstance(route_key, str):
        return _error(404, "not_found", "Unknown route", correlation_id)

    entry = _ROUTE_TABLE.get(route_key)
    if entry is None:
        return _error(404, "not_found", "Unknown route", correlation_id)

    handler, factory = entry
    repo = factory()
    if repo is None:
        return _error(503, "db_not_configured", "Database not configured", correlation_id)

    try:
        return handler(event, repo, user_id, correlation_id)
    except PydanticValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", ())) or "body"
        return _error(
            422,
            "validation_error",
            f"{loc}: {first['msg']}",
            correlation_id,
        )
    except CurationError as exc:
        return _curation_error_response(exc, correlation_id)
    except Exception as exc:  # noqa: BLE001
        log_event(
            "ERROR",
            "curation_handler_unhandled",
            correlation_id=correlation_id,
            error=str(exc),
        )
        return _error(500, "internal_error", "Internal error", correlation_id)


# ---------- Route handlers (Tasks 14–22 fill in) ----------------------------

# Each takes (event, repo, user_id, correlation_id) and returns a Lambda response dict.


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
    deleted = repo.soft_delete(
        user_id=user_id,
        category_id=cid,
        now=utc_now(),
        correlation_id=correlation_id,
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
    return track


def _handle_list_tracks(event, repo, user_id, correlation_id):
    cid = (event.get("pathParameters") or {}).get("id")
    if not cid:
        raise ValidationError("id is required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")
    result = repo.list_tracks(
        user_id=user_id, category_id=cid,
        limit=limit, offset=offset, search=search,
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
    deleted = repo.remove_track(
        user_id=user_id, category_id=cid, track_id=tid,
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


# ---------- spec-D triage handlers ------------------------------------------


def _serialize_triage_block(row, correlation_id: str) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "buckets": [
            {
                "id": b.id,
                "bucket_type": b.bucket_type,
                "category_id": b.category_id,
                "category_name": b.category_name,
                "inactive": b.inactive,
                "track_count": b.track_count,
            }
            for b in row.buckets
        ],
        "correlation_id": correlation_id,
    }


def _create_triage_block(
    event, triage_repo: TriageRepository, user_id: str, correlation_id: str
):
    schema = CreateTriageBlockIn.model_validate(_parse_body(event))
    out = triage_repo.create_block(
        user_id=user_id,
        style_id=schema.style_id,
        name=schema.name,
        date_from=schema.date_from,
        date_to=schema.date_to,
    )
    log_event(
        "INFO",
        "triage_block_created",
        correlation_id=correlation_id,
        user_id=user_id,
        block_id=out.id,
        style_id=out.style_id,
        date_from=out.date_from,
        date_to=out.date_to,
    )
    return _json_response(
        201, _serialize_triage_block(out, correlation_id), correlation_id
    )


def _serialize_block_summary(row) -> dict[str, Any]:
    return {
        "id": row.id,
        "style_id": row.style_id,
        "style_name": row.style_name,
        "name": row.name,
        "date_from": row.date_from,
        "date_to": row.date_to,
        "status": row.status,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "finalized_at": row.finalized_at,
        "track_count": row.track_count,
    }


def _serialize_bucket_track(row) -> dict[str, Any]:
    return {
        "track_id": row.track_id,
        "title": row.title,
        "mix_name": row.mix_name,
        "isrc": row.isrc,
        "bpm": row.bpm,
        "length_ms": row.length_ms,
        "publish_date": row.publish_date,
        "spotify_release_date": row.spotify_release_date,
        "spotify_id": row.spotify_id,
        "release_type": row.release_type,
        "is_ai_suspected": row.is_ai_suspected,
        "artists": list(row.artists),
        "added_at": row.added_at,
    }


def _parse_status_query(event: Mapping[str, Any]) -> str | None:
    qp = event.get("queryStringParameters") or {}
    status = qp.get("status")
    if status is None:
        return None
    if status not in ("IN_PROGRESS", "FINALIZED"):
        raise ValidationError("status must be IN_PROGRESS or FINALIZED")
    return status


def _list_triage_blocks_by_style(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    style_id = (event.get("pathParameters") or {}).get("style_id")
    if not style_id:
        raise ValidationError("style_id is required in path")
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_by_style(
        user_id=user_id,
        style_id=style_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    log_event(
        "INFO",
        "triage_block_listed",
        correlation_id=correlation_id,
        user_id=user_id,
        style_id=style_id,
        count=len(items),
        total=total,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _list_triage_blocks_all(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    limit, offset = _parse_pagination(event)
    status = _parse_status_query(event)

    items, total = repo.list_blocks_all(
        user_id=user_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_block_summary(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _get_triage_block(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    block_id = (event.get("pathParameters") or {}).get("id")
    if not block_id:
        raise ValidationError("id is required in path")
    out = repo.get_block(user_id=user_id, block_id=block_id)
    if out is None:
        raise NotFoundError(
            "triage_block_not_found",
            f"triage block not found: {block_id}",
        )
    return _json_response(
        200, _serialize_triage_block(out, correlation_id), correlation_id
    )


def _list_bucket_tracks(
    event, repo: TriageRepository, user_id: str, correlation_id: str
):
    pp = event.get("pathParameters") or {}
    block_id = pp.get("id")
    bucket_id = pp.get("bucket_id")
    if not block_id or not bucket_id:
        raise ValidationError("id and bucket_id are required in path")
    limit, offset = _parse_pagination(event)
    qp = event.get("queryStringParameters") or {}
    search = qp.get("search")

    items, total = repo.list_bucket_tracks(
        user_id=user_id,
        block_id=block_id,
        bucket_id=bucket_id,
        limit=limit,
        offset=offset,
        search=search,
    )
    return _json_response(
        200,
        {
            "items": [_serialize_bucket_track(r) for r in items],
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


# Single source of truth for routing: each route maps to a
# `(handler, repo_factory)` tuple. Adding a new route requires picking the
# right factory explicitly — there is no silent fallback. spec-C routes use
# `create_default_categories_repository`; spec-D triage routes use
# `create_default_triage_repository`.
def _categories_factory() -> Any:
    return create_default_categories_repository()


def _triage_factory() -> Any:
    return create_default_triage_repository()


_ROUTE_TABLE: dict[str, tuple[Callable[..., dict[str, Any]], Callable[[], Any]]] = {
    "POST /styles/{style_id}/categories": (_handle_create_category, _categories_factory),
    "GET /styles/{style_id}/categories": (_handle_list_by_style, _categories_factory),
    "GET /categories": (_handle_list_all, _categories_factory),
    "GET /categories/{id}": (_handle_get_detail, _categories_factory),
    "PATCH /categories/{id}": (_handle_rename, _categories_factory),
    "DELETE /categories/{id}": (_handle_soft_delete, _categories_factory),
    "PUT /styles/{style_id}/categories/order": (_handle_reorder, _categories_factory),
    "GET /categories/{id}/tracks": (_handle_list_tracks, _categories_factory),
    "POST /categories/{id}/tracks": (_handle_add_track, _categories_factory),
    "DELETE /categories/{id}/tracks/{track_id}": (_handle_remove_track, _categories_factory),
    "POST /triage/blocks": (_create_triage_block, _triage_factory),
    "GET /styles/{style_id}/triage/blocks": (_list_triage_blocks_by_style, _triage_factory),
    "GET /triage/blocks": (_list_triage_blocks_all, _triage_factory),
    "GET /triage/blocks/{id}": (_get_triage_block, _triage_factory),
    "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks": (_list_bucket_tracks, _triage_factory),
}

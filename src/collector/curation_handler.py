"""Lambda handler for the user-curation surface (spec-C/D/E).

Routes for spec-C only at this revision. spec-D and spec-E will append
to `_ROUTE_TABLE`. Every route is JWT-gated by the API Gateway Lambda
Authorizer (spec-A); `user_id` is read from
`event.requestContext.authorizer.lambda.user_id`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from pydantic import ValidationError as PydanticValidationError

from .curation import (
    CurationError,
    NotFoundError,
    PaginatedResult,
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
from .curation.schemas import CreateCategoryIn
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

    handler = _ROUTE_TABLE.get(route_key)
    if handler is None:
        return _error(404, "not_found", "Unknown route", correlation_id)

    repo = create_default_categories_repository()
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
        return _error(exc.http_status, exc.error_code, exc.message, correlation_id)
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
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_list_all(event, repo, user_id, correlation_id):
    limit, offset = _parse_pagination(event)
    result = repo.list_all(user_id=user_id, limit=limit, offset=offset)
    return _json_response(
        200,
        {
            "items": [_category_response(r) for r in result.items],
            "total": result.total,
            "limit": result.limit,
            "offset": result.offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


_ROUTE_TABLE: dict[str, Callable[..., dict[str, Any]]] = {
    "POST /styles/{style_id}/categories": _handle_create_category,
}

_ROUTE_TABLE["GET /styles/{style_id}/categories"] = _handle_list_by_style
_ROUTE_TABLE["GET /categories"] = _handle_list_all

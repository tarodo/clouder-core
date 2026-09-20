"""HTTP routes for per-user style selection."""

from __future__ import annotations

import json
from typing import Any, Mapping

from ..data_api import create_default_data_api_client
from ..errors import ValidationError
from ..settings import get_data_api_settings
from .repository import MAX_SELECTION, UserStylesRepository


def _unauthorized() -> tuple[int, dict[str, Any]]:
    return 401, {"error_code": "unauthorized", "message": "Authentication required"}


def _no_db() -> tuple[int, dict[str, Any]]:
    return 503, {
        "error_code": "db_not_configured",
        "message": "Database is not configured",
    }


def _build_repository() -> UserStylesRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return UserStylesRepository(data_api=client)


def extract_user_id(event: Mapping[str, Any]) -> str | None:
    rc = event.get("requestContext")
    if not isinstance(rc, Mapping):
        return None
    authz = rc.get("authorizer")
    if not isinstance(authz, Mapping):
        return None
    ctx = authz.get("lambda")
    if isinstance(ctx, Mapping):
        return ctx.get("user_id")
    return None


def handle_get_styles(
    event: Mapping[str, Any],
    *,
    limit: int,
    offset: int,
    search: str | None,
) -> tuple[int, dict[str, Any]]:
    user_id = extract_user_id(event)
    if not user_id:
        return _unauthorized()

    qs = event.get("queryStringParameters") or {}
    scope = (qs.get("scope") or "").strip()
    if scope and scope != "all":
        raise ValidationError("scope must be 'all'")

    repo = _build_repository()
    if repo is None:
        return _no_db()

    if scope == "all":
        items = repo.list_catalog(
            user_id=user_id, limit=limit, offset=offset, search=search
        )
        total = repo.count_all(search)
    elif repo.count_selection(user_id) > 0:
        items = repo.list_for_user(
            user_id=user_id, limit=limit, offset=offset, search=search
        )
        total = repo.count_for_user(user_id=user_id, search=search)
    else:
        items = repo.list_all(limit=limit, offset=offset, search=search)
        total = repo.count_all(search)

    return 200, {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def handle_put_my_styles(event: Mapping[str, Any]) -> tuple[int, dict[str, Any]]:
    user_id = extract_user_id(event)
    if not user_id:
        return _unauthorized()

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON body: {exc}")

    style_ids = body.get("style_ids") if isinstance(body, Mapping) else None
    if not isinstance(style_ids, list) or not all(
        isinstance(sid, str) for sid in style_ids
    ):
        raise ValidationError("style_ids must be an array of style ids")
    if len(set(style_ids)) != len(style_ids):
        raise ValidationError("style_ids must be unique")
    if len(style_ids) > MAX_SELECTION:
        raise ValidationError(
            f"style_ids exceeds {MAX_SELECTION} entries"
        )

    repo = _build_repository()
    if repo is None:
        return _no_db()

    repo.replace_selection(user_id=user_id, style_ids=style_ids)
    return 204, {}

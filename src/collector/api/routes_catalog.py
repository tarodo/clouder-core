"""Catalog reads: track and album lists, styles, the curation funnel."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from ..errors import AppError, ValidationError
from ..logging_utils import log_event
from . import deps
from .http import _extract_route_key, _json_response, _parse_pagination_params

_LIST_ROUTES = {
    "GET /tracks": ("tracks", "list_tracks", "count_tracks"),
    "GET /albums": ("albums", "list_albums", "count_albums"),
}


def _handle_list(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    entity, list_method, count_method = _LIST_ROUTES[route_key]

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {
                "error_code": "db_not_configured",
                "message": "Database is not configured",
            },
            correlation_id,
        )

    try:
        limit, offset, search = _parse_pagination_params(event)
    except ValidationError as exc:
        return _json_response(
            400,
            {"error_code": "validation_error", "message": exc.message},
            correlation_id,
        )

    rows = getattr(repository, list_method)(limit, offset, search)
    total = getattr(repository, count_method)(search)

    items = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            item[key] = value
        if "artist_names" in item:
            raw = item.pop("artist_names")
            item["artists"] = [n.strip() for n in raw.split(",")] if raw else []
        items.append(item)

    log_event(
        "INFO",
        "list_completed",
        correlation_id=correlation_id,
        entity=entity,
        result_count=len(items),
        total_count=total,
        limit=limit,
        offset=offset,
    )

    return _json_response(
        200,
        {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


_FUNNEL_STAGES = ("triaged", "categorized", "playlisted")


def _handle_analytics_funnel(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    """Personal: own data for any signed-in user; admins may pass ?user_id."""
    from datetime import time as dtime
    from datetime import timedelta

    from ..analytics_handler import (
        AnalyticsError,
        listening_windows,
        parse_tz_offset,
        resolve_user,
    )

    qs = event.get("queryStringParameters") or {}
    qs = qs if isinstance(qs, Mapping) else {}
    try:
        off = parse_tz_offset(qs.get("tz_offset_min"))
        user_id = resolve_user(event, str(qs.get("user_id") or ""))
    except AnalyticsError as exc:
        raise AppError(exc.status_code, exc.error_code, exc.message) from exc
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    w = listening_windows(deps.utc_now(), off)

    def local_midnight_utc(d: date) -> datetime:
        return datetime.combine(d, dtime(), tzinfo=UTC) - timedelta(minutes=off)

    rows = repository.analytics_funnel(
        user_id,
        day_start=local_midnight_utc(w["today"]),
        week_start=local_midnight_utc(w["week_from"]),
        month_start=local_midnight_utc(w["month_from"]),
    )
    by = {r["stage"]: r for r in rows}
    stages = [
        {"stage": s, **{k: int(by.get(s, {}).get(k) or 0) for k in ("day", "week", "month")}}
        for s in _FUNNEL_STAGES
    ]
    return _json_response(
        200,
        {"today": w["today"].isoformat(), "stages": stages, "correlation_id": correlation_id},
        correlation_id,
    )


def _handle_get_styles(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    from ..user_styles.routes import handle_get_styles

    limit, offset, search = _parse_pagination_params(event)
    status, body = handle_get_styles(
        event, limit=limit, offset=offset, search=search
    )
    if status == 200:
        body["correlation_id"] = correlation_id
        log_event(
            "INFO",
            "list_completed",
            correlation_id=correlation_id,
            entity="styles",
            result_count=len(body["items"]),
            total_count=body["total"],
            limit=limit,
            offset=offset,
        )
    return _json_response(status, body, correlation_id)


def _handle_put_my_styles(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    from ..user_styles.routes import extract_user_id, handle_put_my_styles

    status, body = handle_put_my_styles(event)
    if status == 204:
        log_event(
            "INFO",
            "user_styles_updated",
            correlation_id=correlation_id,
            user_id=extract_user_id(event),
        )
        return {
            "statusCode": 204,
            "headers": {"x-correlation-id": correlation_id},
            "body": "",
        }
    return _json_response(status, body, correlation_id)

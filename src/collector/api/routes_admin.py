"""Admin catalog views: release coverage, style visibility, users."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import ValidationError
from ..logging_utils import log_event
from . import deps
from .http import _iso, _json_response, _parse_json_body


def _handle_admin_coverage(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("week_year") if isinstance(qs, Mapping) else None
    if not raw or not raw.isdigit():
        raise ValidationError("week_year is required (4-digit year)")
    week_year = int(raw)
    if week_year < 2000 or week_year > 2100:
        raise ValidationError("week_year out of range")

    from ..saturday_week import weeks_in_year

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    rows = repository.coverage_for_year(week_year)

    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        bp_raw = row.get("beatport_style_id")
        if bp_raw is None:
            continue
        try:
            sid = int(bp_raw)
        except (TypeError, ValueError):
            continue
        if sid not in grouped:
            grouped[sid] = {
                "style_id": sid,
                "clouder_style_id": row["clouder_style_id"],
                "style_name": row["style_name"],
                "is_hidden": bool(row.get("is_hidden")),
                "cells": [],
            }
        if row.get("run_id") is None:
            continue
        grouped[sid]["cells"].append(
            {
                "week_number": row["week_number"],
                "status": row["status"],
                "run_id": row["run_id"],
                "item_count": row["item_count"],
                "is_custom_range": bool(row.get("is_custom_range")),
                "period_start": _iso(row.get("period_start")),
                "period_end": _iso(row.get("period_end")),
                "started_at": _iso(row.get("started_at")),
                "finished_at": _iso(row.get("finished_at")),
            }
        )

    stats_rows = repository.spotify_stats_for_year(week_year)
    spotify_by_style: dict[int, list[dict[str, Any]]] = {}
    for row in stats_rows:
        try:
            sid = int(row["beatport_style_id"])
        except (KeyError, TypeError, ValueError):
            continue
        spotify_by_style.setdefault(sid, []).append(
            {
                "week_number": int(row["week_number"]),
                "total": int(row["total"]),
                "found": int(row["found"]),
                "not_found": int(row["not_found"]),
                "pending": int(row["pending"]),
                "no_isrc": int(row["no_isrc"]),
            }
        )
    for sid, style_entry in grouped.items():
        style_entry["spotify_weeks"] = sorted(
            spotify_by_style.get(sid, []), key=lambda w: w["week_number"]
        )

    return _json_response(
        200,
        {
            "week_year": week_year,
            "weeks_in_year": weeks_in_year(week_year),
            "styles": list(grouped.values()),
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _handle_admin_style_visibility(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    payload = _parse_json_body(event)
    is_hidden = payload.get("is_hidden")
    if not isinstance(is_hidden, bool):
        raise ValidationError("is_hidden must be a boolean")

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    path = event.get("pathParameters") or {}
    style_id = str(path.get("style_id") or "")
    if not repository.set_style_hidden(style_id, is_hidden, deps.utc_now()):
        return _json_response(
            404,
            {"error_code": "style_not_found", "message": "Style not found"},
            correlation_id,
        )

    log_event(
        "INFO",
        "style_visibility_updated",
        correlation_id=correlation_id,
        style_id=style_id,
        is_hidden=is_hidden,
    )
    return _json_response(
        200,
        {"style_id": style_id, "is_hidden": is_hidden, "correlation_id": correlation_id},
        correlation_id,
    )


def _handle_admin_users(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    return _json_response(
        200,
        {"users": repository.list_users(), "correlation_id": correlation_id},
        correlation_id,
    )

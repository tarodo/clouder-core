"""Ingest runs: the admin list and one run's detail."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ..errors import ValidationError
from . import deps
from .http import _extract_api_request_id, _iso, _json_response

_PHASE_PREFIX = re.compile(r"^\[phase=([^\]]+)\] ")


def _split_phase_prefix(msg: str | None) -> tuple[str | None, str | None]:
    if not msg:
        return None, msg
    m = _PHASE_PREFIX.match(msg)
    if not m:
        return None, msg
    return m.group(1), msg[m.end():]


def _handle_admin_runs(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    qs = event.get("queryStringParameters") or {}
    qs = qs if isinstance(qs, Mapping) else {}

    def _int_param(name: str) -> int:
        raw = qs.get(name)
        if not isinstance(raw, str) or not raw.isdigit() or int(raw) < 1:
            raise ValidationError(f"{name} is required (positive integer)")
        return int(raw)

    style_id = _int_param("style_id")
    week_year = _int_param("week_year")
    week_number = _int_param("week_number")

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    rows = repository.list_runs_for_cell(style_id, week_year, week_number)
    items = [
        {
            "run_id": r["run_id"],
            "status": r["status"],
            "started_at": _iso(r.get("started_at")),
            "finished_at": _iso(r.get("finished_at")),
            "item_count": r.get("item_count"),
            "processed_count": r.get("processed_count"),
            "error_code": r.get("error_code"),
            "error_message": r.get("error_message"),
            "is_custom_range": bool(r.get("is_custom_range")),
            "period_start": _iso(r.get("period_start")),
            "period_end": _iso(r.get("period_end")),
        }
        for r in rows
    ]

    return _json_response(200, {"items": items, "correlation_id": correlation_id}, correlation_id)


def _handle_get_run(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    del context
    api_request_id = _extract_api_request_id(event)
    path_parameters = event.get("pathParameters")
    run_id = None
    if isinstance(path_parameters, Mapping):
        candidate = path_parameters.get("run_id")
        if isinstance(candidate, str) and candidate:
            run_id = candidate

    if not run_id:
        return _json_response(
            400,
            {"error_code": "validation_error", "message": "run_id is required"},
            correlation_id,
        )

    repository = deps.create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {
                "error_code": "db_not_configured",
                "message": "Run status storage is not configured",
            },
            correlation_id,
        )

    row = repository.get_run(run_id)
    if row is None:
        return _json_response(
            404, {"error_code": "not_found", "message": "Run not found"}, correlation_id
        )

    error = None
    if row.get("error_code"):
        phase, clean_msg = _split_phase_prefix(row.get("error_message"))
        error = {
            "code": row.get("error_code"),
            "message": clean_msg,
        }
        if phase is not None:
            error["phase"] = phase

    response = {
        "run_id": run_id,
        "status": row.get("status"),
        "processed_counts": {
            "processed": int(row.get("processed_count") or 0),
            "total": int(row.get("item_count") or 0),
        },
        "error": error,
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "api_request_id": api_request_id,
        "correlation_id": correlation_id,
    }
    return _json_response(200, response, correlation_id)

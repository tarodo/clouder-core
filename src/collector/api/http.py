"""Event parsing and JSON responses shared by the collector-API routes."""

from __future__ import annotations

import base64
import json
import uuid
from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..errors import AdminRequiredError, AppError, ValidationError
from ..schemas import validation_error_message
from ..settings import ApiSettings, get_api_settings


def _require_admin(event: Mapping[str, Any]) -> None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping) and bool(ctx.get("is_admin")):
                return
    raise AdminRequiredError()


def _parse_iso_date_field(payload: Mapping[str, Any], name: str) -> date:
    raw = payload.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"{name} is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _parse_pagination_params(
    event: Mapping[str, Any],
) -> tuple[int, int, str | None]:
    query_params = event.get("queryStringParameters") or {}
    raw_limit = query_params.get("limit", "50")
    raw_offset = query_params.get("offset", "0")
    search = query_params.get("search")

    try:
        limit = int(raw_limit)
    except (ValueError, TypeError):
        raise ValidationError("limit must be an integer")
    try:
        offset = int(raw_offset)
    except (ValueError, TypeError):
        raise ValidationError("offset must be an integer")

    if limit < 1 or limit > 200:
        raise ValidationError("limit must be between 1 and 200")
    if offset < 0:
        raise ValidationError("offset must be non-negative")

    if search is not None:
        search = search.strip()
        if not search:
            search = None

    return limit, offset, search


def _parse_date_param(event: Mapping[str, Any], name: str) -> date | None:
    query_params = event.get("queryStringParameters") or {}
    raw = query_params.get(name) if isinstance(query_params, Mapping) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _load_api_settings() -> ApiSettings:
    try:
        return get_api_settings()
    except PydanticValidationError as exc:
        raise AppError(
            status_code=500,
            error_code="config_error",
            message=f"Collector configuration is invalid: {validation_error_message(exc)}",
        ) from exc


def _parse_json_body(event: Mapping[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if body is None:
        raise ValidationError("Request body is required")

    if event.get("isBase64Encoded"):
        try:
            body = base64.b64decode(body).decode("utf-8")
        except Exception as exc:
            raise ValidationError("Request body base64 payload is invalid") from exc

    if not isinstance(body, str):
        raise ValidationError("Request body must be a JSON string")

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValidationError("Request body must be valid JSON") from exc

    if not isinstance(parsed, dict):
        raise ValidationError("Request body must be a JSON object")
    return parsed


def _extract_route_key(event: Mapping[str, Any]) -> str:
    request_context = event.get("requestContext")
    if isinstance(request_context, Mapping):
        route_key = request_context.get("routeKey")
        if isinstance(route_key, str):
            return route_key
    top_level = event.get("routeKey")
    if isinstance(top_level, str):
        return top_level
    return ""


def _extract_api_request_id(event: Mapping[str, Any]) -> str:
    request_context = event.get("requestContext")
    if isinstance(request_context, Mapping):
        request_id = request_context.get("requestId")
        if isinstance(request_id, str) and request_id:
            return request_id
    return "unknown"


def _extract_correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        for key, value in headers.items():
            if (
                isinstance(key, str)
                and key.lower() == "x-correlation-id"
                and isinstance(value, str)
                and value.strip()
            ):
                return value.strip()
    return str(uuid.uuid4())


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_response(
    status_code: int, payload: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }

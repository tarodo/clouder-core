"""Shared request/response helpers for the curation Lambda routes."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any

from ..logging_utils import log_event
from . import (
    CurationError,
    InactiveStagingFinalizeError,
    TrackNotInUserScopeError,
    TracksNotInSourceError,
    ValidationError,
)


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


def _error(status: int, error_code: str, message: str, correlation_id: str) -> dict[str, Any]:
    return _json_response(
        status,
        {
            "error_code": error_code,
            "message": message,
            "correlation_id": correlation_id,
        },
        correlation_id,
    )


def _curation_error_response(exc: CurationError, correlation_id: str) -> dict[str, Any]:
    """Map a CurationError to an HTTP envelope, attaching structured payloads
    for error subclasses that carry them (InactiveStagingFinalizeError,
    TracksNotInSourceError)."""

    # Server-side / upstream-dependency failures (>= 500, e.g. ytmusic_api_error
    # = 502) used to be returned to the client but never logged, leaving
    # CloudWatch blind to the real YouTube status/reason. Expected client errors
    # (4xx) stay quiet to avoid noise. status_code/reason are the upstream YouTube
    # values when the error carries them.
    if exc.http_status >= 500:
        log_event(
            "ERROR",
            "curation_error_returned",
            correlation_id=correlation_id,
            error_code=exc.error_code,
            error_type=type(exc).__name__,
            error_message=exc.message,
            status_code=getattr(exc, "status_code", None),
            reason=getattr(exc, "reason", None),
        )

    payload: dict[str, Any] = {
        "error_code": exc.error_code,
        "message": exc.message,
        "correlation_id": correlation_id,
    }
    if isinstance(exc, InactiveStagingFinalizeError):
        payload["inactive_buckets"] = list(exc.inactive_buckets)
    elif isinstance(exc, TracksNotInSourceError):
        payload["not_in_source"] = list(exc.not_in_source)
    elif isinstance(exc, TrackNotInUserScopeError):
        payload["missing_track_ids"] = list(exc.missing_track_ids)
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


def _paginated_response(result, mapper, correlation_id: str) -> dict[str, Any]:
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


def _no_content(correlation_id: str) -> dict[str, Any]:
    return {
        "statusCode": 204,
        "headers": {"x-correlation-id": correlation_id},
        "body": "",
    }

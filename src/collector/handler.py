"""AWS Lambda handler for Beatport weekly releases collection."""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from .beatport_client import BeatportClient
from .errors import AppError, ValidationError
from .logging_utils import log_event
from .models import compute_iso_week_date_range, validate_collect_request
from .storage import S3Storage, create_default_s3_client


def lambda_handler(event: Mapping[str, Any], context: Any) -> Dict[str, Any]:
    started_at = time.perf_counter()
    api_request_id = _extract_api_request_id(event)
    lambda_request_id = getattr(context, "aws_request_id", "unknown")
    correlation_id = _extract_correlation_id(event)

    try:
        body = _parse_json_body(event)
        req = validate_collect_request(body)
        week_start, week_end = compute_iso_week_date_range(req.iso_year, req.iso_week)
        run_id = str(uuid.uuid4())

        beatport_client = BeatportClient(base_url=os.getenv("BEATPORT_API_BASE_URL", "https://api.beatport.com/v4/catalog"))
        releases, api_pages_fetched = beatport_client.fetch_weekly_releases(
            bp_token=req.bp_token,
            style_id=req.style_id,
            week_start=week_start,
            week_end=week_end,
            correlation_id=correlation_id,
        )

        duration_ms = int((time.perf_counter() - started_at) * 1000)
        item_count = len(releases)

        meta = {
            "style_id": req.style_id,
            "iso_year": req.iso_year,
            "iso_week": req.iso_week,
            "week_start": week_start,
            "week_end": week_end,
            "run_id": run_id,
            "correlation_id": correlation_id,
            "api_request_id": api_request_id,
            "lambda_request_id": lambda_request_id,
            "collected_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "item_count": item_count,
            "api_pages_fetched": api_pages_fetched,
            "duration_ms": duration_ms,
        }

        storage = S3Storage(
            s3_client=create_default_s3_client(),
            bucket_name=os.environ["RAW_BUCKET_NAME"],
            raw_prefix=os.getenv("RAW_PREFIX", "raw/bp/releases"),
        )
        releases_key, _, _ = storage.write_run_artifacts(releases=releases, meta=meta)

        response = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "api_request_id": api_request_id,
            "lambda_request_id": lambda_request_id,
            "iso_year": req.iso_year,
            "iso_week": req.iso_week,
            "s3_object_key": releases_key,
            "item_count": item_count,
            "duration_ms": duration_ms,
        }

        log_event(
            "INFO",
            "collection_completed",
            correlation_id=correlation_id,
            api_request_id=api_request_id,
            lambda_request_id=lambda_request_id,
            run_id=run_id,
            style_id=req.style_id,
            iso_year=req.iso_year,
            iso_week=req.iso_week,
            item_count=item_count,
            api_pages_fetched=api_pages_fetched,
            duration_ms=duration_ms,
            status_code=200,
        )
        return _json_response(200, response, correlation_id)

    except AppError as exc:
        log_event(
            "ERROR",
            "collection_failed",
            correlation_id=correlation_id,
            api_request_id=api_request_id,
            lambda_request_id=lambda_request_id,
            error_code=exc.error_code,
            status_code=exc.status_code,
            error_type=exc.__class__.__name__,
        )
        return _json_response(
            exc.status_code,
            {
                "error_code": exc.error_code,
                "message": exc.message,
                "correlation_id": correlation_id,
                "api_request_id": api_request_id,
                "lambda_request_id": lambda_request_id,
            },
            correlation_id,
        )
    except Exception as exc:  # pragma: no cover - safety net path
        log_event(
            "ERROR",
            "collection_failed_unexpected",
            correlation_id=correlation_id,
            api_request_id=api_request_id,
            lambda_request_id=lambda_request_id,
            error_type=exc.__class__.__name__,
            status_code=500,
            error_code="internal_error",
        )
        return _json_response(
            500,
            {
                "error_code": "internal_error",
                "message": "Internal server error",
                "correlation_id": correlation_id,
                "api_request_id": api_request_id,
                "lambda_request_id": lambda_request_id,
            },
            correlation_id,
        )


def _parse_json_body(event: Mapping[str, Any]) -> Dict[str, Any]:
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
            if isinstance(key, str) and key.lower() == "x-correlation-id" and isinstance(value, str) and value.strip():
                return value.strip()
    return str(uuid.uuid4())


def _json_response(status_code: int, payload: Mapping[str, Any], correlation_id: str) -> Dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "x-correlation-id": correlation_id,
        },
        "body": json.dumps(payload, ensure_ascii=False),
    }

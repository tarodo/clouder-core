"""AWS Lambda handler for Beatport weekly releases collection API."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import time
import uuid
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .beatport_client import BeatportClient
from .errors import AppError, ValidationError
from .logging_utils import log_event
from .models import (
    ProcessingOutcome,
    ProcessingReason,
    ProcessingStatus,
    RunStatus,
    compute_iso_week_date_range,
)
from .repositories import (
    CreateIngestRunCmd,
    create_clouder_repository_from_env,
    utc_now,
)
from .schemas import CollectRequestIn, validation_error_message
from .settings import ApiSettings, get_api_settings
from .storage import S3Storage, create_default_s3_client


@dataclass(frozen=True)
class EnqueueResult:
    processing_status: ProcessingStatus
    processing_outcome: ProcessingOutcome
    processing_reason: ProcessingReason | None = None


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key == "GET /runs/{run_id}":
        return _handle_get_run(event, context)
    if route_key in ("POST /collect_bp_releases", ""):
        return _handle_collect(event, context)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found"},
        _extract_correlation_id(event),
    )


def _handle_collect(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    started_at_perf = time.perf_counter()
    api_request_id = _extract_api_request_id(event)
    lambda_request_id = getattr(context, "aws_request_id", "unknown")
    correlation_id = _extract_correlation_id(event)

    log_event(
        "INFO",
        "request_received",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
    )

    try:
        settings = _load_api_settings()
        body = _parse_json_body(event)
        request = _parse_collect_request(body)
        week_start, week_end = compute_iso_week_date_range(
            request.iso_year, request.iso_week
        )
        run_id = str(uuid.uuid4())

        log_event(
            "INFO",
            "request_validated",
            correlation_id=correlation_id,
            api_request_id=api_request_id,
            lambda_request_id=lambda_request_id,
            style_id=request.style_id,
            iso_year=request.iso_year,
            iso_week=request.iso_week,
        )

        beatport_client = BeatportClient(base_url=settings.beatport_api_base_url)
        releases, api_pages_fetched = beatport_client.fetch_weekly_releases(
            bp_token=request.bp_token,
            style_id=request.style_id,
            week_start=week_start,
            week_end=week_end,
            correlation_id=correlation_id,
        )

        duration_ms = int((time.perf_counter() - started_at_perf) * 1000)
        item_count = len(releases)
        meta = {
            "style_id": request.style_id,
            "iso_year": request.iso_year,
            "iso_week": request.iso_week,
            "week_start": week_start,
            "week_end": week_end,
            "run_id": run_id,
            "correlation_id": correlation_id,
            "api_request_id": api_request_id,
            "lambda_request_id": lambda_request_id,
            "collected_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "item_count": item_count,
            "api_pages_fetched": api_pages_fetched,
            "duration_ms": duration_ms,
        }

        storage = S3Storage(
            s3_client=create_default_s3_client(),
            bucket_name=settings.raw_bucket_name,
            raw_prefix=settings.raw_prefix,
        )
        releases_key, _ = storage.write_run_artifacts(releases=releases, meta=meta)

        repository = create_clouder_repository_from_env()
        if repository is not None:
            repository.create_ingest_run(
                CreateIngestRunCmd(
                    run_id=run_id,
                    source="beatport",
                    style_id=request.style_id,
                    iso_year=request.iso_year,
                    iso_week=request.iso_week,
                    raw_s3_key=releases_key,
                    status=RunStatus.RAW_SAVED,
                    item_count=item_count,
                    meta=meta,
                    started_at=utc_now(),
                )
            )

        enqueue_result = _enqueue_canonicalization(
            run_id=run_id,
            s3_key=releases_key,
            style_id=request.style_id,
            iso_year=request.iso_year,
            iso_week=request.iso_week,
            correlation_id=correlation_id,
            settings=settings,
        )

        response = {
            "run_id": run_id,
            "correlation_id": correlation_id,
            "api_request_id": api_request_id,
            "lambda_request_id": lambda_request_id,
            "iso_year": request.iso_year,
            "iso_week": request.iso_week,
            "s3_object_key": releases_key,
            "item_count": item_count,
            "duration_ms": duration_ms,
            "run_status": RunStatus.RAW_SAVED.value,
            "processing_status": enqueue_result.processing_status.value,
            "processing_outcome": enqueue_result.processing_outcome.value,
            "processing_reason": (
                enqueue_result.processing_reason.value
                if enqueue_result.processing_reason
                else None
            ),
        }

        log_event(
            "INFO",
            "collection_completed",
            correlation_id=correlation_id,
            api_request_id=api_request_id,
            lambda_request_id=lambda_request_id,
            run_id=run_id,
            style_id=request.style_id,
            iso_year=request.iso_year,
            iso_week=request.iso_week,
            item_count=item_count,
            api_pages_fetched=api_pages_fetched,
            duration_ms=duration_ms,
            status_code=200,
            processing_status=enqueue_result.processing_status.value,
            processing_outcome=enqueue_result.processing_outcome.value,
            processing_reason=(
                enqueue_result.processing_reason.value
                if enqueue_result.processing_reason
                else None
            ),
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
            error_message=exc.message,
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
            error_message=str(exc)[:500],
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


def _handle_get_run(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    correlation_id = _extract_correlation_id(event)
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

    repository = create_clouder_repository_from_env()
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
        error = {
            "code": row.get("error_code"),
            "message": row.get("error_message"),
        }

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


def _enqueue_canonicalization(
    run_id: str,
    s3_key: str,
    style_id: int,
    iso_year: int,
    iso_week: int,
    correlation_id: str,
    settings: ApiSettings,
) -> EnqueueResult:
    queue_url = settings.canonicalization_queue_url.strip()

    if not settings.canonicalization_enabled:
        result = EnqueueResult(
            processing_status=ProcessingStatus.FAILED_TO_QUEUE,
            processing_outcome=ProcessingOutcome.DISABLED,
            processing_reason=ProcessingReason.CONFIG_DISABLED,
        )
        log_event(
            "INFO",
            "canonicalization_enqueue_skipped",
            run_id=run_id,
            processing_status=result.processing_status.value,
            processing_outcome=result.processing_outcome.value,
            processing_reason=result.processing_reason.value,
        )
        return result

    if not queue_url:
        result = EnqueueResult(
            processing_status=ProcessingStatus.FAILED_TO_QUEUE,
            processing_outcome=ProcessingOutcome.DISABLED,
            processing_reason=ProcessingReason.QUEUE_MISSING,
        )
        log_event(
            "INFO",
            "canonicalization_enqueue_skipped",
            run_id=run_id,
            processing_status=result.processing_status.value,
            processing_outcome=result.processing_outcome.value,
            processing_reason=result.processing_reason.value,
        )
        return result

    payload = {
        "run_id": run_id,
        "source": "beatport",
        "s3_key": s3_key,
        "style_id": style_id,
        "iso_year": iso_year,
        "iso_week": iso_week,
        "attempt": 1,
    }

    try:
        client = create_default_sqs_client()
        client.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            MessageAttributes={
                "correlation_id": {
                    "DataType": "String",
                    "StringValue": correlation_id,
                }
            },
        )
        result = EnqueueResult(
            processing_status=ProcessingStatus.QUEUED,
            processing_outcome=ProcessingOutcome.ENQUEUED,
        )
        log_event(
            "INFO",
            "canonicalization_enqueued",
            correlation_id=correlation_id,
            run_id=run_id,
            processing_status=result.processing_status.value,
            processing_outcome=result.processing_outcome.value,
            status_code=200,
        )
        return result
    except Exception as exc:  # pragma: no cover - networked path
        result = EnqueueResult(
            processing_status=ProcessingStatus.FAILED_TO_QUEUE,
            processing_outcome=ProcessingOutcome.ENQUEUE_FAILED,
            processing_reason=ProcessingReason.ENQUEUE_EXCEPTION,
        )
        log_event(
            "ERROR",
            "canonicalization_enqueue_failed",
            correlation_id=correlation_id,
            run_id=run_id,
            error_type=exc.__class__.__name__,
            error_message=str(exc)[:500],
            processing_status=result.processing_status.value,
            processing_outcome=result.processing_outcome.value,
            processing_reason=result.processing_reason.value,
        )
        return result


def create_default_sqs_client() -> Any:
    import boto3

    return boto3.client("sqs")


def _parse_collect_request(payload: Mapping[str, Any]) -> CollectRequestIn:
    try:
        return CollectRequestIn.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc)) from exc


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

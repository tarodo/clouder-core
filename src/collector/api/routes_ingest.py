"""Beatport ingest: collect and admin-ingest endpoints, the run they share, and the
auto-ingest admin routes.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from ..beatport_auth import BeatportAuthError
from ..errors import AppError, ValidationError
from ..logging_utils import log_event
from ..models import (
    ProcessingOutcome,
    ProcessingReason,
    ProcessingStatus,
    RunStatus,
    compute_iso_week_date_range,
)
from ..repositories import CreateIngestRunCmd
from ..schemas import AdminIngestRequestIn, CollectRequestIn, validation_error_message
from ..settings import ApiSettings
from . import deps
from .http import (
    _extract_api_request_id,
    _json_response,
    _load_api_settings,
    _parse_json_body,
)


@dataclass(frozen=True)
class EnqueueResult:
    processing_status: ProcessingStatus
    processing_outcome: ProcessingOutcome
    processing_reason: ProcessingReason | None = None


@dataclass(frozen=True)
class _IngestParams:
    """Inputs for `_run_beatport_ingest`.

    Three valid field combinations:
    - Legacy ISO path: iso_year + iso_week set; week_year/week_number None;
      is_custom_range False.
    - Admin Saturday-week path: week_year + week_number set; iso_year/iso_week None;
      is_custom_range False; period_start/period_end derived from saturday_week_range.
    - Admin custom-range path: same as Saturday-week plus is_custom_range True;
      period_start/period_end taken from the request body verbatim.
    """

    style_id: int
    bp_token: str
    period_start: str  # YYYY-MM-DD
    period_end: str    # YYYY-MM-DD
    iso_year: int | None
    iso_week: int | None
    week_year: int | None
    week_number: int | None
    is_custom_range: bool


IngestParams = _IngestParams


def _run_beatport_ingest(
    event: Mapping[str, Any],
    context: Any,
    params: _IngestParams,
    correlation_id: str,
) -> dict[str, Any]:
    response = collect_period(
        params,
        correlation_id,
        api_request_id=_extract_api_request_id(event),
        lambda_request_id=getattr(context, "aws_request_id", "unknown"),
        trigger="manual",
    )
    return _json_response(200, response, correlation_id)


def collect_period(
    params: _IngestParams,
    correlation_id: str,
    *,
    api_request_id: str,
    lambda_request_id: str,
    trigger: str = "manual",
) -> dict[str, Any]:
    """Fetch one style x period from Beatport, store it raw, record the run and
    enqueue canonicalization — the admin endpoint and auto-ingest share it.
    `params.bp_token` is used for the fetch only."""
    started_at_perf = time.perf_counter()

    log_event(
        "INFO",
        "request_received",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
    )

    settings = _load_api_settings()
    run_id = str(uuid.uuid4())

    log_event(
        "INFO",
        "request_validated",
        correlation_id=correlation_id,
        api_request_id=api_request_id,
        lambda_request_id=lambda_request_id,
        style_id=params.style_id,
        iso_year=params.iso_year,
        iso_week=params.iso_week,
        week_year=params.week_year,
        week_number=params.week_number,
        is_custom_range=params.is_custom_range,
    )

    beatport_client = deps.registry.get_ingest("beatport")
    releases, api_pages_fetched = beatport_client.fetch_weekly_releases(
        bp_token=params.bp_token,
        style_id=params.style_id,
        week_start=params.period_start,
        week_end=params.period_end,
        correlation_id=correlation_id,
    )

    duration_ms = int((time.perf_counter() - started_at_perf) * 1000)
    item_count = len(releases)
    meta = {
        "style_id": params.style_id,
        "iso_year": params.iso_year,
        "iso_week": params.iso_week,
        "week_year": params.week_year,
        "week_number": params.week_number,
        "period_start": params.period_start,
        "period_end": params.period_end,
        "is_custom_range": params.is_custom_range,
        "run_id": run_id,
        "correlation_id": correlation_id,
        "api_request_id": api_request_id,
        "lambda_request_id": lambda_request_id,
        "collected_at_utc": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "item_count": item_count,
        "api_pages_fetched": api_pages_fetched,
        "duration_ms": duration_ms,
        "trigger": trigger,
    }

    storage = deps.S3Storage(
        s3_client=deps.create_default_s3_client(),
        bucket_name=settings.raw_bucket_name,
        raw_prefix=settings.raw_prefix,
    )
    releases_key, _ = storage.write_run_artifacts(releases=releases, meta=meta)

    repository = deps.create_clouder_repository_from_env()
    if repository is not None:
        repository.create_ingest_run(
            CreateIngestRunCmd(
                run_id=run_id,
                source="beatport",
                style_id=params.style_id,
                iso_year=params.iso_year,
                iso_week=params.iso_week,
                week_year=params.week_year,
                week_number=params.week_number,
                period_start=date.fromisoformat(params.period_start),
                period_end=date.fromisoformat(params.period_end),
                is_custom_range=params.is_custom_range,
                raw_s3_key=releases_key,
                status=RunStatus.RAW_SAVED,
                item_count=item_count,
                meta=meta,
                started_at=deps.utc_now(),
            )
        )

    enqueue_result = _enqueue_canonicalization(
        run_id=run_id,
        s3_key=releases_key,
        style_id=params.style_id,
        iso_year=params.iso_year,
        iso_week=params.iso_week,
        correlation_id=correlation_id,
        settings=settings,
    )

    response = {
        "run_id": run_id,
        "correlation_id": correlation_id,
        "api_request_id": api_request_id,
        "lambda_request_id": lambda_request_id,
        "iso_year": params.iso_year,
        "iso_week": params.iso_week,
        "week_year": params.week_year,
        "week_number": params.week_number,
        "period_start": params.period_start,
        "period_end": params.period_end,
        "is_custom_range": params.is_custom_range,
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
        style_id=params.style_id,
        iso_year=params.iso_year,
        iso_week=params.iso_week,
        week_year=params.week_year,
        week_number=params.week_number,
        is_custom_range=params.is_custom_range,
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
    return response


def _handle_collect(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    body = _parse_json_body(event)
    request = _parse_collect_request(body)
    week_start, week_end = compute_iso_week_date_range(
        request.iso_year, request.iso_week
    )
    params = _IngestParams(
        style_id=request.style_id,
        bp_token=request.bp_token,
        period_start=week_start,
        period_end=week_end,
        iso_year=request.iso_year,
        iso_week=request.iso_week,
        week_year=None,
        week_number=None,
        is_custom_range=False,
    )
    return _run_beatport_ingest(event, context, params, correlation_id)


def _handle_admin_ingest(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    body = _parse_json_body(event)
    try:
        request = AdminIngestRequestIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc))

    from ..saturday_week import saturday_week_range

    if request.period_start is None:
        std_start, std_end = saturday_week_range(
            request.week_year, request.week_number
        )
        period_start_iso = std_start.isoformat()
        period_end_iso = std_end.isoformat()
        is_custom = False
    else:
        if request.period_start is None or request.period_end is None:
            raise ValidationError("period_start and period_end are required for a custom range")
        period_start_iso = request.period_start.isoformat()
        period_end_iso = request.period_end.isoformat()
        is_custom = True

    params = _IngestParams(
        style_id=request.style_id,
        bp_token=_beatport_token(correlation_id),
        period_start=period_start_iso,
        period_end=period_end_iso,
        iso_year=None,
        iso_week=None,
        week_year=request.week_year,
        week_number=request.week_number,
        is_custom_range=is_custom,
    )
    return _run_beatport_ingest(event, context, params, correlation_id)


def _beatport_token(correlation_id: str) -> str:
    """Log in with the SSM credentials auto-ingest uses. The token lives only in
    this invocation's memory: it is never returned, logged or stored."""
    try:
        username, password = deps.read_beatport_credentials()
    except Exception as exc:  # missing env/parameter, IAM, KMS: name the cause, never a value
        log_event("ERROR", "beatport_login_failed", correlation_id=correlation_id,
                  phase="credentials", error_type=type(exc).__name__)
        raise AppError(status_code=503, error_code="beatport_credentials_unavailable",
                       message="Beatport credentials are not configured") from exc
    try:
        return deps.fetch_access_token(username, password)
    except BeatportAuthError as exc:
        log_event("ERROR", "beatport_login_failed", correlation_id=correlation_id,
                  phase=exc.step, status_code=exc.status)
        raise AppError(status_code=502, error_code="beatport_login_failed",
                       message=f"Beatport login failed at step {exc.step}") from exc


def _parse_collect_request(payload: Mapping[str, Any]) -> CollectRequestIn:
    try:
        return CollectRequestIn.model_validate(payload)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc)) from exc


def _enqueue_canonicalization(
    run_id: str,
    s3_key: str,
    style_id: int,
    iso_year: int | None,
    iso_week: int | None,
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
            processing_reason=result.processing_reason.value if result.processing_reason else None,
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
            processing_reason=result.processing_reason.value if result.processing_reason else None,
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
        client = deps.create_default_sqs_client()
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
            processing_reason=result.processing_reason.value if result.processing_reason else None,
        )
        return result


def _auto_ingest_view(repo: Any) -> dict[str, Any]:
    from ..auto_ingest_plan import due_week

    settings = repo.get_settings()
    week_year, week_number = due_week(deps.utc_now().date())
    return {
        "settings": {k: settings[k] for k in (
            "enabled", "mode", "fixed_times", "runs_per_day", "timezone",
            "periods_per_run", "backfill_floor", "updated_at")},
        "planned_runs": settings["planned_runs"],
        "last_run": settings["last_run"],
        "running": settings["running"],
        "due_week": {"week_year": week_year, "week_number": week_number},
        "stuck": repo.stuck_pairs(deps.utc_now()),
    }


def _handle_auto_ingest_get(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    return _json_response(200, _auto_ingest_view(deps._auto_ingest_repository()), correlation_id)


def _handle_auto_ingest_put(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    from ..schemas import AutoIngestSettingsIn

    try:
        request = AutoIngestSettingsIn.model_validate(_parse_json_body(event))
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc))
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    user_id = (authorizer.get("lambda") or {}).get("user_id")
    repo = deps._auto_ingest_repository()
    repo.save_settings(request.model_dump(), user_id=user_id, now=deps.utc_now())
    deps._invoke_auto_ingest({"action": "plan"})
    return _json_response(200, _auto_ingest_view(repo), correlation_id)


def _handle_auto_ingest_run(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    deps._invoke_auto_ingest({"action": "run", "manual": True})
    return _json_response(202, {"accepted": True}, correlation_id)

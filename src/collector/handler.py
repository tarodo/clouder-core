"""AWS Lambda handler for Beatport weekly releases collection API."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import re
import time
import uuid
from typing import Any, Mapping

_PHASE_PREFIX = re.compile(r"^\[phase=([^\]]+)\] ")


def _split_phase_prefix(msg: str | None) -> tuple[str | None, str | None]:
    if not msg:
        return None, msg
    m = _PHASE_PREFIX.match(msg)
    if not m:
        return None, msg
    return m.group(1), msg[m.end():]

from pydantic import ValidationError as PydanticValidationError

from .providers import registry
from .errors import AdminRequiredError, AppError, ValidationError
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
from .schemas import AdminIngestRequestIn, CollectRequestIn, validation_error_message
from .settings import ApiSettings, get_api_settings
from .storage import S3Storage, create_default_s3_client


@dataclass(frozen=True)
class EnqueueResult:
    processing_status: ProcessingStatus
    processing_outcome: ProcessingOutcome
    processing_reason: ProcessingReason | None = None


_LIST_ROUTES = {
    "GET /tracks": ("tracks", "list_tracks", "count_tracks"),
    "GET /artists": ("artists", "list_artists", "count_artists"),
    "GET /albums": ("albums", "list_albums", "count_albums"),
    "GET /styles": ("styles", "list_styles", "count_styles"),
}

_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",          # legacy, kept for backward compatibility
    "POST /admin/beatport/ingest",
    "GET /admin/coverage",
    "GET /admin/runs",
    "GET /tracks/spotify-not-found",
    "POST /admin/labels/enrich",
    "GET /admin/labels/enrich-runs/{run_id}",
    "GET /admin/labels/{label_id}",
})


def _require_admin(event: Mapping[str, Any]) -> None:
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping) and bool(ctx.get("is_admin")):
                return
    raise AdminRequiredError()


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
    api_request_id = _extract_api_request_id(event)
    lambda_request_id = getattr(context, "aws_request_id", "unknown")
    try:
        return _route(event, context, correlation_id)
    except AppError as exc:
        log_event(
            "ERROR",
            "request_failed",
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
    except Exception as exc:  # pragma: no cover - safety net
        log_event(
            "ERROR",
            "request_failed_unexpected",
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


def _route(
    event: Mapping[str, Any], context: Any, correlation_id: str
) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key in _ADMIN_ROUTES:
        _require_admin(event)
    if route_key == "GET /runs/{run_id}":
        return _handle_get_run(event, context)
    if route_key in ("POST /collect_bp_releases", ""):
        return _handle_collect(event, context)
    if route_key == "POST /admin/beatport/ingest":
        return _handle_admin_ingest(event, context)
    if route_key == "GET /admin/coverage":
        return _handle_admin_coverage(event)
    if route_key == "GET /admin/runs":
        return _handle_admin_runs(event)
    if route_key == "GET /tracks/spotify-not-found":
        return _handle_spotify_not_found(event)
    if route_key == "POST /admin/labels/enrich":
        from .label_enrichment.routes import handle_post_enrich
        status, body = handle_post_enrich(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/enrich-runs/{run_id}":
        from .label_enrichment.routes import handle_get_run
        status, body = handle_get_run(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/{label_id}":
        from .label_enrichment.routes import handle_get_label
        status, body = handle_get_label(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /labels":
        from .label_enrichment.routes import handle_get_labels_list
        status, body = handle_get_labels_list(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /labels/{label_id}":
        from .label_enrichment.routes import handle_get_label_user
        status, body = handle_get_label_user(event)
        return _json_response(status, body, correlation_id)
    if route_key in _LIST_ROUTES:
        return _handle_list(event, route_key)
    return _json_response(
        404,
        {"error_code": "not_found", "message": "Route not found"},
        correlation_id,
    )


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


def _run_beatport_ingest(
    event: Mapping[str, Any],
    context: Any,
    params: _IngestParams,
) -> dict[str, Any]:
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

    beatport_client = registry.get_ingest("beatport")
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
                started_at=utc_now(),
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
    return _json_response(200, response, correlation_id)


def _handle_collect(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
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
    return _run_beatport_ingest(event, context, params)


def _handle_admin_ingest(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    body = _parse_json_body(event)
    try:
        request = AdminIngestRequestIn.model_validate(body)
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc))

    from .saturday_week import saturday_week_range

    if request.period_start is None:
        std_start, std_end = saturday_week_range(
            request.week_year, request.week_number
        )
        period_start_iso = std_start.isoformat()
        period_end_iso = std_end.isoformat()
        is_custom = False
    else:
        period_start_iso = request.period_start.isoformat()
        period_end_iso = request.period_end.isoformat()
        is_custom = True

    params = _IngestParams(
        style_id=request.style_id,
        bp_token=request.bp_token,
        period_start=period_start_iso,
        period_end=period_end_iso,
        iso_year=None,
        iso_week=None,
        week_year=request.week_year,
        week_number=request.week_number,
        is_custom_range=is_custom,
    )
    return _run_beatport_ingest(event, context, params)


def _handle_admin_coverage(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("week_year") if isinstance(qs, Mapping) else None
    if not raw or not raw.isdigit():
        raise ValidationError("week_year is required (4-digit year)")
    week_year = int(raw)
    if week_year < 2000 or week_year > 2100:
        raise ValidationError("week_year out of range")

    from .saturday_week import weeks_in_year

    repository = create_clouder_repository_from_env()
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
                "style_name": row["style_name"],
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


def _handle_admin_runs(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
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

    repository = create_clouder_repository_from_env()
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


def _handle_list(event: Mapping[str, Any], route_key: str) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)
    entity, list_method, count_method = _LIST_ROUTES[route_key]

    repository = create_clouder_repository_from_env()
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


def _handle_spotify_not_found(event: Mapping[str, Any]) -> dict[str, Any]:
    correlation_id = _extract_correlation_id(event)

    repository = create_clouder_repository_from_env()
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

    rows = repository.find_tracks_not_found_on_spotify(limit, offset, search)
    total = repository.count_tracks_not_found_on_spotify(search)

    items = []
    for row in rows:
        item: dict[str, Any] = {}
        for key, value in row.items():
            item[key] = value
        if "id" in item:
            item["track_id"] = item.pop("id")
        if "artist_names" in item:
            raw = item.pop("artist_names")
            item["artists"] = [n.strip() for n in raw.split(",")] if raw else []
        items.append(item)

    log_event(
        "INFO",
        "spotify_not_found_list_completed",
        correlation_id=correlation_id,
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

"""AWS Lambda handler for Beatport weekly releases collection API."""

from __future__ import annotations

import base64
import json
import os
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError as PydanticValidationError

from .beatport_auth import BeatportAuthError, fetch_access_token
from .beatport_auth import read_credentials as read_beatport_credentials
from .errors import AdminRequiredError, AppError, ValidationError
from .logging_utils import log_event
from .models import (
    ProcessingOutcome,
    ProcessingReason,
    ProcessingStatus,
    RunStatus,
    compute_iso_week_date_range,
)
from .providers import registry
from .repositories import (
    CreateIngestRunCmd,
    create_clouder_repository_from_env,
    utc_now,
)
from .schemas import AdminIngestRequestIn, CollectRequestIn, validation_error_message
from .settings import ApiSettings, get_api_settings
from .storage import S3Storage, create_default_s3_client

_PHASE_PREFIX = re.compile(r"^\[phase=([^\]]+)\] ")


def _split_phase_prefix(msg: str | None) -> tuple[str | None, str | None]:
    if not msg:
        return None, msg
    m = _PHASE_PREFIX.match(msg)
    if not m:
        return None, msg
    return m.group(1), msg[m.end():]


@dataclass(frozen=True)
class EnqueueResult:
    processing_status: ProcessingStatus
    processing_outcome: ProcessingOutcome
    processing_reason: ProcessingReason | None = None


_LIST_ROUTES = {
    "GET /tracks": ("tracks", "list_tracks", "count_tracks"),
    "GET /albums": ("albums", "list_albums", "count_albums"),
}

_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",          # legacy, kept for backward compatibility
    "POST /admin/beatport/ingest",
    "GET /admin/coverage",
    "PATCH /admin/styles/{style_id}",
    "GET /admin/runs",
    "GET /tracks/spotify-not-found",
    "POST /admin/spotify/retry-not-found",
    "GET /admin/spotify/search-status",
    "POST /admin/labels/enrich",
    "POST /admin/labels/{label_id}/enrich-auto",
    "GET /admin/labels/enrich/options",
    "GET /admin/labels/enrich-runs",
    "GET /admin/labels/enrich-runs/{run_id}",
    "GET /admin/labels/backlog",
    "GET /admin/labels/{label_id}",
    "GET /admin/labels/{label_id}/history",
    "GET /admin/auto-enrich/labels",
    "PUT /admin/auto-enrich/labels",
    "POST /admin/artists/enrich",
    "POST /admin/artists/{artist_id}/enrich-auto",
    "GET /admin/artists/enrich/options",
    "GET /admin/artists/enrich-runs",
    "GET /admin/artists/enrich-runs/{run_id}",
    "GET /admin/artists/backlog",
    "GET /admin/artists/{artist_id}",
    "GET /admin/artists/{artist_id}/history",
    "GET /admin/auto-enrich/artists",
    "PUT /admin/auto-enrich/artists",
    "GET /admin/users",
    "GET /admin/auto-ingest",
    "PUT /admin/auto-ingest",
    "POST /admin/auto-ingest/run",
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
        return _handle_get_run(event, context, correlation_id)
    if route_key in ("POST /collect_bp_releases", ""):
        return _handle_collect(event, context, correlation_id)
    if route_key == "POST /admin/beatport/ingest":
        return _handle_admin_ingest(event, context, correlation_id)
    if route_key == "GET /admin/coverage":
        return _handle_admin_coverage(event, correlation_id)
    if route_key == "PATCH /admin/styles/{style_id}":
        return _handle_admin_style_visibility(event, correlation_id)
    if route_key == "GET /admin/users":
        return _handle_admin_users(event, correlation_id)
    if route_key == "GET /admin/auto-ingest":
        return _handle_auto_ingest_get(correlation_id)
    if route_key == "PUT /admin/auto-ingest":
        return _handle_auto_ingest_put(event, correlation_id)
    if route_key == "POST /admin/auto-ingest/run":
        _invoke_auto_ingest({"action": "run", "manual": True})
        return _json_response(202, {"accepted": True}, correlation_id)
    if route_key == "GET /v1/analytics/funnel":
        return _handle_analytics_funnel(event, correlation_id)
    if route_key == "GET /admin/runs":
        return _handle_admin_runs(event, correlation_id)
    if route_key == "GET /tracks/spotify-not-found":
        return _handle_spotify_not_found(event, correlation_id)
    if route_key == "POST /admin/spotify/retry-not-found":
        return _handle_spotify_retry_not_found(event, correlation_id)
    if route_key == "GET /admin/spotify/search-status":
        return _handle_spotify_search_status(correlation_id)
    if route_key == "POST /admin/labels/enrich":
        from .label_enrichment.routes import handle_post_enrich
        status, body = handle_post_enrich(event)
        return _json_response(status, body, correlation_id)
    if route_key == "POST /admin/labels/{label_id}/enrich-auto":
        from .label_enrichment.routes import handle_post_enrich_auto
        status, body = handle_post_enrich_auto(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/enrich/options":
        from .label_enrichment.routes import handle_get_options
        status, body = handle_get_options(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/enrich-runs":
        from .label_enrichment.routes import handle_get_runs_list
        status, body = handle_get_runs_list(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/enrich-runs/{run_id}":
        from .label_enrichment.routes import handle_get_run
        status, body = handle_get_run(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/backlog":
        from .label_enrichment.routes import handle_get_backlog
        status, body = handle_get_backlog(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/{label_id}/history":
        from .label_enrichment.routes import handle_get_label_history
        status, body = handle_get_label_history(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/labels/{label_id}":
        from .label_enrichment.routes import handle_get_label
        status, body = handle_get_label(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/auto-enrich/labels":
        from .label_enrichment.auto_routes import handle_get_auto_config
        status, body = handle_get_auto_config(event)
        return _json_response(status, body, correlation_id)
    if route_key == "PUT /admin/auto-enrich/labels":
        from .label_enrichment.auto_routes import handle_put_auto_config
        status, body = handle_put_auto_config(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
    if route_key == "PUT /labels/{label_id}/preference":
        from .label_enrichment.routes import handle_put_label_preference
        status, body = handle_put_label_preference(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
    if route_key == "GET /me/label-preferences":
        from .label_enrichment.routes import handle_get_my_label_preferences
        status, body = handle_get_my_label_preferences(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /labels":
        from .label_enrichment.routes import handle_get_labels_list
        status, body = handle_get_labels_list(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /labels/{label_id}":
        from .label_enrichment.routes import handle_get_label_user
        status, body = handle_get_label_user(event)
        return _json_response(status, body, correlation_id)
    if route_key == "POST /admin/artists/enrich":
        from .artist_enrichment.routes import handle_post_enrich
        status, body = handle_post_enrich(event)
        return _json_response(status, body, correlation_id)
    if route_key == "POST /admin/artists/{artist_id}/enrich-auto":
        from .artist_enrichment.routes import handle_post_enrich_auto
        status, body = handle_post_enrich_auto(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/enrich/options":
        from .artist_enrichment.routes import handle_get_options
        status, body = handle_get_options(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/enrich-runs":
        from .artist_enrichment.routes import handle_get_runs_list
        status, body = handle_get_runs_list(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/enrich-runs/{run_id}":
        from .artist_enrichment.routes import handle_get_run
        status, body = handle_get_run(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/backlog":
        from .artist_enrichment.routes import handle_get_backlog
        status, body = handle_get_backlog(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/{artist_id}/history":
        from .artist_enrichment.routes import handle_get_artist_history
        status, body = handle_get_artist_history(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/artists/{artist_id}":
        from .artist_enrichment.routes import handle_get_artist
        status, body = handle_get_artist(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /admin/auto-enrich/artists":
        from .artist_enrichment.auto_routes import handle_get_auto_config
        status, body = handle_get_auto_config(event)
        return _json_response(status, body, correlation_id)
    if route_key == "PUT /admin/auto-enrich/artists":
        from .artist_enrichment.auto_routes import handle_put_auto_config
        status, body = handle_put_auto_config(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
    if route_key == "PUT /artists/{artist_id}/preference":
        from .artist_enrichment.routes import handle_put_artist_preference
        status, body = handle_put_artist_preference(event)
        if status == 204:
            return {
                "statusCode": 204,
                "headers": {"x-correlation-id": correlation_id},
                "body": "",
            }
        return _json_response(status, body, correlation_id)
    if route_key == "GET /me/artist-preferences":
        from .artist_enrichment.routes import handle_get_my_artist_preferences
        status, body = handle_get_my_artist_preferences(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /artists":
        from .artist_enrichment.routes import handle_get_artists_list
        status, body = handle_get_artists_list(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /artists/{artist_id}":
        from .artist_enrichment.routes import handle_get_artist_user
        status, body = handle_get_artist_user(event)
        return _json_response(status, body, correlation_id)
    if route_key == "GET /styles":
        from .user_styles.routes import handle_get_styles
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
    if route_key == "PUT /me/styles":
        from .user_styles.routes import extract_user_id, handle_put_my_styles
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
    if route_key in _LIST_ROUTES:
        return _handle_list(event, route_key, correlation_id)
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


# Public name for callers outside the API handler (auto-ingest).
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
        "collected_at_utc": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "item_count": item_count,
        "api_pages_fetched": api_pages_fetched,
        "duration_ms": duration_ms,
        "trigger": trigger,
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

    from .saturday_week import saturday_week_range

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
        username, password = read_beatport_credentials()
    except Exception as exc:  # missing env/parameter, IAM, KMS: name the cause, never a value
        log_event("ERROR", "beatport_login_failed", correlation_id=correlation_id,
                  phase="credentials", error_type=type(exc).__name__)
        raise AppError(status_code=503, error_code="beatport_credentials_unavailable",
                       message="Beatport credentials are not configured") from exc
    try:
        return fetch_access_token(username, password)
    except BeatportAuthError as exc:
        log_event("ERROR", "beatport_login_failed", correlation_id=correlation_id,
                  phase=exc.step, status_code=exc.status)
        raise AppError(status_code=502, error_code="beatport_login_failed",
                       message=f"Beatport login failed at step {exc.step}") from exc


def _auto_ingest_repository() -> Any:
    from .auto_ingest_repository import AutoIngestRepository
    from .data_api import create_default_data_api_client
    from .settings import get_data_api_settings

    settings = get_data_api_settings()
    if not settings.is_configured:
        raise AppError(status_code=503, error_code="db_not_configured",
                       message="Database is not configured")
    return AutoIngestRepository(create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    ))


def _invoke_auto_ingest(payload: Mapping[str, Any]) -> None:
    """Asynchronous: replan after a save, or a manual run."""
    import boto3

    name = os.environ.get("AUTO_INGEST_FUNCTION_NAME", "").strip()
    if not name:
        raise AppError(status_code=503, error_code="config_error",
                       message="AUTO_INGEST_FUNCTION_NAME is not set")
    boto3.client("lambda").invoke(
        FunctionName=name, InvocationType="Event", Payload=json.dumps(dict(payload)).encode()
    )


def _auto_ingest_view(repo: Any) -> dict[str, Any]:
    from .auto_ingest_plan import due_week

    settings = repo.get_settings()
    week_year, week_number = due_week(utc_now().date())
    return {
        "settings": {k: settings[k] for k in (
            "enabled", "mode", "fixed_times", "runs_per_day", "timezone",
            "periods_per_run", "backfill_floor", "updated_at")},
        "planned_runs": settings["planned_runs"],
        "last_run": settings["last_run"],
        "running": settings["running"],
        "due_week": {"week_year": week_year, "week_number": week_number},
        "stuck": repo.stuck_pairs(utc_now()),
    }


def _handle_auto_ingest_get(correlation_id: str) -> dict[str, Any]:
    return _json_response(200, _auto_ingest_view(_auto_ingest_repository()), correlation_id)


def _handle_auto_ingest_put(event: Mapping[str, Any], correlation_id: str) -> dict[str, Any]:
    from .schemas import AutoIngestSettingsIn

    try:
        request = AutoIngestSettingsIn.model_validate(_parse_json_body(event))
    except PydanticValidationError as exc:
        raise ValidationError(validation_error_message(exc))
    authorizer = (event.get("requestContext") or {}).get("authorizer") or {}
    user_id = (authorizer.get("lambda") or {}).get("user_id")
    repo = _auto_ingest_repository()
    repo.save_settings(request.model_dump(), user_id=user_id, now=utc_now())
    _invoke_auto_ingest({"action": "plan"})
    return _json_response(200, _auto_ingest_view(repo), correlation_id)


def _handle_admin_coverage(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
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
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    payload = _parse_json_body(event)
    is_hidden = payload.get("is_hidden")
    if not isinstance(is_hidden, bool):
        raise ValidationError("is_hidden must be a boolean")

    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )

    path = event.get("pathParameters") or {}
    style_id = str(path.get("style_id") or "")
    if not repository.set_style_hidden(style_id, is_hidden, utc_now()):
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
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    repository = create_clouder_repository_from_env()
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


_FUNNEL_STAGES = ("triaged", "categorized", "playlisted")


def _handle_analytics_funnel(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
    """Personal: own data for any signed-in user; admins may pass ?user_id."""
    from datetime import time as dtime
    from datetime import timedelta

    from .analytics_handler import (
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
    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    w = listening_windows(utc_now(), off)

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


def _handle_admin_runs(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:
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


def _handle_list(
    event: Mapping[str, Any], route_key: str, correlation_id: str
) -> dict[str, Any]:
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


def _handle_spotify_not_found(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:

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
        publish_date_from = _parse_date_param(event, "publish_date_from")
        publish_date_to = _parse_date_param(event, "publish_date_to")
        if (
            publish_date_from is not None
            and publish_date_to is not None
            and publish_date_from > publish_date_to
        ):
            raise ValidationError(
                "publish_date_from must be <= publish_date_to"
            )
    except ValidationError as exc:
        return _json_response(
            400,
            {"error_code": "validation_error", "message": exc.message},
            correlation_id,
        )

    rows = repository.find_tracks_not_found_on_spotify(
        limit,
        offset,
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )
    total = repository.count_tracks_not_found_on_spotify(
        search,
        publish_date_from=publish_date_from,
        publish_date_to=publish_date_to,
    )

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


def _parse_iso_date_field(payload: Mapping[str, Any], name: str) -> date:
    raw = payload.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError(f"{name} is required (YYYY-MM-DD)")
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")


def _handle_spotify_search_status(correlation_id: str) -> dict[str, Any]:
    """Admin view of the Spotify search: the queue (SQS) and the backlog (Aurora)."""
    repository = create_clouder_repository_from_env()
    if repository is None:
        return _json_response(
            503,
            {"error_code": "db_not_configured", "message": "Database is not configured"},
            correlation_id,
        )
    now = utc_now()
    counts = repository.spotify_search_counts(since=now - timedelta(minutes=10))
    blocked_until = repository.get_vendor_blocked_until("spotify")
    paused_until = blocked_until if blocked_until is not None and blocked_until > now else None

    queue = {"waiting_messages": 0, "in_flight": 0, "delayed": 0}
    queue_url = _load_api_settings().spotify_search_queue_url.strip()
    if queue_url:
        attrs = create_default_sqs_client().get_queue_attributes(
            QueueUrl=queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
                "ApproximateNumberOfMessagesDelayed",
            ],
        )["Attributes"]
        queue = {
            "waiting_messages": int(attrs.get("ApproximateNumberOfMessages", 0)),
            "in_flight": int(attrs.get("ApproximateNumberOfMessagesNotVisible", 0)),
            "delayed": int(attrs.get("ApproximateNumberOfMessagesDelayed", 0)),
        }

    if paused_until is not None:
        status = "paused"
    elif queue["in_flight"]:
        status = "running"
    elif queue["waiting_messages"] or queue["delayed"]:
        status = "queued"
    else:
        status = "idle"
    return _json_response(
        200,
        {
            "status": status,
            "paused_until": paused_until.isoformat() if paused_until else None,
            "queue": queue,
            "tracks": {
                "waiting": counts["waiting"],
                "not_found": counts["not_found"],
                "searched_last_10_min": counts["searched_recently"],
            },
        },
        correlation_id,
    )


def _handle_spotify_retry_not_found(
    event: Mapping[str, Any], correlation_id: str
) -> dict[str, Any]:

    payload = _parse_json_body(event)

    publish_date_from = _parse_iso_date_field(payload, "publish_date_from")
    publish_date_to = _parse_iso_date_field(payload, "publish_date_to")
    if publish_date_from > publish_date_to:
        raise ValidationError("publish_date_from must be <= publish_date_to")

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

    settings = _load_api_settings()
    queue_url = settings.spotify_search_queue_url.strip()
    if not queue_url:
        log_event(
            "ERROR",
            "spotify_retry_enqueue_failed",
            correlation_id=correlation_id,
            error_code="queue_not_configured",
        )
        return _json_response(
            500,
            {
                "error_code": "enqueue_failed",
                "message": "SPOTIFY_SEARCH_QUEUE_URL is not configured",
            },
            correlation_id,
        )

    now = utc_now()
    reset_count = repository.reset_spotify_not_found(
        publish_date_from, publish_date_to, now
    )
    pending_count = repository.count_spotify_pending_in_range(
        publish_date_from, publish_date_to
    )

    log_event(
        "INFO",
        "spotify_retry_requested",
        correlation_id=correlation_id,
        reset_count=reset_count,
        pending_count=pending_count,
    )

    if reset_count > 0 or pending_count > 0:
        message = {"batch_size": 200, "auto_continue": True}
        try:
            client = create_default_sqs_client()
            client.send_message(
                QueueUrl=queue_url,
                MessageBody=json.dumps(
                    message, ensure_ascii=False, separators=(",", ":")
                ),
                MessageAttributes={
                    "correlation_id": {
                        "DataType": "String",
                        "StringValue": correlation_id,
                    }
                },
            )
            log_event(
                "INFO",
                "spotify_retry_enqueued",
                correlation_id=correlation_id,
                reset_count=reset_count,
            )
        except Exception as exc:
            log_event(
                "ERROR",
                "spotify_retry_enqueue_failed",
                correlation_id=correlation_id,
                error_type=exc.__class__.__name__,
                error_message=str(exc)[:500],
            )
            return _json_response(
                500,
                {
                    "error_code": "enqueue_failed",
                    "message": (
                        "Tracks were reset but the search message could not "
                        "be enqueued; retry the request"
                    ),
                },
                correlation_id,
            )

    return _json_response(
        200,
        {"queued_count": reset_count, "correlation_id": correlation_id},
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


def _parse_date_param(event: Mapping[str, Any], name: str) -> date | None:
    query_params = event.get("queryStringParameters") or {}
    raw = query_params.get(name) if isinstance(query_params, Mapping) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date (YYYY-MM-DD)")


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
            processing_reason=result.processing_reason.value if result.processing_reason else None,
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

"""AWS Lambda handler for the collector API: admin gating and dispatch.

Routes live in `collector/api/routes_*`; `_ROUTE_TABLE` is the single source of
truth and must match the API Gateway routes wired to this Lambda.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import Any

from .api import (
    routes_admin,
    routes_catalog,
    routes_ingest,
    routes_runs,
    routes_spotify,
)
from .api.http import (
    _extract_api_request_id,
    _extract_correlation_id,
    _extract_route_key,
    _json_response,
    _require_admin,
)
from .errors import AppError
from .logging_utils import log_event

Route = Callable[[Mapping[str, Any], Any, str], dict[str, Any]]

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


def _delegate(module: str, func: str) -> Route:
    """A route served by a domain package, imported on first use to keep cold starts lean."""

    def route(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
        handle = getattr(importlib.import_module(f"{__package__}.{module}"), func)
        status, body = handle(event)
        if status == 204:
            return {"statusCode": 204, "headers": {"x-correlation-id": correlation_id}, "body": ""}
        return _json_response(status, body, correlation_id)

    return route


_ROUTE_TABLE: dict[str, Route] = {
    "": routes_ingest._handle_collect,  # direct Lambda invoke (no API Gateway)
    "POST /collect_bp_releases": routes_ingest._handle_collect,
    "POST /admin/beatport/ingest": routes_ingest._handle_admin_ingest,
    "GET /admin/auto-ingest": routes_ingest._handle_auto_ingest_get,
    "PUT /admin/auto-ingest": routes_ingest._handle_auto_ingest_put,
    "POST /admin/auto-ingest/run": routes_ingest._handle_auto_ingest_run,
    "GET /runs/{run_id}": routes_runs._handle_get_run,
    "GET /admin/runs": routes_runs._handle_admin_runs,
    "GET /admin/coverage": routes_admin._handle_admin_coverage,
    "PATCH /admin/styles/{style_id}": routes_admin._handle_admin_style_visibility,
    "GET /admin/users": routes_admin._handle_admin_users,
    "GET /tracks/spotify-not-found": routes_spotify._handle_spotify_not_found,
    "POST /admin/spotify/retry-not-found": routes_spotify._handle_spotify_retry_not_found,
    "GET /admin/spotify/search-status": routes_spotify._handle_spotify_search_status,
    "GET /tracks": routes_catalog._handle_list,
    "GET /albums": routes_catalog._handle_list,
    "GET /v1/analytics/funnel": routes_catalog._handle_analytics_funnel,
    "GET /styles": routes_catalog._handle_get_styles,
    "PUT /me/styles": routes_catalog._handle_put_my_styles,
    "POST /admin/labels/enrich": _delegate("label_enrichment.routes", "handle_post_enrich"),
    "POST /admin/labels/{label_id}/enrich-auto": _delegate("label_enrichment.routes", "handle_post_enrich_auto"),
    "GET /admin/labels/enrich/options": _delegate("label_enrichment.routes", "handle_get_options"),
    "GET /admin/labels/enrich-runs": _delegate("label_enrichment.routes", "handle_get_runs_list"),
    "GET /admin/labels/enrich-runs/{run_id}": _delegate("label_enrichment.routes", "handle_get_run"),
    "GET /admin/labels/backlog": _delegate("label_enrichment.routes", "handle_get_backlog"),
    "GET /admin/labels/{label_id}/history": _delegate("label_enrichment.routes", "handle_get_label_history"),
    "GET /admin/labels/{label_id}": _delegate("label_enrichment.routes", "handle_get_label"),
    "GET /admin/auto-enrich/labels": _delegate("label_enrichment.auto_routes", "handle_get_auto_config"),
    "PUT /admin/auto-enrich/labels": _delegate("label_enrichment.auto_routes", "handle_put_auto_config"),
    "PUT /labels/{label_id}/preference": _delegate("label_enrichment.routes", "handle_put_label_preference"),
    "GET /me/label-preferences": _delegate("label_enrichment.routes", "handle_get_my_label_preferences"),
    "GET /labels": _delegate("label_enrichment.routes", "handle_get_labels_list"),
    "GET /labels/{label_id}": _delegate("label_enrichment.routes", "handle_get_label_user"),
    "POST /admin/artists/enrich": _delegate("artist_enrichment.routes", "handle_post_enrich"),
    "POST /admin/artists/{artist_id}/enrich-auto": _delegate("artist_enrichment.routes", "handle_post_enrich_auto"),
    "GET /admin/artists/enrich/options": _delegate("artist_enrichment.routes", "handle_get_options"),
    "GET /admin/artists/enrich-runs": _delegate("artist_enrichment.routes", "handle_get_runs_list"),
    "GET /admin/artists/enrich-runs/{run_id}": _delegate("artist_enrichment.routes", "handle_get_run"),
    "GET /admin/artists/backlog": _delegate("artist_enrichment.routes", "handle_get_backlog"),
    "GET /admin/artists/{artist_id}/history": _delegate("artist_enrichment.routes", "handle_get_artist_history"),
    "GET /admin/artists/{artist_id}": _delegate("artist_enrichment.routes", "handle_get_artist"),
    "GET /admin/auto-enrich/artists": _delegate("artist_enrichment.auto_routes", "handle_get_auto_config"),
    "PUT /admin/auto-enrich/artists": _delegate("artist_enrichment.auto_routes", "handle_put_auto_config"),
    "PUT /artists/{artist_id}/preference": _delegate("artist_enrichment.routes", "handle_put_artist_preference"),
    "GET /me/artist-preferences": _delegate("artist_enrichment.routes", "handle_get_my_artist_preferences"),
    "GET /artists": _delegate("artist_enrichment.routes", "handle_get_artists_list"),
    "GET /artists/{artist_id}": _delegate("artist_enrichment.routes", "handle_get_artist_user"),
}


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


def _route(event: Mapping[str, Any], context: Any, correlation_id: str) -> dict[str, Any]:
    route_key = _extract_route_key(event)
    if route_key in _ADMIN_ROUTES:
        _require_admin(event)
    route = _ROUTE_TABLE.get(route_key)
    if route is None:
        return _json_response(
            404,
            {"error_code": "not_found", "message": "Route not found"},
            correlation_id,
        )
    return route(event, context, correlation_id)

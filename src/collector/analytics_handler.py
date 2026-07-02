"""Standalone analytics-api Lambda (§10 serving).

Serves per-user analytics by running pre-written, parameterized Athena queries
against mart_user_daily and fact_session. Clients supply a date range and
user_id; they never send SQL. Admin is enforced here on the authorizer context
(§10.1, §13). Aurora is never touched.

Routes are GET /v1/analytics/{user-daily,sessions}.
"""

from __future__ import annotations

import json
import os
import re
import time
from functools import lru_cache
from typing import Any, Mapping

from .logging_utils import log_event

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Route -> named queries. user_id binds via ExecutionParameters (?);
# from/to inline as validated 'YYYY-MM-DD' literals (gotcha #13).
_ROUTE_QUERIES: dict[str, dict[str, str]] = {
    "user-daily": {"user-daily": (
        "SELECT user_id, activity_type, dt, sessions, "
        "avg_tracks_listened, avg_tracks_promoted, avg_tracks_deleted, "
        "p50_duration_ms, p90_duration_ms, p50_time_per_track_ms, p90_time_per_track_ms "
        "FROM mart_user_daily WHERE user_id = ? "
        "AND dt BETWEEN {frm} AND {to} ORDER BY dt, activity_type"
    )},
    "sessions": {"sessions": (
        "SELECT user_id, activity_type, dt, session_seq, ts_start, ts_end, "
        "duration_ms, tracks_listened, tracks_promoted, tracks_deleted "
        "FROM fact_session WHERE user_id = ? "
        "AND dt BETWEEN {frm} AND {to} ORDER BY dt, activity_type, session_seq"
    )},
}


class AnalyticsError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def _require_admin(event: Mapping[str, Any]) -> str:
    # Mirrors handler._require_admin / auth_handler._authorizer_context: is_admin is
    # under event['requestContext']['authorizer']['lambda'] (the 'lambda' nesting is load-bearing).
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        authorizer = rc.get("authorizer")
        if isinstance(authorizer, Mapping):
            ctx = authorizer.get("lambda")
            if isinstance(ctx, Mapping) and bool(ctx.get("is_admin")):
                return str(ctx.get("user_id") or "")
    raise AnalyticsError(403, "admin_required", "Admin role required.")


def _route_name(event: Mapping[str, Any]) -> str:
    route_key = ""
    rc = event.get("requestContext")
    if isinstance(rc, Mapping):
        route_key = str(rc.get("routeKey") or "")
    path = route_key.split(" ", 1)[-1] if route_key else str(event.get("rawPath") or "")
    name = path.rsplit("/", 1)[-1]
    if name not in _ROUTE_QUERIES:
        raise AnalyticsError(404, "unknown_dashboard", f"Unknown dashboard: {name!r}")
    return name


def _validate_params(qs: Mapping[str, Any] | None) -> tuple[str, str, str]:
    qs = qs or {}
    date_from = str(qs.get("from") or "")
    date_to = str(qs.get("to") or "")
    if not _DATE_RE.match(date_from) or not _DATE_RE.match(date_to):
        raise AnalyticsError(400, "invalid_params", "from/to must be YYYY-MM-DD dates.")
    if date_from > date_to:
        raise AnalyticsError(400, "invalid_params", "from must be <= to.")
    user_id = str(qs.get("user_id") or "")
    if not user_id or len(user_id) > 128:
        raise AnalyticsError(400, "invalid_params", "user_id required (max 128 chars).")
    return date_from, date_to, user_id


def build_queries(
    route: str, date_from: str, date_to: str, user_id: str
) -> dict[str, tuple[str, list[str]]]:
    specs = _ROUTE_QUERIES[route]
    # Dates inline as quoted literals (gotcha #13 — Athena mis-parses bound dates).
    # Re-validate here as defense-in-depth against any bypass of _validate_params.
    if not (_DATE_RE.match(date_from) and _DATE_RE.match(date_to)):
        raise AnalyticsError(400, "invalid_params", "from/to must be YYYY-MM-DD dates.")
    frm, to = f"'{date_from}'", f"'{date_to}'"
    # user_id binds via ExecutionParameters (?) — never inlined, never in the SQL string.
    return {name: (sql.format(frm=frm, to=to), [user_id]) for name, sql in specs.items()}


# ── Athena execution (Task 2 — appended below) ───────────────────────────────

_ATHENA_CLIENT: Any = None


def create_default_athena_client() -> Any:
    import boto3  # lazy import keeps unit tests boto3-free

    return boto3.client("athena")


def _client() -> Any:
    global _ATHENA_CLIENT
    if _ATHENA_CLIENT is None:
        _ATHENA_CLIENT = create_default_athena_client()
    return _ATHENA_CLIENT


def _rows_from_result(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = result.get("ResultSet", {}).get("Rows", [])
    if not raw:
        return []
    header = [c.get("VarCharValue", "") for c in raw[0].get("Data", [])]
    out: list[dict[str, Any]] = []
    for row in raw[1:]:
        data = row.get("Data", [])
        out.append(
            {
                header[i]: (data[i].get("VarCharValue") if i < len(data) else None)
                for i in range(len(header))
            }
        )
    return out


def _run_athena(client: Any, sql: str, params: list[str]) -> list[dict[str, Any]]:
    reuse_minutes = int(os.environ.get("ANALYTICS_RESULT_REUSE_MINUTES", "60"))
    kwargs: dict[str, Any] = {
        "QueryString": sql,
        "QueryExecutionContext": {"Database": os.environ["ATHENA_DATABASE"]},
        "WorkGroup": os.environ.get("ATHENA_WORKGROUP", "primary"),
        "ResultConfiguration": {"OutputLocation": os.environ["ATHENA_OUTPUT_LOCATION"]},
        "ResultReuseConfiguration": {
            "ResultReuseByAgeConfiguration": {
                "Enabled": True,
                "MaxAgeInMinutes": reuse_minutes,
            }
        },
    }
    if params:  # Athena rejects an empty ExecutionParameters list; omit when inlined.
        kwargs["ExecutionParameters"] = params
    started = client.start_query_execution(**kwargs)
    qid = started["QueryExecutionId"]
    state = "QUEUED"
    for _ in range(120):
        ex = client.get_query_execution(QueryExecutionId=qid)
        state = ex["QueryExecution"]["Status"]["State"]
        if state in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    if state != "SUCCEEDED":
        raise AnalyticsError(502, "athena_failed", f"Athena query {state}.")
    return _rows_from_result(client.get_query_results(QueryExecutionId=qid))


@lru_cache(maxsize=64)
def _cached_rows(sql: str, params_key: tuple[str, ...]) -> tuple[Any, ...]:
    # ponytail: Athena result-reuse + this warm-Lambda memo is the whole cache (§10.2).
    return tuple(_run_athena(_client(), sql, list(params_key)))


def _correlation_id(event: Mapping[str, Any]) -> str:
    headers = event.get("headers")
    if isinstance(headers, Mapping):
        cid = headers.get("x-correlation-id") or headers.get("X-Correlation-Id")
        if cid:
            return str(cid)
    rc = event.get("requestContext")
    if isinstance(rc, Mapping) and rc.get("requestId"):
        return str(rc["requestId"])
    return "unknown"


def _response(status: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=str),
    }


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    correlation_id = _correlation_id(event)
    try:
        _require_admin(event)
        route = _route_name(event)
        qs = event.get("queryStringParameters")
        date_from, date_to, user_id = _validate_params(qs if isinstance(qs, Mapping) else None)
        payload: dict[str, Any] = {"correlation_id": correlation_id}
        for name, (sql, params) in build_queries(route, date_from, date_to, user_id).items():
            payload[name] = list(_cached_rows(sql, tuple(params)))
        log_event("INFO", "analytics_served", correlation_id=correlation_id,
                  status_code=200)
        return _response(200, payload)
    except AnalyticsError as exc:
        log_event("WARNING", "analytics_rejected", correlation_id=correlation_id,
                  status_code=exc.status_code, error_code=exc.error_code)
        return _response(exc.status_code, {
            "error_code": exc.error_code,
            "message": exc.message,
            "correlation_id": correlation_id,
        })
    except Exception as exc:  # safety net — response stays generic, log carries detail
        log_event("ERROR", "analytics_error", correlation_id=correlation_id,
                  status_code=500, error_type=type(exc).__name__,
                  error_message=str(exc)[:500])
        return _response(500, {
            "error_code": "internal_error",
            "message": "Internal error.",
            "correlation_id": correlation_id,
        })

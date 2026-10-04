"""Standalone analytics-api Lambda (§10 serving).

Serves per-user analytics by running pre-written, parameterized Athena queries
against mart_user_daily and fact_session. Clients supply a date range and
user_id; they never send SQL. Admin is enforced here on the authorizer context
(§10.1, §13). Aurora is never touched.

Routes are GET /v1/analytics/{user-daily,sessions,listening}. `listening` reads
bronze_events live (fresh to the Firehose buffer), not the daily marts.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Mapping

from .analytics_rollup import TRINO
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


_ROUTES = frozenset(_ROUTE_QUERIES) | {"listening"}

# ponytail: unknown/zero track duration -> assume 10 min as the per-play cap.
_FALLBACK_TRACK_MS = 600_000
_OFFSET_RE = re.compile(r"^-?\d{1,3}$")


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
    if name not in _ROUTES:
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


# ── listening: minutes + distinct tracks per local day / 7d / 30d ───────────

def parse_tz_offset(raw: Any) -> int:
    """Browser UTC offset in minutes (east-positive); default UTC."""
    if raw in (None, ""):
        return 0
    s = str(raw)
    if not _OFFSET_RE.match(s) or abs(int(s)) > 840:
        raise AnalyticsError(400, "invalid_params", "tz_offset_min must be an integer in [-840, 840].")
    return int(s)


def listening_windows(now: datetime, tz_offset_min: int) -> dict[str, date]:
    """Local today + rolling 7/30-day window starts. scan_from pads one UTC day
    so the dt-partition prune never cuts a play that maps into the window."""
    today = (now.astimezone(timezone.utc) + timedelta(minutes=tz_offset_min)).date()
    month_from = today - timedelta(days=29)
    return {
        "today": today,
        "week_from": today - timedelta(days=6),
        "month_from": month_from,
        "scan_from": month_from - timedelta(days=1),
    }


def listening_sql(
    d: Mapping[str, str],
    *,
    scan_from: str,
    week_from: str,
    month_from: str,
    tz_offset_min: int,
    source: str = "bronze_events",
) -> str:
    """Per-play listen time = gap to the user's next play, capped at the track's
    duration. Only playback_play is emitted today (no pause/ended), so this is
    the best wall-clock signal. Ordered by ts_client (+ ULID event_id): ts_server
    is stamped once per SDK batch, so plays flushed together would tie at gap 0.
    user_id binds as the single `?`; dates/offset are validated and inlined
    (gotcha #13).
    """
    for v in (scan_from, week_from, month_from):
        if not _DATE_RE.match(v):
            raise AnalyticsError(400, "invalid_params", "bad date literal")
    off = int(tz_offset_min)
    ts = d["to_ts"].format("ts_client")
    local_dt = d["to_date"].format(d["add_min"].format(off, "ts"))
    gap_ms = f"({d['epoch'].format('lead(ts) OVER (ORDER BY ts, event_id)')} - {d['epoch'].format('ts')}) * 1000"
    return f"""
WITH plays AS (
  SELECT track_id, event_id, {ts} AS ts,
         CAST(coalesce(nullif(duration_ms, 0), {_FALLBACK_TRACK_MS}) AS DOUBLE) AS dur_ms
  FROM {source}
  WHERE event_name = 'playback_play' AND user_id = ? AND dt >= '{scan_from}'
),
listened AS (
  SELECT track_id, {local_dt} AS local_dt,
         least(coalesce({gap_ms}, dur_ms), dur_ms) AS ms
  FROM plays
)
SELECT CAST(local_dt AS VARCHAR) AS period, CAST(sum(ms) AS BIGINT) AS listened_ms,
       count(DISTINCT track_id) AS tracks
FROM listened WHERE local_dt >= DATE '{month_from}' GROUP BY local_dt
UNION ALL
SELECT 'week', CAST(sum(ms) AS BIGINT), count(DISTINCT track_id)
FROM listened WHERE local_dt >= DATE '{week_from}'
UNION ALL
SELECT 'month', CAST(sum(ms) AS BIGINT), count(DISTINCT track_id)
FROM listened WHERE local_dt >= DATE '{month_from}'
"""


def shape_listening(rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """Athena rows (period, listened_ms, tracks) -> totals + zero-filled 30-day series."""
    by: dict[str, dict[str, int]] = {
        str(r["period"]): {
            "listened_ms": int(r.get("listened_ms") or 0),
            "tracks": int(r.get("tracks") or 0),
        }
        for r in rows
    }
    zero = {"listened_ms": 0, "tracks": 0}
    days = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
    return {
        "today": today.isoformat(),
        "totals": {
            "day": by.get(today.isoformat(), zero),
            "week": by.get("week", zero),
            "month": by.get("month", zero),
        },
        "daily": [{"dt": dt, **by.get(dt, zero)} for dt in days],
    }


def serve_listening(qs: Mapping[str, Any], caller_id: str) -> dict[str, Any]:
    off = parse_tz_offset(qs.get("tz_offset_min"))
    user_id = str(qs.get("user_id") or caller_id)
    if not user_id or len(user_id) > 128:
        raise AnalyticsError(400, "invalid_params", "user_id required (max 128 chars).")
    w = listening_windows(datetime.now(timezone.utc), off)
    sql = listening_sql(
        TRINO,
        scan_from=w["scan_from"].isoformat(),
        week_from=w["week_from"].isoformat(),
        month_from=w["month_from"].isoformat(),
        tz_offset_min=off,
    )
    # Short reuse, no warm-Lambda memo: "today" must move within minutes.
    rows = _run_athena(_client(), sql, [user_id], reuse_minutes=5)
    return shape_listening(rows, w["today"])


# ── Athena execution ─────────────────────────────────────────────────────────

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


def _run_athena(
    client: Any, sql: str, params: list[str], *, reuse_minutes: int | None = None
) -> list[dict[str, Any]]:
    if reuse_minutes is None:
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
        caller_id = _require_admin(event)
        route = _route_name(event)
        qs = event.get("queryStringParameters")
        qs = qs if isinstance(qs, Mapping) else None
        payload: dict[str, Any] = {"correlation_id": correlation_id}
        if route == "listening":
            payload.update(serve_listening(qs or {}, caller_id))
        else:
            date_from, date_to, user_id = _validate_params(qs)
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

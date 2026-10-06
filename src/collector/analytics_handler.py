"""Standalone analytics-api Lambda: personal listening stats.

GET /v1/analytics/{listening,time-per-track} read bronze_events live through
Athena (fresh to the Firehose buffer); time-per-track joins the nightly catalog
snapshot for track -> style. Any signed-in user gets their own data; only an admin may
pass ?user_id for someone else's (resolve_user). Clients never send SQL and
Aurora is never touched.

SQL is written once for two dialects: Trino/Athena in production, DuckDB in
tests; only the function fragments below differ.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from .logging_utils import log_event

# Dialect fragments. {} is the single positional arg (add_min: {0}=minutes, {1}=ts;
# pctl: {0}=value, {1}=fraction).
TRINO: Mapping[str, str] = {
    "to_ts": "from_iso8601_timestamp({})",
    "epoch": "to_unixtime({})",
    "to_date": "date({})",
    "add_min": "date_add('minute', {0}, {1})",
    "pctl": "approx_percentile({0}, {1})",
}
DUCKDB: Mapping[str, str] = {
    "to_ts": "CAST({} AS TIMESTAMP)",
    "epoch": "epoch({})",
    "to_date": "CAST({} AS DATE)",
    "add_min": "({1} + to_minutes({0}))",
    "pctl": "quantile_cont({0}, {1})",
}

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ROUTES = frozenset({"listening", "time-per-track"})
_STAGES = ("triage", "category", "playlist")
_DAYS = (30, 90)

# ponytail: unknown/zero track duration -> assume 10 min as the per-play cap.
_FALLBACK_TRACK_MS = 600_000
_OFFSET_RE = re.compile(r"^-?\d{1,3}$")


class AnalyticsError(Exception):
    def __init__(self, status_code: int, error_code: str, message: str) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def resolve_user(event: Mapping[str, Any], requested: str) -> str:
    """Personal analytics: any signed-in user sees their own data; only an
    admin may ask for someone else's via ?user_id."""
    ctx: Mapping[str, Any] = {}
    rc = event.get("requestContext")
    if isinstance(rc, Mapping) and isinstance(rc.get("authorizer"), Mapping):
        lam = rc["authorizer"].get("lambda")
        ctx = lam if isinstance(lam, Mapping) else {}
    caller = str(ctx.get("user_id") or "")
    if not caller:
        raise AnalyticsError(401, "unauthorized", "Authentication required.")
    if len(requested) > 128:
        raise AnalyticsError(400, "invalid_params", "user_id max 128 chars.")
    if requested and requested != caller and not bool(ctx.get("is_admin")):
        raise AnalyticsError(403, "admin_required", "Only admins can view other users.")
    return requested or caller


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


def _plays_cte(d: Mapping[str, str], *, scan_from: str, table: str = "bronze_events") -> str:
    """CTE chain (no leading WITH) ending in `plays`: one row per play with
    track_id, stage (playback source), ts, ms.

    ms = the play's "playing" stretches, capped at the track's duration. A
    stretch starts at a play or resume and runs to the user's next playback
    event (pause / resume / ended / next play); stretches after a pause or end
    don't count. Plays without pause/ended events (older data) fall back to
    play -> next play. Ordered by ts_client (+ ULID event_id): ts_server is
    stamped once per SDK batch, so events flushed together would tie. user_id
    binds as the single `?`; scan_from is validated by the caller (gotcha #13).
    """
    ts = d["to_ts"].format("ts_client")
    gap_ms = f"({d['epoch'].format('lead(ts) OVER (ORDER BY ts, event_id)')} - {d['epoch'].format('ts')}) * 1000"
    return f"""ev AS (
  SELECT track_id, source, event_id, event_name, {ts} AS ts,
         CAST(coalesce(nullif(duration_ms, 0), {_FALLBACK_TRACK_MS}) AS DOUBLE) AS dur_ms
  FROM {table}
  WHERE event_name IN ('playback_play', 'playback_pause', 'playback_resume', 'playback_ended')
    AND user_id = ? AND dt >= '{scan_from}'
),
seq AS (
  SELECT *,
    SUM(CASE WHEN event_name = 'playback_play' THEN 1 ELSE 0 END)
      OVER (ORDER BY ts, event_id ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS play_no,
    {gap_ms} AS gap_ms
  FROM ev
),
per_play AS (
  SELECT play_no,
    max(CASE WHEN event_name = 'playback_play' THEN track_id END) AS track_id,
    max(CASE WHEN event_name = 'playback_play' THEN source END) AS stage,
    max(CASE WHEN event_name = 'playback_play' THEN dur_ms END) AS dur_ms,
    min(CASE WHEN event_name = 'playback_play' THEN ts END) AS ts,
    sum(CASE WHEN event_name IN ('playback_play', 'playback_resume')
             THEN coalesce(gap_ms, dur_ms) ELSE 0 END) AS played_ms
  FROM seq
  WHERE play_no > 0
  GROUP BY play_no
),
plays AS (
  SELECT track_id, stage, ts, least(played_ms, dur_ms) AS ms FROM per_play
)"""


def _check_dates(*values: str) -> None:
    for v in values:
        if not _DATE_RE.match(v):
            raise AnalyticsError(400, "invalid_params", "bad date literal")


def listening_sql(
    d: Mapping[str, str],
    *,
    scan_from: str,
    week_from: str,
    month_from: str,
    tz_offset_min: int,
    table: str = "bronze_events",
) -> str:
    """Minutes + distinct tracks per local day, plus 7/30-day totals."""
    _check_dates(scan_from, week_from, month_from)
    local_dt = d["to_date"].format(d["add_min"].format(int(tz_offset_min), "ts"))
    return f"""
WITH {_plays_cte(d, scan_from=scan_from, table=table)},
listened AS (SELECT track_id, {local_dt} AS local_dt, ms FROM plays)
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


def time_per_track_sql(
    d: Mapping[str, str],
    *,
    scan_from: str,
    dict_from: str,
    table: str = "bronze_events",
    catalog: str = "bronze_catalog_export",
) -> str:
    """Listen-time percentiles per stage x style (plus an all-styles row per
    stage, style_id '*'). Style comes from the nightly catalog snapshot; any
    snapshot since dict_from counts (a track's style never changes), so a
    missed night still resolves. Unknown tracks keep style_id NULL."""
    _check_dates(scan_from, dict_from)
    p50 = d["pctl"].format("ms", "0.5")
    p90 = d["pctl"].format("ms", "0.9")
    return f"""
WITH {_plays_cte(d, scan_from=scan_from, table=table)},
dict AS (
  SELECT id, max(style_id) AS style_id FROM {catalog}
  WHERE tbl = 'clouder_tracks' AND snapshot_dt >= '{dict_from}' GROUP BY id
),
names AS (
  SELECT id, max(name) AS name FROM {catalog}
  WHERE tbl = 'clouder_styles' AND snapshot_dt >= '{dict_from}' GROUP BY id
),
x AS (
  SELECT replace(p.stage, '_player', '') AS stage, d.style_id, p.ms
  FROM plays p LEFT JOIN dict d ON d.id = p.track_id
  WHERE p.stage IS NOT NULL
)
SELECT x.stage, x.style_id, max(n.name) AS style_name, count(*) AS n,
       CAST({p50} AS BIGINT) AS p50_ms, CAST({p90} AS BIGINT) AS p90_ms
FROM x LEFT JOIN names n ON n.id = x.style_id
GROUP BY x.stage, x.style_id
UNION ALL
SELECT stage, '*', NULL, count(*), CAST({p50} AS BIGINT), CAST({p90} AS BIGINT)
FROM x GROUP BY stage
"""


def parse_days(raw: Any) -> int:
    if raw in (None, ""):
        return _DAYS[0]
    s = str(raw)
    if not s.isdigit() or int(s) not in _DAYS:
        raise AnalyticsError(400, "invalid_params", f"days must be one of {list(_DAYS)}.")
    return int(s)


def shape_time_per_track(rows: list[dict[str, Any]], *, days: int) -> dict[str, Any]:
    """Athena rows -> one row per style with a cell per stage (None = no plays).
    Order: all styles ('*'), then styles by total plays desc, unknown style last."""
    styles: dict[Any, dict[str, Any]] = {}
    for r in rows:
        if r.get("stage") not in _STAGES:
            continue
        sid = r.get("style_id")
        row = styles.setdefault(
            sid, {"style_id": sid, "style_name": None, "cells": dict.fromkeys(_STAGES)}
        )
        row["style_name"] = row["style_name"] or r.get("style_name")
        row["cells"][r["stage"]] = {
            "n": int(r["n"]),
            "p50_ms": int(float(r["p50_ms"])),
            "p90_ms": int(float(r["p90_ms"])),
        }

    def total(row: dict[str, Any]) -> int:
        return sum(c["n"] for c in row["cells"].values() if c)

    def order(row: dict[str, Any]) -> tuple[int, int]:
        sid = row["style_id"]
        return (0 if sid == "*" else 2 if sid is None else 1, -total(row))

    return {"days": days, "stages": list(_STAGES), "rows": sorted(styles.values(), key=order)}


def serve_time_per_track(qs: Mapping[str, Any], user_id: str) -> dict[str, Any]:
    days = parse_days(qs.get("days"))
    today = datetime.now(timezone.utc).date()
    sql = time_per_track_sql(
        TRINO,
        scan_from=(today - timedelta(days=days)).isoformat(),
        dict_from=(today - timedelta(days=3)).isoformat(),
    )
    rows = _run_athena(_client(), sql, [user_id], reuse_minutes=15)
    return shape_time_per_track(rows, days=days)


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


def serve_listening(qs: Mapping[str, Any], user_id: str) -> dict[str, Any]:
    off = parse_tz_offset(qs.get("tz_offset_min"))
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
    client: Any, sql: str, params: list[str], *, reuse_minutes: int = 5
) -> list[dict[str, Any]]:
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
        route = _route_name(event)
        qs = event.get("queryStringParameters")
        qs = qs if isinstance(qs, Mapping) else {}
        user_id = resolve_user(event, str(qs.get("user_id") or ""))
        payload: dict[str, Any] = {"correlation_id": correlation_id}
        serve = serve_listening if route == "listening" else serve_time_per_track
        payload.update(serve(qs, user_id))
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

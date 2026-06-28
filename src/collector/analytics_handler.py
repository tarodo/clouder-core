"""Standalone analytics-api Lambda (§10 serving).

Serves the five admin dashboards (§11) by running pre-written, parameterized
Athena queries against the gold/ star schema (and bronze_ops for Dashboard 5).
Clients pick a date range; they never send SQL. Admin is enforced here on the
authorizer context (§10.1, §13). Aurora is never touched.

Routes are GET /v1/analytics/{triage,taste,funnel,playback,ops}. The /v1 prefix
is registered in CloudFront api_gw_pure_path_patterns + the Vite dev proxy
(§5.1 step 4) so the SPA fetch reaches API Gateway; the browser page lives at
/admin/analytics (delivered by the existing /admin/* spa-aware patterns).
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Mapping

from .logging_utils import log_event

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Route -> ordered named queries. Every query is a FIXED string with positional
# `?` placeholders bound via Athena ExecutionParameters. No code path interpolates
# client input into SQL (§10.1 "never send raw SQL"). Each named query becomes one
# panel in the dashboard payload (the frontend reads payload[name]); "rows" is the
# primary series, "freshness" is post-processed (ops only).
#
# ponytail: gold/bronze column names below are REPRESENTATIVE — reconcile against
# the actual Increment-3 star schema before apply; the contract the frontend
# depends on is the shape (named, parameterized, multi-query-per-route).
# Increment-3 reconciliation checklist — each template depends on these columns
# existing (verify per template via Glue GetTable / Athena EXPLAIN when the tables
# land; column drift is otherwise undetectable until a live Athena run):
#   dim_date:            date_key, date, saturday_week_year, saturday_week_number
#   dim_category:        category_key, name
#   dim_track:           track_key, title, bpm, label_key
#   dim_label:           label_key, name
#   fact_track_decision: date_key, category_key, track_key, user_key, decision_ms, action
#   fact_triage_session: date_key, undo_rate
#   fact_funnel_step:    date_key, track_key, step, ms_since_prev
#   fact_playback:       date_key, track_key, user_key, listen_through_ratio, skipped
#   fact_seek:           date_key, track_key
#   bronze_ops:          dt, phase, duration_ms, failed_after
#   bronze_events:       dt
#
# NOTE: fact_track_decision.category_key is currently a DEGENERATE dimension
# (bucket_type string) in the P1 star schema — not a dim_category FK. The join
# below must be reconciled when dim_category gains the matching surrogate key in
# Increment-3. Tagged ponytail: in the by_category query below.
_ROUTE_QUERIES: dict[str, dict[str, str]] = {
    "triage": {
        # §11 D1: median decision time + throughput per category over time.
        "rows": (
            "SELECT d.date AS date, c.name AS category, "
            "approx_percentile(f.decision_ms, 0.5) AS median_decision_ms, "
            "count(*) AS decisions "
            "FROM fact_track_decision f "
            "JOIN dim_date d ON f.date_key = d.date_key "
            "LEFT JOIN dim_category c ON f.category_key = c.category_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY d.date, c.name ORDER BY d.date"
        ),
        # §11 D1 headline: undo rate, sourced from fact_triage_session.undo_rate (§7).
        "undo": (
            "SELECT d.date AS date, avg(s.undo_rate) AS undo_rate "
            "FROM fact_triage_session s "
            "JOIN dim_date d ON s.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY d.date ORDER BY d.date"
        ),
    },
    "taste": {
        # §11 D2: label affinity = categorize-count + avg BPM + playback skip-rate
        # per label (fact_playback joined by label_key for the skip signal).
        # ponytail: §11 D2 also names a BPM HISTOGRAM and a category-mix-by-
        # genre/BPM/key breakdown — both deferred follow-ups. This route ships
        # label affinity only. Add a bpm-bucket histogram (GROUP BY width_bucket
        # over dim_track.bpm) + a genre/key mix GROUP BY when D2's full
        # "keep vs skip by genre/BPM/key" value story is needed.
        "rows": (
            "SELECT l.name AS label, count(*) AS categorized, avg(t.bpm) AS avg_bpm, "
            "max(sk.skip_rate) AS skip_rate "
            "FROM fact_track_decision f "
            "JOIN dim_track t ON f.track_key = t.track_key "
            "LEFT JOIN dim_label l ON t.label_key = l.label_key "
            "LEFT JOIN ("
            "  SELECT t2.label_key AS label_key, "
            "  avg(CASE WHEN p.skipped THEN 1.0 ELSE 0.0 END) AS skip_rate "
            "  FROM fact_playback p JOIN dim_track t2 ON p.track_key = t2.track_key "
            "  GROUP BY t2.label_key"
            ") sk ON sk.label_key = t.label_key "
            "JOIN dim_date d ON f.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} AND f.action <> 'undo' "
            "GROUP BY l.name ORDER BY categorized DESC LIMIT 50"
        ),
    },
    "funnel": {
        # §11 D3: lifecycle drop-off + time-between-steps (time-to-publish hop).
        "rows": (
            "SELECT f.step AS step, count(DISTINCT f.track_key) AS tracks, "
            "approx_percentile(f.ms_since_prev, 0.5) AS median_ms_since_prev "
            "FROM fact_funnel_step f "
            "JOIN dim_date d ON f.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY f.step"
        ),
        # §11 D3: weekly throughput by Saturday-week (ADR-0003 — never ISO-week).
        "weekly": (
            "SELECT concat(cast(d.saturday_week_year AS varchar), '-W', "
            "cast(d.saturday_week_number AS varchar)) AS week, "
            "count(DISTINCT f.track_key) AS tracks "
            "FROM fact_funnel_step f "
            "JOIN dim_date d ON f.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY d.saturday_week_year, d.saturday_week_number "
            "ORDER BY d.saturday_week_year, d.saturday_week_number"
        ),
    },
    "playback": {
        # §11 D4: listen-through + skip-rate series.
        # ponytail: §11 D4 also names a listen-through DISTRIBUTION — deferred
        # follow-up. This route ships a MEDIAN listen ratio (+ skip-rate). Add a
        # listen_through_ratio bucket histogram (GROUP BY width_bucket) when the
        # distribution shape is needed.
        "rows": (
            "SELECT d.date AS date, "
            "approx_percentile(p.listen_through_ratio, 0.5) AS median_listen_ratio, "
            "avg(CASE WHEN p.skipped THEN 1 ELSE 0 END) AS skip_rate, "
            "count(*) AS plays "
            "FROM fact_playback p "
            "JOIN dim_date d ON p.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY d.date ORDER BY d.date"
        ),
        # §11 D4: listen-ratio vs final-category correlation
        # (fact_playback -> fact_track_decision -> dim_category). The decision join
        # is by track_key AND user_key: a track is categorized per-user (§2 multi-
        # tenant, one Aurora DB, facts carry user_key), so a track_key-only join
        # would cross-join one user's plays against every other user's
        # categorization of the same track and corrupt the correlation.
        # ponytail: fact_track_decision.category_key is a degenerate string in P1
        # (not a dim_category FK) — reconcile this join when dim_category gains the
        # matching surrogate key in Increment-3.
        "by_category": (
            "SELECT c.name AS category, "
            "avg(p.listen_through_ratio) AS avg_listen_ratio, count(*) AS plays "
            "FROM fact_playback p "
            "JOIN fact_track_decision f "
            "ON f.track_key = p.track_key AND f.user_key = p.user_key "
            "JOIN dim_category c ON f.category_key = c.category_key "
            "JOIN dim_date d ON p.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY c.name ORDER BY plays DESC"
        ),
        # §11 D4: seek heatmap (fact_seek x dim_track). ponytail: representative 1-D
        # slice (most-seeked tracks); full 2-D from/to-bucket heatmap is a follow-up.
        "seek": (
            "SELECT t.title AS track, count(*) AS seeks "
            "FROM fact_seek s "
            "JOIN dim_track t ON s.track_key = t.track_key "
            "JOIN dim_date d ON s.date_key = d.date_key "
            "WHERE date_format(d.date, '%Y-%m-%d') BETWEEN {frm} AND {to} "
            "GROUP BY t.title ORDER BY seeks DESC LIMIT 20"
        ),
    },
    "ops": {
        # §11 D5: enrichment success-rate + latency p50 AND p95 (log-backed bronze_ops).
        "rows": (
            "SELECT o.dt AS dt, o.message AS phase, "
            "approx_percentile(o.duration_ms, 0.5) AS p50_duration_ms, "
            "approx_percentile(o.duration_ms, 0.95) AS p95_duration_ms, "
            "avg(CASE WHEN o.failed_after IS NULL THEN 1 ELSE 0 END) AS success_rate, "
            "count(*) AS runs "
            "FROM bronze_ops o "
            "WHERE o.dt BETWEEN {frm} AND {to} "
            "GROUP BY o.dt, o.message ORDER BY o.dt"
        ),
        # §11 D5: pipeline freshness (newest bronze_events dt vs now).
        "freshness": (
            "SELECT max(dt) AS newest_dt FROM bronze_events WHERE dt BETWEEN {frm} AND {to}"
        ),
    },
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


def _validate_params(qs: Mapping[str, Any] | None) -> tuple[str, str]:
    # ponytail: date-range-only (§10.1 filters descoped for Phase 1). Add a
    # constrained, ExecutionParameters-bound filter param when a dashboard needs one.
    qs = qs or {}
    date_from = str(qs.get("from") or "")
    date_to = str(qs.get("to") or "")
    if not _DATE_RE.match(date_from) or not _DATE_RE.match(date_to):
        raise AnalyticsError(400, "invalid_params", "from/to must be YYYY-MM-DD dates.")
    if date_from > date_to:
        raise AnalyticsError(400, "invalid_params", "from must be <= to.")
    return date_from, date_to


def build_queries(
    route: str, date_from: str, date_to: str
) -> dict[str, tuple[str, list[str]]]:
    specs = _ROUTE_QUERIES[route]
    # The range inlines as quoted string literals (Athena ExecutionParameters mis-parse
    # a date string like '2026-05-29' as the arithmetic 2026-5-29=1992). Re-assert the
    # YYYY-MM-DD shape here as defense-in-depth so nothing but a validated date can ever
    # reach the SQL, independent of the caller.
    if not (_DATE_RE.match(date_from) and _DATE_RE.match(date_to)):
        raise AnalyticsError(400, "invalid_params", "from/to must be YYYY-MM-DD dates.")
    frm, to = f"'{date_from}'", f"'{date_to}'"
    return {name: (sql.format(frm=frm, to=to), []) for name, sql in specs.items()}


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


def _freshness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    newest = rows[0].get("newest_dt") if rows else None
    lag_hours = None
    if newest:
        try:
            dt = datetime.strptime(str(newest), "%Y-%m-%d").replace(tzinfo=timezone.utc)
            lag_hours = round((datetime.now(timezone.utc) - dt).total_seconds() / 3600.0, 1)
        except ValueError:
            lag_hours = None
    return {"newest_dt": newest, "lag_hours": lag_hours}


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
        date_from, date_to = _validate_params(qs if isinstance(qs, Mapping) else None)
        payload: dict[str, Any] = {"correlation_id": correlation_id}
        # ponytail: named queries run sequentially; result-reuse makes repeats ~$0.
        # Parallelize with a ThreadPool only if a dashboard's wall time bites.
        for name, (sql, params) in build_queries(route, date_from, date_to).items():
            rows = list(_cached_rows(sql, tuple(params)))
            if name == "freshness":
                payload["freshness"] = _freshness(rows)
            else:
                payload[name] = rows
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
    except Exception:  # pragma: no cover - safety net, never leak internals
        log_event("ERROR", "analytics_error", correlation_id=correlation_id,
                  status_code=500)
        return _response(500, {
            "error_code": "internal_error",
            "message": "Internal error.",
            "correlation_id": correlation_id,
        })

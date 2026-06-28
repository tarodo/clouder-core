# Phase 1 · Increment 5 — Serving (analytics-api + dashboards) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Serve the five `/admin/analytics` dashboards from the gold star schema via a standalone admin-gated `analytics-api` Lambda that runs only pre-written, parameterized Athena queries, plus the SPA route, a generic spec-driven dashboard renderer, and typed API hooks.

**Architecture:** A new standalone Lambda (`collector.analytics_handler.lambda_handler`, sharing the one collector zip but with its own least-privilege role: Athena + Glue read + S3 read on `gold/`/`bronze/ops/`/`bronze/events/`/`athena-results/`) is wired to five admin-authorized API Gateway routes `GET /v1/analytics/{triage,taste,funnel,playback,ops}` (spec §10.1). The **API XHR contour is the `/v1/*` prefix** — a pure API prefix with no SPA-route collision, registered **once** in CloudFront `api_gw_pure_path_patterns` (`infra/frontend.tf`) and the Vite dev-proxy `BACKEND_ONLY_PREFIXES` (`frontend/vite.config.ts`); without that registration the browser `fetch('/v1/analytics/...')` falls through to the S3 SPA shell and never reaches API Gateway (spec §2 "SPA→API delivery", §5.1 step 4, §10.1). The **browser page** stays at `/admin/analytics` under the existing `requireAdmin` loader; `/admin/*` is already in CloudFront `api_gw_spa_aware_path_patterns` and the Vite `SPA_AWARE_PREFIXES`, so the deep-link still returns the SPA shell — only the new `/v1` prefix needs adding. Each route maps to one or more fixed SQL templates bound by Athena `ExecutionParameters` (date range only; never raw client SQL), with `ResultReuseByAgeConfiguration` + a warm-Lambda `lru_cache`. The SPA renders one generic `AnalyticsDashboard` (multi-panel: chart + table per named query, plus ops freshness), fed by a typed `useAnalytics` hook.

**Tech Stack:** Python 3.12 (boto3 Athena), pytest; Terraform; React 19 + Mantine 9 + `@mantine/charts` (pinned to the installed `@mantine/core` version, peer `recharts >=3.2.1`) + `@tanstack/react-query`; vitest/jsdom (run via the `pnpm test` project script, `NODE_OPTIONS=--no-experimental-webstorage`); OpenAPI 3.1 generator + `openapi-typescript`.

**Spec:** docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md (§10 serving, §11 dashboards, §13 IAM/security, §17 rollout step 5)

> **Scope notes (deliberate):** Phase-1 dashboards are **date-range-only** — §10.1 "filters" beyond `from`/`to` are descoped (no §11 dashboard names a non-date client filter; add a constrained, `ExecutionParameters`-bound filter param when one does). The playback **seek heatmap** ships as a representative 1-D slice (most-seeked tracks, `fact_seek × dim_track`); the full 2-D from/to-bucket heatmap is a tracked follow-up. **Three §11 sub-metrics ship as tracked follow-ups, each tagged `// ponytail:` at its `_ROUTE_QUERIES` entry:** D2's **BPM histogram** and **category-mix-by-genre/BPM/key** breakdown (the taste route ships label affinity instead), and D4's **listen-through distribution** (the playback route ships a median listen ratio instead). Gold/bronze **column names in the SQL templates are representative** (`// ponytail:`) and must be reconciled against the actual Increment-3 star schema when those tables land — the per-template column dependencies are enumerated in the `_ROUTE_QUERIES` header checklist so Increment 3 has a concrete conformance list. The lake bucket / Glue DB / Athena workgroup / gold+bronze tables are created by Increments 2–4 and only **referenced by name** here; `terraform apply` of this increment succeeds once those exist.

---

## File structure

**Created**
- `src/collector/analytics_handler.py` — standalone `lambda_handler`: admin gate on the authorizer context, `/v1/analytics/{dashboard}` route resolution, route→pre-written parameterized Athena queries (one or more named queries per dashboard for the §11 cross-fact metrics), `ResultReuseByAgeConfiguration` + warm-Lambda `lru_cache`, JSON response, ops freshness post-processing.
- `tests/unit/test_analytics_handler.py` — admin enforcement, route resolution, param validation, query building (pre-written only, no raw SQL, every §11 headline metric has a query, per-tenant join present), handler happy path, result-reuse, lru_cache, ops freshness, 403/400/404.
- `infra/analytics_routes.tf` — `aws_lambda_function.analytics` (shared zip) + dedicated role/policy (Athena + Glue read + S3 gold/ops/events/athena-results) + integration + permission + log group + 5 JWT-authorized `GET /v1/analytics/*` routes + analytics-scoped variables.
- `frontend/src/features/admin/hooks/useAnalytics.ts` — one parametrized typed `useQuery` hook over the 5 `/v1/analytics/*` routes.
- `frontend/src/features/admin/lib/dashboards.ts` — the 5 multi-panel `DashboardSpec`s (§11).
- `frontend/src/features/admin/components/AnalyticsDashboard.tsx` — generic loading/error/multi-panel chart+table/freshness renderer.
- `frontend/src/features/admin/routes/AdminAnalyticsPage.tsx` — date-range header + maps specs → dashboards.
- `frontend/src/features/admin/hooks/__tests__/useAnalytics.test.tsx` — hook URL/queryKey/data/error.
- `frontend/src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx` — panel table render + error + ops freshness.
- `frontend/src/routes/__tests__/adminAnalyticsRoute.test.ts` — structural admin-gate coverage (router import).

**Modified**
- `scripts/generate_openapi.py` — add `ANALYTICS_PARAMS`, `ANALYTICS_RESULT`, `_analytics_route`, 5 ROUTES entries (`/v1/analytics/*`), register `AnalyticsResult` schema.
- `docs/api/openapi.yaml` — regenerated.
- `frontend/src/api/schema.d.ts` — regenerated (CI gate).
- **`infra/frontend.tf`** — register the `/v1/*` pure API prefix in `api_gw_pure_path_patterns` (THE BLOCKER fix — without it CloudFront serves the SPA shell for `/v1/analytics/*`).
- **`frontend/vite.config.ts`** — register the `/v1` prefix in `BACKEND_ONLY_PREFIXES` (THE BLOCKER fix — without it the dev proxy serves the SPA shell for `/v1/analytics/*`).
- `frontend/package.json` / `frontend/pnpm-lock.yaml` — add `@mantine/charts` (pinned to installed `@mantine/core`) + `recharts` peer.
- `frontend/src/main.tsx` — import `@mantine/charts/styles.css`.
- `frontend/src/routes/router.tsx` — add `analytics` child under the admin subtree.
- `frontend/src/features/admin/routes/AdminLayout.tsx` — add Analytics tab.
- `frontend/src/i18n/en.json` — `admin.analytics.*` + `admin.tabs.analytics`.

> **Note on the two registration files:** `infra/frontend.tf` + `frontend/vite.config.ts` are listed and modified **on purpose** (MUST-FIX #1). The SPA *page* `/admin/analytics` is already delivered by the existing `/admin/*` spa-aware patterns, but the dashboard *XHRs* go to `/v1/analytics/*`, a brand-new prefix that exists in neither file. If Increment 2 (telemetry) already added `/v1`, Task 5's grep check finds it and the edits are no-ops — but the registration MUST be verified here, because all five dashboards 404-to-SPA-shell at runtime without it (unit tests mock `api()` and would still pass — that is exactly the trap this task closes).

---

## Tasks

### Task 1: Backend — admin gate, route resolution, param validation, query building (pure, no I/O)

**Files:**
- Create `src/collector/analytics_handler.py` (validation + query-building half only)
- Test: `tests/unit/test_analytics_handler.py`

Worktree note: the venv lives at the MAIN repo root. Use the absolute pytest binary `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`; it runs with cwd at the worktree root where `pytest.ini` sets `PYTHONPATH=src`.

- [ ] **Step 1: Write the failing test** (`tests/unit/test_analytics_handler.py`)
```python
from __future__ import annotations

import pytest

from collector import analytics_handler as ah


def _event(route: str, *, is_admin, qs=None):
    authorizer = None
    if is_admin is not None:
        authorizer = {"lambda": {"user_id": "u1", "session_id": "s1", "is_admin": is_admin}}
    return {
        "version": "2.0",
        "rawPath": route,
        "requestContext": {
            "requestId": "req1",
            "routeKey": f"GET {route}",
            **({"authorizer": authorizer} if authorizer is not None else {}),
        },
        "headers": {"x-correlation-id": "cid1"},
        "queryStringParameters": qs,
    }


# ── admin gate (§10.1, §13: is_admin lives under authorizer.lambda) ──
def test_require_admin_raises_when_no_authorizer():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._require_admin(_event("/v1/analytics/triage", is_admin=None))
    assert exc.value.status_code == 403
    assert exc.value.error_code == "admin_required"


def test_require_admin_raises_when_non_admin():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._require_admin(_event("/v1/analytics/triage", is_admin=False))
    assert exc.value.status_code == 403


def test_require_admin_returns_user_id_for_admin():
    assert ah._require_admin(_event("/v1/analytics/triage", is_admin=True)) == "u1"


# ── route resolution ────────────────────────────────────────────────
def test_route_name_extracts_dashboard():
    assert ah._route_name(_event("/v1/analytics/playback", is_admin=True)) == "playback"


def test_route_name_rejects_unknown_dashboard():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._route_name(_event("/v1/analytics/evil", is_admin=True))
    assert exc.value.status_code == 404


# ── param validation ────────────────────────────────────────────────
@pytest.mark.parametrize("qs", [
    None,
    {"from": "not-a-date", "to": "2026-02-01"},
    {"from": "2026-01-01", "to": "2026/02/01"},
    {"from": "2026-02-01", "to": "2026-01-01"},  # from > to
    {"to": "2026-02-01"},                          # missing from
])
def test_validate_params_rejects_bad_input(qs):
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._validate_params(qs)
    assert exc.value.status_code == 400
    assert exc.value.error_code == "invalid_params"


def test_validate_params_accepts_iso_range():
    assert ah._validate_params({"from": "2026-01-01", "to": "2026-02-01"}) == (
        "2026-01-01", "2026-02-01",
    )


# ── query building: pre-written only, params bound, no raw SQL ───────
def test_build_queries_uses_only_prewritten_templates():
    built = ah.build_queries("triage", "2026-01-01", "2026-02-01")
    sql, params = built["rows"]
    assert sql == ah._ROUTE_QUERIES["triage"]["rows"]  # identical to template
    assert params == ["2026-01-01", "2026-02-01"]


def test_build_queries_never_interpolates_client_values():
    sql, _ = ah.build_queries("taste", "2026-01-01", "2026-02-01")["rows"]
    assert "2026-01-01" not in sql and "2026-02-01" not in sql
    assert "?" in sql  # positional ExecutionParameters placeholder present


def test_client_sql_param_is_ignored():
    qs = {"from": "2026-01-01", "to": "2026-02-01", "sql": "DROP TABLE dim_user"}
    date_from, date_to = ah._validate_params(qs)
    built = ah.build_queries("triage", date_from, date_to)
    assert "DROP" not in built["rows"][0]


# ── §11 metric coverage: EVERY dashboard's named metrics have a query ─
def test_triage_route_has_undo_query():
    # §11 D1 headline: undo rate from fact_triage_session.undo_rate.
    built = ah.build_queries("triage", "2026-01-01", "2026-02-01")
    assert set(built) == {"rows", "undo"}
    assert "fact_triage_session" in built["undo"][0]


def test_taste_label_affinity_joins_playback():
    # §11 D2: label affinity = categorize-count vs playback skip-rate per label.
    sql = ah.build_queries("taste", "2026-01-01", "2026-02-01")["rows"][0]
    assert "fact_playback" in sql and "skip_rate" in sql


def test_funnel_has_weekly_saturday_week():
    # §11 D3: weekly throughput by Saturday-week + time-between-steps.
    built = ah.build_queries("funnel", "2026-01-01", "2026-02-01")
    assert set(built) == {"rows", "weekly"}
    assert "saturday_week" in built["weekly"][0]
    assert "ms_since_prev" in built["rows"][0]  # time-to-publish hop timing


def test_playback_route_has_correlation_and_seek_queries():
    # §11 D4: listen-ratio vs final-category correlation + fact_seek heatmap slice.
    built = ah.build_queries("playback", "2026-01-01", "2026-02-01")
    assert set(built) == {"rows", "by_category", "seek"}
    assert "fact_track_decision" in built["by_category"][0]
    assert "dim_category" in built["by_category"][0]
    # §2/§11 D4: the correlation join is per-tenant (track_key AND user_key); a
    # track_key-only join would cross-join every user's plays against every user's
    # decision for that track. Assert the user_key predicate is present so the
    # multi-tenant join can never silently regress.
    assert "user_key" in built["by_category"][0]
    assert "fact_seek" in built["seek"][0]


def test_ops_route_has_freshness_query():
    built = ah.build_queries("ops", "2026-01-01", "2026-02-01")
    assert set(built) == {"rows", "freshness"}


def test_ops_latency_has_p50_and_p95():
    # §11 D5: latency p50 AND p95.
    sql = ah.build_queries("ops", "2026-01-01", "2026-02-01")["rows"][0]
    assert "0.5" in sql and "0.95" in sql
```

- [ ] **Step 2: Run test to verify it fails**
  - Command: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_handler.py -q`
  - Expected: collection error `ModuleNotFoundError: No module named 'collector.analytics_handler'`.

- [ ] **Step 3: Write minimal implementation** (`src/collector/analytics_handler.py`)
```python
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
            "WHERE d.date BETWEEN date(?) AND date(?) "
            "GROUP BY d.date, c.name ORDER BY d.date"
        ),
        # §11 D1 headline: undo rate, sourced from fact_triage_session.undo_rate (§7).
        "undo": (
            "SELECT d.date AS date, avg(s.undo_rate) AS undo_rate "
            "FROM fact_triage_session s "
            "JOIN dim_date d ON s.date_key = d.date_key "
            "WHERE d.date BETWEEN date(?) AND date(?) "
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
            "WHERE d.date BETWEEN date(?) AND date(?) AND f.action <> 'undo' "
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
            "WHERE d.date BETWEEN date(?) AND date(?) "
            "GROUP BY f.step"
        ),
        # §11 D3: weekly throughput by Saturday-week (ADR-0003 — never ISO-week).
        "weekly": (
            "SELECT concat(cast(d.saturday_week_year AS varchar), '-W', "
            "cast(d.saturday_week_number AS varchar)) AS week, "
            "count(DISTINCT f.track_key) AS tracks "
            "FROM fact_funnel_step f "
            "JOIN dim_date d ON f.date_key = d.date_key "
            "WHERE d.date BETWEEN date(?) AND date(?) "
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
            "WHERE d.date BETWEEN date(?) AND date(?) "
            "GROUP BY d.date ORDER BY d.date"
        ),
        # §11 D4: listen-ratio vs final-category correlation
        # (fact_playback -> fact_track_decision -> dim_category). The decision join
        # is by track_key AND user_key: a track is categorized per-user (§2 multi-
        # tenant, one Aurora DB, facts carry user_key), so a track_key-only join
        # would cross-join one user's plays against every other user's
        # categorization of the same track and corrupt the correlation.
        "by_category": (
            "SELECT c.name AS category, "
            "avg(p.listen_through_ratio) AS avg_listen_ratio, count(*) AS plays "
            "FROM fact_playback p "
            "JOIN fact_track_decision f "
            "ON f.track_key = p.track_key AND f.user_key = p.user_key "
            "JOIN dim_category c ON f.category_key = c.category_key "
            "JOIN dim_date d ON p.date_key = d.date_key "
            "WHERE d.date BETWEEN date(?) AND date(?) "
            "GROUP BY c.name ORDER BY plays DESC"
        ),
        # §11 D4: seek heatmap (fact_seek x dim_track). ponytail: representative 1-D
        # slice (most-seeked tracks); full 2-D from/to-bucket heatmap is a follow-up.
        "seek": (
            "SELECT t.title AS track, count(*) AS seeks "
            "FROM fact_seek s "
            "JOIN dim_track t ON s.track_key = t.track_key "
            "JOIN dim_date d ON s.date_key = d.date_key "
            "WHERE d.date BETWEEN date(?) AND date(?) "
            "GROUP BY t.title ORDER BY seeks DESC LIMIT 20"
        ),
    },
    "ops": {
        # §11 D5: enrichment success-rate + latency p50 AND p95 (log-backed bronze_ops).
        "rows": (
            "SELECT o.dt AS dt, o.phase AS phase, "
            "approx_percentile(o.duration_ms, 0.5) AS p50_duration_ms, "
            "approx_percentile(o.duration_ms, 0.95) AS p95_duration_ms, "
            "avg(CASE WHEN o.failed_after IS NULL THEN 1 ELSE 0 END) AS success_rate, "
            "count(*) AS runs "
            "FROM bronze_ops o "
            "WHERE o.dt BETWEEN ? AND ? "
            "GROUP BY o.dt, o.phase ORDER BY o.dt"
        ),
        # §11 D5: pipeline freshness (newest bronze_events dt vs now).
        "freshness": (
            "SELECT max(dt) AS newest_dt FROM bronze_events WHERE dt BETWEEN ? AND ?"
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
    return {name: (sql, [date_from, date_to]) for name, sql in specs.items()}
```

- [ ] **Step 4: Run test to verify it passes**
  - Command: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_handler.py -q`
  - Expected: `20 passed` (16 test functions; `test_validate_params_rejects_bad_input` parametrizes into 5 nodes → 15 + 5 = 20).

- [ ] **Step 5: Commit** — generate the subject+body via the `caveman:caveman-commit` skill on the staged diff (CLAUDE.md forbids hand-written subjects), then commit with a non-indented heredoc:
```bash
git checkout -b feat/analytics-serving
git add src/collector/analytics_handler.py tests/unit/test_analytics_handler.py
git commit -m "$(cat <<'EOF'
feat(analytics): add analytics-api admin gate + parameterized query builder

Pre-written Athena query templates per dashboard (multiple named queries per
route for the §11 cross-fact metrics), bound via positional ExecutionParameters.
Admin enforced on authorizer.lambda.is_admin; date range validated; no raw SQL.
EOF
)"
```
> Use the caveman-commit output verbatim as the subject/body; the block above shows the expected shape only.

---

### Task 2: Backend — Athena execution, result reuse, lru_cache, `lambda_handler`

**Files:**
- Modify `src/collector/analytics_handler.py` (append execution + handler)
- Test: `tests/unit/test_analytics_handler.py` (append handler tests)

- [ ] **Step 1: Write the failing test** (append to `tests/unit/test_analytics_handler.py`)
```python
import json


class _FakeAthena:
    """Records start calls; replays a canned ResultSet (header row + data rows)."""

    def __init__(self, rows_by_call):
        self.rows_by_call = list(rows_by_call)
        self.start_calls = []
        self._i = -1

    def start_query_execution(self, **kwargs):
        self.start_calls.append(kwargs)
        self._i += 1
        return {"QueryExecutionId": f"q{self._i}"}

    def get_query_execution(self, QueryExecutionId):
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}

    def get_query_results(self, QueryExecutionId):
        idx = int(QueryExecutionId[1:])
        header, data = self.rows_by_call[idx]
        rows = [{"Data": [{"VarCharValue": h} for h in header]}]
        for row in data:
            rows.append({"Data": [{"VarCharValue": v} for v in row]})
        return {"ResultSet": {"Rows": rows}}


@pytest.fixture(autouse=True)
def _reset_cache_and_env(monkeypatch):
    monkeypatch.setenv("ATHENA_DATABASE", "clouder_analytics")
    monkeypatch.setenv("ATHENA_WORKGROUP", "beatport-prod-analytics")
    monkeypatch.setenv("ATHENA_OUTPUT_LOCATION", "s3://lake/athena-results/")
    ah._ATHENA_CLIENT = None
    ah._cached_rows.cache_clear()
    yield
    ah._ATHENA_CLIENT = None
    ah._cached_rows.cache_clear()


def test_handler_403_for_non_admin():
    resp = ah.lambda_handler(_event("/v1/analytics/triage", is_admin=False), None)
    assert resp["statusCode"] == 403
    assert json.loads(resp["body"])["error_code"] == "admin_required"


def test_handler_400_for_bad_dates():
    ev = _event("/v1/analytics/triage", is_admin=True, qs={"from": "x", "to": "y"})
    resp = ah.lambda_handler(ev, None)
    assert resp["statusCode"] == 400


def test_handler_200_returns_rows_and_uses_result_reuse():
    fake = _FakeAthena([
        (["date", "decisions"], [["2026-01-02", "5"]]),       # rows query
        (["date", "undo_rate"], [["2026-01-02", "0.10"]]),    # undo query
    ])
    ah._ATHENA_CLIENT = fake
    ev = _event("/v1/analytics/triage", is_admin=True,
                qs={"from": "2026-01-01", "to": "2026-02-01"})
    resp = ah.lambda_handler(ev, None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["rows"] == [{"date": "2026-01-02", "decisions": "5"}]
    assert body["undo"] == [{"date": "2026-01-02", "undo_rate": "0.10"}]
    call = fake.start_calls[0]
    assert call["ExecutionParameters"] == ["2026-01-01", "2026-02-01"]
    assert call["ResultReuseConfiguration"]["ResultReuseByAgeConfiguration"]["Enabled"] is True
    assert call["QueryExecutionContext"]["Database"] == "clouder_analytics"


def test_handler_warm_lambda_lru_cache_skips_second_query():
    fake = _FakeAthena([
        (["date", "decisions"], [["2026-01-02", "5"]]),
        (["date", "undo_rate"], [["2026-01-02", "0.10"]]),
    ])
    ah._ATHENA_CLIENT = fake
    ev = _event("/v1/analytics/triage", is_admin=True,
                qs={"from": "2026-01-01", "to": "2026-02-01"})
    ah.lambda_handler(ev, None)
    n = len(fake.start_calls)            # first load issues one start per named query
    ah.lambda_handler(ev, None)
    assert len(fake.start_calls) == n    # second load fully served from lru_cache


def test_handler_ops_returns_freshness():
    fake = _FakeAthena([
        (["dt", "phase", "p95_duration_ms"], [["2026-01-02", "merge", "120"]]),
        (["newest_dt"], [["2026-01-02"]]),
    ])
    ah._ATHENA_CLIENT = fake
    ev = _event("/v1/analytics/ops", is_admin=True,
                qs={"from": "2026-01-01", "to": "2026-02-01"})
    resp = ah.lambda_handler(ev, None)
    body = json.loads(resp["body"])
    assert body["rows"][0]["phase"] == "merge"
    assert body["freshness"]["newest_dt"] == "2026-01-02"
    assert "lag_hours" in body["freshness"]


def test_handler_404_for_unknown_dashboard():
    resp = ah.lambda_handler(_event("/v1/analytics/evil", is_admin=True,
                                    qs={"from": "2026-01-01", "to": "2026-02-01"}), None)
    assert resp["statusCode"] == 404
```

- [ ] **Step 2: Run test to verify it fails**
  - Command: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_handler.py -q`
  - Expected: failures with `AttributeError: module 'collector.analytics_handler' has no attribute 'lambda_handler'` / `'_cached_rows'` / `'_ATHENA_CLIENT'`.

- [ ] **Step 3: Write minimal implementation** (append to `src/collector/analytics_handler.py` — all imports it needs are already at the top of the module from Task 1)
```python
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
    started = client.start_query_execution(
        QueryString=sql,
        QueryExecutionContext={"Database": os.environ["ATHENA_DATABASE"]},
        WorkGroup=os.environ.get("ATHENA_WORKGROUP", "primary"),
        ResultConfiguration={"OutputLocation": os.environ["ATHENA_OUTPUT_LOCATION"]},
        ExecutionParameters=params,
        ResultReuseConfiguration={
            "ResultReuseByAgeConfiguration": {
                "Enabled": True,
                "MaxAgeInMinutes": reuse_minutes,
            }
        },
    )
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
```
> `log_event(level, message, **fields)` lands the event name under the `message` key (structlog `EventRenamer("message")`, `logging_utils.py:111`) and drops any field not in `ALLOWED_LOG_FIELDS`; `correlation_id`, `status_code`, `error_code` are all allowlisted (`logging_utils.py:14+`). Envelope/query rows are never logged.

- [ ] **Step 4: Run test to verify it passes**
  - Command: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_analytics_handler.py -q`
  - Expected: `26 passed` (Task 1's 20 + 6 handler tests).
  - Full-suite sanity: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q` — stays green (no new failures).

- [ ] **Step 5: Commit** — caveman-commit the staged diff, then:
```bash
git add src/collector/analytics_handler.py tests/unit/test_analytics_handler.py
git commit -m "$(cat <<'EOF'
feat(analytics): run parameterized Athena queries with result reuse + memo

lambda_handler resolves the /v1/analytics dashboard, runs every pre-written
named query via ExecutionParameters with ResultReuseByAgeConfiguration, and
memoizes rows in a warm-Lambda lru_cache. Ops route adds bronze_events freshness.
EOF
)"
```

---

### Task 3: OpenAPI — 5 `/v1/analytics/*` ROUTES + `AnalyticsResult` schema, regenerate openapi.yaml + schema.d.ts

**Files:**
- Modify `scripts/generate_openapi.py` (constants after `COMMON_AUTH_ERRORS` line ~1269; ROUTES insert before the closing `]`; `components.schemas` line ~3894)
- Modify `docs/api/openapi.yaml` (generated)
- Modify `frontend/src/api/schema.d.ts` (generated, CI gate)

The generator already exposes `AUTH`/`ADMIN` (lines 1251–1252), `_make_response(status, description, schema=None)` (1255), `_error(code, description)` (1262), `COMMON_AUTH_ERRORS` (1266); route dicts support `method`/`path`/`auth`/`summary`/`parameters`/`responses` (see the `/admin/coverage` route at line 1526). `"auth": ADMIN` only documents the admin security scheme — it does **not** register the route in the collector handler `_ADMIN_ROUTES` (analytics is a standalone Lambda enforcing admin itself).

- [ ] **Step 1: Confirm the red state**
  - Command: `grep -c "/v1/analytics/" docs/api/openapi.yaml`
  - Expected: `0` (routes not present yet).

- [ ] **Step 2: Add the constants + helper** — after `COMMON_AUTH_ERRORS` (line ~1269):
```python
ANALYTICS_PARAMS = [
    {"name": "from", "in": "query", "required": True,
     "schema": {"type": "string", "format": "date"},
     "description": "Inclusive start date (YYYY-MM-DD)."},
    {"name": "to", "in": "query", "required": True,
     "schema": {"type": "string", "format": "date"},
     "description": "Inclusive end date (YYYY-MM-DD)."},
]

ANALYTICS_RESULT = {
    "type": "object",
    "required": ["rows"],
    "description": "Generic dashboard payload. `rows` is the primary series; routes "
                   "may add further named arrays (one per panel, e.g. `undo`, `weekly`, "
                   "`by_category`, `seek`). `freshness` is present only on the ops route. "
                   "All arrays are schema-on-read objects from the gold star schema.",
    "properties": {
        "rows": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        "freshness": {
            "type": "object",
            "properties": {
                "newest_dt": {"type": ["string", "null"]},
                "lag_hours": {"type": ["number", "null"]},
            },
        },
        "correlation_id": {"type": "string"},
    },
    # Per-route panel arrays (undo/weekly/by_category/seek) are returned dynamically;
    # allow them so the typed client gets an index signature rather than a strict miss.
    "additionalProperties": True,
}


def _analytics_route(name: str, summary: str, description: str) -> dict:
    return {
        "method": "get",
        "path": f"/v1/analytics/{name}",
        "auth": ADMIN,
        "summary": summary,
        "description": description,
        "parameters": ANALYTICS_PARAMS,
        "responses": {
            "200": _make_response(200, summary,
                                  {"$ref": "#/components/schemas/AnalyticsResult"}),
            "400": _error(400, "from/to must be YYYY-MM-DD dates."),
            "404": _error(404, "Unknown dashboard."),
            "502": _error(502, "Athena query failed."),
            **COMMON_AUTH_ERRORS,
            "403": _error(403, "admin_required."),
        },
    }
```

- [ ] **Step 3: Insert the 5 ROUTES entries** — immediately before the closing `]` of `ROUTES`, after the last route's `},`:
```python
    # ── analytics dashboards (§10/§11), standalone analytics-api, admin-only ──
    # XHR path is /v1/analytics/* (the /v1 prefix is registered in CloudFront +
    # Vite dev proxy, Task 5); the browser page is /admin/analytics.
    _analytics_route("triage", "Triage efficiency dashboard data.",
        "Median decision time + throughput per category over time, plus undo rate "
        "(gold fact_track_decision + fact_triage_session). Pre-written parameterized Athena queries."),
    _analytics_route("taste", "Taste profile dashboard data.",
        "Label affinity: categorize count + BPM + playback skip-rate per label "
        "(gold fact_track_decision x dim_track/dim_label x fact_playback)."),
    _analytics_route("funnel", "Funnel dashboard data.",
        "Lifecycle drop-off + time-between-steps and weekly throughput by Saturday-week "
        "(gold fact_funnel_step x dim_date)."),
    _analytics_route("playback", "Playback dashboard data.",
        "Listen-through + skip-rate, listen-ratio-by-final-category correlation (joined per "
        "track_key+user_key), and a most-seeked-tracks slice "
        "(gold fact_playback x fact_track_decision/dim_category, fact_seek x dim_track)."),
    _analytics_route("ops", "Ops/pipeline health dashboard data.",
        "Enrichment success + latency p50/p95 from bronze_ops plus bronze_events freshness lag."),
```

- [ ] **Step 4: Register the response schema** — in `components.schemas` (line ~3894), after `"PlaylistCommentsResponse": PLAYLIST_COMMENTS_RESPONSE,`:
```python
                "AnalyticsResult": ANALYTICS_RESULT,
```

- [ ] **Step 5: Regenerate both artifacts and verify**
  - Commands:
    ```bash
    PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py
    grep -c "/v1/analytics/" docs/api/openapi.yaml
    pnpm -C frontend run api:types
    pnpm -C frontend run typecheck
    ```
  - Expected: generator prints the output path; `grep` returns `5`; `api:types` rewrites `frontend/src/api/schema.d.ts` with the `"/v1/analytics/triage"` (…etc) paths and the `AnalyticsResult` component; `typecheck` exits 0.

- [ ] **Step 6: Commit** — caveman-commit, then:
```bash
git add scripts/generate_openapi.py docs/api/openapi.yaml frontend/src/api/schema.d.ts
git commit -m "$(cat <<'EOF'
feat(api): register 5 admin analytics dashboard routes

Add GET /v1/analytics/{triage,taste,funnel,playback,ops} with a shared
AnalyticsResult schema (400/403/404/502 + auth errors); regenerate openapi.yaml
and frontend schema.d.ts.
EOF
)"
```

---

### Task 4: Infra — `infra/analytics_routes.tf` (standalone Lambda, dedicated role, 5 admin-gated routes)

**Files:**
- Create `infra/analytics_routes.tf`

Mirrors the standalone `auth_authorizer`/`curation` wiring (own role + integration + permission + routes). Confirmed references that already exist: `local.name_prefix` (`main.tf:2`), `local.lambda_zip_file` (`main.tf:31`), `data.aws_caller_identity.current` (`main.tf:37`), `var.aws_region` (`variables.tf:13`), `data.aws_iam_policy_document.lambda_assume` (`iam.tf:1`), `aws_apigatewayv2_api.collector` (`api_gateway.tf:1`), `aws_apigatewayv2_authorizer.jwt` (`auth.tf:156`). The lake bucket / Glue DB / Athena workgroup are created in Increments 2–4 and referenced by name via scoped variables. Routes are `GET /v1/analytics/*`; the matching CloudFront/Vite `/v1` delivery is added in Task 5.

- [ ] **Step 1: Write the file** (`infra/analytics_routes.tf`)
```hcl
# ── analytics-api Lambda (§10 serving) ──────────────────────────────
# Standalone function, dedicated least-privilege role (§13). Shares the one
# collector zip; entry point collector.analytics_handler.lambda_handler.
# Lake bucket / Glue DB / Athena workgroup are provisioned in Increments 2-4
# and referenced here by name. Routes are GET /v1/analytics/* (delivery wired
# in infra/frontend.tf + frontend/vite.config.ts, Task 5).

variable "analytics_lake_bucket" {
  type    = string
  default = "beatport-prod-analytics-lake"
}

variable "analytics_glue_database" {
  type    = string
  default = "clouder_analytics"
}

variable "athena_workgroup" {
  type    = string
  default = "beatport-prod-analytics"
}

variable "analytics_lambda_timeout_seconds" {
  type    = number
  default = 30
}

variable "analytics_lambda_memory_mb" {
  type    = number
  default = 256
}

resource "aws_cloudwatch_log_group" "analytics" {
  name              = "/aws/lambda/${local.name_prefix}-analytics-api"
  retention_in_days = 14
}

resource "aws_iam_role" "analytics_api" {
  name               = "${local.name_prefix}-analytics-api-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "analytics_api" {
  statement {
    sid       = "AllowCloudWatchLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.analytics.arn}:*"]
  }

  statement {
    sid    = "AthenaQuery"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
    ]
    resources = ["arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup}"]
  }

  statement {
    sid    = "GlueReadCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${var.analytics_glue_database}",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.analytics_glue_database}/*",
    ]
  }

  statement {
    sid    = "S3ReadGoldAndOps"
    effect = "Allow"
    actions = ["s3:GetObject", "s3:ListBucket"]
    resources = [
      "arn:aws:s3:::${var.analytics_lake_bucket}",
      "arn:aws:s3:::${var.analytics_lake_bucket}/gold/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/bronze/ops/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/bronze/events/*",
      "arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*",
    ]
  }

  statement {
    sid       = "S3WriteAthenaResults"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["arn:aws:s3:::${var.analytics_lake_bucket}/athena-results/*"]
  }
}

resource "aws_iam_role_policy" "analytics_api" {
  name   = "${local.name_prefix}-analytics-api-policy"
  role   = aws_iam_role.analytics_api.id
  policy = data.aws_iam_policy_document.analytics_api.json
}

resource "aws_lambda_function" "analytics" {
  function_name = "${local.name_prefix}-analytics-api"
  role          = aws_iam_role.analytics_api.arn
  runtime       = "python3.12"
  handler       = "collector.analytics_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.analytics_lambda_timeout_seconds
  memory_size   = var.analytics_lambda_memory_mb

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      ATHENA_DATABASE                = var.analytics_glue_database
      ATHENA_WORKGROUP               = var.athena_workgroup
      ATHENA_OUTPUT_LOCATION         = "s3://${var.analytics_lake_bucket}/athena-results/"
      ANALYTICS_RESULT_REUSE_MINUTES = "60"
      LOG_LEVEL                      = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.analytics]
}

resource "aws_lambda_permission" "analytics_apigw" {
  statement_id  = "AllowExecutionFromApiGatewayAnalytics"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.analytics.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

resource "aws_apigatewayv2_integration" "analytics" {
  api_id                 = aws_apigatewayv2_api.collector.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.analytics.invoke_arn
  payload_format_version = "2.0"
}

locals {
  analytics_routes = [
    "GET /v1/analytics/triage",
    "GET /v1/analytics/taste",
    "GET /v1/analytics/funnel",
    "GET /v1/analytics/playback",
    "GET /v1/analytics/ops",
  ]
}

resource "aws_apigatewayv2_route" "analytics" {
  for_each = toset(local.analytics_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.analytics.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```
> Admin is enforced inside the Lambda (§10.1) — these routes carry only the shared JWT authorizer (`CUSTOM`), and are **not** added to the collector handler `_ADMIN_ROUTES`. The dedicated `analytics_api` role grants **only** Athena + Glue read + S3 read on the lake (and `PutObject` on `athena-results/`) — the collector role is never touched (MUST-FIX: no inherited collector permissions).

- [ ] **Step 2: Validate**
  - Commands:
    ```bash
    terraform -chdir=infra fmt
    terraform -chdir=infra init -backend=false
    terraform -chdir=infra validate
    ```
  - Expected: `Success! The configuration is valid.` (Red→green = missing-file → valid-config.) If a referenced symbol resolves under a different name in this repo, correct the reference and re-run.

- [ ] **Step 3: Commit** — caveman-commit, then:
```bash
git add infra/analytics_routes.tf
git commit -m "$(cat <<'EOF'
feat(infra): add analytics-api Lambda, role and 5 admin routes

Standalone function on the shared zip with a dedicated least-privilege role
(Athena + Glue read + S3 read on gold/ops/events/athena-results), own
integration and five JWT-authorized GET /v1/analytics/* routes; admin enforced
in the handler, collector role untouched.
EOF
)"
```

---

### Task 5: Infra/Frontend — register the `/v1` API prefix (CloudFront + Vite dev proxy) — THE BLOCKER

**Files:**
- Modify `infra/frontend.tf` (`api_gw_pure_path_patterns`, lines ~128–139)
- Modify `frontend/vite.config.ts` (`BACKEND_ONLY_PREFIXES`, lines 14–27)

`/v1/*` is a pure API prefix (no SPA-route collision), so it belongs in CloudFront `api_gw_pure_path_patterns` and Vite `BACKEND_ONLY_PREFIXES` (NOT the spa-aware lists). Without this, the browser `fetch('/v1/analytics/...')` returns the S3 SPA shell — every dashboard fails at runtime even though the jsdom unit tests (which mock `api()`) pass. This registration is shared with Increment 2 telemetry; the grep checks below make the edits idempotent if Increment 2 already added it.

- [ ] **Step 1: Confirm current state**
  - Commands:
    ```bash
    grep -n '"/v1' infra/frontend.tf || echo "frontend.tf: /v1 ABSENT"
    grep -n "'/v1'" frontend/vite.config.ts || echo "vite.config.ts: /v1 ABSENT"
    ```
  - Expected (in this increment, if Increment 2 hasn't landed): both print `ABSENT`. If either already lists `/v1`, leave that file unchanged and skip its edit below.

- [ ] **Step 2: Register `/v1/*` in CloudFront** — in `infra/frontend.tf`, add `"/v1/*"` to the `api_gw_pure_path_patterns` list (e.g. directly after `"/tags*",`):
```hcl
    "/tags*",
    "/v1/*",
```

- [ ] **Step 3: Register `/v1` in the Vite dev proxy** — in `frontend/vite.config.ts`, add `'/v1'` to `BACKEND_ONLY_PREFIXES` (after `'/collect_bp_releases',`):
```ts
  '/collect_bp_releases',
  '/v1',
```

- [ ] **Step 4: Verify**
  - Commands:
    ```bash
    grep -n '"/v1/\*"' infra/frontend.tf
    grep -n "'/v1'" frontend/vite.config.ts
    terraform -chdir=infra fmt
    terraform -chdir=infra validate
    pnpm -C frontend run typecheck
    ```
  - Expected: both greps match the values Step 2/Step 3 inserted (`"/v1/*"` in `infra/frontend.tf`, `'/v1'` in `vite.config.ts`); `terraform validate` → `Success!`; `typecheck` exits 0. (The CloudFront grep regex `"/v1/\*"` is the literal `"/v1/*"` — note the slash before the escaped star — matching the inserted pattern exactly; a slash-less `"/v1*"` would NOT match and is the wrong pattern.) This is declarative delivery config consumed by CloudFront/Vite — there is no unit-testable logic; the true end-to-end proof is the §14 integration smoke: a dev build `fetch('/v1/analytics/triage')` reaching API Gateway instead of the SPA shell.

- [ ] **Step 5: Commit** — caveman-commit, then:
```bash
git add infra/frontend.tf frontend/vite.config.ts
git commit -m "$(cat <<'EOF'
feat(infra): route the /v1 API prefix to API Gateway

Add /v1/* to CloudFront api_gw_pure_path_patterns and the Vite dev-proxy
BACKEND_ONLY_PREFIXES so SPA fetch('/v1/analytics/...') reaches the gateway
instead of falling through to the SPA shell.
EOF
)"
```

---

### Task 6: Frontend — charts dep + typed `useAnalytics` hook + dashboard specs

**Files:**
- Modify `frontend/package.json` + `frontend/pnpm-lock.yaml` (add deps)
- Modify `frontend/src/main.tsx` (charts CSS)
- Create `frontend/src/features/admin/hooks/useAnalytics.ts`
- Create `frontend/src/features/admin/lib/dashboards.ts`
- Test: `frontend/src/features/admin/hooks/__tests__/useAnalytics.test.tsx`

Frontend per-file vitest runs go through the **project `test` script** (`pnpm -C frontend test <path>`) so `NODE_OPTIONS=--no-experimental-webstorage` is preserved — never raw `vitest run`.

- [ ] **Step 1: Add the charts dependency, pinned to the installed Mantine**
  - `@mantine/charts@9.1.1` peers `@mantine/core` at the **exact** version `9.1.1` and `recharts >=3.2.1` (verified in recon; installed `@mantine/core` is `^9.1.1`). Pin charts to whatever core actually resolves to, and add the recharts peer:
    ```bash
    CORE_VER=$(cd frontend && node -p "require('@mantine/core/package.json').version")
    pnpm -C frontend add @mantine/charts@"$CORE_VER" recharts@^3.2.1
    pnpm -C frontend ls @mantine/charts recharts
    ```
  - Expected: `@mantine/charts` version equals the installed `@mantine/core` version; `recharts` resolves to a `3.x` (≥3.2.1, e.g. 3.9.0); `pnpm ls` shows no `UNMET PEER DEPENDENCY`. (Typecheck in Task 8 reconfirms.)

- [ ] **Step 2: Write the failing hook test** (`frontend/src/features/admin/hooks/__tests__/useAnalytics.test.tsx`)
```tsx
import { describe, it, expect, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useAnalytics } from '../useAnalytics';

const apiMock = vi.hoisted(() => vi.fn());
vi.mock('../../../../api/client', () => ({ api: (...a: unknown[]) => apiMock(...a) }));

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useAnalytics', () => {
  it('fetches the /v1 dashboard route with the date range and returns rows', async () => {
    apiMock.mockResolvedValue({ rows: [{ date: '2026-01-02', decisions: 5 }] });
    const { result } = renderHook(
      () => useAnalytics('triage', { from: '2026-01-01', to: '2026-02-01' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiMock).toHaveBeenCalledWith(
      '/v1/analytics/triage?from=2026-01-01&to=2026-02-01',
    );
    expect(result.current.data?.rows[0]).toMatchObject({ decisions: 5 });
  });

  it('surfaces error state', async () => {
    apiMock.mockRejectedValue(new Error('boom'));
    const { result } = renderHook(
      () => useAnalytics('ops', { from: '2026-01-01', to: '2026-02-01' }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

- [ ] **Step 3: Run test to verify it fails**
  - Command: `pnpm -C frontend test src/features/admin/hooks/__tests__/useAnalytics.test.tsx`
  - Expected: fails to resolve `../useAnalytics` (module not found).

- [ ] **Step 4: Write the hook + specs**
  - `frontend/src/features/admin/hooks/useAnalytics.ts`:
```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { paths } from '../../../api/schema';

export type AnalyticsResult =
  paths['/v1/analytics/triage']['get']['responses'][200]['content']['application/json'];

export type DashboardName = 'triage' | 'taste' | 'funnel' | 'playback' | 'ops';

export interface AnalyticsRange {
  from: string;
  to: string;
}

export function useAnalytics(name: DashboardName, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', name, range.from, range.to],
    queryFn: () =>
      api<AnalyticsResult>(
        `/v1/analytics/${name}?from=${range.from}&to=${range.to}`,
      ),
    staleTime: 60_000,
  });
}
```
  - `frontend/src/features/admin/lib/dashboards.ts`:
```ts
import type { DashboardName } from '../hooks/useAnalytics';

export type ChartKind = 'line' | 'bar';

// One panel = one named query in the route payload (its `dataKey`), rendered as
// a chart + table. A dashboard can have several panels for the §11 cross-fact metrics.
export interface PanelSpec {
  dataKey: string;
  titleKey: string;
  chart: ChartKind;
  xKey: string;
  series: { key: string; labelKey: string }[];
}

export interface DashboardSpec {
  name: DashboardName;
  titleKey: string;
  panels: PanelSpec[];
  showFreshness?: boolean;
}

export const DASHBOARDS: DashboardSpec[] = [
  {
    name: 'triage',
    titleKey: 'admin.analytics.triage.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.triage.median', chart: 'line', xKey: 'date',
        series: [{ key: 'median_decision_ms', labelKey: 'admin.analytics.triage.median' }] },
      { dataKey: 'undo', titleKey: 'admin.analytics.triage.undo', chart: 'line', xKey: 'date',
        series: [{ key: 'undo_rate', labelKey: 'admin.analytics.triage.undo' }] },
    ],
  },
  {
    name: 'taste',
    titleKey: 'admin.analytics.taste.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.taste.affinity', chart: 'bar', xKey: 'label',
        series: [
          { key: 'categorized', labelKey: 'admin.analytics.taste.categorized' },
          { key: 'skip_rate', labelKey: 'admin.analytics.taste.skip_rate' },
        ] },
    ],
  },
  {
    name: 'funnel',
    titleKey: 'admin.analytics.funnel.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.funnel.steps', chart: 'bar', xKey: 'step',
        series: [{ key: 'tracks', labelKey: 'admin.analytics.funnel.tracks' }] },
      { dataKey: 'weekly', titleKey: 'admin.analytics.funnel.weekly', chart: 'bar', xKey: 'week',
        series: [{ key: 'tracks', labelKey: 'admin.analytics.funnel.tracks' }] },
    ],
  },
  {
    name: 'playback',
    titleKey: 'admin.analytics.playback.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.playback.listen', chart: 'line', xKey: 'date',
        series: [
          { key: 'median_listen_ratio', labelKey: 'admin.analytics.playback.listen' },
          { key: 'skip_rate', labelKey: 'admin.analytics.playback.skip_rate' },
        ] },
      { dataKey: 'by_category', titleKey: 'admin.analytics.playback.by_category', chart: 'bar', xKey: 'category',
        series: [{ key: 'avg_listen_ratio', labelKey: 'admin.analytics.playback.listen' }] },
      { dataKey: 'seek', titleKey: 'admin.analytics.playback.seek', chart: 'bar', xKey: 'track',
        series: [{ key: 'seeks', labelKey: 'admin.analytics.playback.seeks' }] },
    ],
  },
  {
    name: 'ops',
    titleKey: 'admin.analytics.ops.title',
    panels: [
      { dataKey: 'rows', titleKey: 'admin.analytics.ops.latency', chart: 'bar', xKey: 'phase',
        series: [
          { key: 'p50_duration_ms', labelKey: 'admin.analytics.ops.p50' },
          { key: 'p95_duration_ms', labelKey: 'admin.analytics.ops.p95' },
        ] },
    ],
    showFreshness: true,
  },
];
```

- [ ] **Step 5: Run test to verify it passes + add charts CSS**
  - Edit `frontend/src/main.tsx`: add `import '@mantine/charts/styles.css';` directly after line 12 (`import '@mantine/notifications/styles.css';`).
  - Command: `pnpm -C frontend test src/features/admin/hooks/__tests__/useAnalytics.test.tsx`
  - Expected: `2 passed`.

- [ ] **Step 6: Commit** — caveman-commit, then:
```bash
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/main.tsx frontend/src/features/admin/hooks/useAnalytics.ts frontend/src/features/admin/lib/dashboards.ts frontend/src/features/admin/hooks/__tests__/useAnalytics.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): typed useAnalytics hook + multi-panel dashboard specs

Add @mantine/charts (pinned to installed @mantine/core) + recharts, a
parametrized useAnalytics query hook typed from schema.d.ts hitting
/v1/analytics/*, and the five §11 dashboard specs with per-query panels.
EOF
)"
```

---

### Task 7: Frontend — generic `AnalyticsDashboard` + `AdminAnalyticsPage` + i18n

**Files:**
- Create `frontend/src/features/admin/components/AnalyticsDashboard.tsx`
- Create `frontend/src/features/admin/routes/AdminAnalyticsPage.tsx`
- Modify `frontend/src/i18n/en.json`
- Test: `frontend/src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx`

- [ ] **Step 1: Write the failing component test** (`frontend/src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx`)
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { AnalyticsDashboard } from '../AnalyticsDashboard';
import type { DashboardSpec } from '../../lib/dashboards';

// jsdom has no layout, so stub the chart lib (ResponsiveContainer needs a size).
vi.mock('@mantine/charts', () => ({
  LineChart: () => <div data-testid="line-chart" />,
  BarChart: () => <div data-testid="bar-chart" />,
}));

const useAnalyticsMock = vi.hoisted(() => vi.fn());
vi.mock('../../hooks/useAnalytics', () => ({ useAnalytics: () => useAnalyticsMock() }));

const range = { from: '2026-01-01', to: '2026-02-01' };

function render1(spec: DashboardSpec) {
  render(
    <MantineProvider>
      <AnalyticsDashboard spec={spec} range={range} />
    </MantineProvider>,
  );
}

const triageSpec: DashboardSpec = {
  name: 'triage',
  titleKey: 'admin.analytics.triage.title',
  panels: [
    { dataKey: 'rows', titleKey: 'admin.analytics.triage.median', chart: 'line', xKey: 'date',
      series: [{ key: 'median_decision_ms', labelKey: 'admin.analytics.triage.median' }] },
  ],
};

describe('AnalyticsDashboard', () => {
  it('renders a panel as a table once loaded', () => {
    useAnalyticsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: { rows: [{ date: '2026-01-02', median_decision_ms: 900 }] },
    });
    render1(triageSpec);
    expect(screen.getByTestId('dashboard-triage')).toBeInTheDocument();
    expect(screen.getByText('2026-01-02')).toBeInTheDocument();
    expect(screen.getByText('900')).toBeInTheDocument();
  });

  it('shows error state', () => {
    useAnalyticsMock.mockReturnValue({ isLoading: false, isError: true, data: undefined });
    render1(triageSpec);
    expect(screen.getByText(/failed/i)).toBeInTheDocument();
  });

  it('renders freshness on the ops dashboard', () => {
    useAnalyticsMock.mockReturnValue({
      isLoading: false, isError: false,
      data: {
        rows: [{ phase: 'merge', p95_duration_ms: 120 }],
        freshness: { newest_dt: '2026-01-02', lag_hours: 5 },
      },
    });
    render1({
      name: 'ops',
      titleKey: 'admin.analytics.ops.title',
      panels: [
        { dataKey: 'rows', titleKey: 'admin.analytics.ops.latency', chart: 'bar', xKey: 'phase',
          series: [{ key: 'p95_duration_ms', labelKey: 'admin.analytics.ops.p95' }] },
      ],
      showFreshness: true,
    });
    expect(screen.getByText(/2026-01-02/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**
  - Command: `pnpm -C frontend test src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx`
  - Expected: cannot resolve `../AnalyticsDashboard`.

- [ ] **Step 3: Write the component + page + i18n**
  - `frontend/src/features/admin/components/AnalyticsDashboard.tsx`:
```tsx
import { Alert, Card, Group, Loader, Stack, Table, Text, Title } from '@mantine/core';
import { BarChart, LineChart } from '@mantine/charts';
import { useTranslation } from 'react-i18next';
import { useAnalytics, type AnalyticsRange } from '../hooks/useAnalytics';
import type { DashboardSpec, PanelSpec } from '../lib/dashboards';

const COLORS = ['indigo.6', 'teal.6', 'grape.6'];

type Row = Record<string, unknown>;
type Freshness = { newest_dt?: string | null; lag_hours?: number | null };

function PanelView({ panel, data }: { panel: PanelSpec; data: Record<string, unknown> | undefined }) {
  const { t } = useTranslation();
  const rows = (data?.[panel.dataKey] as Row[] | undefined) ?? [];
  const cols = rows.length > 0 ? Object.keys(rows[0]) : [];
  const series = panel.series.map((s, i) => ({
    name: s.key,
    label: t(s.labelKey),
    color: COLORS[i % COLORS.length],
  }));

  if (rows.length === 0) {
    return (
      <Stack gap="xs" data-testid={`panel-${panel.dataKey}`}>
        <Text fw={600} size="sm">{t(panel.titleKey)}</Text>
        <Text c="dimmed" size="sm">{t('admin.analytics.empty')}</Text>
      </Stack>
    );
  }

  return (
    <Stack gap="xs" data-testid={`panel-${panel.dataKey}`}>
      <Text fw={600} size="sm">{t(panel.titleKey)}</Text>
      {panel.chart === 'line' ? (
        <LineChart h={200} data={rows} dataKey={panel.xKey} series={series} withLegend />
      ) : (
        <BarChart h={200} data={rows} dataKey={panel.xKey} series={series} withLegend />
      )}
      <Table striped withTableBorder>
        <Table.Thead>
          <Table.Tr>{cols.map((c) => (<Table.Th key={c}>{c}</Table.Th>))}</Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((r, i) => (
            <Table.Tr key={i}>
              {cols.map((c) => (<Table.Td key={c}>{String(r[c] ?? '')}</Table.Td>))}
            </Table.Tr>
          ))}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

export function AnalyticsDashboard({
  spec,
  range,
}: {
  spec: DashboardSpec;
  range: AnalyticsRange;
}) {
  const { t } = useTranslation();
  const q = useAnalytics(spec.name, range);
  const data = q.data as Record<string, unknown> | undefined;
  const freshness = data?.freshness as Freshness | undefined;

  return (
    <Card withBorder padding="md" data-testid={`dashboard-${spec.name}`}>
      <Stack gap="sm">
        <Group justify="space-between">
          <Title order={4}>{t(spec.titleKey)}</Title>
          {spec.showFreshness && freshness && (
            <Text
              size="sm"
              c={typeof freshness.lag_hours === 'number' && freshness.lag_hours > 36 ? 'red' : 'dimmed'}
            >
              {t('admin.analytics.ops.freshness', {
                dt: freshness.newest_dt ?? '—',
                lag: freshness.lag_hours ?? '—',
              })}
            </Text>
          )}
        </Group>

        {q.isLoading && <Loader size="sm" />}
        {q.isError && <Alert color="red">{t('admin.analytics.load_failed')}</Alert>}
        {!q.isLoading && !q.isError &&
          spec.panels.map((panel) => (
            <PanelView key={panel.dataKey} panel={panel} data={data} />
          ))}
      </Stack>
    </Card>
  );
}
```
  - `frontend/src/features/admin/routes/AdminAnalyticsPage.tsx`:
```tsx
import { Group, Stack } from '@mantine/core';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { PageHeader } from '../../../components/PageHeader';
import { AnalyticsDashboard } from '../components/AnalyticsDashboard';
import { DASHBOARDS } from '../lib/dashboards';

function isoDaysAgo(days: number): string {
  const d = new Date();
  d.setUTCDate(d.getUTCDate() - days);
  return d.toISOString().slice(0, 10);
}

export function AdminAnalyticsPage() {
  const { t } = useTranslation();
  const [from, setFrom] = useState(() => isoDaysAgo(30));
  const [to, setTo] = useState(() => isoDaysAgo(0));
  const range = { from, to };

  return (
    <Stack>
      <PageHeader
        title={t('admin.analytics.title')}
        subtitle={t('admin.analytics.subtitle')}
        actions={
          <Group gap="xs">
            <input aria-label={t('admin.analytics.from')} type="date" value={from}
              onChange={(e) => setFrom(e.target.value)} />
            <input aria-label={t('admin.analytics.to')} type="date" value={to}
              onChange={(e) => setTo(e.target.value)} />
          </Group>
        }
      />
      {DASHBOARDS.map((spec) => (
        <AnalyticsDashboard key={spec.name} spec={spec} range={range} />
      ))}
    </Stack>
  );
}
```
  - `frontend/src/i18n/en.json`: inside the `"admin"` object, add an `"analytics"` block (next to `"coverage"` / `"spotify_not_found"`) and add `"analytics": "Analytics"` to `admin.tabs` (currently lines 773–776):
```jsonc
    "analytics": {
      "title": "Analytics",
      "subtitle": "Curation, taste, funnel, playback and pipeline health.",
      "from": "From",
      "to": "To",
      "load_failed": "Failed to load dashboard.",
      "empty": "No data for this range.",
      "triage": { "title": "Triage efficiency", "median": "Median decision (ms)", "undo": "Undo rate" },
      "taste": { "title": "Taste profile", "affinity": "Label affinity", "categorized": "Categorized", "skip_rate": "Skip rate" },
      "funnel": { "title": "Funnel", "steps": "Lifecycle steps", "tracks": "Tracks", "weekly": "Weekly throughput (Saturday-week)" },
      "playback": { "title": "Playback", "listen": "Median listen ratio", "skip_rate": "Skip rate", "by_category": "Listen ratio by final category", "seek": "Most-seeked tracks", "seeks": "Seeks" },
      "ops": { "title": "Ops / pipeline health", "latency": "Latency", "p50": "p50 latency (ms)", "p95": "p95 latency (ms)", "freshness": "Fresh to {{dt}} ({{lag}}h lag)" }
    },
```
```jsonc
    "tabs": {
      "coverage": "Coverage",
      "spotify_not_found": "Tracks not on Spotify",
      "analytics": "Analytics"
    },
```

- [ ] **Step 4: Run test to verify it passes**
  - Command: `pnpm -C frontend test src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx`
  - Expected: `3 passed`.

- [ ] **Step 5: Commit** — caveman-commit, then:
```bash
git add frontend/src/features/admin/components/AnalyticsDashboard.tsx frontend/src/features/admin/routes/AdminAnalyticsPage.tsx frontend/src/i18n/en.json frontend/src/features/admin/components/__tests__/AnalyticsDashboard.test.tsx
git commit -m "$(cat <<'EOF'
feat(frontend): generic multi-panel AnalyticsDashboard + admin analytics page

One spec-driven dashboard renders a chart + table per named-query panel (and
ops freshness), driven by DASHBOARDS, with a native date-range header and i18n.
EOF
)"
```

---

### Task 8: Frontend — wire `/admin/analytics` route + tab + admin-gate test + full CI gate

**Files:**
- Modify `frontend/src/routes/router.tsx` (admin subtree, lines 117–130)
- Modify `frontend/src/features/admin/routes/AdminLayout.tsx` (`TAB_VALUES` lines 9–17, `TABS` lines 24–32)
- Test: `frontend/src/routes/__tests__/adminAnalyticsRoute.test.ts`

- [ ] **Step 1: Write the failing structural gate test** (`frontend/src/routes/__tests__/adminAnalyticsRoute.test.ts`)
```ts
import { describe, it, expect } from 'vitest';
import { router } from '../router';

interface RNode {
  path?: string;
  loader?: unknown;
  children?: RNode[];
}

function find(nodes: RNode[], path: string): RNode | undefined {
  for (const n of nodes) {
    if (n.path === path) return n;
    if (n.children) {
      const hit = find(n.children, path);
      if (hit) return hit;
    }
  }
  return undefined;
}

describe('/admin/analytics route', () => {
  it('is a child of the requireAdmin-gated admin subtree', () => {
    const admin = find(router.routes as RNode[], 'admin');
    expect(admin).toBeDefined();
    expect(admin?.loader).toBeTruthy(); // requireAdmin gate present (loader tested separately)
    const analytics = admin?.children?.find((c) => c.path === 'analytics');
    expect(analytics).toBeDefined();
  });
});
```
> This imports the whole router, so it MUST run via the project `test` script (Step 2), not raw `vitest`.

- [ ] **Step 2: Run test to verify it fails**
  - Command: `pnpm -C frontend test src/routes/__tests__/adminAnalyticsRoute.test.ts`
  - Expected: `expect(analytics).toBeDefined()` fails (no analytics child yet).

- [ ] **Step 3: Wire the route + tab**
  - `frontend/src/routes/router.tsx`: add the import next to the other admin route imports (after line 35):
```tsx
import { AdminAnalyticsPage } from '../features/admin/routes/AdminAnalyticsPage';
```
  - Add the child route inside the admin `children` array (after the `auto-enrich` entry, line 130):
```tsx
          { path: 'analytics', element: <AdminAnalyticsPage /> },
```
  - `frontend/src/features/admin/routes/AdminLayout.tsx`: add `'/admin/analytics'` to the `TAB_VALUES` tuple (longest-prefix-first ordering does not matter here — no other tab is a prefix of it) and a tab to `TABS` (after the `auto-enrich` entry, line 31):
```tsx
    { value: '/admin/analytics', label: t('admin.tabs.analytics') },
```

- [ ] **Step 4: Run test to verify it passes**
  - Command: `pnpm -C frontend test src/routes/__tests__/adminAnalyticsRoute.test.ts`
  - Expected: `1 passed`.

- [ ] **Step 5: Run the full CI gate set (typecheck + lint + tests, backend + openapi/schema drift)**
  - Commands:
    ```bash
    pnpm -C frontend run typecheck
    pnpm -C frontend run lint
    pnpm -C frontend run test
    PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py
    git diff --exit-code docs/api/openapi.yaml
    pnpm -C frontend run api:types
    git diff --exit-code frontend/src/api/schema.d.ts
    /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q
    ```
  - Expected: `typecheck` exit 0; `lint` exit 0; the full vitest suite green (new analytics tests included); both `git diff --exit-code` show **no diff** (generated artifacts already committed in Task 3); full pytest suite green (includes the 26 analytics tests). The `requireAdmin` loader itself stays covered by the existing `frontend/src/auth/__tests__/requireAdmin.test.ts`, so admin enforcement is verified end to end (frontend gate + backend `_require_admin`).

- [ ] **Step 6: Commit** — caveman-commit, then:
```bash
git add frontend/src/routes/router.tsx frontend/src/features/admin/routes/AdminLayout.tsx frontend/src/routes/__tests__/adminAnalyticsRoute.test.ts
git commit -m "$(cat <<'EOF'
feat(frontend): mount /admin/analytics under the admin gate

Add the analytics child route inside the requireAdmin-gated admin subtree and
an Analytics tab in AdminLayout. Structural test asserts the gate covers it.
EOF
)"
```

---

## Acceptance (maps to §17 step 5 + §14 checklist)

- **All five dashboards render against `gold/`** (Dashboard 5 also `bronze/ops/` + freshness) via the standalone `analytics-api` — covered by `AnalyticsDashboard.test.tsx` (panel table + error + ops freshness), `useAnalytics.test.tsx` (per-route `/v1` fetch), and `AdminAnalyticsPage` mapping over all 5 `DASHBOARDS`.
- **Every §11 headline metric has a query, every deferred sub-metric is tracked** (MUST-FIX #2): D1 undo rate (`fact_triage_session.undo_rate`, `test_triage_route_has_undo_query`); D2 label affinity = categorize-count vs playback skip-rate per label (`fact_playback` join, `test_taste_label_affinity_joins_playback`); D3 weekly Saturday-week throughput + time-between-steps (`dim_date.saturday_week_*` + `ms_since_prev`, `test_funnel_has_weekly_saturday_week`); D4 listen-ratio-vs-final-category correlation (joined per `track_key`+`user_key`) + seek slice (`fact_playback→fact_track_decision→dim_category`, `fact_seek×dim_track`, `test_playback_route_has_correlation_and_seek_queries`); D5 latency p50 AND p95 (`test_ops_latency_has_p50_and_p95`) + freshness (`test_ops_route_has_freshness_query`). **Deferred (tagged `// ponytail:` at their `_ROUTE_QUERIES` entries, not silently dropped):** D2 BPM histogram + category-mix-by-genre/BPM/key, D4 listen-through distribution — see Skipped.
- **Multi-tenant correlation join is per-tenant** (MUST-FIX, major): the D4 `by_category` query joins `fact_track_decision` on `track_key AND user_key` so one user's plays never cross-join against another user's categorization of the same track (§2). `test_playback_route_has_correlation_and_seek_queries` asserts `"user_key" in built["by_category"][0]`, so the predicate cannot silently regress.
- **THE BLOCKER closed** (MUST-FIX #1): `/v1/*` registered in CloudFront `api_gw_pure_path_patterns` (`infra/frontend.tf`) and Vite `BACKEND_ONLY_PREFIXES` (`frontend/vite.config.ts`) — Task 5, both files listed/modified and grep-verified (the verify grep `"/v1/\*"` matches the inserted `"/v1/*"` exactly) — so the dashboard XHRs reach API Gateway instead of the SPA shell.
- **Admin enforced** server-side (`test_handler_403_for_non_admin`, reading `authorizer.lambda.is_admin`) and client-side (existing `requireAdmin.test.ts` + the new route-structure test).
- **No raw client SQL**: only `_ROUTE_QUERIES` templates run, bound via `ExecutionParameters` (`test_build_queries_*`, `test_client_sql_param_is_ignored`).
- **Result reuse + warm-Lambda memo** verified across multi-query routes (`test_handler_200_returns_rows_and_uses_result_reuse`, `test_handler_warm_lambda_lru_cache_skips_second_query`).
- **Exact test counts** (MUST-FIX #3): `tests/unit/test_analytics_handler.py` collects **20** after Task 1 and **26** after Task 2 (adding the `user_key` assertion to an existing test changes no count). Frontend: `useAnalytics.test.tsx` 2, `AnalyticsDashboard.test.tsx` 3, `adminAnalyticsRoute.test.ts` 1.
- **OpenAPI ⇄ `schema.d.ts` drift gate** passes (Task 8 Step 5 `git diff --exit-code` on both generated files).

**Skipped (out of this increment, add when those increments land):** the gold/bronze tables, Glue DB, Athena workgroup and lake bucket are created by Increments 2–4 and only referenced by name — `terraform apply` of `infra/analytics_routes.tf` succeeds once they exist. Deliberate descopes (`// ponytail:`): §10.1 client **filters** beyond the date range (Phase-1 is date-range-only); the **full 2-D seek heatmap** (ships as a most-seeked-tracks slice); D2's **BPM histogram** + **category-mix-by-genre/BPM/key** and D4's **listen-through distribution** (each tagged at its `_ROUTE_QUERIES` entry); gold/bronze **column names in the SQL are representative** — the per-template column dependencies are enumerated in the `_ROUTE_QUERIES` header checklist, and Increment 3 MUST run a Glue `GetTable` / Athena `EXPLAIN` column-set check per template before apply (column drift is otherwise undetectable until a live Athena run, including the `f.user_key`/`p.user_key` correlation predicate). The §14 **integration smoke** (POST a batch → Parquet lands → Athena `count(*) > 0`; dev `fetch('/v1/analytics/...')` reaches the gateway) is a manual one-shot, not automatable in this increment.
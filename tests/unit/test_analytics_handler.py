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

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
        ah._require_admin(_event("/v1/analytics/user-daily", is_admin=None))
    assert exc.value.status_code == 403
    assert exc.value.error_code == "admin_required"


def test_require_admin_raises_when_non_admin():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._require_admin(_event("/v1/analytics/user-daily", is_admin=False))
    assert exc.value.status_code == 403


def test_require_admin_returns_user_id_for_admin():
    assert ah._require_admin(_event("/v1/analytics/user-daily", is_admin=True)) == "u1"


# ── route resolution ────────────────────────────────────────────────
def test_route_name_extracts_dashboard():
    assert ah._route_name(_event("/v1/analytics/user-daily", is_admin=True)) == "user-daily"


def test_route_name_rejects_unknown_dashboard():
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._route_name(_event("/v1/analytics/evil", is_admin=True))
    assert exc.value.status_code == 404


# ── param validation ────────────────────────────────────────────────
@pytest.mark.parametrize("qs", [
    None,
    {"from": "not-a-date", "to": "2026-02-01", "user_id": "u1"},
    {"from": "2026-01-01", "to": "2026/02/01", "user_id": "u1"},
    {"from": "2026-02-01", "to": "2026-01-01", "user_id": "u1"},  # from > to
    {"to": "2026-02-01", "user_id": "u1"},                         # missing from
    {"from": "2026-01-01", "to": "2026-02-01"},                    # missing user_id
    {"from": "2026-01-01", "to": "2026-02-01", "user_id": ""},     # empty user_id
])
def test_validate_params_rejects_bad_input(qs):
    with pytest.raises(ah.AnalyticsError) as exc:
        ah._validate_params(qs)
    assert exc.value.status_code == 400
    assert exc.value.error_code == "invalid_params"


def test_validate_params_accepts_iso_range():
    assert ah._validate_params({"from": "2026-01-01", "to": "2026-02-01", "user_id": "u1"}) == (
        "2026-01-01", "2026-02-01", "u1",
    )


# ── query building: pre-written only, params bound, no raw SQL ───────
def test_build_queries_uses_only_prewritten_templates():
    built = ah.build_queries("user-daily", "2026-01-01", "2026-02-01", "u1")
    sql, params = built["user-daily"]
    assert "mart_user_daily" in sql
    assert "'2026-01-01'" in sql and "'2026-02-01'" in sql
    assert params == ["u1"]
    assert "u1" not in sql  # bound via ExecutionParameters, not inlined


def test_build_queries_rejects_non_date_values():
    with pytest.raises(ah.AnalyticsError):
        ah.build_queries("user-daily", "2026-01-01'; DROP TABLE dim_user; --", "2026-02-01", "u1")


def test_client_sql_param_is_ignored():
    qs = {"from": "2026-01-01", "to": "2026-02-01", "user_id": "u1", "sql": "DROP TABLE dim_user"}
    date_from, date_to, user_id = ah._validate_params(qs)
    built = ah.build_queries("user-daily", date_from, date_to, user_id)
    assert "DROP" not in built["user-daily"][0]


# ── new routes: user-daily + sessions ─────────────────────────────────
def test_user_daily_binds_user_id_and_inlines_dates(monkeypatch):
    captured: dict = {}

    def fake(client, sql, params):
        captured["sql"] = sql
        captured["params"] = params
        return []

    monkeypatch.setattr(ah, "_run_athena", fake)
    monkeypatch.setattr(ah, "_cached_rows", lambda sql, pk: tuple(fake(None, sql, list(pk))))

    resp = ah.lambda_handler(
        _event("/v1/analytics/user-daily", is_admin=True,
               qs={"user_id": "u1", "from": "2026-06-01", "to": "2026-06-30"}),
        None,
    )

    assert resp["statusCode"] == 200
    assert "mart_user_daily" in captured["sql"]
    assert "'2026-06-01'" in captured["sql"] and "'2026-06-30'" in captured["sql"]
    assert captured["params"] == ["u1"]   # user_id bound, not inlined
    assert "u1" not in captured["sql"]


def test_missing_user_id_400():
    resp = ah.lambda_handler(
        _event("/v1/analytics/user-daily", is_admin=True,
               qs={"from": "2026-06-01", "to": "2026-06-30"}),
        None,
    )
    assert resp["statusCode"] == 400


def test_sessions_route_queries_fact_session(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(
        ah, "_cached_rows",
        lambda sql, pk: captured.setdefault("sql", sql) and (),
    )

    ah.lambda_handler(
        _event("/v1/analytics/sessions", is_admin=True,
               qs={"user_id": "u1", "from": "2026-06-01", "to": "2026-06-30"}),
        None,
    )

    assert "fact_session" in captured["sql"]

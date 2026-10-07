"""Admin API for auto-ingest: settings, plan status, run now."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from collector import handler

VALID = {
    "enabled": True, "mode": "random", "fixed_times": ["09:00", "21:00"], "runs_per_day": 3,
    "timezone": "Asia/Dubai", "periods_per_run": 3, "backfill_floor": "2026-01-03",
}


def _event(route: str, body=None, *, admin: bool = True) -> dict:
    _, path = route.split(" ", 1)
    return {
        "version": "2.0",
        "requestContext": {"requestId": "r", "routeKey": route,
                           "authorizer": {"lambda": {"is_admin": admin, "user_id": "u1"}}},
        "rawPath": path,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "headers": {},
    }


class FakeRepo:
    def __init__(self) -> None:
        self.saved = None
        self.settings = {**VALID, "enabled": False, "planned_runs": ["2026-10-07T21:00:00+00:00"],
                         "last_run": {"ok": True, "pairs": []}, "updated_at": "2026-10-07T00:00:00+00:00"}

    def get_settings(self):
        return dict(self.settings)

    def save_settings(self, values, *, user_id, now):
        self.saved = (dict(values), user_id)
        self.settings.update({k: (v.isoformat() if hasattr(v, "isoformat") else v)
                              for k, v in values.items()})
        return self.get_settings()

    def stuck_pairs(self):
        return [{"style_id": 81, "week_year": 2026, "week_number": 30,
                 "last_attempt_at": "2026-10-06T10:00:00+00:00", "last_error": "UpstreamUnavailableError"}]


@pytest.fixture()
def wiring(monkeypatch):
    repo = FakeRepo()
    invoked: list = []
    monkeypatch.setattr(handler, "_auto_ingest_repository", lambda: repo)
    monkeypatch.setattr(handler, "_invoke_auto_ingest", lambda payload: invoked.append(payload))
    return repo, invoked


def test_get_returns_settings_plan_and_due_week(wiring) -> None:
    response = handler.lambda_handler(_event("GET /admin/auto-ingest"), None)

    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["settings"]["timezone"] == "Asia/Dubai"
    assert body["planned_runs"] == ["2026-10-07T21:00:00+00:00"]
    assert body["last_run"] == {"ok": True, "pairs": []}
    assert set(body["due_week"]) == {"week_year", "week_number"}
    assert body["stuck"][0]["style_id"] == 81


def test_put_saves_and_replans(wiring) -> None:
    repo, invoked = wiring

    response = handler.lambda_handler(_event("PUT /admin/auto-ingest", VALID), None)

    assert response["statusCode"] == 200
    values, user_id = repo.saved
    assert values["backfill_floor"] == date(2026, 1, 3) and user_id == "u1"
    assert invoked == [{"action": "plan"}]


@pytest.mark.parametrize(
    "patch",
    [
        {"fixed_times": ["25:00"]},
        {"fixed_times": []},
        {"timezone": "Mars/Olympus"},
        {"backfill_floor": (date.today() + timedelta(days=2)).isoformat()},
        {"runs_per_day": 0},
        {"periods_per_run": 11},
        {"mode": "hourly"},
        {"unexpected": 1},
    ],
)
def test_put_rejects_invalid_settings(wiring, patch) -> None:
    repo, invoked = wiring

    response = handler.lambda_handler(_event("PUT /admin/auto-ingest", {**VALID, **patch}), None)

    assert response["statusCode"] == 400
    assert repo.saved is None and invoked == []


def test_run_now_invokes_a_manual_run(wiring) -> None:
    _, invoked = wiring

    response = handler.lambda_handler(_event("POST /admin/auto-ingest/run"), None)

    assert response["statusCode"] == 202
    assert invoked == [{"action": "run", "manual": True}]


def test_non_admin_is_rejected(wiring) -> None:
    response = handler.lambda_handler(_event("GET /admin/auto-ingest", admin=False), None)
    assert response["statusCode"] == 403

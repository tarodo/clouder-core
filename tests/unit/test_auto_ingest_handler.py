from __future__ import annotations

import pytest

from collector import auto_ingest_handler as handler
from collector.beatport_auth import BeatportAuthError

TOKEN = "TOKEN-xyz"


@pytest.fixture()
def events(monkeypatch):
    captured: list = []
    monkeypatch.setattr(
        handler, "log_event", lambda level, message, **fields: captured.append((message, fields))
    )
    return captured


def test_auth_check_ok(monkeypatch, events) -> None:
    monkeypatch.setattr(handler, "_read_credentials", lambda: ("user", "pw"))
    monkeypatch.setattr(handler, "fetch_access_token", lambda u, p: TOKEN)

    result = handler.lambda_handler({"action": "auth_check"}, None)

    assert result == {"ok": True}
    assert TOKEN not in repr(events) and "pw" not in repr(events)


def test_auth_check_reports_failed_step(monkeypatch, events) -> None:
    monkeypatch.setattr(handler, "_read_credentials", lambda: ("user", "pw"))

    def fail(u, p):
        raise BeatportAuthError("token", 400)

    monkeypatch.setattr(handler, "fetch_access_token", fail)

    assert handler.lambda_handler({"action": "auth_check"}, None) == {
        "ok": False, "step": "token", "status": 400,
    }


def test_auth_check_reports_missing_credentials(monkeypatch, events) -> None:
    monkeypatch.setenv("BEATPORT_USERNAME_SSM_PARAMETER", "/clouder/beatport/username")
    monkeypatch.setenv("BEATPORT_PASSWORD_SSM_PARAMETER", "/clouder/beatport/password")

    def missing(name):
        raise RuntimeError("ParameterNotFound")

    monkeypatch.setattr(handler.secrets, "_fetch_ssm_parameter", missing)

    assert handler.lambda_handler({"action": "auth_check"}, None) == {
        "ok": False, "step": "credentials", "status": None,
    }


def test_unknown_action_raises() -> None:
    with pytest.raises(ValueError):
        handler.lambda_handler({"action": "drop"}, None)


def test_credentials_failure_logs_the_cause_not_the_value(monkeypatch, events) -> None:
    from botocore.exceptions import ClientError

    monkeypatch.setenv("BEATPORT_USERNAME_SSM_PARAMETER", "/clouder/beatport/username")
    monkeypatch.setenv("BEATPORT_PASSWORD_SSM_PARAMETER", "/clouder/beatport/password")

    def denied(name):
        raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "GetParameter")

    monkeypatch.setattr(handler.secrets, "_fetch_ssm_parameter", denied)

    handler.lambda_handler({"action": "auth_check"}, None)

    (message, fields), = events
    assert fields["error_type"] == "ClientError"
    assert fields["error_code"] == "AccessDeniedException"


# ── plan / run ───────────────────────────────────────────────────────────────

from datetime import datetime, timezone  # noqa: E402

from collector.auto_ingest_repository import PlanningState  # noqa: E402

NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)  # due week: 2026-39


class FakeRepo:
    def __init__(self, *, enabled=True, styles=(81, 96), loaded=frozenset(), busy=False):
        self.settings = {"enabled": enabled, "mode": "random", "fixed_times": ["09:00"],
                         "runs_per_day": 3, "timezone": "UTC", "periods_per_run": 3,
                         "backfill_floor": "2026-01-03", "planned_runs": [], "last_run": None}
        self.state = PlanningState(styles=tuple(styles), loaded=loaded, stuck=frozenset())
        self.busy = busy
        self.released = False
        self.attempts: list = []
        self.last_run = None
        self.planned = None

    def get_settings(self):
        return dict(self.settings)

    def acquire_lease(self, now, minutes=15):
        return not self.busy

    def release_lease(self):
        self.released = True

    def planning_state(self, now):
        return self.state

    def record_attempt(self, style_id, week_year, week_number, *, ok, run_id, error, at):
        self.attempts.append((style_id, week_year, week_number, ok, run_id, error))

    def set_last_run(self, summary):
        self.last_run = summary

    def set_plan(self, planned, now):
        self.planned = planned


class Ctx:
    invoked_function_arn = "arn:aws:lambda:us-east-1:1:function:clouder-prod-auto-ingest"
    aws_request_id = "req-1"


def _collect_ok(params, correlation_id, **kwargs):
    assert kwargs["trigger"] == "auto"
    return {"run_id": f"run-{params.style_id}-{params.week_number}", "item_count": 10}


def test_plan_writes_planned_runs_and_schedules(monkeypatch) -> None:
    monkeypatch.setenv("AUTO_INGEST_SCHEDULE_GROUP", "g")
    monkeypatch.setenv("AUTO_INGEST_SCHEDULER_ROLE_ARN", "arn:role")
    captured = {}
    monkeypatch.setattr(handler, "apply_schedule",
                        lambda client, **kw: captured.update(kw) or ["run-x"])
    repo = FakeRepo()

    result = handler.plan(Ctx(), repo=repo, scheduler=object(), now=NOW,
                          rng=__import__("random").Random(1))

    assert captured["target_arn"] == Ctx.invoked_function_arn and captured["group"] == "g"
    assert repo.planned == result["planned_runs"] and len(repo.planned) == 2  # half a day left


def test_run_skips_when_disabled_unless_manual(monkeypatch) -> None:
    repo = FakeRepo(enabled=False)
    assert handler.run(Ctx(), repo=repo, now=NOW, manual=False, collect=_collect_ok,
                       login=lambda u, p: TOKEN, read_credentials=lambda: ("u", "p")) == {"skipped": "disabled"}
    result = handler.run(Ctx(), repo=repo, now=NOW, manual=True, collect=_collect_ok,
                         login=lambda u, p: TOKEN, read_credentials=lambda: ("u", "p"))
    assert result["ok"] is True and len(result["pairs"]) == 3


def test_second_run_skips_while_the_lease_is_held() -> None:
    repo = FakeRepo(busy=True)
    assert handler.run(Ctx(), repo=repo, now=NOW, manual=False, collect=_collect_ok,
                       login=lambda u, p: TOKEN, read_credentials=lambda: ("u", "p")) == {"skipped": "busy"}
    assert repo.attempts == [] and repo.released is False


def test_login_failure_is_reported_and_releases_the_lease(events) -> None:
    repo = FakeRepo()

    def fail(u, p):
        raise BeatportAuthError("authorize", 200)

    result = handler.run(Ctx(), repo=repo, now=NOW, manual=False, collect=_collect_ok,
                         login=fail, read_credentials=lambda: ("u", "p"))

    assert result["ok"] is False and result["failed_step"] == "authorize"
    assert repo.attempts == [] and repo.released is True
    assert any(m == "auto_ingest_run_failed" for m, _ in events)


def test_failed_period_is_recorded_and_the_run_continues(events) -> None:
    repo = FakeRepo()
    calls = []

    def collect(params, correlation_id, **kwargs):
        calls.append((params.style_id, params.week_number))
        if len(calls) == 2:
            raise RuntimeError(f"boom with {params.bp_token}")
        return _collect_ok(params, correlation_id, **kwargs)

    result = handler.run(Ctx(), repo=repo, now=NOW, manual=False, collect=collect,
                         login=lambda u, p: TOKEN, read_credentials=lambda: ("u", "p"))

    assert calls == [(81, 39), (96, 39), (81, 38)]
    assert [a[3] for a in repo.attempts] == [True, False, True]
    assert repo.attempts[1][5] == "RuntimeError"
    assert [p["ok"] for p in result["pairs"]] == [True, False, True]
    assert repo.last_run == result and repo.released is True
    assert TOKEN not in repr(result) + repr(repo.attempts) + repr(events)

"""Auto-ingest Lambda (docs/data/auto-ingest.md).

- `plan`: turn the admin schedule into one-time EventBridge Scheduler runs for the
  window up to the next 00:05 UTC planner run.
- `run`: take the run lease, log in to Beatport, choose the periods (the due week
  first, then history) and ingest each through the admin endpoint's core.
- `auth_check`: log in and report only whether it worked.

The token is obtained per invocation, kept in memory and passed only to the
Beatport fetch; it is never returned, logged or stored.
"""

from __future__ import annotations

import os
import random
import uuid
from datetime import date, datetime
from typing import Any, Callable, Mapping

from . import secrets
from .auto_ingest_plan import choose_periods, due_week
from .auto_ingest_repository import AutoIngestRepository
from .auto_ingest_schedule import apply_schedule, plan_times
from .beatport_auth import BeatportAuthError, fetch_access_token
from .errors import UpstreamAuthError
from .logging_utils import log_event
from .repositories import utc_now
from .saturday_week import saturday_week_range


def _read_credentials() -> tuple[str, str]:
    return (
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_USERNAME_SSM_PARAMETER"]),
        secrets._fetch_ssm_parameter(os.environ["BEATPORT_PASSWORD_SSM_PARAMETER"]),
    )


def auth_check() -> dict[str, Any]:
    try:
        username, password = _read_credentials()
    except Exception as exc:  # missing env/parameter, IAM, KMS: name the cause, never a value
        log_event(
            "WARNING", "auto_ingest_auth_check", passed=False, phase="credentials",
            error_type=type(exc).__name__,
            error_code=getattr(exc, "response", {}).get("Error", {}).get("Code"),
        )
        return {"ok": False, "step": "credentials", "status": None}
    try:
        fetch_access_token(username, password)
    except BeatportAuthError as exc:
        log_event(
            "WARNING", "auto_ingest_auth_check", passed=False, phase=exc.step,
            status_code=exc.status,
        )
        return {"ok": False, "step": exc.step, "status": exc.status}
    log_event("INFO", "auto_ingest_auth_check", passed=True)
    return {"ok": True}


def _function_arn(context: Any) -> str:
    # Drop a version/alias qualifier: schedules target the function itself.
    return ":".join(str(context.invoked_function_arn).split(":")[:7])


def plan(context: Any, *, repo: Any, scheduler: Any, now: datetime, rng: Any) -> dict[str, Any]:
    settings = repo.get_settings()
    times = plan_times(settings, now, rng=rng)
    apply_schedule(
        scheduler,
        group=os.environ["AUTO_INGEST_SCHEDULE_GROUP"],
        target_arn=_function_arn(context),
        role_arn=os.environ["AUTO_INGEST_SCHEDULER_ROLE_ARN"],
        times=times,
    )
    planned = [t.isoformat() for t in times]
    repo.set_plan(planned, now)
    log_event("INFO", "auto_ingest_planned", count=len(planned))
    return {"planned_runs": planned}


def _error_text(exc: BaseException) -> str:
    # Type and the app's error code only: messages may carry request details.
    code = getattr(exc, "error_code", None)
    return f"{type(exc).__name__}:{code}" if code else type(exc).__name__


def run(
    context: Any,
    *,
    repo: Any,
    now: datetime,
    manual: bool,
    collect: Callable[..., dict[str, Any]] | None = None,
    login: Callable[[str, str], str] = fetch_access_token,
    read_credentials: Callable[[], tuple[str, str]] | None = None,
) -> dict[str, Any]:
    settings = repo.get_settings()
    if not settings["enabled"] and not manual:
        log_event("INFO", "auto_ingest_run_skipped", reason="disabled")
        return {"skipped": "disabled"}
    if not repo.acquire_lease(now):
        log_event("INFO", "auto_ingest_run_skipped", reason="busy")
        return {"skipped": "busy"}
    if collect is None:
        from .handler import collect_period

        collect = collect_period
    correlation_id = f"auto-ingest-{uuid.uuid4()}"
    # Progress for the admin panel, overwritten by the final summary below.
    progress = {"at": now.isoformat(), "manual": manual, "in_progress": True,
                "current": None, "pairs": [], "total": None}
    try:
        repo.set_last_run(progress)
        try:
            username, password = (read_credentials or _read_credentials)()
            token = login(username, password)
        except Exception as exc:
            step = exc.step if isinstance(exc, BeatportAuthError) else "credentials"
            status = exc.status if isinstance(exc, BeatportAuthError) else None
            summary = {"at": now.isoformat(), "manual": manual, "ok": False,
                       "failed_step": step, "status": status, "pairs": []}
            repo.set_last_run(summary)
            log_event("ERROR", "auto_ingest_run_failed", correlation_id=correlation_id,
                      phase=step, status_code=status, error_type=type(exc).__name__)
            return summary

        from .handler import IngestParams

        state = repo.planning_state(now)
        due = due_week(now.date())
        pairs = choose_periods(
            state.styles, state.loaded, state.stuck, due=due,
            floor=date.fromisoformat(settings["backfill_floor"]),
            budget=int(settings["periods_per_run"]),
        )
        outcomes: list[dict[str, Any]] = []
        token_rejected = False
        for style_id, week_year, week_number in pairs:
            start, end = saturday_week_range(week_year, week_number)
            params = IngestParams(
                style_id=style_id, bp_token=token,
                period_start=start.isoformat(), period_end=end.isoformat(),
                iso_year=None, iso_week=None,
                week_year=week_year, week_number=week_number, is_custom_range=False,
            )
            outcome: dict[str, Any] = {"style_id": style_id, "week_year": week_year, "week_number": week_number}
            repo.set_last_run({**progress, "current": dict(outcome), "pairs": outcomes,
                               "total": len(pairs)})
            try:
                result = collect(
                    params, correlation_id, api_request_id="auto-ingest",
                    lambda_request_id=getattr(context, "aws_request_id", "unknown"),
                    trigger="auto",
                )
                outcome.update(ok=True, run_id=result["run_id"], item_count=result.get("item_count"))
                repo.record_attempt(style_id, week_year, week_number, ok=True,
                                    run_id=result["run_id"], error=None, at=utc_now())
            except UpstreamAuthError:
                # The catalog rejected the token: every remaining pair would fail the same
                # way, and none of them is to blame — stop without recording an attempt.
                token_rejected = True
                break
            except Exception as exc:  # one period failing must not stop the others
                outcome.update(ok=False, error=_error_text(exc))
                repo.record_attempt(style_id, week_year, week_number, ok=False,
                                    run_id=None, error=outcome["error"], at=utc_now())
            outcomes.append(outcome)
        del token

        failed = sum(not o["ok"] for o in outcomes)
        summary = {"at": now.isoformat(), "manual": manual, "ok": failed == 0 and not token_rejected,
                   "due_week": list(due), "pairs": outcomes}
        if token_rejected:
            summary.update(failed_step="catalog_auth", status=403)
            log_event("ERROR", "auto_ingest_run_failed", correlation_id=correlation_id,
                      phase="catalog_auth", status_code=403)
        repo.set_last_run(summary)
        log_event("INFO", "auto_ingest_run_completed", correlation_id=correlation_id,
                  count=len(outcomes), runs_failed=failed)
        if outcomes and failed == len(outcomes):
            log_event("ERROR", "auto_ingest_run_failed", correlation_id=correlation_id,
                      count=len(outcomes), runs_failed=failed)
        return summary
    finally:
        repo.release_lease()


def _repository() -> AutoIngestRepository:
    from .data_api import create_default_data_api_client
    from .settings import get_data_api_settings

    settings = get_data_api_settings()
    return AutoIngestRepository(create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    ))


def lambda_handler(event: Mapping[str, Any] | None, context: Any) -> dict[str, Any]:
    action = (event or {}).get("action")
    if action == "auth_check":
        return auth_check()
    if action == "plan":
        import boto3

        return plan(context, repo=_repository(), scheduler=boto3.client("scheduler"),
                    now=utc_now(), rng=random.SystemRandom())
    if action == "run":
        return run(context, repo=_repository(), now=utc_now(),
                   manual=bool((event or {}).get("manual")))
    raise ValueError(f"unknown auto-ingest action: {action!r}")

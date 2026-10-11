"""scripts/dora.py: DORA delivery metrics from deploy runs and PR merges."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dora.py"
spec = importlib.util.spec_from_file_location("dora", SCRIPT)
dora = importlib.util.module_from_spec(spec)
sys.modules["dora"] = dora  # dataclasses resolve annotations through sys.modules
spec.loader.exec_module(dora)

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def deploy(start: float, ok: bool, minutes: float = 5) -> object:
    return dora.Deploy(started=at(start), finished=at(start) + timedelta(minutes=minutes), ok=ok)


def test_deploys_per_week_counts_successes() -> None:
    runs = [deploy(1, True), deploy(2, False), deploy(3, True)]
    assert dora.deploys_per_week(runs, days=14) == 1.0


def test_lead_time_runs_from_first_commit_to_the_deploy_that_ships_it() -> None:
    change = dora.Change(first_commit=at(0), merged=at(10))
    assert dora.lead_times([change], [deploy(10, True)]) == [timedelta(hours=10, minutes=5)]


def test_lead_time_waits_for_the_next_successful_deploy() -> None:
    change = dora.Change(first_commit=at(0), merged=at(10))
    runs = [deploy(10, False), deploy(12, True)]
    assert dora.lead_times([change], runs) == [timedelta(hours=12, minutes=5)]


def test_a_change_not_yet_deployed_has_no_lead_time() -> None:
    assert (
        dora.lead_times([dora.Change(first_commit=at(0), merged=at(10))], [deploy(5, True)]) == []
    )


def test_change_failure_rate() -> None:
    assert (
        dora.change_failure_rate(
            [deploy(1, True), deploy(2, False), deploy(3, True), deploy(4, True)]
        )
        == 0.25
    )
    assert dora.change_failure_rate([]) == 0.0


def test_recovery_counts_a_failure_streak_once() -> None:
    runs = [deploy(1, False), deploy(2, False), deploy(3, True)]
    # From the end of the first failure (1h05) to the end of the next success (3h05).
    assert dora.recovery_times(runs) == [timedelta(hours=2)]


def test_a_failure_not_yet_recovered_has_no_recovery_time() -> None:
    assert dora.recovery_times([deploy(1, True), deploy(2, False)]) == []


def test_window_and_cancelled_runs_are_excluded() -> None:
    raw = [
        {
            "conclusion": "success",
            "createdAt": "2026-09-01T00:00:00Z",
            "updatedAt": "2026-09-01T00:05:00Z",
        },
        {
            "conclusion": "cancelled",
            "createdAt": "2026-10-02T00:00:00Z",
            "updatedAt": "2026-10-02T00:01:00Z",
        },
        {
            "conclusion": "failure",
            "createdAt": "2026-10-03T00:00:00Z",
            "updatedAt": "2026-10-03T00:04:00Z",
        },
    ]
    runs = dora.parse_deploys(raw, since=T0)
    assert runs == [
        dora.Deploy(
            started=datetime(2026, 10, 3, tzinfo=UTC),
            finished=datetime(2026, 10, 3, 0, 4, tzinfo=UTC),
            ok=False,
        )
    ]


def test_summary_line() -> None:
    line = dora.summary(
        per_week=4.25,
        lead=[timedelta(hours=2)],
        cfr=0.081,
        recovery=[timedelta(minutes=25)],
        days=90,
    )
    assert line == (
        "last 90 days: 4.2 deploys a week, median lead time 2.0 h, "
        "change failure rate 8 %, median recovery from a failed deploy 25 min"
    )

from __future__ import annotations

import itertools
import json
import random
from datetime import UTC, datetime

from collector.auto_ingest_schedule import (
    MIN_GAP,
    apply_schedule,
    plan_times,
    window_end,
)

UTC = UTC


def _settings(**overrides):
    base = {
        "enabled": True,
        "mode": "random",
        "fixed_times": ["09:00", "15:00", "21:00"],
        "runs_per_day": 3,
        "timezone": "UTC",
    }
    base.update(overrides)
    return base


def test_window_ends_at_the_next_planner_run() -> None:
    assert window_end(datetime(2026, 10, 7, 0, 5, tzinfo=UTC)) == datetime(
        2026, 10, 8, 0, 5, tzinfo=UTC
    )
    assert window_end(datetime(2026, 10, 7, 13, 0, tzinfo=UTC)) == datetime(
        2026, 10, 8, 0, 5, tzinfo=UTC
    )
    assert window_end(datetime(2026, 10, 7, 0, 4, tzinfo=UTC)) == datetime(
        2026, 10, 7, 0, 5, tzinfo=UTC
    )


def test_fixed_times_follow_the_timezone_across_dst() -> None:
    # Berlin leaves summer time on 2026-10-25.
    s = _settings(mode="fixed", fixed_times=["09:00"], timezone="Europe/Berlin")
    before = plan_times(s, datetime(2026, 10, 24, 0, 5, tzinfo=UTC), rng=random.Random(1))
    after = plan_times(s, datetime(2026, 10, 26, 0, 5, tzinfo=UTC), rng=random.Random(1))
    assert before == [datetime(2026, 10, 24, 7, 0, tzinfo=UTC)]  # 09:00 CEST
    assert after == [datetime(2026, 10, 26, 8, 0, tzinfo=UTC)]  # 09:00 CET


def test_fixed_times_outside_the_window_are_dropped() -> None:
    s = _settings(mode="fixed")
    assert plan_times(s, datetime(2026, 10, 7, 16, 0, tzinfo=UTC), rng=random.Random(1)) == [
        datetime(2026, 10, 7, 21, 0, tzinfo=UTC)
    ]


def test_random_times_are_spaced() -> None:
    now = datetime(2026, 10, 7, 0, 5, tzinfo=UTC)
    for seed in range(50):
        times = plan_times(_settings(runs_per_day=6), now, rng=random.Random(seed))
        assert len(times) == 6
        assert all(now < t < window_end(now) for t in times)
        assert all(b - a >= MIN_GAP for a, b in itertools.pairwise(times))


def test_replan_mid_window_scales_the_count() -> None:
    now = datetime(2026, 10, 7, 12, 5, tzinfo=UTC)  # half of the window left
    assert len(plan_times(_settings(runs_per_day=3), now, rng=random.Random(2))) == 2


def test_disabled_plans_nothing() -> None:
    assert (
        plan_times(
            _settings(enabled=False), datetime(2026, 10, 7, 0, 5, tzinfo=UTC), rng=random.Random(1)
        )
        == []
    )


class FakeScheduler:
    def __init__(self, existing):
        self.existing = existing
        self.deleted: list = []
        self.created: list = []

    def list_schedules(self, GroupName, NamePrefix, **kwargs):
        return {"Schedules": [{"Name": n} for n in self.existing if n.startswith(NamePrefix)]}

    def delete_schedule(self, Name, GroupName):
        self.deleted.append(Name)

    def create_schedule(self, **kwargs):
        self.created.append(kwargs)


def test_apply_replaces_pending_run_schedules() -> None:
    client = FakeScheduler(["run-20261007T0900", "planner"])

    names = apply_schedule(
        client,
        group="g",
        target_arn="arn:fn",
        role_arn="arn:role",
        times=[datetime(2026, 10, 7, 21, 0, tzinfo=UTC)],
    )

    assert client.deleted == ["run-20261007T0900"]
    (created,) = client.created
    assert (created["Name"], created["GroupName"]) == ("run-20261007T2100", "g")
    assert created["ScheduleExpression"] == "at(2026-10-07T21:00:00)"
    assert created["ScheduleExpressionTimezone"] == "UTC"
    assert created["ActionAfterCompletion"] == "DELETE"
    assert created["FlexibleTimeWindow"] == {"Mode": "OFF"}
    assert (created["Target"]["Arn"], created["Target"]["RoleArn"]) == ("arn:fn", "arn:role")
    assert json.loads(created["Target"]["Input"]) == {"action": "run"}
    assert names == ["run-20261007T2100"]

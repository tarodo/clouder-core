"""When auto-ingest runs (docs/data/auto-ingest.md).

The planner runs daily at 00:05 UTC (and on every settings save) and plans the
window up to its next run: fixed local times, or N random times at least an hour
apart. Each planned time becomes a one-time EventBridge Scheduler schedule that
deletes itself after firing.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PLANNER_AT = time(0, 5)
MIN_GAP = timedelta(minutes=60)
_LEAD = timedelta(minutes=5)  # do not plan a run for the very next minutes
RUN_PREFIX = "run-"


def window_end(now: datetime) -> datetime:
    """The planner's next run after `now` (UTC)."""
    today = datetime.combine(now.astimezone(UTC).date(), PLANNER_AT, UTC)
    return today if now < today else today + timedelta(days=1)


def _fixed(settings: Mapping[str, Any], now: datetime, end: datetime) -> list[datetime]:
    zone = ZoneInfo(settings["timezone"])
    local_today = now.astimezone(zone).date()
    times = set()
    for offset in (-1, 0, 1):
        day = local_today + timedelta(days=offset)
        for hhmm in settings["fixed_times"]:
            hours, minutes = (int(x) for x in hhmm.split(":"))
            at = datetime.combine(day, time(hours, minutes), zone).astimezone(UTC)
            if now < at <= end:
                times.add(at)
    return sorted(times)


def _random(settings: Mapping[str, Any], now: datetime, end: datetime, rng: Any) -> list[datetime]:
    start = now + _LEAD
    span = (end - start).total_seconds()
    if span <= 0:
        return []
    count = math.ceil(settings["runs_per_day"] * (end - now) / timedelta(days=1))
    for n in range(count, 0, -1):
        for _ in range(200):  # rejection sampling: uniform times with the minimum gap
            times = sorted(start + timedelta(seconds=rng.uniform(0, span)) for _ in range(n))
            times = [t.replace(second=0, microsecond=0) for t in times]
            if all(b - a >= MIN_GAP for a, b in itertools.pairwise(times)) and times[0] > now:
                return times
    return []


def plan_times(settings: Mapping[str, Any], now: datetime, *, rng: Any) -> list[datetime]:
    if not settings["enabled"]:
        return []
    end = window_end(now)
    if settings["mode"] == "fixed":
        return _fixed(settings, now, end)
    return _random(settings, now, end, rng)


def apply_schedule(
    client: Any, *, group: str, target_arn: str, role_arn: str, times: Sequence[datetime]
) -> list[str]:
    """Replace the pending one-time run schedules in `group` with `times`."""
    token = None
    while True:
        page = client.list_schedules(
            GroupName=group, NamePrefix=RUN_PREFIX, **({"NextToken": token} if token else {})
        )
        for schedule in page.get("Schedules", []):
            client.delete_schedule(Name=schedule["Name"], GroupName=group)
        token = page.get("NextToken")
        if not token:
            break
    names = []
    for at in times:
        at = at.astimezone(UTC)
        name = f"{RUN_PREFIX}{at:%Y%m%dT%H%M}"
        client.create_schedule(
            Name=name,
            GroupName=group,
            ScheduleExpression=f"at({at:%Y-%m-%dT%H:%M:%S})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            ActionAfterCompletion="DELETE",
            State="ENABLED",
            Target={
                "Arn": target_arn,
                "RoleArn": role_arn,
                "Input": json.dumps({"action": "run"}),
                "RetryPolicy": {"MaximumRetryAttempts": 2, "MaximumEventAgeInSeconds": 3600},
            },
        )
        names.append(name)
    return names

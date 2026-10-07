"""Which (style, Saturday-week) pairs an auto-ingest run takes (docs/data/auto-ingest.md).

The due week first for every visible style, then history newest first, all styles
descending together week by week down to the backfill floor.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import AbstractSet, Iterable

from .saturday_week import saturday_week_range, week_of_date

# Days after a Saturday-week closes (Friday) before it is ingested: Beatport keeps
# publishing that week's releases for a few days.
GRACE_DAYS = 3
_FRIDAY = 4

Pair = tuple[int, int, int]  # (Beatport style id, week_year, week_number)


def due_week(today: date) -> tuple[int, int]:
    """The latest Saturday-week whose Friday is at least GRACE_DAYS before today."""
    d = today - timedelta(days=GRACE_DAYS)
    friday = d - timedelta(days=(d.weekday() - _FRIDAY) % 7)
    return week_of_date(friday)


def weeks_back(due: tuple[int, int], floor: date) -> list[tuple[int, int]]:
    """The due week, then older weeks while they start on or after the floor."""
    start, _ = saturday_week_range(*due)
    weeks = [due]
    start -= timedelta(days=7)
    while start >= floor:
        weeks.append(week_of_date(start))
        start -= timedelta(days=7)
    return weeks


def choose_periods(
    styles: Iterable[int],
    loaded: AbstractSet[Pair],
    stuck: AbstractSet[Pair],
    *,
    due: tuple[int, int],
    floor: date,
    budget: int,
) -> list[Pair]:
    ordered = sorted(styles)
    chosen: list[Pair] = []
    for week_year, week_number in weeks_back(due, floor):
        for style in ordered:
            pair = (style, week_year, week_number)
            if pair in loaded or pair in stuck:
                continue
            chosen.append(pair)
            if len(chosen) >= budget:
                return chosen
    return chosen

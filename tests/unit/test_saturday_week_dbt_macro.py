"""Pin dim_date.sql Saturday-week arithmetic against the canonical saturday_week.py."""
from datetime import date, timedelta

import pytest

from collector.saturday_week import week_of_date
from sat_week_mirror import saturday_week_of


def _all_days(y0: int, y1: int):
    d = date(y0, 1, 1)
    end = date(y1, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=1)


@pytest.mark.parametrize("d", list(_all_days(2024, 2031)))
def test_mirror_matches_canonical_every_day(d):
    assert saturday_week_of(d) == week_of_date(d)


@pytest.mark.parametrize(
    "d",
    [
        date(2026, 1, 1),   # Thu -> belongs to 2025's last week
        date(2026, 1, 2),   # Fri -> still 2025
        date(2026, 1, 3),   # Sat -> 2026 week 1 (first Saturday on/after Jan 1)
        date(2027, 1, 1),   # Fri
        date(2027, 1, 2),   # Sat -> 2027 week 1
        date(2022, 1, 1),   # Sat -> 2022 week 1 (Jan 1 itself is a Saturday)
    ],
)
def test_year_boundary_known_dates(d):
    assert saturday_week_of(d) == week_of_date(d)

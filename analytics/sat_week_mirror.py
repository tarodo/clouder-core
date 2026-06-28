"""Python transcription of the dim_date.sql Saturday-week arithmetic.

This is a CONTRACT-PINNING MIRROR: it must compute byte-identical week numbers to
the SQL in models/gold/dims/dim_date.sql so the offline test can verify the
algorithm against the canonical src/collector/saturday_week.py. SQL correctness is
additionally proven live by tests/assert_dim_date_known_weeks.sql in dbt_test.
"""
from __future__ import annotations

from datetime import date, timedelta


def _last_saturday_on_or_before(d: date) -> date:
    delta = ((d.isoweekday() - 6) % 7 + 7) % 7  # Athena: ((day_of_week-6)%7+7)%7
    return d - timedelta(days=delta)


def _first_saturday(year: int) -> date:
    jan1 = date(year, 1, 1)
    off = ((6 - jan1.isoweekday()) % 7 + 7) % 7  # Athena: ((6-day_of_week(jan1))%7+7)%7
    return jan1 + timedelta(days=off)


def saturday_week_of(d: date) -> tuple[int, int]:
    saturday = _last_saturday_on_or_before(d)
    fs_curr = _first_saturday(saturday.year)
    if saturday < fs_curr:
        fs_prev = _first_saturday(saturday.year - 1)
        return (saturday.year - 1, (saturday - fs_prev).days // 7 + 1)
    return (saturday.year, (saturday - fs_curr).days // 7 + 1)

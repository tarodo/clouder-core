from datetime import date, timedelta

import pytest

from collector.saturday_week import (
    first_saturday,
    saturday_week_range,
    week_of_date,
    weeks_in_year,
)


def test_first_saturday_when_jan_1_is_thu():
    # 2026-01-01 is Thursday → first Saturday is Jan 3.
    assert first_saturday(2026) == date(2026, 1, 3)


def test_first_saturday_when_jan_1_is_saturday():
    # 2028-01-01 is Saturday → first Saturday is Jan 1 itself.
    assert first_saturday(2028) == date(2028, 1, 1)


def test_first_saturday_when_jan_1_is_friday():
    # 2027-01-01 is Friday → first Saturday is Jan 2.
    assert first_saturday(2027) == date(2027, 1, 2)


def test_saturday_week_range_2026_w1():
    start, end = saturday_week_range(2026, 1)
    assert start == date(2026, 1, 3)
    assert end == date(2026, 1, 9)


def test_saturday_week_range_2026_w5():
    start, end = saturday_week_range(2026, 5)
    assert start == date(2026, 1, 31)
    assert end == date(2026, 2, 6)


def test_weeks_in_year_2026_is_52():
    assert weeks_in_year(2026) == 52


def test_weeks_in_year_2028_is_53():
    # 2028 starts on Saturday (Jan 1) and ends Sunday (Dec 31).
    # Last Saturday is Dec 30 → 53 weeks fit.
    assert weeks_in_year(2028) == 53


def test_week_of_date_round_trip_2026():
    for n in range(1, weeks_in_year(2026) + 1):
        start, _ = saturday_week_range(2026, n)
        for offset in range(7):
            assert week_of_date(start + timedelta(days=offset)) == (2026, n)


def test_week_of_date_jan_1_2027_belongs_to_prev_year():
    # 2027-01-01 is Friday — falls before first Saturday of 2027 → week 52 of 2026.
    assert week_of_date(date(2027, 1, 1)) == (2026, 52)


def test_saturday_week_range_rejects_out_of_range():
    with pytest.raises(ValueError):
        saturday_week_range(2026, 0)
    with pytest.raises(ValueError):
        saturday_week_range(2026, weeks_in_year(2026) + 1)

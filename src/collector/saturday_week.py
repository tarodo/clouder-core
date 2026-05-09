"""Saturday-anchored week math.

Convention used by the admin Beatport ingest UI.

- Week N of year Y starts on Saturday(Y, N) and ends on the following Friday.
- Saturday(Y, 1) is the first Saturday on or after Jan 1 of Y.
- Days from Jan 1 up to (but excluding) Saturday(Y, 1) belong to the last
  week of Y - 1.
"""

from __future__ import annotations

from datetime import date, timedelta

_SATURDAY = 5  # date.weekday(): Mon=0 .. Sun=6


def first_saturday(year: int) -> date:
    jan1 = date(year, 1, 1)
    delta = (_SATURDAY - jan1.weekday()) % 7
    return jan1 + timedelta(days=delta)


def _last_saturday_on_or_before(d: date) -> date:
    delta = (d.weekday() - _SATURDAY) % 7
    return d - timedelta(days=delta)


def weeks_in_year(year: int) -> int:
    start = first_saturday(year)
    end = _last_saturday_on_or_before(date(year, 12, 31))
    return ((end - start).days // 7) + 1


def saturday_week_range(year: int, week: int) -> tuple[date, date]:
    limit = weeks_in_year(year)
    if week < 1 or week > limit:
        raise ValueError(
            f"week {week} out of range for year {year} (1..{limit})"
        )
    start = first_saturday(year) + timedelta(days=(week - 1) * 7)
    end = start + timedelta(days=6)
    return start, end


def week_of_date(d: date) -> tuple[int, int]:
    saturday = _last_saturday_on_or_before(d)
    year = saturday.year
    fs = first_saturday(year)
    if saturday < fs:
        # Saturday belongs to previous year's last week.
        prev = year - 1
        prev_fs = first_saturday(prev)
        week = ((saturday - prev_fs).days // 7) + 1
        return prev, week
    week = ((saturday - fs).days // 7) + 1
    return year, week

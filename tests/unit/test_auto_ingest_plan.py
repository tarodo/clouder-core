from __future__ import annotations

from datetime import date

import pytest

from collector.auto_ingest_plan import choose_periods, due_week, weeks_back


@pytest.mark.parametrize(
    "today, expected",
    [
        (date(2026, 10, 5), (2026, 39)),   # Monday: the week closed Friday 10-02 is due
        (date(2026, 10, 4), (2026, 38)),   # Sunday: still inside the 3-day grace
        (date(2026, 10, 9), (2026, 39)),   # Friday: week 40 closes today, not due yet
        (date(2026, 10, 12), (2026, 40)),
        (date(2026, 1, 5), (2025, 52)),    # across New Year: last Saturday-week of 2025
        (date(2026, 1, 12), (2026, 1)),
    ],
)
def test_due_week_boundaries(today, expected) -> None:
    assert due_week(today) == expected


def test_weeks_back_stops_at_the_floor_but_keeps_the_due_week() -> None:
    assert weeks_back((2026, 39), date(2026, 9, 12)) == [(2026, 39), (2026, 38), (2026, 37)]
    assert weeks_back((2026, 39), date(2026, 12, 1)) == [(2026, 39)]


def test_due_week_comes_first_for_every_style() -> None:
    chosen = choose_periods(
        {96, 1, 81}, frozenset({(1, 2026, 39)}), frozenset(),
        due=(2026, 39), floor=date(2026, 1, 3), budget=3,
    )
    assert chosen == [(81, 2026, 39), (96, 2026, 39), (1, 2026, 38)]


def test_history_descends_evenly_across_styles() -> None:
    loaded: set = set()
    runs = []
    for _ in range(3):
        chosen = choose_periods({1, 2}, frozenset(loaded), frozenset(),
                                due=(2026, 39), floor=date(2026, 1, 3), budget=3)
        runs.append(chosen)
        loaded.update(chosen)
    assert runs == [
        [(1, 2026, 39), (2, 2026, 39), (1, 2026, 38)],
        [(2, 2026, 38), (1, 2026, 37), (2, 2026, 37)],
        [(1, 2026, 36), (2, 2026, 36), (1, 2026, 35)],
    ]


def test_loaded_and_stuck_are_skipped() -> None:
    chosen = choose_periods(
        {1}, frozenset({(1, 2026, 39)}), frozenset({(1, 2026, 38)}),
        due=(2026, 39), floor=date(2026, 1, 3), budget=2,
    )
    assert chosen == [(1, 2026, 37), (1, 2026, 36)]


def test_nothing_left_above_the_floor() -> None:
    assert choose_periods({1}, frozenset({(1, 2026, 39)}), frozenset(),
                          due=(2026, 39), floor=date(2026, 9, 26), budget=3) == []

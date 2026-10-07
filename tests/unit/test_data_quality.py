"""Data-quality runner logic that needs no database."""

from __future__ import annotations

from datetime import date

from collector.data_quality import CHECKS, Check, expected_week_end, run_checks


def test_expected_week_end_respects_grace_days() -> None:
    # Saturday-weeks run Sat..Fri; a week is due 3 days after its Friday.
    assert expected_week_end(date(2026, 10, 5)) == date(2026, 10, 2)  # Mon: Fri + 3
    assert expected_week_end(date(2026, 10, 4)) == date(2026, 9, 25)  # Sun: still in grace
    assert expected_week_end(date(2026, 10, 9)) == date(2026, 10, 2)  # next Friday


class FakeClient:
    def __init__(self, values: dict[str, object], fail: set[str] = frozenset()) -> None:
        self.values, self.fail, self.calls = values, fail, []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append(params)
        name = next(n for n in self.values if f"/* {n} */" in sql)
        if name in self.fail:
            raise RuntimeError("boom")
        return [{"value": self.values[name]}]


def _check(name: str, comparison: str = "max", threshold: float | None = 0) -> Check:
    return Check(name=name, description=name, sql=f"/* {name} */ SELECT 1 AS value",
                 comparison=comparison, threshold=threshold)


def test_failing_check_is_recorded_and_others_run() -> None:
    client = FakeClient({"a": 0, "b": 0}, fail={"a"})

    results = run_checks(client, date(2026, 10, 7), checks=[_check("a"), _check("b")])

    assert [(r.name, r.passed, r.value) for r in results] == [("a", False, None), ("b", True, 0.0)]


def test_values_are_floats_even_when_the_driver_returns_strings() -> None:
    client = FakeClient({"pct": "99.50"})

    (result,) = run_checks(client, date(2026, 10, 7), checks=[_check("pct", "min", 99)])

    assert result.value == 99.5 and result.passed


def test_recorded_only_checks_never_fail() -> None:
    client = FakeClient({"info": 42})

    (result,) = run_checks(client, date(2026, 10, 7), checks=[_check("info", threshold=None)])

    assert result.passed and result.value == 42.0


def test_only_declared_params_are_sent() -> None:
    client = FakeClient({"p": 0})
    check = Check(name="p", description="p", sql="/* p */ SELECT 1 AS value",
                  comparison="max", threshold=0, params=("expected_end",))

    run_checks(client, date(2026, 10, 7), checks=[check])

    assert client.calls == [{"expected_end": date(2026, 10, 2)}]


def test_every_check_has_a_unique_name_and_a_known_comparison() -> None:
    names = [c.name for c in CHECKS]
    assert len(names) == len(set(names))
    assert {c.comparison for c in CHECKS} <= {"max", "min"}

import pytest

import dbt_runner


class FakeResult:
    def __init__(self, success):
        self.success = success


class FakeInvoke:
    def __init__(self, success=True):
        self.calls = []
        self.success = success

    def __call__(self, args):
        self.calls.append(args)
        return FakeResult(self.success)


def test_multi_token_source_freshness_splits():
    inv = FakeInvoke()
    out = dbt_runner.run_dbt("source freshness", "/proj", "/prof", inv)
    assert inv.calls[0][:2] == ["source", "freshness"]
    assert "--project-dir" in inv.calls[0] and "/proj" in inv.calls[0]
    assert "--profiles-dir" in inv.calls[0] and "/prof" in inv.calls[0]
    assert out["success"] is True


def test_single_token_run():
    inv = FakeInvoke()
    dbt_runner.run_dbt("run", "/proj", "/prof", inv)
    assert inv.calls[0][0] == "run"


def test_failure_raises_runtime_error():
    inv = FakeInvoke(success=False)
    with pytest.raises(RuntimeError):
        dbt_runner.run_dbt("test", "/proj", "/prof", inv)

import json
import pathlib

ASL = (
    pathlib.Path(__file__).resolve().parents[2]
    / "analytics" / "state_machine.asl.json"
)


def _load():
    return json.loads(ASL.read_text())


def test_parallel_runs_both_exports():
    d = _load()
    start = d["States"][d["StartAt"]]
    assert start["Type"] == "Parallel"
    names = {
        b["States"][b["StartAt"]]["Parameters"]["FunctionName"]
        for b in start["Branches"]
    }
    assert names == {"${catalog_export_arn}", "${ops_log_export_arn}"}


def test_order_run_then_freshness_then_test():
    d = _load()
    s = d["States"]
    assert s[d["StartAt"]]["Next"] == "DbtRun"
    assert s["DbtRun"]["Next"] == "DbtSourceFreshness"
    assert s["DbtSourceFreshness"]["Next"] == "DbtTest"


def test_payload_commands():
    d = _load()
    s = d["States"]
    assert s["DbtRun"]["Parameters"]["Payload"]["command"] == "run"
    assert s["DbtSourceFreshness"]["Parameters"]["Payload"]["command"] == "source freshness"
    assert s["DbtTest"]["Parameters"]["Payload"]["command"] == "test"


def test_quality_gate_catches_to_fail():
    d = _load()
    s = d["States"]
    for state in ("DbtSourceFreshness", "DbtTest"):
        assert any(c["Next"] == "NotifyFailure" for c in s[state]["Catch"])
    assert s["NotifyFailure"]["Type"] == "Fail"

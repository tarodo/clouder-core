"""The state machine sends what backfill_handler dispatches on (infra/backfill.asl.json)."""

from __future__ import annotations

import json
from pathlib import Path

ASL = Path(__file__).resolve().parents[2] / "infra" / "backfill.asl.json"


def _definition() -> dict:
    text = (
        ASL.read_text()
        .replace("${backfill_function_arn}", "arn:aws:lambda:eu-central-1:1:function:backfill")
        .replace("${data_quality_function_arn}", "arn:aws:lambda:eu-central-1:1:function:dq")
    )
    assert "${" not in text
    return json.loads(text)


def _states(definition: dict):
    for name, state in definition["States"].items():
        yield name, state, definition["States"]
        if state["Type"] == "Map":
            yield from _states(state["ItemProcessor"])


def test_every_transition_points_at_a_state() -> None:
    for name, state, scope in _states(_definition()):
        targets = [state.get("Next"), state.get("Default")]
        targets += [c["Next"] for c in state.get("Choices", [])]
        targets += [c["Next"] for c in state.get("Catch", [])]
        for target in filter(None, targets):
            assert target in scope, f"{name} -> {target}"


def test_tasks_send_the_actions_the_handler_dispatches() -> None:
    states = _definition()["States"]
    assert states["Plan"]["Parameters"]["Payload"] == {"action": "plan", "input.$": "$"}
    assert states["Replay"]["ItemSelector"] == {
        "action": "replay",
        "run.$": "$$.Map.Item.Value",
        "dry_run.$": "$.plan.dry_run",
    }
    assert states["Summarize"]["Parameters"]["Payload"] == {
        "action": "summarize",
        "dry_run.$": "$.plan.dry_run",
        "results.$": "$.plan.runs",
    }


def test_map_results_replace_the_run_list() -> None:
    # Keeping both the planned runs and their results in the state halves the
    # room under the 256 KiB state limit; the results overwrite the runs.
    assert _definition()["States"]["Replay"]["ResultPath"] == "$.plan.runs"


def test_read_only_steps_retry_through_an_aurora_resume() -> None:
    states = _definition()["States"]
    for name in ("Plan", "Summarize"):
        task_failed = [r for r in states[name]["Retry"] if r["ErrorEquals"] == ["States.TaskFailed"]]
        assert task_failed and task_failed[0]["MaxAttempts"] >= 3, name


def test_replay_failed_names_the_failed_runs() -> None:
    cause = _definition()["States"]["ReplayFailed"]["CausePath"]
    assert "$.report.summary.failed_run_ids" in cause


def test_replay_failures_are_caught_and_counted() -> None:
    replay = _definition()["States"]["Replay"]
    assert replay["MaxConcurrency"] == 2
    inner = replay["ItemProcessor"]["States"]
    assert inner["ReplayRun"]["Catch"][0]["ErrorEquals"] == ["States.ALL"]
    failed = inner[inner["ReplayRun"]["Catch"][0]["Next"]]
    assert failed["Parameters"]["failed"] is True
    assert failed["Parameters"]["run_id.$"] == "$.run.run_id"
    choice = _definition()["States"]["AnyRunFailed"]["Choices"][0]
    assert choice["Variable"] == "$.report.summary.runs_failed"


def test_quality_gate_runs_only_after_an_apply() -> None:
    states = _definition()["States"]
    assert states["IsDryRun"]["Choices"][0] == {
        "Variable": "$.plan.dry_run", "BooleanEquals": True, "Next": "Done",
    }
    assert states["IsDryRun"]["Default"] == "QualityGate"
    assert "${data_quality_function_arn}" in ASL.read_text()

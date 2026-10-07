"""The transform state machine runs the dbt CodeBuild project synchronously and fails visibly."""

from __future__ import annotations

import json
from pathlib import Path

ASL = Path(__file__).resolve().parents[2] / "infra" / "transform.asl.json"


def _definition() -> dict:
    text = ASL.read_text().replace("${dbt_project_name}", "clouder-prod-dbt")
    assert "${" not in text
    return json.loads(text)


def test_runs_dbt_build_synchronously_with_a_retry() -> None:
    build = _definition()["States"]["DbtBuild"]
    assert build["Resource"] == "arn:aws:states:::codebuild:startBuild.sync"
    assert build["Parameters"]["ProjectName"] == "clouder-prod-dbt"
    assert build["Retry"][0]["MaxAttempts"] == 1
    assert build["TimeoutSeconds"] <= 3600


def test_failure_ends_in_a_fail_state() -> None:
    states = _definition()["States"]
    catch = states["DbtBuild"]["Catch"][0]
    assert catch["ErrorEquals"] == ["States.ALL"]
    assert states[catch["Next"]]["Type"] == "Fail"

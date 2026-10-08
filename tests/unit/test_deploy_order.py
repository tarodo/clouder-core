"""The deploy migrates before the API code ships (postmortem 2026-09-20)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


def test_migration_runs_between_the_targeted_and_the_full_apply() -> None:
    steps = yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    targeted = names.index("Terraform apply (migration Lambda only)")
    migrate = names.index("Run DB migrations via Lambda")
    full = names.index("Terraform apply")
    assert targeted < migrate < full
    assert "-target=aws_lambda_function.db_migration" in steps[targeted]["run"]
    assert "-target" not in steps[full]["run"]


def test_both_applies_pass_the_same_variables() -> None:
    # A variable missing from the targeted apply would change the migration
    # Lambda's config in phase 1 and back in phase 2.
    steps = {s.get("name"): s for s in yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]}
    targeted = set(re.findall(r'-var="[^"]+"', steps["Terraform apply (migration Lambda only)"]["run"]))
    full = set(re.findall(r'-var="[^"]+"', steps["Terraform apply"]["run"]))
    assert targeted and targeted == full

"""CI hardening around AWS (ADR-0028): same inputs for plan and apply, secrets only via env,
no dependency install with credentials, one deploy at a time."""

from __future__ import annotations

from pathlib import Path

import yaml

WF = Path(__file__).resolve().parents[2] / ".github" / "workflows"
DEPLOY = yaml.safe_load((WF / "deploy.yml").read_text())
PR = yaml.safe_load((WF / "pr.yml").read_text())

TF_INPUTS = {
    "TF_VAR_spotify_oauth_redirect_uri": "${{ vars.SPOTIFY_OAUTH_REDIRECT_URI }}",
    "TF_VAR_admin_spotify_ids": "${{ vars.ADMIN_SPOTIFY_IDS }}",
    "TF_VAR_allowed_frontend_redirects": "${{ vars.ALLOWED_FRONTEND_REDIRECTS }}",
    "TF_VAR_beatport_client_id": "${{ secrets.BEATPORT_CLIENT_ID }}",
    "TF_VAR_alarm_email": "${{ secrets.ALARM_EMAIL }}",
    "TF_VAR_budget_monthly_limit": "${{ secrets.BUDGET_MONTHLY_LIMIT }}",
}


def _first(steps: list[dict], pred) -> int:
    return next(i for i, s in enumerate(steps) if pred(s))


def _plan_step() -> dict:
    return next(s for s in PR["jobs"]["terraform"]["steps"] if "terraform plan" in s.get("run", ""))


def test_secrets_reach_shell_steps_only_through_env() -> None:
    for name, doc in (("deploy.yml", DEPLOY), ("pr.yml", PR)):
        for job in doc["jobs"].values():
            for step in job.get("steps", []):
                assert "${{ secrets." not in step.get("run", ""), (name, step.get("name"))
                assert "${{ vars." not in step.get("run", ""), (name, step.get("name"))


def test_lambda_is_packaged_before_any_aws_credentials() -> None:
    for steps in (DEPLOY["jobs"]["deploy"]["steps"], PR["jobs"]["terraform"]["steps"]):
        package = _first(steps, lambda s: "package_lambda.sh" in s.get("run", ""))
        creds = _first(steps, lambda s: "configure-aws-credentials" in s.get("uses", ""))
        assert package < creds


def test_deploys_never_run_concurrently() -> None:
    assert DEPLOY["concurrency"] == {"group": "deploy-production", "cancel-in-progress": False}


def test_plan_and_apply_get_the_same_inputs() -> None:
    assert {k: v for k, v in DEPLOY["jobs"]["deploy"]["env"].items() if k.startswith("TF_VAR_")} == TF_INPUTS
    plan = _plan_step()
    assert plan["env"] == TF_INPUTS
    assert "-var-file=prod.tfvars" in plan["run"] and "-var=" not in plan["run"]

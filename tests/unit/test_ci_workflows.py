"""CI hardening around AWS (ADR-0028): same inputs for plan and apply, secrets only via env,
no dependency install with credentials, one deploy at a time."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WF = ROOT / ".github" / "workflows"
FRONTEND_DEPLOY = ROOT / "scripts" / "deploy_frontend.sh"
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


def test_frontend_dependencies_install_before_any_aws_credentials() -> None:
    # pnpm runs dependencies' install scripts (esbuild has a postinstall).
    steps = DEPLOY["jobs"]["deploy"]["steps"]
    build = _first(steps, lambda s: s.get("run", "").strip() == "scripts/deploy_frontend.sh build")
    creds = _first(steps, lambda s: "configure-aws-credentials" in s.get("uses", ""))
    publish = _first(
        steps, lambda s: s.get("run", "").strip() == "scripts/deploy_frontend.sh publish"
    )
    apply = _first(steps, lambda s: s.get("name") == "Terraform apply")
    assert build < creds < apply < publish


def _run_frontend_deploy(tmp_path: Path, mode: str) -> str:
    log = tmp_path / "calls.log"
    log.touch()
    for tool in ("pnpm", "aws", "terraform"):
        fake = tmp_path / tool
        fake.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\n')
        fake.chmod(0o755)
    env = {**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}"}
    subprocess.run(["bash", str(FRONTEND_DEPLOY), mode], env=env, check=True, capture_output=True)
    return log.read_text()


def test_frontend_build_mode_never_touches_aws(tmp_path: Path) -> None:
    calls = _run_frontend_deploy(tmp_path, "build")
    assert "pnpm install --frozen-lockfile" in calls and "pnpm build" in calls
    assert "aws " not in calls and "terraform " not in calls


def test_frontend_publish_mode_installs_nothing(tmp_path: Path) -> None:
    calls = _run_frontend_deploy(tmp_path, "publish")
    assert "pnpm" not in calls
    assert "aws s3 sync" in calls and "aws cloudfront create-invalidation" in calls


def test_deploys_never_run_concurrently() -> None:
    # Job-level: a manual dispatch from another branch skips the job, so it never
    # takes the slot of a main deploy waiting in the queue.
    assert "concurrency" not in DEPLOY
    assert DEPLOY["jobs"]["deploy"]["concurrency"] == {
        "group": "deploy-production",
        "cancel-in-progress": False,
    }


def test_plan_and_apply_get_the_same_inputs() -> None:
    assert {
        k: v for k, v in DEPLOY["jobs"]["deploy"]["env"].items() if k.startswith("TF_VAR_")
    } == TF_INPUTS
    plan = _plan_step()
    assert plan["env"] == TF_INPUTS
    assert "-var-file=prod.tfvars" in plan["run"] and "-var=" not in plan["run"]


# github.actor, not the PR author: secrets follow the actor, so a person pushing a fix
# to a Dependabot branch still gets the plan.
HUMAN = "github.actor != 'dependabot[bot]'"
BOT = "github.actor == 'dependabot[bot]'"


def test_pull_requests_plan_with_the_read_only_role() -> None:
    creds = next(
        s
        for s in PR["jobs"]["terraform"]["steps"]
        if "configure-aws-credentials" in s.get("uses", "")
    )
    assert creds["with"]["role-to-assume"] == "${{ secrets.AWS_PLAN_ROLE_ARN }}"
    assert "AWS_GITHUB_ROLE_ARN" not in (WF / "pr.yml").read_text()


def test_dependabot_prs_validate_without_aws() -> None:
    # Dependabot gets no repository secrets, so it cannot assume a role.
    steps = PR["jobs"]["terraform"]["steps"]
    for s in steps:
        needs_aws = (
            "configure-aws-credentials" in s.get("uses", "")
            or "-backend-config" in s.get("run", "")
            or "terraform plan" in s.get("run", "")
        )
        if needs_aws:
            assert s.get("if") == HUMAN, s.get("name")
    assert any(s.get("if") == BOT and "-backend=false" in s.get("run", "") for s in steps)
    validate = next(s for s in steps if s.get("run", "").strip() == "terraform validate")
    assert "if" not in validate


def test_only_the_terraform_job_can_mint_oidc_tokens() -> None:
    # Every PR job installs third-party code (pip, pnpm); only the plan needs AWS.
    assert "id-token" not in PR.get("permissions", {})
    holders = {
        name
        for name, job in PR["jobs"].items()
        if job.get("permissions", {}).get("id-token") == "write"
    }
    assert holders == {"terraform"}
    assert PR["jobs"]["terraform"]["permissions"] == {"contents": "read", "id-token": "write"}


def test_deploy_snapshots_aliases_smokes_and_rolls_back() -> None:
    steps = DEPLOY["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    snapshot, apply, smoke, rollback = (
        names.index(n)
        for n in ("Snapshot API aliases", "Terraform apply", "Smoke test", "Roll back API aliases")
    )
    assert snapshot < apply < smoke < rollback
    assert steps[snapshot]["id"] == "snapshot"
    assert steps[rollback]["if"] == "failure() && steps.snapshot.outcome == 'success'"
    assert (
        "scripts/smoke.py" in steps[smoke]["run"]
        and "api_aliases.py restore" in steps[rollback]["run"]
    )


def test_deploy_prints_the_alias_snapshot() -> None:
    # The snapshot is the manual-rollback input if the automatic restore fails half-way.
    snapshot = next(
        s for s in DEPLOY["jobs"]["deploy"]["steps"] if s.get("name") == "Snapshot API aliases"
    )
    assert 'cat "$RUNNER_TEMP/aliases.json"' in snapshot["run"]
    assert (
        "| tee" not in snapshot["run"]
    )  # no pipefail in the default shell: tee would hide a failure


def test_lint_job_checks_formatting() -> None:
    runs = [step.get("run", "") for step in PR["jobs"]["lint"]["steps"]]
    assert "ruff format --check src tests scripts" in runs


def test_one_pages_workflow_publishes_landing_lineage_and_demo() -> None:
    assert not (WF / "dbt-docs.yml").exists(), "two Pages workflows overwrite each other"
    pages = (WF / "pages.yml").read_text()
    for needle in (
        "dbt docs generate",
        "pnpm build:demo",
        "site/lineage/index.html",
        "site/demo",
        "site/404.html",
        "pages/index.html",
    ):
        assert needle in pages, needle


def test_pr_builds_the_demo() -> None:
    runs = [step.get("run", "") for step in PR["jobs"]["frontend"]["steps"]]
    assert "pnpm build:demo" in runs
    # The production bundle is checked before the demo build overwrites dist/.
    guard = next(i for i, r in enumerate(runs) if "mockServiceWorker" in r)
    assert runs.index("pnpm build") < guard < runs.index("pnpm build:demo")

# Phase 1 — CI access to AWS, a truthful Terraform plan, Dependabot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull requests plan under a read-only AWS role and see exactly what the deploy will apply; only the `production` environment can assume the admin deploy role; Dependabot PRs can pass CI; the open-PR backlog is cleared.

**Architecture:** A new Terraform-managed role `clouder-prod-gha-plan` (`ReadOnlyAccess`, trusted only by `pull_request`) replaces the admin role in `pr.yml`. Every plan and apply reads one `infra/prod.tfvars` plus the same `TF_VAR_*` inputs, so the PR plan equals the deploy. The admin role `github-actions-terraform` (created by hand at bootstrap) is re-trusted to `environment:production` only and its ARN moves to that environment. Two PRs, because the plan role must exist before `pr.yml` can use it.

**Tech Stack:** GitHub Actions, Terraform 1.14 / AWS provider ~> 5.0, AWS IAM OIDC, Dependabot, pytest + PyYAML for workflow tests.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` — §0 phase 1 and §1.4 items 1–3 (outside the repo). Evidence gathered 2026-10-10: role `github-actions-terraform` has `AdministratorAccess` and trusts `sub` ∈ {`repo:tarodo/clouder-core:ref:refs/heads/main`, `…:pull_request`, `…:environment:production`}; `AWS_GITHUB_ROLE_ARN` is a repo-level secret used by both workflows; the PR plan on 2026-10-10 (run 38057144973) showed `aws_sns_topic.alarms[0]` **destroyed** and all 18 Lambdas changing because it lacks the deploy's variables and `TF_VAR_*` secrets; `SPOTIFY_OAUTH_REDIRECT_URI`, `ADMIN_SPOTIFY_IDS`, `ALLOWED_FRONTEND_REDIRECTS` are `production`-environment variables (docs claim repo variables); Dependabot pip PRs fail the lock-drift check by construction (its compiled `.txt` differs from `uv pip compile --universal`).

## Global Constraints

- Work in the worktree `<repo>` (branch `feat/ci-plan-role` from `origin/main`); PR B gets a fresh branch from `origin/main` after PR A merges.
- Run tests with the main repo's venv: `PYTHONPATH=src <repo>/.venv/bin/pytest …` from the worktree root.
- Commit and PR text come from the `caveman:caveman-commit` skill; subject `type(scope): subject` ≤ 50 chars; multi-line bodies via heredoc; no `Co-Authored-By`, no "Generated with" footer.
- `main` is PR-only with 8 required checks; every merge to `main` deploys to production.
- No real AWS account id in any tracked file (`tests/unit/test_docs_freshness.py` and friends fail); build ARNs from `data.aws_caller_identity.current`.
- No money figures in docs; secret values are never printed in a terminal, a log or a commit — pipe them straight into `gh secret set`.
- Region `us-east-1`; resource prefix `clouder-prod-` (`local.name_prefix`).

## Review Focus

1. **`prod.tfvars` misses a value the deploy used to pass** → the next deploy silently flips a feature (e.g. `spotify_search_enabled` back to `false`). Pinned by `test_prod_tfvars_keeps_the_deployed_values` (Task 2) and by the PR A plan, which must show only the two plan-role resources.
2. **PR plan still lacks an input** (a GitHub variable or `TF_VAR_*` secret not visible to PR jobs) → alarms/topic/budget/Lambda env show as changing. Pinned by `test_plan_and_apply_get_the_same_inputs` (Task 3) and the PR A plan check (Task 4).
3. **Trust tightening locks the deploy out** → `Deploy` fails at OIDC. Rollback JSON saved in Task 0; verified by a manual Deploy run in Task 7.
4. **The Dependabot branch of the `terraform` job also triggers for human PRs** (or the reverse: human PRs skip the plan). Pinned by `test_dependabot_prs_validate_without_aws` (Task 5) using the PR author, not `github.actor`.
5. **A dependency install runs with AWS credentials** (`pip install` in `package_lambda.sh`). Pinned by `test_lambda_is_packaged_before_any_aws_credentials` (Task 3).

---

### Task 0: Pre-flight (out-of-band, no commit)

**Files:** none in the repo; scratchpad `$S=<scratchpad>`.

- [ ] **Step 1: Save the current trust policy for rollback**

```bash
aws iam get-role --role-name github-actions-terraform \
  --query 'Role.AssumeRolePolicyDocument' --output json > "$S/gha-terraform-trust.before.json"
```

- [ ] **Step 2: Copy the three `production` variables to repository level** (values stay identical; the env copies are deleted in Task 4)

```bash
for n in SPOTIFY_OAUTH_REDIRECT_URI ADMIN_SPOTIFY_IDS ALLOWED_FRONTEND_REDIRECTS; do
  gh variable list --env production --json name,value --jq ".[] | select(.name==\"$n\") | .value" \
    | gh variable set "$n" --repo tarodo/clouder-core
done
gh variable list --repo tarodo/clouder-core --json name --jq '.[].name'
```
Expected: the list contains the three names plus `TF_LOCK_TABLE`, `TF_STATE_BUCKET`.

- [ ] **Step 3: Copy the three Terraform-input secrets to repository level from the Terraform state** (never echoed)

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
STATE_BUCKET=$(gh variable list --json name,value --jq '.[] | select(.name=="TF_STATE_BUCKET") | .value')
aws s3 cp "s3://$STATE_BUCKET/clouder-core/prod/terraform.tfstate" "$S/tfstate.json" --quiet
python3 - "$S/tfstate.json" > "$S/secrets.env" <<'PY'
import json, sys
state = json.load(open(sys.argv[1]))
def attr(rtype, name):
    for r in state["resources"]:
        if r["type"] == rtype and r["name"] == name:
            return r["instances"][0]["attributes"]
print("ALARM_EMAIL=" + attr("aws_sns_topic_subscription", "alarm_email")["endpoint"])
print("BUDGET_MONTHLY_LIMIT=" + attr("aws_budgets_budget", "monthly")["limit_amount"])
print("BEATPORT_CLIENT_ID=" + attr("aws_lambda_function", "auto_ingest")["environment"][0]["variables"]["BEATPORT_CLIENT_ID"])
PY
while IFS='=' read -r name value; do printf '%s' "$value" | gh secret set "$name" --repo tarodo/clouder-core; done < "$S/secrets.env"
rm -f "$S/secrets.env" "$S/tfstate.json"
gh secret list --repo tarodo/clouder-core --json name --jq '.[].name'
```
Expected: `ALARM_EMAIL`, `AWS_GITHUB_ROLE_ARN`, `BEATPORT_CLIENT_ID`, `BUDGET_MONTHLY_LIMIT`. If `limit_amount` in state differs in format from the old secret (e.g. `20.0` vs `20`), the PR A plan (Task 4) shows the budget changing — then set the secret to the state's exact string and re-run.

---

### Task 1: Read-only plan role in Terraform

**Files:**
- Create: `infra/ci_roles.tf`
- Modify: `infra/variables.tf` (append `github_repository`), `infra/outputs.tf` (append output)
- Test: `tests/unit/test_ci_roles_infra.py`

**Interfaces:**
- Produces: `aws_iam_role.gha_plan` named `clouder-prod-gha-plan`; output `gha_plan_role_arn` (Task 4 reads it into the repo secret `AWS_PLAN_ROLE_ARN`).

- [ ] **Step 1: Write the failing test** — `tests/unit/test_ci_roles_infra.py`

```python
"""CI roles: pull requests plan under a read-only role only they can assume (ADR-0028)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_ROLES = ROOT / "infra" / "ci_roles.tf"


def test_plan_role_only_reads() -> None:
    tf = CI_ROLES.read_text()
    assert re.findall(r'policy_arn\s*=\s*"([^"]+)"', tf) == ["arn:aws:iam::aws:policy/ReadOnlyAccess"]
    assert 'resource "aws_iam_role_policy"' not in tf  # no inline grants


def test_only_pull_request_jobs_can_assume_the_plan_role() -> None:
    tf = CI_ROLES.read_text()
    assert re.findall(r'"repo:\$\{var\.github_repository\}:([^"]+)"', tf) == ["pull_request"]
    assert '"token.actions.githubusercontent.com:aud"' in tf
    assert '"sts.amazonaws.com"' in tf
    assert tf.count('test     = "StringEquals"') == 2
```

- [ ] **Step 2: Run it to see it fail**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_ci_roles_infra.py -q`
Expected: FAIL — `FileNotFoundError: …/infra/ci_roles.tf`.

- [ ] **Step 3: Implement** — `infra/ci_roles.tf`

```hcl
# ── CI roles (ADR-0028) ──
# Pull requests run `terraform plan` under this read-only role; only pull-request
# jobs of this repository can assume it. The deploy role (admin, created by hand at
# bootstrap, outside this configuration) is trusted only by the `production`
# environment — see docs/ops/deploy.md.

data "aws_iam_policy_document" "gha_plan_assume" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:pull_request"]
    }
  }
}

resource "aws_iam_role" "gha_plan" {
  name               = "${local.name_prefix}-gha-plan"
  description        = "Read-only terraform plan for pull requests (ADR-0028)"
  assume_role_policy = data.aws_iam_policy_document.gha_plan_assume.json
}

# Planning reads every managed resource and the state (which holds the JWT signing
# key); it never needs to write. The SSM SecureString read works through the
# aws/ssm managed key's own policy.
resource "aws_iam_role_policy_attachment" "gha_plan_read_only" {
  role       = aws_iam_role.gha_plan.name
  policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}
```

Append to `infra/variables.tf`:

```hcl
variable "github_repository" {
  description = "owner/name of the GitHub repository whose pull requests may assume the plan role."
  type        = string
  default     = "tarodo/clouder-core"
}
```

Append to `infra/outputs.tf`:

```hcl
output "gha_plan_role_arn" {
  description = "Read-only role for terraform plan in pull requests (GitHub secret AWS_PLAN_ROLE_ARN)"
  value       = aws_iam_role.gha_plan.arn
}
```

- [ ] **Step 4: Run the test and `terraform fmt`**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_ci_roles_infra.py -q && (cd infra && terraform fmt -check -recursive)`
Expected: `2 passed`, fmt prints nothing.

- [ ] **Step 5: Commit** (message via `caveman:caveman-commit`; expected shape `feat(infra): read-only plan role for PRs`)

```bash
git add infra/ci_roles.tf infra/variables.tf infra/outputs.tf tests/unit/test_ci_roles_infra.py
git commit -m "<caveman-commit subject>"
```

---

### Task 2: One `prod.tfvars`, a committed provider lock, a sensitive budget

**Files:**
- Create: `infra/prod.tfvars`, `infra/.terraform.lock.hcl`
- Modify: `.gitignore`, `infra/budgets.tf:5-9`
- Test: `tests/unit/test_deploy_order.py` (replace `test_both_applies_pass_the_same_variables`)

**Interfaces:**
- Produces: `infra/prod.tfvars` — Task 3 passes `-var-file=prod.tfvars` (working directory `infra`) to the PR plan and both deploy applies.

- [ ] **Step 1: Write the failing tests** — in `tests/unit/test_deploy_order.py` replace `test_both_applies_pass_the_same_variables` with:

```python
PROD_TFVARS = DEPLOY.parents[2] / "infra" / "prod.tfvars"

# Exactly what deploy.yml passed as -var before 2026-10-10 (minus the three GitHub variables).
DEPLOYED = {
    "environment": '"prod"',
    "canonicalization_enabled": "true",
    "silver_events_table": '"clouder_silver.events"',
    "gemini_api_key_ssm_parameter": '"/clouder/gemini/api_key"',
    "openai_api_key_ssm_parameter": '"/clouder/openai/api_key"',
    "tavily_api_key_ssm_parameter": '"/clouder/tavily/api_key"',
    "deepseek_api_key_ssm_parameter": '"/clouder/deepseek/api_key"',
    "spotify_search_enabled": "true",
    "vendor_match_enabled": "true",
    "spotify_client_id_ssm_parameter": '"/clouder/spotify/client_id"',
    "spotify_client_secret_ssm_parameter": '"/clouder/spotify/client_secret"',
    "ytmusic_client_id_ssm_parameter": '"/clouder/ytmusic/client_id"',
    "ytmusic_client_secret_ssm_parameter": '"/clouder/ytmusic/client_secret"',
    "youtube_api_key_ssm_parameter": '"/clouder/youtube/api_key"',
    "migration_aurora_auth_mode": '"iam"',
    "enable_secretsmanager_vpc_endpoint": "false",
}


def test_prod_tfvars_keeps_the_deployed_values() -> None:
    pairs = {}
    for line in PROD_TFVARS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, value = (part.strip() for part in line.split("=", 1))
            pairs[key] = value
    assert pairs == DEPLOYED


def test_both_applies_read_prod_tfvars_and_nothing_else() -> None:
    steps = {s.get("name"): s for s in yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]}
    for name in ("Terraform apply (migration Lambda only)", "Terraform apply"):
        run = steps[name]["run"]
        assert "-var-file=prod.tfvars" in run
        assert "-var=" not in run
```

- [ ] **Step 2: Run them to see them fail**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_deploy_order.py -q`
Expected: 2 FAIL (`FileNotFoundError` for `prod.tfvars`; `-var-file` missing).

- [ ] **Step 3: Create `infra/prod.tfvars`**

```hcl
# Non-secret production values. Every terraform plan and apply reads this file: the
# pull-request plan and both deploy phases (ADR-0028). Secrets and environment URLs
# arrive as TF_VAR_* from GitHub (docs/ops/deploy.md).
environment                         = "prod"
canonicalization_enabled            = true
silver_events_table                 = "clouder_silver.events"
gemini_api_key_ssm_parameter        = "/clouder/gemini/api_key"
openai_api_key_ssm_parameter        = "/clouder/openai/api_key"
tavily_api_key_ssm_parameter        = "/clouder/tavily/api_key"
deepseek_api_key_ssm_parameter      = "/clouder/deepseek/api_key"
spotify_search_enabled              = true
vendor_match_enabled                = true
spotify_client_id_ssm_parameter     = "/clouder/spotify/client_id"
spotify_client_secret_ssm_parameter = "/clouder/spotify/client_secret"
ytmusic_client_id_ssm_parameter     = "/clouder/ytmusic/client_id"
ytmusic_client_secret_ssm_parameter = "/clouder/ytmusic/client_secret"
youtube_api_key_ssm_parameter       = "/clouder/youtube/api_key"
migration_aurora_auth_mode          = "iam"
enable_secretsmanager_vpc_endpoint  = false
```

- [ ] **Step 4: `.gitignore`** — delete the line `.terraform.lock.hcl`; after the line `*.tfvars` add `!infra/prod.tfvars`. Check: `git check-ignore -v infra/prod.tfvars infra/.terraform.lock.hcl` prints nothing.

- [ ] **Step 5: Mark the budget amount sensitive** — `infra/budgets.tf`, variable `budget_monthly_limit`, add `sensitive   = true` after `default` (same as `alarm_email` in `variables.tf`), so a plan never prints it.

- [ ] **Step 6: Generate the provider lock**

```bash
cd infra
terraform init -backend=false -input=false >/dev/null
terraform providers lock -platform=linux_amd64 -platform=darwin_arm64 -platform=darwin_amd64
terraform fmt -check -recursive
cd ..
```
Expected: `.terraform.lock.hcl` lists `hashicorp/aws` (5.x) and `hashicorp/random` (3.x) with hashes for the three platforms.

- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_deploy_order.py tests/unit/test_guardrails_infra.py -q`
Expected: `test_prod_tfvars_keeps_the_deployed_values` passes; `test_both_applies_read_prod_tfvars_and_nothing_else` still fails (Task 3 changes `deploy.yml`); guardrails pass.

- [ ] **Step 8: Commit** (expected shape `chore(infra): prod.tfvars and provider lock`)

```bash
git add infra/prod.tfvars infra/.terraform.lock.hcl infra/budgets.tf .gitignore tests/unit/test_deploy_order.py
git commit -m "<caveman-commit subject>"
```

---

### Task 3: Workflows read the same inputs; no secrets in shell; package before credentials; one deploy at a time

**Files:**
- Modify: `.github/workflows/deploy.yml` (whole file below), `.github/workflows/pr.yml` (`terraform` job only)
- Test: `tests/unit/test_ci_workflows.py` (new)

**Interfaces:**
- Consumes: `infra/prod.tfvars` (Task 2).
- Produces: job-level `TF_VAR_*` env in `deploy.yml` and plan-step env in `pr.yml` with the same six names; PR B (Task 5) swaps only the role and adds the Dependabot branch.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_ci_workflows.py`

```python
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
```

- [ ] **Step 2: Run to see failures**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_ci_workflows.py -q`
Expected: 4 FAIL.

- [ ] **Step 3: Replace `.github/workflows/deploy.yml`** with exactly:

```yaml
name: Deploy

on:
  push:
    branches:
      - main
  # Re-sync GitHub secrets to SSM (e.g. Beatport credentials) without a code change.
  workflow_dispatch:

permissions:
  contents: read
  id-token: write

# One deploy at a time: a second merge waits for the first instead of racing it for
# the Terraform state lock and the frontend bucket.
concurrency:
  group: deploy-production
  cancel-in-progress: false

env:
  AWS_REGION: us-east-1

jobs:
  deploy:
    # A manual dispatch can pick any branch; only main reaches production.
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: infra
    env:
      # Every plan and apply reads infra/prod.tfvars plus these inputs; pr.yml passes the
      # same ones to the pull-request plan (ADR-0028, docs/ops/deploy.md).
      TF_VAR_spotify_oauth_redirect_uri: ${{ vars.SPOTIFY_OAUTH_REDIRECT_URI }}
      TF_VAR_admin_spotify_ids: ${{ vars.ADMIN_SPOTIFY_IDS }}
      TF_VAR_allowed_frontend_redirects: ${{ vars.ALLOWED_FRONTEND_REDIRECTS }}
      # Public, but Beatport can rotate it: a secret + manual deploy fixes it without code.
      TF_VAR_beatport_client_id: ${{ secrets.BEATPORT_CLIENT_ID }}
      TF_VAR_alarm_email: ${{ secrets.ALARM_EMAIL }}
      # Monthly budget amount; unset = no budget (the repo is public, no amount in it).
      TF_VAR_budget_monthly_limit: ${{ secrets.BUDGET_MONTHLY_LIMIT }}
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      # Before any AWS credentials exist: pip install runs third-party code.
      - name: Package Lambda
        working-directory: .
        run: scripts/package_lambda.sh

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_GITHUB_ROLE_ARN }}
          aws-region: ${{ env.AWS_REGION }}

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3

      - name: Terraform init
        env:
          TF_STATE_BUCKET: ${{ vars.TF_STATE_BUCKET }}
          TF_LOCK_TABLE: ${{ vars.TF_LOCK_TABLE }}
        run: |
          terraform init -input=false \
            -backend-config="bucket=$TF_STATE_BUCKET" \
            -backend-config="key=clouder-core/prod/terraform.tfstate" \
            -backend-config="region=us-east-1" \
            -backend-config="dynamodb_table=$TF_LOCK_TABLE" \
            -backend-config="encrypt=true"

      - name: Sync Beatport credentials to SSM (auto-ingest)
        working-directory: .
        env:
          BP_USER: ${{ secrets.BEATPORT_USERNAME }}
          BP_PASS: ${{ secrets.BEATPORT_PASSWORD }}
        run: |
          if [ -z "$BP_USER" ] || [ -z "$BP_PASS" ]; then
            echo "BEATPORT_USERNAME / BEATPORT_PASSWORD not set; skipping"
            exit 0
          fi
          aws ssm put-parameter --name /clouder/beatport/username \
            --value="$BP_USER" --type SecureString --overwrite >/dev/null
          aws ssm put-parameter --name /clouder/beatport/password \
            --value="$BP_PASS" --type SecureString --overwrite >/dev/null

      - name: Sync GitHub secrets to SSM Parameter Store
        working-directory: .
        env:
          GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
          TAVILY_API_KEY: ${{ secrets.TAVILY_API_KEY }}
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
          SPOTIFY_CLIENT_ID: ${{ secrets.SPOTIFY_CLIENT_ID }}
          SPOTIFY_CLIENT_SECRET: ${{ secrets.SPOTIFY_CLIENT_SECRET }}
          YTMUSIC_CLIENT_ID: ${{ secrets.YTMUSIC_CLIENT_ID }}
          YTMUSIC_CLIENT_SECRET: ${{ secrets.YTMUSIC_CLIENT_SECRET }}
          YOUTUBE_API_KEY: ${{ secrets.YOUTUBE_API_KEY }}
        run: |
          put() {
            aws ssm put-parameter --name "$1" --value="$2" --type SecureString --overwrite >/dev/null
          }
          put /clouder/gemini/api_key "$GEMINI_API_KEY"
          put /clouder/openai/api_key "$OPENAI_API_KEY"
          put /clouder/tavily/api_key "$TAVILY_API_KEY"
          put /clouder/deepseek/api_key "$DEEPSEEK_API_KEY"
          put /clouder/spotify/client_id "$SPOTIFY_CLIENT_ID"
          put /clouder/spotify/client_secret "$SPOTIFY_CLIENT_SECRET"
          put /clouder/ytmusic/client_id "$YTMUSIC_CLIENT_ID"
          put /clouder/ytmusic/client_secret "$YTMUSIC_CLIENT_SECRET"
          put /clouder/youtube/api_key "$YOUTUBE_API_KEY"

      # Two-phase apply, deliberately. The migration Lambda and the collector
      # API ship from the same zip, so the migration Lambda only receives new
      # alembic revisions via terraform apply. Applying everything at once
      # updated the API first and left it querying a schema that had not caught
      # up yet — measured at 2m40s of 500s on GET /styles during the 2026-09-20
      # deploy. So: bring the migration Lambda up first, run the migration, then
      # apply the rest. -target is normally an emergency tool; here it is the
      # bootstrap ordering this pipeline needs. Both phases read prod.tfvars.
      - name: Terraform apply (migration Lambda only)
        run: |
          terraform apply -auto-approve -input=false \
            -target=aws_lambda_function.db_migration \
            -var-file=prod.tfvars

      - name: Run DB migrations via Lambda
        run: |
          MIGRATION_FN="$(terraform output -raw migration_lambda_function_name)"
          aws lambda invoke \
            --function-name "$MIGRATION_FN" \
            --payload '{"action":"upgrade","revision":"head"}' \
            --cli-binary-format raw-in-base64-out \
            /tmp/migration-response.json \
            > /tmp/migration-meta.json

          python - <<'PY'
          import json
          import pathlib
          import sys

          meta = json.loads(pathlib.Path("/tmp/migration-meta.json").read_text())
          raw_response = pathlib.Path("/tmp/migration-response.json").read_text() or "{}"
          try:
              response = json.loads(raw_response)
          except json.JSONDecodeError:
              response = {"raw": raw_response}

          print("Migration invoke meta:", json.dumps(meta, ensure_ascii=False))
          print("Migration lambda response:", json.dumps(response, ensure_ascii=False))

          if meta.get("FunctionError"):
              sys.exit("Migration Lambda returned FunctionError")

          if isinstance(response, dict) and response.get("status") != "ok":
              sys.exit("Migration Lambda returned non-ok status")
          PY

      - name: Terraform apply
        run: terraform apply -auto-approve -input=false -var-file=prod.tfvars

      - name: Setup pnpm
        uses: pnpm/action-setup@v4
        with:
          version: 9

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: frontend/pnpm-lock.yaml

      - name: Deploy frontend (S3 + CloudFront)
        working-directory: .
        run: scripts/deploy_frontend.sh
```

- [ ] **Step 4: Replace the `terraform` job in `.github/workflows/pr.yml`** (still the old role in PR A) with exactly:

```yaml
  terraform:
    needs: changes
    if: needs.changes.outputs.infra == 'true'
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      # Before any AWS credentials exist: pip install runs third-party code.
      - name: Package Lambda
        working-directory: .
        run: scripts/package_lambda.sh

      - name: Setup Terraform
        uses: hashicorp/setup-terraform@v3

      - name: Terraform fmt
        run: terraform fmt -check -recursive

      - name: Configure AWS credentials (OIDC)
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_GITHUB_ROLE_ARN }}
          aws-region: us-east-1

      - name: Terraform init
        env:
          TF_STATE_BUCKET: ${{ vars.TF_STATE_BUCKET }}
          TF_LOCK_TABLE: ${{ vars.TF_LOCK_TABLE }}
        run: |
          terraform init -input=false \
            -backend-config="bucket=$TF_STATE_BUCKET" \
            -backend-config="key=clouder-core/prod/terraform.tfstate" \
            -backend-config="region=us-east-1" \
            -backend-config="dynamodb_table=$TF_LOCK_TABLE" \
            -backend-config="encrypt=true"

      - name: Terraform validate
        run: terraform validate

      # The same inputs as deploy.yml, so the plan shows what the deploy would apply.
      - name: Terraform plan
        env:
          TF_VAR_spotify_oauth_redirect_uri: ${{ vars.SPOTIFY_OAUTH_REDIRECT_URI }}
          TF_VAR_admin_spotify_ids: ${{ vars.ADMIN_SPOTIFY_IDS }}
          TF_VAR_allowed_frontend_redirects: ${{ vars.ALLOWED_FRONTEND_REDIRECTS }}
          TF_VAR_beatport_client_id: ${{ secrets.BEATPORT_CLIENT_ID }}
          TF_VAR_alarm_email: ${{ secrets.ALARM_EMAIL }}
          TF_VAR_budget_monthly_limit: ${{ secrets.BUDGET_MONTHLY_LIMIT }}
        run: terraform plan -input=false -lock=false -var-file=prod.tfvars
```

Both `Terraform init` steps take the backend names through step `env`, because `test_secrets_reach_shell_steps_only_through_env` forbids `${{ vars.` and `${{ secrets.` inside `run`.

In `tests/unit/test_deploy_order.py`, `import re` became unused when Task 2 replaced the `-var` test — delete it so ruff stays clean.

- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_ci_workflows.py tests/unit/test_deploy_order.py tests/unit/test_guardrails_infra.py tests/unit/test_dependency_locks.py -q`
Expected: all pass.

- [ ] **Step 6: Full backend suite + lint**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest -q && <repo>/.venv/bin/ruff check src tests scripts`
Expected: all pass (DB tests skip), ruff clean.

- [ ] **Step 7: Commit** (expected shape `ci: same plan inputs, secrets via env`)

```bash
git add .github/workflows/deploy.yml .github/workflows/pr.yml tests/unit/test_ci_workflows.py
git commit -m "<caveman-commit subject>"
```

---

### Task 4: PR A — open, verify the plan, merge, deploy, wire the plan role

**Files:** this plan file (`docs/superpowers/plans/2026-10-10-phase1-ci-access.md`) is committed with PR A.

- [ ] **Step 1: Commit the plan** (expected shape `docs(plans): phase 1 CI access plan`) and push: `git push -u origin feat/ci-plan-role`.
- [ ] **Step 2: Open the PR** — title and body from `caveman:caveman-commit`; body says what changed, why (audit phase 1), how verified. `gh pr create --base main --head feat/ci-plan-role --title "…" --body "$(cat <<'EOF' … EOF)"`.
- [ ] **Step 3: Wait for checks** — `gh pr checks <n> --watch --interval 30`. All required checks green.
- [ ] **Step 4: Read the plan** — `gh run view <run> --log | grep '^terraform' | grep -E 'Plan:|will be|must be'`. Expected: `Plan: 2 to add, 0 to change, 0 to destroy.` with `aws_iam_role.gha_plan` and `aws_iam_role_policy_attachment.gha_plan_read_only`. Lambda `source_code_hash` updates are acceptable only if `package_lambda.sh` is not byte-reproducible; any change to an alarm, the SNS topic, the budget, an IAM policy, API Gateway, CloudFront or a Lambda `environment` block means an input is missing — fix it before merging.
- [ ] **Step 5: Merge** — `gh pr merge <n> --merge`; then `gh run watch $(gh run list --workflow Deploy --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status`. Expected: Deploy green.
- [ ] **Step 6: Wire the plan role**

```bash
aws iam get-role --role-name clouder-prod-gha-plan --query 'Role.Arn' --output text \
  | gh secret set AWS_PLAN_ROLE_ARN --repo tarodo/clouder-core
```

- [ ] **Step 7: Drop the `production` duplicates** — only for values that exist at repo level, or the next deploy loses them. Check first, delete only what the check lists:

```bash
gh variable list --repo tarodo/clouder-core --json name --jq '.[].name'   # expect the three below
gh secret list --repo tarodo/clouder-core --json name --jq '.[].name'     # BEATPORT_CLIENT_ID must be here before its env copy goes
for n in SPOTIFY_OAUTH_REDIRECT_URI ADMIN_SPOTIFY_IDS ALLOWED_FRONTEND_REDIRECTS; do gh variable delete "$n" --env production --repo tarodo/clouder-core; done
gh secret delete ALARM_EMAIL --env production --repo tarodo/clouder-core
# Only after `gh secret set BEATPORT_CLIENT_ID --repo tarodo/clouder-core` (value from the env copy):
gh secret delete BEATPORT_CLIENT_ID --env production --repo tarodo/clouder-core
```
`BUDGET_MONTHLY_LIMIT` is unset in both places (no budget exists); nothing to move.

---

### Task 5: PR B — the PR plan runs read-only; Dependabot passes CI; docs and ADR

**Files:**
- Modify: `.github/workflows/pr.yml` (`terraform` job), `.github/dependabot.yml`, `Makefile`, `docs/ops/deploy.md`, `docs/security.md`, `docs/adr/README.md`, `README.md` (ADR count 27 → 28)
- Create: `docs/adr/0028-ci-roles.md`
- Test: `tests/unit/test_ci_workflows.py` (append), `tests/unit/test_dependency_locks.py` (append)

**Interfaces:**
- Consumes: repo secret `AWS_PLAN_ROLE_ARN` (Task 4).

- [ ] **Step 1: Branch** — `git fetch origin && git switch -c feat/ci-plan-readonly origin/main` in the worktree.

- [ ] **Step 2: Failing tests** — append to `tests/unit/test_ci_workflows.py`:

```python
HUMAN = "github.event.pull_request.user.login != 'dependabot[bot]'"
BOT = "github.event.pull_request.user.login == 'dependabot[bot]'"


def test_pull_requests_plan_with_the_read_only_role() -> None:
    creds = next(s for s in PR["jobs"]["terraform"]["steps"] if "configure-aws-credentials" in s.get("uses", ""))
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
```

Append to `tests/unit/test_dependency_locks.py`:

```python
def test_pip_version_updates_go_through_uv_not_dependabot() -> None:
    # Dependabot's compiled lock differs from `uv pip compile --universal`, so its pip
    # PRs always fail the lock-drift check; security updates still open.
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    pip_root = next(u for u in config["updates"] if (u["package-ecosystem"], u["directory"]) == ("pip", "/"))
    assert pip_root["open-pull-requests-limit"] == 0
    assert "upgrade:" in (ROOT / "Makefile").read_text()
```

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest tests/unit/test_ci_workflows.py tests/unit/test_dependency_locks.py -q` → 3 FAIL.

- [ ] **Step 3: `pr.yml` `terraform` job** — keep Task 3's version and change these steps exactly:

```yaml
      - name: Configure AWS credentials (OIDC)
        # Dependabot gets no repository secrets: its PRs validate without AWS (ADR-0028).
        if: github.event.pull_request.user.login != 'dependabot[bot]'
        uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_PLAN_ROLE_ARN }}
          aws-region: us-east-1

      - name: Terraform init
        if: github.event.pull_request.user.login != 'dependabot[bot]'
        env:
          TF_STATE_BUCKET: ${{ vars.TF_STATE_BUCKET }}
          TF_LOCK_TABLE: ${{ vars.TF_LOCK_TABLE }}
        run: |
          terraform init -input=false \
            -backend-config="bucket=$TF_STATE_BUCKET" \
            -backend-config="key=clouder-core/prod/terraform.tfstate" \
            -backend-config="region=us-east-1" \
            -backend-config="dynamodb_table=$TF_LOCK_TABLE" \
            -backend-config="encrypt=true"

      - name: Terraform init (no backend, Dependabot)
        if: github.event.pull_request.user.login == 'dependabot[bot]'
        run: terraform init -input=false -backend=false

      - name: Terraform validate
        run: terraform validate

      # The same inputs as deploy.yml, so the plan shows what the deploy would apply.
      - name: Terraform plan
        if: github.event.pull_request.user.login != 'dependabot[bot]'
        env:
          TF_VAR_spotify_oauth_redirect_uri: ${{ vars.SPOTIFY_OAUTH_REDIRECT_URI }}
          TF_VAR_admin_spotify_ids: ${{ vars.ADMIN_SPOTIFY_IDS }}
          TF_VAR_allowed_frontend_redirects: ${{ vars.ALLOWED_FRONTEND_REDIRECTS }}
          TF_VAR_beatport_client_id: ${{ secrets.BEATPORT_CLIENT_ID }}
          TF_VAR_alarm_email: ${{ secrets.ALARM_EMAIL }}
          TF_VAR_budget_monthly_limit: ${{ secrets.BUDGET_MONTHLY_LIMIT }}
        run: terraform plan -input=false -lock=false -var-file=prod.tfvars
```

The steps before (`Checkout`, `Setup Python`, `Package Lambda`, `Setup Terraform`, `Terraform fmt`) stay exactly as in Task 3 and run for every PR.

- [ ] **Step 4: `.github/dependabot.yml`** — replace with:

```yaml
version: 2
updates:
  # Root Python locks are compiled by uv (`make lock` / `make upgrade`); Dependabot's
  # own compile differs from `uv pip compile --universal` and fails the lock-drift check,
  # so version-update PRs are off here. Security-update PRs still open (re-lock with
  # `make lock` on their branch).
  - package-ecosystem: pip
    directory: /
    schedule: { interval: weekly }
    open-pull-requests-limit: 0
  - package-ecosystem: pip
    directory: /dbt
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
  - package-ecosystem: npm
    directory: /frontend
    schedule: { interval: weekly }
    open-pull-requests-limit: 5
    groups:
      npm-minor:
        update-types: [minor, patch]
    ignore:
      # v7 adds the React Compiler rules (6 errors today) — an upgrade of its own.
      - dependency-name: eslint-plugin-react-hooks
        update-types: [version-update:semver-major]
  - package-ecosystem: github-actions
    directory: /
    schedule: { interval: weekly }
    groups:
      actions:
        patterns: ["*"]
  - package-ecosystem: terraform
    directory: /infra
    schedule: { interval: weekly }
    ignore:
      # AWS provider v6 is a migration of its own.
      - dependency-name: hashicorp/aws
        update-types: [version-update:semver-major]
```

- [ ] **Step 5: `Makefile`** — add `upgrade` to `.PHONY` and after the `lock:` target:

```make
upgrade:         ## re-lock Python deps at the newest versions the .in files allow
	uv pip compile --universal --python-version 3.12 --upgrade requirements-lambda.in -o requirements-lambda.txt
	uv pip compile --universal --python-version 3.12 --upgrade requirements-dev.in -o requirements-dev.txt
```

- [ ] **Step 6: ADR** — create `docs/adr/0028-ci-roles.md`:

```markdown
# ADR-0028: A read-only plan role for pull requests, an environment-gated deploy role
Status: Accepted
Date: 2026-10-10

## Context

Both workflows assumed one role, `github-actions-terraform`, with AdministratorAccess. Its trust
policy accepted `ref:refs/heads/main`, `pull_request` and `environment:production`, and its ARN was
a repository secret, so any pull-request job could act as administrator before review — and
`scripts/package_lambda.sh` installed dependencies with those credentials in the environment. The
`production` environment's branch rule protected the deploy job, not the role.

The pull-request plan also ran with 2 of the 19 variables the deploy passed and without the
Terraform inputs held as secrets. On a PR that touched neither, it showed the alarm topic being
destroyed and every Lambda changing, so nobody could read it as a preview.

## Decision

- `clouder-prod-gha-plan` (`infra/ci_roles.tf`): `ReadOnlyAccess`, assumable only by
  `repo:tarodo/clouder-core:pull_request`. The PR plan runs under it with `-lock=false`.
- `github-actions-terraform` (created at bootstrap, outside Terraform) is trusted only by
  `repo:tarodo/clouder-core:environment:production`; its ARN is a secret of that environment.
- AWS credentials are configured after the Lambda is packaged, so no dependency install runs
  with them.
- `infra/prod.tfvars` holds every non-secret production value; the PR plan and both deploy phases
  read it with the same `TF_VAR_*` inputs. Inputs that are not credentials (alarm email, budget
  amount, Beatport client id) are repository secrets so the plan can see them; Terraform marks the
  email and the budget `sensitive`, so no plan prints them. Credentials (vendor API keys, the
  Beatport login) stay in the `production` environment and only reach SSM.
- Dependabot pull requests get no repository secrets; their Terraform check runs `fmt` and
  `validate` without AWS.

## Consequences

- A pull request can read the account — including the Terraform state, which holds the JWT
  signing key — but change nothing. Reading state is inherent to planning.
- The PR plan is a faithful preview: a change it does not show is not applied.
- The deploy role is still AdministratorAccess ([known gap](../security.md#known-gaps)); only the
  `production` environment, which accepts protected branches only, can assume it.
- Rebuilding the account needs the GitHub OIDC provider and the deploy role first; the plan role
  then comes from the first apply.
```

Add to `docs/adr/README.md` after the 0027 row:

```markdown
| 0028 | [A read-only plan role for pull requests, an environment-gated deploy role](0028-ci-roles.md) |
```

`README.md`: `Key decisions (all 27 in` → `Key decisions (all 28 in`; `- 27 Architecture Decision Records` → `- 28 Architecture Decision Records`.

- [ ] **Step 7: `docs/security.md`** — replace the first two rows of "4. GitHub ↔ AWS" and the first known gap:

```markdown
| Long-lived cloud credentials in CI | No AWS keys anywhere: both workflows assume roles through GitHub OIDC. Pull requests plan under a read-only role (`clouder-prod-gha-plan`) that only pull-request jobs can assume; credentials are configured after the Lambda is packaged, so no dependency install runs with them ([ADR-0028](adr/0028-ci-roles.md)). |
| A malicious or careless change deployed | `main` takes changes only through pull requests with 8 required checks (tests with a coverage gate, lint, types, Terraform, dbt, dependency audit, frontend); admins are not exempt. Only jobs in the `production` environment, which accepts protected branches only, can assume the deploy role; its ARN and the credentials it syncs exist only there. |
```

```markdown
- **The deploy role has AdministratorAccess.** Only the `production` environment can assume it, so a compromised `main` controls the whole account. The fix is a scoped role; it is deferred because the Terraform surface changes often and branch protection guards the path.
```

- [ ] **Step 8: `docs/ops/deploy.md`**
  - `terraform` row of the PR-checks table → `` `scripts/package_lambda.sh`, `terraform fmt -check`, then under the read-only role `clouder-prod-gha-plan`: `terraform init` (remote S3 backend), `terraform validate`, `terraform plan -var-file=prod.tfvars` with the deploy's `TF_VAR_*` inputs — the plan is what the deploy would apply. Dependabot PRs (no secrets) run `init -backend=false` + `validate` only ``.
  - Dependencies paragraph, last sentence → `` Dependabot opens weekly PRs for npm, GitHub Actions, Terraform and the dbt requirements; root Python locks are upgraded with `make upgrade` (its own compile would fail the lock-drift check), and its pip security PRs need `make lock` on their branch. ``
  - Step 1 of the deploy pipeline: append `` Runs before AWS credentials are configured. ``
  - Step 3: replace `` The `-var` list lives in `deploy.yml`; `TF_VAR_beatport_client_id` and `TF_VAR_alarm_email` come from secrets on the full apply. `` with `` Both phases read `infra/prod.tfvars` and the job-level `TF_VAR_*` inputs. ``
  - Add before step 1: `` Deploys never overlap: `concurrency: deploy-production` queues a second merge behind the first. ``
  - GitHub Secrets intro → `` Credentials — the vendor keys, the Beatport login and the deploy role — are scoped to the **`production` environment**. Terraform inputs that are not credentials are repo-root secrets, because the pull-request plan must see the same values as the deploy; Terraform marks the email and the budget `sensitive`. ``
  - Scope column: `BEATPORT_CLIENT_ID`, `ALARM_EMAIL`, `BUDGET_MONTHLY_LIMIT` → `Repo root`.
  - Replace the `AWS_GITHUB_ROLE_ARN` row with two rows:
    `| AWS_GITHUB_ROLE_ARN | production environment | Deploy role (OIDC), trusted only by this environment ([ADR-0028](../adr/0028-ci-roles.md)) |`
    `| AWS_PLAN_ROLE_ARN | Repo root | Read-only plan role `clouder-prod-gha-plan` for PR checks (`terraform output gha_plan_role_arn`) |`

- [ ] **Step 9: Run everything**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest -q && <repo>/.venv/bin/ruff check src tests scripts`
Expected: all pass (doc-link and README-count guards included).

- [ ] **Step 10: Commit** in two commits (messages via `caveman:caveman-commit`): `ci: plan PRs with read-only role` (pr.yml, dependabot.yml, Makefile, tests) and `docs: CI roles ADR and deploy docs` (ADR, README, security.md, deploy.md).

---

### Task 6: PR B — open, verify the read-only plan, merge

- [ ] **Step 1:** push `feat/ci-plan-readonly`, open the PR (title/body via `caveman:caveman-commit`).
- [ ] **Step 2:** `gh pr checks <n> --watch --interval 30` → all green.
- [ ] **Step 3:** In the `terraform` job log, confirm the role: `grep -E 'clouder-prod-gha-plan|No changes|Plan:'`. Expected: the assumed-role line names `clouder-prod-gha-plan` and the plan says `No changes.` If it fails with `AccessDenied` on a read API, add that one action as an inline statement in `infra/ci_roles.tf` (and relax `test_plan_role_only_reads` to allow exactly that statement), merge through the normal path, then re-run.
- [ ] **Step 4:** merge; watch Deploy → green.

---

### Task 7: Lock the deploy role to `production` (out-of-band)

- [ ] **Step 1: Move the deploy ARN to the environment**

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
printf 'arn:aws:iam::%s:role/github-actions-terraform' "$ACCT" \
  | gh secret set AWS_GITHUB_ROLE_ARN --env production --repo tarodo/clouder-core
gh secret delete AWS_GITHUB_ROLE_ARN --repo tarodo/clouder-core
```

- [ ] **Step 2: Re-trust the role**

```bash
python3 - "$S/gha-terraform-trust.before.json" > "$S/gha-terraform-trust.after.json" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
for st in doc["Statement"]:
    st["Condition"]["StringEquals"]["token.actions.githubusercontent.com:sub"] = [
        "repo:tarodo/clouder-core:environment:production"
    ]
print(json.dumps(doc))
PY
aws iam update-assume-role-policy --role-name github-actions-terraform \
  --policy-document "file://$S/gha-terraform-trust.after.json"
```

- [ ] **Step 3: Verify** — `gh workflow run deploy.yml --ref main`, then watch it → green. Rollback if red: `aws iam update-assume-role-policy --role-name github-actions-terraform --policy-document "file://$S/gha-terraform-trust.before.json"`.

---

### Task 8: Clear the PR backlog

- [ ] **Step 1: Close what cannot or should not merge, with a reason**

```bash
gh pr close 270 --comment "AWS provider v6 is a migration of its own; majors of hashicorp/aws are now ignored in dependabot.yml."
gh pr close 273 --comment "pglast 8 parses PostgreSQL 18 and Aurora runs 16 (tests/unit/test_raw_sql_parses.py pins the grammar). Root pip version updates now go through make upgrade (dependabot.yml explains why)."
gh pr close 275 --comment "v7 adds the React Compiler lint rules (6 errors today); that upgrade needs code changes of its own. Majors of this package are ignored for now."
gh pr close 119 --comment "Still blocked on the account concurrency quota (10). The switch enable_lambda_reserved_concurrency and per-worker values stay in Terraform; docs/scalability.md describes when to flip it."
gh pr close 185 --comment "June MVP review, superseded by docs/security.md, docs/ops/failure-modes.md and docs/design/decisions-to-revisit.md."
```

- [ ] **Step 2: Refresh the rest** — `gh pr comment 272 --body "@dependabot rebase"`, same for 271, 274, 276, 277, 278. Wait for their checks (`gh pr checks <n> --watch`).

- [ ] **Step 3: Merge the green ones, one at a time, each followed by a green Deploy** — expected green: #278 (msw), #277 (jest-dom, dev only), #272 (actions), #271 (dbt-core). For #271, after its deploy start the transform once and require `SUCCEEDED`: `aws stepfunctions start-execution --state-machine-arn $(aws stepfunctions list-state-machines --query 'stateMachines[?name==\`clouder-prod-transform\`].stateMachineArn' --output text)` and poll `describe-execution`.

- [ ] **Step 4: #276 (i18next 23 → 26, runtime major)** — merge only if green and `pnpm why i18next` on its branch shows no peer conflict with `react-i18next`; after its deploy, open the site's login page in the browser and confirm text renders as words, not translation keys. Otherwise close with the reason and an `ignore` for its major.

- [ ] **Step 5: #274 (npm-minor group)** — read the failing `frontend` step on the refreshed run. If one package's minor breaks tests, close the group PR with that package named and add it to the npm `ignore` with `update-types: [version-update:semver-minor]` and a one-line reason (via a small PR); otherwise merge when green.

- [ ] **Step 6:** `gh pr list --state open` → empty or only PRs opened after this phase.

---

### Task 9: Close the phase

- [ ] Update §0 of `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md`: phase 1 → `done`, plan path, PR A and PR B links, one line on what moved out-of-band (variables, secrets, trust).
- [ ] Update memory `project_clouder_hiring_audit.md`: phase 1 done; the deploy role is now `environment:production`-only.
- [ ] Remove the worktree when no later phase needs it: `git worktree remove ../clouder-core-p1`.

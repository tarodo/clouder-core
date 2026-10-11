# Deploy Role without AdministratorAccess — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The production deploy role (`github-actions-terraform`, created at bootstrap outside Terraform) gets a policy limited to the AWS services Terraform manages and to the project's own IAM roles, instead of AdministratorAccess; a guard test keeps the policy in step with the Terraform code.

**Architecture:** The policy lives in the repo as `infra/bootstrap/deploy-role-policy.json` with a README that says how it is applied and rolled back (the role is not Terraform's, so the owner applies it). Its service list comes from 90 days of IAM "service last accessed" data for the role (no CloudTrail trail exists, so IAM Access Analyzer policy generation is not available) cross-checked with the resource types in `infra/`. IAM writes are allowed only on `clouder-prod-*` roles and policies; attaching any managed policy except `ReadOnlyAccess` (the plan role's) is denied, and the role can never touch itself. A test maps every Terraform resource type to its IAM namespace and fails when the policy lacks one — a new service breaks the PR, not the deploy.

**Tech Stack:** IAM policy JSON, pytest, AWS CLI (IAM policy simulator, read-only).

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-11.ru.md` §6 IAM, §1.4 п. 6, §0.3 phase 6; `docs/security.md` known gap "The deploy role has AdministratorAccess"; ADR-0028.

## Global Constraints

- Worktree `../clouder-core-loop`, branch `feat/deploy-role-scope` from `origin/main`; tools from the main checkout's `.venv/bin/`.
- Services the role used in the last 90 days (IAM last accessed, 2026-10-11): apigateway, athena, cloudfront, cloudwatch, codebuild, dynamodb, ec2, ecr (last 2026-07-02, no longer used), events, firehose, glue, iam, kms, lambda, logs, rds, s3, scheduler, secretsmanager (RDS-managed master secret), servicequotas, sns, sqs, ssm, states, sts. Terraform also defines `aws_budgets_budget` (created only when the budget secret is set) → `budgets`.
- Applying the policy to the role is the owner's step (IAM outside Terraform). The agent may run the IAM policy simulator (read-only).
- No money figures; English; commit messages from `caveman:caveman-commit`; no AI attribution.

## Review Focus

1. **A deploy must not break**: every action the last-accessed data tracked is allowed by the new policy (policy simulator), and every Terraform resource type maps to an allowed namespace (test).
2. **No privilege escalation through attach**: attaching AdministratorAccess (or any managed policy but ReadOnlyAccess) to a project role is denied. Inline `PutRolePolicy` on `clouder-prod-*` roles stays possible — say so as the remaining gap (permission boundaries are the next step).
3. **The role cannot edit itself** (explicit Deny on `role/github-actions-terraform`).
4. **Every IAM role Terraform creates is named `clouder-prod-*`**, or the IAM statement would not cover it (test).
5. **Rollback is one command** (re-attach AdministratorAccess) and written down before the switch.

---

### Task 1: The policy and its guard

**Files:** Create `infra/bootstrap/deploy-role-policy.json`, `infra/bootstrap/README.md`, `tests/unit/test_deploy_role_policy.py`.

- [ ] **Step 1: Failing tests** — `tests/unit/test_deploy_role_policy.py`:

```python
"""The deploy role's policy covers every AWS service Terraform manages, and nothing more (ADR-0028)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
POLICY = json.loads((INFRA / "bootstrap" / "deploy-role-policy.json").read_text())
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")) + sorted(INFRA.glob("modules/*/*.tf")))

# Terraform resource-type prefix → the IAM namespace that creates it.
NAMESPACE = {
    "aws_apigatewayv2_": "apigateway", "aws_athena_": "athena", "aws_budgets_": "budgets",
    "aws_cloudfront_": "cloudfront", "aws_cloudwatch_dashboard": "cloudwatch",
    "aws_cloudwatch_metric_alarm": "cloudwatch", "aws_cloudwatch_event_": "events",
    "aws_cloudwatch_log_": "logs", "aws_codebuild_": "codebuild", "aws_db_": "rds",
    "aws_rds_": "rds", "aws_glue_": "glue", "aws_iam_": "iam", "aws_kinesis_firehose_": "firehose",
    "aws_kms_": "kms", "aws_lambda_": "lambda", "aws_s3_": "s3", "aws_scheduler_": "scheduler",
    "aws_security_group": "ec2", "aws_subnet": "ec2", "aws_vpc": "ec2", "aws_sfn_": "states",
    "aws_sns_": "sns", "aws_sqs_": "sqs", "aws_ssm_": "ssm", "aws_servicequotas_": "servicequotas",
}


def _allowed() -> set[str]:
    actions = [a for s in POLICY["Statement"] if s["Effect"] == "Allow" for a in s["Action"]]
    return {a.split(":")[0] for a in actions}


def test_every_terraform_resource_type_is_covered() -> None:
    types = set(re.findall(r'(?:resource|data) "(aws_[a-z0-9_]+)"', TF)) - {
        "aws_iam_policy_document",  # rendered locally
        "aws_caller_identity", "aws_availability_zones",  # sts / ec2 reads
    }
    for t in sorted(types):
        ns = next((n for prefix, n in NAMESPACE.items() if t.startswith(prefix)), None)
        assert ns, f"{t}: add its IAM namespace to NAMESPACE and to deploy-role-policy.json"
        assert ns in _allowed(), f"{t} needs {ns}:* in infra/bootstrap/deploy-role-policy.json"
    # The Terraform backend: state in S3, lock in DynamoDB.
    assert {"s3", "dynamodb"} <= _allowed()


def test_iam_writes_only_on_project_roles() -> None:
    (iam,) = [s for s in POLICY["Statement"] if s.get("Sid") == "IamOnProjectRoles"]
    assert iam["Action"] == ["iam:*"]
    assert all(":role/clouder-prod-" in r or ":policy/clouder-prod-" in r for r in iam["Resource"])
    for name in re.findall(r'resource "aws_iam_role" "[a-z_]+" \{\s*name\s*=\s*"([^"]+)"', TF):
        assert name.startswith("${local.name_prefix}-"), name
    for name in re.findall(r'module "role_[a-z_]+" \{[^}]*?name\s*=\s*"([^"]+)"', TF, re.S):
        assert name.startswith("${local.name_prefix}-"), name


def test_no_managed_policy_but_read_only_can_be_attached() -> None:
    (deny,) = [s for s in POLICY["Statement"] if s.get("Sid") == "OnlyReadOnlyAccessAttached"]
    assert deny["Effect"] == "Deny"
    assert set(deny["Action"]) == {"iam:AttachRolePolicy", "iam:DetachRolePolicy"}
    assert deny["Condition"] == {
        "ArnNotEquals": {"iam:PolicyARN": "arn:aws:iam::aws:policy/ReadOnlyAccess"}
    }
    assert "ReadOnlyAccess" in TF  # the one attachment Terraform makes (the plan role)


def test_the_role_cannot_change_itself() -> None:
    (deny,) = [s for s in POLICY["Statement"] if s.get("Sid") == "NotItself"]
    assert deny["Effect"] == "Deny" and deny["Action"] == ["iam:*"]
    assert deny["Resource"] == ["arn:aws:iam::*:role/github-actions-terraform"]


def test_no_wildcard_for_everything() -> None:
    actions = [a for s in POLICY["Statement"] if s["Effect"] == "Allow" for a in s["Action"]]
    assert "*" not in actions and "*:*" not in actions and "ecr:*" not in actions
```

- [ ] **Step 2: Run** → errors (files missing).
- [ ] **Step 3: `infra/bootstrap/deploy-role-policy.json`** —

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ServicesTerraformManages",
      "Effect": "Allow",
      "Action": [
        "apigateway:*", "athena:*", "budgets:*", "cloudfront:*", "cloudwatch:*", "codebuild:*",
        "dynamodb:*", "ec2:*", "events:*", "firehose:*", "glue:*", "kms:*", "lambda:*", "logs:*",
        "rds:*", "s3:*", "scheduler:*", "secretsmanager:*", "servicequotas:*", "sns:*", "sqs:*",
        "ssm:*", "states:*", "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    },
    {
      "Sid": "IamOnProjectRoles",
      "Effect": "Allow",
      "Action": ["iam:*"],
      "Resource": ["arn:aws:iam::*:role/clouder-prod-*", "arn:aws:iam::*:policy/clouder-prod-*"]
    },
    {
      "Sid": "IamReadAndServiceLinkedRoles",
      "Effect": "Allow",
      "Action": ["iam:Get*", "iam:List*", "iam:CreateServiceLinkedRole"],
      "Resource": "*"
    },
    {
      "Sid": "OnlyReadOnlyAccessAttached",
      "Effect": "Deny",
      "Action": ["iam:AttachRolePolicy", "iam:DetachRolePolicy"],
      "Resource": "*",
      "Condition": {"ArnNotEquals": {"iam:PolicyARN": "arn:aws:iam::aws:policy/ReadOnlyAccess"}}
    },
    {
      "Sid": "NotItself",
      "Effect": "Deny",
      "Action": ["iam:*"],
      "Resource": ["arn:aws:iam::*:role/github-actions-terraform"]
    }
  ]
}
```

- [ ] **Step 4: `infra/bootstrap/README.md`** — what this folder is (things Terraform cannot own because it needs them to run: the OIDC provider, the deploy role and its policy, the state bucket and lock table — today only the policy is written down here); how the policy was derived (IAM last accessed, 90 days, 2026-10-11; no CloudTrail trail for Access Analyzer); apply / verify / rollback commands:

```bash
ACCT=$(aws sts get-caller-identity --query Account --output text)
aws iam create-policy --policy-name clouder-prod-deploy --policy-document file://infra/bootstrap/deploy-role-policy.json
aws iam attach-role-policy --role-name github-actions-terraform --policy-arn arn:aws:iam::$ACCT:policy/clouder-prod-deploy
aws iam detach-role-policy --role-name github-actions-terraform --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
gh workflow run deploy.yml --ref main && gh run watch   # must end green
# Rollback, if any step of the deploy is denied:
aws iam attach-role-policy --role-name github-actions-terraform --policy-arn arn:aws:iam::aws:policy/AdministratorAccess
# Updating the policy later:
aws iam create-policy-version --policy-arn arn:aws:iam::$ACCT:policy/clouder-prod-deploy --policy-document file://infra/bootstrap/deploy-role-policy.json --set-as-default
```

and the remaining gap: inline policies on `clouder-prod-*` roles are not bounded (a permissions boundary on those roles is the next step).

- [ ] **Step 5: Tests pass; commit** (e.g. `feat(iam): scoped policy for the deploy role`).

### Task 2: Simulate before the owner switches

- [ ] Run the IAM policy simulator with the new policy over every action the last-accessed report tracked for the role, against `*` (and IAM actions against `arn:aws:iam::<acct>:role/clouder-prod-x`): `aws iam simulate-custom-policy --policy-input-list file://infra/bootstrap/deploy-role-policy.json --action-names … --resource-arns …`. Expected: `allowed` for all but `ecr:*` (unused since July) and IAM actions on non-project roles. Record the counts in the README.

### Task 3: Documents

- [ ] `docs/security.md` known gap: replace the AdministratorAccess bullet with the new state (scoped to 24 services and project roles; attach limited to ReadOnlyAccess; remaining gap: inline role policies unbounded → permissions boundary next). Keep it conditional on the owner's switch: write it as done only after Task 4; until then the PR says "applied by the owner after merge" and the docs describe the policy file and the plan.
- [ ] ADR-0028 Consequences: same.

### Task 4: Ship and owner switch

- [ ] PR (no Terraform change: plan shows no changes); merge.
- [ ] Owner: the apply commands from the README; trigger a deploy; green → done; denied → rollback command and report the denied action.
- [ ] After a green deploy under the scoped role: docs say done (small follow-up commit if Task 3 had to stay conditional); board → `done`.

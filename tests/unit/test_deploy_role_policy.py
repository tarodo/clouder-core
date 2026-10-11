"""The deploy role's policy: the AWS services Terraform manages, and no way to raise itself (ADR-0028).

Every role Terraform creates carries the project's permissions boundary (infra/iam_boundary.tf);
the deploy role cannot create or write a role without it, remove or change it, assume a role,
attach a managed policy other than ReadOnlyAccess, or change its own role or policy.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
POLICY = json.loads((INFRA / "bootstrap" / "deploy-role-policy.json").read_text())
README = (INFRA / "bootstrap" / "README.md").read_text()
TF = "\n".join(
    p.read_text() for p in sorted(INFRA.glob("*.tf")) + sorted(INFRA.glob("modules/*/*.tf"))
)
BOUNDARY = "arn:aws:iam::*:policy/clouder-role-boundary"

# Terraform resource type → the IAM namespace that creates it: exact names first, then prefixes.
# Other aws_iam_* types (users, OIDC providers, instance profiles) are left out on purpose: the
# policy writes only roles, so a new one must fail here before it fails a deploy.
EXACT = {"aws_vpc": "ec2", "aws_iam_policy": "iam"}
PREFIX = {
    "aws_apigatewayv2_": "apigateway",
    "aws_athena_": "athena",
    "aws_budgets_": "budgets",
    "aws_cloudfront_": "cloudfront",
    "aws_cloudwatch_dashboard": "cloudwatch",
    "aws_cloudwatch_metric_alarm": "cloudwatch",
    "aws_cloudwatch_event_": "events",
    "aws_cloudwatch_log_": "logs",
    "aws_codebuild_": "codebuild",
    "aws_db_": "rds",
    "aws_rds_": "rds",
    "aws_glue_": "glue",
    "aws_iam_role": "iam",  # roles, their inline policies and attachments
    "aws_kinesis_firehose_": "firehose",
    "aws_kms_": "kms",
    "aws_lambda_": "lambda",
    "aws_s3_": "s3",
    "aws_scheduler_": "scheduler",
    "aws_security_group": "ec2",
    "aws_subnet": "ec2",
    "aws_vpc_": "ec2",
    "aws_sfn_": "states",
    "aws_sns_": "sns",
    "aws_sqs_": "sqs",
    "aws_ssm_": "ssm",
    "aws_servicequotas_": "servicequotas",
}


def _statement(sid: str) -> dict:
    (st,) = [s for s in POLICY["Statement"] if s.get("Sid") == sid]
    return st


def _allowed() -> set[str]:
    actions = [a for s in POLICY["Statement"] if s["Effect"] == "Allow" for a in s["Action"]]
    return {a.split(":")[0] for a in actions}


def _role_blocks() -> list[str]:
    return re.findall(r'resource "aws_iam_role" "\w+" \{(.*?)\n\}', TF, re.S)


def _role_module_calls() -> list[str]:
    calls = re.findall(r'module "\w+" \{(.*?)\n\}', TF, re.S)
    return [c for c in calls if "modules/lambda_role" in c]


def test_every_terraform_resource_type_is_covered() -> None:
    types = set(re.findall(r'(?:resource|data) "(aws_[a-z0-9_]+)"', TF)) - {
        "aws_iam_policy_document",  # rendered locally
        "aws_caller_identity",  # sts:GetCallerIdentity
        "aws_availability_zones",  # ec2 read
    }
    for t in sorted(types):
        ns = EXACT.get(t) or next((n for p, n in PREFIX.items() if t.startswith(p)), None)
        assert ns, f"{t}: map it here and allow its namespace in deploy-role-policy.json"
        assert ns in _allowed(), f"{t} needs {ns} in infra/bootstrap/deploy-role-policy.json"
    assert {"s3", "dynamodb"} <= _allowed()  # the Terraform backend: state and lock


def test_iam_writes_only_on_project_roles() -> None:
    iam = _statement("IamOnProjectRoles")
    assert iam["Action"] == ["iam:*"]
    # Roles only: a policy grant would let the role rewrite its own policy or the boundary.
    assert iam["Resource"] == ["arn:aws:iam::*:role/clouder-prod-*"]
    blocks = _role_blocks()
    names = [re.search(r'^\s*name\s*=\s*("[^"]+"|var\.name)\s*$', b, re.M) for b in blocks]
    assert blocks and all(names), "every aws_iam_role sets an explicit name"
    for m in names:  # var.name: the lambda_role module, checked at its call sites below
        assert m.group(1).startswith('"${local.name_prefix}-') or m.group(1) == "var.name"
    for call in _role_module_calls():
        name = re.search(r'^\s*name\s*=\s*"([^"]+)"', call, re.M)
        assert name and name.group(1).startswith("${local.name_prefix}-"), call[:80]


def test_no_managed_policy_but_read_only_can_be_attached() -> None:
    deny = _statement("OnlyReadOnlyAccessAttached")
    assert deny["Effect"] == "Deny"
    assert set(deny["Action"]) == {"iam:AttachRolePolicy", "iam:DetachRolePolicy"}
    assert deny["Condition"] == {
        "ArnNotEquals": {"iam:PolicyARN": "arn:aws:iam::aws:policy/ReadOnlyAccess"}
    }
    attached = re.findall(r'policy_arn\s*=\s*"([^"]+)"', TF)
    assert set(attached) == {"arn:aws:iam::aws:policy/ReadOnlyAccess"}
    # A computed policy_arn (a reference, not a literal) would slip past the set above.
    assert len(re.findall(r"policy_arn\s*=", TF)) == len(attached)
    # The deploy role writes no IAM policy: the boundary is the only one Terraform creates.
    assert re.findall(r'resource "aws_iam_policy" "(\w+)"', TF) == ["role_boundary"]
    assert "managed_policy_arns" not in TF and "aws_iam_policy_attachment" not in TF


def test_the_role_cannot_change_itself() -> None:
    deny = _statement("NotItself")
    assert deny["Effect"] == "Deny" and deny["Action"] == ["iam:*"]
    assert deny["Resource"] == [
        "arn:aws:iam::*:role/github-actions-terraform",
        "arn:aws:iam::*:policy/github-actions-terraform-deploy",
    ]
    assert "--policy-name github-actions-terraform-deploy" in README


def test_every_role_carries_the_boundary() -> None:
    boundary = r"permissions_boundary\s*=\s*(local\.role_boundary_arn|var\.permissions_boundary)"
    for block in _role_blocks():
        assert re.search(boundary, block), block[:80]
    calls = _role_module_calls()
    assert calls
    for call in calls:
        assert re.search(r"permissions_boundary\s*=\s*local\.role_boundary_arn", call), call[:80]
    # Through the resource, so roles wait for the boundary to exist.
    assert re.search(r"role_boundary_arn\s*=\s*aws_iam_policy\.role_boundary\.arn", TF)
    assert re.search(r'role_boundary_name\s*=\s*"clouder-role-boundary"', TF)


def test_the_boundary_keeps_roles_out_of_iam() -> None:
    doc = re.search(r'data "aws_iam_policy_document" "role_boundary" \{(.*?)\n\}', TF, re.S).group(
        1
    )
    sids = re.findall(r'sid\s*=\s*"(\w+)"', doc)
    assert sids == ["EverythingButIdentityAndAccount", "ReadIam", "PassProjectRoles"]
    # sts:AssumeRole too: a role in this shared account that trusts the root stays out of reach.
    assert re.search(
        r'not_actions\s*=\s*\["iam:\*", "organizations:\*", "account:\*", "sts:AssumeRole"\]', doc
    )
    assert re.search(r'actions\s*=\s*\["iam:Get\*", "iam:List\*"\]', doc)
    assert re.search(r'actions\s*=\s*\["iam:PassRole"\]', doc)
    assert "role/${local.name_prefix}-*" in doc


def test_roles_cannot_be_written_without_the_boundary() -> None:
    keep = _statement("ProjectRolesKeepTheBoundary")
    assert keep["Effect"] == "Deny"
    assert set(keep["Action"]) == {
        "iam:CreateRole",
        "iam:PutRolePolicy",
        "iam:AttachRolePolicy",
        "iam:PutRolePermissionsBoundary",
    }
    assert keep["Condition"] == {"ArnNotLike": {"iam:PermissionsBoundary": BOUNDARY}}
    stays = _statement("BoundaryStays")
    assert stays["Effect"] == "Deny" and stays["Action"] == ["iam:DeleteRolePermissionsBoundary"]
    frozen = _statement("BoundaryIsNotTheDeploysToChange")
    assert frozen["Effect"] == "Deny" and frozen["Resource"] == [BOUNDARY]
    assert {"iam:CreatePolicyVersion", "iam:SetDefaultPolicyVersion", "iam:DeletePolicy"} <= set(
        frozen["Action"]
    )


def test_the_role_assumes_no_other_role() -> None:
    # A project role's trust policy could name the deploy role; an explicit Deny wins over it.
    deny = _statement("NoAssumingRoles")
    assert deny["Effect"] == "Deny" and deny["Action"] == ["sts:AssumeRole"]
    assert deny["Resource"] == "*"


def test_no_wildcard_for_everything() -> None:
    actions = [a for s in POLICY["Statement"] if s["Effect"] == "Allow" for a in s["Action"]]
    assert "*" not in actions and "*:*" not in actions and "ecr:*" not in actions

"""The deploy role's policy covers every AWS service Terraform manages, and nothing more (ADR-0028)."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"
POLICY = json.loads((INFRA / "bootstrap" / "deploy-role-policy.json").read_text())
TF = "\n".join(
    p.read_text() for p in sorted(INFRA.glob("*.tf")) + sorted(INFRA.glob("modules/*/*.tf"))
)

# Terraform resource-type prefix → the IAM namespace that creates it.
NAMESPACE = {
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
    "aws_iam_": "iam",
    "aws_kinesis_firehose_": "firehose",
    "aws_kms_": "kms",
    "aws_lambda_": "lambda",
    "aws_s3_": "s3",
    "aws_scheduler_": "scheduler",
    "aws_security_group": "ec2",
    "aws_subnet": "ec2",
    "aws_vpc": "ec2",
    "aws_sfn_": "states",
    "aws_sns_": "sns",
    "aws_sqs_": "sqs",
    "aws_ssm_": "ssm",
    "aws_servicequotas_": "servicequotas",
}


def _allowed() -> set[str]:
    actions = [a for s in POLICY["Statement"] if s["Effect"] == "Allow" for a in s["Action"]]
    return {a.split(":")[0] for a in actions}


def test_every_terraform_resource_type_is_covered() -> None:
    types = set(re.findall(r'(?:resource|data) "(aws_[a-z0-9_]+)"', TF)) - {
        "aws_iam_policy_document",  # rendered locally
        "aws_caller_identity",
        "aws_availability_zones",  # sts / ec2 reads
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

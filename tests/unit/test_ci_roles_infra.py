"""CI roles: pull requests plan under a read-only role only they can assume (ADR-0028)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CI_ROLES = ROOT / "infra" / "ci_roles.tf"

# SSM paths the deploy syncs from GitHub secrets; Terraform only passes their names.
VENDOR_SECRETS = (
    "gemini",
    "openai",
    "tavily",
    "deepseek",
    "spotify",
    "ytmusic",
    "youtube",
    "beatport",
)


def test_plan_role_only_reads() -> None:
    tf = CI_ROLES.read_text()
    assert re.findall(r'policy_arn\s*=\s*"([^"]+)"', tf) == [
        "arn:aws:iam::aws:policy/ReadOnlyAccess"
    ]
    effects = re.findall(r'effect\s*=\s*"(\w+)"', tf)
    assert effects and set(effects) == {"Deny"}  # the inline policy only takes away


def test_plan_role_cannot_read_secrets_or_data() -> None:
    # ReadOnlyAccess would decrypt every SecureString (the aws/ssm key trusts the whole
    # account) and read S3 objects, logs, queue messages and query results.
    tf = CI_ROLES.read_text()
    for vendor in VENDOR_SECRETS:
        assert f'/clouder/{vendor}/*"' in tf, vendor
    assert "/clouder/auth/" not in tf  # Terraform manages the JWT key and must read it
    for action in (
        "ssm:GetParameter",
        "ssm:GetParametersByPath",
        "s3:GetObject",
        "logs:GetLogEvents",
        "logs:FilterLogEvents",
        "logs:StartQuery",
        "secretsmanager:GetSecretValue",
        "sqs:ReceiveMessage",
        "athena:GetQueryResults",
    ):
        assert f'"{action}"' in tf, action
    assert "${aws_s3_bucket.raw.arn}/*" in tf and "${aws_s3_bucket.analytics_lake.arn}/*" in tf


def test_only_pull_request_jobs_can_assume_the_plan_role() -> None:
    tf = CI_ROLES.read_text()
    assert re.findall(r'"repo:\$\{var\.github_repository\}:([^"]+)"', tf) == ["pull_request"]
    assert '"token.actions.githubusercontent.com:aud"' in tf
    assert '"sts.amazonaws.com"' in tf
    assert tf.count('test     = "StringEquals"') == 2

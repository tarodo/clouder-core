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

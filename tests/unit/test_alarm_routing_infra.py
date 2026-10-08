"""Every CloudWatch alarm notifies the owner's email through one SNS topic."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra"


def _all_tf() -> str:
    return "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def test_email_topic_is_created_from_a_secret() -> None:
    tf = (INFRA / "alarms.tf").read_text()
    topic = tf[tf.index('resource "aws_sns_topic" "alarms"'):]
    assert re.search(r'count\s*=\s*var\.alarm_email != "" && var\.alarm_sns_topic_arn == "" \? 1 : 0', topic)
    sub = tf[tf.index('resource "aws_sns_topic_subscription" "alarm_email"'):]
    assert re.search(r'protocol\s*=\s*"email"', sub) and re.search(r"endpoint\s*=\s*var\.alarm_email", sub)
    variable = (INFRA / "variables.tf").read_text()
    block = variable[variable.index('variable "alarm_email"'):]
    assert re.search(r'default\s*=\s*""', block.split("}")[0])  # no secret → no topic, deploy passes
    # The address is not in the public repo: it comes from the GitHub secret at deploy.
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    apply = next(s for s in workflow["jobs"]["deploy"]["steps"] if s.get("name") == "Terraform apply")
    assert apply["env"]["TF_VAR_alarm_email"] == "${{ secrets.ALARM_EMAIL }}"


def test_every_alarm_routes_through_the_shared_actions() -> None:
    tf = _all_tf()
    definition = 'local.alarm_topic_arn != "" ? [local.alarm_topic_arn] : []'
    actions = [v.strip() for _, v in re.findall(r"^\s*(alarm_actions|ok_actions)\s*=\s*(.+)$", tf, re.M)]
    assert actions.count(definition) == 1  # the local itself
    used = [v for v in actions if v != definition]
    assert len(used) >= 20 and set(used) == {"local.alarm_actions"}
    assert re.search(
        r'alarm_topic_arn\s*=\s*var\.alarm_sns_topic_arn != "" \? var\.alarm_sns_topic_arn : try\(aws_sns_topic\.alarms\[0\]\.arn, ""\)',
        tf,
    )

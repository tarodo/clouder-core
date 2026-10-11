"""Telemetry is kept 400 days in bronze and silver; the lake survives a destroy (privacy.md)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
TELEMETRY = (ROOT / "infra" / "telemetry.tf").read_text()


def _rule(rule_id: str) -> str:
    m = re.search(rf'id\s*=\s*"{rule_id}"(.*?)\n  \}}', TELEMETRY, re.S)
    assert m, rule_id
    return m.group(1)


def test_bronze_events_expire_with_the_silver_window() -> None:
    rule = _rule("expire-bronze-events")
    days = int(re.search(r"expiration \{ days = (\d+) \}", rule).group(1))
    assert 'prefix = "bronze/events/"' in rule
    dbt_days = yaml.safe_load((ROOT / "dbt" / "dbt_project.yml").read_text())["vars"][
        "events_retention_days"
    ]
    assert days == dbt_days == 400


def test_firehose_error_records_expire() -> None:
    rule = _rule("expire-firehose-errors")
    assert 'prefix = "bronze/_errors/"' in rule and "expiration { days = 30 }" in rule


def test_silver_events_delete_past_the_window() -> None:
    model = (ROOT / "dbt" / "models" / "silver" / "events.sql").read_text()
    assert "delete_expired_events()" in model


def test_lake_bucket_survives_a_destroy() -> None:
    bucket = TELEMETRY[TELEMETRY.index('resource "aws_s3_bucket" "analytics_lake"') :]
    bucket = bucket[: bucket.index("\n}\n")]
    assert re.search(r"force_destroy\s*=\s*false", bucket)

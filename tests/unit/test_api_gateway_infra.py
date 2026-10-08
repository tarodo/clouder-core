"""The public API has a stage-wide rate limit and JSON access logs."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"


def _block(text: str, header: str) -> str:
    start = text.index(header)
    return text[start : text.index("\n}\n", start)]


def test_api_throttling_and_access_logs() -> None:
    stage = _block((INFRA / "api_gateway.tf").read_text(), 'resource "aws_apigatewayv2_stage" "default"')
    burst = int(re.search(r"throttling_burst_limit\s*=\s*(\d+)", stage).group(1))
    rate = float(re.search(r"throttling_rate_limit\s*=\s*([\d.]+)", stage).group(1))
    # The SPA fires about ten calls per page load; a closed group stays far below this.
    assert burst >= 100 and rate >= 50
    assert "access_log_settings" in stage
    assert "destination_arn = aws_cloudwatch_log_group.api_access.arn" in stage
    for field in ("requestId", "routeKey", "status", "integrationLatency", "ip"):
        assert field in stage, field
    group = _block((INFRA / "logging.tf").read_text(), 'resource "aws_cloudwatch_log_group" "api_access"')
    assert '"/aws/apigateway/${local.name_prefix}-collector-api"' in group
    assert "retention_in_days = var.log_retention_days" in group

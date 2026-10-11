"""Background workers cannot take the API's Lambda capacity (postmortem 2026-10-11)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))
PROD = (INFRA / "prod.tfvars").read_text()
API_HEADROOM = 20  # executions kept free for the API functions and the scheduled jobs


def _block(kind: str, name: str) -> str:
    m = re.search(rf'{kind} "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind} {name}"
    return m.group(1)


def _caps() -> dict[str, str]:
    """Event source mapping name → the variable that holds its maximum_concurrency."""
    caps = {}
    for name, body in re.findall(
        r'resource "aws_lambda_event_source_mapping" "([a-z_]+)" \{(.*?)\n\}', TF, re.S
    ):
        m = re.search(r"maximum_concurrency\s*=\s*var\.([a-z_]+)", body)
        caps[name] = m.group(1) if m else ""
    return caps


def test_every_sqs_worker_has_a_concurrency_cap() -> None:
    caps = _caps()
    assert len(caps) >= 7
    for esm, var in caps.items():
        assert var, f"{esm}: scaling_config.maximum_concurrency is missing"
        assert re.search(rf"var\.{var} >= 2 && var\.{var} <= 1000", _block("variable", var)), var


def _quota() -> int:
    m = re.search(r"lambda_concurrency_quota\s*=\s*(\d+)", TF)
    assert m, "local.lambda_concurrency_quota"
    return int(m.group(1))


def _value(var: str) -> int:
    """prod.tfvars wins over the default, as in every plan and apply."""
    m = re.search(rf"^{var}\s*=\s*(\d+)", PROD, re.M)
    if m:
        return int(m.group(1))
    return int(re.search(r"default\s*=\s*(\d+)", _block("variable", var)).group(1))


def test_account_quota_is_requested_in_code() -> None:
    # 'type" "name' makes _block match: resource "type" "name" {
    body = _block("resource", 'aws_servicequotas_service_quota" "lambda_concurrency')
    assert re.search(r'service_code\s*=\s*"lambda"', body)
    assert re.search(r'quota_code\s*=\s*"L-B99A9384"', body)
    assert re.search(r"value\s*=\s*local\.lambda_concurrency_quota", body)


def test_worker_caps_leave_room_for_the_api() -> None:
    total = sum(_value(var) for var in _caps().values())
    assert total + API_HEADROOM <= _quota(), (total, _quota())


def test_account_concurrency_alarm_warns_before_the_quota() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "lambda_account_concurrency')
    assert re.search(r'metric_name\s*=\s*"ConcurrentExecutions"', body)
    assert re.search(r"threshold\s*=\s*local\.lambda_concurrency_quota \* 0\.8", body)
    assert "dimensions" not in body  # account-wide, not one function
    assert "local.alarm_actions" in body


def test_every_api_function_alarms_on_throttles() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "api_throttles')
    assert re.search(r"for_each\s*=\s*local\.api_functions", body)
    assert re.search(r'metric_name\s*=\s*"Throttles"', body)
    assert re.search(r"threshold\s*=\s*1\b", body)
    assert "local.alarm_actions" in body


def test_api_5xx_alarm() -> None:
    body = _block("resource", 'aws_cloudwatch_metric_alarm" "api_5xx')
    assert re.search(r'namespace\s*=\s*"AWS/ApiGateway"', body)
    assert re.search(r'metric_name\s*=\s*"5xx"', body)
    # One 503 after an Aurora resume is expected (ADR-0014); five in five minutes is not.
    assert re.search(r"threshold\s*=\s*5\b", body) and re.search(r"period\s*=\s*300\b", body)
    assert "aws_apigatewayv2_api.collector.id" in body
    assert "aws_apigatewayv2_stage.default.name" in body
    assert "local.alarm_actions" in body

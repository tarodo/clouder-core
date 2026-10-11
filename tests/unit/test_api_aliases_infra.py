"""API Gateway calls the `live` alias of each API function (phase 3, ADR-0029)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))
API = {"collector", "curation", "auth_handler", "auth_authorizer", "analytics", "telemetry"}


def _fn(name: str) -> str:
    m = re.search(rf'resource "aws_lambda_function" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, name
    return m.group(1)


def test_api_functions_publish_versions() -> None:
    for name in API:
        assert re.search(r"publish\s*=\s*true", _fn(name)), name


def test_every_api_integration_targets_the_alias() -> None:
    uris = re.findall(r"(?:integration_uri|authorizer_uri)\s*=\s*([^\n]+)", TF)
    assert uris and all("aws_lambda_alias.live[" in u for u in uris), uris


def test_alias_permissions_exist_and_gate_the_integrations() -> None:
    aliases = (INFRA / "lambda_aliases.tf").read_text()
    assert re.search(r"qualifier\s*=\s*aws_lambda_alias\.live\[each\.key\]\.name", aliases)
    blocks = re.findall(r'resource "aws_apigatewayv2_(?:integration|authorizer)" "[a-z_]+" \{(.*?)\n\}', TF, re.S)
    assert blocks
    for block in blocks:
        assert "aws_lambda_permission.api_live" in block  # depends_on: permission before switch

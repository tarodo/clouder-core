"""Analysis routes sit behind their own authorizer; the token hash stays out of Terraform."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
ROUTE = re.compile(r'resource "aws_apigatewayv2_route" "[^"]+" \{(.*?)\n\}', re.S)


def _routes() -> dict[str, str]:
    out = {}
    for tf in INFRA.glob("*.tf"):
        for body in ROUTE.findall(tf.read_text()):
            # for_each routes (route_key = each.key) never carry the analysis authorizer
            if key := re.search(r'route_key\s*=\s*"([^"]+)"', body):
                out[key.group(1)] = body
    return out


def test_service_routes_use_the_analysis_authorizer() -> None:
    routes = _routes()
    for key in ("POST /v1/analysis/claim", "POST /v1/analysis/results"):
        assert "aws_apigatewayv2_authorizer.analysis_service.id" in routes[key]
        assert "collector_lambda" in routes[key]


def test_only_analysis_routes_use_the_analysis_authorizer() -> None:
    # Each authorizer caches its verdict per header across its routes: a service-token
    # verdict must never be reused on a user route.
    for key, body in _routes().items():
        if "analysis_service" in body:
            assert key.split(" ", 1)[1].startswith("/v1/analysis/"), key
    for tf in INFRA.glob("*.tf"):
        if tf.name != "analysis.tf":
            assert "authorizer.analysis_service" not in tf.read_text(), tf.name


def test_admin_routes_use_the_jwt_authorizer() -> None:
    routes = _routes()
    for key in ("GET /admin/analysis/status", "POST /admin/analysis/requeue"):
        assert "aws_apigatewayv2_authorizer.jwt.id" in routes[key]


def test_analysis_authorizer_is_its_own_resource() -> None:
    tf = (INFRA / "analysis.tf").read_text()
    block = re.search(
        r'resource "aws_apigatewayv2_authorizer" "analysis_service" \{(.*?)\n\}', tf, re.S
    ).group(1)
    assert 'aws_lambda_alias.live["auth_authorizer"].invoke_arn' in block
    assert "enable_simple_responses           = true" in block
    assert '"$request.header.Authorization"' in block


def test_authorizer_reads_only_the_hash_parameter() -> None:
    auth = (INFRA / "auth.tf").read_text()
    assert "ANALYSIS_TOKEN_SHA256_SSM_PARAMETER = var.analysis_token_sha256_ssm_parameter" in auth
    statement = re.search(r'sid\s*=\s*"ReadAnalysisTokenHash"(.*?)\n  \}', auth, re.S).group(1)
    assert "var.analysis_token_sha256_ssm_parameter" in statement
    variables = (INFRA / "variables.tf").read_text()
    assert '"/clouder/auth/analysis_service_token_sha256"' in variables


def test_hash_parameter_is_not_a_terraform_resource() -> None:
    # Owner-written (ADR-0028): nothing secret-adjacent in state.
    for tf in INFRA.glob("*.tf"):
        assert 'analysis_service_token_sha256"\n  type' not in tf.read_text()
        for body in re.findall(
            r'resource "aws_ssm_parameter" "[^"]+" \{(.*?)\n\}', tf.read_text(), re.S
        ):
            assert "analysis" not in body


def test_analysis_routes_are_declared_only_with_their_authorizer() -> None:
    # A /v1/analysis/* route on the JWT authorizer would make it take the service
    # branch and cache a service-token allow for every user route.
    for tf in INFRA.glob("*.tf"):
        if tf.name != "analysis.tf":
            assert "/v1/analysis/" not in tf.read_text(), tf.name

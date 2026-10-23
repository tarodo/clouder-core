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
    for key in (
        "POST /v1/analysis/claim",
        "POST /v1/analysis/results",
        "POST /v1/analysis/features",
    ):
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


def _resource(kind: str, name: str) -> str:
    tf = "\n".join(p.read_text() for p in INFRA.glob("*.tf"))
    return re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', tf, re.S).group(1)


def test_feature_store_bucket_is_private_versioned_and_encrypted() -> None:
    assert '"${local.name_prefix}-audio-features"' in _resource("aws_s3_bucket", "audio_features")
    versioning = _resource("aws_s3_bucket_versioning", "audio_features")
    assert 'status = "Enabled"' in versioning
    lifecycle = _resource("aws_s3_bucket_lifecycle_configuration", "audio_features")
    assert re.search(r"noncurrent_version_expiration \{\s*noncurrent_days = 30", lifecycle)
    assert "days_after_initiation = 7" in lifecycle
    sse = _resource("aws_s3_bucket_server_side_encryption_configuration", "audio_features")
    assert 'sse_algorithm = "AES256"' in sse
    block = _resource("aws_s3_bucket_public_access_block", "audio_features")
    for flag in ("block_public_acls", "block_public_policy", "ignore_public_acls"):
        assert re.search(rf"{flag}\s*= true", block)
    assert re.search(r"restrict_public_buckets\s*= true", block)


def test_ml_jobs_queue_keeps_messages_until_the_worker_exists() -> None:
    queue = _resource("aws_sqs_queue", "ml_jobs")
    assert "aws_sqs_queue.ml_jobs_dlq.arn" in queue
    assert "var.ml_jobs_queue_max_receive_count" in queue
    variables = (INFRA / "variables.tf").read_text()
    for name, value in (
        ("ml_jobs_queue_retention_seconds", "1209600"),
        ("ml_jobs_queue_visibility_timeout_seconds", "960"),
        ("ml_jobs_queue_max_receive_count", "3"),
    ):
        body = re.search(rf'variable "{name}" \{{(.*?)\n\}}', variables, re.S).group(1)
        assert re.search(rf"default\s*= {value}\b", body), name


def test_collector_gets_the_feature_store_env() -> None:
    collector = _resource("aws_lambda_function", "collector")
    assert (
        "AUDIO_FEATURES_BUCKET" in collector and "aws_s3_bucket.audio_features.bucket" in collector
    )
    assert "ML_JOBS_QUEUE_URL" in collector and "aws_sqs_queue.ml_jobs.url" in collector

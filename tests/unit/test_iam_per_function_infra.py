"""Every Lambda runs under its own least-privilege role (matrix derived from env + code).

A permission dropped here is an AccessDenied in prod, so each function's needs are pinned:
REQUIRED must appear in its role's module block, FORBIDDEN must not.
"""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))

RAW = "${aws_s3_bucket.raw.arn}/${var.raw_prefix}/*"
SPOTIFY_RAW = "${aws_s3_bucket.raw.arn}/${var.spotify_raw_prefix}/*"
COVERS = "${aws_s3_bucket.raw.arn}/covers/*"


def q(name: str) -> str:
    return f"aws_sqs_queue.{name}.arn"


DB = ["local.st_data_api", "local.st_db_secret"]
SSM = "local.st_ssm_kms"
TOKENS = "local.st_user_tokens"

REQUIRED: dict[str, list[str]] = {
    "collector": [
        *DB,
        RAW,
        q("canonicalization"),
        q("spotify_search"),
        q("label_enrichment"),
        q("artist_enrichment"),
        "aws_lambda_function.auto_ingest.arn",
        '"sqs:GetQueueAttributes"',
    ],
    "curation": [
        *DB,
        COVERS,
        TOKENS,
        SSM,
        q("label_enrichment"),
        q("artist_enrichment"),
        q("vendor_match"),
        q("auto_enrich_dispatch"),
        q("comments_collect"),
        "var.spotify_client_id_ssm_parameter",
        "var.ytmusic_client_id_ssm_parameter",
    ],
    "auth_handler": [
        *DB,
        TOKENS,
        SSM,
        "var.jwt_signing_key_ssm_parameter",
        "var.spotify_client_id_ssm_parameter",
        "var.ytmusic_client_id_ssm_parameter",
    ],
    "canonicalization_worker": [
        *DB,
        RAW,
        "local.sqs_consume",
        q("canonicalization"),
        q("spotify_search"),
    ],
    "spotify_search_worker": [
        *DB,
        SPOTIFY_RAW,
        SSM,
        q("spotify_search"),
        "var.spotify_client_id_ssm_parameter",
        "var.spotify_credentials_secret_arn",
    ],
    "vendor_match_worker": [
        *DB,
        SSM,
        q("vendor_match"),
        q("comments_collect"),
        "var.spotify_client_id_ssm_parameter",
    ],
    "label_enricher_worker": [
        *DB,
        SSM,
        q("label_enrichment"),
        "var.gemini_api_key_ssm_parameter",
        "var.deepseek_api_key_ssm_parameter",
    ],
    "artist_enricher_worker": [
        *DB,
        SSM,
        q("artist_enrichment"),
        "var.openai_api_key_ssm_parameter",
        "var.tavily_api_key_ssm_parameter",
    ],
    "auto_enrich_dispatch_worker": [
        *DB,
        q("auto_enrich_dispatch"),
        q("label_enrichment"),
        q("artist_enrichment"),
        q("comments_collect"),
    ],
    "comments_collect_worker": [
        *DB,
        SSM,
        q("comments_collect"),
        "var.youtube_api_key_ssm_parameter",
    ],
    "db_migration": ["local.st_db_secret", '"rds-db:connect"', '"ec2:CreateNetworkInterface"'],
}

FORBIDDEN: dict[str, list[str]] = {
    "collector": [TOKENS, COVERS, "local.sqs_consume", '"ec2:', "rds-db:connect"],
    "curation": [RAW, "local.sqs_consume", '"ec2:', "rds-db:connect", "lambda:InvokeFunction"],
    "auth_handler": ['"s3:', '"sqs:', "local.sqs_consume", '"ec2:'],
    "canonicalization_worker": [TOKENS, COVERS, SSM, '"ec2:'],
    "spotify_search_worker": [TOKENS, RAW, COVERS, '"ec2:'],
    "vendor_match_worker": [TOKENS, '"s3:', '"ec2:'],
    "label_enricher_worker": [TOKENS, '"s3:', '"ec2:'],
    "artist_enricher_worker": [TOKENS, '"s3:', '"ec2:'],
    "auto_enrich_dispatch_worker": [TOKENS, '"s3:', SSM, '"ec2:'],
    "comments_collect_worker": [TOKENS, '"s3:', '"ec2:'],
    "db_migration": ["local.st_data_api", '"s3:', '"sqs:', TOKENS],
}


def _block(header: str) -> str:
    start = TF.index(header)
    depth, i = 0, TF.index("{", start)
    for j in range(i, len(TF)):
        depth += {"{": 1, "}": -1}.get(TF[j], 0)
        if depth == 0:
            return TF[start : j + 1]
    raise AssertionError(header)


def role_block(function: str) -> str:
    fn = _block(f'resource "aws_lambda_function" "{function}"')
    module = re.search(r"role\s*=\s*module\.([a-z_]+)\.arn", fn)
    assert module, f"{function} does not use a lambda_role module"
    return _block(f'module "{module.group(1)}"')


def test_no_lambda_uses_the_shared_role() -> None:
    assert "aws_iam_role.collector_lambda" not in TF
    assert not re.search(r'resource "aws_iam_role" "collector_lambda"', TF)


def test_role_matrix() -> None:
    problems = []
    for function, required in REQUIRED.items():
        block = role_block(function)
        problems += [f"{function}: missing {r}" for r in required if r not in block]
        problems += [f"{function}: must not have {f}" for f in FORBIDDEN[function] if f in block]
    assert problems == []


def test_each_role_writes_only_its_own_logs() -> None:
    for function in REQUIRED:
        fn = _block(f'resource "aws_lambda_function" "{function}"')
        block = role_block(function)
        group = re.search(r"log_group_arn\s*=\s*aws_cloudwatch_log_group\.([a-z_]+)\.arn", block)
        assert group, function
        assert f"aws_cloudwatch_log_group.{group.group(1)}" in fn or group.group(1) in fn, function


def test_role_arn_waits_for_its_policy() -> None:
    # deploy.yml's first phase is `-target=aws_lambda_function.db_migration`; without this
    # edge the targeted apply skips the inline policy and hands the function a role that
    # only has a trust policy (and a VPC function update fails without ec2:CreateNetworkInterface).
    module = (INFRA / "modules" / "lambda_role" / "main.tf").read_text()
    output = module[module.index('output "arn"') :]
    assert re.search(r"depends_on\s*=\s*\[aws_iam_role_policy\.this\]", output)

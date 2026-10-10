"""The deploy migrates before the API code ships (postmortem 2026-09-20)."""

from __future__ import annotations

from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


def test_migration_runs_between_the_targeted_and_the_full_apply() -> None:
    steps = yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]
    names = [s.get("name", "") for s in steps]
    targeted = names.index("Terraform apply (migration Lambda only)")
    migrate = names.index("Run DB migrations via Lambda")
    full = names.index("Terraform apply")
    assert targeted < migrate < full
    assert "-target=aws_lambda_function.db_migration" in steps[targeted]["run"]
    assert "-target" not in steps[full]["run"]


PROD_TFVARS = DEPLOY.parents[2] / "infra" / "prod.tfvars"

# Exactly what deploy.yml passed as -var before 2026-10-10 (minus the three GitHub variables).
DEPLOYED = {
    "environment": '"prod"',
    "canonicalization_enabled": "true",
    "silver_events_table": '"clouder_silver.events"',
    "gemini_api_key_ssm_parameter": '"/clouder/gemini/api_key"',
    "openai_api_key_ssm_parameter": '"/clouder/openai/api_key"',
    "tavily_api_key_ssm_parameter": '"/clouder/tavily/api_key"',
    "deepseek_api_key_ssm_parameter": '"/clouder/deepseek/api_key"',
    "spotify_search_enabled": "true",
    "vendor_match_enabled": "true",
    "spotify_client_id_ssm_parameter": '"/clouder/spotify/client_id"',
    "spotify_client_secret_ssm_parameter": '"/clouder/spotify/client_secret"',
    "ytmusic_client_id_ssm_parameter": '"/clouder/ytmusic/client_id"',
    "ytmusic_client_secret_ssm_parameter": '"/clouder/ytmusic/client_secret"',
    "youtube_api_key_ssm_parameter": '"/clouder/youtube/api_key"',
    "migration_aurora_auth_mode": '"iam"',
    "enable_secretsmanager_vpc_endpoint": "false",
}


def test_prod_tfvars_keeps_the_deployed_values() -> None:
    pairs = {}
    for line in PROD_TFVARS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, value = (part.strip() for part in line.split("=", 1))
            pairs[key] = value
    assert pairs == DEPLOYED


def test_both_applies_read_prod_tfvars_and_nothing_else() -> None:
    steps = {s.get("name"): s for s in yaml.safe_load(DEPLOY.read_text())["jobs"]["deploy"]["steps"]}
    for name in ("Terraform apply (migration Lambda only)", "Terraform apply"):
        run = steps[name]["run"]
        assert "-var-file=prod.tfvars" in run
        assert "-var=" not in run

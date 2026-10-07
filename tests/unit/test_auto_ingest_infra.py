"""Terraform and deploy-workflow contracts for auto-ingest."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_lambda_reads_only_the_beatport_credentials() -> None:
    tf = (ROOT / "infra" / "auto_ingest.tf").read_text()
    assert 'handler          = "collector.auto_ingest_handler.lambda_handler"' in tf
    block = re.search(r'sid\s*=\s*"ReadBeatportCredentials"(.*?)\n  \}', tf, re.S).group(1)
    assert '"ssm:GetParameter"' in block
    assert "local.beatport_username_ssm" in block and "local.beatport_password_ssm" in block
    assert '"/clouder/beatport/username"' in tf and '"/clouder/beatport/password"' in tf
    assert "alias/aws/ssm" in tf


def test_deploy_skips_beatport_sync_without_secrets() -> None:
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "deploy.yml").read_text())
    steps = [s for job in workflow["jobs"].values() for s in job["steps"]]
    step = next(s for s in steps if "Beatport" in s.get("name", ""))
    assert step["env"] == {
        "BP_USER": "${{ secrets.BEATPORT_USERNAME }}",
        "BP_PASS": "${{ secrets.BEATPORT_PASSWORD }}",
    }
    script = step["run"]
    assert re.search(r'if \[ -z "\$BP_USER" \] \|\| \[ -z "\$BP_PASS" \]; then\s.*exit 0', script, re.S)
    for name in ("/clouder/beatport/username", "/clouder/beatport/password"):
        assert f"--name {name}" in script
    # `--value=...`: a password starting with "-" must not be parsed as an option.
    assert '--value="$BP_USER"' in script and '--value="$BP_PASS"' in script
    assert script.count("--type SecureString") == 2

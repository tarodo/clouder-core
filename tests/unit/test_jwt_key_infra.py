"""Terraform neither creates nor reads the JWT signing key (security.md, ADR-0028)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))


def test_no_terraform_resource_holds_the_key() -> None:
    assert 'resource "random_password"' not in TF
    assert 'resource "aws_ssm_parameter" "jwt_signing_key"' not in TF


def test_the_live_parameter_is_released_not_destroyed() -> None:
    for address in ("aws_ssm_parameter.jwt_signing_key", "random_password.jwt_signing_key"):
        block = re.search(rf"removed \{{\s*from\s*=\s*{re.escape(address)}(.*?)\n\}}", TF, re.S)
        assert block, address
        assert re.search(r"destroy\s*=\s*false", block.group(1)), address
    assert re.search(r'required_version\s*=\s*">= 1\.7', TF)  # removed blocks need 1.7

"""Terraform contracts for the lakehouse that a reviewer would otherwise check by eye."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"


def test_silver_reads_are_switched_on_by_a_variable_that_defaults_off() -> None:
    # The Lambda must not read clouder_silver.events before the first dbt build
    # created it; flipping (and rolling back) is a tfvars change, not code.
    routes = (INFRA / "analytics_routes.tf").read_text()
    assert re.search(r"SILVER_EVENTS_TABLE\s*=\s*var\.silver_events_table", routes)
    variables = "".join(p.read_text() for p in INFRA.glob("*.tf"))
    block = re.search(r'variable "silver_events_table" \{(.*?)\n\}', variables, re.S)
    assert block and re.search(r'default\s*=\s*""', block.group(1))


def test_dbt_buildspec_runs_freshness_from_the_project_dir() -> None:
    # CodeBuild runs all commands in one shell: a second `cd repo/dbt` fails.
    spec = (INFRA / "lakehouse.tf").read_text()
    assert spec.count("cd repo/dbt") == 1
    assert "dbt source freshness" in spec


def test_dbt_may_ensure_its_own_glue_databases() -> None:
    # dbt-athena starts every build with CREATE SCHEMA IF NOT EXISTS, which
    # calls glue:CreateDatabase even when Terraform already created it.
    spec = (INFRA / "lakehouse.tf").read_text()
    block = re.search(r'sid = "AllowWriteLakehouseCatalog"(.*?)\n  \}', spec, re.S).group(1)
    assert '"glue:CreateDatabase"' in block

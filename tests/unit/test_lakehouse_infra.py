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


def test_dbt_can_read_the_deleted_user_tombstones() -> None:
    # stg_events anti-joins clouder_analytics.deleted_users; without the table
    # (or read access to its prefix) every nightly build fails.
    tf = "".join(p.read_text() for p in INFRA.glob("*.tf"))
    table = re.search(r'resource "aws_glue_catalog_table" "deleted_users" \{(.*?)\n\}', tf, re.S)
    assert table and 'name          = "deleted_users"' in table.group(1)
    assert "/governance/deleted_users/" in table.group(1)
    lakehouse = (INFRA / "lakehouse.tf").read_text()
    assert '"${local.analytics_lake_arn}/governance/deleted_users/*"' in lakehouse


def test_freshness_failures_fail_the_nightly_job() -> None:
    tf = (INFRA / "lakehouse.tf").read_text()
    start = tf.index("buildspec = <<-YAML")
    spec = tf[start:tf.index("    YAML", start)]
    assert "dbt source freshness" in spec and "|| true" not in spec
    assert spec.index("dbt build") < spec.index("dbt source freshness")  # data still flows when stale


def test_catalog_export_freshness_errors_and_telemetry_only_warns() -> None:
    import yaml

    sources = yaml.safe_load((INFRA.parent / "dbt" / "models" / "sources.yml").read_text())
    tables = {t["name"]: t for s in sources["sources"] for t in s["tables"]}
    assert tables["catalog_export"]["freshness"]["error_after"] == {"count": 1, "period": "day"}
    assert "error_after" not in tables["events"]["freshness"]


def test_catalog_freshness_waits_for_the_last_exported_table() -> None:
    # A timed-out export leaves today's partition with only its first tables;
    # only the last table's presence proves the export finished.
    import yaml

    from collector.catalog_export_handler import _EXPORTS

    sources = yaml.safe_load((INFRA.parent / "dbt" / "models" / "sources.yml").read_text())
    tables = {t["name"]: t for s in sources["sources"] for t in s["tables"]}
    assert f"tbl = '{_EXPORTS[-1][0]}'" in tables["catalog_export"]["freshness"]["filter"]


def test_catalog_export_has_room_to_finish() -> None:
    # 300 s ran out on 2026-10-09 with ~310k rows; 900 s is the Lambda maximum.
    tf = (INFRA / "analytics_export.tf").read_text()
    fn = tf[tf.index('resource "aws_lambda_function" "catalog_export"'):]
    assert re.search(r"timeout\s*=\s*900\b", fn[: fn.index("environment")])

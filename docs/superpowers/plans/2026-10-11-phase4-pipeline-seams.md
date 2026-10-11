# Phase 4 — Pipeline seams: a freshness gate, data-quality SLOs on the dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A missed nightly catalog export fails the nightly dbt job (and its existing alarm) instead of passing silently, and every data-quality SLO is visible on the overview dashboard.

**Architecture:** `dbt source freshness` loses `|| true` and the catalog-export source gets `error_after: 1 day` keyed on its snapshot date; telemetry stays warn-only (its flow depends on users, not the pipeline). The build still runs first, so silver/gold keep updating while the job turns red. The dashboard gains three widgets fed by the existing `CLOUDER/DataQuality` metrics, with SLO lines where the check has a minimum.

**Tech Stack:** dbt-core 1.12 / dbt-athena, Terraform (CloudWatch dashboard, CodeBuild buildspec), pytest guard tests.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` §0 phase 4, §5 (orchestration seam, monitoring row), §11 L3 (outside the repo). Evidence: `infra/lakehouse.tf` buildspec runs `dbt source freshness --target prod || true` after `dbt build`; `dbt/models/sources.yml` has freshness (warn only) on `events`, none on `catalog_export`; export at 00:00 UTC, transform at 00:30 UTC, joined only by the cron offset; the dashboard charts `FailedChecks` but no individual check.

## Global Constraints

- Worktree `<repo>` (`clouder-core-p1`), branch `feat/pipeline-seams` from `origin/main` (`ff6276d2`).
- No new AWS service and no change to schedules; the existing `clouder-prod-transform-failed` alarm is the signal.
- Telemetry freshness must never fail the job: two quiet days of a two-user app are normal.
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **A manual transform run late in the day** must not fail on a same-day snapshot (age < 24 h) — `error_after: 1 day` against `snapshot_dt` cast to a timestamp at midnight UTC.
2. **The freshness SQL is valid on Athena** (`snapshot_dt` is a projected string partition) — verified by a manual transform run after the deploy.
3. **A failed freshness step after a good build** turns the Step Functions task red → `transform-failed` alarm; check the ASL catches the CodeBuild failure the same way as a build failure.
4. **Dashboard JSON stays valid** with optional `annotations` and per-widget `period` (CloudWatch rejects `null`).
5. **CI's DuckDB build is unaffected** (freshness is not run in CI; `dbt parse --target prod` still validates the YAML).

---

### Task 1: Freshness gate

**Files:** `dbt/models/sources.yml`, `infra/lakehouse.tf` (buildspec), test `tests/unit/test_lakehouse_infra.py` (append).

- [ ] **Step 1: Failing tests**

```python
def test_freshness_failures_fail_the_nightly_job() -> None:
    tf = (INFRA / "lakehouse.tf").read_text()
    spec = tf[tf.index("buildspec = <<-YAML"):tf.index("    YAML", tf.index("buildspec = <<-YAML"))]
    assert "dbt source freshness" in spec and "|| true" not in spec
    assert spec.index("dbt build") < spec.index("dbt source freshness")  # data still flows when stale


def test_catalog_export_freshness_errors_and_telemetry_only_warns() -> None:
    import yaml

    sources = yaml.safe_load((ROOT / "dbt" / "models" / "sources.yml").read_text())
    tables = {t["name"]: t for s in sources["sources"] for t in s["tables"]}
    assert tables["catalog_export"]["freshness"]["error_after"] == {"count": 1, "period": "day"}
    assert "error_after" not in tables["events"]["freshness"]
```

(`ROOT`/`INFRA` as already defined in that test module; add `ROOT` if missing.)

- [ ] **Step 2:** run → 2 FAIL.
- [ ] **Step 3:** `sources.yml` — `catalog_export` gets:

```yaml
        # The nightly export (00:00 UTC) writes one snapshot per day; the 00:30 build must
        # see today's. Stale = the export failed -> the job fails -> transform-failed alarm.
        loaded_at_field: "cast(snapshot_dt as timestamp)"
        freshness:
          error_after: {count: 1, period: day}
          filter: "snapshot_dt >= cast(current_date - interval '3' day as varchar)"
```

and a comment on `events`: `# Warn only: telemetry follows users, not the pipeline; quiet days are normal.` Buildspec last line → `- DBT_PROFILES_DIR=. dbt source freshness --target prod`; update the comment above `source {` accordingly.

- [ ] **Step 4:** tests pass; `cd dbt && DBT_PROFILES_DIR=. <dbt venv>/dbt parse --target prod` succeeds (if the local dbt venv is missing, rely on the CI `dbt` job and ledger it).
- [ ] **Step 5: Commit** (`feat(lakehouse): stale catalog export fails the build`).

---

### Task 2: Data-quality SLOs on the dashboard

**Files:** `infra/dashboard.tf`, test `tests/unit/test_dashboard_infra.py` (append).

- [ ] **Step 1: Failing test**

```python
def test_dashboard_charts_every_data_quality_slo() -> None:
    from collector.data_quality import CHECKS

    tf = (ROOT / "infra" / "dashboard.tf").read_text()
    for check in CHECKS:
        if check.threshold is None:
            continue  # recorded only, no SLO
        assert f'"{check.name}"' in tf, check.name
        if check.comparison == "min":
            assert re.search(rf"value\s*=\s*{check.threshold:g}\b", tf), check.name  # SLO line
```

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** append to `local.dashboard_widgets` (DQ metrics are daily: `period = 86400`):

```hcl
    {
      title   = "Data quality: freshness and volume"
      stat    = "Maximum"
      period  = 86400
      metrics = [for m in ["styles_behind", "stuck_ingest_runs", "weekly_volume_anomalies", "spotify_unsearched_stale"] : [local.data_quality_namespace, m]]
    },
    {
      title   = "Data quality: completeness (%)"
      stat    = "Minimum"
      period  = 86400
      metrics = [[local.data_quality_namespace, "isrc_coverage_pct"], [local.data_quality_namespace, "spotify_match_pct"]]
      annotations = { horizontal = [
        { label = "ISRC SLO", value = 99 },
        { label = "Spotify match SLO", value = 95 },
      ] }
    },
    {
      title   = "Data quality: integrity"
      stat    = "Maximum"
      period  = 86400
      metrics = [for m in ["orphan_identities", "bpm_out_of_range", "length_out_of_range"] : [local.data_quality_namespace, m]]
    },
```

and in the dashboard body: `period = try(w.period, 300)` and `properties = merge({ ...existing... }, try({ annotations = w.annotations }, {}))`.

- [ ] **Step 4:** test passes; `terraform fmt -check`, `terraform validate`; `jq` the rendered JSON in the PR plan (Task 4) for no `null`.
- [ ] **Step 5: Commit** (`feat(observability): data-quality SLOs on the dashboard`).

---

### Task 3: Docs

**Files:** `docs/data/lakehouse.md` (freshness gate), `docs/data/data-quality.md` (dashboard widgets), `docs/ops/runbook.md` (entry "Nightly dbt build failed: stale catalog export"), `docs/ops/failure-modes.md` (dbt row mentions the freshness gate).

- [ ] Runbook entry: symptom (`clouder-prod-transform-failed`, CodeBuild log shows `ERROR STALE` for `bronze.catalog_export`), check (`aws stepfunctions` / catalog-export Lambda errors, last `snapshot_dt` partition in S3), fix (re-run the export `aws lambda invoke --function-name clouder-prod-catalog-export`, then start the transform state machine).
- [ ] Guard tests green. Commit (`docs: freshness gate and DQ dashboard`).

---

### Task 4: PR, review, merge, verify

- [ ] Plan commit, graphify, push, PR; fresh review; one fix pass.
- [ ] PR plan: only `aws_codebuild_project.dbt` (buildspec) and `aws_cloudwatch_dashboard.overview` change (plus the known 2 derived IAM policies if still present).
- [ ] Merge → Deploy green (smoke passes) → start the transform state machine once → `SUCCEEDED` with freshness `PASS` for `catalog_export` in the CodeBuild log; dashboard shows the three widgets.
- [ ] README Operations: add the "Data quality: completeness (%)" snapshot (`scripts/dashboard_snapshots.py --widget "Data quality: completeness (%)"`) in a small follow-up commit/PR.
- [ ] §0 board: phase 4 done.

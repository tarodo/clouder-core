# P1 engineering maturity (CI gates, AWS hygiene, docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audit's P1: static analysis, locked dependencies and audits, coverage and route-consistency gates in CI, branch protection; a least-privilege IAM role per Lambda, error alarms on every function, Aurora data protection, API Gateway throttling and access logs; engineering highlights, scalability notes backed by 10×/100× synthetic runs, a Makefile and an experiments index.

**Architecture:** Each gate is a CI job or test that fails on regression. Infra changes are Terraform contract tests first (the repo's pattern: `tests/unit/test_*_infra.py` reading `infra/*.tf`), then the change; the IAM split derives each role's statements from what the function's code and env actually use, and is deployed last so a missing permission shows up as an emailed alarm, not a silent failure.

**Tech Stack:** ruff, mypy (+ pydantic plugin), pytest-cov, uv (`pip compile`), pip-audit, pnpm audit, Dependabot, Terraform, GitHub REST API (`gh api`).

**Spec:** hiring audit `~/Desktop/HIRING_AUDIT.ru.md` §0 items 7–17, §11 Level 2/3/4, §13.1 (outside the repo; rulings provisional).

## Global Constraints

- No money figures in the repo (owner rule) — so `docs/ops/cost.md` from item 16 is not written; scalability notes describe levers without prices.
- Measured state on 2026-10-08: ruff (E4/E7/E9/F) 95 findings; mypy (non-strict) 37 errors; coverage 84 % without DB tests, 85 % with them; pip-audit clean; `pnpm audit --prod`: 3 high, all `react-router` 7.14.2 (fixed in 7.18.2); 11 of 18 Lambdas on `aws_iam_role.collector_lambda`; error alarms on 10 of 18 functions.
- Prod changes ship through the normal deploy; nothing is applied by hand. Aurora changes are in place (no replacement).
- Tooling stays the project's: `docs/superpowers/` and `graphify-out/` stay where they are (the plan/graph tools write there); `ponytail:` comments stay (the owner's plugin convention).
- Branch `chore/p1-engineering`, worktree `../clouder-core-p1`; `$VENV=/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin`; Conventional Commits, no AI attribution; `git restore graphify-out` before commits.

## Review Focus

1. A Lambda loses a permission it used under the shared role (e.g. curation's presigned cover upload, the spotify worker re-enqueueing itself) → runtime AccessDenied in prod. Test: `test_role_matrix` in `tests/unit/test_iam_per_function_infra.py` pins every function's actions/resources against a matrix derived from code (Task 8).
2. A route added to the handler but not to Terraform (or vice versa) → `{"message":"Not Found"}` in prod. Test: `test_route_keys_agree` (Task 4).
3. The locked Lambda requirements resolve differently on Linux than on macOS → a broken zip. Test: the lock is compiled with `--universal --python-version 3.12`, and CI's `deps` job re-compiles and diffs it (Task 3).
4. API throttling set below what the SPA bursts on page load → 429s for real users. Test: `test_api_throttling_and_access_logs` asserts burst ≥ 100 and rate ≥ 50 (Task 7).
5. `deletion_protection` blocks a legitimate `terraform destroy` in the future — expected; the runbook says how to lift it (Task 6).

---

### Task 1: ruff + mypy gate

**Files:** Create `pyproject.toml`; Modify `requirements-dev.txt` (add `ruff`, `mypy`, `pytest-cov`, `pip-audit`), `.github/workflows/pr.yml` (job `lint`), source files flagged by the tools.

- [ ] Step 1 — `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
src = ["src", "tests", "scripts"]
extend-exclude = ["graphify-out", "experiments", "frontend", "dbt", "alembic/versions"]

[tool.ruff.lint]
select = ["E4", "E7", "E9", "F", "I", "B"]
ignore = ["B904", "B905"]  # raise-from and zip(strict=) are style changes across ~40 call sites

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["B011", "B017"]

[tool.mypy]
python_version = "3.12"
mypy_path = "src"
explicit_package_bases = true
ignore_missing_imports = true
plugins = ["pydantic.mypy"]
files = ["src/collector"]

[tool.coverage.run]
source = ["src/collector"]
```

- [ ] Step 2 — run `$VENV/ruff check src tests scripts` and `$VENV/mypy` → record counts (expected: non-zero). `ruff check --fix` (safe fixes only), then fix the rest by hand: move late imports to the top (E402, e.g. `handler.py` imports after `_split_phase_prefix`), drop unused variables, split `;` statements, rename shadowing loop vars, fix B023/B007/B010. mypy: fix real type errors (e.g. `aggregator.py` re-defined `counts` / tuple-vs-str keys, `None`-unsafe `.isoformat()` / `.value`), and use `typing.cast` or narrowing where the code is right; a `# type: ignore[code]` only with a one-line reason.
- [ ] Step 3 — `$VENV/ruff check src tests scripts` → 0; `$VENV/mypy` → 0; full `pytest -q` → pass. CI job `lint` (needs `changes`, runs when backend changed): `pip install -r requirements-dev.txt`, `ruff check src tests scripts`, `mypy`.
- [ ] Step 4 — commit `chore(lint): ruff and mypy gates in CI`.

### Task 2: Coverage gate

**Files:** Modify `.github/workflows/pr.yml` (`tests` job), `pyproject.toml`.

- [ ] Step 1 — `[tool.coverage.report] fail_under = 80`, `show_missing = false`; `tests` job runs `pytest -q --cov --cov-report=term --cov-report=xml` and appends the TOTAL line to `$GITHUB_STEP_SUMMARY`.
- [ ] Step 2 — locally: `pytest -q --cov --cov-fail-under=90` → fails (84 %), `--cov-fail-under=80` → passes. Commit `ci(tests): coverage gate at 80 %`. No README badge (it would need a third-party service).

### Task 3: Locked dependencies, audits, Dependabot

**Files:** Create `requirements-lambda.in`, `requirements-dev.in`, `.github/dependabot.yml`; Regenerate `requirements-lambda.txt`, `requirements-dev.txt`; Delete `src/collector/requirements.txt` (no references outside archived specs); Modify `.github/workflows/pr.yml` (job `deps`), `frontend/package.json` + lock (`react-router` ≥ 7.18.2), `docs/ops/deploy.md`.

- [ ] Step 1 — move today's unpinned lists to `.in` files (`requirements-dev.in` starts with `-r requirements-lambda.in` plus dev-only tools); compile: `uv pip compile --universal --python-version 3.12 requirements-lambda.in -o requirements-lambda.txt` and the same for dev. `scripts/package_lambda.sh` keeps installing `requirements-lambda.txt`, now pinned.
- [ ] Step 2 — CI job `deps` (always runs): `uv pip compile` both files again and `git diff --exit-code` (uv keeps existing pins, so it only fails on an edited `.in` without a recompile); `pip-audit -r requirements-lambda.txt -r requirements-dev.txt`; `cd frontend && pnpm audit --prod --audit-level high`. Dev-only npm advisories are left to Dependabot (ruling: they do not ship to users).
- [ ] Step 3 — `pnpm up react-router@^7.18.2` (and `react-router-dom` if present) → `pnpm audit --prod --audit-level high` exits 0; `pnpm typecheck && pnpm lint && pnpm test` → pass.
- [ ] Step 4 — `.github/dependabot.yml`: `pip` (`/`), `npm` (`/frontend`), `github-actions` (`/`), `terraform` (`/infra`), weekly, grouped minor/patch per ecosystem, 5 open PRs max.
- [ ] Step 5 — package the Lambda locally (`scripts/package_lambda.sh` into a temp dir) and import every handler module from the built tree with Python 3.12 → no ImportError. Commit `build(deps): lock Python deps, audit, Dependabot`.

### Task 4: Route consistency test

**Files:** Create `tests/contract/test_route_consistency.py`.

- [ ] Step 1 — test:

```python
"""A route exists in all three places or in none: Terraform, OpenAPI, handler code."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY = re.compile(r'"((?:GET|POST|PUT|PATCH|DELETE) /[^"]*)"')


def terraform_routes() -> set[str]:
    return {k for p in (ROOT / "infra").glob("*.tf") for k in KEY.findall(p.read_text())}


def openapi_routes() -> set[str]:
    sys.path.insert(0, str(ROOT / "scripts"))
    import generate_openapi

    return {f"{r['method'].upper()} {r['path']}" for r in generate_openapi.ROUTES}


def test_route_keys_agree() -> None:
    tf, spec = terraform_routes(), openapi_routes()
    assert sorted(tf - spec) == [] and sorted(spec - tf) == []


def test_every_route_is_handled_in_code() -> None:
    code = "\n".join(p.read_text() for p in (ROOT / "src" / "collector").rglob("*.py"))
    assert sorted(k for k in terraform_routes() if f'"{k}"' not in code) == []
```

  Run → if it passes on the first run, prove it by removing one route from `generate_openapi.ROUTES` locally (fails) and restoring. Commit `test(api): route keys agree across Terraform, OpenAPI, code`.

### Task 5: Error alarms on every function + Firehose delivery

**Files:** Modify `infra/alarms.tf`, `infra/telemetry.tf`; Test `tests/unit/test_alarm_routing_infra.py`.

- [ ] Step 1 — failing tests: every `aws_lambda_function` name is in `local.all_lambdas` (parse resource names, compare with the locals block); a `aws_cloudwatch_metric_alarm` on `AWS/Firehose` `DeliveryToS3.DataFreshness` (Maximum, 900 s period, threshold 900 s, `notBreaching`) for the telemetry stream, routed through `local.alarm_actions`.
- [ ] Step 2 — add the 8 missing functions (analytics_api, artist_enricher_worker, auto_enrich_dispatch_worker, backfill, catalog_export, comments_collect_worker, db_migration, telemetry) to the worker/api maps; add the Firehose alarm. `terraform fmt` + `validate`; commit `feat(alarms): errors on all 18 Lambdas, Firehose freshness`.

### Task 6: Aurora data protection

**Files:** Modify `infra/rds.tf`, `docs/ops/aurora.md`, `docs/ops/runbook.md`; Test `tests/unit/test_aurora_protection_infra.py`.

- [ ] Step 1 — failing test: `deletion_protection = true`, `skip_final_snapshot = false`, `final_snapshot_identifier = "${local.name_prefix}-aurora-final"`, `backup_retention_period = 7`, `copy_tags_to_snapshot = true`.
- [ ] Step 2 — apply in `rds.tf`; docs: how to lift protection deliberately (set false, apply, then destroy). Commit `feat(aurora): deletion protection, final snapshot, 7-day backups`.

### Task 7: API Gateway throttling and access logs

**Files:** Modify `infra/api_gateway.tf`, `infra/logging.tf` (log group), `docs/ops/logs.md`, `docs/ops/runbook.md`; Test `tests/unit/test_api_gateway_infra.py`.

- [ ] Step 1 — failing test `test_api_throttling_and_access_logs`: the `$default` stage has `default_route_settings { throttling_burst_limit >= 100, throttling_rate_limit >= 50 }` and `access_log_settings` to a log group `/aws/apigateway/${local.name_prefix}-collector-api` with a JSON format containing `requestId`, `routeKey`, `status`, `integrationLatency`, `ip`.
- [ ] Step 2 — implement (burst 200, rate 100 rps — the SPA fires about ten calls on load per user; a closed group stays far below); log retention `var.log_retention_days`; logs doc + runbook "429 Too Many Requests". Commit `feat(api): stage throttling and JSON access logs`.

### Task 8: A least-privilege role per Lambda

**Files:** Modify `infra/iam.tf` (split), `infra/lambda.tf`, `infra/auth.tf`, `infra/curation.tf` (role references), `docs/architecture.md`, `README.md` (limitations); Create `tests/unit/test_iam_per_function_infra.py`.

**Matrix** (derived from each function's env and code on 2026-10-08; all get own-log-group logs, and all except `db_migration` get Data API + the Aurora secret):

| Function | S3 | SQS send | SQS consume | SSM / KMS | Other |
|---|---|---|---|---|---|
| collector | Put/Get raw prefix, List raw prefix | canonicalization, spotify_search, label_enrichment, artist_enrichment | — | — | invoke auto-ingest |
| curation | Put/Get `covers/*`, Get raw prefix | label_enrichment, artist_enrichment, vendor_match, auto_enrich_dispatch, comments_collect | — | Spotify + YT Music OAuth params, `alias/aws/ssm`; user-tokens key (GenerateDataKey, Decrypt) | — |
| auth_handler | — | — | — | JWT signing key, Spotify + YT Music OAuth params, `alias/aws/ssm`; user-tokens key | — |
| canonicalization_worker | Get raw prefix, Put raw prefix (quarantine) | spotify_search | canonicalization | — | — |
| spotify_search_worker | Put spotify raw prefix | spotify_search | spotify_search | Spotify client params, `alias/aws/ssm`; Spotify credentials secret if set | — |
| vendor_match_worker | — | comments_collect | vendor_match | Spotify client params, `alias/aws/ssm`; Spotify credentials secret if set | — |
| label_enricher_worker | — | label_enrichment | label_enrichment | Gemini/OpenAI/Tavily/DeepSeek params, `alias/aws/ssm` | — |
| artist_enricher_worker | — | artist_enrichment | artist_enrichment | same as label | — |
| auto_enrich_dispatch_worker | — | label_enrichment, artist_enrichment, comments_collect | auto_enrich_dispatch | — | — |
| comments_collect_worker | — | — | comments_collect | YouTube API key param, `alias/aws/ssm` | — |
| db_migration | — | — | — | — | Aurora secret, `rds-db:connect` for the migrator user, VPC ENI actions |

- [ ] Step 1 — before writing the test, verify every cell against the code (`git grep` for the queue URL env vars, `create_default_s3_client`/`generate_presigned`, `ssm`, `kms` per handler module and its imports); a cell that the code does not need is dropped, a need the table misses is added — ledger each change.
- [ ] Step 2 — failing test `test_role_matrix`: parse `infra/*.tf`, map each `aws_lambda_function` to its role, collect that role's policy statements (actions + resource expressions) and compare with the matrix encoded in the test; plus `test_no_lambda_uses_the_shared_role` (no function references `aws_iam_role.collector_lambda`).
- [ ] Step 3 — implement: a small module `infra/modules/lambda_role/` (inputs: name, log group ARN, list of statement objects; outputs: role ARN) or one `aws_iam_role` + `aws_iam_policy_document` per function in `iam.tf` — pick the module only if it removes repetition the test can still read. Keep the old `collector_lambda` role until no function references it, then delete it in the same change. `terraform fmt` + `validate`.
- [ ] Step 4 — full pytest → pass; commit `feat(iam): least-privilege role per Lambda`.

### Task 9: Highlights, scalability, Makefile, experiments index

**Files:** Create `docs/engineering-highlights.md`, `docs/scalability.md`, `Makefile`, `experiments/README.md`; Modify `scripts/bench_canonicalize.py` only if larger sizes need it, `docs/benchmarks/canonicalization.md`, `README.md` (links, limitations), `docs/architecture.md` (links).

- [ ] Step 1 — run `scripts/bench_canonicalize.py --tracks 6710 36560 --database-url $TEST_DATABASE_URL` (10× the mean and the max week), and `--tracks 67100` if it finishes in under 15 minutes locally (100× the mean); record calls, calls/1k tracks, local seconds, modelled seconds; append the table to `docs/benchmarks/canonicalization.md`.
- [ ] Step 2 — `docs/scalability.md`: what limits each part at 10× and 100× (Data API 1 MB result / 4 MB batch limits and the per-call latency — with the new numbers; Lambda 900 s timeout vs modelled run time; SQS/worker concurrency vs the account quota of 10; fuzzy matcher O(n·m) and blocking keys; Athena small files — compaction already in dbt; Aurora ACU range) and the next step for each. No prices.
- [ ] Step 3 — `docs/engineering-highlights.md`: 8 "where to look" entries with a link and two lines each (set-based canonicalization, replay-safe writes, data contract, DQ checks, auto-ingest planner + lease, entity-resolution eval, Data API retry policy, dbt silver/SCD2, two-phase deploy).
- [ ] Step 4 — `Makefile`: `bootstrap`, `test`, `test-db`, `lint`, `typecheck`, `cov`, `lock`, `openapi`, `package`, `frontend-test`, `screenshots`, `dbt-ci`; each target is the command already used in CI/docs. `experiments/README.md`: one paragraph per sandbox (goal, result, decision) from each experiment's own README.
- [ ] Step 5 — README: link highlights/scalability, update "Known limitations" (per-function IAM, throttling, Aurora protection done; one environment remains), add `make` to "Running it locally". Link test + README test → pass. Commit `docs: engineering highlights, scalability, Makefile`.

## After merge

1. Deploy (IAM roles switch in place; watch the 27+ alarms and `AccessDenied` in logs for an hour: `aws logs filter-log-events --log-group-name <each> --filter-pattern AccessDenied`).
2. Branch protection on `main` via `gh api`: require a PR, required checks `changes`, `tests`, `lint`, `deps`, `alembic-check`, `frontend`, `terraform`, `dbt` (skipped jobs pass), strict up-to-date off, no required reviews (single maintainer), `enforce_admins` false (owner keeps an emergency path). Environment `production`: deployments only from `main`.
3. Graph refresh, worktree cleanup, audit §0 status.

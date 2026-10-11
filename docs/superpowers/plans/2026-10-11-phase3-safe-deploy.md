# Phase 3 — Safe deploy: reproducible package, API aliases, smoke-gated rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A deploy that breaks the API is detected within minutes and the six API Lambdas return to their previous code in seconds, without a revert PR.

**Architecture:** (1) The Lambda zip becomes byte-reproducible, so Terraform publishes a new version only when code really changes. (2) The six API-facing functions (`collector`, `curation`, `auth_handler`, `auth_authorizer`, `analytics`, `telemetry`) publish versions behind a `live` alias; API Gateway calls the alias. Workers stay unqualified — SQS retries and DLQs already absorb a bad worker deploy. (3) The deploy snapshots the alias versions before `terraform apply`, runs a smoke test after the frontend sync, and on failure points every alias back to its snapshot version and fails the job.

**Tech Stack:** Terraform (aws ~> 5.100), GitHub Actions, Python 3.12 stdlib + boto3 (scripts), pytest.

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` §0 phase 3, §1.4 item 5, roadmap L2 "post-deploy smoke + versions/aliases + Rollback section" (outside the repo); phase-1 finding: `package_lambda.sh` is not byte-reproducible, so all 18 Lambdas change in every plan.

## Global Constraints

- Worktree `<repo>`, branch `feat/safe-deploy` from `origin/main` (`16f6adc3`).
- No downtime while switching API Gateway to aliases: an alias permission must exist before the integration points at the alias.
- The smoke test must not write anything or touch Aurora (auto-pause makes DB calls slow and flaky): Lambda invokes use routes that answer 404/400/deny before any I/O.
- Rollback covers Lambda code of the six API functions only; DB migrations are backward compatible by policy (`docs/ops/deploy.md`), the frontend and workers are not rolled back — documented.
- Version storage: ~25 MB per function version; a code-changing deploy adds ~150 MB against the 300 GB account limit (usage 0.45 GB on 2026-10-11) — no pruning now, ceiling documented.
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **Integration switches before the alias permission exists** → API Gateway gets 500 "invalid permissions" for a few seconds of the first deploy. Task 2 adds `depends_on` from each integration/authorizer to the alias permissions and keeps the old unqualified permissions.
2. **A smoke event that is not harmless** (e.g. collector `routeKey: ""` maps to the ingest path). Task 3 runs every smoke event through the real handler locally and asserts the status with network calls forbidden.
3. **Rollback restores the wrong version** (first deploy has no alias yet; snapshot taken after apply). Task 4 snapshots before apply, skips missing aliases, and the workflow test pins the step order.
4. **Non-deterministic zip after all** (pip writes timestamps or `RECORD` differences). Task 1 checks the byte identity of two real `package_lambda.sh` builds in CI-like conditions.
5. **Terraform resets aliases on the next apply after a rollback.** Intended (fix forward), but it must be documented so nobody is surprised (Task 5).

---

### Task 1: Byte-reproducible Lambda zip

**Files:** Create `scripts/deterministic_zip.py`; modify `scripts/package_lambda.sh:24-28`; test `tests/unit/test_deterministic_zip.py`.

**Interfaces:** Produces `deterministic_zip.build(src_dir: Path, out_zip: Path) -> None` — sorted entries, fixed timestamp 1980-01-01, mode 0o755 for files with any exec bit else 0o644, `ZIP_DEFLATED` level 9.

- [ ] **Step 1: Failing test** — `tests/unit/test_deterministic_zip.py`:

```python
"""Same files in, same bytes out: Terraform publishes a new Lambda version only on real change."""

from __future__ import annotations

import importlib.util
import os
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deterministic_zip.py"
spec = importlib.util.spec_from_file_location("deterministic_zip", SCRIPT)
dz = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dz)


def _tree(root: Path, mtime: int) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "b.py").write_text("B = 2\n")
    (root / "a.py").write_text("A = 1\n")
    tool = root / "pkg" / "tool.sh"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o775)
    for p in root.rglob("*"):
        os.utime(p, (mtime, mtime))
    return root


def test_same_files_give_identical_bytes(tmp_path: Path) -> None:
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    dz.build(_tree(tmp_path / "x", 1_700_000_000), one)
    dz.build(_tree(tmp_path / "y", 1_800_000_000), two)
    assert one.read_bytes() == two.read_bytes()


def test_entries_are_sorted_with_normalized_modes(tmp_path: Path) -> None:
    out = tmp_path / "out.zip"
    dz.build(_tree(tmp_path / "x", 1_700_000_000), out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names == sorted(names) == ["a.py", "pkg/b.py", "pkg/tool.sh"]
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        assert modes == {"a.py": 0o644, "pkg/b.py": 0o644, "pkg/tool.sh": 0o755}
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
```

Run: `PYTHONPATH=src <venv>/bin/pytest tests/unit/test_deterministic_zip.py -q` → FAIL (`FileNotFoundError` for the script).

- [ ] **Step 2: Implement** — `scripts/deterministic_zip.py`:

```python
"""Zip a directory so the same files always give the same bytes.

`zip -r` stores mtimes and walk order, so every build differed and Terraform saw all
Lambdas change on every plan. Usage: deterministic_zip.py SRC_DIR OUT_ZIP
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

EPOCH = (1980, 1, 1, 0, 0, 0)


def build(src_dir: Path, out_zip: Path) -> None:
    files = sorted(p for p in src_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(src_dir).as_posix(), EPOCH)
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes(), compresslevel=9)


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))
```

and in `package_lambda.sh` replace the `( cd "$BUILD_DIR"; zip -qr "$OUTPUT_ZIP" . )` block with:

```bash
python "$ROOT_DIR/scripts/deterministic_zip.py" "$BUILD_DIR" "$OUTPUT_ZIP"
```

- [ ] **Step 3:** test passes. Then real build twice: `make package && shasum -a 256 dist/collector.zip > /tmp/a && make package && shasum -a 256 dist/collector.zip` → same hash. If it differs, list differing entries with a zip diff and normalize them (ledger a ruling).
- [ ] **Step 4: Commit** (`build(lambda): reproducible package zip`).

---

### Task 2: `live` aliases for the six API functions

**Files:** Create `infra/lambda_aliases.tf`; modify the six `aws_lambda_function` resources (`publish = true`) and their integrations/authorizer (`infra/api_gateway.tf:21`, `infra/auth.tf:152,159`, `infra/curation.tf:52`, `infra/analytics_routes.tf:171`, `infra/telemetry.tf` integration); test `tests/unit/test_api_aliases_infra.py`.

**Interfaces:** Produces `aws_lambda_alias.live[<key>]` for keys `collector`, `curation`, `auth_handler`, `auth_authorizer`, `analytics`, `telemetry`; output `api_alias_functions` (list of function names) for Task 4.

- [ ] **Step 1: Failing test** — `tests/unit/test_api_aliases_infra.py`:

```python
"""API Gateway calls the `live` alias of each API function (phase 3, ADR-0029)."""

from __future__ import annotations

import re
from pathlib import Path

INFRA = Path(__file__).resolve().parents[2] / "infra"
TF = "\n".join(p.read_text() for p in sorted(INFRA.glob("*.tf")))
API = {"collector", "curation", "auth_handler", "auth_authorizer", "analytics", "telemetry"}


def _fn(name: str) -> str:
    m = re.search(rf'resource "aws_lambda_function" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, name
    return m.group(1)


def test_api_functions_publish_versions() -> None:
    for name in API:
        assert re.search(r"publish\s*=\s*true", _fn(name)), name


def test_every_api_integration_targets_the_alias() -> None:
    uris = re.findall(r"(?:integration_uri|authorizer_uri)\s*=\s*([^\n]+)", TF)
    assert uris and all("aws_lambda_alias.live[" in u for u in uris), uris


def test_alias_permissions_exist_and_gate_the_integrations() -> None:
    aliases = (INFRA / "lambda_aliases.tf").read_text()
    assert re.search(r'qualifier\s*=\s*aws_lambda_alias\.live\[each\.key\]\.name', aliases)
    for block in re.findall(r'resource "aws_apigatewayv2_(?:integration|authorizer)" "[a-z_]+" \{(.*?)\n\}', TF, re.S):
        assert "aws_lambda_permission.api_live" in block  # depends_on: permission before switch
```

- [ ] **Step 2:** run → 3 FAIL.
- [ ] **Step 3: Implement** — `infra/lambda_aliases.tf`:

```hcl
# ── `live` aliases for the API functions (ADR-0029) ──
# API Gateway calls the alias, so a failed smoke test can point it back to the previous
# version in seconds (scripts/api_aliases.py). Workers stay unqualified: SQS retries
# and DLQs already absorb a bad worker deploy.

locals {
  api_functions = {
    collector       = aws_lambda_function.collector
    curation        = aws_lambda_function.curation
    auth_handler    = aws_lambda_function.auth_handler
    auth_authorizer = aws_lambda_function.auth_authorizer
    analytics       = aws_lambda_function.analytics
    telemetry       = aws_lambda_function.telemetry
  }
}

resource "aws_lambda_alias" "live" {
  for_each         = local.api_functions
  name             = "live"
  function_name    = each.value.function_name
  function_version = each.value.version
}

# Alias-scoped invoke permissions. The unqualified ones stay so nothing breaks while an
# integration switches; integrations depend on these.
resource "aws_lambda_permission" "api_live" {
  for_each      = local.api_functions
  statement_id  = "AllowAPIGatewayInvokeLive"
  action        = "lambda:InvokeFunction"
  function_name = each.value.function_name
  qualifier     = aws_lambda_alias.live[each.key].name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.collector.execution_arn}/*/*"
}

output "api_alias_functions" {
  description = "API functions behind the live alias (scripts/api_aliases.py)"
  value       = [for f in local.api_functions : f.function_name]
}
```

In each of the six functions add `publish = true`. Each integration: `integration_uri = aws_lambda_alias.live["<key>"].invoke_arn` and `depends_on = [aws_lambda_permission.api_live]`; the authorizer: `authorizer_uri = aws_lambda_alias.live["auth_authorizer"].invoke_arn` plus the same `depends_on`.

- [ ] **Step 4:** tests pass; `terraform fmt -check` and `terraform validate` (init `-backend=false`) pass; full backend suite green (the IAM/route guard tests must still pass).
- [ ] **Step 5: Commit** (`feat(infra): live aliases for API Lambdas`).

---

### Task 3: Smoke test

**Files:** Create `scripts/smoke.py`; test `tests/unit/test_smoke.py`.

**Interfaces:** Produces `LAMBDA_CHECKS: dict[str, tuple[dict, int]]` (function suffix → (event, expected status)); `check_lambda(payload: dict, expected: int) -> str | None`; `check_http(status: int, headers: dict, body: str, expect: dict) -> str | None`; `main(api_url, site_url, prefix, client) -> int`.

Smoke set (no writes, no Aurora):
- Lambda (alias `live`): `collector-api` GET `/__smoke` → 404; `curation` GET `/__smoke` → 404; `auth-handler` GET `/__smoke` → 404; `analytics-api` GET `/v1/analytics/__smoke` → 404; `telemetry` POST with empty body → 400; `auth-authorizer` with no `Authorization` header → `{"isAuthorized": false}`.
- HTTP: `GET {api}/auth/login` → 302 with `Location` on `accounts.spotify.com`; `GET {api}/styles` without a token → 401; `GET {site}/` → 200 containing `<div id="root">`.

- [ ] **Step 1: Failing tests** — `tests/unit/test_smoke.py` covers: (a) every `LAMBDA_CHECKS` event, run through the real handler with `boto3.client` and the Data API patched to raise, returns the expected status (proves harmlessness); (b) `check_lambda` / `check_http` flag a wrong status, a Lambda `FunctionError`, a missing redirect host; (c) `main` with a fake client and fake HTTP returns 0 when all pass and 1 with a message per failure.
- [ ] **Step 2:** run → FAIL (module missing).
- [ ] **Step 3: Implement** `scripts/smoke.py` (boto3 `lambda.invoke(..., Qualifier="live")`, `urllib.request` with redirects disabled, 20 s timeout, one retry for HTTP 5xx); CLI: `smoke.py --api URL --site URL --prefix clouder-prod`.
- [ ] **Step 4:** tests pass; full suite; ruff; mypy (scripts are outside mypy's `files`, ruff covers them).
- [ ] **Step 5: Commit** (`feat(deploy): post-deploy smoke test`).

---

### Task 4: Snapshot, smoke, roll back in `deploy.yml`

**Files:** Create `scripts/api_aliases.py`; modify `.github/workflows/deploy.yml`; tests `tests/unit/test_api_aliases.py`, `tests/unit/test_ci_workflows.py` (append).

**Interfaces:** `snapshot(client, functions) -> dict[str, str]` (function → alias version; functions without an alias are skipped); `restore(client, snapshot) -> list[str]` (calls `update_alias` only where the current version differs; returns changed functions). CLI: `api_aliases.py snapshot FUNCS... > file`, `api_aliases.py restore file`.

- [ ] **Step 1: Failing tests** — fake client with `get_alias`/`update_alias` (raising `ResourceNotFoundException` for missing aliases): snapshot skips missing; restore updates only differing; restore of an empty snapshot is a no-op. Workflow test: step order `Snapshot API aliases` < `Terraform apply` < `Smoke test` and `Roll back API aliases` has `if: failure() && steps.snapshot.outcome == 'success'` and runs after the smoke step.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `scripts/api_aliases.py`; in `deploy.yml` after `Terraform init`:

```yaml
      - name: Snapshot API aliases
        id: snapshot
        working-directory: .
        run: |
          python scripts/api_aliases.py snapshot \
            clouder-prod-collector-api clouder-prod-curation clouder-prod-auth-handler \
            clouder-prod-auth-authorizer clouder-prod-analytics-api clouder-prod-telemetry \
            > "$RUNNER_TEMP/aliases.json"
```

after `Deploy frontend`:

```yaml
      - name: Smoke test
        working-directory: .
        run: |
          python scripts/smoke.py --prefix clouder-prod \
            --api "$(cd infra && terraform output -raw api_endpoint)" \
            --site "$(cd infra && terraform output -raw frontend_url)"

      - name: Roll back API aliases
        if: failure() && steps.snapshot.outcome == 'success'
        working-directory: .
        run: python scripts/api_aliases.py restore "$RUNNER_TEMP/aliases.json"
```

(`boto3` comes from `pip install boto3` in a step after `Setup Python`, or from `requirements-dev.txt` — use `pip install boto3==<version in requirements-dev.txt>`.)
- [ ] **Step 4:** tests pass; full suite.
- [ ] **Step 5: Commit** (`feat(deploy): smoke-gated alias rollback`).

---

### Task 5: Docs

**Files:** `docs/ops/deploy.md` (new sections "How a change reaches production", "Rollback"), `docs/ops/failure-modes.md` ("A bad deploy" row), `docs/adr/0029-api-aliases-smoke-rollback.md` + index, `README.md` (Production readiness → Delivery; ADR count 28 → 29), `docs/scalability.md` (version storage ceiling).

- [ ] Rollback section: automatic (smoke fails → aliases back, job red); manual (`python scripts/api_aliases.py restore` with a saved snapshot, or `aws lambda update-alias --function-name … --name live --function-version N`); what is not rolled back (frontend, workers, migrations) and that the next apply moves aliases forward again (fix forward). Measured: time of the alias switch (from the drill in Task 6).
- [ ] Guard tests green (README counts, links, ADR index).
- [ ] Commit (`docs: safe deploy and rollback`).

---

### Task 6: PR, review, merge, verify, drill

- [ ] Plan commit, graphify, push, PR via `caveman:caveman-commit`; fresh review; one fix pass.
- [ ] PR plan: exactly the expected changes (6 functions `publish`, 6 aliases, 6 permissions, 6 integration/authorizer URIs) and — after this PR — Lambda `source_code_hash` stops changing on PRs that do not touch `src/`.
- [ ] Merge → Deploy green with the smoke step passing; `aws apigatewayv2 get-integrations` shows alias ARNs; the site renders.
- [ ] **Drill** (after the next code-changing deploy publishes version N+1): snapshot → `update-alias` to N → smoke against N → restore; record the switch time in `deploy.md`. If no second version exists yet, record the drill as pending on the §0 board.
- [ ] §0 board: phase 3 done.

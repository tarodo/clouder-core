# Phase 2 — Docs that match production, guarded by tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every statement the audit found false is corrected, a test stops each from coming back, and the README gains the reviewer-facing sections from audit §12.

**Architecture:** Guard tests first (they fail on today's tree), then the content fixes that turn them green, then two small code changes (lint warnings, CloudFront TLS setting), then the README additions. Docs-only except `infra/frontend.tf` (a no-op for AWS: it writes the value CloudFront already has) and one frontend hook refactor with unchanged behavior.

**Tech Stack:** pytest guard tests (`tests/unit/`), Markdown, Terraform, React/TypeScript (ESLint).

**Spec:** `~/Desktop/HIRING_AUDIT_2026-10-08.ru.md` — §0 phase 2, §1.4 item 4, §12 (README text), phase-1 finding on CloudFront TLS (outside the repo). Evidence 2026-10-11:
- `docs/data/auto-ingest.md` says "Status: deployed disabled", "After" says "Pending"; CloudWatch: `styles_behind` 2 on 10-07/10-08 → 0 from 10-09; 15 completed auto-ingest invocations 10-08…10-10, 45 style-weeks ingested, 0 failed.
- `frontend/README.md` names `beatport-prod-auth-handler` 5×; ADR-0006/0011 use `beatport-prod-*` function names.
- README: "including 51 against a real PostgreSQL" (actual 54).
- `infra/variables.tf:134,457`, `infra/terraform.tfvars.example:35`: Russian text, one money figure.
- `docs/superpowers/**`: 327 absolute local paths (the home directory and the agent scratchpad) in 30 files.
- `pytest.ini`: `pythonpath = src analytics` (no `analytics/`); `.gitignore` lines 36–40 for `analytics/dbt/*`.
- ESLint: 3 warnings (`useCurateSession.ts:229,266` exhaustive-deps; `theme.ts:278` unused disable).
- CloudFront: config `minimum_protocol_version = "TLSv1.2_2021"`, live `TLSv1` (default `*.cloudfront.net` certificate forces it) → perpetual plan diff.

## Global Constraints

- Worktree `<repo>`, branch `docs/truth-and-guards` from `origin/main` (`942cfa91`).
- Backend tests: `PYTHONPATH=src <repo>/.venv/bin/pytest -q`; frontend: `pnpm` from `frontend/`.
- No money figures, no real account ids, no new claims a reader cannot verify by a link.
- `beatport-prod-*` stays legitimate for the raw and analytics-lake buckets, the Athena workgroup, the frontend bucket/OAC/functions and the Beatport provider code (CLAUDE.md gotcha 4) — guards target Lambda function names only.
- Commits and PR text via `caveman:caveman-commit`; no attribution lines.

## Review Focus

1. **A guard that matches legitimate text** (e.g. `beatport-prod-analytics` workgroup, `beatport-prod-raw` bucket) → CI red for a true statement. The name guard derives forbidden names from Terraform's Lambda `function_name`s only (Task 1).
2. **Path replacement corrupts a command** in `docs/superpowers` (e.g. `cd /Users/... && …` → `cd  && …`). Replacement uses the `<repo>` token, never an empty string (Task 2).
3. **The ESLint refactor changes when an effect fires** (telemetry `markShown` per track, next-page prefetch). Existing `useCurateSession` tests must stay green unmodified (Task 3).
4. **The TLS change is not a no-op** in AWS. The PR plan must show `aws_cloudfront_distribution.frontend` absent from the diff (Task 5).
5. **README additions overclaim** (e.g. "rehearsed restore", "read-only CI only"). Every new README sentence must be true today and link to its evidence (Task 4 review checklist).

---

### Task 1: Guard tests (RED)

**Files:**
- Modify: `tests/unit/test_docs_freshness.py` (append), `tests/unit/test_readme.py` (append), `tests/unit/test_guardrails_infra.py` (append)
- Create: `tests/unit/test_repo_hygiene.py`

- [ ] **Step 1: Append to `tests/unit/test_docs_freshness.py`**

```python
def _lambda_suffixes() -> set[str]:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    return set(re.findall(r'function_name\s*=\s*"\$\{local\.name_prefix\}-([a-z0-9-]+)"', tf))


def test_docs_call_lambdas_by_their_current_names() -> None:
    # The functions were renamed beatport-prod-* -> clouder-prod-*; buckets and the Athena
    # workgroup kept the old prefix on purpose (CLAUDE.md gotcha 4), so only function names count.
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    suffixes = _lambda_suffixes()
    assert len(suffixes) == len(re.findall(r'^resource "aws_lambda_function"', tf, re.M))
    stale = re.compile(r"beatport-prod-(" + "|".join(sorted(suffixes, key=len, reverse=True)) + r")\b")
    docs = [*live_docs(), *sorted((ROOT / "docs" / "adr").glob("*.md")), ROOT / "frontend" / "README.md"]
    hits = [f"{d.relative_to(ROOT)}:{n}" for d in docs
            for n, line in enumerate(d.read_text(encoding="utf-8").splitlines(), 1) if stale.search(line)]
    assert hits == []


def test_auto_ingest_doc_reports_production() -> None:
    doc = (ROOT / "docs" / "data" / "auto-ingest.md").read_text()
    status = next(line for line in doc.splitlines() if line.startswith("Status:"))
    assert "disabled" not in status
    after = doc.split("## After", 1)[1].split("\n## ", 1)[0]
    assert "Pending" not in after and re.search(r"\d", after)
```

- [ ] **Step 2: Create `tests/unit/test_repo_hygiene.py`**

```python
"""Tracked text carries no machine-local paths, and config points at real directories."""

from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Each alternative needs a real path character after the prefix, so this line never matches itself.
LOCAL_PATH = re.compile(r"/Users/[A-Za-z]|/private/tmp/claude-\d|/home/[a-z]+/")


def test_tracked_markdown_has_no_local_paths() -> None:
    files = subprocess.run(["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True)
    hits = []
    for rel in files.stdout.split():
        for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if LOCAL_PATH.search(line):
                hits.append(f"{rel}:{n}")
    assert hits == [], hits[:10]


def test_pytest_pythonpath_entries_exist() -> None:
    ini = configparser.ConfigParser()
    ini.read(ROOT / "pytest.ini")
    for entry in ini["pytest"]["pythonpath"].split():
        assert (ROOT / entry).is_dir(), entry


def test_gitignore_has_no_patterns_for_removed_trees() -> None:
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert not [line for line in lines if line.startswith("analytics/")]
```

- [ ] **Step 3: Append to `tests/unit/test_guardrails_infra.py`**

```python
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
MONEY = re.compile(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|/mo(nth)?\b|/мес", re.IGNORECASE)


def test_infra_text_is_english_and_moneyless() -> None:
    files = [*sorted(INFRA.glob("*.tf")), INFRA / "terraform.tfvars.example"]
    hits = [f"{p.name}:{n}" for p in files for n, line in enumerate(p.read_text().splitlines(), 1)
            if CYRILLIC.search(line) or MONEY.search(line)]
    assert hits == []


def test_default_cloudfront_certificate_keeps_tlsv1() -> None:
    # With cloudfront_default_certificate CloudFront forces TLSv1; any other value is a
    # perpetual plan diff and a security claim that is not true (docs/security.md).
    cert = re.search(r"viewer_certificate \{(.*?)\}", (INFRA / "frontend.tf").read_text(), re.S).group(1)
    assert re.search(r"cloudfront_default_certificate\s*=\s*true", cert)
    assert re.search(r'minimum_protocol_version\s*=\s*"TLSv1"', cert)
```

- [ ] **Step 4: Append to `tests/unit/test_readme.py`**

```python
def test_readme_has_the_production_readiness_section_and_no_stale_test_count() -> None:
    assert "## Production readiness" in README
    assert not re.search(r"\d+ against a real PostgreSQL", README)  # counts drift; say what, not how many


def test_frontend_lint_fails_on_warnings() -> None:
    import json

    scripts = json.loads((ROOT / "frontend" / "package.json").read_text())["scripts"]
    assert "--max-warnings=0" in scripts["lint"]
```

- [ ] **Step 5: Run — all new tests fail for the reasons in the spec evidence**

Run: `PYTHONPATH=src <repo>/.venv/bin/pytest -q tests/unit/test_docs_freshness.py tests/unit/test_repo_hygiene.py tests/unit/test_guardrails_infra.py tests/unit/test_readme.py`
Expected: 9 FAIL (names, auto-ingest, local paths, pythonpath, gitignore, infra text, TLS, README section/count, lint flag); every pre-existing test passes.

- [ ] **Step 6: Commit** (`test: guard docs, infra text and lint drift`).

---

### Task 2: Make docs and config true

**Files:** `frontend/README.md`, `docs/adr/0006-spotify-metadata-fallback.md:27`, `docs/adr/0011-spotify-token-bundling.md:26`, `docs/superpowers/**`, `docs/data/auto-ingest.md`, `infra/variables.tf:134,457`, `infra/terraform.tfvars.example:35`, `infra/frontend.tf:289-292`, `docs/security.md` (known gaps), `pytest.ini`, `.gitignore`.

- [ ] **Step 1: Function names** — `beatport-prod-auth-handler` → `clouder-prod-auth-handler` in `frontend/README.md` (5×) and ADR-0011; `beatport-prod-spotify-search-worker` → `clouder-prod-spotify-search-worker` in ADR-0006.

- [ ] **Step 2: Local paths** — in every tracked `docs/**/*.md`:

```bash
git ls-files 'docs/*.md' | xargs perl -pi -e '
  s{/Users/[^/\s]+/Projects/clouder-projects/clouder-core[\w-]*}{<repo>}g;
  s{/Users/[^/\s]+/\.pyenv/versions/[\d.]+/bin/(python[\d.]+)}{$1}g;
  s{/private/tmp/claude-\d+/[^\s`"\x27)]*}{<scratchpad>}g;'
git grep -n -E '/Users/[A-Za-z]|/private/tmp/claude-[0-9]' -- '*.md'   # expect nothing
```

- [ ] **Step 3: `docs/data/auto-ingest.md`** — replace lines 3–4 with
`Status: deployed and enabled since 2026-10-08; runs are planned daily at 00:05 UTC.`
and the `## After` body with:

```markdown
Measured on production, 2026-10-08 → 2026-10-11 (CloudWatch metrics and the
`auto_ingest_run_completed` log events):

| | Before | After |
|---|---|---|
| `styles_behind` (nightly check) | 2 on 2026-10-07 and 10-08 | 0 from 2026-10-09 on |
| Runs | manual only | 15 completed in the first three days (3 a day once the plan settled) |
| Style-weeks ingested | — | 45, 0 failed |
| Manual steps | a token pasted per style × week | none |
```

- [ ] **Step 4: Infra text** — `variables.tf:134` description → `"Aurora Serverless v2 min ACU. 0 = auto-pause after aurora_auto_pause_seconds (cold-start 503 risk through API Gateway; see ADR-0014). 0.5 = always warm."`; `variables.tf:457` → `"CORS origins for API Gateway. An empty list disables CORS."`; `terraform.tfvars.example:35` → `# CORS: list the frontend origins. An empty list disables CORS (server-to-server only).`

- [ ] **Step 5: CloudFront TLS** — `infra/frontend.tf` `viewer_certificate`:

```hcl
  viewer_certificate {
    # The default *.cloudfront.net certificate forces TLSv1 whatever is set here, so
    # anything else is a perpetual plan diff. TLS 1.2 minimum needs a custom domain
    # with an ACM certificate (docs/security.md, known gaps).
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1"
  }
```

and add to `docs/security.md` "Known gaps":
`- **Minimum TLS is CloudFront's default for *.cloudfront.net (TLSv1).** Browsers negotiate TLS 1.2+ anyway; enforcing it needs a custom domain with an ACM certificate.`

- [ ] **Step 6: Hygiene** — `pytest.ini`: `pythonpath = src`; `.gitignore`: delete the `# dbt venv and build artifacts` block's four `analytics/dbt/*` lines (keep `.dbt-venv/`).

- [ ] **Step 7: Run** the Task 1 command → only the README and lint tests still fail. Full backend suite green.

- [ ] **Step 8: Commit** (`docs: match production; English infra text`).

---

### Task 3: Zero ESLint warnings without changing behavior

**Files:** `frontend/src/features/curate/hooks/useCurateSession.ts:227-229,258-268`, `frontend/src/theme.ts:277`, `frontend/package.json` (`lint` script)

- [ ] **Step 1:** markShown effect — depend on the id the effect uses:

```ts
  const currentTrackId = currentTrack?.track_id;
  useEffect(() => {
    if (currentTrackId) telemetry.markShown(currentTrackId);
  }, [currentTrackId, telemetry]);
```

- [ ] **Step 2:** prefetch effect — destructure the stable members (TanStack Query's `fetchNextPage` is stable):

```ts
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = tracksQuery;
  useEffect(() => {
    if (hasNextPage && !isFetchingNextPage && queue.length < QUEUE_REFILL_THRESHOLD) {
      fetchNextPage();
    }
  }, [queue.length, hasNextPage, isFetchingNextPage, fetchNextPage]);
```

- [ ] **Step 3:** `theme.ts:277` — delete the unused `// eslint-disable-next-line @typescript-eslint/no-empty-interface`.
- [ ] **Step 4:** `package.json` `"lint": "eslint src --max-warnings=0"`.
- [ ] **Step 5:** `pnpm lint` → 0 problems; `pnpm typecheck`; `pnpm test` → 1188 passed (useCurateSession tests unmodified); lint test from Task 1 passes.
- [ ] **Step 6: Commit** (`refactor(curate): effects list the values they read`).

---

### Task 4: README sections from audit §12

**Files:** `README.md`

- [ ] **Step 1:** Under the GIF caption add the at-a-glance line:
`**At a glance:** ~98k canonical tracks, 3–5k new every week · 18 Lambda functions, 2 Step Functions workflows · 11 nightly data-quality SLOs · ~3,300 automated tests · every merge to \`main\` deploys to production.`
- [ ] **Step 2:** Measured-results row "Scheduled ingest …": result column → `Two styles a week behind caught up the next day (\`styles_behind\` 2 → 0); 45 style-weeks in the first three days, 0 failed, no manual step`.
- [ ] **Step 3:** After the key-decisions table add `### Where the data lives` with the S3 tree from audit §12.4 (raw zone with `_quarantine/run_id=<run>/`, covers, bronze events and catalog export, `lakehouse/`, `governance/deleted_users/`) and the one-line Aurora model.
- [ ] **Step 4:** After the AWS services table add the "**Deliberately not used:**" paragraph (§12.6).
- [ ] **Step 5:** After the Data pipeline list add the "**When something fails.**" paragraph (§12.7).
- [ ] **Step 6:** Before `## Running it locally` add `## Production readiness` with the six bullets from §12.8 — Delivery (8 required checks, OIDC, read-only plan role for PRs [true since #287], migrations first), Reliability, Observability, Data governance, Security, Cost guardrails — no claim about rehearsed restore or deploy rollback.
- [ ] **Step 7:** Repository layout: add the row `| \`CLAUDE.md\`, \`graphify-out/\`, \`docs/superpowers/\` | AI-agent context: working instructions, a generated code graph, and the specs and plans behind each change (see *How this was built*) |`.
- [ ] **Step 8:** "including 51 against a real PostgreSQL 16" → "including a suite against a real PostgreSQL 16".
- [ ] **Step 9:** Run the Task 1 command and `tests/unit/test_readme.py tests/unit/test_docs_links.py` → all pass. Read every new sentence against its link (Review Focus 5).
- [ ] **Step 10: Commit** (`docs(readme): readiness, data layout, measured ingest`).

---

### Task 5: PR, review, merge, deploy, verify

- [ ] Commit this plan; `graphify update .` + commit; push; PR via `caveman:caveman-commit`.
- [ ] Fresh whole-branch review (most capable model); one fix pass for Critical/Important.
- [ ] CI green; the PR's `terraform` plan does not list `aws_cloudfront_distribution.frontend`.
- [ ] Merge → Deploy green → site renders (headless check) → §0 board: phase 2 done.

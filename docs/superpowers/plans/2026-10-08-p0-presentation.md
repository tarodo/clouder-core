# P0 presentation (README, docs sync, hygiene) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make what CLOUDER already does visible and true on the first screen: an accurate README with measured numbers and screenshots, docs that match the code, no hardcoded AWS identifiers, a license, and a filled GitHub "About".

**Architecture:** Documentation and repository hygiene, each change pinned by a guard test so it cannot drift back: a scan for real AWS account ids in tracked files, a relative-link checker for live docs, an inventory check that every deployed Lambda appears in `docs/architecture.md`, a ban on removed components in live docs, and a README contract test. Screenshots come from the real React components rendered with sample data in the existing Playwright browser harness (the app sits behind a Spotify allow-list).

**Tech Stack:** Markdown, Mermaid, pytest, Vitest browser mode (Playwright/Chromium), `gh` CLI.

**Spec:** hiring audit `~/Desktop/HIRING_AUDIT.ru.md` — §0 (P0 list, 2026-10-08), §12 (README drafts), §13.1 (stale files). It lives outside the repo; rulings are provisional against it.

## Global Constraints

- No money figures anywhere in the repo (owner rule: «проверь чтобы не было цифр про деньги»).
- Texts for GitHub (README, About, docs) are in English.
- Numbers in the README are measured values with a date; nothing invented. Sources: statuses in audit §15.3, `docs/benchmarks/canonicalization.md`, `docs/data/*.md`, CloudWatch (2026-09-08 → 2026-10-08: 156,390 Lambda invocations, 25 errors = 0.016 %).
- Live docs = `README.md` and `docs/**/*.md` except `docs/superpowers/`, `docs/archive/`, `docs/adr/` (ADRs are historical records and stay as written).
- Removed components that must not appear in live docs: `search_handler`, `ai_search_results`, `ai-search-worker` / `ai_search_worker`, `AI_SEARCH_QUEUE_URL`, Perplexity (any case).
- No git history rewrite: the real account id stays in old commits (an account id is not a credential; rewriting a public history is destructive).
- Branch `docs/p0-presentation`, worktree `../clouder-core-p0`; `$VENV=<repo>/.venv/bin`; commits via caveman-commit rules (Conventional Commits, no AI attribution); `git restore graphify-out` before commits.

## Review Focus

1. A relative link in the README or a live doc that points to a renamed or deleted file → the link test fails (Task 2: `test_live_doc_links_resolve`).
2. A Lambda added later without a line in `docs/architecture.md` → the inventory test fails (Task 3: `test_every_deployed_lambda_is_in_the_architecture_doc`).
3. A maintenance script run without `AURORA_CLUSTER_ARN` / `AURORA_SECRET_ARN` → exits with a clear message instead of silently targeting a hardcoded prod cluster (Task 1: `test_scripts_require_aurora_env`).
4. A money figure or a retired claim ("AI-assisted screening", "internal use only") creeping back into the README → the README test fails (Task 7: `test_readme_has_no_money_or_retired_claims`).
5. Screenshot fixtures rendering empty or broken (missing provider, wrong data shape) → the screenshot run asserts each PNG exists and is larger than 20 KB, and each shot waits for a known text from its fixture (Task 5).

---

### Task 1: No hardcoded AWS identifiers

**Files:** Create `tests/unit/test_no_hardcoded_aws_ids.py`; Modify `scripts/backfill_instagram.py`, `scripts/enrichment_stats.py`, `experiments/enrichment_split/src/splitlab/config.py`, `frontend/README.md`, `docs/superpowers/plans/2026-07-15-enrichment-split-experiment.md`, `docs/superpowers/plans/2026-10-07-replayable-backfill.md`.

**Interfaces — Produces:** scripts read `AURORA_CLUSTER_ARN` / `AURORA_SECRET_ARN` (the names the Lambdas use) and exit with code 2 and a message naming the missing variable.

- [ ] Step 1 — failing tests:

```python
"""The public repo carries no real AWS account id; scripts take ARNs from the environment."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = {"000000000000", "111111111111", "123456789012"}
ACCOUNT = re.compile(r"(?:arn:aws:[a-z0-9-]+:[a-z0-9-]*:|tfstate-)(\d{12})")


def test_no_real_account_id_in_tracked_files() -> None:
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    hits = []
    for name in names:
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        hits += [f"{name}: {m.group(0)}" for m in ACCOUNT.finditer(text) if m.group(1) not in FAKE]
    assert hits == []


def test_scripts_require_aurora_env() -> None:
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src")}
    for script in ("scripts/enrichment_stats.py", "scripts/backfill_instagram.py"):
        run = subprocess.run([sys.executable, script], cwd=ROOT, env=env,
                             capture_output=True, text=True)
        assert run.returncode == 2, (script, run.stderr)
        assert "AURORA_CLUSTER_ARN" in run.stderr
```

  Run: `$VENV/pytest tests/unit/test_no_hardcoded_aws_ids.py -q` → both fail (hits in 6 files; scripts start with defaults).
- [ ] Step 2 — in both scripts replace the `DEFAULT_*_ARN` constants with a helper used where the defaults were read:

```python
def _require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set (see docs/ops/env-vars.md); refusing to guess a cluster")
    return value
```

  `sys.exit(str)` exits with code 1 — use `print(msg, file=sys.stderr); raise SystemExit(2)` to get code 2. Call `_require_env("AURORA_CLUSTER_ARN")` / `_require_env("AURORA_SECRET_ARN")` at the start of `main()` (before any argparse work that needs AWS, after `--help`). In `experiments/enrichment_split/.../config.py`, read the two values from the env inside the settings loader (no default constant). In `frontend/README.md` write `bucket=<tfstate-bucket>`; in the two plan docs replace the account id with `<account-id>` and the secret suffix with `<secret-suffix>`.
- [ ] Step 3 — run the test → pass; full suite `$VENV/pytest -q` → pass.
- [ ] Step 4 — commit `chore(security): drop hardcoded AWS account ids`.

### Task 2: Live doc links resolve

**Files:** Create `tests/unit/test_docs_links.py`; Modify every live doc with a broken relative link (found by the test).

- [ ] Step 1 — failing test (expected to fail if any link is broken; if it passes on the first run, confirm by breaking one link locally, then restore):

```python
"""Every relative link in the README and the live docs points to an existing file."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL = ("docs/superpowers/", "docs/archive/", "docs/adr/")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def live_docs() -> list[Path]:
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    return [p for p in docs if not str(p.relative_to(ROOT)).startswith(HISTORICAL)]


def test_live_doc_links_resolve() -> None:
    broken = []
    for doc in live_docs():
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert broken == []
```

- [ ] Step 2 — run; fix each reported link (point to the current file, or drop the link when the target was removed).
- [ ] Step 3 — run → pass; commit `test(docs): check relative links in live docs`.

### Task 3: Architecture doc matches what is deployed

**Files:** Modify `docs/architecture.md`; Create `tests/unit/test_docs_freshness.py`.

**Interfaces — Produces:** `tests/unit/test_docs_freshness.py` with `REMOVED` patterns and `live_docs()` reused by Task 4 (import from `test_docs_links`).

- [ ] Step 1 — failing tests:

```python
"""Live docs describe the system that is deployed, not the one that was removed."""

from __future__ import annotations

import re
from pathlib import Path

from tests.unit.test_docs_links import ROOT, live_docs

REMOVED = re.compile(r"search_handler|ai_search_results|ai[-_]search[-_]worker|AI_SEARCH_QUEUE_URL|perplexity",
                     re.IGNORECASE)


def deployed_handlers() -> set[str]:
    tf = "\n".join(p.read_text() for p in (ROOT / "infra").glob("*.tf"))
    return set(re.findall(r'handler\s*=\s*"(collector\.[a-z_]+)\.lambda_handler"', tf))


def test_every_deployed_lambda_is_in_the_architecture_doc() -> None:
    doc = (ROOT / "docs" / "architecture.md").read_text()
    missing = sorted(h for h in deployed_handlers() if f"`{h}`" not in doc)
    assert len(deployed_handlers()) >= 18 and missing == []


def test_live_docs_do_not_describe_removed_components() -> None:
    hits = []
    for doc in live_docs():
        for n, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if REMOVED.search(line):
                hits.append(f"{doc.relative_to(ROOT)}:{n}: {line.strip()[:80]}")
    assert hits == []
```

  If `tests.unit` is not importable as a package, use `from test_docs_links import ROOT, live_docs` (pytest puts the test dir on `sys.path`). Run → both fail.
- [ ] Step 2 — rewrite `docs/architecture.md`:
  - System overview Mermaid diagram with: SPA (S3 + CloudFront) → API Gateway (Lambda authorizer) → API Lambdas (collector-api, curation, auth, analytics-api, telemetry); ingest (collector-api + auto-ingest, EventBridge Scheduler) → S3 raw zone → SQS canonicalization + DLQ → canonicalization worker → Aurora (RDS Data API); enrichment workers (spotify-search, vendor-match, label/artist enricher, auto-enrich dispatch, comments-collect) with their vendors (Spotify, YouTube Music, YouTube Data API, Gemini, OpenAI, Tavily, DeepSeek); Step Functions backfill (backfill λ) and nightly transform (CodeBuild dbt → Iceberg silver/gold); nightly data-quality λ and catalog-export λ (EventBridge); telemetry → Firehose → S3 bronze → Glue/Athena; CloudWatch alarms → SNS email.
  - A "Lambda functions" table: AWS name, entry module in backticks (`collector.<module>`), trigger, one-line purpose — all 18 (list: analytics-api `collector.analytics_handler`, artist-enricher-worker `collector.artist_enrichment_handler`, auth-authorizer `collector.auth_authorizer`, auth-handler `collector.auth_handler`, auto-enrich-dispatch-worker `collector.auto_enrich_dispatch_handler`, auto-ingest `collector.auto_ingest_handler`, backfill `collector.backfill_handler`, canonicalization-worker `collector.worker_handler`, catalog-export `collector.catalog_export_handler`, collector-api `collector.handler`, comments-collect-worker `collector.comments_collect_handler`, curation `collector.curation_handler`, data-quality `collector.data_quality_handler`, db-migration `collector.migration_handler`, label-enricher-worker `collector.label_enrichment_handler`, spotify-search-worker `collector.spotify_handler`, telemetry `collector.telemetry_handler`, vendor-match-worker `collector.vendor_match_handler`).
  - Subsystems: replace the Perplexity sentence with "Label and artist enrichment runs multi-vendor LLM research (Gemini, OpenAI, Tavily + DeepSeek) on SQS workers — `docs/data/search-and-enrichment.md`, ADR-0016/0017"; add "Data quality and contracts" (ADR-0023, ADR-0026) and "Alerting" (27 CloudWatch alarms → SNS email) bullets.
- [ ] Step 3 — run `test_every_deployed_lambda_is_in_the_architecture_doc` → pass (the removed-components test stays red until Task 4); commit `docs(architecture): sync diagram and Lambda inventory`.

### Task 4: Remove the retired AI-search path from live docs

**Files:** Modify `docs/backend/handlers.md`, `docs/backend/providers.md`, `docs/backend/data-api.md`, `docs/backend/gotchas.md`, `docs/data/README.md`, `docs/data/canonicalization.md`, `docs/data/data-model.md`, `docs/data/search-and-enrichment.md`, `docs/ops/env-vars.md`, `docs/ops/deploy.md`, `docs/ops/runbook.md`, `src/collector/providers/registry.py` (docstring).

- [ ] Step 1 — `test_live_docs_do_not_describe_removed_components` (Task 3) is the failing test; run it and keep its output as the work list.
- [ ] Step 2 — edits (facts verified on 2026-10-08):
  - `handlers.md`: overview table lists all 18 Lambdas (same names/modules as Task 3) and drops "not exhaustive"; delete the "AI Search Worker" section; worker step 6 → "Enqueue a Spotify-search message for the run (best-effort)"; idempotency note → "duplicate Spotify-search messages are harmless (searches upsert)".
  - `providers.md`: `EnrichProvider` row → "Spotify (track identity)"; label/artist research runs outside the registry (`label_enrichment/`, `artist_enrichment/`, ADR-0016/0017); `VENDORS_ENABLED` example `"beatport,spotify,ytmusic"`; delete the Perplexity section.
  - `data-api.md`, `gotchas.md`: "Perplexity or Spotify API key" → "a vendor API key (Spotify, Gemini, OpenAI, …)".
  - `docs/data/README.md`: search-and-enrichment line → "Spotify ISRC + metadata fallback, YouTube Music matching, vendor-match cache, LLM label/artist research".
  - `canonicalization.md` "is_ai_suspected propagation": write path is `project_ai_suspected` in `label_enrichment/repository.py` and `artist_enrichment/repository.py`, mirroring the merged result's `ai_content` when `confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default 0.6; `suspected`/`confirmed` → true, `none_detected` → false, `unknown` → no change); the default prompts (`label_v4_no_ai`, `artist_v2_no_ai`) no longer ask about AI content, so the flag only changes when an AI-aware prompt version is chosen.
  - `data-model.md`: drop `ai_search_results` from the layer diagram (dropped in migration `20260518_21`); `is_ai_suspected` rows → "Set by label/artist enrichment (ADR-0008, ADR-0016/0017)".
  - `search-and-enrichment.md`: intro → "workers enrich canonical tracks with Spotify and YouTube Music data; labels and artists get multi-vendor LLM research"; delete the "Perplexity label and artist screening (superseded)" section; `ai_search_results.result` mention in "Result schema" → the enrichment result tables (`label_enrichment_runs` / `artist_enrichment_runs`, verify names in `alembic/versions` before writing).
  - `env-vars.md`: `VENDORS_ENABLED` table = beatport (ingest), spotify (ISRC lookup), ytmusic (metadata lookup + publish), deezer/apple/tidal (stubs); example `beatport,spotify,ytmusic`; delete the "AI search worker (superseded)" section.
  - `deploy.md`: step 2 lists the SSM parameters `deploy.yml` writes (`/clouder/{gemini,openai,tavily,deepseek}/api_key`, `/clouder/spotify/client_{id,secret}`, `/clouder/ytmusic/client_{id,secret}`, `/clouder/youtube/api_key`, `/clouder/beatport/{username,password}`); step 3 describes the two-phase apply (migration Lambda only → run migrations → full apply) and points to `deploy.yml` for the `-var` list instead of copying it; PR-checks table adds the `dbt` job and "Real-Postgres tests" in `alembic-check`; secrets table: drop `PERPLEXITY_API_KEY`, add `GEMINI_API_KEY`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `DEEPSEEK_API_KEY`, `YTMUSIC_CLIENT_ID`, `YTMUSIC_CLIENT_SECRET`, `YOUTUBE_API_KEY`.
  - `runbook.md` "Lambda reserved concurrency trip": table = spotify_search 3, vendor_match 2, label_enrichment 10, artist_enrichment 10, total 25 → quota target ≥ 35; "Perplexity/Spotify 429s" → "vendor 429s".
  - `registry.py` docstring example → `VENDORS_ENABLED="beatport,spotify,ytmusic"`.
- [ ] Step 3 — `$VENV/pytest tests/unit/test_docs_freshness.py tests/unit/test_docs_links.py -q` → pass; full suite → pass; commit `docs: drop the retired AI-search path`.

### Task 5: README screenshots from the real UI

**Files:** Create `frontend/vitest.screenshots.config.ts`, `frontend/src/screenshots/readme.shot.tsx`, `docs/assets/{curate,triage,coverage,analytics}.png`; Modify `frontend/package.json` (script `screenshots`).

**Interfaces — Produces:** `pnpm screenshots` (from `frontend/`) regenerates the four PNGs; Task 7 embeds them.

- [ ] Step 1 — `vitest.screenshots.config.ts`: copy of `vitest.browser.config.ts` with `include: ['src/screenshots/**/*.shot.tsx']` and the same `setupFiles`; `package.json`: `"screenshots": "vitest run --config vitest.screenshots.config.ts"`.
- [ ] Step 2 — `readme.shot.tsx`: one test per view, viewport 1440×900, the app theme (`clouderTheme` from `src/theme.ts` with `defaultColorScheme="light"`), i18n, `QueryClient` seeded with fixtures, a fixed-width wrapper, then `page.screenshot({ element, path })` into `docs/assets/`. Views and fixtures (fictional artists/labels, real genre names):
  - `curate.png` — `CurateCard` (title "Night Drive", mix "Extended Mix", artists "Mara Quill, Odessa Lane", label "Lowtide Records", BPM 124, key 8A, 6:12) above `DestinationGrid` with 6 buckets (Warm-up 12, Peak time 8, Closing 5, Vocals 9, Old 31, Discard 44), `currentBucketId` = NEW bucket, `forceMode` false.
  - `triage.png` — `BucketGrid` in a `MemoryRouter` with NEW 312, OLD 97, NOT 41, UNCLASSIFIED 18, FAV 6, DISCARD 120 and 4 category buckets.
  - `coverage.png` — `CoverageMatrix` with 6 styles × 52 weeks (completed for weeks 1–39 with item counts 180–1,500, two `failed` cells, week 40+ empty) above `AutoIngestPanel` seeded via `AUTO_INGEST_KEY` (random mode, 3 runs/day, 3 planned runs, last run with 3 ok pairs).
  - `analytics.png` — `ListeningCard`, `FunnelCard`, `TimePerTrackCard` seeded under their exact query keys (`['analytics','listening', qs]`, `['analytics','funnel', qs]`, `['analytics','time-per-track', `${qs}&days=30`]` with `qs = tz_offset_min=${tzOffsetMin()}`), 30 days of listening, funnel stages triaged/categorized/playlisted, 3 style rows.
  Each test waits for a fixture text (`await screen.findByText(...)`) before the screenshot and then asserts `statSync(path).size > 20_000`.
- [ ] Step 3 — `cd frontend && pnpm screenshots` → 4 tests pass; open each PNG and check it renders as intended (no overflow, no empty state, no missing font); `pnpm typecheck && pnpm lint && pnpm test` → pass (the `.shot.tsx` files are outside the jsdom and browser-test globs).
- [ ] Step 4 — commit `docs(assets): README screenshots from the real UI`.

### Task 6: License

**Files:** Create `LICENSE`.

- [ ] Step 1 — `LICENSE` text: "Copyright (c) 2026 Roman (github.com/tarodo). All rights reserved." + a paragraph that the source is published for reading and evaluation only (e.g. job applications, technical review) and that no license is granted to use, copy, modify, distribute, sublicense, sell or run it as a service without written permission + the standard "AS IS" warranty disclaimer. Ruling: source-available rather than MIT — a permissive grant on published versions cannot be taken back, a restrictive one can be relaxed later.
- [ ] Step 2 — commit `docs(license): source-available, all rights reserved` (the link test of Task 2 covers the README's link to it after Task 7).

### Task 7: README

**Files:** Modify `README.md`; Create `tests/unit/test_readme.py`.

- [ ] Step 1 — failing test:

```python
"""README: no money, no retired claims, the sections a reviewer looks for."""

from __future__ import annotations

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")


def test_readme_has_no_money_or_retired_claims() -> None:
    assert not re.search(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|per month|/month", README)
    for retired in ("AI-assisted screening", "internal use only", "Weekly automated ingest"):
        assert retired not in README


def test_readme_has_the_reviewer_sections() -> None:
    for heading in ("## Architecture", "## Measured results", "## What this project demonstrates",
                    "## AWS services", "## Data pipeline", "## Screenshots", "## Running it locally",
                    "## Known limitations", "## How this was built", "## License"):
        assert heading in README, heading
    assert "```mermaid" in README and "docs/assets/" in README
```

  Run → fail.
- [ ] Step 2 — write the README (English). Order and content:
  1. Title, one-line pitch ("A serverless data pipeline on AWS and the DJ curation app built on it"), Deploy badge (`.github/workflows/deploy.yml`), 4-sentence problem statement (audit §12.3 text without the status note about video).
  2. **Measured results** table (before → after, link per row): set-based canonicalization (2,805 → 55 Data API calls for an average week; 16–24× faster per track in prod; `docs/benchmarks/canonicalization.md`, ADR-0022), replayable backfill (153 runs / 100,268 tracks replayed in 7 min 56 s; re-run = 0 changes; `docs/ops/backfill.md`, ADR-0024), Iceberg + dbt lakehouse (1,243 → 38 files; aggregate 6.1–7.0 s → 0.77 s; SCD2 history; `docs/data/lakehouse.md`, ADR-0025, lineage `https://tarodo.github.io/clouder-core/`), data contract (silent drop → quarantine with reasons; a drift alarm that would have fired on 2026-09-13; `docs/data/contracts.md`, ADR-0026), data quality (11 nightly checks with SLOs; first run caught two lagging styles; `docs/data/data-quality.md`, ADR-0023), entity resolution (precision of automatic YouTube Music matches 100 % on a 100-match labelled sample, error < ~3 % at 95 % confidence; `docs/data/entity-resolution.md`), scheduled ingest (manual with a pasted token → EventBridge Scheduler, login per run, due week first then even backfill; `docs/data/auto-ingest.md`, ADR-0027).
  3. **Architecture**: a Mermaid diagram (same content as `docs/architecture.md`, condensed) + a key-decisions table (ADR-0001 Data API, 0002 overlay, 0004 providers, 0014 auto-pause Aurora — no money, 0022–0027) linking `docs/adr/`.
  4. **What this project demonstrates**: data engineering / cloud / software engineering bullets (audit §12.5 updated: 18 Lambdas, 7 SQS queues with DLQs, 2 Step Functions state machines, ~3,300 automated tests incl. 51 real-Postgres tests and dbt unit/data tests, 27 ADRs).
  5. **AWS services**: table (audit §12.6 + Step Functions, EventBridge Scheduler, CodeBuild, SNS; counts updated).
  6. **Data pipeline**: numbered flow (audit §12.7) with step 1 = scheduled ingest (auto-ingest) or an admin-triggered one, plus contract screening, replay/backfill, nightly DQ and dbt build.
  7. **Screenshots**: the four images with a caption "Rendered from the app's React components with sample data (`pnpm screenshots`); the live app is behind a Spotify allow-list."
  8. **By the numbers** (no money): ~100k canonical tracks (2026-10-07 replay), 107,795 raw records, Spotify match 96.85 %, 156k Lambda invocations / 30 days at 0.016 % errors, 228 Terraform resources, 104 API operations, 265+ merged PRs, deploy on every merge.
  9. **Running it locally**: backend tests (`python -m pip install -r requirements-dev.txt`, `pytest -q`), real-Postgres tests (`docker run -d -p 55433:5432 -e POSTGRES_PASSWORD=postgres postgres:16`, `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres pytest tests/db -q`), frontend (`cd frontend && pnpm install && pnpm test`), dbt on DuckDB (`cd dbt && pip install -r requirements.txt && DBT_PROFILES_DIR=. dbt build --target ci`), deploy is GitHub Actions only.
  10. **Repository layout**: `src/collector`, `frontend`, `infra`, `dbt`, `alembic`, `tests`, `docs`, `experiments`.
  11. **Known limitations & next steps**: one production environment; 11 of 18 Lambdas share an IAM role (next: per-function roles); no API Gateway throttling/access logs yet; Aurora deletion protection off; precision measured for YouTube Music only (Spotify next); built for a small closed group (~100k tracks, +3–5k a week).
  12. **How this was built**: audit §12.9 text, pointing to `docs/superpowers/` for specs and plans.
  13. **License**: "Source-available, all rights reserved — see [LICENSE](LICENSE)."
- [ ] Step 3 — `$VENV/pytest tests/unit/test_readme.py tests/unit/test_docs_links.py -q` → pass; full suite → pass; commit `docs(readme): measured results, architecture, screenshots`.

## After merge

1. Deploy runs (docs-only changes; nothing changes in AWS).
2. GitHub About:
   `gh repo edit tarodo/clouder-core --description "Serverless AWS data pipeline + React app for DJ track curation: scheduled Beatport ingest, S3 raw zone, canonical catalog in Aurora with entity resolution, data contracts and nightly DQ checks, Iceberg lakehouse built by dbt on Athena. Terraform, Step Functions, GitHub Actions OIDC." --homepage "https://tarodo.github.io/clouder-core/"` and topics `aws serverless aws-lambda data-engineering data-pipeline terraform aws-step-functions amazon-s3 amazon-sqs aurora-serverless amazon-athena apache-iceberg dbt data-quality entity-resolution kinesis-firehose python react typescript github-actions` (≤ 20). Verify with `gh repo view --json description,homepageUrl,repositoryTopics`.
3. Graph refresh (`graphify update .`), worktree cleanup, audit §0 status.

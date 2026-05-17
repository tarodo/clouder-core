# Documentation Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reshape repository documentation: replace single-purpose `README.md` with a user-block + developer-entry layout, reorganise `docs/` by reader role, distil fifteen ADRs, slim `CLAUDE.md` to ~6-8k, delete old plans, archive old specs. All target docs in English.

**Architecture:** Ten phases (`P0..P10`). Phase 0 only moves and renames files (no content rewrite). Phase 1 creates the skeleton. Phases 2–8 author content in parallel-safe slots. Phase 9 (CLAUDE.md slim) and Phase 10 (verify + cleanup) run last. Each phase = one PR.

**Tech Stack:** Markdown only. No code changes outside CI workflow paths, `frontend/package.json`, and `scripts/generate_openapi.py` (all path updates).

**Spec:** `docs/superpowers/specs/2026-05-17-documentation-overhaul-design.md`.

---

## Conventions

- **Commits:** every commit goes through the `caveman:caveman-commit` skill. Multi-line bodies use heredoc form (`git commit -m "$(cat <<'EOF' ... EOF)"`). Verify with `git log -1 --pretty=%B` after each commit.
- **Branch:** create one branch per phase: `docs/p0-move-cleanup`, `docs/p1-skeleton`, ..., `docs/p10-verify-cleanup`. No `tarodo/` or `claude/` prefix.
- **Language:** every new or rewritten file under `docs/` is **English**. `docs/design_handoff/` and `docs/archive/` keep whatever language they already have.
- **No fluff:** terse, technical, full identifier names. No emojis.
- **Self-plan-deletion:** this plan file (`docs/superpowers/plans/2026-05-17-documentation-overhaul.md`) is preserved through P0 and deleted at the end of P10. P0 deletes every OTHER file in `plans/`.

---

## File Structure (final state)

```
README.md                       # User pitch + developer pointers (rewritten P2)
CLAUDE.md                       # Slim ~6-8k orientation (rewritten P9)
docs/
├── architecture.md             # P1
├── backend/                    # P3
│   ├── README.md
│   ├── handlers.md
│   ├── providers.md
│   ├── data-api.md
│   ├── testing.md
│   └── gotchas.md
├── data/                       # P4
│   ├── README.md
│   ├── data-model.md
│   ├── migrations.md
│   ├── raw-ingestion.md
│   ├── canonicalization.md
│   └── search-and-enrichment.md
├── frontend/                   # P5
│   ├── README.md
│   ├── features.md
│   ├── playback.md
│   ├── auth.md
│   ├── testing.md
│   └── gotchas.md
├── ops/                        # P6
│   ├── README.md
│   ├── deploy.md
│   ├── env-vars.md
│   ├── logs.md
│   ├── aurora.md
│   └── runbook.md
├── api/                        # P7 (openapi.yaml moved here in P0)
│   ├── README.md
│   ├── openapi.yaml
│   └── auth-flow.md
├── adr/                        # P8
│   ├── README.md
│   └── 0001..0015-*.md         # fifteen ADRs
├── archive/                    # P0
│   ├── legacy/                 # docs/data-model.md, docs/frontend.md, docs/spotify-search.md
│   └── specs/                  # docs/superpowers/specs/* + loose 2026-05-13 design
└── design_handoff/             # unchanged
```

---

## Phase 0 — Move + cleanup

**Goal:** mechanical moves only. No content rewrite. Branch: `docs/p0-move-cleanup`.

### Task 0.1: Create branch + target folders

- [ ] **Step 1: Create branch**

```bash
git switch -c docs/p0-move-cleanup
```

- [ ] **Step 2: Create target folders**

```bash
mkdir -p docs/backend docs/data docs/frontend docs/ops docs/api docs/adr \
         docs/archive/legacy docs/archive/specs
```

- [ ] **Step 3: Verify**

```bash
ls -d docs/{backend,data,frontend,ops,api,adr,archive,archive/legacy,archive/specs}
```

Expected: all nine paths listed.

- [ ] **Step 4: Commit (folder creation is a tracked change via .gitkeep)**

Place a `.gitkeep` in each empty folder so git tracks them, then commit.

```bash
touch docs/backend/.gitkeep docs/data/.gitkeep docs/frontend/.gitkeep \
      docs/ops/.gitkeep docs/api/.gitkeep docs/adr/.gitkeep \
      docs/archive/legacy/.gitkeep docs/archive/specs/.gitkeep
git add docs/backend docs/data docs/frontend docs/ops docs/api docs/adr docs/archive
```

Then invoke `caveman:caveman-commit` skill with: *"Adds eight empty target folders for the audience-first docs/ tree. .gitkeep placeholders only."* and commit using its output via heredoc.

### Task 0.2: Move legacy live docs to archive

- [ ] **Step 1: Move three legacy files**

```bash
git mv docs/data-model.md      docs/archive/legacy/data-model.md
git mv docs/frontend.md        docs/archive/legacy/frontend.md
git mv docs/spotify-search.md  docs/archive/legacy/spotify-search.md
```

- [ ] **Step 2: Move the loose stray design file**

```bash
git mv docs/2026-05-13-category-player-frontend-design.md \
       docs/archive/specs/2026-05-13-category-player-frontend-design.md
```

- [ ] **Step 3: Verify**

```bash
ls docs/archive/legacy/   # should list 3 *.md files
ls docs/ | head -20       # no more data-model.md, frontend.md, spotify-search.md, 2026-05-13-*.md
```

- [ ] **Step 4: Commit** via `caveman:caveman-commit` skill: *"Archives the three pre-rewrite live docs and the loose 2026-05-13 design file under docs/archive/."*

### Task 0.3: Move `docs/openapi.yaml` to `docs/api/openapi.yaml`

- [ ] **Step 1: Move file**

```bash
git mv docs/openapi.yaml docs/api/openapi.yaml
```

- [ ] **Step 2: Update `scripts/generate_openapi.py` output path**

File: `scripts/generate_openapi.py`. Change line 2036:

Replace:

```python
    out = Path(__file__).resolve().parents[1] / "docs" / "openapi.yaml"
```

With:

```python
    out = Path(__file__).resolve().parents[1] / "docs" / "api" / "openapi.yaml"
```

Also update the docstring at lines 2 and 14:

```python
"""Generate docs/api/openapi.yaml from pydantic schemas + a manual route table.
```

```python
Output: docs/api/openapi.yaml (OpenAPI 3.1).
```

- [ ] **Step 3: Update `frontend/package.json` codegen command**

File: `frontend/package.json:21`.

Replace:

```json
    "api:types": "openapi-typescript ../docs/openapi.yaml -o src/api/schema.d.ts"
```

With:

```json
    "api:types": "openapi-typescript ../docs/api/openapi.yaml -o src/api/schema.d.ts"
```

- [ ] **Step 4: Update `frontend/README.md`**

File: `frontend/README.md`. Replace every `docs/openapi.yaml` with `docs/api/openapi.yaml` (specifically lines 17 and 51).

- [ ] **Step 5: Update CI workflow**

File: `.github/workflows/pr.yml`. Replace every `docs/openapi.yaml` with `docs/api/openapi.yaml` (lines 27 and 173).

- [ ] **Step 6: Verify nothing else references the old path**

```bash
grep -rn "docs/openapi\.yaml" \
  --include="*.py" --include="*.ts" --include="*.tsx" --include="*.yml" --include="*.yaml" \
  --include="*.tf" --include="*.json" --include="*.md" --include="*.sh" \
  . 2>/dev/null | grep -v "docs/archive/" | grep -v "docs/superpowers/"
```

Expected: empty (references under `docs/archive/` and `docs/superpowers/` are historical and untouched).

- [ ] **Step 7: Regenerate OpenAPI + frontend types to confirm wiring works**

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```

Expected: `wrote ... docs/api/openapi.yaml (...)`.

```bash
cd frontend && pnpm api:types
```

Expected: writes `src/api/schema.d.ts`, no diff against current schema (paths changed, content same).

- [ ] **Step 8: Commit** via `caveman:caveman-commit` skill: *"Moves docs/openapi.yaml to docs/api/openapi.yaml and updates the generator script, frontend codegen command, frontend README, and the PR workflow path filter."*

### Task 0.4: Move `docs/superpowers/specs/*` → `docs/archive/specs/`

- [ ] **Step 1: Move all spec files**

```bash
git mv docs/superpowers/specs/*.md docs/archive/specs/
```

- [ ] **Step 2: Verify specs folder is empty**

```bash
ls docs/superpowers/specs/    # should be empty or only .gitkeep
```

- [ ] **Step 3: Remove the now-empty specs folder**

```bash
rmdir docs/superpowers/specs
```

- [ ] **Step 4: Verify the design spec for THIS overhaul is also moved**

`docs/superpowers/specs/2026-05-17-documentation-overhaul-design.md` should now live at `docs/archive/specs/2026-05-17-documentation-overhaul-design.md`. This is fine — it is historical from the moment the plan exists.

- [ ] **Step 5: Commit** via `caveman:caveman-commit`: *"Moves docs/superpowers/specs/* into docs/archive/specs/. Removes the now-empty specs folder."*

### Task 0.5: Delete `docs/superpowers/plans/*` (except this plan)

- [ ] **Step 1: List plans to delete**

```bash
ls docs/superpowers/plans/ | grep -v '^2026-05-17-documentation-overhaul\.md$'
```

- [ ] **Step 2: Delete every plan except this one**

```bash
find docs/superpowers/plans -type f -name '*.md' \
  ! -name '2026-05-17-documentation-overhaul.md' \
  -delete
```

- [ ] **Step 3: Verify only this plan remains**

```bash
ls docs/superpowers/plans/
```

Expected: only `2026-05-17-documentation-overhaul.md`.

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Deletes historical implementation plans. Git history retains them. Keeps the in-flight documentation-overhaul plan until phase 10."*

### Task 0.6: Update top-level `README.md` and `CLAUDE.md` links to legacy paths

These are stop-gap link updates — the real rewrites happen in P2 and P9. Until then we keep cross-links pointing at the right place.

- [ ] **Step 1: Update `README.md:9-12`**

Replace:

```markdown
- [Frontend integration guide](docs/frontend.md) — auth flow, user flows, quirks for frontend devs
- [OpenAPI spec](docs/openapi.yaml) — import into Postman / Swagger UI / Insomnia
- [Data model](docs/data-model.md) — canonical entities + triage tables
- [Spotify search](docs/spotify-search.md) — vendor match details
```

With:

```markdown
- [Frontend integration guide](docs/archive/legacy/frontend.md) — auth flow, user flows, quirks for frontend devs (legacy; full rewrite pending)
- [OpenAPI spec](docs/api/openapi.yaml) — import into Postman / Swagger UI / Insomnia
- [Data model](docs/archive/legacy/data-model.md) — canonical entities + triage tables (legacy; full rewrite pending)
- [Spotify search](docs/archive/legacy/spotify-search.md) — vendor match details (legacy; full rewrite pending)
```

- [ ] **Step 2: Update `CLAUDE.md` references**

File: `CLAUDE.md`. Patch the three references identified in `grep` output:

Line 24: `# Regenerate docs/openapi.yaml after editing scripts/generate_openapi.py:ROUTES` → `# Regenerate docs/api/openapi.yaml after editing scripts/generate_openapi.py:ROUTES`

Line 83: `... \`docs/openapi.yaml\` (used as Postman import) ...` → `... \`docs/api/openapi.yaml\` (used as Postman import) ...`

Line 85: `... diff-checked against \`docs/openapi.yaml\` ...` → `... diff-checked against \`docs/api/openapi.yaml\` ...`

- [ ] **Step 3: Verify**

```bash
grep -n "docs/openapi\.yaml\|docs/data-model\|docs/frontend\.md\|docs/spotify-search" README.md CLAUDE.md
```

Expected: empty.

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Patches README.md and CLAUDE.md links to point at moved doc paths."*

### Task 0.7: Open PR

- [ ] **Step 1: Push branch + open PR**

PR body and title generated by `caveman:caveman-commit` skill. Title prefix `docs(p0):`.

- [ ] **Step 2: Verify CI passes**

`alembic-check`, `terraform`, `tests`, frontend OpenAPI diff check — all should pass.

- [ ] **Step 3: Merge**

Squash or merge-commit per project convention.

---

## Phase 1 — Skeleton: architecture.md + role-folder TOCs

**Goal:** create `docs/architecture.md` and one `README.md` per role folder as a TOC stub. Branch: `docs/p1-skeleton`.

### Task 1.1: Author `docs/architecture.md`

**Files:**
- Create: `docs/architecture.md`
- Delete: `docs/backend/.gitkeep`, `docs/data/.gitkeep`, `docs/frontend/.gitkeep`, `docs/ops/.gitkeep`, `docs/api/.gitkeep`, `docs/adr/.gitkeep` (only after their `README.md` is in place — see 1.2)

- [ ] **Step 1: Write the file**

Content:

```markdown
# CLOUDER Architecture

CLOUDER is a multi-tenant SaaS for DJs. A shared canonical music catalogue is fed by a serverless ingest pipeline; per-user overlays (playlists, tags, curation state) sit on top. The user-facing surface is a React SPA that talks to a single API Gateway endpoint.

## System overview

```mermaid
flowchart LR
    subgraph SPA["React SPA (Vite + Mantine 9)"]
        UI[UI: triage, curate, categories, player]
    end

    subgraph API["AWS HTTP API Gateway"]
        APIGW[API Gateway routes]
    end

    subgraph Lambdas["AWS Lambdas"]
        AH[auth-handler]
        CH[collector-api]
        SH[ai-search-worker]
        SPW[spotify-search-worker]
        VMW[vendor-match-worker]
        WH[canonicalization-worker]
        MH[migration]
    end

    subgraph Storage
        S3[(S3 raw/bp/releases/*)]
        SQS[(SQS canonicalization queue + DLQ)]
        Aurora[(Aurora PostgreSQL Serverless v2)]
    end

    subgraph Vendors
        BP[[Beatport API]]
        SP[[Spotify Web API + Web Playback SDK]]
        PX[[Perplexity API]]
    end

    UI <--> APIGW
    APIGW --> AH
    APIGW --> CH
    AH <--> Aurora
    AH <--> SP
    CH --> BP
    CH --> S3
    CH --> SQS
    SQS --> WH
    WH --> S3
    WH --> Aurora
    SH <--> PX
    SH <--> Aurora
    SPW <--> SP
    SPW <--> Aurora
    VMW <--> SP
    VMW <--> Aurora
    MH --> Aurora
    UI <--> SP
```

## Subsystems

- **Ingest (P0–P3 of the original collector).** API Lambda fetches a Beatport weekly snapshot, writes `releases.json.gz + meta.json` to S3, enqueues a canonicalization job, and records an `ingest_runs` row. See `docs/data/raw-ingestion.md`.
- **Canonicalization.** SQS-triggered worker reads the raw snapshot, normalises tracks / artists / albums / labels, and upserts canonical entities into Aurora via the RDS Data API. See `docs/data/canonicalization.md`.
- **Search and enrichment.** Per-track ISRC lookup against Spotify, plus a metadata-fallback path for misses. Perplexity is used to flag AI-suspected labels and artists. Results are cached in vendor-match tables. See `docs/data/search-and-enrichment.md`.
- **Curation.** The SPA's tap-to-assign UX assigns tracks from triage buckets into per-user playlists. Optimistic shrink keeps the cursor stable. See `docs/frontend/features.md` and ADR-0010, ADR-0012.
- **Playback.** Spotify Web Playback SDK is lazy-loaded on the first play. The CLOUDER auth refresh stream bundles a Spotify access token; the SPA keeps it in memory only. See `docs/frontend/playback.md` and ADR-0011, ADR-0013.
- **Operations.** Aurora Serverless v2 with `min_acu=0` (auto-pause). Migrations run via a dedicated Lambda. See `docs/ops/aurora.md` and `docs/ops/deploy.md`.

## Where to read next

- New backend contributor → `docs/backend/README.md`.
- New data engineer → `docs/data/README.md`.
- New frontend contributor → `docs/frontend/README.md`.
- Ops / on-call → `docs/ops/runbook.md`.
- Why-this-way questions → `docs/adr/README.md`.
```

- [ ] **Step 2: Verify diagram renders**

```bash
grep -c "```mermaid" docs/architecture.md
```

Expected: `1`.

GitHub will render this on push; no local mermaid CLI required.

- [ ] **Step 3: Commit** via `caveman:caveman-commit`: *"Adds docs/architecture.md as the single source of truth for the system overview, with one mermaid diagram covering the ingest pipeline, search workers, Aurora, vendor APIs, and the SPA."*

### Task 1.2: Author one TOC `README.md` per role folder

For each role folder (`backend`, `data`, `frontend`, `ops`, `api`, `adr`) create a `README.md` that lists the planned files. This anchors the folder before P3..P8 fill them in.

- [ ] **Step 1: Write `docs/backend/README.md`**

```markdown
# Backend

Lambda runtimes, vendor integrations, and the data-access layer.

- [Handlers](handlers.md) — entry points: API, worker, search, spotify, vendor_match, migration.
- [Vendor providers](providers.md) — Protocol pattern, `VENDORS_ENABLED`, adding a vendor.
- [RDS Data API](data-api.md) — `DataAPIClient`, retry policy, transactions, `find_identity`.
- [Testing](testing.md) — pytest setup, `FakeDataAPI`, what it misses.
- [Gotchas](gotchas.md) — backend-only sharp edges.

See also `docs/architecture.md`, `docs/adr/`.
```

- [ ] **Step 2: Write `docs/data/README.md`**

```markdown
# Data

Canonical schema, raw ingestion, transforms, search and enrichment.

- [Data model](data-model.md) — canonical entities, triage tables, identity map.
- [Migrations](migrations.md) — alembic, packaging rename, migration Lambda.
- [Raw ingestion](raw-ingestion.md) — Beatport API → S3 layout, `ingest_runs` state machine, Saturday-week.
- [Canonicalization](canonicalization.md) — normalize → canonical, identity map, propagation rules.
- [Search and enrichment](search-and-enrichment.md) — Spotify ISRC + metadata fallback, Perplexity label search, vendor-match cache, AI flag.

See also `docs/architecture.md`, `docs/adr/`.
```

- [ ] **Step 3: Write `docs/frontend/README.md`**

```markdown
# Frontend

React 19 + Mantine 9 SPA. This folder documents architecture and conventions; for local setup see `frontend/README.md`.

- [Features](features.md) — feature-folder convention, routing, auth and admin guards.
- [Playback](playback.md) — Spotify Web Playback SDK integration, hotkeys, Curate vs Category players.
- [Auth](auth.md) — auth provider, token store, refresh-cookie semantics, Spotify token bundling.
- [Testing](testing.md) — vitest + jsdom shims, MSW, MantineProvider in tests.
- [Gotchas](gotchas.md) — frontend-only sharp edges.

See also `docs/architecture.md`, `docs/adr/`.
```

- [ ] **Step 4: Write `docs/ops/README.md`**

```markdown
# Operations

Deployment, runtime configuration, observability, and incident response.

- [Deploy](deploy.md) — CI/CD workflows, terraform apply order, migration Lambda invocation.
- [Environment variables](env-vars.md) — full runtime env table per Lambda.
- [Logs](logs.md) — structlog events, `aws logs tail`, enabling Aurora PostgreSQL logs.
- [Aurora](aurora.md) — Serverless v2 scaling, auto-pause, IAM auth quirks.
- [Runbook](runbook.md) — common incidents and their fixes.

See also `docs/architecture.md`, `docs/adr/`.
```

- [ ] **Step 5: Write `docs/api/README.md`**

```markdown
# API

HTTP contract for the CLOUDER API.

- [openapi.yaml](openapi.yaml) — OpenAPI 3.1 spec. Import into Postman / Swagger UI / Insomnia.
- [Auth flow](auth-flow.md) — Spotify OAuth redirect, refresh-token rotation, replay detection.

Regenerate `openapi.yaml` with `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` after editing `scripts/generate_openapi.py:ROUTES`. Run `pnpm api:types` in `frontend/` to refresh the generated TypeScript types.
```

- [ ] **Step 6: Write `docs/adr/README.md`**

```markdown
# Architecture Decision Records

ADRs capture the *why* behind load-bearing architectural choices in CLOUDER. They are short (≤ 2 pages), append-only, and stable: once accepted, an ADR is not edited — a new ADR supersedes it.

## Status flow

`Proposed` → `Accepted` → `Superseded by ADR-NNNN` (or `Deprecated`).

## Numbering

Four-digit, monotonic, never reused. The next free number is `0016`.

## Template

```markdown
# ADR-NNNN: <Short title>
Status: Accepted
Date: YYYY-MM-DD

## Context
What problem, what forces, what alternatives were considered.

## Decision
What we chose.

## Consequences
Trade-offs accepted. What becomes harder. Cross-references to topical docs.
```

## Index

| #    | Title                                                                                   |
|------|-----------------------------------------------------------------------------------------|
| 0001 | [RDS Data API at Lambda runtime (vs psycopg)](0001-data-api-runtime.md)                 |
| 0002 | [Multi-tenant overlay model](0002-multi-tenant-overlay.md)                              |
| 0003 | [Saturday-week as canonical period](0003-saturday-week.md)                              |
| 0004 | [Provider abstraction with `VENDORS_ENABLED` gate](0004-provider-abstraction.md)        |
| 0005 | [RDS IAM auth for migration Lambda](0005-iam-auth-migration.md)                         |
| 0006 | [Spotify metadata fallback with strict / relaxed tiers](0006-spotify-metadata-fallback.md) |
| 0007 | [`release_type` derived from Spotify, propagated to canonical](0007-release-type-propagation.md) |
| 0008 | [`is_ai_suspected` soft propagated flag](0008-ai-suspected-flag.md)                     |
| 0009 | [Frontend stack — React 19 + Mantine 9](0009-frontend-stack.md)                         |
| 0010 | [Tap-to-assign curation UX](0010-tap-to-assign.md)                                      |
| 0011 | [Spotify token bundled with CLOUDER auth refresh](0011-spotify-token-bundling.md)       |
| 0012 | [Optimistic shrink, reducer ADVANCE no-op](0012-optimistic-shrink.md)                   |
| 0013 | [PlaybackProvider in authenticated layout, SDK lazy-loaded](0013-playback-lazy-load.md) |
| 0014 | [Aurora Serverless v2 `min_acu=0`](0014-aurora-min-acu-zero.md)                         |
| 0015 | [Refresh-cookie replay = revoke all sessions](0015-refresh-cookie-replay.md)            |
```

- [ ] **Step 7: Remove .gitkeep placeholders now that real README.md files exist**

```bash
rm docs/backend/.gitkeep docs/data/.gitkeep docs/frontend/.gitkeep \
   docs/ops/.gitkeep docs/api/.gitkeep docs/adr/.gitkeep
```

- [ ] **Step 8: Commit** via `caveman:caveman-commit`: *"Adds TOC README.md files for the six new role folders. Removes their .gitkeep placeholders."*

### Task 1.3: Open PR

- [ ] PR title `docs(p1): scaffold architecture overview and role-folder TOCs`. Body via `caveman:caveman-commit`. Wait for green CI, merge.

---

## Phase 2 — Root `README.md` rewrite

**Goal:** rewrite `README.md` with a user block and a developer-entry block. Single file change. Branch: `docs/p2-readme`.

### Task 2.1: Rewrite `README.md`

**Files:**
- Modify: `README.md` (full replacement of body content)

- [ ] **Step 1: Replace the file contents**

```markdown
# CLOUDER

> A weekly track-curation tool for a small circle of DJs.

CLOUDER pulls fresh weekly releases from Beatport into your personal canonical library, lets you triage them with one keystroke, and ships the keepers straight into Spotify-ready playlists you can play in the browser.

**Who it's for.** DJs who buy or audition new releases every week and need a fast, repeatable workflow from "what came out this week" to "what's going into the set."

## Features

- **Weekly automated ingest** from Beatport into a personal canonical catalogue.
- **Tap-to-curate workflow** — one key per destination playlist, optimistic shrinks the queue.
- **In-browser playback** via the Spotify Web Playback SDK, keyboard-first hotkeys.
- **AI-assisted screening** — labels and artists are checked for AI-generated content and flagged.
- **Per-DJ playlists and tags** layered on a shared canonical catalogue.

---

## For developers

CLOUDER is a serverless ingest pipeline (Lambda + S3 + SQS + Aurora PostgreSQL) plus a React 19 SPA. The backend is Python; the frontend is Mantine 9 + react-router 7. Infrastructure is Terraform.

**Start here:**

- **System overview** — [`docs/architecture.md`](docs/architecture.md)
- **Architecture decisions** — [`docs/adr/`](docs/adr/)

**By role:**

- Backend / API / worker dev — [`docs/backend/`](docs/backend/)
- Data engineer — [`docs/data/`](docs/data/)
- Frontend dev — [`docs/frontend/`](docs/frontend/)
- Ops / SRE — [`docs/ops/`](docs/ops/)
- API consumer — [`docs/api/`](docs/api/)

**Local quickstart:**

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

For the SPA: see [`frontend/README.md`](frontend/README.md).
For deployment: see [`docs/ops/deploy.md`](docs/ops/deploy.md).

## License

Private — internal use only.
```

- [ ] **Step 2: Verify all links resolve**

```bash
for link in docs/architecture.md docs/adr/ docs/backend/ docs/data/ docs/frontend/ docs/ops/ docs/api/ frontend/README.md; do
  test -e "$link" && echo "OK: $link" || echo "MISSING: $link"
done
```

Expected: all `OK`.

`docs/ops/deploy.md` does not exist yet (P6 creates it) — that broken link is acceptable until P6 ships and is acknowledged here.

- [ ] **Step 3: Commit** via `caveman:caveman-commit`: *"Rewrites root README.md into a user-facing pitch plus a role-targeted developer entry. The user block names CLOUDER, the audience, and five concrete features. The developer block routes contributors into docs/."*

### Task 2.2: Open PR

- [ ] PR title `docs(p2): rewrite root README with user pitch and developer entry`. Merge after CI.

---

## Phase 3 — Backend docs

**Goal:** author `docs/backend/{handlers,providers,data-api,testing,gotchas}.md`. Branch: `docs/p3-backend`.

Each file below names the **source material** to read and the **section outline** to produce. The implementing engineer reads the named sources, extracts content, and writes the file in English. No prose is invented from scratch — everything traces to current code or CLAUDE.md.

### Task 3.1: `docs/backend/handlers.md`

**Files:**
- Create: `docs/backend/handlers.md`

**Source material to read:**
- `src/collector/handler.py` — API handler entry points
- `src/collector/worker_handler.py` — canonicalization worker
- `src/collector/search_handler.py` — AI search worker
- `src/collector/spotify_handler.py` — Spotify search worker
- `src/collector/vendor_match_handler.py` — vendor match worker
- `src/collector/migration_handler.py` — migration Lambda
- `infra/api_gateway.tf`, `infra/auth.tf`, `infra/curation.tf` — route bindings

**Required sections (H2):**
1. `Overview` — one paragraph: six Lambdas, one shared `src/collector/` package, distinct entry points.
2. `API Lambda (collector.handler)` — routes served, request validation, where the work happens, how it interacts with S3 + SQS + Aurora.
3. `Canonicalization worker (collector.worker_handler)` — SQS trigger, retries, DLQ, idempotency.
4. `AI search worker (collector.search_handler)` — trigger source, Perplexity client, AI-flag write-back.
5. `Spotify search worker (collector.spotify_handler)` — ISRC lookup + metadata fallback.
6. `Vendor match worker (collector.vendor_match_handler)` — fuzzy scorer, match cache, review queue.
7. `Migration Lambda (collector.migration_handler)` — alembic invocation, IAM auth mode.
8. `Auth Lambda (collector.auth_handler)` — locate file in `src/collector/`; if module exists, document Spotify OAuth callback flow + token rotation. Defer details to `docs/frontend/auth.md` and `docs/api/auth-flow.md`.

**Cross-references:** every section ends with "See also: …" pointing to topical docs (`data-api.md`, `providers.md`) and ADRs (ADR-0001 for Data API, ADR-0004 for providers, etc.).

- [ ] **Step 1: Read all source files listed**

- [ ] **Step 2: Author `docs/backend/handlers.md`** following the section outline above. Use English throughout. Cite file paths with `src/collector/handler.py:NN` when referencing a specific function.

- [ ] **Step 3: Verify**

```bash
grep -c "^## " docs/backend/handlers.md
```

Expected: ≥ 7 (overview + 6+ handlers).

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Adds docs/backend/handlers.md describing the six Lambda entry points, their triggers, and their interaction with S3, SQS, and Aurora."*

### Task 3.2: `docs/backend/providers.md`

**Files:**
- Create: `docs/backend/providers.md`

**Source material:**
- `src/collector/providers/base.py` — Protocols and dataclasses
- `src/collector/providers/registry.py` — `_BUILDERS`, accessors, `VENDORS_ENABLED`
- Each `src/collector/providers/<vendor>/` package
- `CLAUDE.md` — "Provider classes are thin adapters", "Adding a new vendor", "`LookupProvider` gained per-track methods in Plan 4", "Vendor match cache is PK..."

**Required sections (H2):**
1. `Overview` — Protocol pattern, role split (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`).
2. `VENDORS_ENABLED gate` — env var format, lazy builders, `VendorDisabledError`.
3. `Wrapped vendors` — Beatport (ingest), Spotify (lookup, enrich, export-stub), Perplexity (label enrich, artist stub).
4. `Stubbed vendors` — YT Music, Deezer, Apple, Tidal — Protocol-satisfied but raise.
5. `Per-track lookup methods` — `lookup_by_isrc`, `lookup_by_metadata`, asymmetric vendor support.
6. `Adding a new vendor` — three concrete steps from CLAUDE.md.

- [ ] **Step 1: Read sources**

- [ ] **Step 2: Author the file**

- [ ] **Step 3: Verify**: `grep -c "^## " docs/backend/providers.md` ≥ 6.

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Adds docs/backend/providers.md documenting the vendor abstraction, VENDORS_ENABLED gating, wrapped and stubbed vendors, and the three-step recipe for adding a vendor."*

### Task 3.3: `docs/backend/data-api.md`

**Files:**
- Create: `docs/backend/data-api.md`

**Source material:**
- `src/collector/data_api.py` — `DataAPIClient` implementation
- `CLAUDE.md` — entries on `retry_data_api`, `retry_data_api_pre_execution`, `find_identity` + `transaction_id`, GROUP BY EXISTS bug, secrets caching

**Required sections (H2):**
1. `Why Data API at runtime` — one paragraph + link to ADR-0001.
2. `DataAPIClient interface` — read, write, transaction methods.
3. `Retry policies` — `retry_data_api` (all transient codes, read/write) vs `retry_data_api_pre_execution` (commit / rollback only). Why splitting matters.
4. `Transactions and find_identity` — passing `transaction_id`, in-flight write visibility.
5. `Secrets caching` — `lru_cache` on `_fetch_secret_string`, rotation requires Lambda recycle.
6. `Pitfalls` — correlated EXISTS after GROUP BY (concrete SQL example from CLAUDE.md), idempotency on non-idempotent writes.

- [ ] **Step 1: Read sources**

- [ ] **Step 2: Author the file**

- [ ] **Step 3: Verify**: `grep -c "^## " docs/backend/data-api.md` ≥ 6. Also `grep "ADR-0001" docs/backend/data-api.md` → ≥ 1.

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Adds docs/backend/data-api.md covering the DataAPIClient interface, retry policy split, transaction semantics, secrets cache lifecycle, and known SQL pitfalls."*

### Task 3.4: `docs/backend/testing.md`

**Files:**
- Create: `docs/backend/testing.md`

**Source material:**
- `pytest.ini`, `requirements-dev.txt`
- `tests/unit/` and `tests/integration/` — sample tests for structure
- `tests/integration/test_curation_handler.py` — `FakeRepo` pattern
- `CLAUDE.md` — `FakeDataAPI` only string-matches SQL fragments; CI checks beyond pytest

**Required sections (H2):**
1. `Running tests` — `pytest -q`, single-file form, env vars.
2. `Layout` — `tests/unit/` vs `tests/integration/`.
3. `FakeDataAPI and FakeRepo` — what they mock, what they miss (real PG needed for correlated EXISTS).
4. `CI beyond pytest` — `FakeRepo` signature mirroring, `frontend/src/api/schema.d.ts` regeneration diff check.

- [ ] **Step 1-4:** same template as 3.3.

- [ ] **Commit** via `caveman:caveman-commit`: *"Adds docs/backend/testing.md describing the pytest layout, the FakeDataAPI / FakeRepo limits, and the CI checks beyond unit and integration tests."*

### Task 3.5: `docs/backend/gotchas.md`

**Files:**
- Create: `docs/backend/gotchas.md`

**Source material:**
- `CLAUDE.md` — every "## Gotchas" bullet whose subject is backend-runtime (Data API behaviour, providers, AWS prefix, env vars, etc.). Frontend, data-canonicalization, and ops gotchas go elsewhere.

**Required sections (H2):**
1. `Runtime and packaging` — Data API vs psycopg, PYTHONPATH, package_lambda rename, AWS prefix `beatport-prod-*`, macOS `python` unavailable.
2. `Secrets and authentication` — `bp_token` discipline, master RDS secret retention, IAM auth flag stickiness.
3. `Concurrency and SQS` — queue visibility ≥ worker timeout, Lambda reserved concurrency gating flag.
4. `Behavioural surprises` — `/runs/{run_id}` 503 `db_not_configured`, API Gateway 29s timeout, list endpoints not projecting `is_ai_suspected`.

Each bullet is a short paragraph with the **what**, the **why**, and the **mitigation**.

- [ ] **Step 1-4:** same template.

- [ ] **Commit** via `caveman:caveman-commit`: *"Adds docs/backend/gotchas.md consolidating backend-runtime sharp edges previously inlined in CLAUDE.md."*

### Task 3.6: PR

- [ ] PR title `docs(p3): author backend docs`. Merge after CI.

---

## Phase 4 — Data docs

**Goal:** author `docs/data/{data-model,migrations,raw-ingestion,canonicalization,search-and-enrichment}.md`. Branch: `docs/p4-data`.

### Task 4.1: `docs/data/data-model.md`

**Files:**
- Create: `docs/data/data-model.md`

**Source material:**
- `docs/archive/legacy/data-model.md` — translate to English and refresh against current schema
- `src/collector/db_models.py` — authoritative SQLAlchemy models
- `alembic/versions/` — recent migrations for schema deltas not yet in the legacy doc

**Required sections (H2):**
1. `Domain map` — source layer (`source_entities`, `source_relations`, `ingest_runs`) → canonical layer (`clouder_*`) → identity bridge (`identity_map`) → triage / curation overlays.
2. `Source layer` — table-by-table, columns and constraints.
3. `Canonical layer` — `clouder_artists`, `clouder_labels`, `clouder_albums`, `clouder_tracks`, `clouder_track_artists`. Include the `release_type` and `is_ai_suspected` fields and link to their ADRs.
4. `Identity map` — purpose, when entries are written, `find_identity` semantics.
5. `Triage and curation overlays` — `triage_blocks`, `triage_buckets`, `clouder_categories`, playlist tables, vendor match tables.
6. `Multi-tenant overlay model` — link to ADR-0002, explain shared canonical core + per-user overlay shape.

- [ ] **Step 1: Read all sources**

- [ ] **Step 2: Author the file** in English. Where the legacy doc has Russian prose, translate. Where the legacy doc is out of date relative to `db_models.py`, prefer `db_models.py`. Use Mermaid ER diagrams sparingly for the canonical and overlay clusters.

- [ ] **Step 3: Verify**

```bash
grep -c "^## " docs/data/data-model.md
```

Expected: ≥ 6.

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Adds docs/data/data-model.md describing source, canonical, identity, triage, and curation layers, with cross-links to ADR-0002, ADR-0007, ADR-0008."*

### Task 4.2: `docs/data/migrations.md`

**Files:**
- Create: `docs/data/migrations.md`

**Source material:**
- `alembic.ini`, `alembic/env.py`, `alembic/versions/` (most recent five files for structure examples)
- `src/collector/migration_handler.py`
- `scripts/package_lambda.sh` — `alembic/` → `db_migrations/` rename
- `CLAUDE.md` — entries on packaging rename, IAM auth mode for migration Lambda
- `infra/migration_lambda.tf` (if exists) — env var contract

**Required sections (H2):**
1. `Local flow` — `alembic upgrade head` with `psycopg`, env vars.
2. `Packaging` — the `alembic/` → `db_migrations/` rename in the Lambda zip, why.
3. `Migration Lambda` — `action=upgrade` / `revision=head` invocation, IAM vs password auth mode (link ADR-0005).
4. `Autogenerate workflow` — when to use `alembic revision --autogenerate`, manual review steps.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/data/migrations.md covering the local alembic flow, the packaging rename, and the migration Lambda contract."*

### Task 4.3: `docs/data/raw-ingestion.md`

**Files:**
- Create: `docs/data/raw-ingestion.md`

**Source material:**
- `src/collector/handler.py` — API Lambda code path
- `src/collector/saturday_week.py` — Saturday-week conversion (link ADR-0003)
- `docs/archive/legacy/data-model.md` — S3 layout description (translate to English)
- `CLAUDE.md` — `POST /collect_bp_releases` deprecated, admin `/admin/beatport/ingest` is the live entry point, `_run_beatport_ingest` shared between them

**Required sections (H2):**
1. `Entry points` — admin `/admin/beatport/ingest` vs deprecated `/collect_bp_releases`. State that `_run_beatport_ingest` in `handler.py` is shared.
2. `Saturday-week convention` — definition, why (link ADR-0003), boundary cases (days before the first Saturday of January).
3. `S3 raw layout` — `raw/bp/releases/style_id=…/year=…/week=…/{releases.json.gz,meta.json}`.
4. `ingest_runs state machine` — `RAW_SAVED` → `QUEUED|FAILED_TO_QUEUE` → `COMPLETED|FAILED`. The `processing_outcome` / `processing_reason` quartet.
5. `Operational notes` — `processing_status=FAILED_TO_QUEUE` semantics, API Gateway 29s timeout interaction.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/data/raw-ingestion.md covering the admin and deprecated ingest entry points, the Saturday-week convention, the S3 raw layout, and the ingest_runs state machine."*

### Task 4.4: `docs/data/canonicalization.md`

**Files:**
- Create: `docs/data/canonicalization.md`

**Source material:**
- `src/collector/normalize.py`, `src/collector/canonicalize.py`
- `src/collector/worker_handler.py` — orchestration
- `CLAUDE.md` — `release_type` propagation (link ADR-0007), `is_ai_suspected` propagation (link ADR-0008), `find_identity` + transaction_id requirement

**Required sections (H2):**
1. `From raw to canonical` — normalize phase output shape, canonicalize phase upserts.
2. `identity_map` — purpose, write path, `find_identity` read path inside transactions (cross-link `docs/backend/data-api.md`).
3. `release_type propagation` — Spotify-only origin, propagation from `clouder_tracks` to `clouder_albums` via `propagate_release_type_to_albums`. Link ADR-0007.
4. `is_ai_suspected propagation` — soft flag, confidence threshold default 0.6, no-op vs explicit clear (`none_detected`). Link ADR-0008.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/data/canonicalization.md describing the normalize and canonicalize phases, identity_map semantics, release_type propagation, and is_ai_suspected propagation."*

### Task 4.5: `docs/data/search-and-enrichment.md`

**Files:**
- Create: `docs/data/search-and-enrichment.md`

**Source material:**
- `docs/archive/legacy/spotify-search.md` — translate to English and refresh
- `src/collector/search/` — search subpackage
- `src/collector/spotify_handler.py`, `src/collector/vendor_match/`
- `CLAUDE.md` — `SpotifyClient` three-lookup order, fuzzy thresholds, vendor match cache PK, `ai_search_results.result` JSONB shape

**Required sections (H2):**
1. `Spotify ISRC lookup` — primary path.
2. `Metadata fallback` — strict + relaxed acceptance tiers, normalisation rules. Link ADR-0006.
3. `Sibling ISRC neighbour matching` — ±1, ±2 on last digit, title+artist gate, no duration check, why.
4. `Perplexity label and artist screening` — AI-content classification, confidence threshold, propagation. Link ADR-0008.
5. `Vendor match cache` — PK `(clouder_track_id, vendor)`, idempotent upsert, low-confidence routing to `match_review_queue`.
6. `Result schema` — `ai_search_results.result` is JSONB; show example query for inner fields.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/data/search-and-enrichment.md covering Spotify ISRC lookup, metadata fallback tiers, sibling ISRC matching, Perplexity screening, the vendor match cache, and the ai_search_results JSONB shape."*

### Task 4.6: PR

- [ ] PR title `docs(p4): author data docs`. Merge after CI.

---

## Phase 5 — Frontend docs

**Goal:** author `docs/frontend/{features,playback,auth,testing,gotchas}.md`. Branch: `docs/p5-frontend`.

### Task 5.1: `docs/frontend/features.md`

**Source material:**
- `frontend/src/features/` — current feature folders
- `frontend/src/routes/`, `frontend/src/auth/`
- `docs/archive/legacy/frontend.md` — translate; refresh against current layout
- `CLAUDE.md` — feature-folder convention, `/admin/*` gating, route SPA bypass

**Required sections (H2):**
1. `Feature-folder convention` — `features/<feature>/{routes,components,hooks,lib}/`.
2. `Routing` — top-level registration, `requireAuth` loader, `requireAdmin` loader.
3. `Vite proxy` — env-gated proxy, SPA-aware bypass for `/categories` and `/triage`.
4. `Admin gating` — client + server, `is_admin` flag, conditional nav rendering.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/frontend/features.md describing the feature-folder convention, routing, the Vite proxy bypass, and admin gating."*

### Task 5.2: `docs/frontend/playback.md`

**Source material:**
- `frontend/src/features/playback/` (or wherever `PlaybackProvider` lives)
- `frontend/src/features/curate/hooks/useCurateHotkeys.ts`, `useCurateSession.ts`
- `frontend/src/features/categories/` — category player
- `CLAUDE.md` — F6 PlaybackProvider section, hotkey conventions, optimistic shrink + ADVANCE no-op, QueueSource discriminated union, MiniBar removal, two auto-advance detectors, cursor = lastCursor - 1 after shrink, seek hotkey 0/20/40/60/80%

**Required sections (H2):**
1. `PlaybackProvider lifecycle` — mounted in authenticated layout, SDK lazy-loaded on first play. Link ADR-0013.
2. `Queue source discriminated union` — bucket vs category variants.
3. `Hotkeys` — J/K, U, Q/W/E, digit assignment, seek 0/20/40/60/80%. Why `event.code` not `event.key`. Why not 0/25/50/75/100%.
4. `Auto-advance` — two detectors (URI mismatch, paused at position 0 with `wasPlayingExpectedRef`). Link ADR-0012.
5. `Optimistic shrink and cursor` — reducer ADVANCE no-op, cursor at lastCursor − 1 after shrink. Link ADR-0012.
6. `Spotify token plumbing` — in-memory `spotifyTokenStore`. Link ADR-0011.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/frontend/playback.md covering the PlaybackProvider lifecycle, queue source union, hotkeys, auto-advance detection, optimistic shrink, and Spotify token plumbing."*

### Task 5.3: `docs/frontend/auth.md`

**Source material:**
- `frontend/src/auth/`
- `frontend/src/features/admin/lib/bpTokenStore.ts`
- `CLAUDE.md` — refresh-cookie replay revocation, AuthProvider bootstrap fires /auth/refresh on mount, `bp_token` in memory only, Spotify access token bundled with refresh stream, `SPOTIFY_OAUTH_REDIRECT_URI` Lambda env caveat

**Required sections (H2):**
1. `AuthProvider and tokenStore` — bootstrap flow, refresh-on-mount.
2. `Refresh-cookie replay detection` — revokes all sessions. Link ADR-0015.
3. `Spotify access token bundling` — returned by `/auth/callback` and `/auth/refresh`, kept in `spotifyTokenStore`, no persistence. Link ADR-0011.
4. `Beatport token in memory only` — module singleton in `bpTokenStore.ts`, "Reset Beatport token" menu item, no persistence.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/frontend/auth.md describing AuthProvider, refresh-cookie replay revocation, Spotify token bundling, and the in-memory Beatport token store."*

### Task 5.4: `docs/frontend/testing.md`

**Source material:**
- `frontend/src/test/setup.ts`, `frontend/vite.config.ts`, `frontend/package.json` test scripts
- `CLAUDE.md` — five jsdom shims, `NODE_OPTIONS=--no-experimental-webstorage`, `notifyManager.setScheduler(queueMicrotask)`, i18n import, `ResizeObserver` + `scrollIntoView` + `getBoundingClientRect` stubs, MSW URL convention, Mantine portal singleton survives RTL cleanup

**Required sections (H2):**
1. `Test stack` — vitest, jsdom, MSW, React Testing Library, Mantine.
2. `Setup shims` — five items listed, each with the symptom they fix.
3. `Mantine in tests` — `MantineProvider` requirement for modal / notifications tests, scoping queries inside dialogs.
4. `MSW conventions` — URL origin must be `http://localhost`.
5. `Vitest typed mocks` — function-type form `vi.fn<() => Promise<T>>()`.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/frontend/testing.md covering the vitest stack, the five jsdom setup shims, Mantine-in-tests requirements, MSW conventions, and Vitest 2.x typed-mock form."*

### Task 5.5: `docs/frontend/gotchas.md`

**Source material:** every CLAUDE.md frontend bullet not yet covered in `features.md`, `playback.md`, `auth.md`, or `testing.md`.

**Required sections (H2):**
1. `Mantine 9 specifics` — `DatePickerInput` undriveable in jsdom, `Title` has no `truncate` prop, `setFieldValue` typing.
2. `TanStack Query` — observers sharing `queryKey` share `queryFn`, gcTime workaround.
3. `Styling` — `<Text component={Link}>` link color override, accent-magenta retired, scale-only just-tapped.
4. `Hooks rules + Navigate` — early-return + hooks lint pattern, thin guard wrapper.
5. `Cold-start auto-recovery` — pendingCreateRecovery + pendingFinalizeRecovery; promote to shared at N=3.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/frontend/gotchas.md consolidating Mantine, TanStack Query, styling, hook, and cold-start recovery sharp edges previously inlined in CLAUDE.md."*

### Task 5.6: PR

- [ ] PR title `docs(p5): author frontend docs`. Merge after CI.

---

## Phase 6 — Ops docs

**Goal:** author `docs/ops/{deploy,env-vars,logs,aurora,runbook}.md`. Branch: `docs/p6-ops`.

### Task 6.1: `docs/ops/deploy.md`

**Source material:**
- `.github/workflows/pr.yml`, `.github/workflows/deploy.yml`
- `scripts/package_lambda.sh`, `scripts/deploy_frontend.sh`
- `infra/` Terraform layout
- `CLAUDE.md` — CI section, GitHub Secrets in `production` environment

**Required sections (H2):**
1. `Pull request checks` — alembic-check, terraform, tests jobs.
2. `Deploy pipeline` — package → terraform apply (prod: `canonicalization_enabled=true`) → invoke migration Lambda.
3. `Frontend deploy` — `scripts/deploy_frontend.sh` flow.
4. `GitHub Secrets` — environment `production` holds Perplexity / Spotify creds; `AWS_GITHUB_ROLE_ARN` at repo root.
5. `Manual operations` — IAM auth toggle, `aws rds modify-db-cluster` examples.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/ops/deploy.md describing the PR checks, the deploy pipeline, the frontend deploy script, GitHub Secrets sourcing, and manual operations."*

### Task 6.2: `docs/ops/env-vars.md`

**Source material:**
- `CLAUDE.md` — "Env Vars (runtime)" section
- `infra/*.tf` — Lambda env var definitions

**Required sections (H2):**
1. `API and worker Lambda` — table: name, type, default, source.
2. `VENDORS_ENABLED` — accepted values, gating behaviour.
3. `AI search worker` — credential precedence, tuning vars.
4. `Spotify search worker` — credential precedence, metadata fallback tuning.
5. `Vendor match worker` — fuzzy threshold, duration tolerance.
6. `Migration Lambda` — auth mode envs.

Tables are the dominant format. Cross-link `docs/data/search-and-enrichment.md` and `docs/ops/aurora.md` where relevant.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/ops/env-vars.md as the single source of truth for Lambda runtime environment variables across all six Lambdas."*

### Task 6.3: `docs/ops/logs.md`

**Source material:**
- `CLAUDE.md` — Logs section
- `src/collector/` — structlog event emission sites

**Required sections (H2):**
1. `Tailing Lambda logs` — `aws logs tail` with terraform outputs.
2. `Structlog events` — full list (`request_received`, `beatport_request/response`, `collection_completed`, `canonicalization_completed/failed`, `migration_started/completed`, `spotify_isrc_neighbour_match`, `spotify_metadata_fallback_attempted/match/match_relaxed/rejected/scores`, …) with one-line meaning each.
3. `Aurora PostgreSQL logs` — disabled by default; enable with `aws rds modify-db-cluster --cloudwatch-logs-export-configuration ...`; tail path.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/ops/logs.md listing Lambda log tail commands, the canonical structlog event names, and the Aurora PostgreSQL log enable path."*

### Task 6.4: `docs/ops/aurora.md`

**Source material:**
- `infra/aurora.tf` (or equivalent)
- `CLAUDE.md` — Aurora auto-pause, IAM auth flag stickiness, `clouder_migrator` IAM grant quirk, master secret retention

**Required sections (H2):**
1. `Serverless v2 scaling` — `min_acu`, `max_acu`, auto-pause window. Link ADR-0014.
2. `IAM authentication` — toggle, terraform drift, manual `aws rds modify-db-cluster` cure. Link ADR-0005.
3. `Migrator role IAM grant` — must be done by master user via Secrets Manager or Data API. Concrete SQL.
4. `Master RDS secret retention` — required at runtime, do not delete after IAM cutover.
5. `Cold-start behaviour` — 503 risk after pause, mitigation paths.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/ops/aurora.md covering Serverless v2 scaling, IAM auth quirks, the migrator role grant procedure, master secret retention, and cold-start behaviour."*

### Task 6.5: `docs/ops/runbook.md`

**Source material:**
- `CLAUDE.md` — every "Known Operational Notes" + scattered ops gotchas
- `docs/ops/aurora.md` (just authored) — cross-link

**Required sections (H2):**
1. `Cold-start 503` — symptom, diagnosis (Aurora idle vs Beatport slow), fix (retry, bump `min_acu`).
2. `processing_status=FAILED_TO_QUEUE` — distinguishing disabled vs enqueue failure via `processing_outcome` / `processing_reason`.
3. `DLQ messages` — common causes, replay procedure.
4. `Refresh-cookie replay revocation` — recovery requires fresh login.
5. `Lambda reserved concurrency trip` — InvalidParameterValueException remedy via Service Quotas.

Format: each section is a short runbook entry — *symptom* / *diagnosis* / *fix*.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/ops/runbook.md with short runbook entries for the most common incidents: cold-start 503, FAILED_TO_QUEUE, DLQ replay, refresh-cookie revocation, and reserved concurrency trip."*

### Task 6.6: PR

- [ ] PR title `docs(p6): author ops docs`. Merge after CI.

---

## Phase 7 — API docs

**Goal:** author `docs/api/auth-flow.md`. `docs/api/openapi.yaml` and `docs/api/README.md` already exist. Branch: `docs/p7-api`.

### Task 7.1: `docs/api/auth-flow.md`

**Source material:**
- `src/collector/auth_handler.py` (or wherever auth lives)
- `infra/auth.tf` — `SPOTIFY_OAUTH_REDIRECT_URI` default, CloudFront vs API GW domains
- `CLAUDE.md` — Spotify OAuth redirect target, replay detection, refresh-cookie behaviour

**Required sections (H2):**
1. `OAuth start` — `/auth/login` flow, state cookie.
2. `OAuth callback` — `/auth/callback` exchange, CSRF state check, why CloudFront domain (not API GW). Link ADR-0011 + brief note that the CloudFront URL must also be in the Spotify Developer Dashboard allow-list.
3. `Token refresh` — `/auth/refresh`, what it returns (CLOUDER + Spotify tokens), rotation semantics. Link ADR-0011 + ADR-0015.
4. `Replay detection` — refresh-cookie reuse → revoke all sessions. Link ADR-0015.
5. `Sequence diagram` — Mermaid `sequenceDiagram` showing browser → API GW → auth-handler → Spotify, including the cookie-set step on callback and the rotation step on refresh.

- [ ] **Step 1-4** per template. Commit message: *"Adds docs/api/auth-flow.md describing the OAuth start, callback, refresh, and replay detection flows, with a sequence diagram and ADR cross-references."*

### Task 7.2: PR

- [ ] PR title `docs(p7): document API auth flow`. Merge after CI.

---

## Phase 8 — ADRs

**Goal:** author all fifteen ADRs in one PR. Branch: `docs/p8-adrs`.

All ADRs use the MADR-lite template from `docs/adr/README.md`. All set `Status: Accepted` and `Date: 2026-05-17`.

Each ADR is short (under two pages). Below is the **decision wording** to use for each; the implementing engineer fills in `Context` and `Consequences` by reading the source material named alongside.

### Task 8.1: ADR-0001 — RDS Data API at Lambda runtime (vs psycopg)

**Source:** `src/collector/data_api.py`, CLAUDE.md "Runtime DB = Data API, not psycopg", historical context: VPC endpoints were a cost / complexity issue.

**Decision wording:**

> Lambda runtime code uses the RDS Data API exclusively. `psycopg` is permitted only for the local `alembic` workflow, never inside `src/collector/` handler paths. The Lambda runtime never imports `psycopg`.

**Consequences:** Smaller deployment artifact (no compiled `psycopg` wheel). No VPC requirement for runtime Lambdas. Different transaction model — see `docs/backend/data-api.md`. Some SQL constructs behave differently from a psycopg connection (correlated EXISTS after GROUP BY).

### Task 8.2: ADR-0002 — Multi-tenant overlay model

**Source:** memory `project_clouder_tenancy.md`, `src/collector/db_models.py`, `docs/data/data-model.md`.

**Decision wording:**

> A single Aurora database hosts a shared canonical music catalogue (`clouder_*` entities) plus per-user overlays for playlists, categories, tags, and curation state. There is no per-tenant database isolation. Ownership is enforced at the column level via `owner_user_id` foreign keys on overlay tables.

**Consequences:** One schema to operate. No tenant data isolation at the storage layer — must be enforced in every query. Cross-tenant analytics and shared catalog dedup are trivial. Bulk tenant export requires explicit filtering.

### Task 8.3: ADR-0003 — Saturday-week as canonical period

**Source:** `src/collector/saturday_week.py`, `frontend/src/features/admin/lib/saturdayWeek.ts`.

**Decision wording:**

> Weekly periods are defined Saturday-to-Friday inclusive. Week 1 begins on the first Saturday on or after January 1. Days before the first Saturday belong to the previous year's last week. ISO weeks are not used.

**Consequences:** Matches the DJ release-week mental model. Year boundaries do not match the calendar year for a few days. Frontend and backend share an identical implementation (one in TypeScript, one in Python) — drift between the two is a bug.

### Task 8.4: ADR-0004 — Provider abstraction with `VENDORS_ENABLED` gate

**Source:** `src/collector/providers/`, CLAUDE.md sections on providers.

**Decision wording:**

> Third-party music services are wrapped behind role Protocols (`IngestProvider`, `LookupProvider`, `EnrichProvider`, `ExportProvider`) in `src/collector/providers/`. Adapter instances are constructed lazily via `_BUILDERS` in `providers/registry.py` and only when the vendor name appears in the `VENDORS_ENABLED` env var. Vendors not enabled raise `VendorDisabledError` from registry accessors.

**Consequences:** Tests for unrelated vendors do not require the disabled vendor's credentials. Adding a vendor is a three-step recipe (adapter class, builder, env var entry). Adapter signatures still match handler call sites rather than the per-track Protocol ideal — future Protocol cleanup is a known follow-up.

### Task 8.5: ADR-0005 — RDS IAM auth for migration Lambda

**Source:** `src/collector/migration_handler.py`, `infra/`, CLAUDE.md "AWS_AUTH_MODE", "master RDS secret retention", "clouder_migrator IAM grant" entries.

**Decision wording:**

> The migration Lambda authenticates to Aurora using an RDS IAM token (`AURORA_AUTH_MODE=iam`, `AURORA_DB_USER=clouder_migrator`). Runtime Lambdas continue to use the master secret via the Data API; the master secret is retained, not deleted, after the migration Lambda cutover.

**Consequences:** Migration credentials rotate automatically with the IAM session. The `rds_iam` role grant must be issued by the master user — `clouder_migrator` cannot self-grant. The IAM-auth flag does not always stick via Terraform; an out-of-band `aws rds modify-db-cluster` may be required. See `docs/ops/aurora.md`.

### Task 8.6: ADR-0006 — Spotify metadata fallback with strict / relaxed tiers

**Source:** CLAUDE.md "SpotifyClient runs three lookups in order", `src/collector/spotify_handler.py`.

**Decision wording:**

> When an ISRC lookup returns zero items and `SPOTIFY_METADATA_FALLBACK_ENABLED=true`, the Spotify worker tries (1) sibling ISRC neighbours with a title+artist gate, then (2) a metadata search with two acceptance tiers: **strict** (`title_sim ≥ 0.90`, `artist_sim ≥ 0.85`, `|dur_diff| ≤ 3000 ms`) and **relaxed** (`title_sim ≥ 0.95`, `artist_sim ≥ 0.95`, no duration check). Strict matches win when both tiers have hits.

**Consequences:** Catches the master-vs-radio-edit case where ISRCs differ by a digit. Adds two extra Spotify API calls in the worst case. Fallback is opt-in; default behaviour is unchanged.

### Task 8.7: ADR-0007 — `release_type` derived from Spotify

**Source:** CLAUDE.md "release_type is Spotify-only", `src/collector/canonicalize.py`.

**Decision wording:**

> `release_type` is sourced from Spotify (`album.album_type`) during ISRC enrichment. The Beatport payload does not expose a release-type field. The value is written onto `clouder_tracks` and propagated to the parent `clouder_albums` via `propagate_release_type_to_albums`. Tracks without a successful ISRC lookup keep `release_type = NULL`.

**Consequences:** Albums are typed as soon as any of their tracks resolves on Spotify. Pre-enrichment, the field is NULL — consumers must tolerate that. The propagation pass is a separate operation from the canonical upsert.

### Task 8.8: ADR-0008 — `is_ai_suspected` soft propagated flag

**Source:** CLAUDE.md "is_ai_suspected is propagated, not stored standalone", `src/collector/search/`.

**Decision wording:**

> `is_ai_suspected` is a soft flag set on `clouder_labels`, `clouder_artists`, and `clouder_tracks` after `propagate_ai_flag` runs, only when `confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default `0.6`). `ai_content=unknown` is a no-op; `none_detected` explicitly clears the flag. The authoritative finding lives in `ai_search_results`; the flag is a query-time filter.

**Consequences:** UI can filter on a single column without joining the JSONB. A wrongly-suspected entity can be cleared by another search returning `none_detected`. The flag is *not* projected by all list endpoints — querying Aurora directly is the verification path.

### Task 8.9: ADR-0009 — Frontend stack: React 19 + Mantine 9

**Source:** memory `project_clouder_frontend_stack.md`, `frontend/package.json`.

**Decision wording:**

> The SPA is built on React 19, Mantine 9, react-router 7, TanStack Query 5, and Vite 5. An earlier direction toward shadcn/ui + Tailwind was reversed; design tokens flow into a single MantineProvider theme.

**Consequences:** All visual components come from Mantine; ad-hoc shadcn-style primitives are out. The Mantine 9 jsdom shims are a permanent cost (see `docs/frontend/testing.md`). Theme customisation lives in one place.

### Task 8.10: ADR-0010 — Tap-to-assign curation UX

**Source:** memory `project_clouder_curation_ux.md`, `frontend/src/features/curate/`.

**Decision wording:**

> Curation assigns tracks to destination playlists by tapping (or hotkey-pressing) the playlist's button. Drag-and-drop is not used. Each destination has a hotkey (`Q W E …` and digits) plus a click target. The pattern works identically on desktop and mobile.

**Consequences:** Faster than drag-and-drop on both surfaces. No touch-drag complexity. Hotkey conflicts must be managed (see `docs/frontend/playback.md`). The assignment is optimistic — see ADR-0012.

### Task 8.11: ADR-0011 — Spotify token bundled with CLOUDER auth refresh

**Source:** CLAUDE.md "spotify_access_token is bundled with the CLOUDER auth refresh stream", `frontend/src/auth/`.

**Decision wording:**

> The backend includes a fresh Spotify access token in the response payload of `/auth/callback` and `/auth/refresh`. The SPA stores it in an in-memory `spotifyTokenStore` (mirror of `tokenStore`). It is never persisted to `localStorage`, `sessionStorage`, or cookies. The Spotify Web Playback SDK reads it via `getOAuthToken(cb)` on every callback invocation.

**Consequences:** One refresh stream rotates both tokens. SDK rotation is transparent. Tab close or hard reload requires a fresh login round-trip to re-acquire the Spotify token.

### Task 8.12: ADR-0012 — Optimistic shrink, reducer ADVANCE no-op

**Source:** CLAUDE.md "Optimistic shrink does the work", `frontend/src/features/curate/hooks/useCurateSession.ts`.

**Decision wording:**

> When a track is assigned, `applyOptimisticMove` filters it from the bucket cache synchronously. `currentIndex` already points at the natural next track; the reducer's `ADVANCE` action is therefore a no-op. The reducer keeps a `pending` window and a `lastOp` snapshot to handle double-tap and undo correctly.

**Consequences:** No track is skipped after a single tap. Double-tap re-targets the *same* track using the stored `lastOp.input.trackIds[0]`, not the post-shrink queue head. Undo restores the snapshot and uses `lastOp.trackIndex` to land the cursor back where it was at assign time.

### Task 8.13: ADR-0013 — PlaybackProvider in authenticated layout, SDK lazy-loaded

**Source:** CLAUDE.md "PlaybackProvider lives in the authenticated _layout.tsx", `frontend/src/features/playback/`.

**Decision wording:**

> `PlaybackProvider` mounts inside the authenticated route layout, not the root. The Spotify Web Playback SDK script is fetched only on the first `controls.play()` call. Public auth pages never instantiate the provider and never request a Spotify token.

**Consequences:** Cold load is cheaper for unauthenticated users. First-play has an extra SDK-boot round-trip — `controls.play()` returns early until `deviceIdRef` is non-null; callers must be ready to invoke play twice (the second after the SDK emits `ready`). Tests must mirror this by emitting `ready` between two `play()` calls.

### Task 8.14: ADR-0014 — Aurora Serverless v2 `min_acu=0`

**Source:** CLAUDE.md "Aurora auto-pause after 300s", `infra/`.

**Decision wording:**

> Aurora Serverless v2 is configured with `aurora_serverless_min_acu = 0` and `aurora_auto_pause_seconds = 300`. The cluster auto-pauses after five minutes of idle. The cost saving is roughly $43 / month relative to always-warm `min_acu = 0.5`.

**Consequences:** First request after pause may exceed the API Gateway 29-second timeout and return `Service Unavailable` even though the Lambda completes the work. Operators may bump `min_acu` to `0.5` when first-request latency matters more than cost. See `docs/ops/aurora.md` and `docs/ops/runbook.md`.

### Task 8.15: ADR-0015 — Refresh-cookie replay = revoke all sessions

**Source:** CLAUDE.md "Refresh-cookie replay detection is unforgiving", `src/collector/auth_handler.py` (or equivalent).

**Decision wording:**

> Reusing the same refresh cookie revokes every active session of the affected user. The only recovery path is a fresh `/auth/login` round-trip. There is no graceful re-auth on a single device.

**Consequences:** A stolen refresh cookie cannot ride alongside the legitimate session — the legitimate user will be logged out as soon as the attacker (or a buggy duplicate request) replays. Development workflows that copy cookies or share devtools state will surface this as accidental logouts. CI / tests that exercise `/auth/refresh` more than once must use a fresh login per case.

### Task 8.16: ADR file authoring loop

For each ADR file `docs/adr/NNNN-<slug>.md` listed in `docs/adr/README.md`:

- [ ] **Step 1: Read named source material** (one or two files plus the CLAUDE.md anchor).

- [ ] **Step 2: Write the file** using the template from `docs/adr/README.md`. Use the **decision wording** above verbatim. Author `Context` and `Consequences` from the source material.

- [ ] **Step 3: Cross-link** to topical docs and to related ADRs.

- [ ] **Step 4: Verify**

```bash
ls docs/adr/ | grep -E '^[0-9]{4}-' | wc -l
```

Expected: `15` after the loop completes.

- [ ] **Step 5: Commit the batch** via `caveman:caveman-commit`: *"Adds the fifteen accepted ADRs distilled from CLAUDE.md gotchas, archived specs, and current code. Each ADR is short, append-only, and cross-linked to its topical doc."*

### Task 8.17: PR

- [ ] PR title `docs(p8): add the fifteen accepted ADRs`. Merge after CI.

---

## Phase 9 — CLAUDE.md slim

**Goal:** rewrite `CLAUDE.md` to ~6-8k characters. Branch: `docs/p9-claude-md-slim`.

### Task 9.1: Rewrite `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md` (full replacement)

- [ ] **Step 1: Take a backup snapshot for verification**

```bash
cp CLAUDE.md /tmp/CLAUDE.md.pre-p9
wc -c CLAUDE.md /tmp/CLAUDE.md.pre-p9
```

- [ ] **Step 2: Write the new slim CLAUDE.md**

Target content (English; replace the file body in full):

```markdown
# CLOUDER — Agent Orientation

CLOUDER is a serverless ingest pipeline plus a React 19 SPA for DJ track curation. The backend lives under `src/collector/`; the SPA under `frontend/`. Infrastructure is Terraform in `infra/`. Aurora PostgreSQL is reached **only via the RDS Data API at runtime** — never `psycopg` inside Lambda code.

This file is the AI-agent map. Detailed documentation lives in `docs/`.

## Where things are

- `src/collector/` — Lambdas (API, worker, search, spotify, vendor_match, migration) + providers + data-access layer.
- `frontend/` — Vite + React 19 + Mantine 9 SPA.
- `alembic/` — schema migrations.
- `infra/` — Terraform (API Gateway, Lambdas, SQS, Aurora, VPC).
- `tests/{unit,integration}` — pytest suites.
- `docs/` — see `docs/architecture.md` first, then the role folder for your task.

## Commands

```bash
python -m pip install -r requirements-dev.txt
pytest -q
pytest tests/unit/test_canonicalize.py -q

export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head

scripts/package_lambda.sh

PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py

cd infra && terraform init && terraform apply
```

## Policies

These are enforced by PreToolUse hooks. Failing them blocks the commit / PR.

- **Commits go through the `caveman:caveman-commit` skill.** Take its output, then `git commit -m "..."`. Never hand-write subject lines.
- **Multi-line commit bodies use heredoc form:** `git commit -m "$(cat <<'EOF' ... EOF)"`. The bare `-m "..."` form truncates the body silently.
- **Conventional Commits required:** subject must match `^(feat|fix|chore|docs|refactor|test|perf|build|ci|style|revert)(\(.+\))?!?: `.
- **Branch names never carry user / agent prefixes.** Use `feat/`, `fix/`, `chore/`, `docs/`, etc.
- **PR titles AND bodies are generated by `caveman:caveman-commit` before `gh pr create`.**

## Top-10 critical gotchas

These bite almost any session. Read the linked topical doc when you need the full picture.

1. **Runtime DB is the Data API, not psycopg.** Importing `psycopg` from any `src/collector/` handler path breaks the Lambda. See `docs/backend/data-api.md`, ADR-0001.
2. **`PYTHONPATH=src` is required** for scripts outside `pytest` (`pytest.ini` sets it for the test runner only).
3. **macOS `python` is unavailable.** Use `python3` for stdlib-only scripts; for project scripts importing `yaml`/`pydantic`, use `.venv/bin/python` (Homebrew `python3.14` lacks deps).
4. **AWS resource prefix is `beatport-prod-*`** (e.g. `beatport-prod-collector-api`). The repo dir is `clouder-core` — they are not the same name.
5. **`bp_token` is never logged or persisted.** No S3, no localStorage, no cookies, no structlog. See `docs/frontend/auth.md`.
6. **Saturday-week, not ISO-week,** is the canonical period. Week 1 begins on the first Saturday on or after January 1. See ADR-0003.
7. **Aurora cold-start 503.** With `min_acu=0`, first request after a 300 s idle may exceed the API Gateway 29 s timeout. See ADR-0014, `docs/ops/runbook.md`.
8. **`docs/api/openapi.yaml` is generated.** Regenerate with `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py` after editing routes in `infra/*.tf` or `scripts/generate_openapi.py:ROUTES`. The frontend CI diff-checks `frontend/src/api/schema.d.ts` against it.
9. **Frontend `pnpm dev` must run from `frontend/`,** not the repo root. Requires `frontend/.env.local` with `VITE_API_BASE_URL=$(cd infra && terraform output -raw api_endpoint)`.
10. **Refresh-cookie replay revokes every session of the user.** Only a fresh `/auth/login` restores them. See ADR-0015.

## Where to go next

| You are working on | Read first |
|---|---|
| Anything you don't recognise | `docs/architecture.md` |
| Backend code, providers, Data API | `docs/backend/` |
| Schema, ingest, canonicalization, search | `docs/data/` |
| SPA, playback, auth, tests | `docs/frontend/` |
| Deploy, env vars, logs, Aurora, incidents | `docs/ops/` |
| API surface, OpenAPI, auth flow | `docs/api/` |
| Why this is the way it is | `docs/adr/` |
| Detailed sharp edges in a subsystem | `docs/<area>/gotchas.md` |
```

- [ ] **Step 3: Verify size and content**

```bash
wc -c CLAUDE.md
```

Expected: between 5500 and 9000 bytes. The target band is "roughly 6-8k".

```bash
grep -c "docs/" CLAUDE.md
```

Expected: ≥ 10 (pointers into docs/).

```bash
for path in docs/architecture.md docs/backend docs/data docs/frontend docs/ops docs/api docs/adr; do
  test -e "$path" || echo "MISSING: $path"
done
```

Expected: no `MISSING` lines.

- [ ] **Step 4: Spot-check that no gotcha is silently dropped**

Open `/tmp/CLAUDE.md.pre-p9` and walk through every `Gotchas` bullet. For each, confirm one of:
- It is one of the top-10 still inlined, OR
- It appears in a `docs/<area>/gotchas.md` or topical doc authored in P3–P6, OR
- It is captured as an ADR in P8.

If a bullet does not fit any of those, restore it to CLAUDE.md or move it to the appropriate topical doc before committing.

- [ ] **Step 5: Commit** via `caveman:caveman-commit`: *"Rewrites CLAUDE.md as a slim ~6-8k orientation file: project map, commands, policies, top-10 critical gotchas, and pointers into docs/. Detailed gotchas now live in docs/<area>/gotchas.md."*

### Task 9.2: PR

- [ ] PR title `docs(p9): slim CLAUDE.md to ~6-8k`. Merge after CI.

---

## Phase 10 — Verify + delete legacy

**Goal:** final link audit, delete `docs/archive/legacy/` once nothing references it, delete this plan file. Branch: `docs/p10-verify-cleanup`.

### Task 10.1: Audit references to legacy paths

- [ ] **Step 1: Grep**

```bash
grep -rn "docs/data-model\.md\|docs/frontend\.md\|docs/spotify-search\.md\|docs/openapi\.yaml" \
  --include="*.py" --include="*.ts" --include="*.tsx" --include="*.yml" --include="*.yaml" \
  --include="*.tf" --include="*.json" --include="*.md" --include="*.sh" \
  . 2>/dev/null | grep -v "docs/archive/" | grep -v "docs/superpowers/" | grep -v "node_modules"
```

Expected: empty. Any hit must be patched to the new path before continuing.

- [ ] **Step 2: Verify the README and CLAUDE.md links resolve**

```bash
for f in README.md CLAUDE.md; do
  awk 'match($0, /\]\(([^)]+)\)/, m) { print m[1] }' "$f" | while read link; do
    case "$link" in
      http*|/*) continue ;;
      *) test -e "$link" || echo "BROKEN in $f: $link" ;;
    esac
  done
done
```

Expected: empty.

- [ ] **Step 3: Verify ADR cross-links resolve**

```bash
ls docs/adr/*.md | while read adr; do
  grep -oE 'ADR-[0-9]{4}|docs/[a-zA-Z0-9_./-]+\.md' "$adr" | sort -u | while read ref; do
    case "$ref" in
      ADR-*)
        num="${ref#ADR-}"
        ls docs/adr/${num}-*.md >/dev/null 2>&1 || echo "BROKEN ADR ref in $adr: $ref"
        ;;
      docs/*)
        test -e "$ref" || echo "BROKEN doc link in $adr: $ref"
        ;;
    esac
  done
done
```

Expected: empty.

### Task 10.2: Delete `docs/archive/legacy/`

- [ ] **Step 1: Confirm no inbound references**

```bash
grep -rn "docs/archive/legacy" \
  --include="*.md" --include="*.py" --include="*.ts" --include="*.tsx" \
  --include="*.yml" --include="*.yaml" --include="*.tf" --include="*.json" \
  . 2>/dev/null | grep -v "docs/archive/" | grep -v "docs/superpowers/"
```

Expected: empty.

If references exist in README.md or CLAUDE.md, they must already have been replaced in P2 / P9. Remove any stragglers now via the `caveman:caveman-commit` skill as a small patch commit before deletion.

- [ ] **Step 2: Delete the folder**

```bash
git rm -r docs/archive/legacy/
```

- [ ] **Step 3: Commit** via `caveman:caveman-commit`: *"Deletes docs/archive/legacy/. The three legacy files have been fully superseded by docs/data/, docs/frontend/, and docs/data/search-and-enrichment.md."*

### Task 10.3: Delete this plan file

- [ ] **Step 1: Delete**

```bash
git rm docs/superpowers/plans/2026-05-17-documentation-overhaul.md
```

- [ ] **Step 2: If `docs/superpowers/plans/` is now empty, remove the folder**

```bash
rmdir docs/superpowers/plans 2>/dev/null || true
test -d docs/superpowers/plans && echo "plans/ still exists, inspect contents" || echo "plans/ removed"
```

- [ ] **Step 3: If `docs/superpowers/` is now empty, remove it**

```bash
rmdir docs/superpowers 2>/dev/null || true
test -d docs/superpowers && echo "superpowers/ still exists, inspect contents" || echo "superpowers/ removed"
```

- [ ] **Step 4: Commit** via `caveman:caveman-commit`: *"Removes the documentation-overhaul plan and the now-empty docs/superpowers/ folders."*

### Task 10.4: PR

- [ ] PR title `docs(p10): final audit and legacy cleanup`. Merge after CI.

---

## Self-review against the spec

- **User block in README** — Task 2.1 ✓
- **Developer block with role-targeted links** — Task 2.1 ✓
- **English everywhere under `docs/` (except `design_handoff/` and `archive/`)** — every authored file is in English; P2 / P3 / P4 / P5 / P6 / P7 / P8 / P9 all assert English content ✓
- **`docs/architecture.md` with one mermaid diagram** — Task 1.1 ✓
- **Every CLAUDE.md gotcha retained, moved, or distilled to ADR** — Task 9.1 Step 4 mandates the walk-through ✓
- **Fifteen ADRs status `Accepted`** — Phase 8 ✓
- **`docs/superpowers/plans/` deleted** — Task 0.5 (other plans) + Task 10.3 (this plan) ✓
- **`docs/superpowers/specs/` moved to `docs/archive/specs/`** — Task 0.4 ✓
- **`docs/openapi.yaml` moved to `docs/api/openapi.yaml` with all references updated** — Task 0.3 (file + script + frontend codegen + CI workflow) ✓
- **CLAUDE.md ~6-8k** — Task 9.1 Step 3 verifies ✓
- **No broken references after the overhaul** — Task 10.1 + Task 10.2 ✓

## Notes for the executor

- Tasks within a phase are **sequential by default**. The phase-level boundary is the PR.
- Phases 3, 4, 5, 6, 7 are **mutually independent** once Phase 1 is merged. They can run in parallel branches.
- Phase 8 (ADRs) is also independent of P3–P7; it can run in parallel with them. P9 (CLAUDE.md slim) must run after P3–P8 because it points at finished files.
- For any task where the source material is unclear or the current code has drifted from CLAUDE.md, **trust the current code** and fix the wording in your authored doc — then note the drift in the PR description for the user to confirm.
- Every commit goes through `caveman:caveman-commit`. Verify after every commit with `git log -1 --pretty=%B`.

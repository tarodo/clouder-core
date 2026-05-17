# Documentation Overhaul Design

Date: 2026-05-17
Status: Accepted (design)

## Goal

Reshape repository documentation so that:

1. The root `README.md` clearly explains **what CLOUDER is, who it is for, and why** to a non-developer reader, then hands off to developer-focused documentation.
2. All other documentation is organised by **reader role** (backend dev, data engineer, frontend dev, ops/SRE, API consumer) instead of being scattered as ad-hoc files.
3. Historical implementation plans are removed and historical design specs are archived; long-lived architectural decisions are distilled into a small set of Architecture Decision Records (ADRs).
4. `CLAUDE.md` is reduced from a 38k all-inclusive gotcha dump to a ~6-8k orientation file that points into the new `docs/` tree.
5. Every documentation file under `docs/` is written in English.

The current state of the repo treats `README.md` as "Beatport Weekly Releases Collector" documentation, which only describes the backend ingest pipeline. The actual product is **CLOUDER**, a DJ track-curation application built on top of that pipeline. This overhaul realigns the documentation surface with the product.

## Non-Goals

- Rewriting user-visible product copy beyond the README user block (no marketing site, no separate end-user help center).
- Translating `docs/design_handoff/` content — it stays as a designer-handoff artifact in its current location.
- Touching `frontend/README.md` beyond a light English pass — the SPA-local quickstart stays minimal and is not duplicated under `docs/frontend/`.
- Restructuring `docs/superpowers/specs/*` content. They are archived as-is for historical reference; ADRs are distilled separately, not copied.
- Establishing new conventions for future documentation lifecycle (review cadence, ownership). Out of scope; can be a follow-up.

## Audience Map

| Surface | Primary audience | Tone |
|---|---|---|
| `README.md` user block | Prospective user (a DJ in the circle) | Product-marketing-lite, plain English |
| `README.md` developer block | New contributor | Terse, link-heavy entry point |
| `docs/architecture.md` | Any new developer | System overview, one diagram |
| `docs/backend/` | Backend / API / worker dev | Code-level, pattern-oriented |
| `docs/data/` | Data engineer | Schema, transforms, pipelines |
| `docs/frontend/` | Frontend dev | SPA stack, feature folders, quirks |
| `docs/ops/` | Ops / SRE / on-call | Deploy, env vars, logs, runbooks |
| `docs/api/` | API consumer / integrator | Auth flow + OpenAPI |
| `docs/adr/` | Any contributor (esp. AI agents) | Decisions, why-this-way |
| `CLAUDE.md` | AI coding agents | Project map + load-bearing rules |
| `frontend/README.md` | Frontend dev (local quickstart only) | Minimal `pnpm dev` setup |

## Target Documentation Tree

```
README.md                       # User pitch + developer entry pointers
CLAUDE.md                       # Slim AI-agent orientation (~6-8k)
docs/
├── architecture.md             # Single source of truth for system overview
├── backend/
│   ├── README.md               # Package map, local entry points
│   ├── handlers.md             # API, worker, search, spotify, vendor_match, migration Lambdas
│   ├── providers.md            # Vendor abstraction, VENDORS_ENABLED, adding a vendor
│   ├── data-api.md             # DataAPIClient, retries, transactions, find_identity
│   ├── testing.md              # pytest setup, FakeDataAPI limits
│   └── gotchas.md              # Backend-only gotchas distilled from CLAUDE.md
├── data/
│   ├── README.md               # Domain map: source → canonical → overlay
│   ├── data-model.md           # Canonical entities + triage tables (rewrite of legacy)
│   ├── migrations.md           # Alembic flow, packaging rename, migration Lambda
│   ├── raw-ingestion.md        # Beatport API → S3 layout, ingest_runs state machine, Saturday-week
│   ├── canonicalization.md     # normalize → canonical, identity_map, propagation
│   └── search-and-enrichment.md# Spotify ISRC + metadata fallback, Perplexity, vendor_match cache, AI flag
├── frontend/
│   ├── README.md               # SPA stack overview; defers to frontend/README.md for local env
│   ├── features.md             # Feature-folder convention, routing, auth/admin guards
│   ├── playback.md             # PlaybackProvider, SDK lazy-load, hotkeys, Curate vs Category players
│   ├── auth.md                 # AuthProvider, tokenStore, refresh-cookie, Spotify token bundling
│   ├── testing.md              # vitest + jsdom shims, MSW, MantineProvider in tests
│   └── gotchas.md              # Frontend-only gotchas distilled from CLAUDE.md
├── ops/
│   ├── README.md               # Operational map (AWS prefix, resource naming)
│   ├── deploy.md               # CI/CD workflows, terraform apply order, migration Lambda
│   ├── env-vars.md             # Full runtime env table per Lambda
│   ├── logs.md                 # Structlog events, aws logs tail, Aurora postgresql log enable
│   ├── aurora.md               # Serverless v2 scaling, auto-pause, IAM auth quirks
│   └── runbook.md              # Common incidents (cold-start 503, FAILED_TO_QUEUE, DLQ)
├── api/
│   ├── README.md               # API surface map
│   ├── openapi.yaml            # Moved from docs/openapi.yaml
│   └── auth-flow.md            # OAuth Spotify redirect, refresh-token rotation
├── adr/
│   ├── README.md               # ADR index + MADR template + status flow
│   └── 0001..0015-*.md         # See ADR list below
├── archive/
│   ├── legacy/                 # docs/data-model.md, docs/frontend.md, docs/spotify-search.md (pre-rewrite)
│   └── specs/                  # docs/superpowers/specs/* moved here, plus the loose 2026-05-13 design
└── design_handoff/             # Unchanged
```

### Files removed

- `docs/superpowers/plans/*` — deleted entirely. Implementation plans are scaffolding; once shipped, their value approaches zero. Git history retains them.
- `docs/superpowers/` parent folder retained only if it contains the `specs/` archive; otherwise removed alongside `plans/`.

### Files preserved without change

- `docs/design_handoff/` (handoff artifact for designer/dev sync).
- `frontend/README.md` (SPA quickstart). May get a light English pass if Russian text is present, but no structural change.

## README.md Design

### Section 1: User block (~½ page)

- **Tagline** — one sentence: what CLOUDER is, for whom.
- **Audience** — small DJ circle; multi-tenant SaaS shape; "pro tool" tone.
- **Features** — 3 to 5 bullets, examples:
  - Weekly automated track ingest from Beatport into a personal canonical library.
  - Tap-to-curate workflow that turns weekly triage into Spotify-ready playlists.
  - In-browser playback via the Spotify Web Playback SDK, keyboard-first.
  - AI-assisted label / artist screening to flag suspected AI-generated content.
  - Per-DJ playlists and tag overlays on a shared canonical catalogue.
- **Screenshot** — optional, single hero image of the curation surface.

### Section 2: Developer entry block (~½ page)

- One-paragraph architecture summary: serverless ingest pipeline + Aurora canonical store + React SPA.
- "Start here" link to `docs/architecture.md`.
- Role-targeted links:
  - Backend dev → `docs/backend/`
  - Data engineer → `docs/data/`
  - Frontend dev → `docs/frontend/`
  - Ops / SRE → `docs/ops/`
  - API consumer → `docs/api/`
  - Architecture decisions → `docs/adr/`
- A short "Quickstart" snippet (clone, install dev deps, run tests, link to local-run docs in `docs/ops/`).

The entire README is in English. No CLI invocation examples beyond the quickstart; everything else lives under `docs/ops/`.

## CLAUDE.md Design

Target size: ~6-8k characters (down from ~38k). Aggressive cut.

### Sections that stay inline

1. **Project intro** — one paragraph.
2. **Layout map** — 10-15 lines pointing at `src/`, `frontend/`, `infra/`, `alembic/`, `docs/`.
3. **Core commands** — pytest, alembic, `scripts/package_lambda.sh`, terraform, `generate_openapi.py`. ~5-10 lines.
4. **Policies** (load-bearing every session; some are enforced by PreToolUse hooks):
   - Commit message format — Conventional Commits via `caveman:caveman-commit` skill.
   - Multi-line commit message must use heredoc form.
   - Branch naming — no user/agent prefix; `feat/`, `fix/`, `chore/`, etc.
   - PR title and body via `caveman:caveman-commit` skill.
5. **Top-10 critical gotchas** (those that bite almost any session):
   - Data API ≠ psycopg at runtime
   - `PYTHONPATH=src` for non-pytest scripts
   - macOS `python` unavailable — use `python3` or `.venv/bin/python`
   - AWS prefix `beatport-prod-*` ≠ repo dir `clouder-core`
   - `bp_token` never logged, never persisted
   - Saturday-week is the canonical period (not ISO-week)
   - Aurora cold-start 503 risk after auto-pause
   - `docs/api/openapi.yaml` must be regenerated after route changes
   - Frontend `pnpm dev` must be run from `frontend/`, not repo root
   - Heredoc form mandatory for multi-line `git commit -m`
6. **Pointers** — explicit "see also" lines:
   - Detailed gotchas: `docs/<area>/gotchas.md`
   - Architecture overview: `docs/architecture.md`
   - Decisions and why-this-way: `docs/adr/`
   - Runbook: `docs/ops/runbook.md`

### Sections moved out

- Backend-runtime gotchas (Data API retry semantics, `find_identity` transaction id, secrets cache, etc.) → `docs/backend/gotchas.md` + `docs/backend/data-api.md`.
- Frontend gotchas (Mantine 9 jsdom shims, F6 SDK quirks, refresh-cookie, etc.) → `docs/frontend/gotchas.md` and topical files.
- Ops / Aurora / IAM quirks → `docs/ops/aurora.md` + `docs/ops/runbook.md`.
- Data canonicalization specifics (`release_type` propagation, AI flag confidence threshold, etc.) → `docs/data/canonicalization.md` + `docs/data/search-and-enrichment.md`.
- Env var tables → `docs/ops/env-vars.md`.
- Logs and structlog event list → `docs/ops/logs.md`.

### Distribution principle

- Load-bearing for **every** session → stays inline in CLAUDE.md.
- Load-bearing when **touching this subsystem** → topical file under `docs/`.
- The "why" behind an architectural choice → an ADR under `docs/adr/`.

## ADR Set

Format: MADR-lite. Each ADR is at most two pages.

```
# ADR-NNNN: <Title>
Status: Accepted
Date: YYYY-MM-DD

## Context
What problem, what forces, what alternatives were considered.

## Decision
What we chose.

## Consequences
Trade-offs accepted. What becomes harder. Cross-references to gotchas / topical docs.
```

`docs/adr/README.md` carries the index, the template, the status flow (Proposed → Accepted → Superseded / Deprecated), and the numbering rule (4-digit, monotonic, never reused).

### Planned ADRs

| # | Title | Audience |
|---|---|---|
| 0001 | RDS Data API at Lambda runtime (vs psycopg) | backend |
| 0002 | Multi-tenant overlay model — shared canonical core + per-user overlay | data |
| 0003 | Saturday-week as the canonical period (vs ISO-week) | data |
| 0004 | Provider abstraction — `providers/` Protocol + `VENDORS_ENABLED` gate | backend |
| 0005 | RDS IAM auth for the migration Lambda; master secret retained for runtime | ops |
| 0006 | Spotify metadata fallback with strict / relaxed acceptance tiers | data |
| 0007 | `release_type` derived from Spotify and propagated to canonical entities | data |
| 0008 | `is_ai_suspected` as a soft propagated flag with confidence threshold | data |
| 0009 | Frontend stack — React 19 + Mantine 9 (superseding earlier shadcn / Tailwind direction) | frontend |
| 0010 | Tap-to-assign curation UX (vs drag-and-drop) | frontend |
| 0011 | Spotify access token bundled with CLOUDER auth refresh; in-memory only | frontend |
| 0012 | Optimistic shrink as the cursor advance mechanism; reducer ADVANCE is a no-op | frontend |
| 0013 | PlaybackProvider lives in the authenticated layout; SDK lazy-loaded | frontend |
| 0014 | Aurora Serverless v2 `min_acu=0` — cost over warm floor | ops |
| 0015 | Refresh-cookie replay = revoke all sessions of the user | backend / security |

ADRs are **distilled** from `docs/superpowers/specs/*` and the current code, not copied. Each ADR links back to its source spec (in `docs/archive/specs/`) where relevant, but is self-contained.

## Migration Strategy

The rewrite is broken into ten phases. Each phase produces a self-contained change that can be reviewed independently. Phases 2–7 are independent of each other and may run in parallel after Phase 1.

### Phase 0 — Move + cleanup (low risk, no content rewrite)

- Create empty target folders: `docs/{backend,data,frontend,ops,api,adr,archive,archive/legacy,archive/specs}`.
- Move legacy files to `docs/archive/legacy/`:
  - `docs/data-model.md`
  - `docs/frontend.md`
  - `docs/spotify-search.md`
- Move `docs/openapi.yaml` → `docs/api/openapi.yaml`. Audit and update references:
  - `scripts/generate_openapi.py` (output path)
  - `.github/workflows/*.yml` (any diff-check step against the OpenAPI file)
  - Frontend codegen path for `frontend/src/api/schema.d.ts`
  - Any link inside the SPA, CLAUDE.md, or other docs.
- Move `docs/superpowers/specs/*` → `docs/archive/specs/`.
- Move the loose `docs/2026-05-13-category-player-frontend-design.md` → `docs/archive/specs/`.
- Delete `docs/superpowers/plans/*` (and the `docs/superpowers/` parent if it becomes empty).
- Sweep CLAUDE.md and README.md for stale links and patch them to the new locations.

### Phase 1 — Skeleton

- Create `docs/architecture.md` with the system overview and one mermaid diagram (API Lambda + Worker + Aurora + S3 + SQS + vendors + SPA).
- Create `README.md` files inside each role folder (`backend/`, `data/`, `frontend/`, `ops/`, `api/`, `adr/`) as empty tables of contents. These act as scaffolding for parallel work in later phases.

### Phase 2 — README.md rewrite

- Replace the current README content with the two-block design above (user block + developer entry).
- Single file, isolated change. Easy to revert if needed.

### Phase 3 — Backend docs

- Fill `backend/{handlers,providers,data-api,testing,gotchas}.md` from current code and CLAUDE.md extractions.

### Phase 4 — Data docs

- Fill `data/{data-model,migrations,raw-ingestion,canonicalization,search-and-enrichment}.md`.
- Source material: legacy `docs/data-model.md`, legacy `docs/spotify-search.md`, CLAUDE.md data sections, current schema in `src/collector/db_models.py`.

### Phase 5 — Frontend docs

- Fill `frontend/{features,playback,auth,testing,gotchas}.md`.
- Source material: legacy `docs/frontend.md`, CLAUDE.md frontend section, current code in `frontend/src/`.

### Phase 6 — Ops docs

- Fill `ops/{deploy,env-vars,logs,aurora,runbook}.md`. The env-var table is a single source of truth — duplicate references in other docs must be replaced with links.

### Phase 7 — API docs

- Author `api/auth-flow.md`. `api/openapi.yaml` is already in place after Phase 0.

### Phase 8 — ADRs

- Author all fifteen ADRs in one batch (single PR). ADRs are append-only and benefit from a single review pass.

### Phase 9 — CLAUDE.md slim

- Rewrite CLAUDE.md to the slim layout. Verify every pointer resolves to a real file. Done last so pointers can be authored against finished docs.

### Phase 10 — Verify + delete legacy

- `grep -R "docs/data-model\|docs/frontend\.md\|docs/spotify-search\|docs/openapi"` to catch every stale reference.
- Remove `docs/archive/legacy/` only after the grep is clean and CI is green.
- Final sanity pass: every link in README.md and CLAUDE.md resolves.

## Acceptance Criteria

- `README.md` has both a user block and a developer entry block; user block fits in roughly half a page and contains tagline, audience, 3–5 feature bullets.
- All files under `docs/` are in English, except `docs/design_handoff/` (preserved as-is, may retain Russian designer-handoff artifacts) and `docs/archive/` (frozen historical content, not rewritten).
- `docs/architecture.md` exists, with a single high-level diagram covering API Lambda, Worker Lambda, S3 raw store, SQS queue, Aurora, vendor providers, and the SPA.
- Every gotcha currently inlined in CLAUDE.md is either retained (top-10 critical) or has been moved to a topical `docs/<area>/` file. No gotcha is silently dropped.
- `docs/adr/` contains the fifteen ADRs listed above with status `Accepted`.
- `docs/superpowers/plans/` is deleted.
- `docs/superpowers/specs/` content is moved to `docs/archive/specs/`.
- `docs/openapi.yaml` has been moved to `docs/api/openapi.yaml` and all references are updated (including CI workflows and frontend codegen path if applicable).
- `CLAUDE.md` is reduced to roughly 6–8k characters and contains only the sections listed under "CLAUDE.md Design" above.
- A final grep shows no broken references to legacy doc paths.

## Risks and Mitigations

- **Broken links in code, CI, or the SPA after moving `docs/openapi.yaml`.** Mitigation: Phase 0 audit includes an explicit grep for the old path; CI runs verify before Phase 9.
- **Gotchas silently lost during CLAUDE.md slim.** Mitigation: the slim is the last phase; the "top-10 inline / rest topical" classification is checked against the current CLAUDE.md line-by-line in Phase 9. Anything not classifiable is kept in CLAUDE.md by default.
- **ADRs drift from reality if extracted from stale specs.** Mitigation: each ADR is cross-checked against current code and current CLAUDE.md gotchas, not only the source spec.
- **Reviewer overload from a single mega-PR.** Mitigation: ten phases shipped as separate PRs (or a small number of bundled PRs); each phase is self-contained.
- **English translation introduces ambiguity in technical terms.** Mitigation: keep code identifiers, AWS resource names, and event names verbatim; only the surrounding prose is translated.

## Out of Scope (Restated)

- Marketing / product help content beyond the README user block.
- Restructuring or translating `docs/design_handoff/`.
- A documentation lifecycle policy (review cadence, ownership). Can be a follow-up.
- Changes to the `frontend/README.md` beyond a possible light English pass.

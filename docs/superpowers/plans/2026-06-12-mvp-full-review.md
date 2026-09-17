# Full MVP Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to run this plan task-by-task in the main session. Tasks 3–6 invoke the `Workflow` tool, which is only available to the main loop — do NOT dispatch these tasks to subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute the approved full-repo review (spec: `docs/superpowers/specs/2026-06-10-mvp-full-review-design.md`) and produce `report.md` + `backlog.md` under `docs/reviews/2026-06-10-mvp-review/`, delivered as a PR.

**Architecture:** Six sequential phases, each a checkpoint: setup → automated scanners → multi-agent system map → finder fan-out (~26 agents over the subsystem×dimension matrix) → dedup + 3-lens adversarial verification → synthesis. Workflow scripts orchestrate agents; the main session writes all files (workflow scripts have no filesystem access — every phase returns JSON/markdown that the executor persists).

**Tech Stack:** Claude Workflow tool (multi-agent), bandit, pip-audit, pnpm audit, tsc, eslint, checkov, jq, git/gh.

---

## Context for the executor (zero-context primer)

- **Working dir (always):** `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/full_review` — a git worktree on branch `worktree-full_review`. Do not cd to the main repo root.
- **Repo:** CLOUDER — serverless ingest (AWS Lambda + Aurora via RDS Data API) + React SPA. Backend `src/collector/`, SPA `frontend/`, Terraform `infra/`, migrations `alembic/versions/` (30), tests `tests/{unit,integration}` + CI `.github/workflows/{pr,deploy}.yml`, docs + 20 ADRs in `docs/`.
- **This is a READ-ONLY review of the code.** No fixes, no live AWS calls. The only writes are review artifacts + this plan's checkboxes.
- **Sensitive:** `bp_token` and other user tokens must never be pasted into artifacts — reference code locations only.
- **macOS:** plain `python` does not exist; use `python3` for stdlib scripts. Project venv lives at the MAIN repo root: `/Users/roman/Projects/clouder-projects/clouder-core/.venv` (not needed for this plan — scanners use a throwaway venv in `/tmp`).
- **Commit policy (hook-enforced):** every commit message comes from the `caveman:caveman-commit` skill; Conventional Commits subject; no `Co-Authored-By`/AI trailers; multi-line bodies only via `git commit -m "$(cat <<'EOF' ... EOF)"`. Suggested subjects below still go through the skill.
- **Workflow failure recovery:** every `Workflow` call returns a `runId` and persisted script path. If a run dies mid-phase, re-invoke with `{scriptPath, resumeFromRunId}` — completed agents replay from cache.
- **Accepted MVP behaviors (do NOT report as findings):** cold-start 503 after Aurora idle (ADR-0014); refresh-cookie replay revoking all sessions (ADR-0015, intended); `min_acu=0` (deliberate cost choice); YouTube Music weekly re-connect in Testing mode. `experiments/` and `docs/archive/` are out of scope.

## File structure

Created by this plan:

```
docs/reviews/2026-06-10-mvp-review/
├── report.md              # final: executive summary, MVP verdict, per-dimension sections, stats
├── backlog.md             # final: all confirmed findings as checkboxes, P0→P3
├── scanners.md            # final: scanner summary appendix
├── system-map.md          # final: phase-2 map (data flows, attack surface, write/spend points)
└── working/               # intermediate, deleted in Task 6
    ├── scanner-findings.json   # scanner hits converted to the finding schema
    ├── findings-raw.json       # phase-3 finder output pool
    └── findings-verified.json  # phase-4 survivors with votes
```

The finding object (one schema end-to-end):

```json
{
  "title": "short imperative summary",
  "severity": "P0|P1|P2|P3",
  "dimension": "SEC|DATA|COST|REL|ARCH|TEST|DOCS",
  "subsystem": "auth|ingest|canonicalization|curation|enrichment|data-access|migrations|infra|frontend|ci|system",
  "where": "path/to/file.py:123",
  "evidence": "what the code actually does there",
  "risk": "concrete MVP consequence",
  "recommendation": "what to change",
  "effort": "S|M|L"
}
```

Severity guide (from the spec, repeated in every agent prompt): **P0** exploitable hole / data loss / uncontrolled AWS spend; **P1** serious risk in SEC/DATA/COST needing special conditions, or silent gradual corruption; **P2** reliability/correctness outside the weighted dimensions; **P3** quality/drift/test gaps.

---

### Task 1: Phase 0 — setup

**Files:**
- Create: `docs/reviews/2026-06-10-mvp-review/report.md` (scaffold)
- Create: `docs/reviews/2026-06-10-mvp-review/backlog.md` (scaffold)
- Create: `docs/reviews/2026-06-10-mvp-review/working/.gitkeep`

- [ ] **Step 1: Pin the review SHA and create the skeleton**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/full_review
REVIEW_SHA=$(git rev-parse HEAD)
mkdir -p docs/reviews/2026-06-10-mvp-review/working
touch docs/reviews/2026-06-10-mvp-review/working/.gitkeep
echo "$REVIEW_SHA"
```

- [ ] **Step 2: Write `report.md` scaffold** (fill `<SHA>` with the value from Step 1)

```markdown
# CLOUDER full MVP review — report

**Reviewed commit:** <SHA>
**Spec:** ../../superpowers/specs/2026-06-10-mvp-full-review-design.md
**Status:** IN PROGRESS

## Verdict

_(filled in synthesis phase)_

## Executive summary

_(filled in synthesis phase)_

## Findings by dimension

_(filled in synthesis phase)_

## Stats

_(filled in synthesis phase)_
```

- [ ] **Step 3: Write `backlog.md` scaffold**

```markdown
# CLOUDER MVP review — fix backlog

**Status:** IN PROGRESS — populated by the synthesis phase.

Sorted P0 → P3. Each item is self-contained for a standalone fix session.
```

- [ ] **Step 4: Commit**

Invoke `caveman:caveman-commit`, then commit. Suggested subject: `docs(review): scaffold MVP review artifacts`.

---

### Task 2: Phase 1 — automated scanners

**Files:**
- Create: `docs/reviews/2026-06-10-mvp-review/scanners.md` (draft)
- Create: `docs/reviews/2026-06-10-mvp-review/working/scanner-findings.json`

- [ ] **Step 1: Throwaway scanner venv**

```bash
python3 -m venv /tmp/mvp-review-venv
/tmp/mvp-review-venv/bin/pip -q install bandit pip-audit checkov
```

Expected: exits 0. (checkov pulls many deps; 1–3 min.)

- [ ] **Step 2: Run Python scanners** (from the worktree root)

```bash
/tmp/mvp-review-venv/bin/bandit -r src/collector -f json -o /tmp/mvp-bandit.json || true
/tmp/mvp-review-venv/bin/pip-audit -r src/collector/requirements.txt -f json -o /tmp/mvp-pipaudit-runtime.json || true
/tmp/mvp-review-venv/bin/pip-audit -r requirements-dev.txt -f json -o /tmp/mvp-pipaudit-dev.json || true
```

`|| true` because these exit non-zero when they find issues — that is the point.

- [ ] **Step 3: Run frontend scanners**

```bash
cd frontend && pnpm install --frozen-lockfile
pnpm audit --json > /tmp/mvp-pnpm-audit.json || true
pnpm typecheck > /tmp/mvp-tsc.txt 2>&1 || true
pnpm lint > /tmp/mvp-eslint.txt 2>&1 || true
cd ..
```

- [ ] **Step 4: Run checkov on Terraform**

```bash
/tmp/mvp-review-venv/bin/checkov -d infra -o json > /tmp/mvp-checkov.json || true
```

- [ ] **Step 5: Convert to the finding schema**

Read the outputs (use `jq`/`Read`). Apply these filters and write each surviving hit as a finding object into `working/scanner-findings.json` (a JSON array; `subsystem` per source file; severity by judgment within the guide):

| Source | Keep | Dimension |
|---|---|---|
| bandit | severity ≥ MEDIUM and confidence ≥ MEDIUM | SEC |
| pip-audit | every vulnerability | SEC |
| pnpm audit | high + critical | SEC |
| tsc | every error (not warning) | REL |
| eslint | errors only | REL |
| checkov | failed checks, excluding ones contradicting accepted behaviors | SEC, or COST for retention/sizing checks, REL for backup/DLQ checks |

Prefix scanner finding titles with the tool name, e.g. `bandit: ...`. These merge into the verification pool in Task 5 — scanner findings get verified like all others.

- [ ] **Step 6: Draft `scanners.md`** — one section per tool: command run, totals (found / kept after filter), and the kept items as a table. Raw JSON stays in `/tmp` (not committed).

- [ ] **Step 7: Sanity-check + commit**

```bash
jq length docs/reviews/2026-06-10-mvp-review/working/scanner-findings.json
```

Expected: a number ≥ 0, no parse error. Then caveman-commit; suggested subject: `docs(review): add scanner results`.

---

### Task 3: Phase 2 — system map (Workflow)

**Files:**
- Create: `docs/reviews/2026-06-10-mvp-review/system-map.md`

- [ ] **Step 1: Run the map workflow** — invoke `Workflow` with this script:

```js
export const meta = {
  name: 'mvp-review-system-map',
  description: 'Phase 2: parallel readers build the system map for finder context',
  phases: [{ title: 'Read' }, { title: 'Merge' }],
}
const ROOT = '/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/full_review'
const COMMON = `You are mapping the CLOUDER repo at ${ROOT} (read-only; never modify files; ignore experiments/ and docs/archive/). Return raw markdown for your section — no preamble. Every claim cites file:line. Be exhaustive within your area.`
const READERS = [
  { key: 'api-surface', prompt: `${COMMON} Section: **API surface & auth flow**. Enumerate every API Gateway route (infra/api_gateway.tf, infra/curation_routes_*.tf, infra/auth.tf) and its Lambda handler function (src/collector/handler.py, curation_handler.py, auth_handler.py). For each route: method, path, authorizer yes/no, where the handler derives user identity. Describe the JWT/refresh flow end to end (auth_handler.py, auth_authorizer.py, frontend/src/auth).` },
  { key: 'ingest-flow', prompt: `${COMMON} Section: **Ingest & canonicalization data flow**. Trace: Beatport fetch (beatport_client.py, handler.py) → S3 layout (storage.py) → SQS message shape → worker (worker_handler.py, canonicalize.py, normalize.py) → every Aurora table written, with the upsert/conflict strategy and transaction boundaries per message. Note ingest_runs lifecycle and saturday_week period logic.` },
  { key: 'enrichment-flow', prompt: `${COMMON} Section: **Enrichment & vendor calls**. Map every external vendor call site (spotify_client.py, spotify_handler.py, vendor_match*, label_enrichment*, artist_enrichment*, auto_enrich_dispatch_handler.py, providers/): trigger (route/queue/dispatch), vendor + endpoint, caching table, retry behavior, and what multiplies call volume (fan-out per track/block).` },
  { key: 'data-access', prompt: `${COMMON} Section: **Data-access layer**. Describe how SQL reaches Aurora: data_api.py, data_api_retry.py, repositories.py, db_models.py. How are statements built and parameterized? Where are transactions started/committed? Which operations retry and how is idempotency handled? List every raw-SQL construction site.` },
  { key: 'infra', prompt: `${COMMON} Section: **Infrastructure**. From infra/*.tf: every Lambda (memory, timeout, env vars, reserved concurrency), every queue (redrive policy, DLQ, visibility timeout), Aurora config (ACU bounds, backups, deletion protection), S3 buckets (public access, lifecycle), IAM roles and the actions each is granted (flag wildcards), alarms (alarms.tf) and log retention (logging.tf), network topology incl. NAT (network.tf).` },
  { key: 'frontend', prompt: `${COMMON} Section: **Frontend**. Map frontend/src: API client and auth/token storage (api/, auth/ — where tokens live, what touches localStorage/cookies), route structure, the curation/triage/playback feature surfaces (features/, hooks/), how API errors and 401/503 are handled, where optimistic updates mutate state.` },
]
phase('Read')
const sections = await parallel(READERS.map(r => () =>
  agent(r.prompt, { label: `map:${r.key}`, phase: 'Read' })))
phase('Merge')
const good = sections.filter(Boolean)
if (good.length < READERS.length) log(`WARNING: ${READERS.length - good.length} reader(s) returned nothing`)
const map = await agent(
  `Merge these sections into one coherent system-map.md for the CLOUDER repo. Keep all file:line citations; dedupe overlaps; add a final section "Attack surface, DB write points, spend points" summarizing across sections: (a) every unauthenticated or weakly-authorized entry point, (b) every code path that writes to Aurora, (c) every code path that spends money (vendor API calls, Aurora wakeups, log volume). Start with "# CLOUDER system map". Sections:\n\n${good.join('\n\n---\n\n')}`,
  { label: 'map:merge', phase: 'Merge' })
return { map }
```

(Barrier is correct here: the merge needs all sections.)

- [ ] **Step 2: Persist** — write the returned `map` string to `docs/reviews/2026-06-10-mvp-review/system-map.md`. Skim it: must contain all six sections plus the attack-surface summary; if a reader returned nothing, re-run with `resumeFromRunId` (cached agents replay free).

- [ ] **Step 3: Commit** — caveman-commit; suggested subject: `docs(review): add system map`.

---

### Task 4: Phase 3 — finder fan-out (Workflow)

**Files:**
- Create: `docs/reviews/2026-06-10-mvp-review/working/findings-raw.json`

- [ ] **Step 1: Run the finder workflow** — invoke `Workflow` with the script below, passing `args` as the JSON object `{ "map": "<full contents of system-map.md>" }` (read the file and pass the real string; actual JSON value, not a stringified blob).

```js
export const meta = {
  name: 'mvp-review-finders',
  description: 'Phase 3: 26 finders over the subsystem x dimension matrix',
  phases: [{ title: 'Find' }],
}
const ROOT = '/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/full_review'
const FINDINGS_SCHEMA = {
  type: 'object', required: ['findings'],
  properties: { findings: { type: 'array', items: {
    type: 'object',
    required: ['title','severity','dimension','subsystem','where','evidence','risk','recommendation','effort'],
    properties: {
      title: { type: 'string' },
      severity: { enum: ['P0','P1','P2','P3'] },
      dimension: { enum: ['SEC','DATA','COST','REL','ARCH','TEST','DOCS'] },
      subsystem: { enum: ['auth','ingest','canonicalization','curation','enrichment','data-access','migrations','infra','frontend','ci','system'] },
      where: { type: 'string' },
      evidence: { type: 'string' },
      risk: { type: 'string' },
      recommendation: { type: 'string' },
      effort: { enum: ['S','M','L'] },
    } } } },
}
const RULES = `You are a review finder for the CLOUDER repo at ${ROOT} (read-only; ignore experiments/ and docs/archive/).
Severity: P0 = exploitable security hole, data loss/corruption, or uncontrolled AWS spend; P1 = serious SEC/DATA/COST risk needing special conditions, or silent gradual corruption; P2 = reliability/correctness issue outside those dimensions; P3 = quality/drift/test gaps.
Accepted MVP behaviors — do NOT report: cold-start 503 after Aurora idle (ADR-0014); refresh-cookie replay revoking all sessions (intended, ADR-0015); min_acu=0; YouTube Music weekly re-connect in Testing mode.
Context: multi-tenant SaaS for a small DJ circle; runtime DB access is RDS Data API only (psycopg in src/collector is itself a finding); tokens (bp_token, Spotify, Google) must never be logged or persisted.
Only report what you can evidence with file:line — read the code, do not speculate. No style nits. At most 15 findings; prioritize by severity. Use the exact severity/dimension/subsystem enums.
System map for orientation:\n` + args.map
const FINDERS = [
  // 14 dedicated deep finders (the ✓✓ cells)
  { key: 'sec-auth', dim: 'SEC', sub: 'auth', focus: 'Auth & token security: JWT creation/validation and algorithm pinning, refresh rotation and replay handling, cookie flags (HttpOnly/Secure/SameSite/path), authorizer coverage of EVERY route in infra (find routes with no authorizer), secrets.py key management, token material reaching logs/responses/state. Start: src/collector/auth_handler.py, auth_authorizer.py, auth/, secrets.py, infra/auth.tf, frontend/src/auth.' },
  { key: 'sec-ingest', dim: 'SEC', sub: 'ingest', focus: 'bp_token lifecycle: every place the Beatport token is received, passed, or could leak — structlog calls, exception messages, S3 object bodies, ingest_runs rows, URLs. Verify the "never logged or persisted" invariant. Start: src/collector/handler.py, beatport_client.py, storage.py, logging_utils.py.' },
  { key: 'data-ingest', dim: 'DATA', sub: 'ingest', focus: 'Ingest integrity: S3 write atomicity (releases.json.gz + meta.json pair), partial-failure states (S3 written but SQS enqueue fails, or ingest_runs row inconsistent), re-ingesting the same week (overwrite? duplicate jobs?), snapshot completeness checks. Start: handler.py, storage.py, infra/sqs.tf.' },
  { key: 'data-canon', dim: 'DATA', sub: 'canonicalization', focus: 'Canonicalization idempotency: SQS at-least-once delivery vs upsert keys (can redelivery duplicate tracks/artists/labels/albums?), conflict targets vs real unique constraints in alembic, partial batch failure mid-message, transaction boundaries per message. Start: worker_handler.py, canonicalize.py, repositories.py, alembic/versions.' },
  { key: 'sec-curation', dim: 'SEC', sub: 'curation', focus: 'Tenant isolation: for EVERY curation route, does the handler take user_id from the authorizer context (never the payload)? IDOR on playlist/tag/triage/track ids — can user A touch user B rows? Audit every repository query for missing user_id predicates. Start: curation_handler.py, curation/, repositories.py.' },
  { key: 'data-curation', dim: 'DATA', sub: 'curation', focus: 'Playlist/curation data integrity: multi-statement mutations without a transaction, position/ordering integrity under concurrent requests, cascade behavior on delete (orphans), triage-finalize state transitions, optimistic-shrink server counterpart. Start: curation_handler.py, repositories.py, db_models.py.' },
  { key: 'cost-enrich', dim: 'COST', sub: 'enrichment', focus: 'Vendor spend: Perplexity/OpenAI/Spotify call volume — what bounds calls per track/block/week? Fan-out multiplication in auto_enrich_dispatch, retries on vendor failure (paid call in a retry loop = P0), cache hit checks BEFORE the paid call, batch sizes. Start: label_enrichment*, artist_enrichment*, auto_enrich_dispatch_handler.py, providers/, vendor_match*.' },
  { key: 'rel-enrich', dim: 'REL', sub: 'enrichment', focus: 'Silent enrichment failures: Lambda timeout is not a Python exception — find paths where timeout/crash leaves status rows stuck pending forever; dispatch worker error handling; DLQ consumers for enrichment queues (does anything alarm?); log_event dropping fields not in ALLOWED_LOG_FIELDS (logging_utils.py) hiding diagnostics. Start: auto_enrich_dispatch_handler.py, label_enrichment_handler.py, artist_enrichment_handler.py, logging_utils.py, infra/sqs.tf, infra/alarms.tf.' },
  { key: 'sec-dataapi', dim: 'SEC', sub: 'data-access', focus: 'SQL injection surface: audit every SQL string construction in data_api.py and repositories.py — all user input must travel as Data API parameters, never interpolated (f-strings/format/concat into SQL, incl. identifiers, ORDER BY, LIKE patterns, IN-list expansion). Start: data_api.py, repositories.py.' },
  { key: 'data-dataapi', dim: 'DATA', sub: 'data-access', focus: 'Transaction correctness: which multi-statement operations run WITHOUT a Data API transaction (partial-write risk)? data_api_retry.py: can a retry re-execute a non-idempotent INSERT/UPDATE (double write)? Are transaction ids handled correctly on retry? Start: data_api.py, data_api_retry.py, repositories.py.' },
  { key: 'data-migrations', dim: 'DATA', sub: 'migrations', focus: 'Migration safety: scan all 30 alembic revisions for destructive DDL (DROP/ALTER with data loss), backfills that can lose or corrupt rows, divergence between final alembic schema and db_models.py, revision graph health, migration_handler.py failure mid-migration (partial DDL, no transaction). Start: alembic/versions/, migration_handler.py, db_models.py.' },
  { key: 'sec-infra', dim: 'SEC', sub: 'infra', focus: 'Infra security: IAM wildcards (Action:* / Resource:*) per role in iam.tf and which Lambda gets what; S3 public-access blocks and bucket policies; security groups (network.tf) — anything open beyond need; API Gateway routes wired WITHOUT the authorizer; secrets/tokens in tf variables, outputs, or state. Start: infra/iam.tf, infra/s3.tf, infra/network.tf, infra/api_gateway.tf, infra/auth.tf, infra/curation_routes_*.tf.' },
  { key: 'cost-infra', dim: 'COST', sub: 'infra', focus: 'Cost controls: Aurora max ACU bound, CloudWatch log retention (never/expensive?), missing billing/usage alarms, SQS redrive maxReceiveCount vs paid-work retries, Lambda timeout×memory worst case, NAT gateway data-processing costs in network.tf, S3 lifecycle rules for raw snapshots. Start: infra/rds.tf, infra/logging.tf, infra/alarms.tf, infra/sqs.tf, infra/lambda.tf, infra/network.tf, infra/s3.tf.' },
  { key: 'test-ci', dim: 'TEST', sub: 'ci', focus: 'Test & CI gates: what does pr.yml actually gate (pytest? typecheck? eslint? openapi diff?) vs what deploy.yml assumes; critical paths with no tests (auth_authorizer, tenant isolation in repositories, data_api_retry, canonicalize conflict handling); integration tests vs moto fidelity for the Data API; tests asserting nothing. Start: .github/workflows/pr.yml, deploy.yml, tests/unit/, tests/integration/, pytest.ini.' },
  // 10 grouped finders (the remaining ✓ cells, one per subsystem)
  { key: 'grp-auth', dim: 'REL', sub: 'auth', focus: 'Auth, remaining lenses — DATA: session/refresh-token table integrity; REL: refresh error paths, clock skew, expiry races; ARCH: auth module boundaries and duplication; TEST: authorizer + handler coverage; DOCS: docs/frontend/auth.md and ADR-0005/0015 vs code. Tag each finding with its true dimension.' },
  { key: 'grp-ingest', dim: 'REL', sub: 'ingest', focus: 'Ingest, remaining lenses — COST: S3 storage growth/lifecycle, Beatport call volume per run; REL: Beatport API error/timeout handling inside the 29s gateway budget, ingest_runs stuck states; TEST: coverage of handler.py + storage.py failure paths. Tag each finding with its true dimension.' },
  { key: 'grp-canon', dim: 'REL', sub: 'canonicalization', focus: 'Canonicalization, remaining lenses — COST: per-message Aurora wakeups, batch sizing; REL: poison messages, DLQ handling, partial batch retry; ARCH: canonicalize.py vs normalize.py boundary; TEST: golden-case coverage, saturday_week.py edge years (Jan 1 = Saturday etc.). Tag each finding with its true dimension.' },
  { key: 'grp-curation', dim: 'REL', sub: 'curation', focus: 'Curation, remaining lenses — REL: error responses, partial batch ops, dispatch error swallowing; ARCH: curation_handler.py size and routing structure (route table sprawl, mixed concerns); TEST: coverage of triage-finalize and reorder logic. Tag each finding with its true dimension.' },
  { key: 'grp-enrich', dim: 'SEC', sub: 'enrichment', focus: 'Enrichment, remaining lenses — SEC: vendor API key storage/rotation (Secrets Manager vs env vars), key exposure in logs; DATA: vendor_match cache uniqueness/staleness, enrichment result overwrites; ARCH: providers/ abstraction (ADR-0004) — do all vendors actually go through it?; TEST: provider mocking fidelity. Tag each finding with its true dimension.' },
  { key: 'grp-dataapi', dim: 'REL', sub: 'data-access', focus: 'Data-access, remaining lenses — COST: chatty per-row Data API calls (N+1) waking Aurora; REL: data_api_retry.py error classification (what retries that should not, what fails that should retry); ARCH: repository-pattern leaks (SQL outside repositories.py); TEST: retry-path coverage. Tag each finding with its true dimension.' },
  { key: 'grp-migrations', dim: 'REL', sub: 'migrations', focus: 'Migrations, remaining lenses — REL: migration Lambda timeout on long DDL against a cold Aurora, ordering vs deploy (deploy.yml: migrations before or after new code?); DOCS: migration runbook accuracy vs migration_handler.py. Tag each finding with its true dimension.' },
  { key: 'grp-infra', dim: 'REL', sub: 'infra', focus: 'Infra, remaining lenses — DATA: RDS backup retention, PITR, deletion protection, final snapshot; REL: DLQs on every queue + alarms on DLQ depth, Lambda async on-failure destinations, alarm coverage of the silent-failure paths; DOCS: docs/ops/ vs actual tf. Tag each finding with its true dimension.' },
  { key: 'grp-frontend', dim: 'SEC', sub: 'frontend', focus: 'Frontend, all lenses — SEC: token storage (memory only? anything in localStorage/sessionStorage/cookies/URLs), dangerouslySetInnerHTML/XSS sinks, bp_token handling in the UI; DATA: optimistic updates without rollback on API failure; REL: unhandled API errors, 401/refresh loops, 503 cold-start UX; ARCH: api/ client layering, feature boundaries; TEST: coverage of auth + curation flows, missing browser tests for visual-critical pieces. Tag each finding with its true dimension.' },
  { key: 'grp-ci', dim: 'SEC', sub: 'ci', focus: 'CI/deploy, remaining lenses — SEC: AWS auth in deploy.yml (OIDC vs long-lived keys), secret exposure in logs, unpinned third-party actions; COST: what deploy runs on every push; REL: deploy ordering (migrations vs lambda code vs frontend), no-rollback risks; DOCS: docs/ops/deploy.md vs deploy.yml. Tag each finding with its true dimension.' },
  // 2 cross-cutting
  { key: 'arch-system', dim: 'ARCH', sub: 'system', focus: 'Whole-system architecture: dependency direction (handlers → repositories → data_api — violations?), Lambda responsibility boundaries, queue topology sanity, shared-module coupling across src/collector, the generated OpenAPI contract vs actual handlers (route table in three places — CLAUDE.md gotcha 8), what breaks first when adding a vendor or 10x users. Report structural risks as findings.' },
  { key: 'docs-drift', dim: 'DOCS', sub: 'system', focus: 'Docs/ADR drift: check each of the 20 ADRs in docs/adr/ against current code — flag any whose decision the code no longer follows; verify CLAUDE.md gotchas still true; docs/api/openapi.yaml freshness vs handlers and infra routes; stale docs/ pages. One finding per confirmed drift.' },
]
phase('Find')
const results = await parallel(FINDERS.map(f => () =>
  agent(`${RULES}\n\nYOUR CELL — subsystem: ${f.sub}, primary dimension: ${f.dim}.\nFocus: ${f.focus}`,
        { label: `find:${f.key}`, phase: 'Find', schema: FINDINGS_SCHEMA })))
const ok = results.filter(Boolean)
if (ok.length < FINDERS.length) log(`WARNING: ${FINDERS.length - ok.length} finder(s) died — list their keys before synthesis`)
const findings = ok.flatMap(r => r.findings)
log(`${findings.length} raw findings from ${ok.length}/${FINDERS.length} finders`)
return { findings, findersRun: ok.length }
```

- [ ] **Step 2: Persist + sanity-check** — write the returned `findings` array to `working/findings-raw.json`.

```bash
jq 'length, (group_by(.severity) | map({(.[0].severity): length}) | add)' docs/reviews/2026-06-10-mvp-review/working/findings-raw.json
```

Expected: total count (plausibly 60–250) and a per-severity breakdown. If `findersRun < 26`, resume the run (`resumeFromRunId`) before proceeding.

- [ ] **Step 3: Commit** — caveman-commit; suggested subject: `docs(review): add raw finder pool`.

---

### Task 5: Phase 4 — dedup + adversarial verification (Workflow)

**Files:**
- Create: `docs/reviews/2026-06-10-mvp-review/working/findings-verified.json`

- [ ] **Step 1: Merge pools and run the verify workflow** — read `working/findings-raw.json` and `working/scanner-findings.json`, concatenate into one array, and invoke `Workflow` passing `args` as `{ "findings": [ ...the merged array... ] }`:

```js
export const meta = {
  name: 'mvp-review-verify',
  description: 'Phase 4: dedup then 3-lens adversarial verification of every finding',
  phases: [{ title: 'Verify' }],
}
const ROOT = '/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/full_review'
const VERDICT_SCHEMA = {
  type: 'object', required: ['refuted','reason','severity'],
  properties: {
    refuted: { type: 'boolean' },
    reason: { type: 'string' },
    severity: { enum: ['P0','P1','P2','P3','unchanged'] },
  },
}
// ---- dedup (plain code, deterministic) ----
const norm = s => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const rank = { P0: 0, P1: 1, P2: 2, P3: 3 }
const byKey = new Map()
for (const f of args.findings) {
  const file = String(f.where).split(':')[0]
  const key = `${f.dimension}|${file}|${norm(f.title).slice(0, 60)}`
  const prev = byKey.get(key)
  if (!prev || rank[f.severity] < rank[prev.severity]) byKey.set(key, f)
}
const deduped = [...byKey.values()]
log(`dedup: ${args.findings.length} -> ${deduped.length}`)
// ---- adversarial verify ----
const LENS = {
  correctness: 'CORRECTNESS: read the cited code yourself — does it actually behave as the finding claims? Wrong line, misread logic, or a guard the finder missed means refuted.',
  impact: 'IMPACT: assume the claim is technically true — does it matter for THIS MVP (multi-tenant SaaS, small DJ circle)? Accepted behaviors (cold-start 503 ADR-0014, refresh-replay revocation ADR-0015, min_acu=0, YT weekly re-connect) mean refuted. Purely theoretical issues with no plausible trigger mean refuted.',
  repro: 'REPRODUCIBILITY: trace one concrete path that triggers it — which route/queue message/input, with which preconditions. If you cannot construct the path from real code, refuted.',
}
phase('Verify')
const verified = await pipeline(deduped,
  (f, _, i) => parallel(Object.entries(LENS).map(([name, lens]) => () =>
    agent(`You are an adversarial reviewer. Try to REFUTE this finding. Repo (read-only): ${ROOT}.\n${lens}\nIf the severity is wrong, say the correct level in "severity" (else "unchanged"). Default refuted=true when uncertain.\nFinding: ${JSON.stringify(f)}`,
          { label: `verify:${i}:${name}`, phase: 'Verify', schema: VERDICT_SCHEMA })))
    .then(votes => {
      const vs = votes.filter(Boolean)
      const keep = vs.filter(v => !v.refuted)
      const sevVotes = keep.map(v => v.severity).filter(s => s !== 'unchanged')
      const majority = sevVotes.find(s => sevVotes.filter(x => x === s).length >= 2)
      const finalSeverity = majority || f.severity
      return { ...f, severity: finalSeverity, survived: keep.length >= 2,
               votes: vs.map(v => ({ refuted: v.refuted, reason: v.reason })) }
    }))
const out = verified.filter(Boolean)
const kept = out.filter(f => f.survived)
log(`verified: ${kept.length}/${out.length} survived`)
return { all: out, survivedCount: kept.length }
```

- [ ] **Step 2: Persist** — write the returned `all` array (survivors AND refuted, with votes — the report's stats need both) to `working/findings-verified.json`.

```bash
jq '[.[] | select(.survived)] | length' docs/reviews/2026-06-10-mvp-review/working/findings-verified.json
```

- [ ] **Step 3: Spot-check 3 random refuted findings** — read their `votes[].reason`; if a refutation looks wrong (e.g. lens misunderstood the accepted-behavior list), note it for the synthesis agent rather than re-running.

- [ ] **Step 4: Commit** — caveman-commit; suggested subject: `docs(review): add verified findings`.

---

### Task 6: Phase 5 — synthesis, final artifacts, PR

**Files:**
- Modify: `docs/reviews/2026-06-10-mvp-review/report.md` (replace scaffold)
- Modify: `docs/reviews/2026-06-10-mvp-review/backlog.md` (replace scaffold)
- Modify: `docs/reviews/2026-06-10-mvp-review/scanners.md` (final pass)
- Delete: `docs/reviews/2026-06-10-mvp-review/working/`

- [ ] **Step 1: Run the synthesis workflow** — pass `args` as `{ "findings": [ ...survivors only... ], "stats": { "raw": N, "deduped": N, "survived": N, "findersRun": 26, "scannerKept": N } }` (numbers from Tasks 2–5):

```js
export const meta = {
  name: 'mvp-review-synthesis',
  description: 'Phase 5: per-dimension report sections + MVP verdict',
  phases: [{ title: 'Sections' }, { title: 'Verdict' }],
}
const DIM_NAMES = { SEC: 'Security & tokens', DATA: 'Data integrity', COST: 'AWS cost',
  REL: 'Reliability', ARCH: 'Architecture', TEST: 'Tests & CI', DOCS: 'Docs & ADR drift' }
const dims = [...new Set(args.findings.map(f => f.dimension))]
phase('Sections')
const sections = await parallel(dims.map(d => () => {
  const fs = args.findings.filter(f => f.dimension === d)
  return agent(`Write the "${DIM_NAMES[d]}" section of a code-review report (markdown, start at "## ${DIM_NAMES[d]}"). Open with a 2-4 sentence assessment of this dimension's overall health, then one "### [ID] Px — title" block per finding with Where/Evidence/Risk/Recommendation/Effort lines. Assign IDs ${d}-001.. in severity order. Findings (JSON): ${JSON.stringify(fs)}`,
    { label: `section:${d}`, phase: 'Sections' })
}))
phase('Verdict')
const p01 = args.findings.filter(f => f.severity === 'P0' || f.severity === 'P1')
const verdict = await agent(
  `You are concluding a full MVP review of CLOUDER (multi-tenant DJ-curation SaaS, small user circle). Stats: ${JSON.stringify(args.stats)}. Counts by severity: ${JSON.stringify(Object.fromEntries(['P0','P1','P2','P3'].map(s => [s, args.findings.filter(f => f.severity === s).length])))}. All P0/P1 findings: ${JSON.stringify(p01.map(f => ({ severity: f.severity, dimension: f.dimension, title: f.title, risk: f.risk })))}.
Write two markdown sections: "## Verdict" — exactly one of: **ready** / **ready with reservations** / **blockers exist** (any P0 ⇒ blockers exist; P1s in SEC/DATA/COST ⇒ at most "ready with reservations"), with a short justification naming the deciding findings; and "## Executive summary" — ≤300 words for the project owner: strongest areas, weakest areas, the fix order you recommend.`,
  { label: 'verdict', phase: 'Verdict' })
return { sections: sections.filter(Boolean), verdict, dims }
```

- [ ] **Step 2: Assemble `report.md`** — replace the scaffold: header (reviewed SHA, date, spec link, status FINAL) + returned `verdict` (Verdict + Executive summary) + all `sections` + a `## Stats` section: findings by severity and by subsystem (compute with `jq` from `findings-verified.json`), dedup/survival numbers from `stats`, finders run, scanner totals.

- [ ] **Step 3: Assemble `backlog.md`** — replace the scaffold: every survivor as `- [ ] **[ID] Px (dimension/subsystem, effort)** — title · \`where\` — recommendation`, sorted P0→P3 then by dimension, IDs matching the report. Each line must be actionable without opening the report.

- [ ] **Step 4: Cross-check IDs** — every ID in `backlog.md` appears in `report.md` and vice versa:

```bash
diff <(grep -oE '\[(SEC|DATA|COST|REL|ARCH|TEST|DOCS)-[0-9]+\]' docs/reviews/2026-06-10-mvp-review/report.md | sort -u) \
     <(grep -oE '\[(SEC|DATA|COST|REL|ARCH|TEST|DOCS)-[0-9]+\]' docs/reviews/2026-06-10-mvp-review/backlog.md | sort -u)
```

Expected: empty diff.

- [ ] **Step 5: Finalize** — mark `scanners.md` status FINAL; delete the working dir:

```bash
git rm -r docs/reviews/2026-06-10-mvp-review/working
```

- [ ] **Step 6: Commit + PR** — caveman-commit (suggested subject: `docs(review): add full MVP review report and backlog`); push branch; `gh pr create` to `main` with caveman-generated title/body. PR body: verdict line, severity counts, link to backlog.

---

## Self-review notes (done at plan-writing time)

- Spec coverage: phases 0–5 → Tasks 1–6; matrix cells → the 26-entry `FINDERS` array (14 deep + 10 grouped + 2 cross-cutting); severity model, finding schema, artifacts, accepted-behavior exclusions all embedded in prompts. Gates: Task 4 requires the Task 3 map via `args`; Task 6 consumes survivors only.
- Workflow constraint honored: scripts never touch the filesystem; the executor persists every phase's return value.
- `Date.now()`/`Math.random()` not used in any script (resume-safe).

# Full MVP review — design

**Date:** 2026-06-10
**Status:** Approved (design), pending implementation plan
**Area:** whole repository (read-only review; output under `docs/reviews/`)

## Goal

One comprehensive review of the entire repository — architecture, code, security,
data integrity, AWS cost, tests, infra, docs — to answer: **is CLOUDER stable
enough to run as an MVP, and what must be fixed first?**

Deliverable: a prioritized findings report plus a fix backlog. Fixes themselves
are explicitly **out of scope** — each backlog item is written to be self-contained
enough to hand to a separate fix session.

## Scope

In scope (the whole repo at a pinned commit SHA):

- `src/collector/` — all Lambdas, providers, data-access layer
- `frontend/src/` — SPA
- `infra/*.tf` — Terraform
- `alembic/versions/` — 30 schema migrations
- `tests/{unit,integration}` — 159 test files, plus `.github/workflows/{pr,deploy}.yml`
- `docs/` + 20 ADRs — drift against actual code

Out of scope:

- Live AWS state (no `aws` CLI calls; code-only review)
- Applying fixes
- `experiments/`, `docs/archive/`

## Risk weighting

Per the owner's priorities, three dimensions get the highest severity weight:

1. **Security & tokens** — `bp_token` / Spotify / Google token leakage, tenant
   isolation, auth flow, IAM rights, injections.
2. **Data integrity** — loss/corruption of the canonical catalogue or per-user
   playlists: ingest idempotency, migrations, transactions, DLQ handling.
3. **AWS cost** — uncontrolled spend: Aurora ACU, SQS retry storms, vendor API
   calls (Perplexity/OpenAI/Spotify), log volume.

Normal weight: correctness/reliability, architecture boundaries, test quality,
docs/ADR drift. (Availability — e.g. the known cold-start 503, ADR-0014 — is
accepted MVP behavior and weighs lower.)

## Review matrix

`✓✓` = priority cell (deep finder with the high-weight lens), `✓` = standard
finder, blank = skipped.

| Subsystem | Security | Data | Cost | Reliability | Arch | Tests | Docs |
|---|---|---|---|---|---|---|---|
| 1. Auth & tokens (`auth_handler`, `auth_authorizer`, `auth/`, `secrets.py`, `infra/auth.tf`, `frontend/src/auth`) | ✓✓ | ✓ | | ✓ | ✓ | ✓ | ✓ |
| 2. Ingest (`handler.py`, `beatport_client`, `storage.py`, S3/SQS) | ✓✓ bp_token | ✓✓ | ✓ | ✓ | | ✓ | |
| 3. Canonicalization (`worker_handler`, `canonicalize`, `normalize`, `saturday_week`) | | ✓✓ idempotency | ✓ retries | ✓ | ✓ | ✓ | |
| 4. Curation API (`curation_handler`, `curation/`, `curation_routes_*.tf`) | ✓✓ tenant isolation | ✓✓ playlists | | ✓ | ✓ | ✓ | |
| 5. Enrichment & vendors (label/artist enrichment, `vendor_match`, `spotify_*`, `providers/`, dispatch worker) | ✓ API keys | ✓ cache tables | ✓✓ Perplexity/fan-out | ✓✓ silent failures | ✓ | ✓ | |
| 6. Data-access (`data_api*`, `repositories`, `db_models`, `logging_utils`) | ✓✓ SQL injection | ✓✓ transactions | ✓ | ✓ retry | ✓ | ✓ | |
| 7. Migrations (30 alembic revisions, `migration_handler`) | | ✓✓ destructive DDL | | ✓ | | | ✓ |
| 8. Infra (19 tf files: IAM, network, RDS, SQS, alarms) | ✓✓ IAM/SG/S3 | ✓ RDS backups | ✓✓ ACU/logs/alarms | ✓ DLQ/timeouts | | | ✓ |
| 9. Frontend (api, auth, features, hooks, routes, player) | ✓ tokens/XSS | ✓ optimistic updates | | ✓ error handling | ✓ | ✓ | |
| 10. CI & deploy (`pr.yml`, `deploy.yml`) | ✓ secrets/permissions | | ✓ | ✓ | | ✓✓ coverage | ✓ |

Plus two cross-cutting agents outside the matrix:

- **Whole-system architecture** — module boundaries, dependency direction, ADR
  decisions vs. what the code actually does.
- **Docs/ADR drift** — 20 ADRs + `docs/` checked against reality.

Agent allocation: each `✓✓` cell gets a dedicated deep finder (14 cells);
each subsystem's remaining `✓` cells are grouped into one combined finder per
subsystem (~10); plus the 2 cross-cutting agents ⇒ **~26 finder agents**.

## Process phases

Each phase is a separate workflow run; the owner sees intermediate output
between phases. Executed with multi-agent orchestration (ultracode).

| # | Phase | What happens | Output | Agents |
|---|---|---|---|---|
| 0 | Setup | Skeleton of `docs/reviews/2026-06-10-mvp-review/`, pin review commit SHA | report scaffold | 0 |
| 1 | Scanners | bandit, pip-audit, pnpm audit, tsc, eslint, checkov — one-time install, run, parse | machine findings into the shared pool | 0–2 |
| 2 | System map | Parallel readers: data flows, attack surfaces, DB write points, spend points | context map for finders | ~6 |
| 3 | Finder fan-out | Matrix above; each agent gets the map + its cell(s), returns structured findings (file:line, severity, MVP risk) | raw findings pool | ~26 |
| 4 | Dedup + adversarial verify | Dedup by file/topic in plain code (not an agent); each finding attacked by 3 skeptics with distinct lenses: correctness, real impact, reproducibility. Survives at ≥2/3 votes | confirmed findings | ~3 × findings |
| 5 | Synthesis | `report.md` + `backlog.md` + appendices; commit + PR | final artifacts | ~3 |

Gates: phase 3 does not start without the phase-2 map; phase 5 consumes only
verified findings.

## Severity model

| Level | Criterion | Example |
|---|---|---|
| **P0 — MVP blocker** | Exploitable hole, data loss/corruption, uncontrolled AWS spend | another tenant reads playlists; migration drops a column without backup; infinite retry loops on a paid vendor API |
| **P1 — high** | Serious risk in a high-weight dimension but needs special conditions; or a silent failure corrupting data gradually | token logged on error path; upsert without a unique key duplicates tracks |
| **P2 — medium** | Reliability/correctness outside high-weight dimensions: broken feature, bad error UX, missing retry | unhandled 503 in the SPA; missing DLQ alarm |
| **P3 — low** | Quality: architecture drift, dead code, test gaps, stale docs | ADR contradicts code; test with no assertions |

## Finding format

Identical shape from finder output through to the backlog (illustrative
example, not a real finding):

```markdown
### [SEC-007] P1 — bp_token reaches structlog on retry error
- Where: src/collector/beatport_client.py:142
- Dimension: security · Subsystem: ingest
- MVP risk: user token lands in CloudWatch, readable by anyone with logs:Get
- Recommendation: mask the field before logging; add a test
- Effort: S · Verified: 3/3 (correctness, impact, repro)
```

ID prefix = dimension (`SEC`, `DATA`, `COST`, `REL`, `ARCH`, `TEST`, `DOCS`).
Effort: S (< 1 h), M (half a day), L (a day or more).

## Artifacts

All under `docs/reviews/2026-06-10-mvp-review/`:

- `report.md` — executive summary; MVP verdict (**ready / ready with
  reservations / blockers exist**); per-dimension sections; stats (findings by
  severity/subsystem, scanner totals, agents run).
- `backlog.md` — every confirmed finding as a checkbox item, sorted P0→P3;
  each item self-contained for a standalone fix session.
- `scanners.md` — raw scanner output (appendix).
- `system-map.md` — the phase-2 map (side value: reusable in docs later).

Committed on this branch (`full_review` worktree), delivered as a PR to `main`.

## Non-goals

- No fixes in this effort — backlog only.
- No live-AWS inspection (terraform drift, real IAM, CloudWatch) — a possible
  follow-up review.
- No new tooling permanently added to the repo; scanners install ad-hoc.

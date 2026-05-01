# Frontend iter-2a Roadmap

> **For agentic workers:** this is a META plan, not an implementation plan. It points at the per-ticket spec/plan pairs that come next. To execute one ticket, run `superpowers:brainstorming` then `superpowers:writing-plans` for that ticket if a spec doesn't already exist, or jump straight into `superpowers:subagent-driven-development` when both already do.

**Date:** 2026-05-01
**Status:** Active. A2 (bootstrap + auth + AppShell skeleton) merged in PR #29 (commit `35480c3` on `main`).
**Scope:** Map the remaining iter-2a frontend work into atomic tickets with dependencies, point at existing specs, surface tech debt that new sessions need to know about.

---

## Where we stand

| Layer | Done | Reference |
|---|---|---|
| Backend | Auth, Categories CRUD, Triage CRUD + finalize | `src/collector/*.py`, `docs/openapi.yaml` |
| Backend infra | CORS, Aurora min ACU 0.5, alarms, paths-filter CI | `infra/`, `.github/workflows/pr.yml` |
| Design | Mantine 9 handoff, all P-01..P-25 + S-01..S-10 page catalogs, component spec sheet | `docs/design_handoff/` |
| Frontend bootstrap (A2) | Vite 5 + React 19 + Mantine 9, sign-in, AppShell, 5 placeholder routes, 46 tests passing | `frontend/`, plan `2026-04-30-frontend-bootstrap.md` |

The frontend SPA boots, signs in via Spotify OAuth, persists auth across page refresh, and renders responsive AppShell with placeholders for every iter-2a destination. Each placeholder route is **the next ticket** to fill in.

---

## Ticket queue (recommended order)

Each row is a single PR. Sub-PRs allowed if a row gets too large (e.g. Triage covers 9 pages — could split into list/create/detail/finalize sub-tickets).

| # | Ticket | Pages | Backend endpoints | Existing design | Existing backend spec | Size |
|---|---|---|---|---|---|---|
| **F1** | Categories CRUD | P-09..P-12 | `GET/POST/PATCH/DELETE /categories`, reorder | `02 Pages catalog` Pass 1 | `2026-04-26-spec-C-categories-design.md` | M (3-4 days) |
| **F2** | Triage list + create modal | P-13..P-15 | `GET /triage/blocks`, `POST /triage/blocks` | `02 Pages catalog` Pass 1 | `2026-04-28-spec-D-triage-design.md` | M |
| **F3** | Triage detail (buckets + reordering) | P-16..P-19 | `GET /triage/blocks/{id}`, `POST /move`, `POST /transfer` | `02 Pages catalog` Pass 1 | spec-D | L (4-6 days) |
| **F4** | Triage finalize | P-20..P-21 + S-04 | `POST /triage/blocks/{id}/finalize` | Pass 1 + Pass 2 patterns | spec-D | S |
| **F5** | Curate desktop + mobile | P-22..P-23 | `POST /triage/blocks/{id}/move`, hotkey overlay | `03 Pages catalog` Pass 2 | spec-D + Q6 + Q7 + Q8 | L |
| **F6** | PlayerCard + sticky mini | P-24 | Spotify Web Playback SDK directly | spec sheet § PlayerCard | `2026-04-29-playback-ux-design.md`, OPEN_QUESTIONS Q5 | L |
| **F7** | Device picker | P-25 | Spotify Web API `getMyDevices`, `transferMyPlayback` | Pass 2 | OPEN_QUESTIONS Q5 | M |
| **F8** | Home / Dashboard | P-05..P-08 | `GET /styles`, `GET /categories`, `GET /triage/blocks` | Pass 1 | — (composes existing data) | M |
| **F9** | Profile / Settings (basic) | P-24 mobile profile tab | `GET /me`, `DELETE /me/sessions/{id}` | Pass 2 | spec-A | S |
| **F10** | Patterns polish + a11y audit | S-01..S-10 | — | Pass 2 | `docs/design_handoff/a11y.md` | M |

**Why this order:** F1 is the smallest CRUD with no cross-ticket dependencies. F2-F4 build the triage pipeline that Curate (F5) consumes. F6-F7 unlock playback. F8 (Home) is intentionally **last in the gameplay loop** because it composes data from F1+F3, so building it before Categories and Triage means stubs everywhere. F10 is a sweep across all completed surfaces.

If you want a vertical demo earlier, jump F1 → F8 with stubs (Coming-soon for Triage links) → then come back for F2-F4.

### Cross-cutting work (slot anywhere)

| Ticket | Why | Scope |
|---|---|---|
| **CC-1** Production deploy | The SPA only runs via `pnpm dev` today — no public URL | CloudFront + S3 + path-based routing to API GW; optional custom domain. Estimated 1 day Terraform. |
| **CC-2** Playwright E2E baseline | F1 (Categories CRUD) is the first surface that justifies E2E | One smoke test per major flow: sign-in, create category, create triage, finalize. Run against prod-staging or dev env. |
| **CC-3** Code-splitting | Bundle is 544 KB; will only grow as features land | Add `build.rollupOptions.output.manualChunks` for Mantine, Tabler, react-query separately. Land before F8 to keep Home fast. |
| **CC-4** i18n RU bundle | iter-2b deliverable; planned from day-1 | Add `frontend/src/i18n/ru.json`, mirror keys, wire toggle in F9 (Profile). |
| **CC-5** Dark theme toggle | iter-2b; tokens already in place | Mount color scheme bridge per `MANTINE_9_NOTES.md`, expose toggle in F9. |

### Phase 2 (post iter-2a)

| Ticket | Why |
|---|---|
| Isolated dev environment | When backend churn or contributor count justifies it. Two paths in `frontend/README.md` § "Future: isolated environments". |
| Layer 3 release-playlists | `2026-04-25-old-version-feature-parity-design.md` — out of iter-2a scope, nav stub already reserved. |
| Real-time updates (SSE / polling) | If multi-device usage matters. |
| Search & filtering across catalogues | When data volume becomes painful. |

---

## Quick-start: a fresh Claude Code session

When you open a new session to land ticket Fn:

1. **Sync local main:**
   ```bash
   cd /Users/roman/Projects/clouder-projects/clouder-core
   git checkout main
   git pull origin main
   ```

2. **Create a worktree for the ticket:**
   ```bash
   # use the using-git-worktrees skill or:
   git worktree add .claude/worktrees/<topic> -b feat/<topic> main
   cd .claude/worktrees/<topic>
   ```

3. **Tell Claude Code:**
   > "We're starting ticket **F1: Categories CRUD**. The roadmap is `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`. Existing design is `docs/superpowers/specs/2026-04-26-spec-C-categories-design.md`. The frontend exists at `frontend/`; it has placeholder pages, an `apiClient` wrapper, react-query, Mantine 9, i18n. Bootstrap is in `docs/superpowers/specs/2026-04-30-frontend-bootstrap-design.md` if you need context. Use `superpowers:brainstorming` to flesh out the UI design (the backend spec and design handoff already cover behaviour), then `superpowers:writing-plans` to produce the implementation plan."

4. **Per-ticket context Claude needs:**
   - The backend endpoints (`docs/openapi.yaml`)
   - The existing pages catalog HTML files (open them in a browser; Claude can also `grep` them as text since they're inlined)
   - The component spec sheet (`docs/design_handoff/04 Component spec sheet.html`)
   - OPEN_QUESTIONS.md for any unknowns the design intentionally deferred

---

## Tech debt blocking nothing today, but worth fixing soon

| # | Issue | Impact when it bites | Fix |
|---|---|---|---|
| TD-1 | `scripts/package_lambda.sh:8` invokes bare `python` | Local `terraform apply` impossible; backend Lambda config drift goes through AWS CLI workarounds | Replace with `python3` (or `.venv/bin/python` per `CLAUDE.md` gotcha). 1-line PR. |
| TD-2 | Lambda `SPOTIFY_OAUTH_REDIRECT_URI` set via AWS CLI, matches `terraform.tfvars` so next `terraform apply` is a no-op diff | Will silently revert if someone touches that var in tfvars without realising | Document in `infra/README.md` if missing; consider terraform import after TD-1 lands. |
| TD-3 | `frontend/src/theme.ts:277` carries unused `eslint-disable @typescript-eslint/no-empty-interface` | One pre-existing lint warning; cosmetic | Fix in `docs/design_handoff/theme.ts` (verbatim source) and re-copy. |
| TD-4 | Bundle 544 KB minified | Slow first paint as features grow | CC-3 above. |
| TD-5 | AuthProvider test occasionally flakes (snapshot lag race) | Red CI, false alarms | Investigate with deterministic clock + flushSync; not currently failing. |
| TD-6 | No branch protection on `main` | PRs can be merged without CI passing | One-time GitHub setting: Settings → Branches → Add rule: require status checks (`changes`, `frontend`, `tests`, `alembic-check`, `terraform`). |

---

## Constraints to remember (carry into every new session)

These are decisions that bind every future frontend ticket. Don't re-litigate them in a fresh session — they're locked.

- **React 19 + Mantine 9.** Cannot downgrade React; Mantine 9 declares React 19 peer.
- **Vite proxy + 127.0.0.1**, not `localhost`. Spotify whitelist + Lambda env both pin `127.0.0.1`. Vite `server.host: '127.0.0.1'` required.
- **No backend code changes.** All `frontend/` work assumes the existing API contract (`docs/openapi.yaml`). When the contract genuinely needs changing, that's a separate backend ticket and a separate PR — not bundled into the frontend ticket.
- **`pnpm api:types` after every backend contract change.** CI fails on drift.
- **Domain terms (NEW/OLD/NOT/DISCARD/UNCLASSIFIED/FINALIZED/BPM/key) are not translated.** Even when RU lands, these stay literal.
- **`/auth/return` is a SPA route**, not a backend route. Vite proxy must NOT include `/auth` as a prefix — list specific endpoints.
- **OAuth `code` is single-use.** Any new auth-touching code must dedupe via `useRef` (not in-effect booleans). React 18+ StrictMode WILL double-fire effects in dev.
- **`/auth/refresh` returns only tokens**, never `user`. After refresh, fetch `/me` to rebuild identity.
- **`getAuthSnapshot()` mirror must be updated synchronously** inside dispatching helpers, not via `useEffect` — that effect runs after the next render, and `requireAuth` reads the snapshot before then.
- **Refresh cookie is `SameSite=Strict`.** Same-origin only via Vite proxy with `cookieDomainRewrite: ''`.

These bullets exist because each one was a real bug fixed during A2 smoke test. The full forensic table is in `frontend/README.md` § "Smoke-test gotchas".

---

## What this roadmap explicitly is NOT

- An implementation plan. Each Fn ticket needs its own brainstorming → spec → plan cycle (or invokes the existing spec-A/C/D backend plans as input to a fresh frontend spec).
- A delivery commitment. The order is *recommended*, not mandatory; F1 → F2 → F4 → F5 → F8 → F3 is a perfectly fine reordering if the user wants to demo finalize sooner.
- A staffing plan. Solo dev today; if a contributor joins, jump to "Phase 2 → Isolated dev environment" before parallelising.

---

## Hand-off checklist (before starting a new session)

- [ ] Latest `main` pulled in the worktree directory you'll be working in
- [ ] `pnpm install` run (or `pnpm install --frozen-lockfile` if pnpm-lock.yaml hasn't drifted)
- [ ] `pnpm api:types` regenerated (backend spec may have changed since A2)
- [ ] `pnpm test` green locally (46 tests passing today)
- [ ] Spotify Developer Dashboard whitelist still includes `http://127.0.0.1:5173/auth/return`
- [ ] Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` still says `http://127.0.0.1:5173/auth/return` (re-verify after any backend deploy)
- [ ] `frontend/.env.local` set to current `terraform output -raw api_endpoint`

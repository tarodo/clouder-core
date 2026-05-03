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
| ~~**F1**~~ ✅ **Shipped 2026-05-02** | Categories CRUD + DnD reorder + read-only tracks tab | P-09..P-13 | `GET/POST/PATCH/DELETE /categories`, reorder, list-tracks | `02 Pages catalog` Pass 1 | `2026-04-26-spec-C-categories-design.md` | M — actual ~1 day session |
| ~~**F2**~~ ✅ **Shipped 2026-05-03** | Triage list + create modal + soft-delete | P-14..P-15 | `GET /triage/blocks`, `POST /triage/blocks`, `DELETE /triage/blocks/{id}` | `02 Pages catalog` Pass 1 | `2026-04-28-spec-D-triage-design.md` | M — actual ~1 day session |
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
| TD-7 | Curation Lambda CloudWatch IAM gap. Logging perms in `beatport-prod-collector-lambda-policy` did not include `/aws/lambda/beatport-prod-curation:*`. Patched ad-hoc via `aws iam put-role-policy` on 2026-05-02 to unblock F1 smoke. | Terraform drift on next `terraform apply` (will revert the manual fix). | Add the curation log-group ARN to whatever module generates the Lambda IAM policy in `infra/`. Then `terraform apply` to align state. |
| TD-8 | `SPOTIFY_OAUTH_REDIRECT_URI` Lambda env was set to API GW callback URL (Postman flow) before F1 smoke. Patched ad-hoc on 2026-05-02 to `http://127.0.0.1:5173/auth/return` (SPA flow). | Same Terraform drift — `terraform.tfvars` likely still has the old API GW URL. | Set the dev redirect URI in tfvars (or environment-specific tfvars when prod SPA deploys via CC-1). Until then, document in `infra/README.md`. |

---

## Lessons learned (post-F1, 2026-05-02)

The full F1 cycle (brainstorm → plan → 22 tasks → smoke against prod API) surfaced these non-obvious gotchas. Carry them into iter-2a F2-F10.

**Frontend / test-infra:**

1. **Node 25 ships `--experimental-webstorage`** which injects a stub `localStorage` over jsdom's. Tests that call `localStorage.clear()` blow up. Fix: prefix vitest scripts in `frontend/package.json` with `NODE_OPTIONS=--no-experimental-webstorage`.
2. **TanStack Query 5 + React 19 + `act()`.** TQ5 default `notifyManager` schedules state updates via `setTimeout(0)`. `act()` only drains microtasks; the state notification fires AFTER `act` returns, so `result.current.data` stays undefined after `await mutateAsync(...)`. Fix: `notifyManager.setScheduler(queueMicrotask)` in `src/test/setup.ts`.
3. **i18next not initialised in component tests.** `useTranslation()` returns raw keys. Fix: `import '../i18n'` once in `src/test/setup.ts` so the singleton initialises before any component test mounts.
4. **Mantine 9 components in jsdom need stubs.** `Select`/`Combobox` calls `ResizeObserver` and `Element.prototype.scrollIntoView`. jsdom doesn't ship either. Fix: stub both in `setup.ts` (one-line guards each).
5. **Mantine 9 transitions are non-deterministic in jsdom.** Modal/Menu open animations leak across `userEvent.click(...)` calls. Fix: pass `transitionProps={{ duration: 0 }}` on overlay components in test wrappers OR globally via theme.

**TanStack Query gotchas:**

6. **Multiple observers on the same `queryKey` SHARE a `queryFn`. Latest registration wins.** A passive `useQuery` with `enabled: false` and a placeholder rejecting `queryFn` (added to keep cache from GC during fake timers) will OVERRIDE the real fetch — every subsequent invalidate-driven refetch errors. Don't use that pattern. Keep cache alive in tests via `gcTime: Infinity` on the test QueryClient instead.

**Vite dev / SPA routing:**

7. **Vite proxy prefix table can shadow SPA routes.** `/categories` matches both backend endpoints AND SPA routes (`/categories/:styleId`, etc). On F5 the browser sends `Accept: text/html` and the proxy forwards JSON from API GW → blank page. Fix: per-prefix `bypass` that returns `/index.html` for `Accept: text/html` GETs; only on prefixes that have an SPA route. Backend-only prefixes (e.g. `/auth/login` redirect) must proxy unconditionally.
8. **Hooks order rule + `Navigate` early-return.** Calling `useParams` then `if (!param) return <Navigate>` then more hooks is a `react-hooks/rules-of-hooks` violation that lint catches but easy to slip in. Pattern: split into a thin guard wrapper plus an inner component that owns the hooks.
9. **`<Text component={Link}>` picks up browser default link colors** (blue / visited purple). Mantine `Text` doesn't override anchor styling. Set `c="var(--color-fg)"` and `td="none"` explicitly, or use Mantine `<Anchor>` (which respects `theme.primaryColor`).

**Auth / OAuth:**

10. **Spotify OAuth redirect URI is set in two places** that must agree: the Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` (used to build the Spotify auth URL) and the Spotify Developer Dashboard whitelist. If the Lambda env points at API GW callback (Postman flow) but the SPA expects `/auth/return` → state cookie mismatch + replay-detection cascade.
11. **Refresh-cookie replay detection is unforgiving.** Backend rotates the refresh token on each use; using the same cookie twice (e.g. via two parallel bootstrap effects) revokes ALL of the user's sessions. After replay is triggered, ONLY a fresh `/auth/login` round-trip restores the session. Cookie-clear + relogin during dev — not a code bug.
12. **AuthProvider bootstrap fires `/auth/refresh` on mount** even on the SPA login flow. With no cookie yet (first visit), it 401s — that's expected and harmless because `tokenStore.get()` returns null at that point and `notifyAuthFailure` only fires when token was present.

**Backend / infra (already in TD-7 + TD-8 above but worth restating):**

13. **Curation Lambda's CW log group was un-writable** because `beatport-prod-collector-lambda-policy` listed every Lambda log group EXCEPT curation's. Lambda still ran (zero-error metric is misleading), but every error path was invisible. Verify all new Lambdas appear in the policy when adding handlers in `infra/`.
14. **Production env mutations require explicit grant.** Sandbox blocks IAM/Lambda env changes by default; the user has to authorize each modification by name (role + policy + change). Plan accordingly when troubleshooting prod-only behaviour from a dev environment.

---

## Lessons learned (post-F2, 2026-05-03)

The F2 cycle (brainstorm → plan → 19 tasks → smoke against prod API GW) added these gotchas on top of the F1 set. Carry them into F3-F10.

**Frontend / Mantine 9:**

15. **Mantine 9 `DatePickerInput type="range"` emits `[string | null, string | null]`, not `[Date | null, Date | null]`.** TS types lie — `valueFormat="YYYY-MM-DD"` formats the display AND the emitted value. Schemas validating the tuple must accept both shapes: `z.union([z.date(), z.string().min(1)])` then `transform([new Date(a), new Date(b)])`. Discovered post-smoke when Create button silently no-op'd (Zod tuple element error landed at `dateRange.0` / `dateRange.1` paths, not `dateRange`).
16. **Mantine 9 + Floating UI `hide()` middleware on jsdom.** Popover-anchored components (`Menu` dropdown, `Combobox`, `Select`) compute `referenceHidden: true` from jsdom's zero-dimension `getBoundingClientRect`, then inject `display: none` on the dropdown — `getByRole('menuitem')` can't find items. Fix: 5th jsdom shim in `src/test/setup.ts` stubs `getBoundingClientRect` to return non-zero rect when native returns 0×0, plus non-zero `window.innerWidth/Height` and `documentElement.client*`. Documented in CLAUDE.md.
17. **Mantine form 9.x `setFieldValue` typing dropped the third options arg.** Plan code `form.setFieldValue('name', value, { validate: false })` doesn't typecheck — the only accepted option is `{ forceUpdate?: boolean }`. Just call `form.setFieldValue(key, value)` without options; if you need to skip validation, use `form.setValues` with a partial.

**Test infra:**

18. **Mantine `DatePickerInput` is undriveable in jsdom via `userEvent.type` / `fireEvent.change`.** The component is a button + popover, not a text input. For unit / integration tests, mock `@mantine/dates` at file scope: `vi.mock('@mantine/dates', () => ({ DatePickerInput: <plain input that splits ' – ' em-dash> }))`. The mock parses `'YYYY-MM-DD – YYYY-MM-DD'` and emits `[Date, Date]` directly to the form's onChange. Real DatePicker behavior is left to E2E (CC-2).
19. **`userEvent.type` + `vi.useFakeTimers()` + TQ5 + React 19 microtask scheduler is brittle.** When testing 503 cold-start auto-recovery (3 timers at t=0/+15s/+30s), prefer real timers + `waitFor` with a 3s ceiling, OR drive form input via `fireEvent.change` inside the timer-controlled block. Documented in F2 integration test comments.
20. **Mantine notifications store is global and persists across tests.** Without `notifications.clean()` in `beforeEach` / `afterEach`, toast text from a prior test can leak into the next test's `findByText` assertion window. Defensive add — cheap belt-and-suspenders.

**Architectural / refactor patterns:**

21. **Extract shared atoms BEFORE the second consumer ships, not after.** F2 needed `useStyles` + `StyleSelector` (both originally in F1's feature folder). The mid-flight D14 refactor (Tasks 1-2 of F2 plan) moved both to `frontend/src/{hooks,components}/` and rewired F1's imports in the same commit. F3-F10 should expect this dependency direction (`features/<feature>` → `components/`, `hooks/`, never to another feature).
22. **`<Navigate to="/parent" replace />` is the right "missing-param" fallback,** not `return null`. F2 Task 14 originally returned null when `:styleId` was absent, which would render a blank page on a misconfigured route. Switching to `<Navigate to="/triage" replace />` routes through `TriageIndexRedirect` and picks a style. F1's `CategoriesListPage` uses the wrapper-split pattern; either works.

**503 cold-start UX pattern:**

23. **Pure scheduler + hook adapter + sentinel error is the right shape for the cold-start auto-recovery flow.** `pendingCreateRecovery.ts` accepts `{ payload, refetchAllTabs, onSuccess, onFailure, delays? }` — no React, no QueryClient. The hook (`useCreateTriageBlock`) builds the closure and throws `PendingCreateError` on 503 so the dialog can branch on the error class. Reusable for F3 (finalize) and F4 (curate import). When a third consumer arrives, promote to `frontend/src/lib/coldStartRecovery.ts`.
24. **Match by `(name, date_from, date_to)` tuple, not by ID.** The auto-recovery scheduler doesn't have the server-assigned ID, so it polls list endpoints and matches on the deterministic tuple the user submitted. Idempotency-Key header would be cleaner but requires a backend ticket.

**Backend / infra:**

25. **OAuth Lambda `SPOTIFY_OAUTH_REDIRECT_URI` env still defaults to API GW callback after backend deploys.** TD-8 not yet permanently fixed in terraform. Symptom: `csrf_state_mismatch` on `/auth/callback` because cookie set on `127.0.0.1:5173` doesn't transmit to `*.execute-api.amazonaws.com`. Patch via `aws lambda update-function-configuration --cli-input-json` (the shorthand `--environment` syntax fights JSON-encoded env values). Re-flip after every deploy until terraform owns it.
26. **`api_endpoint` from `terraform output -raw api_endpoint` includes a trailing slash.** Strip it before writing to `frontend/.env.local` — Vite proxy target works with or without it but the trailing slash sometimes confuses path concatenation in `apiClient`.

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
- [ ] `pnpm test` green locally (91 tests passing post-F1; 46 baseline + F1 surfaces)
- [ ] Spotify Developer Dashboard whitelist still includes `http://127.0.0.1:5173/auth/return`
- [ ] Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` still says `http://127.0.0.1:5173/auth/return` (re-verify after any backend deploy)
- [ ] `frontend/.env.local` set to current `terraform output -raw api_endpoint`

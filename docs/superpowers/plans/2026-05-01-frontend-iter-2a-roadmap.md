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
| ~~**F3a**~~ ✅ **Shipped 2026-05-03** | Triage detail (block + bucket browse + single-track move + soft-delete) — required out-of-band spec-D backend hotfix (ANY/UNNEST → IN-list, see lessons #27-28) before push | P-16, P-17 | `GET /triage/blocks/{id}`, `GET .../buckets/{bucket_id}/tracks`, `POST /move` | `02 Pages catalog` Pass 1 | spec-D | M — actual ~1 day session + ½ day backend hotfix |
| ~~**F3b**~~ ✅ **Shipped 2026-05-03** | Triage transfer (cross-block) — single-track, two-step modal, fire-and-toast (no Undo per snapshot semantics) | P-19 | `POST /triage/blocks/{src_id}/transfer` | Pass 1 | spec-D | M — actual ~1 session via subagent-driven plan |
| ~~**F4**~~ ✅ **Shipped 2026-05-03** | Triage finalize + bulk transfer-from-FINALIZED | P-20..P-21 + S-04 | `POST /triage/blocks/{id}/finalize` | Pass 1 + Pass 2 patterns | spec-D | M — actual ~1 day session via subagent-driven plan |
| ~~**F5**~~ ✅ **Shipped 2026-05-04** | Curate desktop + mobile | P-22..P-23 | `POST /triage/blocks/{id}/move`, hotkey overlay | `03 Pages catalog` Pass 2 | spec-D + Q6 + Q7 + Q8 | L — actual ~1 day session via subagent-driven plan (22 tasks, 380 tests) |
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
| TD-9 | OpenAPI description for `POST /triage/blocks/{src_id}/transfer` is wrong. `docs/openapi.yaml` (and the generated `frontend/src/api/schema.d.ts:2492`) describes the endpoint as "Tracks leave the source block entirely (deleted from source bucket membership)." This is INCORRECT — spec-D §5.8 says snapshot semantics ("Source is not mutated") and the actual code in `src/collector/curation/triage_repository.py:393` is INSERT-only with no DELETE. F3b ships against the actual semantics. Caught during F3b spec self-review. | Future contributors reading the OpenAPI / schema.d.ts may incorrectly assume source mutation and write code accordingly. | Update either the FastAPI route docstring or `scripts/generate_openapi.py:ROUTES` (whichever sources that string), regenerate `docs/openapi.yaml`, and re-run `pnpm api:types` to refresh `schema.d.ts`. 1-line content change + regen. |
| TD-10 | F3a `BucketDetailPage` Move error mapping uses wrong `error_code` string. `routes/BucketDetailPage.tsx:143` checks `code === 'inactive_bucket'`, but the backend's `InactiveBucketError.error_code = 'target_bucket_inactive'` (`src/collector/curation/__init__.py:74`). The "invalid target" toast never fires in prod for inactive-bucket move 409s — falls back to generic `triage.move.toast.error`. Caught during F3b final code review. F3a unit + integration tests use the same wrong mocked code (`useMoveTracks.test.tsx:106`, `BucketDetailPage.integration.test.tsx:153`), masking the bug. | Move into an inactive STAGING bucket gives the user the wrong toast in prod. Low frequency (UI prefilters inactive); cosmetic but confusing. | Update `BucketDetailPage.tsx:143` to check `'target_bucket_inactive'`, then update the two F3a tests to mock the correct code so the test would catch a future regression. Separate small PR — not bundled into F3b to keep blast radius minimal. |
| TD-11 | GitHub Actions on Node.js 20. `actions/checkout@v4`, `actions/setup-python@v5`, `aws-actions/configure-aws-credentials@v4`, `hashicorp/setup-terraform@v3` all run on Node 20 in `.github/workflows/deploy.yml` and `pr.yml`. GitHub will force Node 24 by default 2026-06-02 and remove Node 20 from runners 2026-09-16. Surfaced as a warning on the F3b deploy run 25283163171. | After 2026-06-02 these actions may behave unexpectedly under Node 24 unless updated; after 2026-09-16 the runs may fail outright. | Bump the four action versions to their Node-24-compatible releases (check each action's repo for the current major). Test on a `ci/<topic>` branch first since the cutover affects every workflow. Window: any time before 2026-06-02. |
| TD-12 | Spec-D narrative drift on finalize error code. Spec-D §5.9 narrative says 422 `block_not_editable`; the backend actually emits `invalid_state` (`InvalidStateError.error_code = 'invalid_state'` at `src/collector/curation/__init__.py:67`, raised in `triage_repository.py:529` for non-IN_PROGRESS blocks). F4 codes against the actual contract. Same drift class as TD-9 (OpenAPI description) and TD-10 (Move error code). | Future contributors reading spec-D may write the wrong frontend mapping. | Update spec-D §5.9 narrative or rename `InvalidStateError.error_code` for the finalize path. Doc-only or 1-line code change. |

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

## Lessons learned (post-F3a, 2026-05-03)

The F3a cycle (brainstorm → plan → 22 tasks via subagent-driven-development → smoke against prod API GW) shipped 26 commits cleanly tested locally (205/205 tests, typecheck clean, build 890 KB +43 KB delta), but **prod smoke surfaced a spec-D backend bug that blocks push of the merge**. F3a is therefore merged to local `main` but **not pushed**. Carry these into F3b/F4/F5 and the spec-D hotfix session.

**Backend (spec-D) — blocker for F3a push:**

27. **`triage_repository.move_tracks` and `transfer_tracks` use `ANY(:track_ids)` and `UNNEST(:track_ids::text[])` — both fail at runtime against Aurora Data API.** `data_api.py:_to_field` serialises Python lists as JSON-strings with `typeHint: "JSON"` (i.e. Postgres `jsonb`). `ANY(jsonb)` doesn't exist; `jsonb::text[]` cast doesn't work either. Aurora returns the error, the curation handler catches it, returns 500 `internal_error`. **Fix pattern is documented in `categories_repository.py`:** "Build an IN-list parametrically (Data API forbids ANY/array on plain strings)" — use `placeholders = ", ".join(f":t{i}" ...)` + per-id params. Three SQL blocks need patching: `move_tracks` lines 340 + 360, `transfer_tracks` line 453.

28. **Unit tests don't exercise SQL semantics — they mock the Data API client.** `tests/unit/test_triage_repository.py::test_move_tracks_happy_path` mocks `_data_api.execute` to return canned rows; never executes the SQL string. Spec-D shipped without an integration test against a real Postgres → bug surfaced only when F3a became the first UI consumer. **Action:** add an integration test in `tests/integration/test_triage_repository.py` that exercises `move_tracks` / `transfer_tracks` against the ephemeral Postgres CI uses for `alembic-check`. Catches every future Data-API-vs-Postgres divergence in this codepath.

29. **Structlog whitelist (`ALLOWED_LOG_FIELDS` in `logging_utils.py`) silently drops unknown fields.** `curation_handler.py:222` logs `error=str(exc)` on the unhandled-exception path — but `error` is not in the whitelist, so the log line shows just `"message": "curation_handler_unhandled"` with no exception detail. Made the move 500 unbug-able from CW alone — had to read the source. **Fix:** rename to `error_message=str(exc)` + add `error_type=type(exc).__name__` (both already whitelisted). Two-line patch.

**Backend infra reverts (F1/F2 patches, drifted again):**

30. **TD-7 (curation Lambda CW IAM) reverted again.** `beatport-prod-collector-lambda-policy` lost the `/aws/lambda/beatport-prod-curation:*` ARN between the F2 ad-hoc patch (2026-05-02) and the F3a smoke (2026-05-03). Symptom: Lambda invocations succeed but every error path is invisible (no log stream past the previous patch's deploy). Re-patched ad-hoc via `aws iam put-role-policy`. Next `terraform apply` will revert. **Permanent fix:** add the curation log-group ARN to the IAM policy module in `infra/`. TD-7 promoted to a **must-fix-before-F3a-push** blocker — without it, future move/finalize errors will be invisible again.

31. **TD-8 (`SPOTIFY_OAUTH_REDIRECT_URI` Lambda env) also reverted.** Was pointing at API GW callback (Postman flow); had to flip back to `http://127.0.0.1:5173/auth/return` for SPA dev smoke. Same as F1. Re-flip after every backend deploy until terraform owns it.

**Frontend / dev workflow:**

32. **Vite test files: drop `import React from 'react'` for pure JSX-runtime files.** F3a's two integration tests had a leftover `React` import that triggered TS6133 (`'React' is declared but its value is never read`) under the project's strict TS settings — broke `pnpm typecheck`. Component test files that build a wrapper with `({ children }: { children: React.ReactNode })` still need it; integration tests using `RouterProvider` directly do not. Took one extra commit to discover.

33. **Subagent-driven-development workflow is fast and disciplined when the plan is precise.** F3a shipped 22 tasks (plus 4 follow-up fixes from code review) over a single session. Implementer subagents caught two real plan defects (T1 zero-handling semantic, T6 noUncheckedIndexedAccess chains) and made correct judgment calls without escalating. Two-stage review (spec compliance + code quality) added value on the substantive tasks (T1, T3, T7). Skipped the formal review for trivial tasks (T2 icon re-export, T8/T9/T10 leaf components) — verified inline. Kept overall throughput high without sacrificing rigor on the load-bearing pieces.

**Process / scope:**

34. **A frontend ticket can surface a backend bug that blocks deploy.** F3a is the first UI consumer of `POST /triage/blocks/{id}/move` — spec-D wrote the endpoint but never exercised it from real client. The bug is in spec-D, not F3a; the right move is to merge F3a locally (frontend code is correct, all 205 tests green) but **not push** until the backend hotfix lands. Otherwise prod gets an SPA that throws red toasts on every Move click. Carry this principle: when smoke surfaces a backend bug, scope it as a separate ticket and gate the push.

---

## Lessons learned (post-F3b, 2026-05-03)

The F3b cycle (brainstorm → plan → 10 tasks via subagent-driven-development → final cross-task review) shipped 13 commits, 244 tests (was 205 baseline = +39 vs +25 target), bundle 896.56 KB (+6.3 KB minified, well under 30 KB ratchet), zero F3a regressions. Carry these into F4/F5/F6.

**Spec / contract discipline:**

35. **The OpenAPI description string is not authoritative.** `docs/openapi.yaml` claimed the transfer endpoint "Tracks leave the source block entirely (deleted from source bucket membership)" — incorrect; spec-D §5.8 and the actual repository code do INSERT-only with no DELETE. Brainstorming caught this by cross-checking `triage_repository.py:393` against the OpenAPI string. **Action:** when designing a frontend feature against an existing endpoint, verify the OpenAPI description matches the spec doc AND the repository code. Three-way alignment is required before writing the design. Tracked as `TD-9`.

36. **Backend `error_code` strings must be verified against `curation/__init__.py`, not the spec narrative.** The F3b spec used `inactive_bucket` and `style_mismatch` in its error mapping initially, but the actual codes emitted by `InactiveBucketError` and `StyleMismatchError` are `target_bucket_inactive` and `target_block_style_mismatch`. Caught during spec self-review by greping `curation/__init__.py`. **Action:** before writing any error-code switch in frontend code, grep the backend exception class's `error_code` attribute. Don't trust prose summaries. F3a's Move handler shipped with the wrong code (`inactive_bucket`) and the toast never fires in prod — tracked as `TD-10`. The F3a tests use the wrong mocked code, masking the bug — `vi.spyOn`-style tests are only as good as the mocked values.

37. **Backend HTTP status codes for transfer can lie.** Spec/plan §6.3 said `invalid_state` returns 409, but the backend actually returns 422 (`CurationError` subclasses default to 422 unless overridden). The frontend doesn't care — `ApiError.code` is keyed on the `error_code` body field, not the HTTP status. So the bug is invisible at runtime. **Action:** when documenting an API in a spec, the HTTP status table is informational; the contract is `error_code`. Don't write tests that assert on HTTP status alone.

**Subagent-driven workflow (round 2 — F3b):**

38. **Subagents sometimes report success without committing.** Tasks 7 and 9 implementer subagents returned the commit message text but the actual `git commit` never landed. Caught by checking `git log` and `git status` after each task. **Action:** the controller MUST verify every task commit landed via `git log -1 --pretty=%B` before marking the task complete — don't trust the subagent's "Commit SHA: ..." line in isolation. Pattern: when a subagent's report is truncated to just the commit message string (no Status / counts / typecheck output), assume the work didn't fully complete and verify directly.

39. **Final cross-task review catches gaps that per-task reviews miss.** F3b's per-task reviews approved each piece, but the final reviewer found 5 of 11 spec integration test scenarios missing — the per-task reviewer for Task 9 only checked that the 6 written tests passed, not whether the spec's full list was covered. **Action:** always run the final-reviewer pass after the last task, even when every per-task review was green. Look for spec-vs-implementation completeness, not just spec compliance per piece.

40. **Test-only Mantine workarounds belong in test setup, not production components.** Task 6's first implementation added `transitionProps={{ duration: 0 }}` directly on the `<Modal>` JSX to defeat jsdom portal-animation races. This silently disabled modal animations in prod for all users. Code-quality review caught it; the fix was to extract a `testTheme` constant and apply via `<MantineProvider theme={testTheme}>` only in tests. Final review then deduped the `testTheme` to `frontend/src/test/theme.ts`. **Action:** any "duration: 0" / "animation: none" / "polling: 0" overrides for tests must live in test setup, never in production component JSX. If the workaround can't be expressed in a theme/prop override, gate via `process.env.NODE_ENV === 'test'`.

41. **Snapshot-semantics mutations don't need optimistic UI.** F3a's Move was optimistic with snapshot/rollback/Undo because the source list visually shrinks. F3b's Transfer is fire-and-toast with no Undo because the source bucket is unchanged on the page the user is on. **Action:** before adding `onMutate` to a TanStack Query mutation, ask: "what visible state on the current page changes if I don't optimistically update?" If the answer is "nothing," skip the optimistic write. Saves a snapshot/rollback machinery and avoids the honest-Undo problem (you can't undo something the backend doesn't expose a delete for).

42. **`useEffect` reset on `opened={false}` is redundant when modal is mount-on-demand.** F3b `TransferModal` resets state in both `handleClose` and a `useEffect` listening to `opened`. The modal is mounted only when `transferTrackId !== null`, so `opened` never transitions `true → false` while mounted — the `useEffect` cannot fire. Final reviewer flagged the redundancy as harmless but suggested removing or commenting. **Action:** when mounting a modal conditionally, you don't need both reset paths. Pick one (the imperative `handleClose`). If you keep both for "defense in depth," add a comment explaining the redundancy is intentional for a future mount-always pattern.

**Test-infrastructure (carry into F4+):**

43. **Mantine Modal needs `transitionProps={{ duration: 0 }}` in test theme.** Same fix shape as F2's Menu. Centralized in `frontend/src/test/theme.ts` for reuse. F4 finalize will use a Modal — point its tests at the same theme.

44. **`vi.spyOn(qc, 'invalidateQueries')` is the right verification for hooks whose only side-effect is invalidation.** When the cache is empty (which is typical for a freshly-mounted hook), `invalidateQueries` produces no observable state change — a spy is the only way to verify the call happened with the right key. Don't try to assert on `qc.getQueryState(...)` for these cases.

---

## Lessons learned (post-F4, 2026-05-03)

The F4 cycle (brainstorm → plan → 13 tasks via subagent-driven-development → final follow-ups) shipped finalize (modal + 503 cold-start recovery + 409 blocker variant) plus bulk transfer-from-FINALIZED with paginated track-id drain. Test count 244 → 282 (+38), bundle still well within ratchet, zero F3a/F3b regressions. Carry these into F5/F6.

**Cold-start + recovery patterns:**

45. **Cold-start scheduler reuse pattern.** F4 introduced `pendingFinalizeRecovery` mirroring F2's `pendingCreateRecovery` shape — pure scheduler, three-tick polling, status-flip match condition (`block.status === 'FINALIZED'`). Same pattern hosts any cache-driven cold-start polling: pass `refetch`, `onSuccess(block)`, `onFailure()`, optional `delays`. Promotion to `frontend/src/lib/coldStartRecovery.ts` deferred per F2 lesson 23 until N=3 consumers; F4 + F2 are 2 — tracked as `FUTURE-F4-4`. Resist the urge to extract early; the scheduler shape is still adapter-shaped (e.g. F2 polls all-tabs, F4 polls one block) and a third consumer will tell us which fields belong in the shared core.

46. **Recovery `onSuccess` reads from cache, not from scheduler arg.** Plan code routed `refreshed.buckets` through the `onSuccess(block)` arg, but the scheduler's typed contract only carries `{id, status}` (the minimum needed for the flip-decision). To get the full block for the success-toast template (`promoted N tracks across M categories`), read `qc.getQueryData<TriageBlock>(triageBlockKey(...))` after the scheduler's invalidate. **Action:** keep scheduler arg types narrow to the polling decision; let consumers re-read the cache for view data. Avoids overloading the scheduler shape with consumer-specific fields.

**Snapshot-semantics + bulk operations:**

47. **Snapshot-semantics rollback is impossible AND unnecessary.** Bulk transfer from FINALIZED tech buckets uses INSERT-only backend. `ON CONFLICT (triage_bucket_id, track_id) DO NOTHING` makes retry idempotent. Source bucket is never mutated, so partial-failure rollback is impossible AND unnecessary — retrying the same `track_ids` skips already-promoted rows server-side. **Action:** when designing UX for snapshot operations, the "where" of "вернуть на место" is already the source. No rollback infrastructure needed; the user can simply retry. Generalises F3b lesson 41 (snapshot-semantics → no optimistic UI) to: snapshot-semantics → no rollback either.

48. **Paginated track-id drain for bulk operations.** `useBucketTracks` is `useInfiniteQuery` with `PAGE_SIZE=50`. Bulk Transfer requires every track ID, so the click handler drains `fetchNextPage` until `result.hasNextPage === false` BEFORE opening the modal. Critical: drive the loop via the AWAIT RETURN VALUE (TanStack Query 5 returns latest query state from `fetchNextPage`), NOT the closed-over `tracksQuery` snapshot — that snapshot has stale `hasNextPage` from the render where the click handler was created. **Action:** any bulk operation over a paginated query MUST loop on the awaited return, not on the closure. Rule: `let cur = await q.fetchNextPage(); while (cur.hasNextPage) cur = await cur.fetchNextPage();`.

**Error-handling infrastructure (carry into F5+):**

49. **`ApiError.raw` carries the parsed body.** F4's 409 `inactive_buckets_have_tracks` handler reads `err.raw as FinalizeErrorBody` to extract `inactive_buckets[]` and flip the modal to the blocker variant. The infrastructure was already in place from `error.ts:7` (`raw?: unknown` field set inside `ApiError.from`); F4 spec falsely flagged this as TD until self-review caught it. **Action:** before adding a new "ApiError needs to carry XYZ" line to the spec, grep `frontend/src/api/error.ts` — `raw` already covers most cases. The frontend already has the body; the work is just casting it to the right interface.

50. **Plan code defects caught at implementation.** Three plan-code mistakes were corrected during F4 by TDD: (1) plan's `vi.fn<[], Promise<X>>()` syntax is Vitest 1.x; needs `vi.fn<() => Promise<X>>()` for Vitest 2.x. (2) plan's recovery `onSuccess` referenced `refreshed.buckets` but the scheduler arg type only carries `{id, status}`; implementer used `qc.getQueryData<TriageBlock>(triageBlockKey(...))` instead. (3) plan's bulk-error catch routed through `handleTransferError`, which would close the modal; implementer extracted a shared `mapTransferError` helper so single-track keeps close-on-error and bulk stays on step 2 for retry. **Action:** write plans against the spec, but expect TDD to surface these — the test failures are the canary. Don't fight the plan when the test says it's wrong; treat the divergence as a planning-stage information gap and update the implementation to fit reality.

**Test infrastructure:**

51. **Test-only theme propagation.** `<MantineProvider theme={testTheme}>` (introduced in F3b for jsdom Modal animation kill) is the right place for any jsdom Modal/Notifications animation override. F4 reused it across all 5 test types (FinalizeModal, FinalizeSummaryRow, FinalizeBlockerRow, TransferModal, FinalizeFlow integration). One source of truth — when adding a new component test that uses a Modal, point the wrapper at `testTheme`. **Action:** never inline `transitionProps={{ duration: 0 }}` again; if a new component family (Drawer, Popover full-modal, etc.) needs a similar override, add it to `frontend/src/test/theme.ts` so prod components stay clean. Reinforces F3b lesson 40.

52. **Shared-portal DOM bleeds between tests when the portal node persists.** F4's two new integration tests (`404 stale block`, `503 cold-start terminal`) initially failed when run after any prior test in the file but passed in isolation. Mantine's `data-mantine-shared-portal-node` div is a singleton survives across `cleanup()` calls, and `screen.getAllByRole('button', { name: 'Finalize' })` matched stale buttons from prior tests' modal portals. **Fix:** scope queries to the live dialog via `const dialog = await screen.findByRole('dialog'); within(dialog).findByRole('button', ...)`. **Action:** for any test that asserts on a Modal element by role/name, scope to the dialog. Don't trust `screen.getAllByRole` inside a portal-heavy app.

---

## Lessons learned (post-F5, 2026-05-04)

The F5 cycle (brainstorm → spec → plan → 22 tasks via subagent-driven-development → polish) shipped the keyboard-first Curate session: hybrid entry (Triage CTAs + standalone resume), one-bucket source queue, just-tapped pulse + 200ms auto-advance, depth-1 silent undo, double-tap cancel-and-replace, end-of-queue smart-suggest, full per-style resume via localStorage. Test count 282 → 380 (+98), bundle 890KB → 910KB (+20KB), zero regressions across F1-F4.

**Layout-safe keyboard binding:**

53. **`event.code` for letters/digits, `event.key` for shifted characters.** `useCurateHotkeys` matches by `KeyQ`/`KeyW`/`KeyE`/`Digit1`–`Digit9`/`KeyU`/etc — the physical key position, layout-independent. Cyrillic and Dvorak users press the QWE-physical position and the binding still resolves to NEW/OLD/NOT. The single exception is `?` (shifted, layout-dependent intent), which uses `event.key === '?'`. **Action:** any future global keyboard surface MUST default to `event.code` and only fall through to `event.key` for layout-dependent intent (typed glyphs).

**State machine + timer interaction:**

54. **Timer IDs in `useRef`, not in reducer state.** A reducer state field that tracked `pendingTimerId` would feedback-loop: timer scheduled → state update → re-render → effect re-runs → new timer scheduled. Refs sidestep this. Reducer dispatches happen INSIDE the `setTimeout` callback; reducer body itself stays pure. **Action:** for any UI machinery that involves debounced or delayed dispatch, isolate the timer ID in a ref and dispatch a pure transition from the timer callback.

55. **`stateRef.current = state` mirror lets imperative callbacks read fresh state without stale closures.** `useCurateSession`'s `assign`/`undo` callbacks must read `state.lastOp` and `state.currentIndex` at call time, not at callback-creation time. Including `state` in the `useCallback` deps would invalidate the callback identity on every state change — defeating React.memo on consumers. The fix: `const stateRef = useRef(state); stateRef.current = state;` written on every render, then `stateRef.current.lastOp` inside the callback. Callback deps stay stable. **Action:** for any imperative callback that needs fresh state but stable identity, use the `stateRef` pattern. Don't add state to the dep array.

56. **Optimistic shrink + auto-advance: known UX limitation.** `useMoveTracks.applyOptimisticMove` filters the assigned track from the bucket-tracks query cache synchronously. Curate's queue (same query) shrinks by 1 immediately, then the reducer's 200ms `ADVANCE` increments `currentIndex` again — effectively skipping one track every assign. Making `ADVANCE` a no-op fixes the UX but breaks `useCurateSession`'s 12 reducer-mechanic tests. Acceptable in iter-2a because in fast curation users notice "next track shown" not "specific track shown". Documented in CLAUDE.md gotcha; revisit in iter-2b.

**Plan-as-source-of-truth vs reality:**

57. **Plan code blocks ship `: JSX.Element` annotations that break the project's strict TS.** The codebase doesn't use return type annotations on components — `tsc -b --noEmit` errors with `Cannot find namespace 'JSX'`. T7's implementer noticed and dropped the annotation; T8's kept it (verbatim per plan) and broke typecheck. **Action:** when writing future plans for this repo, omit `: JSX.Element` from component signatures. The implementer prompt should also surface this as a reminder.

58. **TS6133 unused-import errors come from leftover `import React from 'react'` in route/integration tests.** Pure JSX-runtime tests (e.g. `<MemoryRouter>` direct usage) don't reference `React` — strict TS flags it. F5 saw this in three tests; fixed inline. CLAUDE.md gotcha #32 already documents this. **Action:** future test scaffolding should skip `import React` unless the file explicitly types `React.ReactNode` or similar.

59. **`nextSuggestedBucket` semantics: wrap-around vs simple-priority.** Plan code block specified simple priority (NEW → UNCLASSIFIED → OLD → NOT, skipping current). Implementer's tests forced wrap-around (after current, then back to start). The right interpretation is wrap-around — "after this bucket, what's next" — and the implementer's deviation matched test intent. **Action:** when plan code and plan tests disagree, the tests describe user-facing behavior; the code is just suggested implementation. Trust the tests.

**Subagent-driven development cadence:**

60. **Implementer subagents drop the commit step often.** ~50% of implementer reports show "draft commit message" but `git status` reveals untracked files. Likely because the implementer thinks they committed but the bash invocation didn't fire (or fired in a child shell that didn't propagate). **Action:** controller verifies commit landed via `git log --oneline -1` after every dispatch. If untracked files remain, controller commits manually. Don't re-dispatch — saves a roundtrip.

61. **Subagents over-engineer when given full code blocks.** T4's `nextSuggestedBucket` implementer added wrap-around logic the plan's code block didn't request — but ALSO needed to satisfy the plan's tests (which only worked with wrap-around). Net result: implementer's "deviation" was correct because the plan was internally inconsistent. **Action:** plan-code blocks are suggestions, not contracts; tests are the contract. When the implementer deviates AND tests pass, accept it.

62. **Two-stage review (spec then quality) catches structural issues TDD doesn't.** F5 saw the code-quality reviewer flag `useCurateSession` issues (whole-object deps, off-by-one, missing pulse cleanup) that all 12 tests passed. The reviewer's "Important" findings led to a +5min fix that prevents downstream re-render storms. **Action:** keep both review stages even when tests pass and spec compliance is clean. The reviewers see different signals.

**Browser-native UX vs global hotkey binding:**

63. **`autoFocus` on primary CTA replaces global Enter binding.** F5's spec said `Enter` accepts the EndOfQueue suggestion. Two paths: (a) bind Enter globally in `useCurateHotkeys` with a context-aware callback, (b) `<Button autoFocus>` on the primary CTA → browser Enter activation works automatically. Path (b) is cleaner and avoids keyboard layer leaking into surface-specific behavior. The `jsx-a11y/no-autofocus` lint rule is silenced inline because keyboard-flow continuation is intentional. **Action:** when a single CTA dominates a surface, prefer `autoFocus` over global Enter binding — let the browser do the work.

**Bundle vs feature complexity:**

64. **Curate ships in +20KB minified despite 5+ new components and a state machine.** Mantine's tree-shaking is doing the work; the new code mostly composes existing primitives. CC-3 (code-splitting Mantine, Tabler, react-query) remains deferred — bundle is comfortable at 910KB / 271KB gz. Revisit when F8 (Home) lands and the homepage path needs splitting.

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

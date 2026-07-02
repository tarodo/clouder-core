# Analytics v2 — Frontend Dashboard Implementation Plan (Plan 4 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. `- [ ]` checkboxes.

**Goal:** Replace the five old admin analytics dashboards (triage/taste/funnel/playback/ops) with a single **per-user daily** view over the new `mart_user_daily` + `fact_session` routes: pick a user + date range, see per-day × activity_type session counts, averages, and duration / time-per-track percentiles, with a drill-down to that range's sessions.

**Architecture:** Regenerate the OpenAPI-typed client (`schema.d.ts`) from the Plan-3 openapi, rewrite the `useAnalytics` hook into `useUserDaily` + `useSessions`, and rebuild `AdminAnalyticsPage` as a user-id + date-range form driving a Mantine table (+ a sessions/day line chart) and a sessions drill-down table. Delete the old 5-dashboard config.

**Tech Stack:** React 19, Mantine 9 (`@mantine/core`, `@mantine/charts`), TanStack Query, `openapi-typescript`, Vitest.

**Plan series:** Plans 1-3 (backend) DONE. This is Plan 4, the last feature plan. Plan F (beatport→clouder rename) is separate/risky. Spec: `docs/superpowers/specs/2026-06-30-analytics-v2-user-daily-design.md`.

**Worktree:** branch `feat/analytics-v2`. Frontend commands run from `frontend/`. **Verify visual changes in a real browser** (gotcha #11 / the "verify visual in browser" rule): `pnpm test:browser` if the harness runs here; jsdom (`pnpm test`) applies no styles.

---

## Backend contract (already shipped)

- `GET /v1/analytics/user-daily?user_id=&from=&to=` → `{ "user-daily": [ {user_id, activity_type, dt, sessions, avg_tracks_listened, avg_tracks_promoted, avg_tracks_deleted, p50_duration_ms, p90_duration_ms, p50_time_per_track_ms, p90_time_per_track_ms}, ... ], correlation_id }`.
- `GET /v1/analytics/sessions?user_id=&from=&to=` → `{ "sessions": [ {user_id, activity_type, dt, session_seq, ts_start, ts_end, duration_ms, tracks_listened, tracks_promoted, tracks_deleted}, ... ], correlation_id }`.
- Both admin-only; numeric columns arrive as strings (Athena result rows are stringified — coerce in the UI). `avg_*` and `tracks_*` are NULL for `playlist`.

---

## File Structure

| File | Action |
|---|---|
| `frontend/src/api/schema.d.ts` | Regenerate (`pnpm api:types`) |
| `frontend/src/features/admin/hooks/useAnalytics.ts` | Rewrite → `useUserDaily` + `useSessions` |
| `frontend/src/features/admin/lib/dashboards.ts` | Delete (5-dashboard config obsolete) |
| `frontend/src/features/admin/components/AnalyticsDashboard.tsx` | Replace → `UserDailyTable` + `SessionsTable` |
| `frontend/src/features/admin/routes/AdminAnalyticsPage.tsx` | Rewrite (user_id + range form) |
| `frontend/src/features/admin/**/*analytics*.test.tsx` | Rewrite |
| i18n locale file(s) (`admin.analytics.*`) | Swap old dashboard keys for new column labels |

---

### Task 1: Regenerate the typed client + rewrite the hooks

**Files:** `frontend/src/api/schema.d.ts`, `frontend/src/features/admin/hooks/useAnalytics.ts`, delete `frontend/src/features/admin/lib/dashboards.ts`

- [ ] **Step 1: Regenerate schema types**

Run: `cd frontend && pnpm api:types`
Then confirm the new paths exist: `grep -E "analytics/(user-daily|sessions|triage)" src/api/schema.d.ts` → shows `user-daily` and `sessions`, NOT `triage`. (CLAUDE.md gotcha #8: CI diff-checks this file against `docs/api/openapi.yaml` — it must be regenerated, not hand-edited.)

- [ ] **Step 2: Write the hooks**

Rewrite `useAnalytics.ts` to:
```ts
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { paths } from '../../../api/schema';

export type UserDailyResult =
  paths['/v1/analytics/user-daily']['get']['responses'][200]['content']['application/json'];
export type SessionsResult =
  paths['/v1/analytics/sessions']['get']['responses'][200]['content']['application/json'];

export interface AnalyticsRange { from: string; to: string; }

export function useUserDaily(userId: string, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', 'user-daily', userId, range.from, range.to],
    queryFn: () =>
      api<UserDailyResult>(
        `/v1/analytics/user-daily?user_id=${encodeURIComponent(userId)}&from=${range.from}&to=${range.to}`,
      ),
    enabled: userId.trim().length > 0,   // don't fire until a user is chosen
    staleTime: 60_000,
  });
}

export function useSessions(userId: string, range: AnalyticsRange) {
  return useQuery({
    queryKey: ['admin', 'analytics', 'sessions', userId, range.from, range.to],
    queryFn: () =>
      api<SessionsResult>(
        `/v1/analytics/sessions?user_id=${encodeURIComponent(userId)}&from=${range.from}&to=${range.to}`,
      ),
    enabled: userId.trim().length > 0,
    staleTime: 60_000,
  });
}
```
Adjust the exact `api<T>()` call form to match the existing `api` client signature (read `frontend/src/api/client.ts`). If `paths[...]['application/json']` typing is awkward because the payload key is `"user-daily"` (a hyphen), define a hand-written row interface instead and type the hook return as `{ "user-daily": UserDailyRow[] }` — keep it typed, don't use `any`.

- [ ] **Step 3: Delete the obsolete dashboards config**

`git rm frontend/src/features/admin/lib/dashboards.ts` (its 5-dashboard/panel/chart spec is replaced by the fixed per-user table). Any test importing it is rewritten in Task 2.

- [ ] **Step 4: Typecheck** (will fail until Task 2 updates consumers — that's expected; just confirm the hook file itself has no type errors by reading tsc output). Do NOT commit yet — commit at the end of Task 2 so the tree is never broken.

---

### Task 2: Rebuild the page + components + i18n + tests

**Files:** `AdminAnalyticsPage.tsx`, `AnalyticsDashboard.tsx` (replace), i18n locale(s), tests

- [ ] **Step 1: Write the component tests (TDD)**

Rewrite the analytics component/page tests (delete the old panel/chart-spec tests). Cover, with a mocked hook (`vi.mock('../hooks/useAnalytics')`):
1. Empty state: no `user_id` entered → prompt to pick a user, no fetch.
2. `user-daily` rows render a table: given rows for `triage`/`category`/`playlist`, the table shows `dt`, `activity_type`, `sessions`, the three averages, and the four percentiles; playlist's NULL averages render as an em-dash (`—`), not `null`/`NaN`.
3. Numeric coercion: a `p50_duration_ms` arriving as the string `"120000"` renders as a number/duration, not the raw string.
4. Sessions drill-down: rows render one line per session with `ts_start`/`duration_ms`.

Match the repo's test wrapper (MantineProvider + i18n + QueryClient) — reuse whatever the existing analytics test used.

- [ ] **Step 2: Run → fail.** `cd frontend && pnpm test analytics`

- [ ] **Step 3: Rebuild the components**

Replace `AnalyticsDashboard.tsx` with two focused components (or one file exporting both):
- `UserDailyTable({ userId, range })`: calls `useUserDaily`; renders a Mantine `Table` (one row per `dt`×`activity_type`) with columns: Date, Activity, Sessions, Avg listened, Avg promoted, Avg deleted, p50/p90 duration (formatted ms→`m:ss` or seconds), p50/p90 time-per-track. Coerce string numerics via `Number(...)`; render NULL/undefined as `—`. Optionally a `@mantine/charts` `LineChart` of `sessions` per `dt` (one line per activity_type) above the table. Handle loading (`<Loader/>`) and error (`<Alert/>`) states like the old component did.
- `SessionsTable({ userId, range })`: calls `useSessions`; a `Table` of sessions (Date, Activity, #, Start, Duration, Listened, Promoted, Deleted), NULLs as `—`.

Rewrite `AdminAnalyticsPage.tsx`: keep the from/to date inputs, ADD a `user_id` text input (`aria-label` via a new i18n key `admin.analytics.user_id`); state drives `useUserDaily`/`useSessions`. Render `UserDailyTable` then `SessionsTable`. When `user_id` is empty, show a dimmed "pick a user" prompt (i18n `admin.analytics.pick_user`) instead of the tables.

> ponytail: a free-text `user_id` input is the MVP (admin knows the ids). A user picker (dropdown of known users) is a follow-up — no user-list endpoint exists yet; do not build one here.

- [ ] **Step 4: i18n** — In the locale file(s) under `frontend/src` (grep `admin.analytics.title` to find them), REMOVE the obsolete per-dashboard keys (`admin.analytics.{triage,taste,funnel,playback,ops}.*`) and ADD the new ones used above: `admin.analytics.user_id`, `admin.analytics.pick_user`, and column headers (`admin.analytics.col.date/activity/sessions/avg_listened/avg_promoted/avg_deleted/p50_duration/p90_duration/p50_tpt/p90_tpt/…`). Keep `admin.analytics.title`, `.subtitle`, `.from`, `.to`, `.empty`. Update every locale that has the old keys (grep to enumerate).

- [ ] **Step 5: Run tests → pass.** `cd frontend && pnpm test analytics`

- [ ] **Step 6: CI gates (gotcha: vitest alone misses tsc/eslint)**
Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test analytics`
All PASS. Fix any type/lint fallout (e.g. remaining imports of the deleted `dashboards.ts` or old hook exports).

- [ ] **Step 7: Browser check (if the harness runs here)**
Run: `cd frontend && pnpm test:browser` (if present/runnable). If it can't run in this environment, note that visual verification is pending a real browser. Do NOT block the task on it.

- [ ] **Step 8: Commit**
```bash
git add -A frontend
git commit -m "$(cat <<'EOF'
feat(admin): per-user daily analytics dashboard

Replace the 5 dbt-era dashboards with a user-id + date-range view
over mart_user_daily / fact_session: per-day×activity session counts,
averages, duration + time-per-track percentiles, sessions drill-down.
Regenerated schema.d.ts from the new OpenAPI.
EOF
)"
```

---

### Task 3: Refresh graphify + verify

- [ ] **Step 1:** `cd frontend && pnpm typecheck && pnpm lint && pnpm test` (full frontend suite) → PASS. Then backend `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q` → PASS (unchanged).
- [ ] **Step 2:** Confirm no dangling refs to the old dashboards: `grep -rnE "DASHBOARDS|DashboardName|'triage'|dashboards" frontend/src/features/admin | grep -viE '\.test\.'` → nothing referencing the deleted config.
- [ ] **Step 3:** `graphify . --update` (doc-key error non-fatal), `git add -A graphify-out`, commit if changed:
```bash
git commit -m "$(cat <<'EOF'
chore(graphify): refresh graph after analytics frontend
EOF
)"
```

---

## Self-Review

**Spec coverage:** delete 5 old dashboards (Part E) → Tasks 1 (config) + 2 (page/component/i18n). Per-user daily view with user selector + date range + the mart metrics + sessions drill-down (Part E / Dashboard #1) → Task 2. Typed client regen (gotcha #8) → Task 1. Browser verification (gotcha #11) → Task 2 Step 7.

**Type/name consistency:** `useUserDaily`/`useSessions` (Task 1) are the only hooks the new components import (Task 2). `dashboards.ts` deletion (Task 1) is matched by removing its importers (Task 2 tests + the replaced component). Payload keys `"user-daily"`/`"sessions"` match the backend route names exactly.

**Risks:** Athena returns all columns as strings — the UI MUST coerce (`Number()`), tested in Task 2 Step 1.3. The hyphenated `"user-daily"` payload key can trip OpenAPI-typescript typing — fallback to a hand-written row interface (kept typed). Visual correctness (table layout, chart) needs a real browser (gotcha #11); jsdom green ≠ visual proof — flagged, run `pnpm test:browser` locally before merge.

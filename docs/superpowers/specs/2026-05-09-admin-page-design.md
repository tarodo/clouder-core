# Admin Page — Beatport Ingest Coverage

**Date:** 2026-05-09
**Status:** brainstorm stage — design awaiting user approval before implementation plan
**Author:** @tarodo (via brainstorming session)
**Scope:** new admin namespace `/admin` with two pages — Coverage matrix (style × week) with on-demand Beatport ingest, and the existing Spotify-not-found tracks list.

## 1. Goals

1. Admin sees, at a glance, which (style × week) pairs have already been ingested for a given year.
2. Admin starts a Beatport ingest for any (style, week) cell, with an optional date-range override.
3. Admin observes ingest progress live and gets a terminal toast even after navigating away.
4. Admin reads the existing list of tracks not matched on Spotify in the same admin shell.

Non-goals (deferred):

- Bulk multi-week ingest in one click.
- Cancel a running ingest.
- Re-enqueue from the Spotify-not-found list.
- Deleting ingest runs.
- Aurora-encrypted server-side `bp_token` storage.
- Mobile polish for `/admin/coverage` (matrix is desktop-first).
- Removal of the legacy `POST /collect_bp_releases` (kept deprecated; cleanup is a follow-up).

## 2. Week convention

Weeks are **Saturday-anchored**, not ISO.

- `Saturday(Y, 1)` = first Saturday on or after Jan 1 of `Y`.
- Week `N` of year `Y` runs `[Saturday(Y, N) … Friday(Y, N+1) - 1d]` inclusive (7 days).
- Days from Jan 1 up to, but not including, `Saturday(Y, 1)` belong to the last week of `Y - 1`.
- `weeks_in_year(Y)` is 52 or 53; computed as `floor((last_saturday(Y) - first_saturday(Y)) / 7) + 1` where `last_saturday(Y) = max d <= Dec 31 of Y where d.weekday() == Saturday`.

Reference implementations:

- Backend: `src/collector/saturday_week.py` (pure module). Public API: `saturday_week_range(year, week) -> (date, date)`, `week_of_date(d) -> (year, week)`, `weeks_in_year(year) -> int`, `first_saturday(year) -> date`.
- Frontend: `frontend/src/features/admin/lib/saturdayWeek.ts` (mirrors backend).

Test cases (BE + FE share fixtures):

- 2026: Jan 1 = Thu → first Saturday = Jan 3 → week 1 = Jan 3 – Jan 9.
- 2027: Jan 1 = Fri → first Saturday = Jan 2; days Jan 1 belongs to week 52/53 of 2026.
- 2028 (leap): first Saturday = Jan 1; week 1 = Jan 1 – Jan 7.
- 53-week year: 2027 if last Saturday is Dec 25; verify boundary explicitly.
- `week_of_date` round-trips against `saturday_week_range` for all 52/53 weeks of 2025–2028.

## 3. Backend changes

### 3.1 Migration

Add to `ingest_runs`:

```sql
ALTER TABLE ingest_runs
  ALTER COLUMN iso_year DROP NOT NULL,
  ALTER COLUMN iso_week DROP NOT NULL,
  ADD COLUMN week_year       INTEGER,
  ADD COLUMN week_number     INTEGER,
  ADD COLUMN period_start    DATE,
  ADD COLUMN period_end      DATE,
  ADD COLUMN is_custom_range BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX idx_ingest_runs_coverage
  ON ingest_runs (week_year, style_id, week_number);
```

Legacy `iso_year` / `iso_week` are dropped from `NOT NULL` so new admin runs can omit them. Existing rows keep their ISO values; new rows from `POST /admin/beatport/ingest` write only the new columns. Coverage queries gate on `WHERE week_year IS NOT NULL`. Old rows are not backfilled in this iteration — they remain queryable via `GET /runs/{run_id}` but do not appear on the coverage matrix.

### 3.2 New endpoints (all admin-gated)

`POST /admin/beatport/ingest`

Request schema (`AdminIngestRequestIn` in `src/collector/schemas.py`):

```jsonc
{
  "style_id": 1,
  "week_year": 2026,
  "week_number": 5,
  "period_start": "2026-01-31", // optional
  "period_end":   "2026-02-06", // optional
  "bp_token":     "...",
  "search_label_count": 50      // optional, existing semantics
}
```

Validation:

- `week_year`: `2000 <= y <= 2100`.
- `week_number`: `1 <= n <= weeks_in_year(week_year)`.
- `period_start` and `period_end`: both present or both absent. One alone → 400 `validation_error` with field path.
- If both absent: server computes `(period_start, period_end) = saturday_week_range(week_year, week_number)`, writes `is_custom_range = FALSE`.
- If both present: server uses the provided values verbatim, writes `is_custom_range = TRUE`. No constraint that they overlap the standard week — admin override is intentional.
- `bp_token`: required, never logged, never written to S3 (existing rule).

Response: same shape as the existing `POST /collect_bp_releases` (run_id, processing_status, etc.). Internal pipeline is shared — `_handle_collect` is refactored into a private helper called by both legacy and admin handlers.

`GET /admin/coverage?week_year=YYYY`

Response:

```jsonc
{
  "week_year": 2026,
  "weeks_in_year": 52,
  "styles": [
    {
      "style_id": 1,
      "style_name": "Tech House",
      "cells": [
        {
          "week_number": 1,
          "status": "completed",
          "run_id": "uuid",
          "started_at": "2026-01-04T09:12:00Z",
          "finished_at": "2026-01-04T09:14:00Z",
          "item_count": 147,
          "is_custom_range": false,
          "period_start": "2026-01-03",
          "period_end":   "2026-01-09"
        }
      ]
    }
  ]
}
```

- `styles` lists every row in `clouder_styles`, ordered by `name`. A style with no runs in `week_year` still appears with empty `cells`.
- `cells` contains exactly one entry per week_number that has a run. The frontend completes the gaps to `1..weeks_in_year`.
- If multiple runs exist for `(style_id, week_number)` the latest by `started_at` wins (window function `ROW_NUMBER() OVER (PARTITION BY style_id, week_number ORDER BY started_at DESC) = 1`).

`GET /admin/runs?style_id=N&week_year=YYYY&week_number=W`

All three params required. Returns `{ items: RunSummary[] }` ordered by `started_at DESC`. Powers the per-cell history list. Same shape as `GET /runs/{run_id}` per item.

### 3.3 Reused endpoints

- `GET /runs/{run_id}` — polling. No change.
- `GET /styles` — style picker / matrix rows. Already non-admin; keep.
- `GET /tracks/spotify-not-found` — second admin page. No change beyond it already being admin-gated.

### 3.4 Auth

`_ADMIN_ROUTES` in `src/collector/handler.py` extended:

```python
_ADMIN_ROUTES = frozenset({
    "POST /collect_bp_releases",         # legacy, deprecated
    "POST /admin/beatport/ingest",
    "GET /admin/coverage",
    "GET /admin/runs",
    "GET /tracks/spotify-not-found",
})
```

`_require_admin` already enforces `is_admin` JWT claim → 403 `admin_required`.

### 3.5 API Gateway

`infra/api_gateway.tf` registers the three new routes against the existing API Lambda integration. Authorizer config is unchanged (the same Lambda authorizer attaches `is_admin` to the request context).

### 3.6 OpenAPI

`scripts/generate_openapi.py:ROUTES` is updated to include the new endpoints; `docs/openapi.yaml` regenerated.

## 4. Frontend changes

### 4.1 Folder layout

```
frontend/src/features/admin/
  routes/
    AdminLayout.tsx
    AdminCoveragePage.tsx
    AdminSpotifyNotFoundPage.tsx
  components/
    YearNavigator.tsx
    CoverageMatrix.tsx
    CoverageMatrixCell.tsx
    CellDetailDrawer.tsx
    IngestForm.tsx
    RunDetails.tsx
    RunHistoryList.tsx
    BpTokenInput.tsx
    RunProgressToast.tsx
    SpotifyNotFoundTable.tsx
  hooks/
    useCoverage.ts
    useCellRuns.ts
    useStartIngest.ts
    useRunPoller.ts
    useSpotifyNotFound.ts
  lib/
    saturdayWeek.ts
    bpTokenStore.ts
    cellState.ts
    runsTracker.ts
```

### 4.2 Routing

- `/admin` → loader chain `requireAuth` + `requireAdmin` → redirect `/admin/coverage`.
- `/admin/coverage` → `AdminCoveragePage`.
- `/admin/spotify-not-found` → `AdminSpotifyNotFoundPage`.
- `requireAdmin` (new file `frontend/src/auth/requireAdmin.ts`) awaits `bootstrapPromise()` then calls `getAuthSnapshot()`. If `snap.status !== 'authenticated'` or `snap.user.is_admin === false` → `throw redirect('/')`. Mirrors the existing `requireAuth` shape (`frontend/src/auth/requireAuth.ts`).

### 4.3 AppShell nav

`_layout.tsx` `NAV_ITEMS` is augmented at runtime: an `Admin` entry (icon `IconShield` added to `components/icons.ts`) is appended only when the current user has `is_admin === true`. Both desktop sidebar and mobile footer pick up the conditional list.

### 4.4 AdminLayout

Sub-shell rendered inside `<AppShell.Main>`. Mantine `<Tabs>` with two tabs (`Coverage`, `Tracks not on Spotify`); active tab derived from `useLocation().pathname`. Tab change pushes `navigate(...)`.

### 4.5 Coverage page

Header row:

- `<YearNavigator>` — `<` / `>` buttons + dropdown (range 2024–2030, default `currentSaturdayWeek().year`).
- Style multi-select filter (Mantine `<MultiSelect>`).
- Optional text search by style name (client-side filter).

Matrix:

- Two-axis CSS grid. First column sticky (`position: sticky; left: 0`). Header row sticky top. Outer scroll wrapper `overflow-x: auto`.
- Cell size: 24×24 px on desktop. Column count = `weeks_in_year` of the active year.
- Cell color rules (function `cellState(cell, runsTracker)`):
  - `empty` (no run) — `var(--mantine-color-dark-6)`.
  - `loaded` (status `completed`) — `green-7`.
  - `loaded-custom` (loaded + `is_custom_range`) — `green-7` with `outline: 1px solid var(--mantine-color-yellow-5)`.
  - `failed` (latest run `failed`) — `red-7`, ✗ glyph at 50% opacity.
  - `running` (latest run is `pending` / `running` OR present in `runsTracker`) — `yellow-5` with CSS pulse keyframe.
  - `n/a` (`week_number > weeks_in_year`) — diagonal stripes; never present in current year, kept for forward-compat.
- Hover: Mantine `<Tooltip>` showing `Wk {n} · {periodLabel} · {item_count} items` plus `· custom range` when applicable.
- Click: opens / rebinds `<CellDetailDrawer>` with `(style_id, week_year, week_number)`.

Skeleton: Mantine `<Skeleton>` rectangles fill the matrix while coverage is loading. Empty styles list (`styles=[]`) → `<EmptyState>` "No styles configured".

### 4.6 Drawer behavior

Single Mantine `<Drawer position="right" size="md" closeOnClickOutside>`. State machine driven by `cellState`:

- `empty` / `failed` → `<IngestForm>` (failed prepends `<Alert>` with `error_code` + `error_message`).
- `loaded` → `<RunDetails>` + `<RunHistoryList>` + collapsed `Re-ingest` CTA that expands `<IngestForm>` inline.
- `running` → `<RunProgress>` with live stats (status, processed_count / item_count if available).

Switching cells while the drawer is open updates contents; the drawer does **not** unmount. Closing the drawer mid-flight does not cancel the ingest.

### 4.7 IngestForm

Fields:

- `bp_token` (`<PasswordInput>`) — rendered only when `bpTokenStore.get() === null`. Once stored, replaced with text "Token loaded · Reset".
- `Override date range` (`<Switch>`). Off (default): no date inputs, server computes from `(week_year, week_number)`. On: two `<DateInput valueFormat="YYYY-MM-DD">` pre-filled with the standard Saturday-week range.
- `Advanced ▸` collapse → `search_label_count` numeric input (optional).

Submit:

- `useStartIngest.mutate({ style_id, week_year, week_number, period_start?, period_end?, bp_token, search_label_count? })`.
- On success: `runsTracker.add(run_id, meta)`, drawer flips to `<RunProgress>`, `useRunPoller(run_id)` starts.
- On error: inline `<Alert>` with mapped i18n message + `correlation_id` for support.

Override-validation parity with backend: schema rejects "only one of period_start / period_end" client-side too (Zod refine).

### 4.8 RunDetails / RunHistoryList

`<RunDetails>` shows started/finished timestamps, duration, `item_count` / `processed_count`, period range, custom-range badge. Errors → red `<Alert>`.

`<RunHistoryList>` calls `useCellRuns({style_id, week_year, week_number})` (key `['admin', 'runs', styleId, weekYear, weekNumber]`). Compact rows, latest first. Click expands a row inline with full details. List hides when 0 historic runs (i.e., the only run is the latest already shown above).

### 4.9 Polling and live updates

`useRunPoller(run_id)`:

- `useQuery({ queryKey: ['runs', run_id], queryFn, refetchInterval: r => isTerminal(r) ? false : 2000 })`.
- On terminal: invalidate `['admin', 'coverage', week_year]` and `['admin', 'runs', styleId, weekYear, weekNumber]`; remove run from `runsTracker`.

`runsTracker` (Zustand store) holds `Map<run_id, { styleId, weekYear, weekNumber, startedAt }>`. The matrix derives `running` cell state from this store; the global toast surface subscribes too.

`<RunProgressToast>` uses Mantine `notifications`. One persistent (`autoClose: false`) toast per running run. On terminal, `notifications.update` sets autoClose 4s and color (green/red).

### 4.10 bp_token store

`bpTokenStore.ts` is a module-scoped object with `get()`, `set(value)`, `clear()`. No persistence (no localStorage, no sessionStorage, no cookies). Survives soft navigations; cleared on tab close or hard reload. UserMenu gains a "Reset Beatport token" item, only visible when `is_admin === true` and `bpTokenStore.get() !== null`.

### 4.11 Spotify-not-found page

Reuses `GET /tracks/spotify-not-found`. Layout: header with total count + search, Mantine `<Table>` (cols `Title`, `Artists`, `Album`, `Label`, `Style`, `ISRC`, `Last seen`), Mantine `<Pagination>` page-based (default `limit=50`).

`useSpotifyNotFound({ limit, offset, search })` → key `['admin', 'spotifyNotFound', limit, offset, search]`. `placeholderData: keepPreviousData` for paginated continuity. 300 ms debounce on search (`useDebouncedValue`).

Empty state: `<EmptyState>` "No tracks awaiting Spotify match".

### 4.12 Error mapping (i18n keys under `admin.errors.*`)

| `error_code`         | i18n key                            | Surface                               |
| -------------------- | ----------------------------------- | ------------------------------------- |
| `validation_error`   | `admin.errors.validation`           | Inline alert in form                  |
| `bp_token_invalid`   | `admin.errors.bpTokenInvalid`       | Inline alert + clears token store     |
| `db_not_configured`  | `admin.errors.dbNotConfigured`      | Page-level alert                      |
| `internal_error`     | `admin.errors.internal`             | Toast + correlation_id                |
| `admin_required`     | `admin.errors.adminRequired`        | Should not happen — fallback redirect |

## 5. Data flow (typical happy path)

1. Admin opens `/admin/coverage`. `useCoverage(2026)` fetches matrix data. Matrix renders.
2. Admin clicks an `empty` cell. Drawer opens with `<IngestForm>`. First time → admin pastes `bp_token`; subsequent ingests skip the field.
3. Admin clicks `Start ingest`. POST to `/admin/beatport/ingest` returns `{ run_id, status: 'pending' }`.
4. `runsTracker.add(run_id, ...)`. Matrix cell flips to `running` (yellow pulse). Persistent toast appears. Drawer flips to `<RunProgress>`.
5. `useRunPoller` polls every 2 s. On terminal status:
   - `runsTracker.remove(run_id)`,
   - coverage + cell-runs caches invalidated,
   - cell repaints green/red,
   - toast updates to success/error and auto-closes in 4 s.
6. Admin can close the drawer mid-flight. Polling continues. Tab close stops the FE clock; the BE finishes regardless and the next visit shows the final state.

## 6. Tests

### Backend

- `tests/unit/test_saturday_week.py` — full week-math coverage, including 53-week years and Jan-1 boundaries.
- `tests/unit/test_admin_schemas.py` — `AdminIngestRequestIn` validation, including the "only one date" rejection.
- `tests/integration/test_admin_ingest_endpoint.py` — happy path, override path, `is_admin=false` → 403.
- `tests/integration/test_admin_coverage_endpoint.py` — empty styles, partial cells, latest-run-per-cell selection, `weeks_in_year` correctness.
- `tests/integration/test_admin_runs_endpoint.py` — DESC order, missing params → 400.

### Frontend

- `lib/saturdayWeek.test.ts` — fixtures shared with backend.
- `auth/requireAdmin.test.ts` — non-admin redirect.
- `features/admin/components/CoverageMatrix.test.tsx` — render, cell states, sticky behavior, click → drawer.
- `features/admin/components/CellDetailDrawer.test.tsx` — three states, switching cells without unmount.
- `features/admin/components/IngestForm.test.tsx` — override toggle, default-range pre-fill, bp_token store interaction, override validation.
- `features/admin/hooks/useRunPoller.test.tsx` — refetchInterval gating + invalidation.
- `features/admin/lib/runsTracker.test.ts` — multi-run state.
- `features/admin/routes/AdminSpotifyNotFoundPage.test.tsx` — search debounce + pagination.
- `routes/_layout.test.tsx` — admin nav appears only when `is_admin`.

MSW handlers in `frontend/src/test/handlers.ts` cover the three new endpoints.

## 7. Open questions / risks

- **Beatport API rejecting custom long ranges.** Beatport's `publish_date` filter accepts arbitrary ranges in practice, but very wide windows may paginate slowly and trip API Gateway's 29s timeout for the synchronous response. Mitigation: same as today — the Lambda finishes in background; admin retries the cell view after a few seconds. Documented in `CLAUDE.md` already.
- **`weeks_in_year` mismatch FE/BE.** Algorithms must agree exactly; covered by shared fixture-based tests.
- **Concurrent runs on the same (style, week).** Allowed. Latest run by `started_at` wins for the cell color; the drawer history exposes both.
- **Legacy ISO data invisibility.** Old runs predating this feature do not appear on the matrix. Documented; no migration in this iteration.
- **`bp_token` survives soft navigations.** Admin who steps away leaves the token in JS memory until tab close. Acceptable per the in-memory-store decision (no persistence boundaries crossed).

## 8. Out of scope (explicit)

- Bulk multi-week ingest UI.
- Cancel a running run.
- Re-enqueue track from the Spotify-not-found list.
- Deletion / archival of `ingest_runs` rows.
- Aurora-encrypted `bp_token` server-side storage.
- Mobile polish for the matrix (functional, not pretty).
- Removal of `POST /collect_bp_releases`.

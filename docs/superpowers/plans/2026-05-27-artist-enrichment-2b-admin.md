# Artist Enrichment 2B — Admin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give admins the artist-enrichment controls at parity with labels — an "artists" auto-enrich config tab, an artist backlog page with point-wise vendor-settings enqueue + per-artist history, and artist enrichment-runs list + detail pages.

**Architecture:** Mirror the label admin UI (`features/admin`). Reuse the entity-agnostic components as-is (`EnrichConfigForm`, `BacklogToolbar`, `BacklogTable`, `RunsTable`, `RunDetailHeader`, `RunStatusBadge`, `RunJsonViewer` — they take data/props, only their type imports are label-shaped but structurally identical to the artist types). Mirror the label-coupled pieces as `Artist*` variants: the hooks (hardcoded `/admin/labels/...` endpoints), `EnqueueDrawer` (posts label body), `LabelHistoryDrawer`, the backlog/runs pages, and the `ArtistsTab`.

**Tech Stack:** Vite + React 19 + Mantine 9 + TanStack Query + react-router; tests vitest (jsdom).

**Spec:** `docs/superpowers/specs/2026-05-27-artist-enrichment-frontend-design.md` (sub-project 2). This is **plan 2B of 3** (2A API+Library ✅ → 2B admin → 2C player+preferences). 2A already shipped `frontend/src/api/artists.ts` with `RunSummary`/`RunsListResponse`/`RunDetail`/`RunCell`/`EnrichmentOptions`/`EnrichBody`/`BacklogArtist`/`BacklogResponse`/`ArtistHistoryResponse`/`ArtistHistoryCell`. 2B does NOT touch the player or preferences (2C).

**Conventions (same as 2A):**
- `<repo>` = `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search`. Frontend: `<repo>/frontend`. Tests: `cd <repo>/frontend && pnpm test <paths>` (vitest run; pass paths, NO `--run`). Typecheck: `pnpm typecheck`. Lint: `pnpm lint`. Do NOT run `pnpm dev`.
- Each task: failing test → impl → green → commit. Hook enforces Conventional Commits, no AI attribution. After committing verify `git log -1` + `git status --short` (clean). NOTE: subagents in this project have repeatedly created files but skipped the commit — always run the commit and confirm the tree is clean before reporting DONE.
- **Mirror sources (read, then copy+transform):** `frontend/src/features/admin/routes/{AdminAutoEnrichPage,AdminEnrichmentBacklogPage,AdminEnrichmentRunsPage,AdminEnrichmentRunDetailPage}.tsx`, `frontend/src/features/admin/components/enrichment/{EnqueueDrawer,LabelHistoryDrawer}.tsx`, `frontend/src/features/admin/hooks/{useAutoEnrichConfig,useSaveAutoEnrichConfig,useEnrichmentOptions,useLabelBacklog,useEnqueueEnrichment,useEnrichmentRuns,useEnrichmentRunDetail}.ts`, `frontend/src/api/autoEnrich.ts`, `frontend/src/routes/router.tsx`, and the admin nav (find it: `grep -rln "labels/enrich\|/admin/auto-enrich" frontend/src/features/admin/routes/AdminLayout.tsx frontend/src/**/*.tsx`).
- **Deltas:** `label`→`artist`, `/admin/labels/...`→`/admin/artists/...`, enqueue body `{labels:[{label_id}]}`→`{artists:[{artist_id}]}`, `queued_labels`→`queued_artists`, query keys `['admin','labelBacklog'|'enrichmentRuns'|'autoEnrich','labels']`→artist equivalents, types from `api/labels`→`api/artists`. **Reuse `EnrichConfigForm`/`BacklogToolbar`/`BacklogTable`/`Runs*` as-is** (pass artist data; structural typing accepts it).

---

## File Structure

```
frontend/src/api/artistAutoEnrich.ts                         Task 1 (NEW — auto-config types)
frontend/src/features/admin/hooks/useArtistAutoEnrichConfig.ts      Task 1
frontend/src/features/admin/hooks/useSaveArtistAutoEnrichConfig.ts  Task 1
frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx   Task 1 (enable artists tab + ArtistsTab)
frontend/src/features/admin/hooks/useArtistEnrichmentOptions.ts     Task 2
frontend/src/features/admin/hooks/useArtistBacklog.ts               Task 2
frontend/src/features/admin/hooks/useEnqueueArtistEnrichment.ts     Task 2
frontend/src/features/admin/components/enrichment/ArtistEnqueueDrawer.tsx   Task 2
frontend/src/features/admin/components/enrichment/ArtistHistoryDrawer.tsx   Task 2
frontend/src/features/admin/routes/AdminArtistEnrichmentBacklogPage.tsx     Task 2
frontend/src/features/admin/hooks/useArtistEnrichmentRuns.ts        Task 3
frontend/src/features/admin/hooks/useArtistEnrichmentRunDetail.ts   Task 3
frontend/src/features/admin/routes/AdminArtistEnrichmentRunsPage.tsx        Task 3
frontend/src/features/admin/routes/AdminArtistEnrichmentRunDetailPage.tsx   Task 3
frontend/src/routes/router.tsx                               Task 2+3 (routes)
<admin nav file>                                             Task 2+3 (nav links)
frontend/src/i18n/en.json                                    Task 1-3 (keys; mostly reuse)
```

Reused unchanged: `EnrichConfigForm`, `BacklogToolbar`, `BacklogTable`, `RunsTable`, `RunDetailHeader`, `RunStatusBadge`, `RunJsonViewer`.

---

## Task 1: Auto-enrich config — artists tab

**Files:**
- Create: `frontend/src/api/artistAutoEnrich.ts`, `useArtistAutoEnrichConfig.ts`, `useSaveArtistAutoEnrichConfig.ts`
- Modify: `frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx`
- Test: `AdminAutoEnrichPage.test.tsx` (or an `ArtistsTab` test)

- [ ] **Step 1: Auto-config API types**

Read `frontend/src/api/autoEnrich.ts` (it extracts `AutoEnrichConfigResponse`/`AutoEnrichConfigBody` from `paths['/admin/auto-enrich/labels']`). Create `frontend/src/api/artistAutoEnrich.ts`:
```ts
import type { paths } from './schema';

export type AutoEnrichConfigResponse = paths['/admin/auto-enrich/artists']['get']['responses'][200]['content']['application/json'];
export type AutoEnrichConfigBody     = paths['/admin/auto-enrich/artists']['put']['requestBody']['content']['application/json'];
```
(Match the exact export names/shape of `api/autoEnrich.ts`.) `pnpm typecheck` → resolves (the artist auto-enrich paths exist in `schema.d.ts` from SP1).

- [ ] **Step 2: Hooks**

Copy `useAutoEnrichConfig.ts` → `useArtistAutoEnrichConfig.ts`: endpoint `/admin/auto-enrich/artists`, query key `['admin','autoEnrich','artists']`, types from `../../../api/artistAutoEnrich`. Copy `useSaveAutoEnrichConfig.ts` → `useSaveArtistAutoEnrichConfig.ts`: PUT `/admin/auto-enrich/artists`, invalidate `['admin','autoEnrich','artists']`.

- [ ] **Step 3: Write the failing test**

`AdminAutoEnrichPage.test.tsx` (or `ArtistsTab.test.tsx`): mock `useArtistAutoEnrichConfig` (return a config+options) + `useSaveArtistAutoEnrichConfig`; render `AdminAutoEnrichPage`, click the "artists" tab, assert the `EnrichConfigForm` renders (vendors from options) and the enabled switch + save button work (save called with the artist config on submit). Run → FAIL (artists tab is disabled / no ArtistsTab).

- [ ] **Step 4: Enable the artists tab + add `ArtistsTab`**

In `AdminAutoEnrichPage.tsx`: add an `ArtistsTab` function mirroring `LabelsTab` exactly but using `useArtistAutoEnrichConfig`/`useSaveArtistAutoEnrichConfig`. Remove `disabled` from the `<Tabs.Tab value="artists">` and replace the coming-soon `<Tabs.Panel value="artists">` body with `<ArtistsTab />`. The `EnrichConfigForm` is reused as-is (pass `query.data.options`). i18n: reuse the `admin_auto_enrich.*` keys (they're entity-neutral: title/enabled_label/save/saved/save_error/tab_artists). Leave the `tracks` tab disabled.

- [ ] **Step 5: Run the test → PASS.** `pnpm typecheck` → 0. `pnpm test src/features/admin 2>&1 | tail -6` → admin suite green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/artistAutoEnrich.ts frontend/src/features/admin/hooks/useArtistAutoEnrichConfig.ts frontend/src/features/admin/hooks/useSaveArtistAutoEnrichConfig.ts frontend/src/features/admin/routes/AdminAutoEnrichPage.tsx frontend/src/features/admin/routes/__tests__/AdminAutoEnrichPage.test.tsx
git commit -m "feat(artist-enrich): add artists auto-enrich config tab"
git log -1 --format='%H %s'
git status --short
```

---

## Task 2: Artist backlog + enqueue

**Files:**
- Create: hooks `useArtistEnrichmentOptions.ts`, `useArtistBacklog.ts`, `useEnqueueArtistEnrichment.ts`; components `ArtistEnqueueDrawer.tsx`, `ArtistHistoryDrawer.tsx`; route `AdminArtistEnrichmentBacklogPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (route) + the admin nav
- Test: `AdminArtistEnrichmentBacklogPage.test.tsx` (and/or `ArtistEnqueueDrawer.test.tsx`)

- [ ] **Step 1: Hooks**

- `useArtistEnrichmentOptions.ts` ← `useEnrichmentOptions.ts`: endpoint `/admin/artists/enrich/options`, key `['admin','artistEnrichment','options']`, type `EnrichmentOptions` from `api/artists`.
- `useArtistBacklog.ts` ← `useLabelBacklog.ts`: endpoint `/admin/artists/backlog`, key `['admin','artistBacklog',style,status]`, type `BacklogResponse` from `api/artists`. Export `ArtistStatusFilter = 'all'|'none'|'completed'|'outdated'`.
- `useEnqueueArtistEnrichment.ts` ← `useEnqueueEnrichment.ts`: POST `/admin/artists/enrich`, body `EnrichBody` from `api/artists` (shape `{artists:[{artist_id}],...}`), response `{run_id, queued_artists}`, invalidate `['admin','artistBacklog']` + `['admin','artistEnrichmentRuns']`.

- [ ] **Step 2: Drawers**

- `ArtistEnqueueDrawer.tsx` ← `EnqueueDrawer.tsx`: prop `artistIds: string[]`; use `useArtistEnrichmentOptions` + `useEnqueueArtistEnrichment`; submit body `{ artists: artistIds.map((artist_id) => ({ artist_id })), vendors, models, prompt_slug, prompt_version, merge_vendor:'deepseek', merge_model }`; success notification uses `res.queued_artists`; reuse `EnrichConfigForm` as-is. Reuse the `admin_enrichment.enqueue_drawer.*` i18n keys.
- `ArtistHistoryDrawer.tsx` ← `LabelHistoryDrawer.tsx` (read it): prop `artistId`/`artistName`; fetch `/admin/artists/{artist_id}/history` via a small hook or inline query (mirror how `LabelHistoryDrawer` fetches; type `ArtistHistoryResponse` from `api/artists`).

- [ ] **Step 3: Failing test**

`AdminArtistEnrichmentBacklogPage.test.tsx`: mock `useArtistBacklog` (2 artists), `useStyles`; render the page; assert backlog rows render via `BacklogTable`, selecting rows + clicking enqueue opens `ArtistEnqueueDrawer`. (Or a focused `ArtistEnqueueDrawer.test.tsx` asserting submit posts `{artists:[{artist_id}]}`.) Run → FAIL.

- [ ] **Step 4: Page**

`AdminArtistEnrichmentBacklogPage.tsx` ← `AdminEnrichmentBacklogPage.tsx`: use `useArtistBacklog`/`ArtistStatusFilter`; reuse `BacklogToolbar` + `BacklogTable` (pass artist items — structural types accept it); use `ArtistEnqueueDrawer` (prop `artistIds`) + `ArtistHistoryDrawer`. Keep the `useStyles`/`slugifyStyle` style filtering verbatim.

- [ ] **Step 5: Route + nav**

In `router.tsx`, under `admin` children, add `{ path: 'artists/enrich', element: <AdminArtistEnrichmentBacklogPage /> }` (import it). In the admin nav (the file found via the grep in Conventions — likely `AdminLayout` or a nav component), add an "Artists enrichment" link to `/admin/artists/enrich` beside the existing labels-enrich link. Mirror the label nav entry.

- [ ] **Step 6: Verify + commit**

`pnpm test src/features/admin 2>&1 | tail -6` → green; `pnpm typecheck` → 0; `pnpm lint src/features/admin 2>&1 | tail -4`.
```bash
git add frontend/src/features/admin/hooks/useArtist*.ts frontend/src/features/admin/hooks/useEnqueueArtist*.ts frontend/src/features/admin/components/enrichment/Artist*.tsx frontend/src/features/admin/routes/AdminArtistEnrichmentBacklogPage.tsx frontend/src/features/admin/routes/__tests__/AdminArtistEnrichmentBacklogPage.test.tsx frontend/src/routes/router.tsx
# + the admin nav file + any i18n
git commit -m "feat(artist-enrich): add artist backlog + enqueue admin page"
git log -1 --format='%H %s'
git status --short
```

---

## Task 3: Artist enrichment runs pages

**Files:**
- Create: hooks `useArtistEnrichmentRuns.ts`, `useArtistEnrichmentRunDetail.ts`; routes `AdminArtistEnrichmentRunsPage.tsx`, `AdminArtistEnrichmentRunDetailPage.tsx`
- Modify: `frontend/src/routes/router.tsx` (routes) + admin nav
- Test: `AdminArtistEnrichmentRunsPage.test.tsx`

- [ ] **Step 1: Hooks**

Read `useEnrichmentRuns.ts` + `useEnrichmentRunDetail.ts`. Copy → `useArtistEnrichmentRuns.ts` (endpoint `/admin/artists/enrich-runs`, key `['admin','artistEnrichmentRuns',...]`, type `RunsListResponse` from `api/artists`) and `useArtistEnrichmentRunDetail.ts` (endpoint `/admin/artists/enrich-runs/{run_id}`, key `['admin','artistEnrichmentRun',runId]`, type `RunDetail` from `api/artists`).

- [ ] **Step 2: Failing test**

`AdminArtistEnrichmentRunsPage.test.tsx`: mock `useArtistEnrichmentRuns` (a couple runs); render; assert runs render via `RunsTable` with links to `/admin/artists/enrich/runs/:runId`. Run → FAIL.

- [ ] **Step 3: Pages**

`AdminArtistEnrichmentRunsPage.tsx` ← `AdminEnrichmentRunsPage.tsx`: use `useArtistEnrichmentRuns`; reuse `RunsTable`/`RunStatusBadge` (pass artist runs); links to `/admin/artists/enrich/runs/:runId`.
`AdminArtistEnrichmentRunDetailPage.tsx` ← `AdminEnrichmentRunDetailPage.tsx`: route param `runId`; use `useArtistEnrichmentRunDetail`; reuse `RunDetailHeader`/`RunJsonViewer`/`RunStatusBadge` (the run cells carry `artist_id`/`artist_name` — confirm the reused components read generic cell fields; if `RunDetailHeader`/the cells table hard-render `label_name`, add a minimal artist-aware variant — read them first and report).

- [ ] **Step 4: Routes + nav**

In `router.tsx`, add `{ path: 'artists/enrich/runs', element: <AdminArtistEnrichmentRunsPage /> }` and `{ path: 'artists/enrich/runs/:runId', element: <AdminArtistEnrichmentRunDetailPage /> }`. Add an artist-runs nav link beside the label-runs one (or link from the backlog page header, mirroring the label flow).

- [ ] **Step 5: Verify + commit**

`pnpm test src/features/admin 2>&1 | tail -6` → green; `pnpm typecheck` → 0.
```bash
git add frontend/src/features/admin/hooks/useArtistEnrichmentRun*.ts frontend/src/features/admin/routes/AdminArtistEnrichmentRuns*.tsx frontend/src/features/admin/routes/__tests__/AdminArtistEnrichmentRunsPage.test.tsx frontend/src/routes/router.tsx
# + admin nav + i18n
git commit -m "feat(artist-enrich): add artist enrichment runs pages"
git log -1 --format='%H %s'
git status --short
```

---

## Done criteria for plan 2B

- The "artists" tab in `AdminAutoEnrichPage` is enabled and saves the artist auto-enrich config.
- `/admin/artists/enrich` lists the artist backlog with style/status filters and enqueues selected artists with vendor settings (posting `{artists:[{artist_id}]}`); per-artist history drawer works.
- `/admin/artists/enrich/runs` + `/runs/:runId` show artist enrichment runs.
- Admin nav links to the artist pages. Label admin suite remains green; typecheck clean; no `pnpm dev`.

## Next: 2C (player panel + preferences)

The player `ArtistsPanel` (main artist as `ArtistTile` card + every other artist as a chip with AI badge) below the label info on `BucketPlayerPanel`/`CategoryPlayerPanel`/`PlaylistPlayerPanel`; `ArtistTile` (mirror `LabelTile`, with `useArtistInfo`); `ArtistPreferenceButtons` + `useSetArtistPreference` (added to `ArtistTile`, `ArtistDetailHeader`, `ArtistsTable`) + the "my artists" filter (unhide via the `hideMyFilter` prop added in 2A); jsdom tests + **browser tests** (`pnpm test:browser`) for the panel layout. Then PR all of SP2.

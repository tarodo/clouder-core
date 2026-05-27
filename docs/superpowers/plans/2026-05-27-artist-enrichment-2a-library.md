# Artist Enrichment 2A — API + Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users browse enriched artists in the Library — a small backend touch exposing artist ids on the triage bucket-tracks response, the artist API client + read hooks, and the Library artists list + detail pages (no preferences yet).

**Architecture:** Mirror the label Library frontend (`features/library`) with parallel `Artist*` components, reusing the `api<T>()` client, react-query patterns, and the `api/labels.ts` `paths[...]` type-extraction style. The one backend change: the triage bucket-tracks query/serializer emit artist `{id,name,role}` objects instead of a name string (so later the triage player can resolve artist ids).

**Tech Stack:** Backend: Python 3.12, Aurora Data API. Frontend: Vite + React 19 + Mantine 9 + TanStack Query + react-router + openapi-typescript; tests with vitest (jsdom).

**Spec:** `docs/superpowers/specs/2026-05-27-artist-enrichment-frontend-design.md` (sub-project 2). This is **plan 2A of 3** (2A API+Library → 2B admin → 2C player panel + preferences). 2A deliberately EXCLUDES: preference buttons / "my artists" filter (2C), the player `ArtistsPanel` (2C), admin UI (2B). The artist API endpoints already exist (SP1, deployed) and the worktree `frontend/src/api/schema.d.ts` already contains the artist paths (regenerated in SP1 plan 1B).

**Conventions:**
- `<repo>` = `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/improve_artist_search` (work here). `<main-repo>` = `/Users/roman/Projects/clouder-projects/clouder-core`.
- Backend tests: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest <paths>`.
- Frontend: run from `<repo>/frontend`. Install once if needed (`pnpm install`). Tests: `cd <repo>/frontend && pnpm test <paths>` (vitest jsdom). Type-check: `pnpm tsc --noEmit` (or the project's `pnpm build`/`typecheck` script — check `frontend/package.json`). Do NOT run `pnpm dev`.
- Each task: failing test → impl → green → commit. Hook enforces Conventional Commits, no AI attribution. After committing verify `git log -1` + `git status --short` (clean).
- **Mirror source-of-truth (read, then copy+transform):** `frontend/src/api/labels.ts`, `frontend/src/features/library/hooks/{useLabelsList,useLabelDetail,useLabelInfo}.ts`, `frontend/src/features/library/routes/{LibraryListPage,LabelDetailPage}.tsx`, `frontend/src/features/library/components/{EntityTabs,LabelsTable,LabelCard,LabelDetailHeader}.tsx` + the label overview/styles/channel-links tab components, `frontend/src/routes/router.tsx`.
- **Field deltas (label → artist), apply consistently:** `label`→`artist`, `label_id`→`artist_id`, `/labels`→`/artists`; denorm/display fields `founded_year`→`active_since`, drop `activity`/`last_release_date`, `notable_artists`→`notable_collaborators`; label channel links → artist links `spotify_url, soundcloud_url, bandcamp_url, beatport_url, residentadvisor_url, discogs_url, instagram_url, twitter_url, website`; add `artist_type`. **Omit preference UI in 2A** (the label components embed `LabelPreferenceButtons` — leave those out of the artist components; 2C adds `ArtistPreferenceButtons`).

---

## File Structure

```
src/collector/curation/triage_repository.py      Task 1 (modify list_bucket_tracks query + BucketTrackRowOut)
src/collector/curation_handler.py                Task 1 (_serialize_bucket_track)
frontend/src/features/triage/hooks/useBucketTracks.ts   Task 1 (BucketTrack.artists type + consumers)
frontend/src/api/artists.ts                       Task 2 (NEW — type extraction)
frontend/src/features/library/hooks/useArtistsList.ts   Task 2 (NEW)
frontend/src/features/library/hooks/useArtistDetail.ts  Task 2 (NEW)
frontend/src/features/library/hooks/useArtistInfo.ts    Task 2 (NEW)
frontend/src/features/library/components/EntityTabs.tsx Task 3 (enable artists tab)
frontend/src/routes/router.tsx                    Task 3 (add artist routes)
frontend/src/features/library/routes/ArtistsListPage.tsx     Task 3 (NEW)
frontend/src/features/library/components/ArtistsTable.tsx    Task 3 (NEW)
frontend/src/features/library/components/ArtistCard.tsx      Task 3 (NEW)
frontend/src/features/library/routes/ArtistDetailPage.tsx    Task 4 (NEW)
frontend/src/features/library/components/ArtistDetailHeader.tsx + overview/styles/links  Task 4 (NEW)
```

i18n: mirror the label keys used by the copied components into the artist namespace (find them in `frontend/src/**/locales` or the `t('library...')` usages; add `t('library.artists...')` / reuse generic keys). Each task notes the keys it needs.

---

## Task 1: Backend touch — artist ids on bucket-tracks

**Files:**
- Modify: `src/collector/curation/triage_repository.py` (`list_bucket_tracks` query + `BucketTrackRowOut`)
- Modify: `src/collector/curation_handler.py:1115` (`_serialize_bucket_track`)
- Modify: `frontend/src/features/triage/hooks/useBucketTracks.ts` (`BucketTrack.artists` type + any consumer)

The triage bucket-tracks response carries `artists` as a list of name strings (from `STRING_AGG(ca.name, ...)`). Change it to emit `{id, name, role}` objects so the triage player (2C) can resolve artist ids.

- [ ] **Step 1: Read the current shapes**

Read `src/collector/curation/triage_repository.py:983-1011` (the `list_bucket_tracks` SELECT — it uses `STRING_AGG(ca.name, ',' ORDER BY cta.role, ca.name) AS artist_names`) and the `BucketTrackRowOut` dataclass/row type it builds (grep `BucketTrackRowOut` in that file) — note how `artist_names` (comma string) becomes `.artists` (list[str]). You will change the aggregate to a JSON array of objects and adjust the row parsing.

- [ ] **Step 2: Write/extend the failing backend test**

Find the existing test for `list_bucket_tracks` or `_serialize_bucket_track` (`grep -rln "list_bucket_tracks\|_serialize_bucket_track\|bucket.*tracks" tests/`). Add/adjust a test asserting the serialized bucket track's `artists` is a list of `{"id","name","role"}` dicts (ordered by role then name). If the repo test uses a fake Data API returning rows, seed a row whose artist aggregate is the JSON-array form and assert `BucketTrackRowOut.artists == [{"id":...,"name":...,"role":...}, ...]`. Run it → FAIL (currently names).

- [ ] **Step 3: Change the query + row + serializer**

In `triage_repository.py` `list_bucket_tracks`, replace the artist aggregate line:
```sql
STRING_AGG(ca.name, ',' ORDER BY cta.role, ca.name) AS artist_names
```
with:
```sql
COALESCE(
  json_agg(json_build_object('id', ca.id, 'name', ca.name, 'role', cta.role)
           ORDER BY cta.role, ca.name)
  FILTER (WHERE ca.id IS NOT NULL),
  '[]'
) AS artists
```
Update `BucketTrackRowOut` so `artists` is parsed from the JSON aggregate into `list[dict]` (Aurora Data API returns `json_agg` as a JSON-encoded string — `json.loads` it if it's a str, else use as-is; mirror the existing JSONB-decode pattern used elsewhere, e.g. label repository's `json.loads(v) if isinstance(v, str)`). Drop the old comma-split of `artist_names`.

In `curation_handler.py:1128`, change `"artists": list(row.artists)` to `"artists": row.artists` (already a list of dicts).

- [ ] **Step 4: Run the backend test → PASS.** Also run the broader curation/triage suite for no regression: `cd <repo> && PYTHONPATH=src <main-repo>/.venv/bin/pytest tests/unit -k "bucket or triage or curation" -q 2>&1 | tail -5`.

- [ ] **Step 5: Update the frontend `BucketTrack` type + consumers**

In `frontend/src/features/triage/hooks/useBucketTracks.ts`, change `artists: string[];` to:
```ts
  artists: { id: string; name: string; role: string }[];
```
Then `grep -rn "\.artists" frontend/src/features/triage` to find consumers (e.g. `BucketPlayerPanel` may join artist names for display). Update each to read `.name` from the objects (e.g. `track.artists.map(a => a.name).join(', ')`). Keep the current display behavior working (the full `ArtistsPanel` comes in 2C). Type-check: `cd <repo>/frontend && pnpm tsc --noEmit` (or the project typecheck script) → no errors.

- [ ] **Step 6: Commit**

```bash
git add src/collector/curation/triage_repository.py src/collector/curation_handler.py frontend/src/features/triage/hooks/useBucketTracks.ts tests/
git commit -m "feat(artist-enrich): expose artist ids on bucket-tracks response"
git log -1 --format='%H %s'
git status --short
```

---

## Task 2: Artist API client + read hooks

**Files:**
- Create: `frontend/src/api/artists.ts`
- Create: `frontend/src/features/library/hooks/useArtistsList.ts`, `useArtistDetail.ts`, `useArtistInfo.ts`
- Test: `frontend/src/features/library/hooks/__tests__/useArtistsList.test.ts` (and siblings, per the repo's test placement convention — check where label hook tests live first)

Mirror `frontend/src/api/labels.ts` + the label hooks. The worktree `schema.d.ts` already has the artist paths.

- [ ] **Step 1: Write `api/artists.ts`**

Create `frontend/src/api/artists.ts`, mirroring `frontend/src/api/labels.ts` with `/labels`→`/artists`:
```ts
import type { paths } from './schema';

export type ArtistSummary       = paths['/artists']['get']['responses'][200]['content']['application/json']['items'][number];
export type ArtistsListResponse = paths['/artists']['get']['responses'][200]['content']['application/json'];
export type ArtistDetail        = paths['/artists/{artist_id}']['get']['responses'][200]['content']['application/json'];
export type BacklogArtist       = paths['/admin/artists/backlog']['get']['responses'][200]['content']['application/json']['items'][number];
export type BacklogResponse     = paths['/admin/artists/backlog']['get']['responses'][200]['content']['application/json'];
export type RunSummary          = paths['/admin/artists/enrich-runs']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunsListResponse    = paths['/admin/artists/enrich-runs']['get']['responses'][200]['content']['application/json'];
export type RunDetail           = paths['/admin/artists/enrich-runs/{run_id}']['get']['responses'][200]['content']['application/json'];
export type RunCell             = NonNullable<RunDetail['cells']>[number];
export type EnrichmentOptions   = paths['/admin/artists/enrich/options']['get']['responses'][200]['content']['application/json'];
export type EnrichBody          = paths['/admin/artists/enrich']['post']['requestBody']['content']['application/json'];
export type ArtistHistoryResponse = paths['/admin/artists/{artist_id}/history']['get']['responses'][200]['content']['application/json'];
export type ArtistHistoryCell   = ArtistHistoryResponse['items'][number];
```
Verify the types resolve: `cd <repo>/frontend && pnpm tsc --noEmit` → no errors (confirms `schema.d.ts` has these paths). If a path is missing from `schema.d.ts`, STOP and report — it means the worktree schema is stale (regenerate via the SP1 method).

- [ ] **Step 2: Write the failing hook test**

Mirror the label hook test (find it: `grep -rln "useLabelsList\|labelsListKey" frontend/src`). Create `useArtistsList.test.ts` asserting the hook builds `/artists?style=...&q=...&sort=...&my=...&page=...&limit=...` and returns the response (mock `api<T>()`). Run → FAIL (hook missing).

- [ ] **Step 3: Write the hooks**

- `useArtistsList.ts`: copy `useLabelsList.ts`, swap `Label`→`Artist`, `labels`→`artists`, query key `['library','artists',...]`, endpoint `/artists`. Same params (`styleId/q/sort/page/limit/my`).
- `useArtistInfo.ts`: copy `useLabelInfo.ts` (the player-tile fetch), endpoint `GET /artists/{artistId}`, key `['library','artistInfo',artistId]`, type `ArtistDetail` (or the info shape the endpoint returns).
- `useArtistDetail.ts`: copy `useLabelDetail.ts`, endpoint `GET /artists/{artistId}`, type `ArtistDetail`. (If `useLabelInfo` and `useLabelDetail` hit the same endpoint with different keys/usages, mirror that exactly.)

- [ ] **Step 4: Run the hook test → PASS.** Type-check clean.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/artists.ts frontend/src/features/library/hooks/useArtist*.ts frontend/src/features/library/hooks/__tests__/useArtist*.test.ts
git commit -m "feat(artist-enrich): add artist API types and read hooks"
git log -1 --format='%H %s'
git status --short
```

---

## Task 3: Library artists list + EntityTabs + routes

**Files:**
- Modify: `frontend/src/features/library/components/EntityTabs.tsx` (enable artists tab)
- Modify: `frontend/src/routes/router.tsx` (add `:styleId/artists` route)
- Create: `frontend/src/features/library/routes/ArtistsListPage.tsx`, `components/ArtistsTable.tsx`, `components/ArtistCard.tsx`
- Test: `ArtistsListPage.test.tsx` (jsdom)

- [ ] **Step 1: Write the failing component test**

Mirror the label list page test if one exists (`grep -rln "LibraryListPage\|LabelsTable" frontend/src/**/*.test.tsx`). Create `ArtistsListPage.test.tsx`: render with a mocked `useArtistsList` returning 2 artists, assert their names render in `ArtistsTable`, and assert columns include country + active_since (NOT founded_year). Run → FAIL.

- [ ] **Step 2: Enable the artists tab in `EntityTabs.tsx`**

Replace the disabled/coming-soon artists tab:
```tsx
<Tooltip label={t('library.entity_tabs.artists_coming_soon')}>
  <Tabs.Tab value="artists" data-disabled disabled>
    {t('library.entity_tabs.artists')}
  </Tabs.Tab>
</Tooltip>
```
with an enabled tab that navigates to `/library/${styleId}/artists`:
```tsx
<Tabs.Tab value="artists">{t('library.entity_tabs.artists')}</Tabs.Tab>
```
and extend the tab-change handler to navigate to the artists route when `value === 'artists'` (mirror how it navigates for 'labels'). Read the current `EntityTabs` to match its navigation pattern exactly.

- [ ] **Step 3: Add routes in `router.tsx`**

In the `library` children (beside `:styleId/labels/:labelId`), add:
```tsx
{ path: ':styleId/artists', element: <ArtistsListPage /> },
{ path: ':styleId/artists/:artistId', element: <ArtistDetailPage /> },
```
Import `ArtistsListPage` (Task 3) and `ArtistDetailPage` (Task 4). (If Task 4 isn't done yet when wiring this, import it but note the file is created in Task 4 — the route will only resolve once Task 4 lands; keep both in this step or split the detail route into Task 4. Recommended: add the list route here, the detail route in Task 4.)

- [ ] **Step 4: Write `ArtistsListPage` + `ArtistsTable` + `ArtistCard`**

Copy `LibraryListPage.tsx` → `ArtistsListPage.tsx`: swap `useLabelsList`→`useArtistsList`, `Label`→`Artist`, render `ArtistsTable`/`ArtistCard`, `EntityTabs` value `artists`. **Omit the `my` preference filter UI** (2C) — keep `q`/`sort`/`page` (default `my='all'`, not surfaced).
Copy `LabelsTable.tsx` → `ArtistsTable.tsx`: columns name, country, **active_since** (not founded year), track_count, AI detected (reuse AI badge display), description. **Omit the preference column** (2C). Link rows to `/library/:styleId/artists/:artistId`.
Copy `LabelCard.tsx` → `ArtistCard.tsx`: name, country, tagline, primary_styles badges, enrichment status; link to the artist detail route.
Add the i18n keys these need (mirror the label keys into `library.artists.*` or reuse generic ones).

- [ ] **Step 5: Run the test → PASS.** Type-check clean. Sanity: `cd <repo>/frontend && pnpm test -- src/features/library 2>&1 | tail -5` (label library tests unbroken).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/library/components/EntityTabs.tsx frontend/src/routes/router.tsx frontend/src/features/library/routes/ArtistsListPage.tsx frontend/src/features/library/components/ArtistsTable.tsx frontend/src/features/library/components/ArtistCard.tsx frontend/src/**/*.test.tsx frontend/src/**/locales/**
git commit -m "feat(artist-enrich): add Library artists list + enable entity tab"
git log -1 --format='%H %s'
git status --short
```

---

## Task 4: Library artist detail page

**Files:**
- Create: `frontend/src/features/library/routes/ArtistDetailPage.tsx`
- Create: `frontend/src/features/library/components/ArtistDetailHeader.tsx` + the artist overview/styles/channel-links sub-components (mirror the label ones)
- Modify: `frontend/src/routes/router.tsx` (the `:styleId/artists/:artistId` route, if not added in Task 3)
- Test: `ArtistDetailPage.test.tsx` (jsdom)

- [ ] **Step 1: Write the failing test**

Create `ArtistDetailPage.test.tsx`: render with mocked `useArtistDetail` returning an artist (country, active_since, bio, notable_collaborators, ai_content=confirmed, the channel urls). Assert: name renders, the AI badge shows (colored per `confirmed`), active_since renders (not founded_year), notable collaborators render, and the channel links render the artist URLs (spotify/soundcloud/etc.). Run → FAIL.

- [ ] **Step 2: Write the detail components**

Copy `LabelDetailPage.tsx` → `ArtistDetailPage.tsx` (swap `useLabelDetail`→`useArtistDetail`, render the artist header + tabs + links).
Copy `LabelDetailHeader.tsx` → `ArtistDetailHeader.tsx`: keep the `AI_COLOR` map + tooltip-on-`ai_reasoning` AI badge; show country + **active_since** (not founded_year). **Omit the preference buttons** (2C — `ArtistDetailHeader` renders without them for now; 2C adds `ArtistPreferenceButtons`).
Copy the label overview tab → artist overview (summary, bio, notable_collaborators), styles tab → primary_styles, channel-links → the 9 artist URLs (spotify/soundcloud/bandcamp/beatport/residentadvisor/discogs/instagram/twitter/website). Add the i18n keys.

- [ ] **Step 3: Ensure the detail route exists** in `router.tsx` (`:styleId/artists/:artistId` → `ArtistDetailPage`); if added in Task 3, confirm the import now resolves.

- [ ] **Step 4: Run the test → PASS.** Type-check clean. Library suite green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/library/routes/ArtistDetailPage.tsx frontend/src/features/library/components/ArtistDetailHeader.tsx frontend/src/features/library/components/Artist*.tsx frontend/src/routes/router.tsx frontend/src/**/*.test.tsx frontend/src/**/locales/**
git commit -m "feat(artist-enrich): add Library artist detail page"
git log -1 --format='%H %s'
git status --short
```

---

## Done criteria for plan 2A

- Bucket-tracks response carries `artists: [{id,name,role}]`; the triage frontend type + display updated; curation/triage suite green.
- `api/artists.ts` + `useArtistsList`/`useArtistDetail`/`useArtistInfo` resolve against the worktree `schema.d.ts`; type-check clean.
- The Library "artists" tab is enabled; `/library/:styleId/artists` lists enriched artists (name/country/active_since/AI/description) and `/library/:styleId/artists/:artistId` shows the detail (header + AI badge + bio + collaborators + channel links). No preference UI yet.
- Label Library tests remain green; no `pnpm dev`/deploy.

## Next: 2B (admin) then 2C (player panel + preferences)

2B: enable the `artists` tab in `AdminAutoEnrichPage` (`ArtistsTab` + reused `EnrichConfigForm`), artist backlog `/admin/artists/enrich` (reuse `BacklogToolbar`/`BacklogTable`/`EnqueueDrawer`) + runs pages + hooks (`useArtistBacklog`, `useEnqueueArtistEnrichment`, artist auto-config hooks) + routes. 2C: the player `ArtistsPanel` (main `ArtistTile` card + chips for every other artist) on the three players below the label info, `ArtistPreferenceButtons` + `useSetArtistPreference`, the "my artists" filter, AI-badge polish; jsdom + **browser tests** (`pnpm test:browser`) for the panel layout. Then PR all of SP2.

# Artist Enrichment — Frontend (Design Spec, sub-project 2)

**Date:** 2026-05-27
**Status:** Approved for planning
**Sub-project:** 2 of 2. SP1 (backend + auto-dispatch) shipped (PR #150, deployed). SP2 is the React frontend that consumes the artist API SP1 exposed.

## Goal

Surface artist enrichment in the CLOUDER SPA at parity with labels: an admin tab + manual backlog/enqueue, a Library artists list + detail, an artist info panel on every player below the label info, user preferences, and the AI badge. Mirror the proven label-enrichment frontend; the genuinely new piece is the multi-artist player panel (a track has several artists).

## Scope

- **Small backend touch (in plan 2A):** add `artists: [{id, name, role}]` to the triage bucket-tracks response so the triage player can resolve artist ids (it currently carries only artist names). Regenerate `frontend/src/api/schema.d.ts`.
- **Frontend** (Vite + React 19 + Mantine 9, `frontend/src`):
  - API client + types (`api/artists.ts`) + react-query hooks mirroring the label hooks.
  - Library: enable the `artists` tab in `EntityTabs`; artists list page + detail page + table/card; "my artists" filter.
  - Player: an `ArtistsPanel` (main artist as a full `ArtistTile` card + every other artist as a chip) below the label info on `BucketPlayerPanel`, `CategoryPlayerPanel`, `PlaylistPlayerPanel`.
  - Admin: enable the `artists` tab in `AdminAutoEnrichPage` (auto-config) + artist backlog/enqueue/runs pages.
  - Preferences: like/dislike buttons + hook; "my artists" filter.
  - AI badge: reuse the label pattern.

## Non-goals

- No new backend enrichment logic (SP1 shipped it). The only backend change is exposing artist ids on the bucket-tracks response.
- No redesign of the label UI; artist components are parallel additions following existing patterns.

## Decisions (from brainstorming)

| Decision | Choice |
|---|---|
| Architecture | Mirror the label frontend with parallel artist components; reuse `EnrichConfigForm`/`EnqueueDrawer`/`BacklogTable`/AI-badge + query patterns. Reject entity-generic refactor (risk to working UI). |
| Multi-artist player layout | **Panel B**: main artist = full `ArtistTile` card; all other artists (feat/producer/remixer) = compact chips (name + AI badge, expand on click). **All** non-main artists as chips (no cap). |
| Player surfaces | All three players (Bucket, Category, Playlist), panel below the label info. |
| Triage data gap | **Small backend touch in 2A** — add artist `{id,name,role}` to the bucket-tracks response → full panel on every player. |
| Playlist player | Full `ArtistsPanel` (artist detail needs no styleId), even though it has no `LabelTile`. |
| Admin / Library / preferences | Full parity with labels (decided in SP1 brainstorm). |

## Architecture

Parallel `artist`-prefixed components mirroring the label ones, under the same feature folders (`features/library`, `features/admin`, and the three player feature folders). Reuse, don't fork, the entity-agnostic pieces: `EnrichConfigForm`, `EnqueueDrawer`, `BacklogTable`/`BacklogToolbar`, the AI-badge markup, the `api<T>()` client, and the react-query `useQuery`/`useMutation` patterns. The one new component is `ArtistsPanel` (main card + chips); `ArtistTile` itself mirrors `LabelTile`.

Types come from the SP1-generated `frontend/src/api/schema.d.ts` (`paths['/artists']`, `paths['/admin/artists/enrich']`, etc.), extracted in a new `frontend/src/api/artists.ts` exactly like `api/labels.ts`.

## Components & surfaces

### 0. Backend touch (plan 2A)
The triage `BucketTrack` carries `artists: string[]` (names only). Category/Playlist carry `{id, name}`. Add artist `{id, name, role}` to the bucket-tracks response (the curation handler + its repository query already join the track's artists for names — extend to include ids + role) and update `useBucketTracks`'s `BucketTrack` type. Regenerate the OpenAPI + `schema.d.ts`.

### 1. API client + hooks
- `frontend/src/api/artists.ts`: `ArtistSummary`, `ArtistDetail`, `ArtistInfo`, `BacklogArtist`, `EnrichArtistsBody`, `ArtistsListResponse`, etc., extracted from `paths[...]`.
- Hooks (mirror label hooks 1:1): `useArtistsList`, `useArtistDetail`, `useArtistInfo`, `useSetArtistPreference` (optimistic, patches artistInfo + artistsList caches), `useAutoEnrichConfig`/`useSaveAutoEnrichConfig` (artists variant — parametrize by kind or add artist hooks), `useArtistBacklog`, `useEnqueueArtistEnrichment`. Query keys namespaced (`['library','artists',...]`, `['admin','artistBacklog']`, etc.).

### 2. Player `ArtistsPanel` (requirement 4)
New `ArtistsPanel` component: given a track's artists (ordered, with roles), render the **main** artist as a full `ArtistTile` (mirrors `LabelTile`: name, country, `active_since`, bio, notable collaborators, channel links, AI badge, preference buttons; data via `useArtistInfo(artistId)` → `GET /artists/{id}`) and **every** other artist as a compact chip (name + role + AI badge; click expands to its `ArtistTile`). Inserted below the label block on:
- `BucketPlayerPanel` (below `LabelTile`)
- `CategoryPlayerPanel` (below `LabelTile`)
- `PlaylistPlayerPanel` (below the inline label name; no `LabelTile` there)
`ArtistTile` is its own file (mirrors `LabelTile`), reused by `ArtistsPanel` and the chip-expand. Each artist's info is fetched independently (one `useArtistInfo` per rendered tile); chips fetch lazily on expand.

### 3. Library (requirement 3)
- `EntityTabs`: enable the `artists` tab (remove the disabled/coming-soon stub), navigate to `/library/:styleId/artists`.
- Routes (`routes/router.tsx`): `:styleId/artists` → `ArtistsListPage`; `:styleId/artists/:artistId` → `ArtistDetailPage`.
- `ArtistsListPage` mirrors `LibraryListPage`: filters `q`/`sort`/`page`/`my` + style; `useArtistsList`; renders `ArtistsTable` (columns: name, country, active_since, track_count, AI, preference, description) and/or `ArtistCard`.
- `ArtistDetailPage` mirrors `LabelDetailPage`: `ArtistDetailHeader` (AI badge, preference buttons, country/active_since) + overview tab (summary, bio, notable collaborators) + styles tab (primary_styles) + channel-links panel (the 9 artist URLs). Data via `useArtistDetail`.

### 4. Admin (requirement 1)
- `AdminAutoEnrichPage`: enable the `artists` tab (replace the coming-soon stub) with an `ArtistsTab` mirroring `LabelsTab` — `useAutoEnrichConfig`/`useSaveAutoEnrichConfig` (artists) + the reused `EnrichConfigForm`.
- Artist backlog page at `/admin/artists/enrich` (mirror `AdminEnrichmentBacklogPage`): reuse `BacklogToolbar`/`BacklogTable`/`EnqueueDrawer`/history drawer; `useArtistBacklog` (`GET /admin/artists/backlog`) + `useEnqueueArtistEnrichment` (`POST /admin/artists/enrich`). Point-wise enqueue with vendor settings via `EnqueueDrawer`.
- Runs pages `/admin/artists/enrich/runs[/:runId]` mirroring the label runs pages (`GET /admin/artists/enrich-runs[/{run_id}]`).
- Add the admin routes to `routes/router.tsx`.

### 5. Preferences
`ArtistPreferenceButtons` (mirror `LabelPreferenceButtons`) used in `ArtistTile`, `ArtistDetailHeader`, `ArtistsTable`; `useSetArtistPreference` (`PUT /artists/{id}/preference`, body `{status: liked|disliked|none}`, optimistic). "my artists" filter (`my=liked|disliked|unrated`) in `ArtistsListPage`.

### 6. AI badge
Reuse the label pattern: `ArtistTile` uses the outline white badge; `ArtistDetailHeader` uses the colored `AI_COLOR` map (`none_detected:green, unknown:gray, suspected:yellow, confirmed:red`) + a tooltip showing `ai_reasoning`. Factor the `AI_COLOR`/`formatAiContent` into a shared helper if it's currently duplicated; otherwise mirror.

## Testing

- **jsdom (`pnpm test`, vitest):** artist hooks (query/mutation, optimistic preference), `ArtistTile`/`ArtistsPanel` rendering (main card + chips, chip expand), `ArtistsListPage`/`ArtistDetailPage`, admin `ArtistsTab` + backlog/enqueue, with mocked `api<T>()`.
- **Browser (`pnpm test:browser`, `@vitest/browser` + Playwright, `*.browser.test.tsx`):** the `ArtistsPanel` layout on a player — this is a visual/layout change and jsdom applies no stylesheets (CLAUDE.md gotcha #11: verify visual/CSS/layout in a real browser, don't deploy-and-pray). Run locally (CI has no browser).
- The OpenAPI/`schema.d.ts` diff-check (from 2A's backend touch) must stay in sync.

## Decomposition (for the plan)

Split the SP2 plan into 3 sequential files (like SP1):
- **2A** — backend touch (bucket-tracks artist ids) + regen schema.d.ts; `api/artists.ts` + the read hooks; Library: `EntityTabs` enable, `ArtistsListPage`, `ArtistDetailPage`, `ArtistsTable`/`ArtistCard`, routes. End state: browse artists in Library.
- **2B** — admin: `ArtistsTab` in `AdminAutoEnrichPage`, artist backlog/enqueue/runs pages + hooks + routes. End state: admin can configure auto-enrich + manually enqueue.
- **2C** — player `ArtistsPanel` (panel B) on the three players, `ArtistTile`, `ArtistPreferenceButtons` + `useSetArtistPreference`, "my artists" filter, AI badge; jsdom + browser tests. End state: artist info on every player + preferences.

Each is independently testable. After 2C, finish + PR all of SP2, completing the artist-enrichment feature end to end.

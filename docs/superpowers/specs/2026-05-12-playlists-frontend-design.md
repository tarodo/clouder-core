# Playlists Frontend Design

**Date:** 2026-05-12
**Status:** Spec draft → awaiting user review → implementation plan
**Companion to:** [`2026-05-11-playlists-backend-design.md`](./2026-05-11-playlists-backend-design.md)

## Goal

Add a `Playlists` section to the CLOUDER SPA where the user manages user-owned
playlists: list view (table), detail view (metadata + ordered tracks + cover +
publish to Spotify), cross-feature track add from categories, and Spotify
track import. Frontend wraps the 14 backend routes already shipped on the
curation Lambda.

## Architecture

- Standalone feature folder `frontend/src/features/playlists/` following the
  established F1 feature-folder convention (`routes/`, `components/`, `hooks/`,
  `lib/`, `__tests__/`).
- Two top-level routes (`/playlists`, `/playlists/:id`) under the existing
  authenticated `AppShellLayout` (`requireAuth` loader). Added to AppShell nav
  between `Curate` and `Profile`.
- All server state via TanStack Query 5 with three keyspaces:
  `playlistsKey(search?)`, `playlistDetailKey(id)`, `playlistTracksKey(id)`.
- All mutations use optimistic updates where the operation is reversible
  (rename / description / public toggle / reorder / add track / remove track)
  and pessimistic for irreversible work (delete playlist, publish to Spotify).
- Toast UX mirrors categories: green success toast with inline `Undo` link
  for reversible operations; red error toasts for failures; modal confirms
  for destructive actions.
- One cross-feature touchpoint: the existing
  `frontend/src/features/categories/components/TrackRowActions.tsx` Menu gains
  an `Add to playlist ▶` submenu so the user can push a single track into
  any playlist without leaving the category view.

## Tech Stack

- React 19 + Mantine 9 + react-router 7 + TanStack Query 5 (existing).
- `@dnd-kit/core` + `@dnd-kit/sortable` for track reorder (already used by
  `CategoriesList`).
- Mantine `FileButton` from `@mantine/core` for cover upload (no extra
  dependency; `@mantine/dropzone` is **not** installed and adding it solely
  for this feature is unjustified). Pair with a click-target image preview
  to keep the UX dropzone-shaped without the package.
- `zod` for client schemas (already in repo).
- Vitest + MSW + jsdom for tests (existing).

## API Contract (recap)

Backend routes wired on the curation Lambda
(`POST /playlists`, `GET /playlists`, `GET /playlists/{id}`,
`PATCH /playlists/{id}`, `DELETE /playlists/{id}`,
`GET /playlists/{id}/tracks`, `POST /playlists/{id}/tracks`,
`DELETE /playlists/{id}/tracks/{track_id}`,
`POST /playlists/{id}/tracks/order`,
`POST /playlists/{id}/cover/upload-url`,
`POST /playlists/{id}/cover/confirm`,
`DELETE /playlists/{id}/cover`,
`POST /playlists/{id}/tracks/import-spotify`,
`POST /playlists/{id}/publish`).

`schema.d.ts` types these as `Record<string, never>` (openapi-ts does not
introspect inline response shapes). Strong TS types live in
`frontend/src/features/playlists/lib/playlistTypes.ts` and mirror the backend
Pydantic payloads from `src/collector/curation/schemas.py` plus the
serializers in `_playlist_response` / `_playlist_track_response`.

### Type sketch

```ts
// playlistTypes.ts
export interface Playlist {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  cover_s3_key: string | null;
  cover_url: string | null;          // presigned GET, may be null
  cover_uploaded_at: string | null;  // ISO8601
  spotify_playlist_id: string | null;
  last_published_at: string | null;
  needs_republish: boolean;
  track_count: number;
  created_at: string;
  updated_at: string;
}

export interface PlaylistTrack {
  track_id: string;
  position: number;
  added_at: string;
  title: string;
  spotify_id: string | null;
  isrc: string | null;
  length_ms: number | null;
  origin: 'beatport' | 'spotify';
}

export interface PaginatedPlaylists {
  items: Playlist[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export interface AddTracksResult {
  added: string[];
  skipped_duplicates: string[];
  position_after: number;
}

export interface ImportSpotifyResult {
  added: { track_id: string; spotify_id: string; title: string }[];
  skipped: { ref: string; reason: 'invalid_ref' | 'not_found' | 'already_in_playlist' }[];
  position_after: number;
}

export interface PublishResult {
  spotify_playlist_id: string;
  spotify_url: string;
  skipped_tracks: { track_id: string; title: string; reason: string }[];
  cover_failed: boolean;
  published_at: string;
}
```

## Routes & Navigation

```
/playlists                — list view
/playlists/:id            — detail view
```

Both nested under `<AppShellLayout>` with `requireAuth`. Added to `NAV_ITEMS`
in `frontend/src/routes/_layout.tsx`:

```ts
{ path: '/playlists', labelKey: 'appshell.playlists', Icon: IconPlaylist }
```

Position: between `/curate` and `/profile`. i18n key
`appshell.playlists = "Playlists"`.

`router.tsx` additions:

```tsx
{
  path: 'playlists',
  children: [
    { index: true, element: <PlaylistsListPage /> },
    { path: ':id', element: <PlaylistDetailPage /> },
  ],
},
```

## Feature folder layout

```
frontend/src/features/playlists/
├── routes/
│   ├── PlaylistsListPage.tsx
│   ├── PlaylistDetailPage.tsx
│   └── __tests__/
│       ├── PlaylistsListPage.test.tsx
│       └── PlaylistDetailPage.test.tsx
├── components/
│   ├── PlaylistsTable.tsx
│   ├── PlaylistRow.tsx
│   ├── PlaylistFormDialog.tsx        # create / rename / edit description
│   ├── PlaylistMetaPanel.tsx         # detail-page header inline-editable fields
│   ├── PlaylistTracksList.tsx        # dnd-kit reorder
│   ├── PlaylistTrackRow.tsx
│   ├── PlaylistTrackRowActions.tsx
│   ├── CoverPicker.tsx               # dropzone + presigned PUT flow
│   ├── PublishButton.tsx
│   ├── PublishConfirmModal.tsx
│   ├── PublishResultModal.tsx        # shows skipped_tracks + cover_failed warnings
│   ├── ImportSpotifyModal.tsx
│   ├── AddTracksModal.tsx            # picker across user's categories
│   ├── DriftBadge.tsx                # yellow "Needs republish" pill
│   └── __tests__/...
├── hooks/
│   ├── usePlaylists.ts
│   ├── usePlaylistDetail.ts
│   ├── usePlaylistTracks.ts
│   ├── useCreatePlaylist.ts
│   ├── usePatchPlaylist.ts
│   ├── useDeletePlaylist.ts
│   ├── useAddTracksToPlaylist.ts
│   ├── useRemoveTrackFromPlaylist.ts
│   ├── useReorderPlaylistTracks.ts
│   ├── useImportSpotifyTracks.ts
│   ├── usePublishPlaylist.ts
│   ├── useUploadCover.ts             # 3-step orchestration
│   ├── useClearCover.ts
│   └── __tests__/...
├── lib/
│   ├── playlistSchemas.ts            # zod schemas (name, description, cover)
│   ├── spotifyRefParse.ts            # mirror of backend parser
│   ├── playlistTypes.ts              # see Type sketch
│   ├── queryKeys.ts
│   └── __tests__/spotifyRefParse.test.ts
└── index.ts                          # public re-exports
```

## Component Designs

### List page (`PlaylistsListPage.tsx`)

Mantine `Table` (responsive — collapses to card list on mobile, mirrors
categories `CategoriesList`). Columns:

| Cover (40×40 thumb) | Name (link) | Tracks | Public | Spotify | Updated | ⋮ |

- Cover thumb: `Avatar` with `cover_url`; placeholder icon if null.
- Name: `<Anchor component={Link} to={\`/playlists/\${id}\`}>` (use
  `c="var(--color-fg)"`, `td="none"` per Mantine link-styling gotcha).
- Public column: `IconLockOpen` / `IconLock` icon.
- Spotify column: `IconBrandSpotify` if `spotify_playlist_id != null`, plus
  `<DriftBadge />` if `needs_republish === true`.
- Updated: relative date (`Intl.RelativeTimeFormat`).
- `⋮ menu`: Rename, Edit description, Delete (red, confirm modal).

**Header controls:**
- Title `Playlists` (Mantine `Title order={1}`).
- `TextInput` search (300ms debounce, `IconSearch` left section, clearable),
  passed as `?search=` to `GET /playlists`.
- `Button leftSection={<IconPlus />}` "Create playlist" → opens
  `PlaylistFormDialog mode="create"`.

**Pagination:** `limit=20` default. "Load more" button at bottom while
`items.length < total`. Same pattern as categories tracks.

**Empty state:** centered placeholder + "Create your first playlist" CTA.

**Error handling:**
- `409 playlist_name_conflict` (create / rename) → inline error in
  `PlaylistFormDialog`.
- `429 playlist_limit_reached` → red toast "Playlist limit reached
  (200 max)".
- Generic 5xx → red toast "Something went wrong".

### Detail page (`PlaylistDetailPage.tsx`)

```
Breadcrumbs: [Playlists] › <name>

┌─────────────────────────────────────────────────────┐
│ ┌─────────┐  <name> (h1, click→inline edit)         │
│ │  Cover  │  <description> (Textarea, blur saves)   │
│ │ 160×160 │  [Switch] Public                        │
│ └─────────┘  N tracks · Updated 2h ago              │
│ [Replace]    [Publish to Spotify ↻DriftBadge] [⋮]   │
│ [Remove]                                            │
└─────────────────────────────────────────────────────┘

[+ Add tracks ▼]  [Import from Spotify]  [Search tracks…]

┌─────────────────────────────────────────────────────┐
│ ≡ 1. Title — Artist                3:42 [↗] [⋮]    │
│ ≡ 2. ...                                            │
└─────────────────────────────────────────────────────┘
```

**Header (`PlaylistMetaPanel`):**
- `<CoverPicker />` on the left — square 160×160 with current cover or
  placeholder. Buttons below: `Replace`, `Remove` (red, confirm).
- Inline-edit name: click on title → `<TextInput>` → `Enter`/`blur` triggers
  `PATCH /playlists/{id}`. Escape cancels. Validation via
  `playlistSchemas.name` (1-100 chars).
- Inline-edit description: similar pattern with `<Textarea autosize>`.
- `<Switch>` Public/Private — onToggle sends `PATCH`.
- Stats: `track_count` + relative `updated_at`.
- `<PublishButton />` — see Publish section below.
- Header `⋮ menu`: Delete playlist (red, confirm), Edit name, Edit
  description.

**Tracks toolbar:**
- `Add tracks ▼` button → `<AddTracksModal />`.
- `Import from Spotify` button → `<ImportSpotifyModal />`.
- Search `TextInput` — filters loaded tracks client-side by title/artist.
  Server-side search not in `GET /playlists/{id}/tracks` contract.

**Tracks list (`PlaylistTracksList`):**
- dnd-kit `<DndContext>` + `<SortableContext>` (same wiring as
  `CategoriesList`).
- Each row (`PlaylistTrackRow`): drag handle `IconGripVertical`, position
  number, title, artist (joined from `artists[]` if present — note: backend
  serializer currently only exposes `title`, drop artist if not present and
  open follow-up to add it server-side), duration `mm:ss`, origin badge
  (`Beatport` grey / `Spotify` green), external link `IconExternalLink` to
  `https://open.spotify.com/track/{spotify_id}` if `spotify_id`, `⋮ menu`.
- `⋮ menu`: Remove from playlist (red).
- Optimistic reorder: snapshot tracks → reorder in cache → fire
  `POST /tracks/order`. On `400 order_mismatch` → rollback + invalidate +
  toast "Tracks changed elsewhere, please retry".

**Empty tracks state:** "No tracks yet — add from a category or import
from Spotify". Two inline CTAs duplicating the toolbar buttons.

### `PlaylistFormDialog`

Mantine `Modal` mode `create | rename | edit-description`:
- create: name + description + public switch.
- rename: name only.
- edit-description: description only.

Submit: `useCreatePlaylist` / `usePatchPlaylist`. Errors:
- 400 validation → field-level error.
- 409 name_conflict → set `serverError` on `name` field (mirrors
  categories pattern).

### `CoverPicker`

- Inline thumbnail + Replace/Remove buttons.
- Replace flow:
  1. Hidden `<FileButton accept="image/jpeg,image/png">` triggered by the
     visible Replace button. Client-side guard: reject files where
     `file.type` is not `image/jpeg`/`image/png` or `file.size > 262_144`
     (mirrors backend `MAX_COVER_BYTES = 262_144` and `content_type` enum).
  2. On accept: call `useUploadCover` hook which orchestrates the 3-step
     flow (presign → PUT → confirm). Show progress indicator.
  3. Optimistic: do NOT update preview until step 3 succeeds (else stale
     blob URL leaks).
- Remove flow: confirm modal → `DELETE /playlists/{id}/cover`.
- Errors:
  - 400 `cover_too_large` → toast "Cover too large (max 256 KB)" + reset.
  - 400 `cover_missing` (rare; S3 PUT failed silently) → toast "Upload
    failed, retry".
  - presigned PUT network error → toast + reset.
- After confirm: server returns updated playlist; `setQueryData` on detail
  cache. New `cover_url` includes fresh `epoch_ms` so the browser will not
  reuse the prior image's cached copy.

### `PublishButton` + `PublishConfirmModal`

Three states driven by `spotify_playlist_id` + `needs_republish`:

| spotify_playlist_id | needs_republish | Label                           |
|---------------------|-----------------|---------------------------------|
| null                | —               | "Publish to Spotify"            |
| set                 | false           | "Re-publish to Spotify"         |
| set                 | true            | "Re-publish to Spotify" + drift |

Click behavior:
- First publish (`spotify_playlist_id === null`): direct
  `POST /publish` with `{confirm_overwrite: false}`. Loading spinner on
  button.
- Re-publish: open `PublishConfirmModal` with body explaining the
  overwrite scope (`This will overwrite the existing Spotify playlist
  '<name>'. <N> CLOUDER tracks will fully replace its current contents,
  along with the cover and description.`). On confirm →
  `POST /publish` with `{confirm_overwrite: true}`.
- Loading state: button shows `Loader` + disabled. API GW 29s timeout
  scenario: if request rejects with network error / 503, surface a toast
  "Backend warming up, retry in a moment" with retry CTA. (No automatic
  recovery scheduler — first publish is interactive.)

After success:
- `invalidateQueries(playlistDetailKey(pid))` to pick up new
  `spotify_playlist_id`, `last_published_at`, `needs_republish=false`.
- Green toast with inline `Open in Spotify` external link
  (`result.spotify_url`).
- If `skipped_tracks.length > 0`: open `PublishResultModal` listing
  skipped tracks with their reason.
- If `cover_failed === true`: yellow toast "Tracks updated. Spotify
  rejected the cover — try Replace and re-publish."

Errors:
- 400 `confirm_overwrite_required` (server saw stale `null` → race; a
  concurrent publish happened) → reopen `PublishConfirmModal` after
  refetch.
- 412 `spotify_not_authorized` → toast "Spotify isn't linked — sign in
  again" with `Re-link` CTA navigating to `/profile`.
- 502 `spotify_upstream_error` → toast with retry CTA.

### `DriftBadge`

Yellow `Mantine Badge` with `IconAlertTriangle` and tooltip
"Tracks/cover changed since the last Spotify publish. Re-publish to push
the latest version."

### `ImportSpotifyModal`

- Mantine `Modal` size="lg".
- `Textarea` autosize, placeholder shows three sample formats (URL,
  URI, bare id), one per line.
- Client-side `parseSpotifyRef(line)` per non-empty line. Show inline
  per-line validation badges as the user types (debounced 300ms):
  - ✓ valid (id resolved).
  - ✗ invalid (reason).
- `Import` button enabled when at least one line parses + total
  ≤ 50 (matches backend `MAX_IMPORT_REFS_PER_REQUEST`).
- On submit: `POST /playlists/{id}/tracks/import-spotify` with
  `{spotify_refs: [...]}`.
- Response → render summary table inside the modal:
  - "Added (N)" — list of added titles.
  - "Skipped (M)" — ref + human-readable reason.
- Bottom buttons: `Close` (also invalidates `playlistTracksKey(pid)` +
  `playlistDetailKey(pid)`) and `Import more` (resets textarea).
- Errors:
  - 412 `spotify_not_authorized` → banner inside modal "Spotify not
    linked. Re-link in Profile." with link.
  - 502 `spotify_upstream_error` → retry button.
  - 400 `invalid_payload` (cap exceeded) → inline error.

### `AddTracksModal` (from categories)

Two-pane modal:
1. Left: Style + Category select (reusing `<StyleSelector />` and a new
   `<CategorySelector />` driven by `useCategoriesByStyle`).
2. Right: scrollable track list for the picked category, multi-select
   checkboxes, client-side search.
3. Bottom: `Add N tracks` button → `POST /playlists/{id}/tracks` with
   `{track_ids: [...]}`.

Constraints:
- Max 200 tracks per request (informal cap to keep payload light; backend
  cap from `playlists_service.MAX_TRACKS_PER_PLAYLIST = 1000` only applies
  to total playlist size, not single batches).
- `403 track_not_in_user_scope` (cross-user track) → toast "Some tracks
  unavailable" + list `missing_track_ids` from `ApiError.raw`.
- Duplicates server-side: `skipped_duplicates` returned in response → toast
  "N tracks were already in this playlist" alongside the success message.

After success:
- `invalidateQueries(playlistTracksKey(pid))` + detail.
- Modal closes.
- Green toast with `Undo` link (per added track UX) — undo issues
  `DELETE /playlists/{id}/tracks/{track_id}` for each `result.added`.

### Cross-feature: `Add to playlist` submenu

Extend `frontend/src/features/categories/components/TrackRowActions.tsx`
Menu with a new section:

```
Menu.Label: "Add to playlist"
  - <playlist 1>
  - <playlist 2>
  ...
  - <Anchor>Manage playlists…</Anchor>
```

Lazy-load playlists via `usePlaylists({ limit: 100 })` only when the menu
opens (gate the query with `enabled`). Clicking a playlist fires
`POST /playlists/{pid}/tracks` body `{track_ids: [trackId]}`. Toast pattern
matches existing categories track move flow (green + Undo).

If user has zero playlists, show `Menu.Item disabled` "No playlists yet"
with link to `/playlists`.

## Data Flow

### Query keys (`lib/queryKeys.ts`)

```ts
export const playlistsKey = (search?: string) =>
  ['playlists', search ?? null] as const;

export const playlistDetailKey = (id: string) =>
  ['playlists', id] as const;

export const playlistTracksKey = (id: string) =>
  ['playlists', id, 'tracks'] as const;
```

### Mutation patterns

**Optimistic (rename / description / public toggle):**
- Snapshot detail cache.
- `setQueryData(playlistDetailKey(pid), newState)`.
- On error: rollback snapshot + red toast.
- On success: server response replaces optimistic state (in case server
  normalized `name`).

**Optimistic (reorder):**
- Snapshot tracks cache.
- Apply reorder in cache.
- POST full ordered list.
- On 400 `order_mismatch`: rollback + invalidate (track set drifted).
- On success: leave optimistic state.

**Optimistic (add tracks single track from categories):**
- Append `track_id` to `playlistTracksKey(pid)` cache (need detail loaded
  too — increment `track_count`).
- On `skipped_duplicates` in response → no-op for that id (already in
  cache).
- On rollback → remove from cache.

**Optimistic (remove track):**
- Filter out track + decrement `track_count`.
- Toast Undo → re-POST with same `track_id`.

**Pessimistic (delete playlist):**
- Confirm modal first.
- On 204 → `removeQueries(playlistDetailKey(pid))` +
  `invalidateQueries(playlistsKey())`.
- Navigate back to `/playlists`.

**Pessimistic (publish):**
- Loading state on button.
- Refetch detail on success.

**Pessimistic (cover upload):**
- Multi-step orchestration; preview only flips after `confirm` returns.

### Cross-feature invalidations

- Track removed from a category — does NOT affect playlist membership
  (separate join table). Skip invalidation.
- Track tag changes — no impact on playlist tracks query (no tag filter
  exposed yet).
- User logout → reset all `playlists*` caches via existing
  `auth:expired` listener (TanStack `queryClient.clear()` already happens
  in `AuthProvider`).

## Error Handling Catalog

| Status | Code                          | UI                                                              |
|--------|-------------------------------|-----------------------------------------------------------------|
| 400    | `validation_error`            | Field-level error inside the relevant form.                      |
| 400    | `order_mismatch`              | Rollback reorder + toast "Tracks changed, retry".                |
| 400    | `cover_missing` / `cover_too_large` | Toast + reset upload state.                              |
| 400    | `confirm_overwrite_required`  | Reopen `PublishConfirmModal` with stale-state warning.           |
| 400    | `invalid_spotify_ref`         | Inline per-line in `ImportSpotifyModal`.                         |
| 403    | `track_not_in_user_scope`     | Toast + list missing ids from `ApiError.raw.missing_track_ids`.  |
| 404    | `playlist_not_found`          | EmptyState "Playlist not found" + back link.                     |
| 409    | `playlist_name_conflict`      | Inline `name` field error.                                       |
| 412    | `spotify_not_authorized`      | "Spotify not linked" toast/banner + Re-link CTA to `/profile`.   |
| 429    | `playlist_limit_reached`      | Red toast "Playlist limit reached (200 max)".                    |
| 502    | `spotify_upstream_error`      | Toast with retry CTA.                                            |
| 503    | (cold start)                  | Toast "Backend warming up" + retry CTA. No auto-recovery.        |

## Loading / Skeleton States

- List page: `FullScreenLoader` while initial query loads.
- Detail page: skeleton (cover placeholder + 4 row skeletons) while
  parallel queries (`detail`, `tracks`) load.
- Mutation buttons: replace label with `<Loader size="sm" />` during
  pending.

## Accessibility

- All Menus / Modals use Mantine defaults (focus trap + escape close).
- Drag handle on track rows has `aria-label="Drag to reorder"`.
- Cover Replace control is a regular button (visible label, focusable);
  no custom drag target gating means there is nothing keyboard-inaccessible.
- Inline-edit fields announce changes via `aria-live="polite"` on the
  parent stack.
- Color-only state (drift badge, origin badge) always carries a text
  label.

## i18n

New namespace `playlists.*` in `frontend/src/i18n/en.json`. Key groups:
- `playlists.list_title`, `playlists.create_cta`, `playlists.search_placeholder`,
  `playlists.table.*`, `playlists.empty.*`, `playlists.form.*`,
- `playlists.detail.title_placeholder`, `playlists.detail.publish_cta_first`,
  `playlists.detail.publish_cta_again`, `playlists.detail.drift_badge`,
  `playlists.detail.add_tracks`, `playlists.detail.import_spotify`,
- `playlists.cover.replace`, `playlists.cover.remove`,
  `playlists.cover.help_text` (size/format hint shown under the
  Replace button),
- `playlists.publish.confirm_title`, `playlists.publish.confirm_body`,
  `playlists.publish.result_skipped_title`, `playlists.publish.cover_failed`,
- `playlists.import.placeholder`, `playlists.import.added`,
  `playlists.import.skipped_*`,
- `playlists.add_tracks.title`, `playlists.add_tracks.add_n`,
- `playlists.toast.created/renamed/deleted/published/track_added/...`,
- `playlists.errors.name_conflict`, `playlists.errors.limit_reached`,
  `playlists.errors.spotify_not_authorized`,
  `playlists.errors.cover_too_large`, etc.

Add `appshell.playlists` and `categories.row_actions.add_to_playlist_label` /
`categories.row_actions.no_playlists`.

## Testing Strategy

Per existing convention:

- **Route tests** (`routes/__tests__/*.test.tsx`): render with MSW happy-path
  handlers, assert key UI surfaces present. One test per route.
- **Component tests** (`components/__tests__/*.test.tsx`): one test file per
  component covering its primary states + the most likely failure.
- **Hook tests** (`hooks/__tests__/*.test.ts`): cache invalidation, optimistic
  rollback on error, undo wiring (for add/remove).
- **Pure lib tests** (`lib/__tests__/spotifyRefParse.test.ts`): mirror the
  backend table-test in `tests/unit/test_playlists_service.py` —
  URL, URI, bare id, malformed inputs.
- **Cross-feature**: add a test in
  `frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx`
  asserting the new submenu appears with the user's playlists and that
  clicking one fires `POST /playlists/{pid}/tracks`.
- **Integration smoke test** (`__tests__/integration.playlists.test.tsx` at
  feature root): full happy-path — create playlist → upload cover → add
  tracks from a category → import a spotify ref → publish (first time) →
  drift after track removal → re-publish with confirm.

MSW handlers under `frontend/src/test/handlers/playlists.ts` exporting all
14 routes + a `resetPlaylistsState()` helper for between tests.

Pay attention to known frontend gotchas:
- `notifyManager.setScheduler(queueMicrotask)` already in `src/test/setup.ts`.
- jsdom shims for `ResizeObserver`, `scrollIntoView`, `getBoundingClientRect`
  already in place — Modal/Dropzone should work.
- Mantine portal singleton: scope queries via `within(await screen.findByRole('dialog'))`.
- MSW URLs use `http://localhost/...`.
- TanStack 5 query-key collisions: ensure `playlistsKey()` and
  `playlistDetailKey(id)` differ structurally so they do not share `queryFn`.

## Performance Considerations

- Detail page mounts two parallel queries (`detail`, `tracks`). Tracks query
  uses `limit=100` first page, `getNextPageParam` for infinite scroll
  using the existing `/tracks` pagination shape (offset/limit/total).
- Cover thumbnails on the list page reuse the same presigned GET URL
  returned by the server — `staleTime: 4 * 60 * 1000` so the 5-minute
  presign window does not expire mid-session unnoticed; on `staleTime`
  expiry the list refetches and gets fresh URLs.
- `AddTracksModal` track list is paginated per category — load 50 at a time,
  same as categories detail.

## Out of scope (YAGNI)

- Bulk operations on playlists (multi-select delete, multi-select move
  tracks).
- Playlist duplicate / clone.
- Track-level metadata edit from the playlist detail page.
- Server-side track search within a playlist (`GET /playlists/{id}/tracks`
  does not accept `?search=`; client-side filter on loaded rows is
  enough at 1000-track cap).
- Cross-playlist track move (the backend does not expose a transfer
  endpoint — multi-step add/remove is fine for v1).
- Drag-from-categories-page drop-on-playlist (the submenu satisfies the
  cross-feature add case).
- Share UI for `is_public=true` (no public discovery endpoint exists).
- Public/private semantics in the Spotify publish step are decoupled from
  CLOUDER `is_public` flag; we surface the CLOUDER flag only.

## Open follow-ups (not blocking)

- Backend `_playlist_track_response` currently omits `artists[]` and
  `label_name`. Reasonable to ship without; opens a tiny BE follow-up
  ticket to align with bucket track serializer.
- Cover URL versioning relies on `epoch_ms` filenames. If we later want
  to keep history, we should retain old `s3_key` rows.
- `usePlaylists({ limit: 100 })` from the categories submenu is unbounded
  — fine at 200 playlist user-cap; if cap rises, switch to autocomplete.

## Implementation order (high-level)

1. Foundation: routes, nav item, types, query keys, MSW handlers.
2. List page + create dialog + delete confirm.
3. Detail page header + inline-edit metadata + delete.
4. Cover upload (3-step orchestration).
5. Tracks list (read-only) + remove track + reorder (dnd-kit).
6. `AddTracksModal` from categories.
7. Categories `Add to playlist ▶` submenu (cross-feature touch).
8. `ImportSpotifyModal`.
9. Publish flow (button + confirm modal + result modal + drift badge).
10. i18n pass, accessibility pass, integration test.

Each step ships as its own task in the writing-plans output with TDD-first
test scaffolding.

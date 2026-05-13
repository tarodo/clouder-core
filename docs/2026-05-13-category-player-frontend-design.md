# Category Player — Design Spec

**Date:** 2026-05-13
**Status:** Approved (brainstorming)
**Branch:** `worktree-add_playlist_player`

## Goal

Inline player on the category detail page. User starts a track from a category, marks it (tags, playlists, remove) without leaving the page, auto-advances to the next track on natural end. Plays only on its own page; navigating away clears the queue. The triage MiniBar is retired in the same change.

## Non-goals

- Cross-page persistence of category playback.
- Mobile parity with Curate (fullscreen takeover only).
- Tag hotkeys.
- Multi-level undo (depth 1 only).
- Spotify-native queue manipulation (we keep the F6 per-track `play(uri)` model).

---

## Architecture

Reuse the singleton `PlaybackProvider` mounted in `frontend/src/routes/_layout.tsx`. A new `QueueSource` variant identifies category-bound playback so a single SDK player serves both Curate and Category.

```ts
// frontend/src/features/playback/lib/types.ts
export type QueueSource =
  | { type: 'bucket'; blockId: string; bucketId: string }
  | { type: 'category'; categoryId: string; styleId: string };
```

`hasPlayerCard(pathname)` extends to match `/categories/:styleId/:id`. The function name stays (was introduced for MiniBar gating, retained as a generic "this route owns playback" predicate).

### New files

| Path | Purpose |
|---|---|
| `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` | Left column composition: PlayerCard base + tag cloud + playlist cloud + Remove + hotkey wiring |
| `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx` | Chips for active playlists; first 10 carry `[1]…[0]` hotkey badges |
| `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` | Chips for all user tags; track-assigned ones rendered filled |
| `frontend/src/features/categories/hooks/useCategoryPlayerQueue.ts` | Reactive `bindQueue` against `useCategoryTracks` results |
| `frontend/src/features/categories/hooks/useUndoStack.ts` | Module-scoped depth-1 undo with toast wiring |
| `frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts` | Category-specific hotkey hook (1-0, U, A/S/D/F/G, J/K, Space); existing `usePlaybackHotkeys` (curate) stays untouched |

### Files modified

| Path | Change |
|---|---|
| `frontend/src/features/playback/lib/types.ts` | Extend `QueueSource` |
| `frontend/src/features/playback/routeContext.ts` | Add `CATEGORY_DETAIL` regex; export `hasCategoryPlayer`; keep `hasPlayerCard` truthy for both routes |
| `frontend/src/routes/_layout.tsx` | Remove `<MiniBar>` + `<LeaveContextDialog>` from `PlaybackChrome`. Keep `<DevicePickerSurface>`. |
| `frontend/src/features/categories/routes/CategoryDetailPage.tsx` | Add 2-column desktop layout, fullscreen takeover on mobile; mount `CategoryPlayerPanel` + `useCategoryPlayerQueue`; call `controls.prewarm()` on mount; call `controls.clearQueue()` on unmount |
| `frontend/src/features/categories/components/TracksTab.tsx` | Add "Fresh only" toggle (URL state `?fresh=0/1`, default on); add "Play" affordance per row (click row chevron / button); render `UsedInPlaylistBadge` |
| `frontend/src/features/categories/hooks/useCategoryTracks.ts` | Accept `fresh: boolean` param; thread to backend; surface `used_in_playlist` field |
| `frontend/src/features/playlists/hooks/useAddTracksToPlaylist.ts` | On success patch `['categories','tracks']` caches: set `used_in_playlist=true`; if active-source list filter is `fresh=true`, drop track from `items` (optimistic shrink) |
| `frontend/src/features/playlists/hooks/useRemoveTrackFromPlaylist.ts` | On success invalidate `['categories','tracks']` (cannot locally know if other playlists hold the track) |

### Files deleted

- `frontend/src/features/playback/MiniBar.tsx`
- `frontend/src/features/playback/MiniBar.module.css`
- `frontend/src/features/playback/LeaveContextDialog.tsx`
- `frontend/src/features/playback/__tests__/MiniBar.test.tsx`
- `frontend/src/features/playback/__tests__/LeaveContextDialog.test.tsx`

---

## UI

### Desktop layout (`min-width: md`)

```
+---------------------------------------------------------------+
|  Breadcrumbs / Title / Rename / Delete                        |
+---------------------------------------------------------------+
| PlayerPanel ~420px  | TracksTab (flex)                        |
|                     | - Search / Tag filter / Fresh toggle    |
| Cover               | - Tracks table:                         |
| Title / artists     |   row: cover · title · artists · tags   |
| Device picker icon  |        · bpm · length · used-badge · ⋯  |
| ──────────────────  |        click row → play, ⋯ menu actions |
| Seek bar            |                                         |
| Prev · Play · Next  |                                         |
| ──────────────────  |                                         |
| Tags (cloud, all)   |                                         |
| ──────────────────  |                                         |
| Playlists (cloud)   |                                         |
|  [1]Acid [2]Disco…  |                                         |
| ──────────────────  |                                         |
| Remove from cat     |                                         |
+---------------------------------------------------------------+
```

Pre-Play state (no current track): the left column shows a 420px-wide placeholder with a "Pick a track to start playing" message and a faint cover skeleton — same width so the right column doesn't reflow.

### Mobile layout (`< md`)

Tracks list is rendered as before (current `TracksTab` mobile cards). Tapping a track Play affordance navigates to a fullscreen player route: `/categories/:styleId/:id/player`. Back arrow returns to the list; playback continues (no `clearQueue` on this back navigation — the back stays within the same `CategoryDetailPage`).

> Why a child route, not a modal: AppShell footer nav must vanish in player mode; a router-driven page swap is cleaner than imperative shell-state toggles.

### Tag cloud

Source: `useTags()` (all user tags). Sort: by `name` ASC. Rendering:
- Tags currently assigned to the playing track: filled `Chip` in the tag's color.
- Tags NOT assigned: outline `Chip`.

Click toggles assignment (calls `useAddTrackTag` / `useRemoveTrackTag`). No hotkeys. Empty state when user has zero tags: link to TagsManagerModal.

### Playlist cloud

Source: `usePlaylists({ status: 'active' })` sorted by `created_at ASC` (matches the playlists page default). First 10 carry a small leading badge `[1]…[9]` then `[0]`. Track-already-in-playlist chips: filled (Mantine theme primary). Others: outline. Click adds; clicking a filled chip removes.

Order is stable per user across renders because `created_at` is immutable. Adding a new playlist appends it at position N+1; if there were fewer than 10 it gets a fresh hotkey on next mount.

Empty state when no active playlists: link to `/playlists` and dismissable hint.

### Remove from category

Single danger-tinted button at the bottom of the left column: "Remove from category". Optimistic remove (existing `useRemoveTrackOptimistic`), then push undo entry. **Current-track behavior: continue playing** (no pause). Natural-end advance lands on the next track in the (post-shrink) queue.

### Used-in-playlist badge

A subtle gray `Badge` ("In playlist") rendered in a dedicated table column AND on each cloud chip when the track is in it. Backed by the new `used_in_playlist` boolean.

### Fresh-only toggle

A `Switch` next to the tags filter in `TracksTab`. URL state: `?fresh=0` to disable; absent or `?fresh=1` = default on. Tooltip explains: "Hide tracks already used in any playlist."

---

## Data flow

### Backend changes

`GET /categories/:id/tracks` accepts a new optional `fresh` query parameter:
- Values: `fresh=1` enables the filter, `fresh=0` disables. **Absent → disabled** (backward-compatible: existing clients without the param see all tracks, as today).
- The new UI always sends an explicit value: default ON from the toggle → `?fresh=1`; toggled off → `?fresh=0`.
- Backend SQL adds an `EXISTS … playlist_tracks JOIN playlists` sub-select projected as `used_in_playlist BOOL`. When `fresh=1`, an extra `AND NOT EXISTS(…)` is applied.

To keep the SQL builder readable, hoist the sub-select into a CTE-like fragment used both in projection and in the WHERE.

`src/collector/curation/categories_repository.py:list_tracks` extends:
- New kwarg `fresh: bool = False` (default false → old behavior unchanged).
- New projected column `used_in_playlist: bool` always returned in the row.

Handler (`src/collector/curation_handler.py: _handle_list_tracks`) parses `?fresh=` → bool (`"1"` → `True`, `"0"` or absent → `False`).

OpenAPI: regenerate `docs/openapi.yaml` after editing `scripts/generate_openapi.py:ROUTES`.

### Frontend cache patching

Add-to-playlist mutation:
```ts
onSuccess: (_, { trackIds, playlistId }) => {
  // Update all category-tracks caches: set used_in_playlist=true for affected.
  queryClient.setQueriesData<InfiniteData<PaginatedTracks>>(
    { queryKey: ['categories', 'tracks'], type: 'active' },
    (data) => data && {
      ...data,
      pages: data.pages.map((page) => ({
        ...page,
        items: page.items
          .map((it) => trackIds.includes(it.id) ? { ...it, used_in_playlist: true } : it)
          // Shrink for fresh-on caches: filter affected items out.
          .filter((it) => !(getFreshFlagFromKey(queryKey) && trackIds.includes(it.id) && it.used_in_playlist === true)),
      })),
    }
  );
  queryClient.invalidateQueries({ queryKey: ['playlists', playlistId, 'tracks'] });
}
```

Helper `getFreshFlagFromKey(queryKey)` reads the `fresh` slot from the cache key tuple. The key tuple grows from `(id, search, sort, order, tagIds, tagMatch)` to `(id, search, sort, order, tagIds, tagMatch, fresh)`.

### Queue binding

`useCategoryPlayerQueue(categoryId, tracksList)`:
- On every `tracksList` identity change, compute next cursor preserving the currently-playing track id if still present, else clamp to 0.
- Call `playback.controls.bindQueue({ source: { type: 'category', categoryId, styleId }, tracks, cursor })`.
- On unmount: `controls.clearQueue()`.

### Spotify auto-advance

No new code. The F6 mechanism in `PlaybackProvider.player_state_changed` detects URI mismatch after natural track end and calls `advanceRef.current?.(+1)`. `findNextPlayable` skips null-spotify-id tracks. The category queue plugs into this with zero extra work.

---

## Hotkeys

`useCategoryPlayerHotkeys(playlistsTop10, panelApi)`:

| Key | Action | Notes |
|---|---|---|
| `Space` | togglePlayPause | Existing |
| `J` | prev | Mirror curate |
| `K` | next | Mirror curate |
| `A`/`S`/`D`/`F`/`G` | seek to 0/25/50/75/100% | Existing helper |
| `Digit1`…`Digit9, Digit0` | toggle current track in `playlists[0..9]` | Index 9 = `Digit0` |
| `U` | undo last action | Pop undo stack |
| `?` (event.key) | toggle hotkey help overlay | Optional; cheap |

Activation rules:
- Hook subscribes only when `playback.queue.source?.type === 'category'`.
- Skip when `event.target` matches `input, textarea, select, [contenteditable]`.
- Match letters/digits via `event.code` (layout-safe).

Existing `usePlaybackHotkeys` (curate) is unchanged; category hotkeys live in a parallel hook.

---

## Undo model

Depth-1 stack, module-scoped, no React state mirror (subscribers via tiny event emitter — same pattern as `tokenStore`).

```ts
interface UndoEntry {
  id: string;
  label: string;             // i18n key already resolved
  undo: () => Promise<void>;
}

export const undoStack = {
  push(entry: UndoEntry): void,
  popAndRun(): Promise<void>,
  peek(): UndoEntry | null,
  subscribe(cb: () => void): () => void,
};
```

Wired actions:

| Action | `label` template |
|---|---|
| Add to playlist | "Added to {name}" |
| Remove from playlist | "Removed from {name}" |
| Add tag | "Tagged: {tag}" |
| Remove tag | "Untagged: {tag}" |
| Remove from category | "Removed from {category}" |

On every `push`:
- If a previous notification exists, `notifications.hide(prevId)`.
- `notifications.show({ id, message: label, autoClose: 8000, action: { label: 'Undo', onClick: () => undoStack.popAndRun() } })`.

`U` hotkey calls `undoStack.popAndRun()` — same path.

The `undo` callback restores prior optimistic-cache state. Each mutation hook captures the pre-mutation snapshot inside `onMutate` (TanStack Query pattern) and stores it in the closure passed to `push`.

---

## Edge cases

| Case | Behavior |
|---|---|
| Track with `spotify_id == null` | Play button disabled; auto-advance skips (existing `findNextPlayable`) |
| Active device offline | `queue.status === 'disconnected'`; PlayerCard error region invites picker open (F7 behavior, unchanged) |
| Empty queue under fresh-on | Empty-state in tracks table with link "Disable Fresh-only" toggling URL state |
| Cursor after optimistic shrink | Preserve current track id; if last item removed, clamp cursor to `max(0, len-1)`; do not start playback |
| Current track removed from category | Track continues playing (Spotify session unchanged); shrink removes from queue; advance to next on natural end |
| Fresh-toggle flip while playing | Rebind queue with new filtered list; current track may not be in the new list — keep playing until natural end; advance picks from new list |
| Two browser tabs on same category | SDK device_id conflict (known F6 limitation; not regressed) |
| User adds to playlist with hotkey `5` but only 4 playlists exist | No-op silently; help overlay shows active key range |

---

## Tests

### Unit
- `useUndoStack`: push / pop / replace / subscribe / unsubscribe.
- `useCategoryPlayerHotkeys`: each key, input-skip, source-gate.
- `useCategoryPlayerQueue`: rebind preserves cursor, clamps on shrink, clears on unmount.
- Backend `list_tracks(fresh=true)`: `EXISTS` filter, `used_in_playlist` projection, combination with `tags`+`search`+`sort`.

### Integration (vitest + msw + jsdom)
- Click track row → bindQueue called with category source, cursor at clicked index → SDK preWarm → play.
- Hotkey `1` → optimistic shrink (fresh on), `used_in_playlist=true` (fresh off), toast appears with Undo.
- `U` → undo runs → list state restored → toast hides.
- Remove-from-category on currently-playing track → continues playing → SDK URI-mismatch event → next track plays.
- Mocked SDK URI-mismatch → auto-advance.
- Navigate away from `/categories/:styleId/:id` → `clearQueue` called once.
- Mount triage (curate) page → no MiniBar element in DOM after F6 deletion.

### Out of scope (E2E)
- Real Spotify SDK boot — covered by manual smoke against staging.

---

## Implementation order

1. **Backend:** `fresh` filter + `used_in_playlist` projection + `list_tracks` repository test.
2. **Frontend types + routes:** extend `QueueSource`, update `routeContext`, regenerate `schema.d.ts` if needed.
3. **MiniBar deletion + LeaveContextDialog deletion:** small focused PR; remove imports; delete files + tests; verify curate still works (player-card-only).
4. **`useUndoStack` + `useCategoryPlayerQueue` + `useCategoryPlayerHotkeys`:** isolated hooks with unit tests.
5. **`CategoryPlayerPanel`:** composition + tag cloud + playlist cloud + remove + integration.
6. **`CategoryDetailPage`:** 2-column desktop layout + mobile child route `/categories/:styleId/:id/player`.
7. **Cache patching for add-to-playlist:** mutation hooks update categories cache.
8. **Polish:** loading states, empty states, error toasts, hotkey help overlay.

---

## CLAUDE.md additions (post-implementation)

- New `QueueSource.type === 'category'` variant — extend any `switch` exhaustively.
- Undo stack depth 1; `notifications.hide` replaces prior toast on push.
- MiniBar and LeaveContextDialog removed; `hasPlayerCard` now also matches `/categories/:styleId/:id`.
- `useCategoryTracks` cache key includes `fresh`; mutations that affect playlist membership MUST patch all variants.
- Fullscreen mobile player at `/categories/:styleId/:id/player`; back navigation does not clear queue (stays in the same `CategoryDetailPage` mount).
- Playlist hotkeys map index 0..9 → `Digit1`..`Digit9, Digit0` (NOT `Digit0`..`Digit9`).

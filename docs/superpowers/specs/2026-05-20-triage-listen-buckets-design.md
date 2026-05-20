# Triage — Listen to Bucket Tracks — Design Spec

**Date:** 2026-05-20
**Status:** Draft (awaiting user review)
**Scope:** Add audio playback to the triage bucket-detail view so a user can audition the tracks sitting in any triage bucket — including the per-category staging buckets — before finalizing the triage block.

## Goal

While triaging, a user has sorted incoming tracks into per-category staging buckets. Before finalizing (which promotes those tracks into the real categories), they want to listen to what they have staged. This adds a per-row Play button plus a player panel on the bucket-detail page, mirroring the existing category listen experience (`CategoryDetailPage`): a track list with inline Play on the side of a `PlayerCard` panel, with the bucket's tracks bound to the global `PlaybackProvider` queue.

Playback is read-only auditioning. No tracks are moved, no categories are written. The user listens, navigates back, and finalizes as before.

## Out of scope

- Re-sorting / distributing tracks while listening — the existing Curate flow already covers "play and distribute" for technical buckets, and the bucket-detail page keeps its existing move/transfer menus untouched. This feature only adds playback.
- A player on the block-overview page (`TriageDetailPage`) — auditioning happens inside a single bucket. (This was approach C, rejected.)
- Tags / playlist assignment from the triage player — those are category-player features and stay out of triage.
- Any backend, schema, or API change. The bucket-tracks endpoint already returns everything needed.

## Background — what already exists

- **Bucket-tracks API:** `GET /triage/blocks/{id}/buckets/{bucketId}/tracks` returns `BucketTrack` rows that already carry `spotify_id`, `title`, `artists[]`, `length_ms`, `bpm`, `label_name`, `mix_name`, `is_ai_suspected` (see `frontend/src/features/triage/hooks/useBucketTracks.ts`). No new fields needed.
- **Playback queue is generic.** `playback.controls.bindQueue({ source, tracks, cursor, onCursorChange })` accepts a `source` of `{ type: 'bucket'; blockId; bucketId }` — already part of `QueueSource` in `frontend/src/features/playback/lib/types.ts`. The Curate session (`useCurateSession`) already binds a bucket queue this way.
- **Category listen UX is the template.** `CategoryDetailPage` hoists the tracks query + filter state, maps rows to `PlaybackTrack[]`, binds them via `useCategoryPlayerQueue`, renders a desktop split (`CategoryPlayerPanel` + `TracksTab` with per-row `onPlay`), and on mobile pushes a nested `/player` fullscreen route (`CategoryPlayerPage`) via outlet context.
- **`PlayerCard`** (`frontend/src/features/playback/PlayerCard.tsx`) is the shared presentational player atom used by both `CategoryPlayerPanel` and `CurateSession`.

## Decisions

- **Scope of buckets:** Play is enabled on **all** bucket-detail pages — staging buckets *and* technical buckets (NEW/OLD/NOT/UNCLASSIFIED/DISCARD). Playback is generic and harmless; restricting to staging would add a gate for no benefit. Technical buckets keep their existing "Curate from bucket" button as well.
- **Mobile presentation:** mirror categories — a nested fullscreen player route. Per-row Play on mobile starts playback and navigates to the player route.
- **Block status:** playback works regardless of block status (`IN_PROGRESS` or `FINALIZED`); auditioning is read-only.

## 1. Components

### 1.1 `useBucketPlayerQueue(blockId, bucketId, tracks)` — new hook

`frontend/src/features/triage/hooks/useBucketPlayerQueue.ts`

A direct analogue of `useCategoryPlayerQueue`. Binds the bucket's visible tracks to the singleton `PlaybackProvider` queue with `source: { type: 'bucket', blockId, bucketId }`. On every `tracks` identity change it recomputes the cursor (keep the currently-playing track id if it still exists in the new list, else clamp to tail using the same "shrink" logic as the category hook). Clears the queue on unmount. The cursor-recompute logic is copied verbatim from `useCategoryPlayerQueue` — same shrink/clamp behavior.

### 1.2 `toPlaybackTrack(BucketTrack)` — shared helper

`frontend/src/features/triage/lib/toPlaybackTrack.ts`

```ts
function toPlaybackTrack(t: BucketTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.join(', '),
    cover_url: null,
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
  };
}
```

This currently lives inline inside `useCurateSession.ts`. Extract it to the shared lib and switch `useCurateSession` to import it. (Targeted refactor — removes the duplication this feature would otherwise create.)

### 1.3 `BucketTrackRow` — add Play affordance

`frontend/src/features/triage/components/BucketTrackRow.tsx`

- New optional props: `onPlay?: () => void`, `isCurrent?: boolean`.
- Render a Play/Pause `ActionIcon` at the start of the row (both `desktop` and `mobile` variants), mirroring the category `TrackRow`. Disabled when `track.spotify_id === null`.
- When `isCurrent`, highlight the row (same visual treatment categories use for the playing row).
- Existing move/transfer menus are untouched.

### 1.4 `BucketTracksList` — thread playback props

`frontend/src/features/triage/components/BucketTracksList.tsx`

- New optional props: `onPlay?: (track: BucketTrack) => void`, `currentTrackId?: string | null`.
- Pass `onPlay={() => onPlay?.(tr)}` and `isCurrent={tr.track_id === currentTrackId}` to each `BucketTrackRow`.
- **Lift the tracks query + search state up to the page.** Today `BucketTracksList` owns its own `useBucketTracks(blockId, bucketId, debounced)` and search input, while `BucketDetailPage` separately holds a second `useBucketTracks(blockId, bucketId, '')` for the bulk-transfer drain. To bind the player queue to the list the user actually sees (search-filtered), the search state, debounce, and the tracks query move into `BucketDetailPage`. `BucketTracksList` becomes a presentational list that receives `items`, pagination handlers, and the search-input value/handlers as props. This consolidates to a single `useBucketTracks` instance per page.

### 1.5 `BucketPlayerPanel` — new lean player panel

`frontend/src/features/triage/components/BucketPlayerPanel.tsx`

A stripped-down sibling of `CategoryPlayerPanel`. Renders:

- `PlayerCard variant="full"` bound to `playback.track.current`, with play/pause, prev, next, seek, retry, device picker, and Spotify link wired to `playback.controls`.
- Optional `belowMainRow` showing `label_name` + `bpm` + the AI badge, looked up from the visible `items` for the current track (same rich-meta lookup pattern as `CategoryPlayerPanel`, including the "last seen rich row" fallback so meta survives a list shrink).
- Empty state ("pick a track") when nothing is playing.
- **No** tag cloud, **no** playlist cloud (those are category-only).

Keyboard hotkeys: reuse the generic `usePlaybackHotkeys` (play/pause/prev/next/seek) rather than the category-specific `useCategoryPlayerHotkeys`, scoped active when `playback.queue.source?.type === 'bucket'` and matches this block/bucket.

### 1.6 `BucketPlayerPage` — mobile fullscreen route

`frontend/src/features/triage/routes/BucketPlayerPage.tsx`

Nested under `BucketDetailPage`, mirrors `CategoryPlayerPage`: a back arrow + `BucketPlayerPanel`, receiving the visible `items` via outlet context (`BucketDetailOutletContext = { items: BucketTrack[] }`). The parent page owns the queue binding + filter state and stays mounted, so navigating to/from `/player` preserves queue and search.

### 1.7 `BucketDetailPage` — wiring

`frontend/src/features/triage/routes/BucketDetailPage.tsx`

- Hold search state + the single `useBucketTracks` query (moved up from the list).
- `const playerTracks = useMemo(() => items.map(toPlaybackTrack), [items])`.
- `useBucketPlayerQueue(blockId, bucketId, playerTracks)`.
- `playback.controls.prewarm()` on mount (inside the user-gesture warm-up pattern used by `CategoryDetailPage`).
- `playTrack(track)`: prewarm, find the queue index by id, `play(queueIdx)` (fallback `play(undefined, toPlaybackTrack(track))` if not yet in queue). On mobile, `navigate(.../buckets/:bucketId/player)`.
- Desktop layout: a `Flex` split — `BucketPlayerPanel` beside the tracks list — when `isDesktop`; on mobile, render the list alone and let `playTrack` push the player route. Mirror the `useMediaQuery` + `useMatch('.../player')` outlet pattern from `CategoryDetailPage`.
- Bulk-transfer drain reuses the now-hoisted query's `fetchNextPage`.

### 1.8 Router

`frontend/src/routes/router.tsx`

Add a nested child to the bucket route:

```tsx
{
  path: ':styleId/:id/buckets/:bucketId',
  element: <BucketDetailPage />,
  children: [{ path: 'player', element: <BucketPlayerPage /> }],
},
```

## 2. Data flow

1. `BucketDetailPage` fetches bucket tracks (search-filtered) → `items: BucketTrack[]`.
2. `items` → `PlaybackTrack[]` → `useBucketPlayerQueue` binds them as the global queue (`source.type === 'bucket'`).
3. User taps Play on a row → `playTrack` resolves the queue index and calls `playback.controls.play(idx)`; Spotify Web Playback SDK plays `spotify:track:{spotify_id}`. Mobile additionally navigates to the player route.
4. `PlayerCard` in `BucketPlayerPanel` reflects `playback.track.current` + `playback.queue.status`; prev/next walk the bound bucket queue; auto-advance at track end moves the cursor.
5. Navigating away from the bucket-detail page unmounts the hook → `clearQueue()`.

## 3. Edge cases & error handling

- **`spotify_id === null`:** row Play button disabled; if such a track is reached by auto-advance, `PlaybackProvider` silently skips it (existing PB4 skip-null behavior).
- **Empty bucket / search miss:** existing empty states render; no player queue binding of consequence (empty list).
- **SDK not ready / disconnected:** `PlayerCard` shows its `disconnected`/`buffering`/`error` states (same state mapping `CategoryPlayerPanel` uses).
- **Block finalized:** playback still works (read-only). Move menus already hide/adjust per existing `showMoveMenu` logic — unchanged.
- **List shrink (e.g. a move while playing):** cursor recompute in `useBucketPlayerQueue` keeps the current track or clamps — identical to the category hook's tested behavior.

## 4. Testing (TDD)

- **Unit — `useBucketPlayerQueue`:** binds with `source.type === 'bucket'` + correct `blockId`/`bucketId`; recomputes cursor on tracks change (keep current / clamp on shrink); calls `clearQueue` on unmount. Mirror `useCategoryPlayerQueue.test.tsx`.
- **Component — `BucketTrackRow`:** renders Play; disabled when `spotify_id` is null; calls `onPlay` on click; applies current-row highlight when `isCurrent`.
- **Component — `BucketPlayerPanel`:** empty state when no current track; renders `PlayerCard` + label/BPM meta for the current track; control callbacks fire.
- **Integration — `BucketDetailPage`:** clicking a row Play binds the bucket queue and calls `play`; the playing row is highlighted; on mobile-width it navigates to the `/player` route; search filtering rebinds the queue to the filtered list.
- **i18n:** add keys for play/pause aria, player empty state, open-in-Spotify aria, and the mobile back-arrow aria, in both `en` and `ru` locale files. (Reuse existing `category_player.*` key shapes as the naming model under a new `triage.bucket_player.*` namespace.)

## 5. Files touched

**New**
- `frontend/src/features/triage/hooks/useBucketPlayerQueue.ts`
- `frontend/src/features/triage/lib/toPlaybackTrack.ts`
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
- `frontend/src/features/triage/routes/BucketPlayerPage.tsx`
- Test files for the above.

**Changed**
- `frontend/src/features/triage/components/BucketTrackRow.tsx` — Play affordance.
- `frontend/src/features/triage/components/BucketTracksList.tsx` — presentational; query/search hoisted; thread playback props.
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — own query/search, queue binding, player layout, mobile route navigation.
- `frontend/src/features/curate/hooks/useCurateSession.ts` — import shared `toPlaybackTrack` instead of the inline copy.
- `frontend/src/routes/router.tsx` — nested `player` route.
- `frontend/src/features/triage/index.ts` — export `BucketPlayerPage` if needed by the router import style.
- locale files (`en`, `ru`).

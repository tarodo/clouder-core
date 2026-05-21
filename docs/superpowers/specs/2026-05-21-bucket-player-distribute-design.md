# Triage — Quick Distribution in the Bucket Player — Design Spec

**Date:** 2026-05-21
**Status:** Draft (awaiting user review)
**Scope:** Add quick-distribution buttons to the bucket player (`BucketPlayerPanel`) so that, while auditioning a triage bucket, a user can tap a destination category to move the currently-playing track there and immediately advance to the next track — a lean version of the Curate destination grid.

## Goal

The bucket player (shipped in the "listen to bucket tracks" feature) lets a user audition a bucket's tracks. This adds a row of destination buttons below the player: tapping one moves the **currently-playing** track from the current bucket into that destination and auto-plays the next track. This turns the audition surface into a fast "listen → sort" loop without leaving for the full Curate session.

This is a **lean** distributor — the staging-category subset of the Curate destination grid, without Force mode, without keyboard hotkeys, without the technical NEW/OLD/NOT buttons.

## Out of scope

- Force mode (the Curate toggle that also writes the track into a category overlay).
- Keyboard hotkeys for destinations (Curate's 1-N / Q/W/E/Z bindings).
- Technical destination buttons (NEW / OLD / NOT). Only staging categories + DISCARD are offered.
- Rewinding playback on undo. Undo restores the moved track to the bucket, but the player keeps playing the track it advanced to (unlike the full Curate undo, which re-plays the restored track).
- Any backend / API / schema change. The `POST /triage/blocks/{id}/move` endpoint already exists and is used by triage + curate.
- Reusing the curate `DestinationGrid`/`DestinationButton` components — importing them into the triage feature would create a circular `triage ↔ curate` dependency (curate already imports from triage). A lean triage-local button component is built instead.

## Background — what already exists

- **`BucketPlayerPanel`** (`frontend/src/features/triage/components/BucketPlayerPanel.tsx`) renders the player for a bucket. It already receives `{ blockId, bucketId, items }` (today `blockId`/`bucketId` are declared but unused in the body). It is rendered on the desktop split (`BucketDetailPage`) and on the mobile `/player` route (`BucketPlayerPage`).
- **`useBucketPlayerQueue`** binds the visible bucket tracks to the global `PlaybackProvider` queue. `playback.track.current` / `playback.queue.tracks` / `playback.controls.play(idx?, overrideTrack?)` are available.
- **`useMoveTracks(blockId, styleId)`** (`frontend/src/features/triage/hooks/useMoveTracks.ts`) performs an optimistic move: `onMutate` filters the moved track out of the source bucket's `bucketTracks` cache (`applyOptimisticMove`) and decrements/increments bucket counts. `takeSnapshot` + `undoMoveDirect` support undo.
- **`BucketDetailPage.handleMove`** already moves a track and shows a green toast with an inline "Undo" action (`undoMoveDirect`). This is the move+undo pattern to mirror.
- **`useTriageBlock(blockId)`** returns the block (with `buckets`, `status`, `style_id`). It is already loaded/cached by `BucketDetailPage`, so a second consumer is a cache hit.
- **`bucketLabel(bucket, t)`** and `isTechnical(bucket)` live in `frontend/src/features/triage/lib/bucketLabels.ts`.

## Decisions (from brainstorming)

- **Lean distributor:** destinations = staging categories (excluding the current bucket) + the DISCARD bucket. No Force, no hotkeys, no NEW/OLD/NOT.
- **Auto-advance:** after the move, the player immediately plays the next track in the queue.
- **Panel self-fetches the block:** `BucketPlayerPanel` calls `useTriageBlock(blockId)` to get `buckets`/`status`/`style_id` rather than receiving them via props/outlet-context. This makes distribution work identically on the desktop split and the mobile `/player` route with no extra plumbing, and finally gives `blockId`/`bucketId` a use.
- **Gated on `IN_PROGRESS`:** buttons render only when the block status is `IN_PROGRESS` (moves are not allowed on `FINALIZED` blocks) and a track is currently playing.

## 1. Components

### 1.1 `BucketDistributeButtons` — new presentational component

`frontend/src/features/triage/components/BucketDistributeButtons.tsx`

```tsx
export interface BucketDistributeButtonsProps {
  destinations: TriageBucket[];
  onDistribute: (toBucketId: string) => void;
}
```

- Renders a `SimpleGrid` (e.g. `cols={{ base: 2, md: 3 }}`) of Mantine `Button`s, one per destination, labeled via `bucketLabel(bucket, t)`. DISCARD may be rendered with a distinct variant/color (e.g. `variant="light" color="red"`) but this is cosmetic.
- A short section label above the grid (`t('triage.bucket_player.distribute.heading')`, e.g. "Move current track to").
- Each button: `onClick={() => onDistribute(bucket.id)}`, `aria-label` derived from the bucket label.
- Renders `null` when `destinations` is empty.
- No Force toggle, no hotkey hints, no technical buttons.

### 1.2 `useBucketDistribute` — new hook

`frontend/src/features/triage/hooks/useBucketDistribute.ts`

```ts
export function useBucketDistribute(args: {
  blockId: string;
  bucketId: string;
  styleId: string;
}): (toBucketId: string) => void;
```

Returns a `distribute(toBucketId)` callback. Behavior:

1. Read `current = playback.track.current`. If `null`, no-op.
2. Compute the successor: find `current.id` in `playback.queue.tracks`; `successor = tracks[idx + 1] ?? null`.
3. `const input: MoveInput = { fromBucketId: bucketId, toBucketId, trackIds: [current.id] }`.
4. `takeSnapshot(qc, blockId, bucketId)`, then `move.mutate(input, { onSuccess, onError })` using `useMoveTracks(blockId, styleId)`.
   - `onSuccess`: show a green toast with an inline "Undo" action that calls `undoMoveDirect(qc, blockId, styleId, input, snapshot)` — mirror `BucketDetailPage.handleMove`'s toast, including the `move.isPending` / inflight guard.
   - `onError`: show an error toast (reuse the existing `triage.move.toast.*` error keys / mapping from `handleMove`).
5. The mutation's `onMutate` optimistically shrinks the source bucket cache, so `playerItems` shrinks and `useBucketPlayerQueue` rebinds.
6. Advance: if `successor` exists, call `playback.controls.play(undefined, successor)` (the override-track form, so playback does not depend on rebind/cursor timing). If no successor, do nothing (queue naturally ends).

The hook uses `usePlayback`, `useMoveTracks`, `useQueryClient`, `useTranslation`, and `notifications`.

### 1.3 `BucketPlayerPanel` — wire in distribution

`frontend/src/features/triage/components/BucketPlayerPanel.tsx`

- Call `useTriageBlock(blockId)` to get the block.
- `const distribute = useBucketDistribute({ blockId, bucketId, styleId: block?.style_id ?? '' })`.
- Compute destinations: when `block?.status === 'IN_PROGRESS'`, `destinations = block.buckets.filter((b) => b.id !== bucketId && (b.bucket_type === 'STAGING' || b.bucket_type === 'DISCARD'))`. Otherwise `[]`.
- Render `<BucketDistributeButtons destinations={destinations} onDistribute={distribute} />` below the `PlayerCard`, only when `current` exists (the panel already early-returns its empty state when nothing is playing, so the buttons live in the playing branch).
- `blockId`/`bucketId` props are now used (remove their "reserved" comment).

No router or page changes: the mobile `/player` route renders `BucketPlayerPanel` with `blockId`/`bucketId`, so distribution works there automatically.

## 2. Data flow

1. User taps a destination button → `onDistribute(toBucketId)` → `useBucketDistribute.distribute`.
2. Capture `current` + `successor` from the live playback queue.
3. `move.mutate` → `onMutate` optimistically removes the current track from the source bucket cache → `playerItems` (page) and the list both shrink (shared query key) → `useBucketPlayerQueue` rebinds the queue.
4. `playback.controls.play(undefined, successor)` immediately plays the next track.
5. Server confirms; `onSuccess` shows the undo toast and invalidates the destination bucket + block + blocks-by-style caches (via `useMoveTracks.onSuccess`).

## 3. Error handling & edge cases

- **No current track:** `distribute` is a no-op; the buttons are not rendered anyway (panel shows its empty state).
- **Current track is the last in the queue:** no successor; the move proceeds, playback finishes the current track and the queue ends. No crash.
- **FINALIZED block:** `destinations` is empty → `BucketDistributeButtons` renders `null`. No moves possible (consistent with the row move-menu being hidden on FINALIZED).
- **No eligible destinations** (e.g. only one staging bucket and no DISCARD): renders `null`.
- **Move fails (server error / stale state):** `onError` toast (reuse `handleMove`'s error-key mapping: `target_bucket_inactive`/`invalid_state` → invalid target; `tracks_not_in_source`/`bucket_not_found`/`triage_block_not_found` → stale state; else generic). The optimistic shrink is rolled back by `useMoveTracks.onError`. The player has already advanced to the successor; it is not rewound (lean behavior).
- **Undo:** the toast "Undo" restores the moved track to the source bucket (`undoMoveDirect`); the track reappears in the list/queue on the next rebind. Playback is **not** rewound to it (documented lean behavior).

## 4. Testing (TDD)

- **`BucketDistributeButtons`** (component): renders one button per destination using `bucketLabel`; excludes nothing extra (caller pre-filters); calls `onDistribute(bucket.id)` on click; renders nothing when `destinations` is empty.
- **`useBucketDistribute`** (hook): fires `move.mutate` with `{ fromBucketId, toBucketId, trackIds: [current.id] }`; calls `playback.controls.play(undefined, successor)` with the next queue track; no-op when `playback.track.current` is null; plays nothing when the current track is last (no successor). Mock `useMoveTracks` + `usePlayback`.
- **`BucketPlayerPanel`** (component): shows the distribute buttons when `block.status === 'IN_PROGRESS'` and a track is playing; hides them when `FINALIZED`; hides them when nothing is playing; tapping a destination invokes the move path. Mock `useTriageBlock` + `usePlayback` (+ `useMoveTracks` or the distribute hook).
- **Integration** (`BucketDetailPage`): play a track, tap a destination → a `POST /triage/blocks/{id}/move` is issued with the right body, and the next track becomes current. Extend the existing integration test (MSW handler for `/move`), reusing the existing `usePlayback` mock; the mock's `play` spy / `queue.tracks` may need a populated queue + a stubbed `current` to exercise the successor path.
- **i18n:** add `triage.bucket_player.distribute.heading` (and any aria key) to `frontend/src/i18n/en.json` (EN-only; no `ru.json`).

## 5. Files touched

**New**
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` (+ test)
- `frontend/src/features/triage/hooks/useBucketDistribute.ts` (+ test)

**Changed**
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — fetch block, compute destinations, render buttons; update its test.
- `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx` — distribution integration test.
- `frontend/src/i18n/en.json` — distribute heading/aria keys.

No backend, schema, API, or router changes.

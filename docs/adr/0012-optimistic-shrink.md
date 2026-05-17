# ADR-0012: Optimistic shrink, reducer ADVANCE no-op
Status: Accepted
Date: 2026-05-17

## Context

In the curate session, the user assigns a track to a destination and expects the UI to immediately show the next track — the current one should disappear and the successor should take its place without any delay or flicker. The assignment also triggers playback of the new track via the Spotify SDK.

The naive implementation fires the server mutation, waits for confirmation, then re-fetches the queue. This introduces 300–600 ms of latency that is very visible in a rapid-assignment workflow. Optimistic UI (apply the effect locally before server confirmation, roll back on error) eliminates the lag.

Two sub-problems emerged. First, when the assigned track is removed from the queue cache, what should `currentIndex` point at? Second, when should `ADVANCE` increment the index?

**Optimistic shrink**: `applyOptimisticMove` filters the assigned track from the bucket-tracks TanStack Query cache synchronously. Because the cache is the source of truth for the queue array, the curate queue shrinks by 1. After the shrink, `queue[currentIndex]` already points at what was `queue[currentIndex + 1]` before — the natural successor. No index increment is needed.

**ADVANCE is a no-op**: the reducer's `ADVANCE` action was originally designed to increment `currentIndex` after the 200 ms pending window. However, since optimistic shrink already repositions the queue, an additional `currentIndex++` would skip one track — visible as a brief flicker from track t+1 to track t+2. The fix was to keep the `ADVANCE` dispatch (for timing and undo state management purposes) but make the reducer body a no-op for the index.

The 200 ms timer still fires `scheduleAdvance` after each assignment, because it serves two other purposes: detecting double-taps (user changes destination within the window) and cancelling pending undo on window close. The index increment is simply dropped from the reducer.

**Double-tap correctness**: when the user taps destination A then destination B within 200 ms, the second tap must target the same track (t1), not the post-shrink successor (t2). The move operation captures `lastOp.input.trackIds[0]` at the first tap and reuses it on the second tap, bypassing `queue[currentIndex]`.

## Decision

When a track is assigned, `applyOptimisticMove` filters it from the bucket cache synchronously. `currentIndex` already points at the natural next track; the reducer's `ADVANCE` action is therefore a no-op. The reducer keeps a `pending` window and a `lastOp` snapshot to handle double-tap and undo correctly.

## Consequences

- The ADVANCE no-op is counter-intuitive and has caused confusion when revisiting the code. The `useCurateSession.ts` reducer has an explicit comment explaining the no-op. Do not "fix" it by adding an index increment.
- Timer IDs for the pending window (`pendingTimerRef`) and the just-tapped pulse (`pulseTimerRef`) live in `useRef`, not reducer state. Storing them in reducer state would cause re-renders on every timer-id change, creating a feedback loop.
- `stateRef.current = state` is a mirror pattern that lets imperative callbacks (`assign`, `undo`) read fresh reducer state without adding state to deps arrays. Callback identity is stable across renders.
- After an optimistic shrink of the currently-playing track in the category player, the cursor is set to `lastCursor - 1` (not `lastCursor`). Everything after the removed track shifts down by one; `advance(+1)` from `lastCursor - 1` lands on the successor. Edge case: `lastCursor = 0` yields cursor `= -1`, handled by `findNextPlayable(tracks, 0, +1)` starting from `tracks[0]`.
- Undo (`UNDO_AFTER`) uses `lastOp.trackIndex` (captured at assign time) to restore `currentIndex` to the pre-assign state. This is the same index the original track was at, not the post-shrink index.

**Cross-references:** `../frontend/playback.md`, `../frontend/features.md`.

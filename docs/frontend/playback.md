# Frontend Playback Reference

See `docs/adr/0013-playback-lazy-load.md`, `docs/adr/0012-optimistic-shrink.md`, `docs/adr/0011-spotify-token-bundling.md`.

## PlaybackProvider lifecycle

`frontend/src/features/playback/PlaybackProvider.tsx`

`PlaybackProvider` is mounted inside the authenticated shell layout (`frontend/src/routes/_layout.tsx`). It is always present for logged-in users — on every route, not just playback-active routes.

The Spotify Web Playback SDK script is **lazy-loaded**: `loadSpotifySdk()` (`frontend/src/features/playback/lib/sdkLoader.ts`) is called only on the first `controls.play()` invocation. Public auth pages (`/login`, `/auth/return`) never trigger it.

SDK boot race during integration tests: the first `controls.play()` calls `ensureSdk()` then returns early because `deviceIdRef` is null until the SDK emits its `ready` event. Tests must click play once to trigger SDK init, await the synthetic `ready` event, then click play again to get actual playback. See `integration.batch1.test.tsx` `preWarm()` helper.

After `ready` fires, `PlaybackProvider` calls `transferMyPlayback(device_id, { play: false })` synchronously to make the CLOUDER browser tab the active Spotify Connect device.

## Queue source discriminated union

`frontend/src/features/playback/lib/types.ts:33`

```ts
export type QueueSource =
  | { type: 'bucket';   blockId: string; bucketId: string }
  | { type: 'category'; categoryId: string; styleId: string };
```

Always narrow on `source.type` before reading variant-specific fields. Curate passes `{ type: 'bucket', blockId, bucketId }`; the category player passes `{ type: 'category', categoryId, styleId }`.

`controls.bindQueue(args: BindQueueArgs)` is called by the consumer (curate session hook, category player queue hook) whenever the tracks list identity changes. It accepts `{ source, tracks, cursor, onCursorChange }`. The provider stores `onCursorChange` in a ref and dispatches `JUMP_TO` into the consumer's reducer when auto-advance moves the cursor.

`controls.clearQueue()` resets queue state and clears `track.current`. Called on route leave.

## Hotkeys

Two hook layers operate simultaneously on curate routes:

### `usePlaybackHotkeys` (`frontend/src/features/playback/usePlaybackHotkeys.ts`)

Registered globally on `window`. Fires on all routes where `PlaybackProvider` is active.

| Key | Action |
|-----|--------|
| `Space` | toggle play / pause |
| `KeyJ` (no shift) | prev track |
| `KeyK` (no shift) | next track |
| `Shift+KeyJ` | seek −10 000 ms |
| `Shift+KeyK` | seek +10 000 ms |
| `KeyA` | seek to 0% |
| `KeyS` | seek to 20% |
| `KeyD` | seek to 40% |
| `KeyF` | seek to 60% |
| `KeyG` | seek to 80% |

Seek targets 0 / 20 / 40 / 60 / 80% — **not** 25 / 50 / 75 / 100%. `KeyG` maps to 80% deliberately: seeking to 100% (track end) would immediately trip the natural-end auto-advance detector (the `paused && position=0` branch), causing an unwanted skip.

### `useCurateHotkeys` (`frontend/src/features/curate/hooks/useCurateHotkeys.ts`)

Registered on curate routes only. Disabled on mobile (`max-width: 64em`).

| Key | Action |
|-----|--------|
| `KeyQ` | assign to `NEW` bucket |
| `KeyW` | assign to `OLD` bucket |
| `KeyE` | assign to `NOT` bucket |
| `KeyZ` | assign to `DISCARD` bucket |
| `Digit1`–`Digit9` | assign to playlist by position index (0-based: index 0 = `Digit1`, index 8 = `Digit9`) |
| `KeyU` | undo last assignment |
| `KeyL` | toggle force-mode |
| `?` | open hotkey overlay |
| `Escape` | close overlay / exit curate |

All letter/digit keys use `event.code` (physical key position) — layout-safe for Cyrillic, Dvorak, AZERTY. The single exception is `?` which uses `event.key === '?'` because `?` is a shifted character whose layout intent matters.

`KeyJ` and `KeyK` are **not** bound in `useCurateHotkeys` — they are handled exclusively by `usePlaybackHotkeys` to avoid double-fire and SDK-state interference.

## Auto-advance

`frontend/src/features/playback/PlaybackProvider.tsx` — `player_state_changed` listener.

Two detectors run in the same `player_state_changed` callback:

**Detector 1 — URI mismatch** (`playbackConfirmedRef.current && currentUri !== expected`):
Fires when Spotify Connect auto-loads the next item from the user's remote queue. The Spotify SDK seamlessly transitions tracks (no pause/zero-position event), so URI drift is the only reliable signal. Guard: `playbackConfirmedRef` must be `true` (the expected track was confirmed playing) to avoid false triggers from initial `transferMyPlayback` state events.

**Detector 2 — paused at zero** (`paused && position === 0 && URI matches expected && wasPlayingExpectedRef.current`):
Fires when the user's remote queue is empty and Spotify simply pauses the current track at position 0 at natural end. Without this, playback dies silently when nothing is queued in the user's Spotify session.

`wasPlayingExpectedRef` is reset to `false` alongside `expectedSpotifyIdRef` in `play()`, `advance()`, and `clearQueue()` to prevent stale triggers on the first `player_state_changed` event after a fresh play.

See `docs/adr/0012-optimistic-shrink.md`.

## Optimistic shrink and cursor

`frontend/src/features/curate/hooks/useCurateSession.ts`, `frontend/src/features/categories/hooks/useCategoryPlayerQueue.ts`.

See `docs/adr/0012-optimistic-shrink.md`.

**`ADVANCE` reducer action is a no-op.** When the user taps a destination, `useMoveTracks.applyOptimisticMove` synchronously removes the assigned track from the bucket-tracks cache. The curate queue (same query) shrinks by 1 and `currentIndex` already points at the natural successor. Incrementing inside `ADVANCE` would skip one track — visible flicker from t2 to t3 instead of t2.

The 200 ms pending-window timer still fires `scheduleAdvance` for double-tap detection and undo cancellation; only the index increment was dropped.

**Double-tap reuses `lastOp.input.trackIds[0]`**, not `queue[currentIndex]`. On double-tap (e.g. key `1` then key `2` within 200 ms), `assign` calls `undoMoveDirect` (synchronous cache restore) then re-applies the move to the new destination. The second move targets the same `trackId` captured at the first tap. Reading `queue[stateRef.current.currentIndex]` post-shrink would yield the successor track (t2 instead of t1) — wrong. Same applies to `lastOp.trackIndex` for the new `lastOp` so post-window undo restores the right index.

**Category player cursor after shrink**: when the currently-playing track is removed optimistically, cursor is set to `lastCursor - 1`. Everything after the removed track shifts down by one, so `advance(+1)` from `lastCursor - 1` lands on the successor at `lastCursor`. Edge case: `lastCursor = 0` yields `cursor = -1`; `findNextPlayable(tracks, 0, +1)` handles that as start-from-`tracks[0]`.

## Spotify token plumbing

`frontend/src/auth/spotifyTokenStore.ts`

`spotifyTokenStore` is a module-scoped singleton (identical structure to `tokenStore`). It holds the Spotify-issued access token in memory only — never persisted to localStorage, sessionStorage, or cookies.

The token is populated from:
- `POST /auth/callback` response body (`spotify_access_token` field)
- `POST /auth/refresh` response body (same field)

Both calls go through `AuthProvider`, which calls `spotifyTokenStore.set(body.spotify_access_token)` on success.

The Spotify Web Playback SDK reads the token via `getOAuthToken(cb)`:

```ts
getOAuthToken: (cb: (t: string) => void) => {
  const t = spotifyTokenStore.get();
  if (t) cb(t);
},
```

Token rotation is transparent: the next SDK `getOAuthToken` callback picks up whatever `spotifyTokenStore` currently holds. No SDK re-init is required.

See `docs/adr/0011-spotify-token-bundling.md`.

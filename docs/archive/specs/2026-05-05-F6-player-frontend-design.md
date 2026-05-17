# F6 — PlayerCard + sticky MiniBar (frontend playback)

**Date:** 2026-05-05
**Status:** brainstorm complete; awaiting plan
**Author:** @tarodo (via brainstorming session, Claude Opus 4.7)
**Parent (umbrella playback spec):** [`2026-04-29-playback-ux-design.md`](./2026-04-29-playback-ux-design.md) — PB1–PB18 architectural decisions, 18 integration scenarios.
**Roadmap row:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F6** "PlayerCard + sticky mini · P-24 · Spotify Web Playback SDK directly".

**Predecessors (already shipped):**

- F1 — Categories CRUD.
- F2 — Triage list + create.
- F3a / F3b — Triage detail + transfer.
- F4 — Triage finalize + bulk transfer.
- F5 — Curate desktop + mobile (`useCurateSession`, `useCurateHotkeys`, `EndOfQueue`, optimistic shrink).

**Successors:**

- **F7** — full P-25 device picker UI (consumes `PlaybackProvider.devices` + `transferMyPlayback` flow; F6 ships an auto-pick stub of the same surface).
- **F10 / F11** — PlayerCard inside Categories detail (PB5 + PB14 playback-subset hotkeys). Deferred from F6 by user.

## 1. Context and Goal

Up to F5, CLOUDER moves track rows between buckets without ever playing audio. Users open a side window into the real Spotify app to listen. F6 lifts playback inside CLOUDER itself via the Spotify Web Playback SDK + Spotify Connect protocol.

After F6 the user can:

- Tap Play on any track row inside Curate and the Spotify-hosted player streams audio through the current browser tab (the **CLOUDER Web Player** virtual device).
- Use playback hotkeys (`Space`, `J`/`K`, `Shift+J/K`, `A`/`S`/`D`/`F`/`G`) without leaving the keyboard-driven Curate flow.
- See a sticky **MiniBar** at the bottom of the AppShell on routes that do not host a full PlayerCard (Tracks list, Profile, Home, Triage list).
- Be prompted before navigating to a different PlayerCard context (different Curate block / Categories detail) while a queue is active.
- Have the destination-tap auto-advance from F5 actually move audio to the next track (today the 200 ms hold ends with a no-op SDK call).

F6 deliberately does **not** ship the P-25 device picker UI. Device selection in F6 is silent: SDK `ready` → `transferMyPlayback(local_device_id, { play: false })`. F7 builds the full picker (Drawer / Popover, `getMyDevices` polling, `last_device_id` localStorage persistence). Stub copy in F6's PlayerCard `disconnected` state already routes the user toward "open device picker" — that link becomes functional in F7.

PlayerCard in Categories detail (P-10) is also deferred. Real DJ workflow centres on Curate; Categories is an archive surface. The user explicitly chose to defer Categories playback to a polish sweep (F10 / F11).

## 2. Scope

**In scope:**

- `PlaybackProvider` React context: SDK lifecycle (lazy load, init, ready/error events), queue FSM, token plumbing.
- Lazy injection of `https://sdk.scdn.co/spotify-player.js` on first PlayerCard route mount.
- Bundling `spotify_access_token` from `/auth/callback` and `/auth/refresh` (already returned by backend, currently discarded by SPA) into AuthProvider context + a new in-memory `spotifyTokenStore`.
- PlayerCard full variant (P-22 mobile, P-23 desktop) per `04 Component spec sheet.html § PlayerCard`.
- Sticky MiniBar in AppShell footer for non-PlayerCard routes.
- Interactive scrub bar on PlayerCard via Mantine `<Slider>` with debounced `seek` calls.
- Playback hotkeys: `Space`, `J` (prev), `K` (next), `Shift+J/K` (±10 s), `A`/`S`/`D`/`F`/`G` (seek 0/20/40/60/80 %).
- F5 hotkey changes: swap `KeyJ` ↔ `KeyK`, repurpose `Space` from external-Spotify-link to play/pause (link moves to a button-only affordance in `CurateCard`).
- Queue auto-advance after Curate destination tap (PB11) extends F5's 200 ms hold with a real SDK `play()` of the next track; undo within the window cancels.
- No-spotify-id row guard: disabled Play button + tooltip; auto-skip in queue (PB4).
- Empty-bucket PlayerCard state when 100 % of tracks have `spotify_id IS NULL`.
- End-of-queue UX (PB10): existing `EndOfQueue.tsx` extended; SDK paused on entry.
- Route navigation guard via React Router 7 `useBlocker` (PB7): prompt only when target is another PlayerCard context.
- Error mapping: SDK errors → toast / state, 401 → AuthProvider refresh + retry once, network offline → indicator.

**Out of scope (deferred):**

- P-25 device picker UI, `getMyDevices` polling, `last_device_id` localStorage persistence — **F7**.
- PlayerCard inside Categories detail (P-10) — **F10 / F11**.
- Spotify `audio-analysis` drop-detection (FUTURE-G-PB-1).
- Per-user hotkey rebinding UI (FUTURE-G-PB-2).
- Listening analytics (FUTURE-G-PB-3).
- Crossfade / gapless / pre-buffering (FUTURE-G-PB-4).
- Multi-tab coordination via `BroadcastChannel` (FUTURE-G-PB-5).
- PWA / native wrappers (FUTURE-G-PB-6).
- Queue persistence across browser refresh — refresh restarts the queue from the next Curate Play tap.

## 3. Architectural Decisions

The umbrella spec (`2026-04-29-playback-ux-design.md`) owns PB1–PB18. F6 inherits them verbatim. The decisions below are F6-local refinements / deviations.

| # | Decision | Rationale |
|---|---|---|
| **F6-1** | Spotify access token is bundled into the existing CLOUDER auth refresh stream, not a separate `/auth/spotify/refresh` endpoint. `TokenResponse.spotify_access_token` and `RefreshResponse.spotify_access_token` (already in `docs/openapi.yaml:1858-1892`) propagate through `AuthProvider` into a new in-memory `spotifyTokenStore`. PB16's separate-endpoint sketch is overridden — backend already does it as one call. | The combined endpoint already exists; no backend work needed. Single refresh schedule (existing `AuthProvider.scheduleRefresh`). The Spotify SDK reads the current token via its `getOAuthToken(cb)` callback, so token rotation is transparent. |
| **F6-2** | `PlaybackProvider` lives in the **authenticated** `_layout.tsx` (post-`requireAuth`), outside the per-route `<Outlet />`. The provider exists for the whole authenticated session; the SDK script is lazy-loaded only on first mount of a PlayerCard route (Curate today; Categories detail later). Public routes (`/auth/login`, `/auth/return`) never instantiate the provider. | Provider must outlive route swaps so a queue active on Curate keeps playing when the user navigates to Tracks list. Lazy SDK init keeps Profile / Home / Tracks list free of the ~80 KB SDK boot cost. Public auth pages have no `spotify_access_token` available anyway. |
| **F6-3** | Device selection in F6 is silent and exclusive to the CLOUDER Web Player tab. On SDK `ready({device_id})` the provider calls `transferMyPlayback(device_id, { play: false })`. No picker UI, no `last_device_id` persistence, no `getMyDevices` polling. F7 layers all of that on top. | Auto-pick is the spec's PB8 silent path anyway. F7 is a full ticket — pulling its UI into F6 would double the scope of an already-large frontend ticket. Disconnected state in PlayerCard surfaces the missing picker as a hint copy. |
| **F6-4** | Hotkey ownership stays with each route. F5's `useCurateHotkeys` keeps owning destination + undo + overlay keys; a new `usePlaybackHotkeys` mounted at the same Curate route owns playback keys. Both bind to `window` keydown with editable-target guard. | Two hooks with disjoint key sets is simpler than merging into a god-hook with branching. F7's later Categories detail playback gets `usePlaybackHotkeys` only (no destination keys), proving the split. |
| **F6-5** | F5's J / K binding is swapped to align with the umbrella spec PB14 (J = prev, K = next). The change is a one-line swap in `useCurateHotkeys.ts` plus updated test fixtures. | F5 shipped with `J = onSkip` (next) and `K = onPrev`, the inverse of PB14. User chose to align with PB14 because the playback hotkeys (`J` = prev / `K` = next) and the cursor movement should match exactly — having them inverted relative to one another would create dual muscle memory. |
| **F6-6** | F5's `Space` is reassigned from `onOpenSpotify` (external Spotify deep-link) to play/pause. The "open in real Spotify" affordance becomes button-only inside `CurateCard` (no hotkey). | With inline SDK playback, an external-Spotify hotkey is redundant for playable tracks. Button-only keeps the affordance for the no-spotify-id case (where inline play is disabled) without competing with Space for the primary playback verb. |
| **F6-7** | Cursor / queue ownership is hybrid (brainstorming Q3 option **(c)**). F5's `useCurateSession` reducer remains source of truth for `currentIndex`. PlaybackProvider exposes `bindQueue({ source, tracks, cursor, onCursorChange })`. The provider drives only SDK calls and FSM; cursor mutations round-trip through `onCursorChange` back into F5's reducer. | Preserves all 380+ F5 tests and the carefully-tuned reducer (lastOp, justTapped, pending timer refs, double-tap, optimistic shrink, page-boundary recovery). PlayerCard / MiniBar J/K hotkeys still work because they invoke `onCursorChange`, which dispatches into the reducer. |
| **F6-8** | F5's `ADVANCE` reducer action stays a no-op (per CLAUDE.md gotcha — "Optimistic shrink does the work"). F6 layers a pure SDK trigger on top: at the end of the 200 ms hold, the assign callback calls `playback.next()`, which inspects the (already-shrunk) tracks list, picks the first playable track at or after the unchanged `currentIndex`, and SDK `play()`s it. Undo cancels the pending advance via `playback.cancelPendingAdvance()` ref. | Aligns with the "shrink does the work" invariant. Avoids skip-one-track bugs. |
| **F6-9** | The SDK script tag is injected exactly once per page lifecycle by an idempotent `sdkLoader.ts`. Re-mounting PlaybackProvider re-uses the existing `Spotify` global. | A second `<script>` tag triggers `INVALIDATION_OF_AUTHENTICATION` in the SDK in some configurations. Cheap to avoid. |
| **F6-10** | Scrub bar is a Mantine `<Slider>` (interactive), not a `<Progress>` (read-only) as the spec sheet snippet suggested. Hidden thumb on idle (rendered only on hover/focus). Drag emits `seekMs(ms)` debounced at 100 ms; commit on `onChangeEnd`. Disabled in `error` and `disconnected` states. | Spec sheet's `<Progress>` was a viz hint; PB13 explicitly requires interactive scrub. Hidden thumb keeps the visual identical to the design while supporting the interaction. 100 ms debounce keeps SDK from choking under rapid drags. |
| **F6-11** | MiniBar `Close` (X) is a one-tap `clearQueue()` with no confirmation. PB6 is silent on this — brainstorming Q5 picked the no-confirm path. | MiniBar tap is explicit user intent. Confirm-on-every-close adds friction to a low-cost reversible action (re-tap Play in the source bucket restores the queue). |
| **F6-12** | Empty-bucket state: when bound to a queue whose tracks are 100 % `spotify_id IS NULL`, PlayerCard renders a dedicated state with `WifiOff` icon + copy "В этом ведре нет треков с Spotify match". Hotkeys are no-ops; `play()` calls are guarded. | Without this state, PlayerCard would mount frozen on `idle` and silently swallow Space presses. The state is rare (UNCLASSIFIED before Spotify enrichment) but visible enough to need real copy. |
| **F6-13** | LeaveContextDialog uses React Router 7 `useBlocker`. Blocker triggers iff `queue.status ∈ {playing, paused, buffering}` AND target route is a PlayerCard context different from current. Tracks list / Profile / Home / Triage list / Categories list pass through (MiniBar appears). | Router-level guard is cleaner than per-link `onClick` interception. `useBlocker` is the React Router 7 native primitive for this exact pattern. |
| **F6-14** | All Spotify Web API calls go through a thin `spotifyWebApi.ts` wrapper that handles 401 → AuthProvider.refresh → retry-once. A second 401 surfaces a re-login prompt. | Centralises the refresh-and-retry logic so individual call sites (`play`, `transferPlayback`, `seek`) stay one-liners. |

## 4. Component Layout

### 4.1 New files

```
frontend/src/features/playback/
├── PlaybackProvider.tsx          // context + SDK lifecycle + queue FSM
├── usePlayback.ts                // typed context consumer
├── PlayerCard.tsx                // full + mini variants
├── PlayerCard.module.css         // Slider override (thin track, hover-thumb)
├── MiniBar.tsx                   // sticky-mini variant in AppShell footer
├── LeaveContextDialog.tsx        // Mantine Modal + useBlocker integration
├── usePlaybackHotkeys.ts         // Space / J / K / Shift+J,K / A,S,D,F,G
├── lib/
│   ├── sdkLoader.ts              // idempotent <script> injection
│   ├── queueFsm.ts               // idle | loading | playing | paused | ended | error
│   ├── seekHotkeys.ts            // pct→ms + clamp helpers
│   ├── skipNullSpotifyId.ts      // cursor-advance helper for PB4
│   └── spotifyUri.ts             // `spotify:track:${id}` reconstruct
├── api/
│   └── spotifyWebApi.ts          // play / transferPlayback / seek; 401-retry-once
└── __tests__/
```

### 4.2 Existing files to edit

- `auth/AuthProvider.tsx` — add `spotifyAccessToken: string | null` to context value; populate on `signIn` and `refresh`; clear on `signOut`.
- `auth/tokenStore.ts` — add a sibling `spotifyTokenStore` (in-memory, no `localStorage` / `sessionStorage` / cookies; PB16).
- `routes/_layout.tsx` — wrap `<Outlet />` with `<PlaybackProvider>`; render `<MiniBar />` after `<Outlet />` and `<LeaveContextDialog />` alongside.
- `features/curate/components/CurateSession.tsx` — render `<PlayerCard variant="full" />` at the top (P-22 mobile / P-23 desktop centre column); call `playback.bindQueue(...)` on mount and on tracks-list identity change.
- `features/curate/hooks/useCurateSession.ts` — at the end of the 200 ms post-assign hold call `playback.next()`; undo path calls `playback.cancelPendingAdvance()`. Bind queue on mount.
- `features/curate/hooks/useCurateHotkeys.ts` — swap `KeyJ` ↔ `KeyK` (J = prev, K = next); remove `Space → onOpenSpotify`. Drop the `onOpenSpotify` callback from the hook's args.
- `features/curate/components/CurateCard.tsx` (or wherever the row is rendered) — add a no-hotkey "Open in Spotify" button affordance. Disabled-Play button + tooltip on rows where `track.spotify_id == null`.
- `features/curate/components/HotkeyOverlay.tsx` — append playback rows: `Space`, `J`, `K`, `Shift+J`, `Shift+K`, `A`/`S`/`D`/`F`/`G` (with localised copy).
- `features/curate/components/EndOfQueue.tsx` — copy: "Bucket finished. {n} tracks done."; on enter, fire `playback.pause()`.

### 4.3 PlaybackProvider context shape

```ts
interface PlaybackContextValue {
  queue: {
    source: { type: 'bucket'; blockId: string; bucketId: string } | null;
    tracks: Track[];          // bound from owner; not owned here
    cursor: number;           // updated via onCursorChange round-trip
    status: 'idle' | 'loading' | 'playing' | 'paused' | 'buffering' | 'ended' | 'error';
  };
  track: {
    current: Track | null;
    positionMs: number;
    durationMs: number;
  };
  sdk: { ready: boolean; error: SdkError | null };
  controls: {
    play: (idx?: number) => Promise<void>;
    pause: () => Promise<void>;
    togglePlayPause: () => Promise<void>;
    next: () => Promise<void>;
    prev: () => Promise<void>;
    seekMs: (ms: number) => Promise<void>;
    seekPct: (p: number) => Promise<void>;
    bindQueue: (b: BindQueueArgs) => void;
    clearQueue: () => void;
    cancelPendingAdvance: () => void;
    openSpotifyExternal: (uri: string) => void;
  };
}

interface BindQueueArgs {
  source: { type: 'bucket'; blockId: string; bucketId: string };
  tracks: Track[];
  cursor: number;
  onCursorChange: (next: number) => void;
}
```

### 4.4 PlayerCard state matrix

Per `04 Component spec sheet.html § PlayerCard`, plus F6-12 empty-bucket addition:

| State | Centre icon | Scrub opacity | Subline | Slider |
|---|---|---|---|---|
| `idle` | `PlayIcon` | 1.0 | artists | enabled |
| `playing` | `PauseIcon` | 1.0 | artists | enabled |
| `buffering` | `<Loader size={20}/>` | 0.4 | artists + Badge "Buffering…" | enabled |
| `paused` | `PlayIcon` | 0.6 | artists | enabled |
| `error` | `AlertIcon` (`--color-danger`) | 0.4 | "Playback failed · Retry" | disabled |
| `disconnected` | `WifiOffIcon` (`--color-fg-muted`) | 0.3 | "Reconnect Spotify · Open device picker" (no-op stub in F6) | disabled |
| `empty-bucket` (F6-12) | `WifiOffIcon` (`--color-fg-muted`) | 0.0 (hidden) | "В этом ведре нет треков с Spotify match" | disabled |

### 4.5 MiniBar

- Position: `bottom: 0`, `left: 0`, `right: 0`, `height: 56px`, `border-top: 1px solid var(--color-border)`, `background: var(--color-bg-elevated)`, `z-index` above route content but below modal portals.
- Visibility: `queue.source != null && queue.status ∈ {playing, paused, buffering} && route.hasPlayerCard === false`.
- Anatomy: `Cover 40×40` + `Stack(title, artists)` + `Play/Pause ActionIcon` + `Close ActionIcon`. Title size 14, artists muted.
- Click on title or cover → navigate back to source route (`bucket:blockId/bucketId` → `/triage/blocks/:blockId/buckets/:bucketId`). Close = `clearQueue()`.

### 4.6 Hotkey layer (Curate full set after F6)

| Key | Owner | Effect |
|---|---|---|
| `Digit0` | `useCurateHotkeys` | Destination = DISCARD |
| `Digit1`–`Digit9` | `useCurateHotkeys` | Destination = staging[0..8] |
| `KeyQ` | `useCurateHotkeys` | Destination = NEW |
| `KeyW` | `useCurateHotkeys` | Destination = OLD |
| `KeyE` | `useCurateHotkeys` | Destination = NOT |
| `KeyU` | `useCurateHotkeys` | Undo last destination (within 200 ms window) |
| `KeyJ` | `useCurateHotkeys` | Previous track in queue (was: skip → next, swapped per F6-5) |
| `KeyK` | `useCurateHotkeys` | Next track in queue (was: prev, swapped per F6-5) |
| `Space` | `usePlaybackHotkeys` | Play / pause (was: open Spotify external, repurposed per F6-6) |
| `Shift+KeyJ` | `usePlaybackHotkeys` | Seek −10 s |
| `Shift+KeyK` | `usePlaybackHotkeys` | Seek +10 s |
| `KeyA` | `usePlaybackHotkeys` | Seek 0 % |
| `KeyS` | `usePlaybackHotkeys` | Seek 20 % |
| `KeyD` | `usePlaybackHotkeys` | Seek 40 % |
| `KeyF` | `usePlaybackHotkeys` | Seek 60 % |
| `KeyG` | `usePlaybackHotkeys` | Seek 80 % |
| `?` | `useCurateHotkeys` | Open hotkey overlay |
| `Escape` | `useCurateHotkeys` | Close overlays / exit session |

`usePlaybackHotkeys` ignores `Shift+KeyJ` / `Shift+KeyK` if the user holds `Shift` while a destination key is pressed (no overlap — destination keys are digits, not letters, so no real conflict). Editable-target guard identical to `useCurateHotkeys`.

**Hotkey scope across routes.** Both `useCurateHotkeys` and `usePlaybackHotkeys` mount **only on PlayerCard routes** (Curate today; Categories detail later). On non-PlayerCard routes (Tracks list, Profile, Home, Triage list, Categories list) **no playback keyboard shortcuts are bound** — control happens via MiniBar's Play/Pause and Close buttons. This avoids surprising keyboard captures on routes where the user is reading or filling a form. `Space` on a Tracks list page must scroll the page, not toggle playback.

`Q W E` cannot be reassigned to seek %: F5 already binds them to NEW / OLD / NOT (`useCurateHotkeys.ts:89-105`). The user picked `A S D F G` after this conflict surfaced.

### 4.7 Queue FSM

Reuses the umbrella spec § 4.3 / § 8.1 transitions:

```
idle ──play()──▶ loading ──ready──▶ playing
                                       │
                                       ├──pause()──▶ paused ──resume()──▶ playing
                                       │
                                       ├──cursor reaches end + no next page──▶ ended
                                       │
                                       └──SDK error──▶ error
                                                           │
                                                           └──retry──▶ loading
clearQueue() / leave-context confirm: any → idle
```

`buffering` is a sub-state of `playing` (driven by SDK `player_state_changed.position` not advancing for >500 ms and `loading === true`).

## 5. Data Flow

### 5.1 First Play in a session

```
User logs in → AuthProvider stores spotify_access_token
User navigates to /triage/blocks/:bid/buckets/:uid/curate
  ↓
PlaybackProvider mounts
  ├── sdkLoader.load() — injects <script> if not present
  ├── window.onSpotifyWebPlaybackSDKReady → new Spotify.Player({ getOAuthToken: cb => cb(spotifyTokenStore.get()) })
  ├── player.connect() → emits 'ready' { device_id }
  └── transferMyPlayback(device_id, { play: false })  — silent F6-3
CurateSession mounts → calls playback.bindQueue({ source, tracks, cursor=0, onCursorChange })
User taps Play on track row T
  ├── if T.spotify_id === null → no-op (button is disabled anyway)
  └── playback.controls.play(T.idx)
        ├── player.activateElement()  (iOS / autoplay unlock; called inside the click handler)
        ├── onCursorChange(T.idx)     — round-trip into F5 reducer
        └── spotifyWebApi.play({ uris: [`spotify:track:${T.spotify_id}`], device_id })
SDK player_state_changed → status=playing, track.position_ms updates
PlayerCard renders state=playing
```

### 5.2 Auto-advance after destination tap

```
User presses '3' (staging[2]) while track T plays
  ↓
useCurateHotkeys → onAssign(staging[2].id)
useCurateSession.assign(...):
  dispatch ASSIGN_PENDING (just-tapped pulse 80 ms)
  POST /triage/blocks/{id}/move (optimistic shrink: tracks list shorter by 1)
  bindQueue rebind (memoised: same source + cursor, different tracks identity)
  pendingTimerRef = setTimeout(200ms, () => {
    if cancelled (user pressed U) → return
    playback.controls.next()
      ├── compute nextIdx via skipNullSpotifyId(tracks, cursor, +1)
      ├── if !nextIdx → status='ended'; player.pause()
      ├── onCursorChange(nextIdx)
      └── spotifyWebApi.play({ uris: [`spotify:track:${tracks[nextIdx].spotify_id}`], device_id })
  })

If U pressed within 200 ms:
  useCurateSession.undoMoveDirect():
    clearTimeout(pendingTimerRef) → playback.next() never fires
    rollback move (DELETE) — F5's existing path
    SDK keeps playing the same track
```

The cursor numerically does not change after a destination tap (the shrink already moved the next track into the same index slot). `playback.next()` here means "advance to the playable track at current cursor", which after the shrink is the new track. F5 invariant preserved.

### 5.3 Route navigation while playing

```
User in Curate (block A bucket U) with queue.status='playing' clicks Tracks-list link
  ↓
useBlocker callback runs:
  if queue.status === 'idle' or 'ended' → return false (allow nav)
  contextDifferent(current, next):
    target route /tracks → not a PlayerCard route → return false
  → navigation proceeds; PlayerCard unmounts, MiniBar appears
SDK keeps playing — provider survives, only the route Outlet swapped
```

```
User clicks another Curate block link (block B)
  ↓
useBlocker:
  status='playing' → consider blocking
  contextDifferent: target is bucket:B/Y, source is bucket:A/U → different → block
LeaveContextDialog opens
  Confirm  → blocker.proceed(); playback.clearQueue(); navigation completes
  Cancel   → blocker.reset(); user stays
```

### 5.4 Token refresh

```
AuthProvider.scheduleRefresh fires at (issued_at + expires_in − 300 s):
  POST /auth/refresh
    → 200 { access_token, spotify_access_token, expires_in, ... }
    → tokenStore.set(access_token)
    → spotifyTokenStore.set(spotify_access_token)  ← NEW in F6
    → reschedule
SDK requests a fresh token via getOAuthToken(cb) → cb(spotifyTokenStore.get())
On any spotifyWebApi call returning 401:
  if not currently refreshing → AuthProvider.forceRefresh(); retry the original call once
  if retry also 401 → toast + clearQueue + navigate /auth/login
```

### 5.5 SDK events → state mapping

| SDK event | Provider state change |
|---|---|
| `ready({device_id})` | `sdk.ready=true`; `transferMyPlayback(device_id, { play: false })` |
| `not_ready({device_id})` | `status='disconnected'`; SDK will retry-reconnect |
| `player_state_changed(state)` | `track.positionMs`, `track.durationMs` updated; `status` reflects `state.paused` |
| `initialization_error` | `sdk.error='init'`; toast |
| `authentication_error` | trigger `AuthProvider.forceRefresh`; on retry-401 → re-login |
| `account_error` | `navigate('/auth/premium-required')` (P-03 already routed) |
| `playback_error` | `status='error'`; toast + retry button (re-issues last `play()`) |

## 6. Error Handling

| Source | Symptom | Frontend response |
|---|---|---|
| SDK `account_error` | Free Spotify account | Navigate `/auth/premium-required` (P-03). Existing route. |
| SDK `playback_error` | Generic SDK failure | Toast "Playback failed". PlayerCard `status='error'` + Retry. |
| SDK `authentication_error` | Token rejected | `AuthProvider.forceRefresh()`; on retry-401 → re-login. |
| SDK `initialization_error` | Script load / init failure | Toast "Player init failed — refresh"; PlayerCard `status='disconnected'`. |
| `transferMyPlayback` 404 | Selected device went offline | Reopen "open device picker" stub link; surface "Devices changed". F7 will make it real. |
| `play()` 502 / 503 | Spotify side transient | Retry once after 1 s; on persistent → `status='error'` + toast. |
| Bucket-tracks API 404 | Block soft-deleted in another tab | `clearQueue()`; toast "Block was deleted"; navigate `/triage`. |
| `navigator.onLine === false` | Browser offline event | Offline indicator in PlayerCard + MiniBar; new `play()` deferred until `online`. SDK keeps streaming on remote device. |
| Lazy-load page fetch fails | Network blip | Inline retry button on PlayerCard ("Could not load next page — retry"); J/K disabled until retry succeeds. |
| Two CLOUDER tabs fighting | One tab steals playback from the other | Documented limitation (umbrella spec § 6 row 9). The losing tab passively reflects the other tab's `player_state_changed`. |

## 7. Hotkey Reference

See § 4.6. The hotkey overlay (`?`) renders the union of `useCurateHotkeys` + `usePlaybackHotkeys` rows, scoped to the Curate route. Layout-safe matching via `event.code` (`KeyA`, `KeyJ`, `Space`, `Digit0–9`); `?` uses `event.key` (shifted character with layout-dependent intent — F5 precedent).

## 8. Testing

### 8.1 Unit

1. `PlaybackProvider.controls.play()` — happy path; token-refresh path; SDK error path; no-spotify-id guard.
2. `PlaybackProvider.controls.next()` / `prev()` — skip null spotify_id; enter `ended` when no playable left.
3. `bindQueue` rebind — cursor preserved across tracks-identity change (F5 shrink scenario).
4. `cancelPendingAdvance` — undo within 200 ms → no SDK call.
5. `usePlaybackHotkeys` — Space, J, K, Shift+J/K, A–G fire the right controls; ignored when target is `<input>`.
6. `useCurateHotkeys` — J/K swap: J=prev, K=next; Space removed.
7. `seekHotkeys` — `pctToMs(0.6, 360_000) === 216_000`; `seekMs(-5_000)` clamps to 0; `seekMs(>duration)` clamps to duration.
8. `skipNullSpotifyId` — `[A,null,null,D]` next from index 0 → 3; prev from 3 → 0; all-null → `null`.
9. `sdkLoader.load()` — second call does not inject a second `<script>`.
10. `spotifyTokenStore` — get / set / clear; in-memory only (asserts no `localStorage.setItem` calls).
11. `AuthProvider` — `spotify_access_token` set on signIn / refresh, cleared on signOut, propagated to context value.
12. `LeaveContextDialog` — `useBlocker` only fires when target is another PlayerCard route; passes through Tracks list / Profile / Home.
13. `PlayerCard` — all 7 states render (idle / playing / buffering / paused / error / disconnected / empty-bucket); centre icon + subline + scrub opacity match § 4.4.
14. `PlayerCard` Slider — drag emits debounced `seekMs` (one call per 100 ms); `onChangeEnd` commits; disabled in error / disconnected.
15. `MiniBar` visibility — render iff `queue.source && status ∈ {playing,paused,buffering} && !route.hasPlayerCard`.
16. `MiniBar` Close → `clearQueue()` with no confirm; MiniBar disappears.

### 8.2 Integration (mocked SDK + MSW)

Mock Spotify SDK with a stub that emits `ready`, `player_state_changed`, and the error taxonomy on demand. Mock Spotify Web API (`/v1/me/player/play`, `/v1/me/player`, `/v1/me/player/seek`) with MSW.

1. **First Play happy path.** Login → Curate → tap Play on track 3 → SDK plays → PlayerCard `state='playing'`.
2. **Auto-advance after destination.** Tap `3` → 200 ms hold → `playback.next()` → next track plays.
3. **Undo within window.** Tap `3` → `U` at 150 ms → no SDK call → current track continues.
4. **Skip null spotify_id.** Queue `[A, null, null, D]` → auto-advance from A → D plays.
5. **End of bucket.** Queue 5 playable tracks; advance past last → `status='ended'`; EndOfQueue UI visible; SDK paused.
6. **Token refresh proactive.** Mount with `expires_in=600` → fake timer +300 s → `AuthProvider.refresh` fires → SDK `getOAuthToken` callback returns the new token.
7. **Token refresh on 401.** Spotify Web API `play` returns 401 → `AuthProvider.forceRefresh` → retry `play` returns 200.
8. **Route nav with active queue.** Curate playing → click Tracks-list → PlayerCard unmounts → MiniBar appears → SDK still playing.
9. **Leave-context confirm.** Curate block A queue active → click block B link → ConfirmDialog → cancel = stay; confirm = `clearQueue` + navigate.
10. **MiniBar close.** From Tracks-list → MiniBar X → queue cleared, MiniBar disappears.
11. **F5 hotkey swap.** In Curate session: `J` = previous track in queue; `K` = next track. Destination keys (`0–9`, `Q/W/E`, `U`) still work.
12. **Space play/pause.** Space toggles SDK play/pause. The `Open in Spotify` button affordance in the row still opens the external deep-link.
13. **A/S/D/F/G seek.** Track 360 s; press `D` → position 144 s (40 %); press `A` → 0 s.
14. **Shift+J/K seek.** Position 100 s → `Shift+J` → 90 s; `Shift+K` → 110 s. Clamps at boundaries.
15. **No-bucket-Spotify-match.** Bucket where 100 % of tracks have `spotify_id IS NULL` → PlayerCard renders empty-bucket state; hotkeys no-op.
16. **Disconnected state.** SDK `initialization_error` → PlayerCard `state='disconnected'`; "Open device picker" link is a no-op stub in F6.
17. **Premium required.** SDK `account_error` → `navigate('/auth/premium-required')` (P-03).

### 8.3 Coverage

No numeric gate. Every state in § 4.7 has ≥ 1 unit test. All 17 integration scenarios required-green for merge.

Bundle ratchet: F5 shipped 380 tests / ~900 KB. Target +25–35 tests, +20–30 KB minified. Spotify SDK is loaded from `sdk.scdn.co` — not in our bundle. `@types/spotify-web-playback-sdk` (or hand-written declarations) stays a `devDependency`.

### 8.4 Manual

Out of CI:

- Real Spotify Premium dev account: `audio` plays through the CLOUDER tab.
- 4-hour session: token refresh fires multiple times; playback never interrupts.
- Mobile Safari first-tap autoplay unlock: `player.activateElement()` is called inside the click handler.

## 9. Acceptance Criteria

- F5 functionality regresses to zero failed tests after the J/K and Space swaps.
- Navigating to Profile / Home / Tracks list / Auth pages does not load the SDK script (no `<script src="…sdk.scdn.co…">` in DOM).
- A 4-hour session sustains playback through ≥ 1 token refresh without audible drop.
- A 2000-track bucket plays end-to-end without OOM, in ≤ 21 bucket-tracks fetches (1 initial + 20 lazy via F5's existing pagination).
- Tracks with `spotify_id IS NULL` render with disabled Play and tooltip; auto-skip in queue.
- End-of-queue: copy "Bucket finished. {n} tracks done." renders; CTA `autoFocus`; SDK is paused.
- MiniBar visible on every non-PlayerCard route while a queue is active; close = `clearQueue()`.
- LeaveContextDialog fires only when target is another PlayerCard context.
- All 16 unit and 17 integration tests green.
- Bundle increase ≤ 30 KB minified; test count delta within +25/+35.

## 10. Open Items, Edge Cases, Future Flags

### 10.1 Edge cases worth a code comment

- **iOS autoplay unlock.** `player.activateElement()` must be called **inside the click handler** that triggers the first `play()` of a session. The provider's `controls.play()` is invoked from the row click handler — keep this synchronous; no `setTimeout` shim.
- **`spotify_uri` reconstruction.** Backend returns `spotify_id` (bare ID). SDK needs `spotify:track:${id}`. Reconstruct in `spotifyUri.ts`. Document in calling code.
- **`spotify_access_token` refresh race.** Between scheduled refresh and a 401 retry, two parallel refresh attempts are possible. `AuthProvider.forceRefresh()` must dedupe (single in-flight Promise).
- **`useBlocker` quirk.** React Router 7's blocker has a transient `'unblocked'` state that briefly surfaces between proceed and the final navigation. Test this race.
- **Mid-track destination tap with `U` at exactly 200 ms.** Edge: timer fires at 200 ms; if `U` arrives in the same tick it is racy. Implementation should treat the timer callback as the source of truth — once it fires, `U` becomes a no-op for that move.
- **`activateElement` on tab switch.** If the user backgrounds the tab and returns, the SDK may de-prioritise audio. SDK handles this; do not call `activateElement` on every play.

### 10.2 Carryover to F7

- Full P-25 device picker UI (Drawer mobile / Popover desktop).
- `getMyDevices` polling (30 s while PlayerCard route is mounted, plus on `window` `focus`).
- `localStorage.clouder.last_device_id` persistence + silent re-pick (PB8).
- `transferMyPlayback` flow on user-selected device.
- Disconnected-state link wired to open the picker.

### 10.3 Carryover to F10 / F11

- PlayerCard inside Categories detail (P-10) with playback-subset hotkeys (PB14: Space, J, K, Shift+J/K, A–G; no destination keys, no `U`).
- LeaveContextDialog with Categories-detail context detection.

### 10.4 Future flags (umbrella spec)

- `FUTURE-G-PB-1` — `audio-analysis` drop-detection.
- `FUTURE-G-PB-2` — Per-user hotkey rebinding UI.
- `FUTURE-G-PB-3` — Listening analytics.
- `FUTURE-G-PB-4` — Crossfade / gapless.
- `FUTURE-G-PB-5` — Multi-tab `BroadcastChannel` coordination.
- `FUTURE-G-PB-6` — PWA / native wrappers.

## 11. References

- Umbrella playback spec: [`2026-04-29-playback-ux-design.md`](./2026-04-29-playback-ux-design.md)
- spec-A (auth): [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md)
- spec-D (triage / bucket-tracks API): [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md)
- F5 design: [`2026-05-04-F5-curate-frontend-design.md`](./2026-05-04-F5-curate-frontend-design.md)
- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md)
- Design handoff:
  - `docs/design_handoff/03 Pages catalog · Pass 2 (Curate-Patterns).html` (P-22, P-23, P-24)
  - `docs/design_handoff/04 Component spec sheet.html` § PlayerCard (lines 1052–1163)
  - `docs/design_handoff/OPEN_QUESTIONS.md` Q5 (SDK / device picker), Q6 (hotkey scope), Q8 (auto-advance)
- Spotify Web Playback SDK: <https://developer.spotify.com/documentation/web-playback-sdk>
- Spotify Connect: <https://developer.spotify.com/documentation/web-api/concepts/spotify-connect>
- React Router 7 `useBlocker`: <https://reactrouter.com/en/main/hooks/use-blocker>

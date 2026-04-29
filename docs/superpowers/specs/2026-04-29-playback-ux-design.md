# Playback UX — Spotify Web Playback SDK integration

**Date:** 2026-04-29
**Status:** brainstorm stage
**Author:** @tarodo (via brainstorming session)
**Parent:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — spec-D §1 deliberately removed Spotify-playlist-per-triage; this spec replaces that with frontend-side Web Playback SDK orchestration.
**Predecessors:**

- [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md) — provides the Spotify access token returned in `/auth/callback` and a refresh path for it.
- [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — provides bucket-track listing API, hotkey/destination model, auto-advance contract.
- `docs/design_handoff/OPEN_QUESTIONS.md` — Q5 (device picker / SDK init), Q6 (hotkey scope), Q8 (auto-advance after destination).

**Successor:** spec-G (Frontend) consumes this contract when wiring PlayerCard / queue / hotkey layer.

## 1. Context and Goal

spec-D removed Spotify playlists from the triage and category layers. The user listens to tracks **inside CLOUDER** via the Spotify Web Playback SDK + Spotify Connect protocol. CLOUDER does not output audio itself; it controls a Spotify-hosted playback session that runs on whichever device the user picks (their phone, their desktop Spotify app, a Sonos system, or the CLOUDER browser tab as a virtual `CLOUDER Web Player` device).

The frontend therefore needs a clear contract for:

1. **Queue model** — what is the in-memory list of tracks the SDK plays through, and how does it relate to the bucket-tracks pagination API?
2. **No-Spotify-id behaviour** — UNCLASSIFIED tracks frequently lack `spotify_id`; what happens when the queue contains them?
3. **Playback scope across routes** — where in the app is the live player visible, where is it not, what happens when the user navigates away mid-playback?
4. **Device selection lifecycle** — when does the picker open, what is silently re-used, what is the fallback when a remembered device is offline?
5. **End-of-bucket behaviour** — what happens when auto-advance runs out of tracks in the focus bucket?
6. **Seek and quick-jump hotkeys** — DJ workflow demands fast skip-to-mid; standard scrub is necessary but not sufficient.

After this spec ships, the frontend team has a single source of truth for the playback subsystem, and can implement PlayerCard, queue manager, device picker (P-25), and the extended hotkey overlay without ad-hoc decisions.

## 2. Scope

**In scope:**

- Frontend-managed in-memory queue model and its lazy-loading contract against `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` and `GET /categories/{id}/tracks`.
- Spotify Web Playback SDK initialisation, lifecycle, token refresh integration.
- Device selection: picker, persistence to localStorage, fallback.
- Playback scope across routes: PlayerCard + mini-bar + leave-context confirm.
- Auto-advance, J/K manual nav, end-of-bucket behaviour.
- Seek hotkeys: `Q/W/E/R/T` (jump-to-percent) and `Shift+J` / `Shift+K` (±10s).
- Hotkey scope per route (Curate full set vs Categories detail subset).
- No-Spotify-id track handling (disable Play in row + auto-skip in queue).

**Out of scope:**

- Backend changes. This spec is frontend-only. The only backend touchpoint is the existing `/auth/spotify/refresh` route from spec-A.
- Spotify `audio-analysis` integration for true drop-detection (`FUTURE-G-PB-1`).
- Per-user hotkey rebinding UI (`FUTURE-G-PB-2`).
- Crossfade / gapless / pre-buffering optimisations beyond what the SDK provides natively.
- Mobile-app-specific playback (PWA / native wrappers) — this spec targets web browser only.
- Queue persistence across browser refreshes. A page refresh re-initialises the queue from the current bucket on first Play tap.
- Multi-tab coordination. If the user opens two CLOUDER tabs, each owns its own SDK instance and competes for the same Spotify Connect device. We do not coordinate them.
- Offline / network-loss recovery beyond surfacing the SDK's own error events. No retry queue.
- Listening analytics (track-completion, skip-rate). `FUTURE-G-PB-3`.

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| PB1 | Frontend is the source of truth for the queue. The Spotify SDK is told only about the **current track** via `play({uris: [current.spotify_uri]})`. `addToQueue` is not used. | A bucket can hold up to ~2000 tracks; pre-loading them all into Spotify's queue is wasteful and not supported by Spotify's per-call URI limits anyway. Frontend already paginates the bucket-tracks API; reusing that ordered list as the playback queue keeps a single source of truth. |
| PB2 | Queue scope = **focus bucket** of the current view (one bucket of one triage block, or one category). Order matches the bucket API: `added_at DESC, track_id ASC`. | Triage workflow is bucket-by-bucket; each bucket is a decision boundary. Mixing buckets into one queue would muddy the destination-tap context (hotkey 0–9 means different things per bucket). |
| PB3 | Queue is lazy-loaded in pages of 100 from the existing bucket-tracks endpoint. Initial Play loads page 1 (offset=0, limit=100); when the user nears the end of the loaded slice (within 5 tracks), the next page is fetched and appended. | Fits the spec-D `?limit=&offset=` contract verbatim. No new API. Cap of 100 per page balances initial Play latency against fetch frequency for 2000-track buckets. |
| PB4 | Tracks with `spotify_id IS NULL` are visible in the bucket list with a **disabled Play button** + tooltip "Нет Spotify match — слушай вручную". In the queue they are auto-skipped by J/K and auto-advance. | UNCLASSIFIED is the dominant no-Spotify case (NULL `spotify_release_date` ⇒ NULL `spotify_id`). Hiding them would obscure that the bucket has tracks; auto-skip in queue is zero-friction; disabled-Play-with-tooltip explains the asymmetry. |
| PB5 | Live PlayerCard (full form) is rendered inside Curate / Triage block (P-15..P-20) and Categories detail (P-10). All other routes (Tracks list, Profile, Library, Auth flow) show no PlayerCard. | Only Curate and Categories have the per-row Play affordance and the queue context. Tracks list is admin/discovery — Spotify Connect handles deep listening separately. |
| PB6 | When a queue is active and the user navigates to a route without a PlayerCard, a compact **mini-bar** is rendered at the bottom of the AppShell showing track + play/pause + close. Playback continues on the Spotify device in the background. | Real DJ workflow is fundamentally background: the user listens while reading release notes, browsing other categories, or tweaking Profile. Hard-stop on every route change would regress vs Spotify full app. |
| PB7 | Switching to a route that has its own PlayerCard with a **different queue context** (e.g. opening another triage block while a queue is active) prompts a confirm dialog: `Прервать текущую очередь?` { Да, новый блок \| Нет, остаться }. Accepting clears the existing queue and starts the new one fresh. | Defends against accidental queue loss; matches the DJ "I'm in the middle of a session" mental model. |
| PB8 | Default device on session start: silent `transferMyPlayback(localStorage.clouder.last_device_id)` if the device is in `getMyDevices()` and not `is_restricted`; otherwise open the P-25 picker. First-ever session always opens the picker. | Respects the user's last choice without being aggressive. The picker is the single fallback path — first-use, offline-device, manual override. |
| PB9 | Device pick (whether silent or via picker) writes the chosen `device_id` to `localStorage.clouder.last_device_id`. The CLOUDER Web Player virtual device counts here too. | Cross-session persistence. localStorage is appropriate — `device_id` is not a credential; it identifies the user's own hardware. |
| PB10 | When auto-advance reaches the end of the loaded queue and no more pages exist (focus bucket exhausted), playback **stops**. UI shows a hint: `Bucket finished. Next: <next_bucket_label> (<count> tracks) — нажми → или Tab чтобы продолжить`. There is no auto-jump to the next bucket. | Each bucket is a decision boundary; auto-jump would muddle the destination-tap hotkey context (hotkey 0–9 binds to the bucket the user is tapping into, and the user must consciously change focus). The hint preserves continuous-listen ergonomics with one explicit confirmation tap. |
| PB11 | Auto-advance after destination-tap: 200 ms hold (existing OPEN_QUESTIONS Q8 contract), then move queue cursor to next playable track (skipping no-Spotify-id rows per PB4) and `play()`. `U` (undo) within the 200 ms window cancels both the destination tap and the queue-cursor advance. | Preserves Q8 verbatim; PB4 layers on cleanly because the cursor advance walks the queue until it finds a `spotify_id`. |
| PB12 | A track that the user destination-taps **stays in the loaded queue** until session end / page refresh. The backend has already moved it to a staging bucket, but the frontend does not refetch the queue mid-session. | Refetching on every tap would break J/K consistency (the user might have just queued the next track in their head) and add latency. The in-memory queue is a snapshot; staging-buckets refresh is what the user opens later. |
| PB13 | Standard Spotify scrub bar in PlayerCard. Plus three classes of seek hotkeys: `Q W E R T` = jump to 0% / 20% / 40% / 60% / 80% of duration; `Shift+J` / `Shift+K` = −10s / +10s; native `seek(positionMs)` SDK call for both. | DJ-typical preview is mid-track, not intro. Percentage jumps cover the common "preview the drop / preview the breakdown" pattern; ±10s covers fine adjustments. Drop-detection via Spotify `audio-analysis` is `FUTURE-G-PB-1` (extra API call per track, fragile on lo-fi / ambient / intro-heavy material). |
| PB14 | Hotkey scope differs by route: Curate / Triage = full set (destinations `0–9` + `U` undo + playback `Space` `J/K` `Shift+J/K` `Q W E R T` + `?` overlay + `Esc`); Categories detail = playback subset only (`Space` `J/K` `Shift+J/K` `Q W E R T` + `?` + `Esc`). | Categories detail has no destination-tap mechanism (track is already in the category) and no undo target. Removing `0–9` and `U` from that scope prevents accidental no-op key presses. |
| PB15 | The Spotify SDK player is initialised lazily on first navigation into a PlayerCard route (Curate or Categories detail). Idle routes do not bear the SDK boot cost. | Avoids SDK init on Tracks-list / Profile / Auth pages where it is unnecessary; reduces time-to-interactive on the public Auth pages. The trade-off is a one-time ~200 ms init delay on the first Play tap; acceptable. |
| PB16 | Spotify access token is held in a React context provider, in-memory only, never localStorage / sessionStorage / cookies. Token refresh is auto-scheduled 5 min before `expires_in` via `/auth/spotify/refresh` (existing OPEN_QUESTIONS Q5 contract). On 401 from any Spotify Web API call (devices polling, transferPlayback), the frontend refreshes once and retries; a second 401 propagates to the user as a re-login prompt. | Token-in-memory is the OAuth-best-practice envelope from Q5. Auto-refresh schedule plus single-retry-on-401 covers the common edge case (token expired between the schedule and a network call). |
| PB17 | `getMyDevices` polling: every 30 s while a PlayerCard route is mounted, plus an immediate refresh on `window` `focus` event. Polling is paused on routes without a PlayerCard. | Matches OPEN_QUESTIONS Q5. Tab-focus refresh catches the common "I just plugged in headphones / opened Sonos" workflow. |
| PB18 | All UI strings in this spec are placeholders (Russian copy). Final wording is owned by design / copy. | Keeps spec implementable now; copy can land via PR comments without re-spec. |

## 4. Component Layout

### 4.1 React component tree (relevant subtree)

```
<AppShell>
  <Outlet />                                  // route content
  <PlaybackProvider>                          // SDK init, queue state, device state, token refresh
    <MiniBar />                               // visible if queue.active && route.hasPlayerCard === false
    <ConfirmDialog id="leave-queue-context" />
  </PlaybackProvider>
</AppShell>

// Inside Curate / Categories routes:
<PlayerCard />                                 // full form, hotkeys bound at this scope
```

`PlaybackProvider` exposes via context:

- `queue: { tracks, cursor, status }` where `status ∈ idle | loading | playing | paused | ended | error`.
- `device: { current_id, available[], picker_open }`.
- `controls: { play(track_idx), pause(), resume(), next(), prev(), seekMs(), seekPct(), addToQueue(track[]), clearQueue(), openPicker(), pickDevice(id) }`.
- `track: { current, position_ms, duration_ms }` — derived from SDK `player_state_changed`.

`PlayerCard` consumes the context. The mini-bar is a stripped-down view of the same context (track title + play/pause + close = `clearQueue` + dismiss).

### 4.2 Hotkey layer

A single `useHotkeys` invocation at the route level (Curate or Categories), bound to `document.body`. Definitions per PB14:

```ts
// Curate scope
{
  '0': () => destination(DISCARD),
  '1': () => destination(staging[0]), '2': () => destination(staging[1]), /* ... '6' */
  '7': () => destination(NEW), '8': () => destination(OLD), '9': () => destination(NOT),
  'space': () => controls.togglePlayPause(),
  'j': () => controls.prev(), 'k': () => controls.next(),
  'shift+j': () => controls.seekMs(track.position_ms - 10_000),
  'shift+k': () => controls.seekMs(track.position_ms + 10_000),
  'q': () => controls.seekPct(0),
  'w': () => controls.seekPct(0.2),
  'e': () => controls.seekPct(0.4),
  'r': () => controls.seekPct(0.6),
  't': () => controls.seekPct(0.8),
  'u': () => undoLastDestination(),
  '?': () => openHotkeyOverlay(),
  'escape': () => closeOpenOverlays(),
}

// Categories detail scope — drop destinations + U
```

Hotkey overlay (`?`) is rendered as a Mantine `Modal` listing the bindings active in the current scope. It must reflect the route scope (do not show `0–9` in Categories detail).

### 4.3 Queue manager

A small finite-state machine inside `PlaybackProvider`:

```
            ┌──────────┐  startPlay(track_idx) ┌──────────┐
            │   idle   │ ─────────────────────▶│ playing  │
            └──────────┘                       └──────────┘
                  ▲                                 │ │ ▲
                  │                  pause()        │ │ │ resume()
                  │                                 ▼ │ │
                  │                            ┌──────────┐
                  │                            │  paused  │
                  │                            └──────────┘
                  │                                 │
                  │ clearQueue() / leave-context    │
                  │                                 ▼
                  │                          ┌─────────────┐
                  └──────────────────────────│   ended     │
                                             └─────────────┘
```

`ended` enters when the cursor reaches the end of the loaded queue and no more pages exist (PB10). The hint UI is rendered from this state.

`error` is a side-state reachable from `loading` / `playing` on SDK error events; the UI shows a toast + retry button (re-issuing the last `play()` call).

### 4.4 Lazy queue loading

```
on Play tap:
  if track in loaded slice → set cursor; play
  else → fetch page containing track (offset = floor(track_idx / 100) * 100)

on cursor advance (auto-advance / J / K):
  if cursor >= loaded.length - 5 → fetch next page (offset = loaded.length, limit = 100)
  if response.items.length < limit → mark queue as fully loaded
  if cursor >= loaded.length and queue fully loaded → enter ended state (PB10)
```

Pages are accumulated; we never evict. A 2000-track bucket fully traversed = 20 fetches × 100 tracks ≈ 88 KB JSON × 20 = 1.7 MB cumulative — acceptable for a session.

### 4.5 Device picker

P-25 already exists in the design system. Mounts as a Mantine `Drawer` (mobile) / `Popover` (desktop). Visibility is driven by `device.picker_open`. States from OPEN_QUESTIONS Q5 verbatim:

- `playerReady === false` → connecting skeleton.
- `playerReady === true && devices.length === 0` → empty state with `Open Spotify, transfer playback to CLOUDER` instruction.
- `playerReady === true && devices.length > 0` → list with the CLOUDER Web Player virtual device pinned at top, marked `(this tab)`.

Selecting a device calls `transferMyPlayback(device_id)` and writes `localStorage.clouder.last_device_id = device_id`. On error (`account_error`, `playback_error`), the picker remains open and surfaces the SDK error; existing Q5 contract.

## 5. Data Flow

### 5.1 First Play in a session

```
User clicks Play on track row T in bucket B
  │
  ▼
PlayerCard.onPlay(T)
  │
  ▼
PlaybackProvider.controls.play(T.idx)
  │  ├── if SDK not initialised → init SDK; await `ready`
  │  ├── if device.current_id === null → open picker
  │  │   └── after pick → continue
  │  ├── if T.spotify_id === null → no-op (Play button was disabled — guard)
  │  ├── lazy-load page if T not in loaded slice
  │  ├── set queue.cursor = T.idx
  │  └── Spotify Web API: PUT /me/player/play { uris: [T.spotify_uri] }
  │
  ▼
SDK player_state_changed → status = playing, track.position_ms updates @ 250ms tick
  │
  ▼
PlayerCard renders track meta, scrub, controls
```

### 5.2 Auto-advance after destination-tap

```
User presses hotkey "3" (staging bucket index 2) while track T plays
  │
  ▼
Curate.onDestination(staging[2], T)
  │  ├── optimistic: hotkey overlay visual feedback (just-tapped pulse, OPEN_QUESTIONS Q7 / Q8)
  │  ├── POST /triage/blocks/{id}/move { from: B.id, to: staging[2].id, track_ids: [T.id] }
  │  └── after 200 ms hold:
  │       ├── if user pressed `U` → cancel: rollback move (DELETE) + abort cursor advance
  │       └── else: controls.next()  → cursor advance, skip no-spotify-id, play next
```

### 5.3 Route navigation while playing

```
User in Curate, queue is active, presses Tracks-list link
  │
  ▼
Router transition begins
  │  ├── if target route has its own PlayerCard with different context:
  │  │     show ConfirmDialog "Прервать текущую очередь?"
  │  │     → on cancel: stay
  │  │     → on confirm: clearQueue(); proceed
  │  └── else (e.g. Tracks list, Profile):
  │        proceed; PlayerCard unmounts; MiniBar appears (PB6)
```

### 5.4 Token refresh

```
On SPA mount with valid access_token:
  schedule timer at (now + expires_in - 300s) → refreshToken()

refreshToken():
  POST /auth/spotify/refresh  (cookie-based; no body)
    → 200 { access_token, expires_in }
    → store in context; reschedule timer
    → 401 / non-2xx: surface re-login prompt; clear queue; navigate to /auth/login

On any Spotify Web API call returning 401 (devices polling / transferPlayback):
  if not currently refreshing → refreshToken(); retry the original call once
  if retry also 401 → surface re-login prompt
```

## 6. Error Handling

| Source | Symptom | Frontend response |
|---|---|---|
| SDK `account_error` (Premium required) | User has free Spotify | Navigate to existing P-03 Premium-required state. Existing Q5 contract. |
| SDK `playback_error` | Generic SDK failure | Toast + retry button (re-issues last `play()`). Status enters `error` state. |
| SDK `authentication_error` | Token rejected | Trigger refresh; on retry-401, force re-login. |
| SDK `initialization_error` | SDK script load failed | Toast "Player init failed — refresh"; PlayerCard renders with disabled controls and reload link. |
| `transferMyPlayback` 404 | Selected device went offline | Reopen picker; surface "Devices changed — pick another". `last_device_id` is **not** cleared (might come back online). |
| `play()` 502 / 503 (Spotify side) | Transient | Retry once after 1 s; if still failing, toast + status=error. |
| Bucket-tracks API 404 (block deleted while listening) | spec-D allows soft-delete from another tab | Clear queue; toast "Block was deleted"; navigate to Triage list. |
| Network offline | Browser offline event | Mini-bar / PlayerCard show offline indicator; SDK keeps playing if device is not the CLOUDER tab. New `play()` calls deferred until online. |
| `lazy-load` page fetch fails | Network blip | Mark queue as `loading-error`; show inline retry on PlayerCard ("Could not load next page — retry"); J/K is disabled until retry succeeds. |
| Two CLOUDER tabs fighting for one device | One tab steals playback from the other | Out of scope (PB §2). The losing tab will see `player_state_changed` reflect the other tab's commands; UX may be confusing but is not destructive. Documented limitation. |

## 7. Hotkey Reference Table

| Key | Curate | Categories detail | Effect |
|---|---|---|---|
| `0` | ✅ | — | Destination = DISCARD |
| `1`–`6` | ✅ | — | Destination = staging[0..5] (per OPEN_QUESTIONS Q6 — first 6 only; rest via click) |
| `7` | ✅ | — | Destination = NEW |
| `8` | ✅ | — | Destination = OLD |
| `9` | ✅ | — | Destination = NOT |
| `Space` | ✅ | ✅ | Toggle play / pause |
| `J` | ✅ | ✅ | Previous track in queue (skips no-Spotify-id) |
| `K` | ✅ | ✅ | Next track in queue (skips no-Spotify-id) |
| `Shift+J` | ✅ | ✅ | Seek −10 s |
| `Shift+K` | ✅ | ✅ | Seek +10 s |
| `Q` | ✅ | ✅ | Seek to 0 % of duration |
| `W` | ✅ | ✅ | Seek to 20 % |
| `E` | ✅ | ✅ | Seek to 40 % |
| `R` | ✅ | ✅ | Seek to 60 % |
| `T` | ✅ | ✅ | Seek to 80 % |
| `U` | ✅ | — | Undo last destination (within 200 ms window per Q8; rolls back move + cancels auto-advance) |
| `?` | ✅ | ✅ | Open hotkey overlay (scope-aware) |
| `Esc` | ✅ | ✅ | Close open overlays / dialogs |

**Layout caveat:** `Q W E R T` assumes QWERTY physical layout. Dvorak / AZERTY users will see the keys map to different physical positions. iter-2a does not provide a rebinding UI; future preference covered by `FUTURE-G-PB-2`. Documented in the hotkey overlay.

## 8. State Diagrams

### 8.1 Queue lifecycle

Already described in §4.3. Transitions:

- `idle → playing` on `controls.play()`.
- `playing → paused` on `controls.pause()` or SDK external pause.
- `paused → playing` on `controls.resume()`.
- `playing → ended` when cursor reaches end of fully-loaded queue (PB10).
- any → `error` on SDK error event.
- any → `idle` on `controls.clearQueue()` or leave-context confirm.

### 8.2 Device state

```
            no_token
                │
                ▼ /auth/callback returns
         token_in_memory
                │
                ▼ first PlayerCard route mount
         sdk_initialising
                │
                ▼ SDK 'ready' event
         player_ready
                │
                ▼ first play attempt
         resolving_device ──┬─→ silent_pick (PB8) ──→ active
                            └─→ picker_open ────────→ active
                                                       │
                                                       ▼ user opens picker / device offline
                                                  picker_open ──→ active
```

`player_ready` corresponds to the existing OPEN_QUESTIONS Q5 `playerReady === true` boolean.

## 9. Testing

### 9.1 Unit (component / hook level)

- `PlaybackProvider.controls.play()` — token refresh path, lazy-load page path, SDK error path, no-Spotify-id guard.
- `PlaybackProvider.controls.next()` / `prev()` — skips tracks with `spotify_id === null` (PB4); enters `ended` state at end of fully-loaded queue (PB10).
- `useHotkeys` scope swap when navigating Curate ↔ Categories detail (PB14): destination keys silently no-op in Categories detail.
- Lazy-load — fetches next page on cursor near-end; deduplicates concurrent fetches; marks queue fully-loaded on short last page.
- `localStorage.clouder.last_device_id` — written on every successful `pickDevice`; cleared only on re-login (not on offline).
- Token refresh schedule — fires at `expires_in - 300` s; reschedules after refresh.
- `Q W E R T` hotkeys translate to correct `seek(positionMs)` values for several `duration_ms` samples (180s, 360s, 600s).
- `Shift+J / Shift+K` clamp at `[0, duration_ms]`.

### 9.2 Integration (tab-level, mocked SDK)

Mock the Spotify SDK with a stub that emits `ready`, `player_state_changed`, and the full error taxonomy on demand. Mock the Spotify Web API (`getMyDevices`, `transferMyPlayback`, `play`) with MSW.

1. **First Play happy path.** User logs in, navigates to Curate, picks a device, taps Play on the third track in NEW. Queue loads page 1, cursor=2, SDK plays, PlayerCard renders.
2. **Auto-advance after destination.** Press `3` (staging[2]); within 200 ms PlayerCard pulses; at 200 ms the move POST resolves; cursor advances; next track plays.
3. **Undo within window.** Press `3`, then `U` within 150 ms; move is rolled back; cursor stays; current track resumes.
4. **Skip no-Spotify-id.** Queue with tracks `[A(yes), B(null), C(null), D(yes)]`; auto-advance from A skips to D; J from D skips to A.
5. **End of bucket.** Queue fully loaded with 5 tracks; auto-advance past the last track; status enters `ended`; UI hint visible; pressing `→` (or click) opens the next bucket and starts its queue from track 0.
6. **Lazy-load near end.** Queue loaded with 100 tracks; cursor reaches 95; next-page fetch fires once; cursor 96–99 plays without re-fetch; cursor 100 plays from newly-loaded page 2.
7. **Lazy-load fetch failure.** Inject 500 on the second page; J/K disabled; retry button visible; on retry success J/K re-enabled.
8. **Route nav with active queue.** Start queue in Curate; navigate to Tracks list; PlayerCard unmounts; MiniBar appears; SDK keeps playing.
9. **Leave-context confirm.** Start queue in triage block 1; click triage block 2 link; ConfirmDialog appears; cancel → stay; confirm → clear; new queue starts.
10. **Mini-bar dismiss.** From Tracks list, click MiniBar close → queue clears, MiniBar disappears.
11. **Token refresh proactive.** Mount with `expires_in=600`; advance fake timer to 300s; refresh fires; new token in context.
12. **Token refresh on 401.** Spotify Web API call returns 401; refresh fires; original call retries once and succeeds; UX uninterrupted.
13. **Device offline fallback.** localStorage has `last_device_id=X`; X not in `getMyDevices`; picker opens; user picks Y; Y written to localStorage.
14. **Device picker first time.** localStorage empty; first Play tap opens picker; picker visible until user picks.
15. **CLOUDER tab as device.** SDK ready; user picks "CLOUDER Web Player"; transferMyPlayback succeeds; tab plays audio.
16. **SDK init lazy.** Mount Tracks list / Profile — SDK script not loaded. Navigate to Curate — SDK script loads; first Play succeeds after init.
17. **Hotkey scope per route.** In Curate, `5` triggers staging[4]. In Categories detail, `5` no-ops; only playback keys work.
18. **Seek hotkeys.** Track duration 360s; press `R` → position becomes 216s (60 %); press `Shift+J` → 206s; press `Q` → 0s.

### 9.3 Visual / manual

Cypress + a real Spotify Premium dev account (gated behind a flag in CI). Out of scope for `tests/` directory; run as a manual smoke before iter-2a release.

- Real `audio` plays through the CLOUDER tab when picked.
- Transfer to a real Spotify desktop / mobile device works.
- Tab focus event refreshes `getMyDevices`.
- Hotkey overlay matches §7 table per route.

### 9.4 Coverage

No numeric gate. Every state in §4.3 / §8.2 has at least one unit test; all 18 integration scenarios are required-green for spec-G ship.

## 10. Open Items, Edge Cases, Future Flags

### 10.1 Edge cases worth code comments

- **Two tabs fighting for one device.** Documented limitation (PB §2). The losing tab will see `player_state_changed` reflect the other tab's commands.
- **Mid-track destination tap with `U` undo right at 200 ms.** Race window. The implementation should treat the 200 ms timer as the source of truth: if `U` arrives `<= 200 ms` after the destination key, undo wins; if `> 200 ms`, the move and cursor advance commit and `U` becomes a no-op for this spec. Post-commit undo (rolling back an already-promoted move) is OPEN_QUESTIONS Q8 territory and is not extended here.
- **`localStorage.clouder.last_device_id` on logout.** Cleared on `POST /auth/logout` so a different user logging in on the same browser does not inherit the previous user's device.
- **Mini-bar persists across hard refresh?** No (PB §2 — no queue persistence across refresh). On refresh, mini-bar is gone; user re-taps Play in the bucket they came from.
- **`spotify_uri` reconstruction.** The bucket-tracks API returns `spotify_id` (the bare ID); the SDK needs a full `spotify:track:<id>` URI. Reconstruct in the frontend. Documented in the consuming code.

### 10.2 Future flags

- **`FUTURE-G-PB-1`** — Spotify `audio-analysis` integration for true drop-detection. Replaces the per-fixed-percentage Q-T jumps with a "drop" hotkey that seeks to the start of the highest-energy section.
- **`FUTURE-G-PB-2`** — Per-user hotkey rebinding UI in Profile. Persists to backend as `users.hotkey_layout` JSON. Solves the QWERTY-only assumption in §7.
- **`FUTURE-G-PB-3`** — Listening analytics: track-completion rate, skip-rate per bucket, avg listen duration before destination tap. Drives data-informed UX iteration in iter-2b.
- **`FUTURE-G-PB-4`** — Crossfade / gapless between queue tracks via SDK pre-buffering. Real-DJ-grade requirement, not iter-2a critical.
- **`FUTURE-G-PB-5`** — Multi-tab coordination via `BroadcastChannel`. One leader tab owns the SDK; others reflect its state read-only.
- **`FUTURE-G-PB-6`** — PWA / mobile-native wrappers with platform-specific playback. iter-2a is web only.

### 10.3 Cross-spec dependencies

- **Consumes** spec-D `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` with `limit` / `offset` for lazy queue loading.
- **Consumes** spec-C `GET /categories/{id}/tracks` with the same pagination contract for the Categories-detail PlayerCard.
- **Consumes** spec-A `/auth/spotify/refresh` for proactive and reactive token refresh.
- **Consumes** existing `clouder_tracks.spotify_id` (set by Spotify enrichment in spec-D §6.2).
- **Consumes** existing OPEN_QUESTIONS Q5 / Q6 / Q8 contracts and supersedes their loose ends with concrete decisions PB1–PB18.
- **Does not modify** any backend code or schema. Pure frontend spec.

## 11. Acceptance Criteria

- All 18 integration scenarios in §9.2 pass.
- Hotkey reference (§7) matches the rendered overlay in both Curate and Categories detail.
- A 2000-track bucket plays through end-to-end without OOM, without queue-jump glitches, and with no more than 21 bucket-tracks fetches (1 initial + 20 lazy).
- Token refresh: a session of 4 h sustains playback uninterrupted (token refresh fires multiple times silently).
- Device pick is silent on the second-and-subsequent session if the same device is online.
- No-Spotify-id tracks render with a disabled Play button and a tooltip; auto-advance and J/K skip them transparently.
- End-of-bucket renders the hint per PB10, and the suggested next-bucket affordance opens that bucket and begins its queue from track 0.
- Mini-bar appears outside Curate / Categories whenever a queue is active, and disappears on `clearQueue()`.
- Leave-context confirm fires when navigating to a different PlayerCard route; not when navigating to a non-PlayerCard route.

## 12. References

- Parent: [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md)
- spec-A (predecessor): [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md)
- spec-C (predecessor): [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md)
- Design handoff open questions: [`docs/design_handoff/OPEN_QUESTIONS.md`](../../design_handoff/OPEN_QUESTIONS.md) — Q5 (SDK / device picker), Q6 (hotkey scope), Q8 (auto-advance after destination), Q9 (long-op tolerances).
- Frontend integration guide: [`docs/frontend.md`](../../frontend.md)
- Spotify Web Playback SDK: <https://developer.spotify.com/documentation/web-playback-sdk>
- Spotify Connect protocol: <https://developer.spotify.com/documentation/web-api/concepts/spotify-connect>

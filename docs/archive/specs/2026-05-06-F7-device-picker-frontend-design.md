# F7 — Device picker (P-25, frontend)

**Date:** 2026-05-06
**Status:** brainstorm complete; awaiting plan
**Author:** @tarodo (via brainstorming session, Claude Opus 4.7)
**Parent (umbrella playback spec):** [`2026-04-29-playback-ux-design.md`](./2026-04-29-playback-ux-design.md) — PB1–PB18 architectural decisions.
**Predecessor:** [`2026-05-05-F6-player-frontend-design.md`](./2026-05-05-F6-player-frontend-design.md) — PlayerCard + sticky MiniBar; auto-pick CLOUDER tab stub which F7 replaces.
**Roadmap row:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F7** "Device picker · P-25 · Spotify Web API `getMyDevices`, `transferMyPlayback`".

**Predecessors (already shipped):**

- F1 — Categories CRUD.
- F2 — Triage list + create.
- F3a / F3b — Triage detail + transfer.
- F4 — Triage finalize + bulk transfer.
- F5 — Curate desktop + mobile.
- F6 — PlayerCard + sticky MiniBar; SDK lifecycle; silent auto-pick of the CLOUDER Web Player tab.

**Successors:**

- **F10 / F11** — PlayerCard inside Categories detail (P-10) reuses `DeviceIndicator` + the same picker surface.

## 1. Context and Goal

After F6, CLOUDER plays audio inline through the Spotify Web Playback SDK. Device selection is silent: on SDK `ready` the provider calls `transferMyPlayback(localDeviceId, { play: false })` and from then on every `play()`/`seek()`/`pause()` is sent against the CLOUDER Web Player tab. There is no way to:

- See where audio is going (the active device is implicit).
- Switch playback to another Spotify-connected device (laptop ↔ phone ↔ studio speakers).
- Recover gracefully when the active device disconnects mid-session.

F7 closes those gaps. It ships the full P-25 device picker UI (Drawer on mobile, Popover on desktop), `getMyDevices` polling, `localStorage`-backed silent restore of the user's last picked device, and a visible device indicator in PlayerCard + MiniBar. F6's silent CLOUDER-tab auto-pick becomes the *fallback* for first-session users; on subsequent sessions the user lands back on whichever device they last explicitly picked.

After F7 the user can:

- Glance at PlayerCard or MiniBar and read which device is active (a pill with device-type icon and name).
- Tap the pill (or the wired-up "Open device picker" link in the disconnected state) to open the picker.
- Pick any visible device — playback transfers via Spotify Connect; subsequent controls target the new device.
- Have the previous picked device silently restored on the next session, falling back to CLOUDER Web Player if the saved device is offline.

## 2. Scope

**In scope:**

- `getMyDevices` API call inside `frontend/src/features/playback/api/spotifyWebApi.ts` (uses the existing 401-retry-once wrapper).
- Spotify device type definitions (`SpotifyDevice`, `SpotifyDeviceType`).
- Picker UI:
  - `DevicePicker.tsx` — desktop Mantine `<Popover>` content, anchored to the indicator that opened it.
  - `DeviceDrawer.tsx` — mobile Mantine `<Drawer position="bottom">` content.
  - `DevicePickerSurface.tsx` — media-query wrapper, mounted globally in `_layout.tsx`.
- `DeviceIndicator.tsx` — pill (icon + truncated name) rendered in PlayerCard subline (full mode) and MiniBar (compact mode); tap opens the picker.
- `DeviceList.tsx` + `DeviceRow.tsx` — list rendering shared by desktop and mobile surfaces.
- `PlaybackProvider` extension (per Approach 2): new `devices` slice on the context value with `list`, `active`, `cloderTabId`, `isLoading`, `error`, `isOpen`, `open`, `close`, `refresh`, `pick`.
- Polling lifecycle managed by `PlaybackProvider`:
  - 30 s + `window` `focus` baseline when picker is closed.
  - 5 s aggressive when picker is open.
  - Paused while `sdk.ready === false`.
- `lastDeviceStore.ts` — thin wrapper over `localStorage.clouder.last_device_id`. Write only on user-explicit `pick()`. Read on bootstrap.
- Bootstrap silent restore: at SDK `ready`, wait for the first `getMyDevices` poll, then transfer to `last_device_id` if it's in the list, else to CLOUDER Web Player.
- Wire `disconnected`-state PlayerCard "Open device picker" link to `playback.devices.open()` (was a no-op stub in F6).
- Auto-refresh `getMyDevices` on `transferMyPlayback` 404; picker stays open with the refreshed list.
- Empty / connecting / loading / error / list states for the picker.

**Out of scope (deferred):**

- Multi-device output / crossfade — FUTURE.
- Device renaming, favoriting, or pinning — FUTURE.
- Volume slider per device (Spotify supports `setVolume` but it's a separate UX surface) — FUTURE.
- Polling pause when `document.hidden === true` — micro-optimisation; revisit in F10 if cost shows up.
- BroadcastChannel multi-tab coordination — `FUTURE-G-PB-5`.
- "Bring back here" express button (one-tap to switch back to CLOUDER tab without opening picker) — may land as F10 polish.
- Hotkey for opening picker (`Shift+D` candidate; `KeyD` is reserved for 40 % seek) — FUTURE.
- PlayerCard inside Categories detail (P-10) — F10 / F11.

## 3. Architectural Decisions

The umbrella spec (`2026-04-29-playback-ux-design.md`) owns PB1–PB18. F6 added F6-1 through F6-14. F7 adds the decisions below; conflicts with F6 are called out explicitly.

| # | Decision | Rationale |
|---|---|---|
| **F7-1** | F6-3 is unlocked. The active playback device may be any device returned by `getMyDevices`; the CLOUDER Web Player tab is one option among many. `PlaybackProvider` keeps two refs: `activeDeviceIdRef` (where audio is playing — used by every `play`/`seek`/`pause` call) and `cloderTabIdRef` (the local SDK device, set on SDK `ready`, used as bootstrap fallback). | F6-3 was a temporary auto-pick to ship playback without picker UI; F7's whole point is to expose device choice. |
| **F7-2** | `lastDeviceStore.set(deviceId)` is called only inside the user-driven `devices.pick()` handler on success. It is **not** called from the bootstrap auto-transfer or from the auto-pick CLOUDER-tab fallback. | If bootstrap wrote to localStorage, the auto-fallback would overwrite a previously saved remote device every cold start and silent restore would never trigger. |
| **F7-3** | Bootstrap silent restore sequence: SDK `ready` → set `cloderTabIdRef` → run the first `getMyDevices` refresh → resolve `activeDeviceId = lastDeviceStore.get()` if that ID is in the returned list, else `cloderTabIdRef.current` → `transferMyPlayback({ deviceId: activeDeviceId, play: false })`. If `getMyDevices` itself errors, fall back silently to CLOUDER tab without retry. The existing F6 `deviceReadyRef` Promise (resolved on SDK `ready` today) is **extended**: it now resolves only AFTER the bootstrap transfer completes. `controls.play()` calls that race the bootstrap (e.g. user mashes Play before the first poll returns) await `deviceReadyRef.current.promise` exactly as in F6. | Preserves F6's invariant "playback works after SDK ready" even on a network blip; avoids a stuck "Connecting…" state if Spotify's device endpoint is briefly unhealthy. The Promise extension is the smallest change that keeps the F6 race-handling pattern correct in the F7 multi-step bootstrap. |
| **F7-4** | `DevicePickerSurface` is mounted exactly once in `routes/_layout.tsx` alongside `<MiniBar />` and `<LeaveContextDialog />`. It internally selects `<Drawer>` (mobile, `useMediaQuery('(max-width: 64em)')`) or `<Popover>` (desktop, anchored to the last-clicked `DeviceIndicator`). Consumers (`DeviceIndicator` in PlayerCard / MiniBar; the disconnected-state link) are pure triggers — they call `playback.devices.open()` and pass an anchor ref. | One picker per session; trigger surfaces multiply but the modal/drawer mount stays single. Avoids two picker instances racing on the same `getMyDevices` poll. |
| **F7-5** | Polling is owned by a single `useEffect` inside `PlaybackProvider` with deps `[sdkReady, isOpen]`. `setInterval(refresh, isOpen ? 5000 : 30000)` plus a `window` `focus` listener. Cleanup on dep change and unmount. | One source of truth. A second `useEffect` (e.g. inside the picker component) would race and double-fire `getMyDevices`. |
| **F7-6** | Polling is paused while `sdk.ready === false`. Polling is enabled on every authenticated route (not just PlayerCard routes) so the MiniBar pill always reflects current state. F6's lazy SDK init still applies — the SDK script only loads on first PlayerCard route mount; once loaded, it stays for the session and the polling effect runs whenever `_layout` is mounted. | Without this, the MiniBar pill on Tracks list / Profile / Home would show stale device state and tapping the pill would open a picker with a stale list. The Spotify Web API call is cheap enough to run from any authenticated route. |
| **F7-7** | Device-type icons map from Spotify's `type` field via a single `iconForDeviceType()` helper. CLOUDER Web Player tab gets a special `IconCloud` icon (not the generic `Computer`) so the user can recognise it instantly in the list. | Visual recognition beats textual scanning, especially when multiple Computer-type devices are signed in. |
| **F7-8** | Transfer failure handling: any 4xx / 5xx (except 401, which is handled inside `spotifyWebApi.ts` via the existing `onAuthExpired` flow) → toast + immediate `refresh()` → picker stays open with the freshly fetched list. 401 second-failure path falls through to the F6 re-login flow. 403 (rare; usually caught at SDK init) → navigate to `/auth/premium-required` (P-03). | Q3 lock: auto-heal. Self-refresh removes the offline device from the list so the user's next tap can succeed. |
| **F7-9** | When the active device disappears from a polling refresh (mid-session offline), `PlaybackProvider` flips `queue.status` to `disconnected` and surfaces the existing F6 disconnected PlayerCard state. The wired "Open device picker" link is the recovery path. No automatic re-transfer to CLOUDER tab — user intent matters more than convenience here. | Silent re-transfer would surprise users who lost their kitchen speaker and now hear audio from their laptop without consenting. |
| **F7-10** | `localStorage` access is wrapped in try/catch. If unavailable (Safari private mode, storage quota, etc.) `lastDeviceStore` is a no-op store; the picker still works without persistence. | F6 already in-memory only for `spotify_access_token`; the principle for F7 is that persistence is a UX nicety, not a correctness requirement. |

## 4. Component Layout

### 4.1 New files

```
frontend/src/features/playback/
├── DevicePicker.tsx              // desktop <Popover> content
├── DeviceDrawer.tsx              // mobile <Drawer> content
├── DevicePickerSurface.tsx       // media-query wrapper, mounted in _layout
├── DeviceIndicator.tsx           // pill (icon + name + open trigger)
├── DeviceList.tsx                // shared connecting/loading/empty/error/list switch
├── DeviceRow.tsx                 // single row (icon, name, active check, restricted badge)
├── DevicePicker.module.css       // popover, drawer, pill styles
└── lib/
    ├── deviceTypes.ts            // SpotifyDevice + SpotifyDeviceType + iconForDeviceType
    ├── lastDeviceStore.ts        // localStorage read/write/clear; try/catch wrapped
    └── usePolling.ts             // generic interval hook; respects enabled flag + window focus
```

API addition (existing file):

- `frontend/src/features/playback/api/spotifyWebApi.ts` — `getMyDevices(opts)` returning `Promise<SpotifyDevice[]>`. Uses the existing `call('GET', '/v1/me/player/devices', null, opts)` wrapper for 401-retry-once.

### 4.2 Existing files to edit

- `frontend/src/features/playback/PlaybackProvider.tsx` — add `devices` slice (state + refs); add the polling `useEffect`; rename `deviceIdRef` (semantic only) to `activeDeviceIdRef` and add `cloderTabIdRef`; refactor SDK `ready` handler to wait for first poll then resolve active device per F7-3; add `pick()` and `refresh()` implementations; on polling refresh, detect `activeDeviceId ∉ list` and flip status to `disconnected`.
- `frontend/src/features/playback/usePlayback.ts` — type widen the context to include `DevicesSlice`.
- `frontend/src/features/playback/PlayerCard.tsx` — render `<DeviceIndicator mode="full" />` in subline below artists. In `disconnected` state, replace the no-op "Open device picker" link with a `<button onClick={playback.devices.open}>` that also passes an anchor ref.
- `frontend/src/features/playback/MiniBar.tsx` — render `<DeviceIndicator mode="compact" />` to the left of the Play/Pause `ActionIcon`.
- `frontend/src/routes/_layout.tsx` — mount `<DevicePickerSurface />` after `<MiniBar />` and alongside `<LeaveContextDialog />`.

### 4.3 `DevicesSlice` shape

```ts
type SpotifyDeviceType =
  | 'Computer' | 'Smartphone' | 'Speaker' | 'TV'
  | 'CastVideo' | 'CastAudio' | 'AVR' | 'STB'
  | 'AudioDongle' | 'GameConsole' | 'AutomobileVoice' | 'Unknown';

interface SpotifyDevice {
  id: string;
  name: string;
  type: SpotifyDeviceType;
  is_active: boolean;
  is_private_session: boolean;
  is_restricted: boolean;
  volume_percent: number | null;
}

interface DevicesSlice {
  list: SpotifyDevice[];
  active: SpotifyDevice | null;
  cloderTabId: string | null;
  isLoading: boolean;
  error: 'network' | 'auth' | null;
  isOpen: boolean;
  open: (anchor?: HTMLElement | null) => void;
  close: () => void;
  refresh: () => Promise<void>;
  pick: (deviceId: string) => Promise<void>;
}
```

`active` is reactive: the provider holds `activeDeviceId` as `useState<string | null>(null)` AND mirrors it into `activeDeviceIdRef.current` synchronously inside every setter (F5 lesson 55 pattern). Synchronous consumers — `controls.play() / seek() / pause()` — read the ref. The `devices.active` slot exposed on context is computed via `useMemo(() => list.find(d => d.id === activeDeviceId) ?? null, [list, activeDeviceId])`. State drives re-renders so `DeviceIndicator` updates; ref drives synchronous SDK calls so they don't race React scheduling. `active` is `null` while bootstrap restore is in flight or when the active device ID is not present in the latest poll (which flips `queue.status` to `disconnected` per F7-9).

### 4.4 Picker state matrix

| State | Trigger | Render |
|---|---|---|
| `connecting` | `sdk.ready === false` | Skeleton with 3 ghost rows + caption "Connecting to Spotify…" |
| `loading` | `isLoading && list.length === 0` | Same skeleton |
| `empty` | `!isLoading && list.length === 0 && error === null` | EmptyState: "No devices found. Open Spotify on a device, then refresh." + Refresh button |
| `error` | `error === 'network'` | "Couldn't load devices · Retry" button |
| `auth-error` | `error === 'auth'` | "Re-sign in to Spotify" linking to `/auth/login` |
| `list` | `list.length > 0` | Rows: icon + name + (check icon if `device.id === active?.id`) + (restricted badge if `is_restricted`) |

### 4.5 `DeviceIndicator` anatomy

- Compact mode (MiniBar): `Icon 16` + truncated name (max-width 80 px) + invisible click target. Tap → `devices.open(anchorEl)`.
- Full mode (PlayerCard): `Icon 14` + name (max-width 160 px) + `ChevronDownIcon`. Mounted in PlayerCard subline as `Stack(artists, indicator)`. Disabled (`active === null`) → grayed pill with copy "No device" or hidden entirely.

### 4.6 `iconForDeviceType` mapping

```
Computer        → IconDeviceLaptop  (or IconCloud if device.id === cloderTabId)
Smartphone      → IconDeviceMobile
Tablet          → IconDeviceTablet
Speaker         → IconDeviceSpeaker
TV              → IconDeviceTv
CastVideo       → IconCast
CastAudio       → IconBroadcast
AVR             → IconDeviceTv
STB             → IconDeviceTv
AudioDongle     → IconHeadphones
GameConsole     → IconDeviceGamepad
AutomobileVoice → IconCar
Unknown         → IconDeviceUnknown
```

The CLOUDER-tab override happens inside `iconForDeviceType(device, cloderTabId)`, not inside the row component, so the same mapping is reused everywhere.

## 5. Data Flow

### 5.1 Cold start, no `last_device_id` saved

```
Login → AuthProvider populates spotify_access_token
User navigates to first PlayerCard route (Curate)
  ↓
PlaybackProvider mounts; sdkLoader loads SDK script
SDK 'ready' event → cloderTabIdRef = device_id; sdk.ready = true
PlaybackProvider effect [sdkReady]:
  → refresh()  // first getMyDevices call
  → list = [CLOUDER Web Player, ...other clients]
  → resolve activeDeviceId:
      lastSaved = lastDeviceStore.get()  // null
      → activeDeviceIdRef = cloderTabIdRef
  → spotifyApi.transferMyPlayback({ deviceId: activeDeviceId, play: false })
  → polling effect starts: setInterval(refresh, 30000) + focus listener
DeviceIndicator on PlayerCard reads list + activeDeviceIdRef → "CLOUDER Web Player" + IconCloud
```

### 5.2 Cold start, `last_device_id` matches an online device

```
SDK ready → cloderTabIdRef set
First refresh → list = [CLOUDER, "iPhone", "KitchenSpeaker"]
lastSaved = "spotify:device:iphone-uuid"
list.find(d => d.id === lastSaved) → iPhone present
activeDeviceIdRef = iPhone.id
transferMyPlayback({ deviceId: iPhone.id, play: false })
DeviceIndicator → "iPhone" + IconDeviceMobile
lastDeviceStore is NOT touched (this transfer is a silent restore, F7-2)
```

### 5.3 Cold start, `last_device_id` saved but offline

```
SDK ready → cloderTabIdRef set
First refresh → list = [CLOUDER, "KitchenSpeaker"]   // no iPhone
lastSaved = "spotify:device:iphone-uuid"
list.find ... → undefined → fallback CLOUDER tab
activeDeviceIdRef = cloderTabIdRef
transferMyPlayback({ deviceId: cloderTabIdRef, play: false })
lastDeviceStore.clear()  // OPTIONAL: only if we want to forget stale IDs
                          // Default: keep — iPhone may come back in next sessions
```

We default to **keeping** the stale ID. If the user picks a new device the entry is overwritten. Wiping on first miss would punish "iPhone is just sleeping for one session" cases.

### 5.4 User opens picker, picks a remote speaker

```
User taps DeviceIndicator on PlayerCard (or MiniBar)
  → playback.devices.open(anchorEl)
  → isOpen = true → polling effect re-runs with intervalMs=5000
DevicePickerSurface re-renders with isOpen=true
  → mobile: <Drawer opened>
  → desktop: <Popover opened anchor={anchorEl}>
DeviceList renders rows from current list
User taps "KitchenSpeaker" row
  → playback.devices.pick(speaker.id)
      → spotifyApi.transferMyPlayback({ deviceId: speaker.id, play: false })
        ├── 200/204 → activeDeviceIdRef = speaker.id
        │              lastDeviceStore.set(speaker.id)
        │              close()  // picker closes
        └── 404 → toast "Device offline"; refresh() immediately; picker stays open
SDK 'player_state_changed' propagates new state via Spotify Connect; PlayerCard updates positionMs + paused via existing F6 listener
Subsequent play/seek/pause target speaker.id via activeDeviceIdRef
```

### 5.5 Active device disappears mid-session

```
KitchenSpeaker disconnects from Wi-Fi
  → next polling tick (5 s if picker open, 30 s if not)
  → list = [CLOUDER, "iPhone"]   // no speaker
  → effect detects activeDeviceIdRef ∉ list
  → queue.status = 'disconnected'
PlayerCard renders disconnected state
User taps "Open device picker" link → playback.devices.open(linkAnchor)
User picks CLOUDER tab → transferMyPlayback → status returns to 'paused' (last known SDK state)
User taps Play (or Space) → resumes audio on CLOUDER tab
```

### 5.6 Polling lifecycle

```
sdk.ready === false                  → no polling; cleanup any prior interval
sdk.ready === true, isOpen === false → setInterval(refresh, 30000) + focus listener
sdk.ready === true, isOpen === true  → setInterval(refresh, 5000) + focus listener
deps change                          → cleanup previous interval/listener, mount new
unmount (logout / tab close)         → cleanup
```

### 5.7 Token refresh during polling

`getMyDevices` goes through the same `call(...)` wrapper as `play` / `transferMyPlayback` / `seek`, so 401 → `onAuthExpired` → `AuthProvider.forceRefresh()` → retry once. A second 401 sets `error = 'auth'`; the picker shows "Re-sign in to Spotify" linking to `/auth/login`.

## 6. Error Handling

| Source | Symptom | Frontend response |
|---|---|---|
| `getMyDevices` 401 | Token expired | `onAuthExpired` retry-once via existing `spotifyWebApi.ts` flow; on second 401 → `error = 'auth'`; picker shows "Re-sign in" |
| `getMyDevices` 5xx | Spotify transient outage | `error = 'network'`; picker shows "Couldn't load · Retry"; auto-retry on the next interval tick |
| `getMyDevices` network failure | Browser offline / DNS / etc | Same as 5xx — `error = 'network'` |
| `transferMyPlayback` 404 | Device went offline between poll and tap | Toast "Device offline · refresh"; immediate `refresh()`; picker stays open with the freshened list |
| `transferMyPlayback` 403 | Premium-required (rare; usually caught at SDK init) | `navigate('/auth/premium-required')` (P-03) |
| `transferMyPlayback` 5xx | Spotify transient | Toast "Switch failed · Retry"; picker stays open; no auto-retry (user retries manually) |
| Bootstrap restore: `last_device_id` stale | localStorage has ID not in current list | Silent fallback to CLOUDER tab. lastDeviceStore is **not** cleared — iPhone may come back next session |
| `localStorage` unavailable (Safari private mode, quota) | `lastDeviceStore.set/get/clear` throws | Try/catch wrapper makes the store a no-op; picker still functional without persistence |
| Active device disappears mid-session | Polling tick returns list without `activeDeviceId` | `queue.status = 'disconnected'`; F6 disconnected PlayerCard state; user opens picker manually |

## 7. Hotkeys

F7 does not introduce hotkeys. The picker is opened by tap on `DeviceIndicator` (PlayerCard or MiniBar) or by tap on the wired-up "Open device picker" link in the disconnected state.

A `Shift+D` candidate exists for a future "open picker" hotkey (`KeyD` is already bound to seek 40 % per F6 § 4.6). Not in scope; revisit in F10 polish if a real DJ workflow demands it.

## 8. Testing

### 8.1 Unit (target ~14)

1. `spotifyWebApi.getMyDevices` — happy path; 401-retry-once; 5xx surface error.
2. `lastDeviceStore` — `get` / `set` / `clear`; try/catch wraps `localStorage` access (assert no throw when `localStorage` is shimmed unavailable).
3. `iconForDeviceType` — every `SpotifyDeviceType` value maps to expected icon; CLOUDER-tab override returns `IconCloud` when `device.id === cloderTabId`.
4. `usePolling` — interval respects `enabled` flag; swaps interval on `intervalMs` change; cleans up on unmount; `window` focus event triggers refresh.
5. `DeviceIndicator` — full mode renders chevron; compact mode does not; disabled state when `active === null`; click invokes `devices.open(anchor)`.
6. `DeviceRow` — active-check icon when `device.id === active?.id`; restricted badge when `device.is_restricted === true`; click invokes `pick(device.id)`.
7. `DeviceList` — renders the right state for connecting / loading / empty / error / auth-error / list inputs.
8. `DevicePicker` (desktop) — opens at the anchor element; closes on outside click; closes on escape.
9. `DeviceDrawer` (mobile) — opens from bottom; closes on backdrop tap; closes on swipe-down (best-effort under jsdom — fall back to verifying `onClose` callback wiring).
10. `DevicePickerSurface` — renders `<Drawer>` when `useMediaQuery('(max-width: 64em)')` is true; `<Popover>` otherwise.
11. `PlaybackProvider.devices.pick()` — happy path (transfer success → `activeDeviceIdRef` updates → `lastDeviceStore.set` called → `close()`); 404 path (toast + refresh + picker stays open); 5xx path (toast, no refresh, no close).
12. `PlaybackProvider` bootstrap restore — last_device matches list element → `transferMyPlayback` called with that ID, `lastDeviceStore.set` **NOT** called; last_device missing from list → fallback CLOUDER tab, `lastDeviceStore.set` not called; lastDeviceStore returns null → CLOUDER tab.
13. `PlaybackProvider` polling — interval is 5 s while `isOpen`, 30 s while closed; focus event fires `refresh`; effect cleans up on unmount.
14. `PlaybackProvider` active-device-offline detection — polling refresh that omits `activeDeviceId` flips `queue.status` to `disconnected`.

### 8.2 Integration (mocked SDK + MSW; target ~9)

Mock Spotify Web API endpoints `/v1/me/player/devices`, `/v1/me/player/play`, `/v1/me/player` (transfer), `/v1/me/player/seek` via MSW. Reuse the F6 SDK stub.

1. **Cold start, no last_device.** Login → Curate → SDK ready → first `getMyDevices` returns `[CLOUDER]` → `transferMyPlayback(cloderId)` → `DeviceIndicator` reads "CLOUDER Web Player" + IconCloud.
2. **Cold start, last_device offline.** Pre-seed `lastDeviceStore` with stale ID → SDK ready → first poll returns list without that ID → fallback CLOUDER tab → indicator shows CLOUDER. lastDeviceStore is unchanged.
3. **Cold start, last_device online.** Pre-seed lastDeviceStore with iPhone ID → first poll returns list including iPhone → silent transfer to iPhone → indicator shows "iPhone" + IconDeviceMobile.
4. **Open picker desktop.** `useMediaQuery` mocked to false (≥ 64em) → tap `DeviceIndicator` on PlayerCard → `<Popover>` opens with list.
5. **Open picker mobile.** `useMediaQuery` mocked to true → tap `DeviceIndicator` on MiniBar (after navigating off the PlayerCard route) → `<Drawer>` opens from bottom.
6. **Pick remote device happy path.** Picker open, list contains "KitchenSpeaker" → tap row → MSW returns 204 → `lastDeviceStore.get()` returns speaker ID → picker closes → indicator updates.
7. **Pick remote device 404.** Picker open → tap stale "iPhone" → MSW returns 404 → toast "Device offline" appears → next `getMyDevices` poll returns list without iPhone → picker stays open with refreshed list.
8. **Disconnected → picker.** Force SDK `initialization_error` → PlayerCard renders disconnected state → tap "Open device picker" link → picker opens (uses link as anchor on desktop; Drawer on mobile).
9. **Polling cadence.** With fake timers: picker closed, advance 30 s → MSW recorded one extra `getMyDevices` call. Open picker, advance 5 s → another call. Close picker, advance 5 s → no new call (next call at +30 s).

### 8.3 Coverage / bundle ratchet

Bundle target: +10–18 KB minified (no new runtime deps; pure code paths). F6 baseline 910 KB → F7 ≤ 928 KB.

Test count delta target: +20 / +30 vs F6 baseline (~430 / ~440 total).

Spotify SDK type declarations in `frontend/src/types/spotify-sdk.d.ts` already exist (F6); F7 adds local `SpotifyDevice` types in `lib/deviceTypes.ts` and does not add new `@types/*` deps.

### 8.4 Manual

Out of CI:

- Real Spotify Premium dev account, two devices (laptop + phone): cold start → CLOUDER tab. Open picker → pick phone → audio shifts to phone, indicator updates. Reload page → silent restore to phone (last_device_id remembered).
- Disconnect phone Wi-Fi mid-session: PlayerCard flips disconnected within 30 s; picker recovers via CLOUDER-tab pick.
- Mobile Safari: Drawer opens from bottom, swipe-down dismiss works.

## 9. Acceptance Criteria

- `DeviceIndicator` renders in PlayerCard subline (full mode) and MiniBar (compact mode); tap opens the picker.
- Bootstrap silent restore: with `last_device_id` saved and online, audio is on the saved device after SDK ready (no manual user action required).
- `lastDeviceStore.set` is called only inside user-driven `pick()` (verified by integration test 1 + 2: no localStorage write on bootstrap auto-pick).
- Picker auto-refreshes on `transferMyPlayback` 404; the offline device is removed from the list on the refresh.
- Polling cadence verified: 5 s while picker open, 30 s + window focus while closed.
- F6 disconnected-state "Open device picker" link is wired and opens the picker.
- Empty list state copy matches OPEN_QUESTIONS Q5: "No devices found. Open Spotify on a device, then refresh."
- All 14 unit + 9 integration tests green.
- F1–F6 test suites: zero regressions.
- Bundle increase ≤ 18 KB minified.

## 10. Open Items, Edge Cases, Future Flags

### 10.1 Edge cases worth a code comment

- **`lastDeviceStore` race with bootstrap.** If the user logs out and immediately back in within the same tab (same `localStorage`), `lastDeviceStore.get()` returns the previous user's saved ID. Acceptable today (auth flow clears tokens but not localStorage); flag for review if multi-account support arrives.
- **Picker open during SDK reconnect.** If SDK fires `not_ready` while picker is open, `sdk.ready` flips false → polling pauses → list goes stale. Document this; the picker should still allow the user to close it. Re-opening after `not_ready` will show the connecting skeleton until SDK comes back.
- **Two CLOUDER tabs in the same browser.** Each tab registers its own SDK device via the SDK script. `getMyDevices` returns both as separate "CLOUDER Web Player" entries. The `cloderTabId` override-icon logic only matches the *current tab's* ID; the other tab's entry shows as `IconDeviceLaptop` (a generic Computer). Acceptable — multi-tab UX is a known limitation (umbrella spec § 6 row 9).
- **`is_restricted` rows.** Spotify marks devices that don't support remote control as `is_restricted: true`. F7 renders a badge but does not disable the row — Spotify is the authority on whether a transfer succeeds. If a restricted-row pick 404s, the auto-refresh + toast pattern handles it.
- **Mobile Drawer + active scroll.** When the picker drawer opens over a scrolled Curate session, the body should not scroll behind. Mantine `<Drawer>` handles this by default (`lockScroll`); verify no regression on F5 hotkey edges.
- **`activeDeviceIdRef` mid-`pick()`.** The optimistic update of `activeDeviceIdRef` happens after the `transferMyPlayback` resolves successfully. If the user taps a second device while the first transfer is in flight, the second `pick()` should wait for the first (or cancel). Implementation: serialise `pick()` calls via a `pendingPickRef` Promise; a second tap during in-flight transfer is a no-op until the first resolves.

### 10.2 Carryover to F10 / F11

- `DeviceIndicator` reused in PlayerCard inside Categories detail (P-10).
- `DevicePickerSurface` mounted in `_layout` already covers Categories detail without changes.
- Future: dedicated indicator state for "device transfer in progress" (a brief spinner inside the pill) — out of F7 scope; current UX uses the picker close-on-success as the affordance.

### 10.3 Future flags

- `FUTURE-G-PB-5` — multi-tab `BroadcastChannel` coordination; not blocking F7.
- `FUTURE-F7-1` — `Shift+D` hotkey to open picker.
- `FUTURE-F7-2` — "Bring back here" express button on PlayerCard when active ≠ CLOUDER tab.
- `FUTURE-F7-3` — Volume slider per device (Spotify `setVolume`).
- `FUTURE-F7-4` — `document.hidden` polling pause to save Spotify API quota on backgrounded tabs.
- `FUTURE-F7-5` — Device renaming / favoriting / pinning UI.

## 11. References

- Umbrella playback spec: [`2026-04-29-playback-ux-design.md`](./2026-04-29-playback-ux-design.md)
- F6 design: [`2026-05-05-F6-player-frontend-design.md`](./2026-05-05-F6-player-frontend-design.md)
- spec-A (auth, Spotify token plumbing): [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md)
- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md)
- Design handoff:
  - `docs/design_handoff/03 Pages catalog · Pass 2 (Curate-Patterns).html` (P-25)
  - `docs/design_handoff/04 Component spec sheet.html` § Drawer / Popover / EmptyState
  - `docs/design_handoff/OPEN_QUESTIONS.md` Q5 (SDK / device picker)
  - `docs/design_handoff/MANTINE_9_NOTES.md` (Drawer scroll lock, Popover anchor handling)
- Spotify Web API:
  - <https://developer.spotify.com/documentation/web-api/reference/get-a-users-available-devices>
  - <https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback>
- Spotify Connect: <https://developer.spotify.com/documentation/web-api/concepts/spotify-connect>

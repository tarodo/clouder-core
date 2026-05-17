# ADR-0013: PlaybackProvider in authenticated layout, SDK lazy-loaded
Status: Accepted
Date: 2026-05-17

## Context

The Spotify Web Playback SDK is a ~150 kB browser script loaded from `sdk.scdn.co`. It initialises a Web Audio context, registers a Spotify Connect device, and emits `player_state_changed` events throughout its lifetime. Initialising the SDK has several costs: the script load itself, an immediate call to `getOAuthToken` to fetch the Spotify access token, and a `transferMyPlayback` call to nominate the CLOUDER browser tab as the active Connect device.

Two questions arose: where in the component tree should the provider live, and when should the SDK script be fetched?

**Provider placement**: `PlaybackProvider` could live at the root (wrapping even public routes), at the authenticated shell layout (always mounted for logged-in users), or at individual route level (mounted only on curate/category routes). Root placement would attempt SDK initialisation before login, which is incorrect — there is no Spotify token before auth. Route-level placement would re-initialise the SDK on every route change, interrupting playback. The authenticated shell layout is the right boundary: always mounted for logged-in users, dismounted on logout, never instantiated on public auth pages.

**SDK lazy load**: the SDK script is large and its initialisation has side effects (Web Audio, device registration). A user who logs in and immediately views their categories list should not be burdened with SDK initialisation if they never start playback. The SDK script is therefore fetched on the first `controls.play()` call only (`loadSpotifySdk()` in `sdkLoader.ts`). Subsequent calls reuse the already-loaded script.

A side effect of lazy loading is a boot race during integration tests and on the first real play: the first `controls.play()` call invokes `ensureSdk()` but returns early because the `deviceIdRef` is null until the SDK emits `ready`. The consumer must wait for `ready` before calling `play()` again. In integration tests this is handled by the `preWarm()` helper which clicks play, awaits the synthetic `ready` event, then clicks again.

## Decision

`PlaybackProvider` mounts inside the authenticated route layout, not the root. The Spotify Web Playback SDK script is fetched only on the first `controls.play()` call. Public auth pages never instantiate the provider and never request a Spotify token.

## Consequences

- `PlaybackProvider` is always present on authenticated routes — even on pages that have no playback UI (e.g. triage list, admin pages). The provider is low-cost when idle; it only registers a single `player_state_changed` listener and holds refs.
- The SDK boot race means the first `play()` call after page load is always a no-op from the user's perspective (device not yet registered). The provider retries play automatically after `ready`. This adds ~1–2 seconds of latency on the very first play of a session.
- `controls.clearQueue()` and `controls.bindQueue()` are callable from any authenticated route. Route-change handlers in the consumer hooks (curate session, category player queue) call `clearQueue()` on unmount to reset provider state.
- `QueueSource` is a discriminated union (`{ type: 'bucket', ... } | { type: 'category', ... }`). Always narrow on `source.type` before accessing variant-specific fields. The cursor ownership (`currentIndex`) remains in the consumer hook's reducer; `PlaybackProvider` dispatches `JUMP_TO` back to the consumer via an `onCursorChange` callback when auto-advance fires.
- Adding a new playback-enabled route requires calling `controls.bindQueue()` on mount and `controls.clearQueue()` on unmount — the provider does not auto-clear when the consumer unmounts.

**Cross-references:** `../frontend/playback.md`, `../frontend/auth.md`.

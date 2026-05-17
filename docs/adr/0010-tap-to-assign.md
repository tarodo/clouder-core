# ADR-0010: Tap-to-assign curation UX
Status: Accepted
Date: 2026-05-17

## Context

The core curation workflow in CLOUDER is assigning tracks to destination playlists or triage buckets. The design question was what interaction model to use for the assignment gesture.

**Drag-and-drop** is a common pattern in music and playlist management tools. It is expressive (visible drag target, ghost element), but it has significant drawbacks for this use case. First, on mobile it conflicts with scroll; multi-touch disambiguation is unreliable. Second, keyboard-only workflows are impossible — DJs using CLOUDER at a workstation during a session review need to stay on the keyboard. Third, drag targets must be spatially visible simultaneously, constraining the layout.

**Tap-to-assign** (clicking or hotkey-pressing the destination button) was chosen instead. Each destination playlist is a visible button in a fixed panel. Tapping the button assigns the currently-shown track to that destination and advances to the next. The gesture is equivalent to a hotkey press, so keyboard and pointer interactions are naturally unified. The interaction is the same on desktop and mobile — tap a button or press a key.

Hotkeys use physical key position (`event.code`) rather than `event.key` to be layout-safe across Cyrillic, Dvorak, and AZERTY keyboards. Letter keys (Q/W/E for bucket types, digits for playlists) map to their standard QWERTY positions. The `?` key is the single exception because its intent is layout-dependent (shifted character).

The double-tap window (200 ms) allows a user to change their mind within the window and reassign the same track to a different destination. The undo gesture (U key) allows reverting the most recent assignment after the window closes.

## Decision

Curation assigns tracks to destination playlists by tapping (or hotkey-pressing) the playlist's button. Drag-and-drop is not used. Each destination has a hotkey (Q/W/E and digits) plus a click target. The pattern works identically on desktop and mobile.

## Consequences

- Destination buttons must all be visible at the same time. The curate layout reserves a fixed panel for destinations; the number of visible destinations is constrained by screen height.
- The 200 ms double-tap window enables destination change without a separate "undo" step, but it introduces a brief period where the track is not committed. During this window the track is optimistically removed from the queue (shrunk from the cache) but not yet committed to the server if the second tap arrives.
- Undo (`KeyU`) reverts only the most recent assignment (depth-1 stack). Multiple sequential undos are not supported in the current implementation.
- Hotkey conflicts with the playback layer (`KeyJ` = prev, `KeyK` = next in `usePlaybackHotkeys`) are resolved by keeping curate-specific keys (`Q`, `W`, `E`, `digits`) out of `usePlaybackHotkeys` and keeping `J`/`K` out of `useCurateHotkeys`.
- The tap-to-assign pattern was extended to the category player (playlist assignment from category view) using the same mechanics and the same hotkey numbering convention.

**Cross-references:** `../frontend/features.md`, `../frontend/playback.md`.

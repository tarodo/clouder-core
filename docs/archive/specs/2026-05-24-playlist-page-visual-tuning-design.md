# Playlist Page Visual Tuning — Design

**Date:** 2026-05-24
**Scope:** Frontend only — visual tweaks to the playlist detail page (`/playlists/:id`). No backend/API/type changes.

## Goal

Eight visual adjustments the user requested on the playlist detail page, plus making the track-list tags read-only (tags are edited only in the player).

## Design

### A. Cover (`CoverPicker.tsx`)

- The cover avatar itself becomes the click target (wrap it in `FileButton`): clicking an empty **or** filled cover opens the file picker (= replace).
- Remove the "Replace cover" `Button` and the help-text line below.
- Empty cover: render the limits hint **inside** the placeholder — the photo icon + small text `JPEG/PNG · ≤256 KB` + an "upload" hint, all inside the 160px avatar area.
- Filled cover: keep the clear/remove action as a small subtle trash `ActionIcon` over the cover's top-right corner (calls the existing `useClearCover` flow; `e.stopPropagation()` so it doesn't open the picker). The confirm modal stays.
- Show a loading overlay/spinner on the avatar while `useUploadCover` is pending.

### B. Description width (`PlaylistMetaPanel.tsx`)

- The bordered description box currently spans the full content column. Cap it: `maxWidth: 520`.

### C. Publish button (`PublishButton.tsx`) — softer green

- Change the `<Button color="green">` (filled, bright) to a soft treatment matching the tag pills (light fill + border): `variant="light" color="green"` plus a subtle green border (`style={{ borderColor: ... , borderWidth: 1, borderStyle: 'solid' }}` or `variant="light"` + a 1px `var(--mantine-color-green-...)` border). Keep the Spotify icon + loading + behavior.

### D. Add Tracks button (`PlaylistDetailPage.tsx`) — lower brightness

- The Add Tracks `Button` is filled-primary (bright). Change to `variant="light"` (soft fill). Import already uses `variant="default"`; leave it.

### E. Controls placement (`PlaylistDetailPage.tsx`)

- Move the controls (Add Tracks / Import from Spotify / Search) from full-width above the split to **directly above the track list**. On desktop (split layout) that means inside the right column, above the tiles; on mobile, above the list as today. This reverses the full-width placement from PR #136.

### F. Search width (`PlaylistDetailPage.tsx`)

- The search `TextInput` currently has `flex: 1, minWidth: 200` (stretches). Give it a fixed sensible width: `width: 280` (drop the `flex: 1`).

### G. Track meta line (`PlaylistTrackRow.tsx`)

- Replace the separate dimmed `Text` chips on line 2 with a single pipe-separated meta string: `Label | 87 BPM | 3:44 | 2026-05-04`.
  - Build parts: label name (or `—`), `${bpm} BPM` (only when `bpm != null`), `formatLength(length_ms)`, `formatReleaseDate(spotify_release_date)` (only when present). Join the present parts with ` | `.
- Read-only tag pills follow the meta on line 2 (see H).

### H. Track-list tags are read-only

- Tags in the list are display-only — editing happens in the player. Remove the click-to-remove from the tile: render `TagPill` **without** `onRemove`. Drop `onRemoveTag` from `PlaylistTrackRow`, from `PlaylistTracksList`'s props/threading, and from `PlaylistDetailPage` (remove the `onRemoveTag` callback + `usePlaylistRemoveTrackTag` usage there). The **player** (`PlaylistPlayerPanel`) keeps its own tag editing (`usePlaylistAddTrackTag`/`usePlaylistRemoveTrackTag`) — unchanged.

### I. Remove track → pale-red text (`PlaylistTrackRow.tsx`)

- Replace the `<Button color="red" variant="light">` with a plain pale-red text affordance: `Button variant="subtle" color="red" size="xs"` (text-only, low emphasis). Calls the same `onRemove(track)`.

## Testing / verification

- **jsdom:** `PlaylistTrackRow.test.tsx` — meta renders as a single ` | `-joined string containing `BPM`; tags render but are NOT removable (no `Remove <tag>` button); the Remove-track control is present (subtle) and fires `onRemove`. Update/remove the old "click pill to remove" test (behavior intentionally dropped). `CoverPicker` test (create or extend) — clicking the avatar opens the file input; no "Replace cover" button; empty state shows the limits text.
- **Browser smoke:** the existing `PlaylistTrackRow.browser.test.tsx` still passes (tile renders play/number/Remove).
- Gate: `cd frontend && pnpm typecheck && pnpm lint && pnpm test` green; `pnpm test:browser` green locally.

## Out of scope

- Backend / API / `PlaylistTrack` type changes.
- Tag editing in the list (intentionally removed — player only).
- The player panel, the playback queue, drag-and-drop behavior.

## Acceptance criteria

1. Cover: no "Replace cover" button or help-text line; clicking the cover (empty or filled) opens the picker; empty cover shows the limits hint inside; filled cover has a small remove/clear action.
2. Description box is capped (~520px), not full-width.
3. Publish button is soft green (light fill + border), not bright filled.
4. Add Tracks button is soft (`variant="light"`), not bright filled.
5. Add Tracks / Import / Search sit directly above the track list; search has a fixed width (~280px), not stretched.
6. Track line 2 reads like `Label | 87 BPM | 3:44 | 2026-05-04`; list tags are read-only; the Remove-track control is pale-red text.
7. `pnpm typecheck && pnpm lint && pnpm test` and `pnpm test:browser` all green.

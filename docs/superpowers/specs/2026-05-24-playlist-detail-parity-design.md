# Playlist Detail — Categories Parity — Design

**Date:** 2026-05-24
**Scope:** Backend (enrich playlist-tracks payload) + frontend (player panel, rich draggable track tiles, editable tags, drop the `is_public` toggle).

## Goal

Bring the playlist detail page (`/playlists/:id`) to parity with the category detail page:

1. Add a player like categories — a `PlayerCard` "now playing" panel **plus an editable tag cloud** — and a play button before every track.
2. Keep the existing draggable track tiles and their position number.
3. Show the full per-track info from the categories table (artists, label, BPM, length, release date, **tags**) on each tile, with **editable tags**. No filter/sort UI is added.
4. Replace the per-track burger menu ("Remove from Category") with a single light-red **Remove** button.
5. Remove the `is_public` ("public within CLOUDER") toggle from the UI — the platform-sharing idea is dropped; playlists are shared only to Spotify.

This is a multi-part feature (backend + frontend) and will become a multi-task plan. Backend enrichment lands first because the frontend depends on the richer payload.

## Background (verified in the codebase)

- **Playlist tracks are thin today.** `PlaylistsRepository.list_tracks` (`src/collector/curation/playlists_repository.py:536`) selects only `title, spotify_id, isrc, length_ms, origin`. `PlaylistTrack` (frontend `lib/playlistTypes.ts`) mirrors that. There are no artists/label/BPM/release/tags.
- **The enriched track query already exists** for categories in `src/collector/curation/categories_repository.py` (joins `clouder_track_artists`/artists, the label, and the per-user tags overlay; selects `bpm, spotify_release_date, mix_name, is_ai_suspected`). The playlist query mirrors it.
- **Tag mutations are track-scoped, not category-scoped.** The API is `POST /tracks/{trackId}/tags` (`{ tag_id }`) and `DELETE /tracks/{trackId}/tags/{tagId}` (`useAddTrackTag.ts:52`, `useRemoveTrackTag.ts:53`). The `categoryId` carried by `useAddTrackTag`/`useRemoveTrackTag`/`TrackTagsPopover` is used **only** to target the optimistic cache patch + invalidation (`['categories','tracks',categoryId]`). So tag editing works on the playlist page without a category — the mutation just needs to patch the playlist-tracks cache instead.
- **Playback queue source** (`src/features/playback/lib/types.ts:32`) supports only `'bucket'` and `'category'`. A `'playlist'` source must be added. `useCategoryPlayerQueue` (`features/categories/hooks/useCategoryPlayerQueue.ts`) is the binding template.
- **Category player** (`CategoryPlayerPanel.tsx`) = `PlayerCard` + editable tag cloud (`PlayerPanelTagCloud`) + playlist-membership cloud + `LabelTile` + undo + hotkeys, all category-scoped. The chosen playlist player is **`PlayerCard` + editable tags + label tile only** (no playlist-membership cloud).
- **Category track row** (`TrackRow.tsx`, desktop) is the reference for the tile content: play button, title + mix_name, tags cell, artists, label, BPM, length, release date.
- **`is_public`** is a backend field (`db_models`, `curation/schemas`, `playlists_repository`, `playlists_publish_service`) surfaced in the UI by a `Switch` in `PlaylistFormDialog` (create), a `Switch` in `PlaylistMetaPanel` (edit), and a lock/unlock icon in `PlaylistRow`.

## Design

### A. Remove the `is_public` toggle (UI only)

- `PlaylistFormDialog.tsx`: remove the `Switch` (and the `is_public` field from the form values, the `initial`/effect wiring, and the create payload `out.is_public`). The create flow no longer sends `is_public`; the backend default (`false`) applies.
- `PlaylistMetaPanel.tsx`: remove the `is_public` `Switch` and its `onPatch({ is_public })` path.
- `PlaylistRow.tsx`: remove the lock/unlock icon (`IconLock`/`IconLockOpen`).
- Remove the now-unused i18n keys `playlists.form.is_public_label` / `is_public_description`.
- **Backend untouched.** The `is_public` column, schema field, and publish service stay (defaulting `false`). `PlaylistFormValues`/schema keep `is_public` optional so the API contract is unchanged. No DB migration.

### B. Backend — enrich the playlist-tracks payload

- Extend `PlaylistsRepository.list_tracks` to join artists + label and select `bpm, spotify_release_date, mix_name, is_ai_suspected`, plus the per-user tags overlay — mirroring `categories_repository`'s enriched track query. Reuse the same join/aggregation shape (artists ordered, label name, tags as `[{id,name,color}]` for the requesting `user_id`).
- Extend `PlaylistTrackRow` (the repo dataclass) and `_playlist_track_response` (`curation_handler.py:247`) with the new fields.
- Update the OpenAPI schema for the playlist-tracks response (`scripts/generate_openapi.py` / route schema) and regenerate `docs/api/openapi.yaml`, then regenerate the frontend `schema.d.ts`.
- No new endpoint, no pagination/filter/sort changes. `used_in_playlist` is not included (trivially true here).

### C. Frontend types

- Extend `PlaylistTrack` (`lib/playlistTypes.ts`) with `mix_name: string | null`, `artists: {id;name}[]`, `label: {id;name}|null`, `bpm: number|null`, `spotify_release_date: string|null`, `is_ai_suspected: boolean`, `tags: {id;name;color:string|null}[]` — aligned with `CategoryTrack`.
- Regenerate `schema.d.ts` from the updated OpenAPI; the CI diff-check must pass.

### D. Playback wiring

- Add `{ type: 'playlist'; playlistId: string }` to `QueueSource` (`playback/lib/types.ts`). Update any exhaustive `source.type` switches (e.g. hotkey "is this queue active" checks).
- Add `usePlaylistPlayerQueue(playlistId, tracks)` mirroring `useCategoryPlayerQueue`: bind the singleton queue with the `playlist` source, recompute cursor on tracks-identity change, clear on unmount.
- Play buttons on tiles and the player transport drive this queue. `PlaylistDetailPageInner` maps the rich `PlaylistTrack[]` → `PlaybackTrack[]` and binds the queue (mirroring `CategoryDetailPageInner`).

### E. Player panel — `PlaylistPlayerPanel`

- New component mirroring `CategoryPlayerPanel`, scoped to **PlayerCard + editable tags + label tile**:
  - `PlayerCard` (variant `full`): now playing (cover, title, mix_name), transport (play/pause/prev/next), seek, label/BPM meta row, Spotify link — sourced from the currently-playing rich `PlaylistTrack`.
  - Editable tag cloud (reuse `PlayerPanelTagCloud`, see §G) wired to playlist-scoped tag mutations; undo toast on add/remove (match categories).
  - `LabelTile` when the playing track has a label.
  - Playback transport hotkeys active when `playback.queue.source?.type === 'playlist'` && matches this playlist (reuse the playback-hotkey hook, **without** the playlist-toggle bindings).
  - No playlist-membership cloud.
- Empty state ("pick a track") like the category panel.

### F. Track tiles — `PlaylistTrackRow` redesign

- **Keep:** the draggable tile container (bg-elevated + border), the `dnd-kit` drag handle, and the position number.
- **Add:**
  - A play button before the title (reuse the categories pattern: `ActionIcon` + `IconPlayerPlayFilled`, disabled with a tooltip when `spotify_id` is null), wired to play this track in the playlist queue.
  - Title + `mix_name`, artists, label, BPM, length, release date — the categories desktop-row fields, laid out to fit the tile.
  - **Editable tags:** tag pills (soft style, with `×` to remove) + a `+` popover to add/create (reuse the decoupled tag editor from §G).
  - "current" highlight when this tile's track is playing.
- **Replace:** `PlaylistTrackRowActions` (burger `Menu`) with a single light-red **Remove** button (`Button color="red" variant="light"` or equivalent light-red), calling the existing `onRemove`.

### G. Decouple tag editing from the categories cache

- Lift the tag mutations out of `TrackTagsPopover` (and the cloud): the editor becomes presentational — props `currentTagIds`, `availableTags`, `onToggle(tag, checked)` (and create-tag callback), with **no `categoryId`**. `PlayerPanelTagCloud` already exposes `onAdd`/`onRemove`; `TrackTagsPopover` is changed to call an injected `onToggle` instead of doing its own category-scoped mutation.
- Categories pages wire these callbacks to the existing `useAddTrackTag`/`useRemoveTrackTag` (categories-cache optimistic patch) — behavior unchanged.
- New playlist tag hooks (`usePlaylistTrackTag` add/remove, or one toggle hook) hit the same `/tracks/{id}/tags` endpoints and optimistically patch the `playlistTracksKey(playlistId)` cache, with rollback on error.
- Tests keep the categories tag flows green after the refactor.

### H. Page composition (unchanged controls)

- `PlaylistDetailPage` keeps Add tracks / Import from Spotify / Publish / Delete / the client-side title search. No sort/filter UI is added.
- Desktop: split layout — `PlaylistPlayerPanel` left, the draggable tiles list right (mirror `CategoryDetailPage`'s `Flex`). Mobile: tap a track → `/playlists/:id/player` route rendering the panel (mirror the categories mobile player route; parent stays mounted so queue + list survive).
- Reorder stays disabled while searching (already the case).

## Testing / verification

- **Backend:** `PlaylistsRepository.list_tracks` returns artists/label/BPM/release/mix/tags in position order, scoped to the owner and the requesting user's tags; handler/response shape matches the OpenAPI schema. Reuse the categories repo test patterns.
- **Frontend (jsdom):** `PlaylistTrackRow` renders the play button (disabled w/o `spotify_id`), number, title/mix, artists/label/BPM/length/release, tag pills, and the Remove button; Remove fires `onRemove`; tag add/remove patches the playlist cache optimistically and rolls back on error. `PlaylistPlayerPanel` renders the PlayerCard + tag cloud and an empty state. Categories tag flows still pass after the §G refactor.
- **Frontend (browser harness, `*.browser.test.tsx`):** a light smoke that a tile shows play + number + Remove and the desktop split mounts (geometry is not load-bearing here, unlike the focus-ring case — keep it minimal).
- Gate: backend `pytest -q`; frontend `pnpm typecheck && pnpm lint && pnpm test`; `pnpm test:browser` locally; OpenAPI regenerated and `schema.d.ts` in sync (CI diff-check green).

## Out of scope

- Removing `is_public` from the backend/DB (UI-only this round).
- Filters/sorting on the playlist page.
- Playlist-membership editing from the playlist player (no playlist-cloud).
- `used_in_playlist` badge on playlist tiles.
- Hotkey-based tag/playlist assignment in the playlist player (transport hotkeys only).

## Acceptance criteria

1. The playlist create form, meta panel, and list row no longer show any `is_public` toggle/icon; creating a playlist still works (backend defaults `false`).
2. The playlist-tracks API returns artists, label, BPM, release date, mix_name, and the user's tags per track.
3. The playlist detail page shows a categories-style player (PlayerCard + editable tags + label tile), desktop split / mobile player route, with a working play button before each track.
4. Each track tile keeps its draggable handle + number and shows the full categories-table info with **editable** tags; the burger menu is replaced by a light-red **Remove** button.
5. Editing tags on the playlist page updates the same per-user track tags (no category needed) and reflects optimistically; categories tag editing is unchanged.
6. Backend `pytest`, frontend `pnpm typecheck && pnpm lint && pnpm test`, and `pnpm test:browser` all green; OpenAPI + `schema.d.ts` in sync.

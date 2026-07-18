# Spotify import: artist fix + whole-playlist mirror — design

**Date:** 2026-07-17
**Status:** Approved design, ready for implementation plan
**Area:** `src/collector/curation/` (Spotify import), `vendor_match` (YT Music), `frontend/src/features/playlists/`

## Problem

Two intertwined asks, both on the Spotify → clouder import path:

1. **YouTube link search does not work for Spotify-imported tracks.** Reported as "the search didn't run". Observed behaviour: an imported Spotify track never gets a YouTube (YT Music) link — not on the track, not even as a review candidate.
2. **No way to import a whole Spotify playlist.** Only single tracks can be imported today (paste up to 50 refs).

### Root cause of #1 (confirmed by code read)

The YT Music search *is* enqueued on Spotify import — `_enqueue_ytmusic(...)` at `curation_handler.py:1154` — but it silently drops the imported tracks:

1. `upsert_imported_track` (`curation/playlists_repository.py:846`) inserts a `clouder_tracks` row (title/isrc/length/spotify_id/origin) but **does not persist the track's artists**, even though the Spotify `get_track` payload already carries them (`curation/spotify_user_client.py:73-80`). No rows land in `clouder_track_artists`.
2. `fetch_unmatched_match_inputs` (`curation/playlists_repository.py:914`) derives the artist via `STRING_AGG` over `clouder_track_artists` → for an imported track this is the **empty string**.
3. `enqueue_vendor_matches` (`vendor_match/enqueue.py:41-57`) builds `VendorMatchMessage(artist="")`; the `_strip_non_empty` validator (`schemas.py:96`) **raises on empty artist** → the track is dropped with `vendor_match_enqueue_invalid` and never reaches SQS.
4. Net effect: the YT Music worker never runs for that track → no link, no review candidate.

Library tracks (Beatport-triaged) carry artists, so their YT Music search works — only the Spotify import path is broken.

**The user's belief that "we moved the YouTube search to category-add" is not in the code.** `_enqueue_ytmusic` is called at exactly two sites — `curation_handler.py:946` (add tracks to playlist) and `:1154` (Spotify import) — and never on category-add (`_handle_add_track`, `:727`). No relocation happened; the search was always on the playlist/import side and is simply being starved of artist data.

## Goals

- **A (fix):** Spotify-imported tracks reliably get a YouTube link (i.e. the YT Music vendor-match runs for them).
- **B (feature):** Import an entire Spotify playlist as a **new** clouder playlist that mirrors the Spotify playlist name.
- Reuse the existing import pipeline; A is the foundation that makes YouTube links work for both single-import and playlist-import.

## Non-goals (explicitly out of scope this pass)

- **Label metadata from Spotify.** Deferred. Rationale: unlike artists (inline in the track payload, free to persist), `label` is **not** in the Spotify track object — it lives only on the full album object (`GET /albums/{id}`), and in clouder it attaches via `clouder_tracks.album_id → clouder_albums.label_id`. That means an extra Spotify call + an album-row write + (for playlists) an async worker — disproportionate cost for a bonus field. Tracked as a follow-up.
- Importing into an existing playlist, or a "new-or-existing" chooser. Decision: always a **new mirror playlist**.
- Async/background import for very large playlists. Decision: **synchronous with a ~200-track cap**.
- Audio features, Spotify genres, cover art mirroring.

## Design

### Part A — Persist artists on import (the fix)

The Spotify `get_track` payload already exposes `artists[]` (name + spotify_id). Thread it into the write path and persist it.

- Extend the import write path to accept `artists: list[str]` (names, in order) and, **only when inserting a new `clouder_tracks` row**, persist them:
  - For each name: `normalize_text(name)` → `SELECT id FROM clouder_artists WHERE normalized_name = :n` → reuse, else `INSERT` a fresh `clouder_artists` row (uuid, name, normalized_name, timestamps).
  - `INSERT INTO clouder_track_artists (track_id, artist_id, role) VALUES (..., 'main') ON CONFLICT DO NOTHING`.
  - Pattern mirrors `artist_enrichment/repository.py:112-135`.
- **Do not rewrite artists for an existing track** (spotify_id dedup hit). Reused tracks (Beatport-origin, or already-imported) already carry artists; touching them is needless and risks clobbering enrichment.
- `clouder_artists` has **no `spotify_id` column** — dedup is by `normalized_name` (matches existing ingest/enrichment behaviour).

**Result:** `fetch_unmatched_match_inputs` returns a non-empty `artist` → `VendorMatchMessage` validates → the message reaches SQS → the YT Music worker runs (match, or review candidate). Zero changes to the vendor-match subsystem itself.

### Part B — Import a whole Spotify playlist (new mirror playlist)

**B1 — Spotify client (`SpotifyUserClient`).**
- `get_playlist(id)` — fetch playlist name (`GET /playlists/{id}?fields=name`) for the mirror playlist title.
- `get_playlist_tracks(id)` — paginate `GET /playlists/{id}/tracks?limit=100&offset=…` following the `next` cursor until exhausted or the cap is reached. Each item wraps a `track` object of the same shape as `get_track`; reuse the id/name/duration/isrc/artists extraction. **Skip** items where `track is null` (removed/unavailable), `is_local` is true (local files, no id), or `track.type == 'episode'` (podcasts). Count skips.

**B2 — Playlist-ref parser.**
- `parse_spotify_playlist_ref` (analogous to `parse_spotify_ref` in `curation/playlists_service.py`): accepts `spotify:playlist:<id>`, `https://open.spotify.com/playlist/<id>`, or a bare 22-char base62 id. Rejects anything else.

**B3 — Batched write path (timeout safety).**
- Looping 200 single-track `upsert_imported_track` transactions will not fit the 29 s API Gateway budget (~5 Data-API round-trips × 200). Add `import_tracks_batch(user_id, tracks, now) -> list[str]` (ordered `clouder_tracks.id`s) that does the whole import in **one transaction** with batched statements via `batch_execute`:
  - bulk `SELECT` existing `spotify_id`s (dedup),
  - bulk `INSERT` new `clouder_tracks`,
  - bulk upsert `clouder_artists` + bulk link `clouder_track_artists` (Part A logic, batched),
  - bulk `INSERT` `user_imported_tracks`.
- **Refactor single-import (`_handle_import_spotify`) onto `import_tracks_batch` (batch-of-1)** so there is exactly one artist-writing code path.

**B4 — Route + handler.**
- `POST /playlists/import-spotify-playlist` (note: **not** under `/playlists/{id}` — it creates a new playlist).
- Request: `ImportSpotifyPlaylistIn = { spotify_playlist_ref: str, name: str | None }` (optional name override; default = Spotify playlist name).
- Handler `_handle_import_spotify_playlist`:
  1. `parse_spotify_playlist_ref` → playlist id.
  2. `_build_spotify_user_client(user_id, correlation_id)`.
  3. `get_playlist(id)` (name) + `get_playlist_tracks(id)` capped at `MAX_IMPORT_PLAYLIST_TRACKS = 200`.
  4. `repo.create_playlist(user_id, name=...)` → new playlist id.
  5. `import_tracks_batch(...)` → track ids.
  6. `repo.append_tracks(user_id, new_playlist_id, track_ids, now)`.
  7. `_enqueue_ytmusic(repo, added_track_ids, correlation_id)`.
  8. Response: `{ playlist_id, name, imported, skipped, truncated, total }`.
- **Route registration is three places** (per project gotcha): `_ROUTE_TABLE` in `curation_handler.py`, `scripts/generate_openapi.py:ROUTES`, and `infra/curation_routes_playlists.tf`. Missing the gateway one → `{"message":"Not Found"}`.

**Cap behaviour:** if the Spotify playlist has more than 200 usable tracks, import the first 200 and return `truncated: true` with `total` = full count.

### OAuth scopes

- Add `playlist-read-private` and `playlist-read-collaborative` to `SPOTIFY_SCOPES` (`auth_handler.py:59`). Reading a **public** playlist works with any valid token; private/collaborative playlists require these scopes.
- Scope changes require **re-consent** (fresh `/auth/login`), not just a token refresh. Existing users must reconnect Spotify once.
- If the resolved token lacks the scope, Spotify returns 403 → the existing `SpotifyScopeInsufficientError` path surfaces a clear "reconnect Spotify" error to the client.

### Frontend

- New entry point at the **playlists-list level** (a new playlist is created): a "Import playlist from Spotify" action opening `ImportSpotifyPlaylistModal`.
  - Model on the existing `frontend/src/features/playlists/components/ImportSpotifyModal.tsx` + `hooks/useImportSpotifyTracks.ts`.
  - Fields: Spotify playlist URL (client-side validated via a playlist-ref parser mirroring `lib/spotifyRefParse`), optional name override.
  - On success: navigate to the new playlist detail page + toast "Imported N (skipped M, truncated to 200)".
  - Error states: invalid URL (client parse), Spotify not connected / scope insufficient (prompt reconnect), playlist not found / private-inaccessible.
- The existing single-track import modal is unchanged; it now benefits from Part A (working artists → working YouTube links).
- Regenerate `frontend/src/api/schema.d.ts` from the updated OpenAPI (CI diff-checks it).

### Backfill (existing broken imports)

Tracks imported before this fix have no artists and therefore no YouTube link. One-off script (precedent: the Instagram backfill, PR #221):

- `scripts/backfill_spotify_import_artists.py`:
  1. Find `clouder_tracks WHERE origin = 'spotify_user_import'` with no `clouder_track_artists` rows and a non-null `spotify_id`.
  2. Batch-fetch artists via `GET /v1/tracks?ids=` (up to 50 ids/call, **client-credentials** app token — track catalog data is public). Requires adding a small `get_tracks(ids)` batch method to the ingest-side `SpotifyClient` (it currently only does ISRC search).
  3. Upsert artists (Part A logic) + link `clouder_track_artists`.
  4. Re-enqueue YT Music via `enqueue_vendor_matches` for the healed track ids.
- Run with `PYTHONPATH=src` and the appropriate Data-API / SQS / Spotify-secret env, guarded by a `--dry-run` default.

## Testing

- **Regression (proves the fix):** after import, `fetch_unmatched_match_inputs` returns a non-empty `artist` and `enqueue_vendor_matches` sends a message for the imported track (previously dropped as `vendor_match_enqueue_invalid`).
- Unit: artist persistence + dedup by `normalized_name`; reuse of an existing artist; artists written only on new-track insert (not on spotify_id dedup hit).
- Unit: `parse_spotify_playlist_ref` (uri / url / bare id accepted; garbage rejected).
- Unit: `get_playlist_tracks` pagination, skip null/local/episode, cap at 200 (mock Spotify responses).
- Unit: `import_tracks_batch` — dedup, ordered ids, single-transaction semantics.
- Integration: `POST /playlists/import-spotify-playlist` creates a playlist, imports tracks, enqueues YT Music (mock SQS), returns `{imported, skipped, truncated, total}`; 403 scope-insufficient path returns a reconnect error.
- Frontend: modal validation + success navigation + error states (jsdom; modal is simple, no browser test needed).
- Regenerate and diff-check OpenAPI (`scripts/generate_openapi.py`) and `frontend/src/api/schema.d.ts`.

## Edge cases

- Playlist items that are null / local / episodes → skipped and counted.
- `spotify_id` dedup hit (track already in `clouder_tracks` from Beatport ingest or a prior import) → reuse the row; do not rewrite artists. Note: a track imported *before* this fix that is reused here stays artist-less — that is what the backfill script addresses.
- Rate limits: a 200-track playlist is 2 pages; `SpotifyUserClient._request` already retries 429 once (respecting `Retry-After`).
- Timeout: batched writes + cap 200 + ≤2 Spotify pages should fit the 29 s budget — flagged as a risk to validate during implementation (measure a full 200-track import).
- Empty-artist track even from Spotify (rare) → the enqueue still drops it safely (no regression).

## Key files

- `src/collector/curation/spotify_user_client.py` — add `get_playlist`, `get_playlist_tracks`.
- `src/collector/curation/playlists_service.py` — add `parse_spotify_playlist_ref`, `MAX_IMPORT_PLAYLIST_TRACKS`.
- `src/collector/curation/playlists_repository.py` — extend/refactor to `import_tracks_batch` (artist persistence), reuse in `upsert_imported_track` path.
- `src/collector/curation/schemas.py` — `ImportSpotifyPlaylistIn`.
- `src/collector/curation_handler.py` — `_handle_import_spotify_playlist`, route table, thread `artists` into single-import.
- `src/collector/auth_handler.py` — add read scopes to `SPOTIFY_SCOPES`.
- `src/collector/spotify_client.py` — add `get_tracks(ids)` batch (for the backfill script).
- `scripts/generate_openapi.py`, `infra/curation_routes_playlists.tf` — register the new route.
- `scripts/backfill_spotify_import_artists.py` — one-off backfill.
- `frontend/src/features/playlists/` — `ImportSpotifyPlaylistModal`, hook, types, list-level entry point; regenerated `schema.d.ts`.

# ADR-0021: Spotify playlist import as a synchronous mirror playlist
Status: Accepted
Date: 2026-07-18

## Context

Users could import Spotify tracks only one reference at a time (paste up to 50 refs into an open playlist). Importing a whole playlist meant pasting every track by hand.

Two constraints shaped the design:

- **Imported tracks were silently unmatchable.** Import persisted the track row (title, ISRC, duration, `spotify_id`) but discarded the artists Spotify returns. The vendor-match producer drops any message with an empty `artist` (ADR-0019's pipeline), so no imported track ever got a YouTube Music match — not even a review-queue candidate. Any import feature had to fix artist persistence first.
- **The write path is the cost.** The curation Lambda sits behind API Gateway's 29-second hard timeout, and Aurora is reached through the RDS Data API (ADR-0001), where every statement is a network round-trip. A per-track transaction (~5 round-trips) does not survive 200 tracks.

Spotify's shape mattered too: playlist items page 100 at a time, items can be `null` / local / podcast episodes, and the track object does **not** carry `label` — that lives only on the full album object.

Alternatives considered:

1. **Asynchronous import job** — SQS worker, job-status table, frontend polling. Handles playlists of any size, but adds a queue, a worker, a status surface, and polling UI for an action performed a handful of times a week.
2. **Import into the currently open playlist** rather than creating one — reuses the existing modal, but "add a whole playlist" then silently merges two track sets.
3. **Capture label during import** — an extra `GET /albums` call per unique album plus an album row, since label attaches via `clouder_tracks.album_id → clouder_albums.label_id`.

## Decision

- Import creates a **new clouder playlist mirroring the Spotify playlist's name**, via `POST /playlists/import-spotify-playlist`. It never appends to an existing playlist; the name can be overridden in the request.
- **Synchronous**, capped at `MAX_IMPORT_PLAYLIST_TRACKS = 200`. The response reports `truncated` when the source playlist is larger. Rejected alternative 1 — no new infrastructure.
- A single batched write path, `import_tracks_batch`, serves **both** single-track and whole-playlist import: one Data API transaction using `batch_execute`, which also persists artists (`clouder_artists` + `clouder_track_artists`, deduped by `normalized_name`) for newly inserted tracks. One code path, so artist persistence cannot regress on one of them.
- OAuth scopes widened with `playlist-read-private` and `playlist-read-collaborative` so a user can import their own non-public playlists.
- **Label is not captured at import** (alternative 3 deferred).

## Consequences

- Playlists longer than 200 tracks import their first 200; the client is told via `truncated`. Raising the cap means re-testing against the 29 s budget, or revisiting alternative 1.
- **Widening scopes forces one-time re-consent.** A refresh does not widen an existing token — every already-connected user must re-run `/auth/login`, and until they do, importing a private playlist returns 412 `spotify_scope_insufficient`. See [../api/auth-flow.md](../api/auth-flow.md).
- Batched writes trade per-track isolation for speed: one bad row rolls back the whole import. Because the playlist row is created before the import (separate Data API call), the handler soft-deletes the just-created playlist when the import fails, so a retry is not blocked by a name conflict.
- `append_tracks` must dedup its input. A Spotify playlist may legitimately list the same track twice, which would otherwise violate the `playlist_tracks` PK `(playlist_id, track_id)` and fail the request.
- Imported tracks still carry no label. Adding it later means an extra batched `GET /albums` call and writing `clouder_albums` — a self-contained follow-up, not a redesign.
- Tracks imported before this change stay artist-less until healed; `scripts/backfill_spotify_import_artists.py` does that and re-enqueues their matches.

Cross-references: [ADR-0019](0019-youtube-music-vendor.md) (vendor match pipeline), [ADR-0001](0001-data-api-runtime.md) (Data API at runtime), [../backend/gotchas.md](../backend/gotchas.md#empty-artist-silently-skips-vendor-match) (empty artist skips vendor match), [../api/auth-flow.md](../api/auth-flow.md) (scopes and re-consent).

# YouTube Music publish — design

**Date:** 2026-05-31
**Status:** Approved (design), pending implementation plan
**Author:** brainstorming session

## Goal

From the playlist page, a user can publish a playlist to **YouTube Music under their
own account**, with the same experience as the existing Spotify publish: first
publish, republish-with-overwrite, and a result modal listing skipped tracks.

## Decisions (locked)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Integration API | **ytmusicapi (authenticated)** — reuses the already-installed library, creates a real YouTube Music playlist. Unofficial internal API; ToS grey area; accepted. |
| 2 | v1 scope | **Full parity with Spotify** — connect + first publish + republish (`confirm_overwrite`) + skipped-tracks modal. |
| 3 | Connect UX | **Inline on the publish button** — clicking publish while not connected opens a device-code connect modal, then publishes. |
| 4 | OAuth flow | **Device-flow** (Google "TVs and Limited Input devices"), the only flow ytmusicapi supports. |
| 5 | Republish strategy | **Edit-in-place** (stable playlist URL): `edit_playlist` meta → `get_playlist` → `remove_playlist_items` → `add_playlist_items`. |
| 6 | Publish execution | **Synchronous** in the curation Lambda (mirrors Spotify). May move to an SQS worker later if large playlists approach the API Gateway 29 s limit. |
| 7 | Publish-state storage | **Mirrored columns** on `playlists` (`ytmusic_*`), not a normalized `playlist_publications` table. Pragmatic for two vendors, matches existing style. |
| 8 | `device_code` custody | **Client-held** between `device-code` and `poll` (backend stateless), like the Spotify PKCE verifier. Short-lived, HTTPS-only. |
| 9 | Playlist privacy | **Parity with Spotify**: `'PUBLIC' if playlist.is_public else 'PRIVATE'`. |
| 10 | Cover image | **Skipped** — YouTube Music has no custom-cover API. `cover_failed` is always `false`. |

## Architecture principle

Mirror the Spotify publish path almost one-to-one with **separate** YouTube Music
classes. We do **not** refactor the working Spotify path into a shared base — lower
risk. A shared base can be extracted later if a third vendor appears.

The matching layer already exists: matched YouTube Music `video_id`s live in
`vendor_track_map` (vendor=`ytmusic`), surfaced by
`playlists_repository.fetch_ytmusic_status(track_ids)`. The publish path **reuses**
this; no new matching work.

## Prerequisite (ops, one-time)

Create a Google Cloud OAuth client of type **"TVs and Limited Input devices"**.
Store `client_id` / `client_secret` in Secrets Manager / SSM as an **app-level**
secret (one for all users). Per-user we persist only the refresh token (encrypted).

The Google OAuth app stays in **"testing" mode** (≤100 test users) to avoid Google's
verification process — fits the small DJ-circle audience. Each user who connects must
be added as a test user, or the consent screen is published for the limited scope.

## Component 1 — OAuth (connect a YouTube Music account)

YouTube Music is a **secondary** linked account. (Spotify OAuth is the app login;
YouTube is not.) This is a net-new connect flow.

### Backend (in `auth_handler`, JWT-gated — these require an authenticated user)

- `POST /auth/ytmusic/device-code`
  → `OAuthCredentials(client_id, client_secret).get_code()`
  → returns `{ user_code, verification_url, interval, expires_in, device_code }`.
- `POST /auth/ytmusic/poll` (body `{ device_code }`)
  → `OAuthCredentials.token_from_code(device_code)`.
  - Still pending → HTTP **202** `{ status: "authorization_pending" }` (also handle
    `slow_down`, `access_denied`, `expired_token`).
  - Success → KMS-envelope-encrypt access + refresh tokens (reuse `KmsEnvelope`),
    upsert into `user_vendor_tokens` (vendor=`ytmusic`) via the existing
    `auth_repository.upsert_vendor_token`, return HTTP **200** `{ connected: true }`.
- `DELETE /auth/ytmusic` — disconnect (delete the `ytmusic` token row). For parity.
- `GET /me` — add `ytmusic_connected: bool` so the frontend knows the button state.

`device_code` is returned to the client and posted back on poll; the backend stores
nothing between the two calls.

### `YtmusicTokenResolver` (`curation/ytmusic_token_resolver.py`)

Mirror of `SpotifyTokenResolver`:
- Read the `ytmusic` row from `user_vendor_tokens`; decrypt.
- If within the refresh leeway of `expires_at`, refresh via
  `OAuthCredentials.refresh_token(refresh_token)` (Google may **not** return a new
  refresh token — keep the existing one), re-encrypt, update the row.
- Return a resolved access token used to construct the authenticated client:
  `YTMusic(auth=<token dict>, oauth_credentials=OAuthCredentials(client_id, client_secret))`.
- Raise `YtmusicNotAuthorizedError` when no token is on file or refresh fails.

## Component 2 — Backend publish

### Route

`POST /playlists/{id}/publish-ytmusic` — **synchronous**, in the curation Lambda.

Register in **all three places** (route-registration rule):
1. `curation_handler._ROUTE_TABLE`
2. `scripts/generate_openapi.py:ROUTES`
3. `infra/curation_routes_playlists.tf`

Body: `{ confirm_overwrite: bool }`. Mirrors `POST /playlists/{id}/publish`.

### `YtmusicUserClient` (`curation/ytmusic_user_client.py`)

Thin wrapper over an authenticated `ytmusicapi.YTMusic`. The **single point of impact**
if Google changes the internal API.

- `create_playlist(name, description, privacy) -> YtmusicPlaylistRef(id, url)`
  → `YTMusic.create_playlist(title, description, privacy_status)`.
- `add_items(playlist_id, video_ids)` → `YTMusic.add_playlist_items(playlist_id,
  video_ids, batchSize=100)` (chunk by 100, matching Spotify).
- `get_items(playlist_id) -> list[track dicts with videoId + setVideoId]`
  → `YTMusic.get_playlist(playlist_id, limit=...)`.
- `remove_all_items(playlist_id, items)` → `YTMusic.remove_playlist_items(playlist_id,
  items)` (items must carry `setVideoId` from `get_items`).
- `edit_meta(playlist_id, name, description, privacy)`
  → `YTMusic.edit_playlist(playlist_id, title, description, privacyStatus)`.
- `delete(playlist_id)` → `YTMusic.delete_playlist(playlist_id)` (used only for
  orphan recovery if needed).

Error mapping: not-authorized → `YtmusicNotAuthorizedError`; missing playlist →
`YtmusicNotFoundError`; everything else → `YtmusicApiError`.

The YouTube Music playlist URL is `https://music.youtube.com/playlist?list={id}`.

### `YtmusicPublishService` (`curation/ytmusic_publish_service.py`)

Mirror of `PlaylistsPublishService`:

1. `repo.get(user_id, playlist_id)`; `PlaylistNotFoundError` if missing.
2. If `playlist.ytmusic_playlist_id` and not `confirm_overwrite` →
   `ConfirmOverwriteRequiredError`.
3. `repo.list_tracks(...)` → track ids. `repo.fetch_ytmusic_status(track_ids)` →
   for each track with `status == "matched"`, take its `video_id`.
   - `skipped = [{track_id, title, reason: "no_ytmusic_match"} for tracks without a
     matched video_id]`.
   - No video ids at all → `NothingToPublishError`.
4. `privacy = "PUBLIC" if playlist.is_public else "PRIVATE"`.
5. Publish:
   - `target_id = playlist.ytmusic_playlist_id`.
   - If `target_id`: `edit_meta` → on not-found (orphan, playlist deleted on YT)
     fall through to create (mirrors Spotify's `treat_404_as_orphan`); else
     `get_items` → `remove_all_items` → `add_items`.
   - If no `target_id`: `create_playlist` → `add_items`. Capture `ytmusic_url`.
6. Cover: skipped (no API). `cover_failed = False`.
7. `repo.set_ytmusic_publish_state(user_id, playlist_id, ytmusic_playlist_id=target_id,
   now)`.
8. Return `YtmusicPublishResult(ytmusic_playlist_id, ytmusic_url, skipped,
   published_at)`.

Emit the same structured log events as the Spotify path (`*_started`,
`*_succeeded`, `*_partial_fail` / orphan-recreated), namespaced for ytmusic.

## Component 3 — Database

Migration on `playlists`:
- `ytmusic_playlist_id TEXT NULL`
- `ytmusic_last_published_at TIMESTAMPTZ NULL`
- `ytmusic_needs_republish BOOLEAN NOT NULL DEFAULT FALSE`
- index `idx_playlists_ytmusic_playlist_id` on `ytmusic_playlist_id`

Repository:
- `set_ytmusic_publish_state(...)` — mirror of `set_publish_state`.
- Include the three new columns in the `get` and list projections so the frontend
  receives them.

## Component 4 — Frontend

- `usePublishYtmusic` hook → `POST /playlists/{id}/publish-ytmusic`, body
  `{ confirm_overwrite }`; on success invalidate playlist detail + list queries.
- **"Publish to YT Music"** button beside the Spotify button on the playlist page
  (mirror `PublishButton.tsx`).
- **Connect inline:** on click, if `!ytmusic_connected` (from `GET /me`) or the
  publish returns `412 ytmusic_not_connected`, open `YtMusicConnectModal`:
  - `useYtmusicDeviceCode` → shows `user_code` + a link to `verification_url`
    ("open and enter this code").
  - `useYtmusicPoll` polls `POST /auth/ytmusic/poll` at `interval`; on `200` close
    the modal and proceed to publish.
- Generalize `PublishResultModal` to take a vendor label + URL + skipped list (reuse
  for both Spotify and YouTube Music).
- Error mapping: `412` → connect modal; `400 confirm_overwrite_required` → overwrite
  confirmation (same as Spotify); `502 ytmusic_upstream` → error toast.
- Extend the `Playlist` type with `ytmusic_playlist_id`,
  `ytmusic_last_published_at`, `ytmusic_needs_republish`. Regenerate
  `frontend/src/api/schema.d.ts` from the OpenAPI spec (CI diff-gate).

## API surface summary

| Method | Path | Auth | Handler | Purpose |
|--------|------|------|---------|---------|
| POST | `/auth/ytmusic/device-code` | JWT | auth | start device-flow, return user code |
| POST | `/auth/ytmusic/poll` | JWT | auth | exchange device code for tokens |
| DELETE | `/auth/ytmusic` | JWT | auth | disconnect |
| GET | `/me` (extended) | JWT | auth | add `ytmusic_connected` |
| POST | `/playlists/{id}/publish-ytmusic` | JWT | curation | publish playlist |

## Error model (HTTP)

- `400 confirm_overwrite_required` — already published, `confirm_overwrite` false.
- `409 nothing_to_publish` — no matched YouTube Music tracks.
- `412 ytmusic_not_connected` — no `ytmusic` token on file.
- `502 ytmusic_upstream` — ytmusicapi / YouTube error.

(Match the existing Spotify handler's status codes where they overlap.)

## Testing strategy

- **Unit:** `YtmusicPublishService` with a fake `YtmusicUserClient` + fake repo —
  cover first-publish, republish-overwrite, orphan-recreate, skipped tracks,
  nothing-to-publish, confirm-overwrite-required. `YtmusicTokenResolver` refresh /
  no-refresh / refresh-failure paths.
- **Unit:** device-code + poll handlers — pending (202), success (200), denied,
  expired. Token encryption round-trip.
- **Unit:** `YtmusicUserClient` error mapping with a fake `YTMusic`.
- **Frontend (jsdom):** hook + button states (connect-needed, publishing, overwrite,
  result). **Browser test** for the connect modal + result modal layout
  (`pnpm test:browser`) per the CLAUDE.md visual-verification rule.
- **OpenAPI:** regenerate and confirm `schema.d.ts` is in sync.

## Risks (accepted)

1. **Unofficial API fragility** — Google may change YouTube Music's internal API.
   Mitigation: isolate all calls in `YtmusicUserClient`.
2. **Sync-publish latency** — very large playlists (500+) make a get→remove→add
   chain that could approach the API Gateway 29 s limit. Acceptable for the
   small-circle audience and typical sizes; move to an SQS worker if it bites.
3. **Lambda package size** — adds `ytmusicapi` to the curation Lambda (currently only
   in the vendor_match worker). Acceptable.
4. **OAuth testing-mode cap** — ≤100 connected users without Google verification.
   Fits the audience.

## Out of scope (v1)

- Custom playlist cover for YouTube Music (no API).
- Async/worker-based publish (revisit only if latency bites).
- A dedicated account/settings page (connect stays inline).
- Normalized multi-vendor publish-state table (revisit at a third vendor).

# Playlists (Backend) — Design

**Date**: 2026-05-11
**Scope**: Backend (Python Lambda + Aurora + S3 + Spotify Web API)
**Frontend**: Out of scope — a separate spec will cover UI once backend ships.

## Summary

Add user-owned playlists to CLOUDER. A user can:

- Create / read / update / soft-delete playlists (name, description, public flag, cover).
- Add tracks from any of their own categories (tracks may span styles).
- Import individual tracks from Spotify by link or ID, creating thin canonical rows when needed.
- Upload a cover image (JPEG ≤ 256 KB) via presigned S3 PUT.
- Publish a playlist to Spotify. First publish creates a new Spotify playlist; subsequent publishes are a full overwrite gated by an explicit `confirm_overwrite=true`.

Playlists live in the existing curation Lambda alongside categories / triage / tags. No new Lambda, no new infra service.

## Architecture

```
HTTP (API GW v2)
  ↓
curation Lambda  (handler routes /playlists/*)
  ├── playlists_service.py   — limits, normalization, orchestration
  ├── playlists_repository.py — Aurora Data API (user_id scoped)
  ├── spotify_user_client.py  — OAuth-token Spotify Web API client
  ├── storage.py              — presigned cover URLs + S3 read for publish
  └── secrets_envelope.py     — KMS-decrypt Spotify access token (shared)
  ↓                      ↓                       ↓
Aurora              S3 (covers/*)        Spotify Web API
```

Tenancy: every repository method takes `user_id` and includes it in WHERE. Cross-user access yields zero rows → mapped to 404 by handler (same pattern as `categories_repository.py`).

## Data Model

### Migration 19 — `20260512_19_playlists.py`

#### Alter `clouder_tracks`

```sql
ALTER TABLE clouder_tracks
  ADD COLUMN origin TEXT NOT NULL DEFAULT 'beatport'
  CHECK (origin IN ('beatport', 'spotify_user_import'));

-- Replace partial non-unique idx with partial UNIQUE for ON CONFLICT idempotency
DROP INDEX idx_tracks_spotify_id;
CREATE UNIQUE INDEX uq_tracks_spotify_id
  ON clouder_tracks(spotify_id)
  WHERE spotify_id IS NOT NULL;
```

Existing rows keep `origin='beatport'`. Beatport ingest continues writing `'beatport'`.

#### New table `playlists`

```sql
CREATE TABLE playlists (
  id                  UUID PRIMARY KEY,
  user_id             UUID NOT NULL REFERENCES users(id),
  name                TEXT NOT NULL,
  normalized_name     TEXT NOT NULL,
  description         TEXT,
  is_public           BOOLEAN NOT NULL DEFAULT FALSE,
  cover_s3_key        TEXT,
  cover_uploaded_at   TIMESTAMPTZ,
  spotify_playlist_id TEXT,
  last_published_at   TIMESTAMPTZ,
  needs_republish     BOOLEAN NOT NULL DEFAULT FALSE,
  created_at          TIMESTAMPTZ NOT NULL,
  updated_at          TIMESTAMPTZ NOT NULL,
  deleted_at          TIMESTAMPTZ
);

CREATE INDEX idx_playlists_user_created
  ON playlists(user_id, created_at DESC)
  WHERE deleted_at IS NULL;

CREATE UNIQUE INDEX uq_playlists_user_normname
  ON playlists(user_id, normalized_name)
  WHERE deleted_at IS NULL;

CREATE INDEX idx_playlists_spotify_playlist_id
  ON playlists(spotify_playlist_id)
  WHERE spotify_playlist_id IS NOT NULL;
```

#### New table `playlist_tracks`

```sql
CREATE TABLE playlist_tracks (
  playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
  track_id    UUID NOT NULL REFERENCES clouder_tracks(id) ON DELETE RESTRICT,
  position    INT  NOT NULL CHECK (position >= 0),
  added_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (playlist_id, track_id)
);

CREATE UNIQUE INDEX uq_playlist_tracks_playlist_position
  ON playlist_tracks(playlist_id, position) DEFERRABLE INITIALLY DEFERRED;

CREATE INDEX idx_playlist_tracks_playlist_position
  ON playlist_tracks(playlist_id, position);
```

`DEFERRABLE INITIALLY DEFERRED` lets a transaction temporarily violate uniqueness during reorder swaps.

#### New table `user_imported_tracks`

```sql
CREATE TABLE user_imported_tracks (
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  track_id    UUID NOT NULL REFERENCES clouder_tracks(id) ON DELETE CASCADE,
  imported_at TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (user_id, track_id)
);

CREATE INDEX idx_user_imported_tracks_user
  ON user_imported_tracks(user_id);
```

Marks which user imported a given `spotify_user_import` track. Many-to-many because multiple users may import the same Spotify track. Used by the scope-check SQL to grant access to a user's own imports.

### Limits (service-layer validation)

| Limit | Value |
|---|---|
| Active playlists per user | 200 |
| Tracks per playlist | 1000 |
| `name` length | 1..100 chars |
| `description` length | 0..300 chars |
| Cover JPEG size | ≤ 262 144 bytes (256 KB, matches Spotify Cover API) |
| Spotify-import refs per request | ≤ 50 |

### `normalized_name`

`lower(trim(name))` with consecutive whitespace collapsed to single space. Same helper as categories / tags (reuse `_normalize_name`).

## S3 Layout for Covers

**Bucket**: existing `RAW_BUCKET_NAME`.
**Key**: `covers/{user_id}/{playlist_id}/{epoch_ms}.jpg`

`epoch_ms` is a cache-busting version. New upload → new key → fresh CloudFront / browser cache without query-string hacks. Old keys remain in S3 until a future lifecycle rule sweeps them (out of MVP scope).

### Upload flow

1. `POST /playlists/{id}/cover/upload-url` body `{ content_type: "image/jpeg" }`
   → server generates presigned PUT (5-min expiry, `Content-Type=image/jpeg`, `Content-Length<=262144`)
   → response `{ upload_url, s3_key, expires_in: 300 }`.
2. Client `PUT upload_url` with raw JPEG bytes.
3. `POST /playlists/{id}/cover/confirm`
   → backend HEAD the S3 object (validates size + content-type)
   → `UPDATE playlists SET cover_s3_key=$s3_key, cover_uploaded_at=now()` + `needs_republish=true` if previously published.

### Read flow

`GET /playlists/{id}` and `GET /playlists` return `cover_url` as a presigned GET (1-hour expiry). Cover is private — no public bucket policy.

### Delete

`DELETE /playlists/{id}/cover` nulls `cover_s3_key` + `cover_uploaded_at`, sets `needs_republish=true`. S3 object is not deleted.

## REST API

All endpoints under JWT auth (existing auth middleware → `user_id`). Error envelope `{error_code, message, correlation_id}`.

### Playlist CRUD

| Method | Path | Notes |
|---|---|---|
| `POST` | `/playlists` | body `{ name, description?, is_public? }`. 201 with full playlist. |
| `GET` | `/playlists` | `?cursor=&limit=20`, ORDER BY `created_at DESC`. |
| `GET` | `/playlists/{id}` | Detail incl. `cover_url`, `track_count`, publish state. |
| `PATCH` | `/playlists/{id}` | Partial: `name?`, `description?`, `is_public?`. Sets `needs_republish=true` if previously published. |
| `DELETE` | `/playlists/{id}` | Soft delete (`deleted_at = now()`). |

Every mutating endpoint sets `needs_republish=true` when `spotify_playlist_id IS NOT NULL`:
PATCH (name / description / is_public), cover upload-confirm, cover delete, tracks POST,
tracks DELETE, tracks order, import-spotify. Publish itself clears it back to `false`.

### Cover

| Method | Path | Notes |
|---|---|---|
| `POST` | `/playlists/{id}/cover/upload-url` | Issue presigned PUT. |
| `POST` | `/playlists/{id}/cover/confirm` | After client PUT to S3. |
| `DELETE` | `/playlists/{id}/cover` | Clear cover (S3 object remains). |

### Tracks

| Method | Path | Notes |
|---|---|---|
| `GET` | `/playlists/{id}/tracks` | `?cursor=&limit=50`, ORDER BY `position ASC`. |
| `POST` | `/playlists/{id}/tracks` | body `{ track_ids: [...] }`. Append. Dedup against existing. |
| `DELETE` | `/playlists/{id}/tracks/{track_id}` | Remove + re-dense positions. |
| `POST` | `/playlists/{id}/tracks/order` | body `{ track_ids: [ordered] }`. Full reorder (must match current set). |

`POST /playlists/{id}/tracks` validates every `track_id` against the user's scope (see SQL below). Unknown / cross-user IDs → 404 `track_not_in_user_scope`.

### Spotify import

```
POST /playlists/{id}/tracks/import-spotify
  body: { spotify_refs: ["spotify:track:...", "https://open.spotify.com/...", "5xkAVrK..."] }
  → 201 {
      added: [{ track_id, spotify_id, title }],
      skipped: [{ ref, reason: 'invalid_ref' | 'not_found' | 'already_in_playlist' }],
      position_after: int
    }
```

Accepts up to 50 refs. Three accepted formats: `spotify:track:<22-char-id>`, `https://open.spotify.com/track/<id>[?si=...]`, bare 22-char base62 ID.

### Publish

```
POST /playlists/{id}/publish
  body: { confirm_overwrite: bool }
  → 200 {
      spotify_playlist_id,
      spotify_url,
      skipped_tracks: [{ track_id, title, reason: 'no_spotify_id' }],
      published_at
    }
```

Publish stages (sequential, single Lambda invocation):

1. Resolve token (`user_vendor_tokens.spotify`); refresh if expiring within 60 s.
2. If `playlists.spotify_playlist_id IS NULL` → `POST /v1/users/{user_spotify_id}/playlists`.
   Else require `confirm_overwrite=true` (409 `confirm_overwrite_required` otherwise), then `PUT /v1/playlists/{id}` with `{name, description, public}`.
3. Filter tracks to those with `spotify_id IS NOT NULL`. Build URI list `spotify:track:{id}`. `PUT /v1/playlists/{id}/tracks` for first 100 (full replace). `POST /v1/playlists/{id}/tracks` for each next batch of 100.
4. If `cover_s3_key IS NOT NULL` → S3 GET → base64 → `PUT /v1/playlists/{id}/images`.
5. `UPDATE playlists SET spotify_playlist_id=..., last_published_at=now(), needs_republish=false`.

## Spotify Web API Integration

### `spotify_user_client.py`

User-OAuth flow (distinct from existing `spotify_client.py` which uses client_credentials). Resides in `src/collector/curation/`. Wraps `requests` with retry decorator and KMS-decrypts the access token per call.

| Method | Endpoint | Use |
|---|---|---|
| `get_track(spotify_id)` | `GET /v1/tracks/{id}` | Import resolve. |
| `create_playlist(user_spotify_id, name, description, public)` | `POST /v1/users/{user_id}/playlists` | First publish. |
| `update_playlist(playlist_id, name, description, public)` | `PUT /v1/playlists/{id}` | Re-publish metadata. |
| `replace_tracks(playlist_id, uris)` | `PUT /v1/playlists/{id}/tracks` | First 100 tracks (replace). |
| `append_tracks(playlist_id, uris)` | `POST /v1/playlists/{id}/tracks` | Subsequent batches. |
| `set_cover(playlist_id, jpeg_bytes)` | `PUT /v1/playlists/{id}/images` | base64-encoded body. |

### Token lifecycle

1. `SELECT access_token_enc, refresh_token_enc, data_key_enc, expires_at FROM user_vendor_tokens WHERE user_id=$user_id AND vendor='spotify'`.
2. KMS-decrypt access token (existing `envelope` helper, factored into shared `secrets_envelope.py`).
3. If `expires_at - now() < 60s` → `POST /api/token grant_type=refresh_token` → re-encrypt + UPDATE row.
4. If refresh fails 400 / 401 → 412 `spotify_not_authorized` (user must re-login).

### Scope

Existing OAuth scope (`auth_handler.py:53`) already includes `playlist-modify-public playlist-modify-private ugc-image-upload`. No scope change. Users whose tokens predate the `ugc-image-upload` grant → Spotify returns `insufficient_scope` → backend maps to 412 `spotify_scope_insufficient`, UI asks user to re-login.

### Retry + errors

- 429: respect `Retry-After`, retry once with exponential backoff. Still 429 → 502 `spotify_rate_limited`.
- 5xx: 1 retry, then 502 `spotify_api_error`.
- 401 after refresh attempt: 412 `spotify_not_authorized`.
- All retries via a dedicated `spotify_retry` decorator (mirrors `data_api_retry.py` pattern).

### Partial-publish failure

- First publish: `create_playlist` succeeded but `replace_tracks` failed → DO NOT persist `spotify_playlist_id`. The new (empty) Spotify playlist becomes orphan; next attempt creates a fresh one. Acceptable for MVP.
- Re-publish: failure mid-replace leaves Spotify inconsistent. `needs_republish` stays `true`. Log `playlist_publish_partial_fail` with the failed stage.

### Orphan `spotify_playlist_id` (user deleted Spotify playlist manually)

If `PUT /v1/playlists/{spotify_playlist_id}` returns 404, the previously-known Spotify playlist no longer exists. The publish service falls back to the first-publish branch: clears `spotify_playlist_id` in memory, runs `create_playlist`, and proceeds. `confirm_overwrite` is honored — the user already opted in to overwrite, and a missing playlist is a stronger no-conflict signal. Log `playlist_publish_orphan_recreated` with the old ID for audit.

### Import resolution

```python
def import_track(user_id, spotify_ref):
    spotify_id = parse_ref(spotify_ref)
    existing = SELECT id FROM clouder_tracks WHERE spotify_id = :spotify_id
    if existing:
        INSERT INTO user_imported_tracks (user_id, track_id, imported_at)
          VALUES (:user_id, :existing_id, now())
          ON CONFLICT DO NOTHING
        return existing.id

    spotify_track = client.get_track(spotify_id)
    track_id = uuid4()
    INSERT INTO clouder_tracks (
        id, title, length_ms, spotify_id, isrc, origin,
        label_id, album_id, ...
    ) VALUES (
        :track_id, :title, :length_ms, :spotify_id, :isrc,
        'spotify_user_import', NULL, NULL, ...
    ) ON CONFLICT (spotify_id) DO NOTHING
      RETURNING id

    -- If ON CONFLICT skipped, re-SELECT to get the winner's id
    final_id = result.id or SELECT id FROM clouder_tracks WHERE spotify_id=:spotify_id

    -- Artists: upsert by spotify_id if present
    for artist in spotify_track.artists:
        artist_id = upsert_artist_by_spotify_id(artist)
        INSERT INTO clouder_track_artists (track_id, artist_id, position)
          VALUES (:final_id, :artist_id, :pos)
          ON CONFLICT DO NOTHING

    INSERT INTO user_imported_tracks (user_id, track_id, imported_at)
      VALUES (:user_id, :final_id, now())
      ON CONFLICT DO NOTHING
    return final_id
```

`ON CONFLICT (spotify_id) DO NOTHING` handles the race where two users import the same track simultaneously. Album / label / release_type are left NULL — only Beatport-origin tracks have those.

## Scope-Check SQL

Used by `POST /playlists/{id}/tracks` to verify every supplied `track_id` belongs to the calling user:

```sql
SELECT t.id
FROM clouder_tracks t
WHERE t.id = ANY(:track_ids)
  AND (
    EXISTS (
      SELECT 1 FROM category_tracks ct
      JOIN categories c ON c.id = ct.category_id
      WHERE ct.track_id = t.id AND c.user_id = :user_id
    )
    OR EXISTS (
      SELECT 1 FROM playlist_tracks pt
      JOIN playlists p ON p.id = pt.playlist_id
      WHERE pt.track_id = t.id
        AND p.user_id = :user_id
        AND p.deleted_at IS NULL
    )
    OR EXISTS (
      SELECT 1 FROM user_imported_tracks uit
      WHERE uit.track_id = t.id AND uit.user_id = :user_id
    )
  );
```

Returned set is compared to input — missing IDs → 404 with their list.

## Component Layout

```
src/collector/curation/
  playlists_repository.py        # NEW — Aurora Data API
  playlists_service.py           # NEW — validation, orchestration
  spotify_user_client.py         # NEW — OAuth Spotify Web API
  schemas.py                     # EXTEND — request/response models

src/collector/curation_handler.py  # EXTEND — +12 route handlers
src/collector/secrets_envelope.py  # NEW — extracted KMS envelope helpers
                                   # (auth_handler.py currently owns them)
src/collector/storage.py           # EXTEND — presign helpers for covers
src/collector/errors.py            # EXTEND — new error codes

alembic/versions/
  20260512_19_playlists.py         # NEW

scripts/generate_openapi.py        # EXTEND ROUTES table (12 routes)
infra/api_gateway.tf               # EXTEND — 12 new route integrations
                                   # to curation Lambda
infra/curation.tf                  # EXTEND — IAM policy adds S3 covers/*
```

### Layer responsibilities

- **Handler**: parse body, extract `user_id` from JWT, validate envelope, map service errors to HTTP codes.
- **Service**: enforce limits, normalize name, orchestrate publish (Spotify + S3 + DB), call repository inside a single `repository.transaction()` where multi-step writes are needed.
- **Repository**: pure Aurora I/O via `data_api.py`. Every method takes `user_id`.

## Errors (extensions to `errors.py`)

| Code | HTTP | Trigger |
|---|---|---|
| `playlist_name_conflict` | 409 | `(user_id, normalized_name)` exists |
| `playlist_limit_reached` | 429 | ≥ 200 active playlists |
| `playlist_track_limit` | 400 | append would exceed 1000 tracks |
| `track_not_in_user_scope` | 404 | track not in user's categories / playlists / imports |
| `confirm_overwrite_required` | 409 | re-publish without `confirm_overwrite=true` |
| `spotify_not_authorized` | 412 | no token, or refresh failed |
| `spotify_scope_insufficient` | 412 | Spotify `insufficient_scope` |
| `spotify_api_error` | 502 | 5xx or 429-after-retries |
| `spotify_rate_limited` | 502 | persistent 429 |
| `invalid_spotify_ref` | 400 | parser failure |
| `cover_missing` | 400 | confirm called but S3 HEAD 404 |
| `cover_too_large` | 400 | S3 object > 262 144 bytes |
| `order_mismatch` | 400 | reorder body ≠ current track set |
| `nothing_to_publish` | 400 | empty playlist on publish |

## Structlog Events

```
playlist_created / patched / deleted
playlist_track_added (n=N) / removed / reordered
playlist_cover_upload_url_issued / cover_confirmed / cover_deleted
playlist_spotify_import_requested (refs_count=N)
playlist_spotify_track_imported (spotify_id, reused_existing=bool)
playlist_spotify_import_failed (spotify_id, reason)
playlist_publish_started (first_time=bool, track_count, has_cover=bool)
playlist_publish_token_refreshed
playlist_publish_create_called / _replace_tracks_called (batch=N) / _cover_called
playlist_publish_succeeded (spotify_playlist_id, skipped=N, duration_ms)
playlist_publish_failed (stage, reason)
playlist_publish_partial_fail (stage, spotify_playlist_id)
playlist_publish_orphan_recreated (old_spotify_playlist_id, new_spotify_playlist_id)
```

Every event includes `correlation_id`, `user_id`, `playlist_id`. `spotify_access_token` is NEVER logged — same rule as `bp_token`.

## IAM (Terraform)

`beatport-prod-curation` Lambda role additions:
- `s3:PutObject` / `s3:GetObject` / `s3:HeadObject` on `${raw_bucket_arn}/covers/*`.
- `kms:Decrypt` on the `user_vendor_tokens` KMS key — already granted to auth handler; extend to curation Lambda.
- `secretsmanager:GetSecretValue` for master RDS — already granted.
- `rds-data:ExecuteStatement` — already granted.

S3 bucket policy unchanged (covers stay private; access is via presigned GET).

## Test Plan

### Unit

- `parse_spotify_ref` — 3 accepted formats + edge cases (uppercase ID, query strings, leading whitespace, malformed input).
- `playlists_service` limits — 200 / 1000 / 100-char / 300-char boundaries.
- `_normalize_name` — whitespace collapse, case fold, emoji.
- `reorder_tracks` order_mismatch detection (missing IDs, extra IDs, duplicate IDs).
- `spotify_user_client` retry: 429 with `Retry-After`, 5xx single retry, 401 propagation.
- `validate_tracks_in_scope` SQL: cross-user track absent from result, own categories / own playlists / own imports all grant access.

### Integration (ephemeral Postgres)

- Full CRUD lifecycle: create → patch → add tracks → reorder → soft-delete; soft-deleted playlist hidden from list.
- Cover flow: upload-url → mocked S3 PUT → confirm → `cover_url` present in GET.
- Re-upload cover: new `epoch_ms` key, old key untouched.
- Publish first-time: mocked Spotify client; `spotify_playlist_id` persisted; 4 API calls in correct order.
- Re-publish without confirm → 409 `confirm_overwrite_required`.
- Re-publish with confirm: name + tracks + cover replaced; `needs_republish` cleared.
- Skip tracks without `spotify_id`: response carries `skipped_tracks`, Spotify call receives only resolvable URIs.
- Token expired → refresh executed once; UPDATE row.
- Spotify 401 post-refresh → 412 `spotify_not_authorized`.
- Import: existing `spotify_id` reused, missing creates new `origin='spotify_user_import'` row, `user_imported_tracks` marker added.
- Import race: two simultaneous imports of the same Spotify ID — ON CONFLICT keeps a single canonical row.
- `is_public=true` reaches Spotify `public=true`.
- Orphan Spotify ID: re-publish where Spotify returns 404 on PUT → falls back to create flow, new `spotify_playlist_id` persisted, `playlist_publish_orphan_recreated` logged.
- All mutating endpoints set `needs_republish=true` post-publish (PATCH, tracks add/remove/reorder, cover confirm/delete, import).

## Out of Scope / Future Work

- Bulk import (Spotify playlist or album URL) — single-track only in MVP.
- Async publish for very large playlists (>700 tracks risk API GW 29s timeout) — sync only.
- Image resizing — client must produce JPEG ≤ 256 KB.
- Cover lifecycle / orphan cleanup — old `epoch_ms` keys remain in S3.
- Cross-user playlist sharing — `is_public` controls only Spotify visibility, not CLOUDER ACL.
- Spotify playlist deletion — soft delete in CLOUDER never unfollows on Spotify.
- Auto-recovery of `spotify_id` for Beatport-origin tracks during publish — `spotify_search_worker` handles that out-of-band.

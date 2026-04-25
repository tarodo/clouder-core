# Old Version Feature Parity — Gap Analysis

**Date:** 2026-04-25
**Status:** brainstorm stage
**Author:** @tarodo (via brainstorming session)
**Source artefact:** `docs/clouder_dj_old.xml` (Repomix dump of pre-AWS Clouder DJ project: FastAPI + React + Postgres + Redis/Taskiq, single-deployment-per-user app).

## 1. Context and Goal

The user (DJ) maintained a hand-rolled monolithic music-curation web app (`clouder_dj_old`) and is rebuilding it as a serverless backend on AWS (`clouder-core`). The new repo today implements only the **ingestion + canonicalization + vendor-match data backbone** (Beatport ingest → S3 raw → SQS → canonical `clouder_*` tables → Spotify ISRC enrichment → Perplexity label search → vendor match cache).

The old version goes much further: it is an end-user product with Spotify OAuth login, multi-stage curation (raw layer → categories → release playlists), and direct Spotify playlist mutations.

The goal of this spec is **NOT** to design an implementation. It is to:

1. Catalogue every user-facing process from the old version.
2. For each, classify how the current AWS architecture stands relative to it: `covered`, `partial`, `missing`, or `superseded`.
3. Identify which old features are still desired (vs. dropped by design).
4. Decompose desired-but-missing features into a **prioritized list of follow-up specs** — each one will get its own brainstorm → spec → plan cycle. Nothing in this document gets implemented; this is a research deliverable.

## 2. Scope

**In scope:**

- Inventory of old features grouped by domain.
- Per-feature readiness classification against the current AWS arch.
- A decomposition into follow-up specs with a recommended ordering.
- Explicit list of old features that should be **dropped** (not ported) and why.

**Out of scope:**

- Design or plan for any individual missing feature (each becomes its own spec later).
- Migration of data from old Postgres into new Aurora (different schema, different tenancy model — this is greenfield).
- UI / frontend specifics. The old React app is a reference for UX, not a design source.
- Security review of the old OAuth token encryption (`SpotifyToken` Fernet) — irrelevant; new arch will use KMS envelope per existing `user_vendor_tokens` plan.

## 3. Architectural Diff

### 3.1 Old version (clouder_dj_old)

```
Browser (React + Vite)
     │
     ▼
FastAPI monolith ──► PostgreSQL (single DB, all entities + auth)
     │
     ├──► Spotify OAuth (PKCE, per-user)
     ├──► Spotify Web API (search, playlist CRUD)
     ├──► Beatport API (user-supplied bp_token)
     │
     └──► Taskiq broker (Redis) ──► Worker ──► same DB
```

Deployment model: docker-compose, **one user per deployment** (multi-user-ready schema but single-tenant in practice).

### 3.2 New version (clouder-core)

```
HTTP API Gateway
     │
     ├── POST /collect_bp_releases ─┐
     ├── GET  /runs/{run_id}        │
     ├── GET  /tracks, /artists,    │
     │        /albums, /labels,     ├──► API Lambda (collector.handler)
     │        /styles, /tracks/     │             │
     │        spotify-not-found ────┘             ▼
     │                                       S3 raw  +  ingest_runs (Aurora Data API)
     │                                             │
     ▼                                             ▼
                                           SQS canonicalization
                                                  │
                                                  ▼
                                       Worker Lambda (canonicalize)
                                                  │
                                  ┌───────────────┼────────────────┐
                                  ▼               ▼                ▼
                          ai_search SQS    spotify_search SQS  vendor_match SQS
                          (Perplexity)     (Spotify ISRC)      (per-vendor ID)
```

Deployment model: serverless, **no users, no auth, no playlists** — pure data pipeline.

### 3.3 Functional delta

| Layer                     | Old | New | Delta                                                            |
|---------------------------|-----|-----|------------------------------------------------------------------|
| Auth (Spotify OAuth)      | Yes (Mode 1 only) | No | Per §7.3: required scopes expand (Mode 1 + Mode 2 + Premium gate). Whole layer missing. |
| Multi-user / multi-tenant | Implicit | No (single-tenant pipeline) | Per §7.1: multi-tenant from day one, three-layer (admin ingest / shared core / per-user overlay). |
| Beatport ingest           | Date-range, on-demand | Iso-week + style, on-demand | Param shape differs; new is narrower |
| Canonical entities        | Flat (track/release/artist/label) | UUID-keyed `clouder_*` + identity_map | New is stricter and richer |
| Spotify track enrichment  | Batch ISRC search via Taskiq | Per-track via SQS worker | Equivalent, async-by-design |
| Spotify artist enrichment | Yes | No | Missing |
| Triage (was "raw layer", 5-playlist curation) | Yes (Spotify-backed) | No | Re-scoped per §7.4: **Aurora-only**, no Spotify playlists. Missing. |
| Categories (silver)       | Yes (Spotify-backed) | No | Re-scoped per §7.4: **Aurora-only**. Missing. |
| Release playlists (gold)  | Yes (Spotify-backed) | Stub (`release_mirror` planned in 2026-04-18 spec) | Partial. Per §7.4: keeps Spotify sync (Mode 1 write) + multi-vendor mirror. |
| Spotify playlist CRUD     | Yes | No (export-stub only) | Needed only for release-playlist sync (§7.4). Not needed for triage/categories. |
| Spotify Web Playback SDK | Frontend-only, Premium | None | Required (§7.3 Mode 2) so frontend can play tracks during triage. |
| AI label search           | No  | Yes | New feature, no parity needed |
| Vendor match cache        | No  | Yes | New feature, no parity needed |
| Frontend                  | React SPA | None | Missing |
| Read API for browsing     | Yes (`/tracks`, `/releases`, ...) | Yes (`/tracks`, `/artists`, `/albums`, `/labels`, `/styles`) | Roughly equivalent |
| Task status polling       | `/tasks/status/{id}` | `/runs/{run_id}` (only ingest runs) | Partial — ingest only |

## 4. Old Feature Inventory and Readiness

Each row: feature name → status against current new arch → desired action.

Status legend:

- **covered** — new arch already has equivalent or better.
- **partial** — backbone exists, user-facing surface missing.
- **missing** — no equivalent.
- **superseded** — old design intentionally replaced; do not port.
- **drop** — feature deliberately not desired in new product.

### 4.1 Auth & User Model

| # | Feature                          | Endpoint(s)               | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| A1 | Spotify OAuth login (PKCE)      | `GET /auth/login`, `GET /auth/callback` | missing | Need user table, OAuth handler Lambda, KMS-encrypted refresh-token storage. The 2026-04-18 spec already proposes `user_vendor_tokens` table + KMS crypto without the OAuth flow — so the storage half is partially designed. |
| A2 | App-token refresh                | `POST /auth/refresh`      | missing | JWT issue/refresh layer. |
| A3 | Spotify token auto-refresh on 401| Frontend lib              | missing | Frontend concern; deferred. |
| A4 | User profile (`/me`)             | `GET /me`                 | missing | Trivial once user table exists. |
| A5 | Encrypted Spotify refresh token  | `spotify_tokens` table    | partial | New plan: KMS envelope; old: Fernet. |

### 4.2 Beatport Ingestion

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| B1 | Collect tracks for style+date range | `POST /collect/beatport/collect` (date_from, date_to) | superseded | New arch uses `iso_year + iso_week` (single week). Date-range collection was lossy and re-fetched; weekly cadence is cleaner. |
| B2 | Two-phase processing (raw → entities)| `external_data` w/ `processed=false` → batch process | superseded | New arch: raw S3 + canonicalize via SQS (`source_entities` + `clouder_*`). Functionally equivalent, conceptually better. |
| B3 | Track collection stats           | `GET /collect/stats`      | partial  | New `/tracks?...&total=...` etc. give counts but no roll-up by style. Add `GET /stats` later if useful. |

### 4.3 Spotify Enrichment

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| S1 | Track enrichment by ISRC         | `POST /collect/spotify/enrich` | covered | New `spotify_handler` does this per-batch, idempotent via `spotify_searched_at`. |
| S2 | Fuzzy artist match scoring       | rapidfuzz, similarity_threshold=80 | partial | New `vendor_match` worker has `FUZZY_MATCH_THRESHOLD=0.92`, but only for track→vendor mapping, not artist-level. |
| S3 | Detect duplicate Spotify IDs across local tracks | enrichment side-effect | missing | No equivalent; data quality concern. Track in a follow-up. |
| S4 | Artist enrichment                | `POST /collect/spotify/enrich-artists` | missing | Need a `spotify_artist_search` flow analogous to label-search. |
| S5 | Read tracks not found on Spotify | `GET /tracks/spotify-not-found` | covered | Already in `handler.py:_handle_spotify_not_found`. |

### 4.4 Triage Curation (was "Raw Layer Bronze" in old code)

Per §7.2 + §7.4: triage lives entirely in Aurora — no Spotify playlists are created. The 5-bucket model survives as logical buckets, not Spotify playlists.

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| R1 | Create triage block (5 buckets + N category targets) | `POST /curation/styles/{style_id}/raw-blocks` (old) → `POST /triage/blocks` (new) | missing | Aurora-only. Requires: `users`, `triage_blocks`, `triage_playlists`, `triage_block_tracks`, `triage_playlists_tracks`. **No Spotify calls** for create. |
| R2 | List blocks (paginated, all / by style) | `GET /curation/raw-blocks`, `GET /curation/styles/{style_id}/raw-blocks` | missing | Trivial once R1 exists. |
| R3 | Get single block                 | `GET /curation/raw-blocks/{block_id}` | missing | Returns block + bucket counts. |
| R4 | Mark block processed             | `POST /curation/raw-blocks/{block_id}/process` | missing | |
| R5 | Delete block                     | `DELETE /curation/raw-blocks/{block_id}` | missing | Just soft-delete in Aurora. No Spotify cleanup needed. |
| R6 | Track classification into NEW/OLD/NOT/TRASH/TARGET buckets | service-internal during R1 | missing | Logic depends on `release_type` (album_type) which new schema stores on `clouder_tracks` after Spotify enrichment. The old §10.2 ordering simplifies dramatically: no `asyncio.gather()` of Spotify creates, no 0.5s propagation delay, no transactional Spotify-rollback risk. |
| R7 | Move track between buckets       | (was implicit via Spotify-client drag in old) | missing | New: explicit endpoint, e.g. `POST /triage/blocks/{id}/move` with `{track_id, from_bucket, to_bucket}`. |

### 4.5 Categories (Silver)

Per §7.4: categories live entirely in Aurora — no Spotify playlist per category.

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| C1 | Create categories (batch)        | `POST /curation/styles/{style_id}/categories` | missing | Just Aurora rows. **No Spotify playlist per category.** Drops the entire Mode-1 transactional pitfall. |
| C2 | List categories (all / by style) | `GET /curation/categories`, `GET /curation/styles/{style_id}/categories` | missing | |
| C3 | Update category (rename)         | `PATCH /curation/categories/{category_id}` | missing | Aurora-only rename. No Spotify orphan-detection needed. |
| C4 | Delete category                  | `DELETE /curation/categories/{category_id}` | missing | Soft-delete in Aurora. |
| C5 | Add track to category            | `POST /curation/categories/{category_id}/tracks` | missing | Aurora INSERT, idempotent on `(category_id, track_id)`. No Spotify call. |

### 4.6 Release Playlists (Gold) — the only layer that syncs to Spotify

Per §7.4: release-playlist is the assembly point. Aurora is source of truth, but each release-playlist is mirrored to Spotify (Mode 1 write) and optionally to other vendors via `release_mirror_worker`.

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| P1 | Create empty release playlist    | `POST /release-playlists` | partial | Aurora-create + Spotify-create (user OAuth). Reuse the 2026-04-18 `release_mirror_worker` flow but as the primary write path, not a stub. |
| P2 | Import existing Spotify playlist | `POST /release-playlists/import` | open (§7.6) | Read-only direction (Spotify → Aurora), doesn't violate §7.4. Decide in spec-E whether to keep. |
| P3 | List release playlists           | `GET /release-playlists`  | missing | |
| P4 | Get single release playlist + tracks | `GET /release-playlists/{playlist_id}` | missing | |
| P5 | Add/remove tracks                | (implicit in old)         | missing | Aurora write + push delta to Spotify (Mode 1 add/remove items). |
| P6 | Trigger multi-vendor mirror      | new (per 2026-04-18 spec) | missing | Per-vendor playlist create on YT Music / Deezer / Apple / Tidal. |

### 4.7 Browse / Read API

| # | Feature                          | Old endpoint              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| Br1 | Paginated tracks (with search)  | `GET /tracks`             | covered | New has equivalent. |
| Br2 | Paginated releases (albums)     | `GET /releases`           | covered | New `GET /albums`. |
| Br3 | Styles, artists, labels list    | `GET /styles`, `/artists`, `/labels` | covered | All present. |
| Br4 | Single-entity detail endpoints  | implied                   | missing | New only has list endpoints today. |

### 4.8 Background Tasks

| # | Feature                          | Old mechanism             | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| T1 | Long-running task progress      | Taskiq + Redis result backend | partial | New: `ingest_runs.processed_count / item_count`. Sufficient for current ingest but no equivalent for enrichment progress. |
| T2 | Task status endpoint             | `GET /tasks/status/{task_id}` | partial | `GET /runs/{run_id}` covers ingest only. Need a generic job-status surface if curation tasks become async. |

### 4.9 Frontend

| # | Feature                          | Old artefact              | Status   | Notes |
|---|----------------------------------|---------------------------|----------|-------|
| F1 | React SPA (Vite + Tailwind + shadcn) | `frontend/` | missing | Out of scope for backend specs; tracked separately. |
| F2 | Spotify Web Playback SDK player | `Player.tsx` + `useSpotifyPlayer.ts` | missing | Frontend-only. |

## 5. Drop List (Old Features Not Worth Porting)

These are deliberately NOT ported. Each gets a sentence on why.

- **Date-range Beatport collection (B1).** Replaced by iso-week cadence in new arch. Cleaner, idempotent.
- **`external_data.processed=false` two-phase processing (B2).** Replaced by `source_entities` + canonical `clouder_*` + `identity_map`. Strictly better.
- **Fernet-encrypted Spotify refresh token (A5).** Replaced by KMS envelope in 2026-04-18 spec.
- **Taskiq + Redis broker.** Replaced by SQS. Don't reintroduce.
- **`Player.tsx` + Web Playback SDK.** Frontend-only; out of scope here.

## 6. Decomposition Into Follow-Up Specs

Re-shaped after §7 decisions. The Spotify-Export adapter (spec-B) is now needed only for the release-playlist layer — triage and categories live entirely in Aurora and don't depend on it. This collapses the dependency graph significantly.

1. **`spec-A: User & Auth Foundation`** — covers A1–A5 + Premium-gate from §7.3. Adds: `users` table (with `is_admin` flag), Spotify OAuth login/callback Lambda with combined Mode 1 + Mode 2 scope (§7.3), Premium check at callback, KMS-encrypted user OAuth token (per 2026-04-18 `user_vendor_tokens`), JWT issue/refresh, `GET /me`, `is_admin` middleware for ingest endpoints. **Hard dependency for everything below.**
2. **`spec-C: Categories`** — covers C1–C5. **Aurora-only** (no Spotify per §7.4). Trivial surface — good first user feature post spec-A. Independent of spec-B.
3. **`spec-D: Triage Curation`** — covers R1–R7 (renamed per §7.2). **Aurora-only** (no Spotify per §7.4). Largest user feature by surface area but architecturally simpler than the old code (no Spotify transactional risk). Depends on spec-A and spec-C (target buckets reference categories).
4. **`spec-B: Spotify Playlist Export adapter`** — only `ExportProvider` real implementation for Spotify (Mode 1 write). Used **only** by spec-E. Reduced scope vs. original plan: triage and categories no longer call it.
5. **`spec-E: Release Playlists + multi-vendor mirror`** — covers P1–P6. Depends on spec-A, spec-B. Reconciles with 2026-04-18 `release_mirror_worker`: that worker becomes the primary write path for release-playlists, not a stub. Includes Spotify Mode 1 write + multi-vendor mirror (YT/Deezer/Apple/Tidal stubs from 2026-04-18 spec).
6. **`spec-F: Spotify Artist Enrichment`** — S4. Independent ingest-side concern; admin-triggered. Can ship in parallel with any user-side spec.
7. **`spec-G: Frontend (Web Playback SDK + curation UI)`** — separate spec, frontend-only. Depends on spec-A (auth) and on spec-D (triage API surface). Web Playback SDK setup (Mode 2 Premium streaming).
8. **`spec-H (optional): Read API polish`** — Br4 single-entity detail endpoints, B3 stats roll-up, S3 duplicate-Spotify-id audit. Low priority. JWT-gated per §7.5.
9. **`spec-I (optional): Generic Job Status API`** — only if release-playlist mirror becomes async-heavy. Defer until needed.

Dependency graph (post §7):

```
spec-A (User/Auth/Premium) ──┬──► spec-C (Categories, Aurora-only)
                             │       │
                             │       ▼
                             ├──► spec-D (Triage, Aurora-only) ──► spec-G (Frontend)
                             │
                             └──► spec-B (Spotify Export) ──► spec-E (Release Playlists + mirror)

spec-F (Artist Enrichment) — independent (ingest)
spec-H, spec-I — independent, low priority
```

The critical path is shorter: spec-A → spec-C → spec-D unlocks the entire user-facing curation flow without ever touching spec-B. Release-playlist sync is a deliberate later milestone.

## 7. Architectural Decisions (resolved 2026-04-25)

The five questions originally listed here have been resolved during the brainstorming session. The product shape that all subsequent specs MUST honour:

### 7.1 Tenancy — multi-tenant SaaS

- One Aurora DB serves all users. Multi-tenant from day one.
- Three layers: **ingest** (admin/cron only), **canonical core** (shared), **user overlay** (per-user).
- Frontend is the only entry point for user surface. Public ingest endpoints stay admin-protected.
- Every user-layer table carries `user_id NOT NULL FK → users.id`. Every user query filters by current `user_id`.

### 7.2 Curation layers (renamed from old "raw layer")

- **Triage** — first curation layer (was `raw_layer_*` in old code; renamed because the new ingest pipeline already uses "raw" for S3 source data). Tables: `triage_blocks`, `triage_playlists`, `triage_block_tracks`, `triage_playlists_tracks`. API: `POST /triage/blocks`, etc. Section 4.4 below uses the new name.
- **Categories** — second curation layer. Unchanged name.
- **Release playlists** — final curation layer. Unchanged name.

### 7.3 Spotify integration — three distinct roles

| Role | Auth | Scope | Premium needed | Used by |
|------|------|-------|----------------|---------|
| Lookup / Enrich | service client_credentials | none (app-level) | no | admin ingest (ISRC search, release_type) |
| Web API playlist write (Mode 1) | user OAuth | `playlist-modify-public`, `playlist-modify-private` | no | **release-playlist sync only** |
| Web Playback SDK (Mode 2) | user OAuth | `streaming`, `user-read-playback-state`, `user-modify-playback-state` | **yes** | frontend playback (browser as Spotify Connect device) |

Combined user OAuth scope string:
`user-read-email user-read-private playlist-modify-public playlist-modify-private streaming user-read-playback-state user-modify-playback-state`

**Premium-only access.** Login-gate blocks non-Premium Spotify users at OAuth callback. Acceptable because target user (DJ) is always Premium.

### 7.4 Source of truth

- **Triage and categories** live **only in Aurora**. No Spotify playlists are created or written for these layers. User listens via our frontend (Web Playback SDK plays Spotify-URI tracks directly). User cannot edit triage/categories via Spotify-client.
- **Release playlists** are pushed to Spotify via user OAuth (Mode 1 write). Aurora remains source of truth — we do NOT read back from Spotify. If the user edits the Spotify-side copy directly, those edits are invisible to us.
- **Multi-vendor mirror** (YT Music, Deezer, Apple Music, Tidal) stays in scope per 2026-04-18 spec. Triggered on demand from a finished release-playlist.

### 7.5 Browse-API auth

- Every endpoint requires JWT. No public read access, even for canonical core listing.
- Canonical data (`/tracks`, `/artists`, `/albums`, `/labels`, `/styles`) is shared across all users — but only logged-in users can read it.
- Admin-only endpoints (ingest, `match_review_queue`, run status) live behind an `is_admin` flag on the `users` table. No separate admin API surface.

### 7.6 Still-open mini-questions (deferred to individual specs)

- **P2 — release-playlist import from Spotify.** Old version supports importing an existing Spotify playlist URL into a local release-playlist (read-only direction, doesn't violate the no-Spotify-sync rule). Decide in spec-E whether to keep or drop this convenience.
- **Premium fallback UX** — what does the login screen show to a non-Premium user who tries to log in? Plain block, or a CTA explaining the requirement? Decide in spec-A.

## 8. Acceptance Criteria for This Spec

Status: §7 decisions have been resolved during the brainstorming session (2026-04-25). The spec is ready for implementation-spec breakouts.

Outstanding for the user:
- Spot-check §4 inventory after the §7-driven re-shape (esp. §4.4 triage, §4.5 categories, §4.6 release-playlists).
- Confirm §6 ordering (proposed: spec-A → spec-C → spec-D unblocks the user-curation flow without spec-B/spec-E).
- Decide the §7.6 mini-questions when their target spec begins (P2 import, Premium fallback UX).

Once §6 ordering is confirmed, each `spec-*` row becomes its own brainstorm cycle with its own design doc. No code is written off this spec.

## 9. References

- New project README: `README.md`
- New data model: `docs/data-model.md`
- Vendor-sync readiness spec (related, partial coverage of spec-E): `docs/superpowers/specs/2026-04-18-vendor-sync-readiness-design.md`
- New project CLAUDE.md (gotchas + env vars): root `CLAUDE.md`
- Old project Repomix dump: previously at `docs/clouder_dj_old.xml`. **Removed after extraction** — operational knowledge captured in §10 below.

## 10. Knowledge Dump From Old Code

This section preserves every operationally relevant value, edge case, and ordering decision extracted from the old codebase before it was deleted from this repository. File paths refer to the old project layout (FastAPI monolith) — they exist only as historical context, not as something to read in this repo.

**Applicability after §7 decisions.** Several items below describe Spotify playlist mutations that were used for triage and categories in the old code. After §7.4 (Aurora-only triage + categories), those items apply **only to spec-E (Release Playlists)** — the only layer that still writes to Spotify. They are explicitly tagged `[release-playlist only]` where relevant. Items marked `[obsolete]` describe behaviour the new architecture deliberately does NOT reproduce.

### 10.1 Spotify API integration

| # | Item | Old file | Value / Pattern |
|---|------|----------|------------------|
| K1.1 | OAuth scopes | `backend/app/core/settings.py` | Old: `"user-read-email user-read-private playlist-modify-public playlist-modify-private"`. **New (per §7.3, Mode 1 + Mode 2):** `"user-read-email user-read-private playlist-modify-public playlist-modify-private streaming user-read-playback-state user-modify-playback-state"`. Premium-only. |
| K1.2 | Access-token TTL | settings | `30` minutes. |
| K1.3 | Refresh-token TTL | settings | `7` days (much shorter than Spotify's own 60-day refresh window — intentional). |
| K1.4 | OAuth state cookie | `backend/app/api/auth.py` | `max_age=600` (10 min), `httponly=True`, `secure=settings.SECURE_COOKIES`. Same TTL as the code-verifier cookie. |
| K1.5 | PKCE config | `backend/app/core/security.py` | code_verifier = `base64.urlsafe_b64encode(os.urandom(32))` (256-bit entropy). challenge_method = `S256`. |
| K1.6 | Spotify propagation delay after `create_playlist` | `backend/app/services/raw_layer.py` | `await asyncio.sleep(0.5)` between create and add-items. Without this, add-items can 404 on a freshly-created playlist. **[release-playlist only]** — triage/categories don't create Spotify playlists. |
| K1.7 | Add-items batch size | `backend/app/clients/spotify.py` | Hard limit `100` items per `POST /v1/playlists/{id}/tracks`. Loop in chunks of 100. **[release-playlist only]** |
| K1.8 | Search-by-ISRC query format | spotify client | `{"q": f"isrc:{isrc}", "type": "track"}`. `type=track` is mandatory. |
| K1.9 | ISRC enrichment batch size | settings | `SPOTIFY_SEARCH_BATCH_SIZE = 50`. |
| K1.10 | Get-playlist-items pagination | spotify client | `limit=50` per page; field filter `items(track(uri)),next` to minimize payload; loop while response has `next` URL. |
| K1.11 | Unfollow vs delete | spotify client | Spotify exposes only `DELETE /v1/playlists/{id}/followers` — there is no true delete. Catch 404 silently (already gone). **[release-playlist only]** |
| K1.12 | Update-playlist 404 = orphan | `backend/app/services/category.py` | If `update_playlist_details()` raises `SpotifyNotFoundError`, soft-delete the local category. **[obsolete]** — categories no longer have Spotify playlists. Pattern still useful for spec-E (release-playlist orphan detection on user-side delete). |
| K1.13 | Add-track dedup | category service | Always call `get_playlist_items()` first; return success if `track_uri` already present. **[release-playlist only]** — add-track to category is now an Aurora INSERT with unique constraint, not a Spotify call. |
| K1.14 | Token-revocation signature | spotify client | `status_code == 400 and error_data.get("error") == "invalid_grant"`. Delete the stored token and force re-OAuth. |
| K1.15 | Server-error retry | spotify client | Up to 3 retries on `502/503/504`. Exponential `delay = 1.0 * 2**attempt`. 429 (rate-limit) is not retried in code; relies on httpx + Spotify `Retry-After`. |

### 10.2 Raw-layer block creation (most subtle flow in the OLD product)

**[obsolete for triage]** — per §7.4, the new triage layer lives only in Aurora and creates no Spotify playlists. The Spotify-orchestration parts of this section are dead. The **classification rules** (which tracks land in which bucket) survive as pure Aurora logic and are still authoritative for spec-D.

Step ordering inside `RawLayerService.create_raw_layer_block()` (`backend/app/services/raw_layer.py`):

1. Validate style exists; validate `(user_id, style_id, block_name)` unique.
2. Fetch matching tracks from DB (style + date range).
3. `asyncio.gather()` create 4 fixed playlists (`INBOX_NEW`, `INBOX_OLD`, `INBOX_NOT`, `TRASH`) + N category-target playlists in parallel on Spotify.
4. Flush block + playlist rows to DB.
5. `await asyncio.sleep(0.5)` (Spotify propagation, see K1.6).
6. Categorize tracks in memory.
7. `asyncio.gather()` add-items to each playlist in parallel (per-playlist chunked at 100, see K1.7).

**Track classification rules** (`_categorize_tracks()`):

- `INBOX_NEW`: `release_date >= start_date` AND `album_type ∈ VALID_SPOTIFY_ALBUM_TYPES`.
- `INBOX_OLD`: `release_date < start_date` AND `album_type ∈ VALID_SPOTIFY_ALBUM_TYPES`.
- `INBOX_NOT`: `album_type ∉ VALID_SPOTIFY_ALBUM_TYPES`.
- `VALID_SPOTIFY_ALBUM_TYPES = ("album", "single")` — compilations excluded by design.
- `TRASH` and `TARGET` playlists: created empty; populated later by manual curation.
- Tracks with no `release_date`: silently skipped (do not classify into NEW/OLD).

**Playlist-name format:** `f"{style.name} :: {block_name} :: {TYPE}"` where TYPE is `NEW`/`OLD`/`NOT`/`TRASH`/uppercased category name. Example: `"Techno :: Q1-2024 :: NEW"`.

**Transactional weakness in old code:** if Spotify create succeeds for some playlists then DB flush fails, orphan playlists accumulate on Spotify. New arch must add a compensating-delete step or split the flow into "reserve DB row → create Spotify → confirm DB row" with idempotency.

### 10.3 ISRC enrichment match logic

`EnrichmentService._validate_spotify_search_result()` (`backend/app/services/enrichment.py`):

- ISRC match alone is **not sufficient.** Both required:
  1. Spotify returned at least one track for the ISRC.
  2. Local artist names fuzzy-match a Spotify artist name above threshold.
- Library: `rapidfuzz`, scorer `fuzz.ratio` (NOT `token_set_ratio`), via `process.extractOne(...)`.
- Threshold constant: `ARTIST_FUZZY_MATCH_THRESHOLD = 85` in `backend/app/core/constants.py`. Endpoint accepts `similarity_threshold: int = 80` override (default 80 in the API surface, 85 in the constants — pick one when re-implementing; the old code is inconsistent).

**Reason codes stored in `external_data.raw_data` for non-matches:**

- `{"status": "missing_isrc"}` — local track has no ISRC.
- `{"status": "not_found_by_isrc"}` — Spotify returned no result.
- `{"status": "duplicate_spotify_track_existing_link", "spotify_id": ..., "linked_track_id": ...}` — Spotify ID already linked to a different local track from a previous run.
- `{"status": "duplicate_spotify_track_in_batch", "spotify_id": ...}` — same Spotify ID matched twice within one enrichment batch (in-memory `batch_assigned_ids: set[str]`).

**External-id collision-avoidance for not-found records:** `external_id = f"NOT_FOUND_{track.id}_{uuid.uuid4()}"` (constant: `SPOTIFY_NOT_FOUND_PREFIX = "NOT_FOUND_"`). Allows storing multiple "not found" attempts without unique-constraint violations.

### 10.4 Release-playlist import (Spotify → local)

`ReleasePlaylistService.import_from_spotify()` (`backend/app/services/release_playlist.py`):

- URL parsing regex: `re.compile(r"(?<=playlist\/)([a-zA-Z0-9]+)")`. Fallback: if the input has no `/` and no whitespace, treat the whole string as a raw playlist ID.
- Orphan items (Spotify URI with no matching local track) are **silently skipped**, not error.
- Order preservation: build `uri_to_position = {uri: i for i, uri in enumerate(spotify_uris)}` and persist `(track_id, position)` rows.

### 10.5 Auth + token storage

| Item | Old file | Value |
|------|----------|-------|
| JWT algorithm | `backend/app/core/security.py` | `HS256` (configurable via `JWT_ALGO`). |
| Refresh-token encryption | security | `cryptography.fernet.Fernet` with key from `ENCRYPTION_KEY` env. Stored in `spotify_tokens.encrypted_refresh_token`. (New arch: replace with KMS envelope per 2026-04-18 spec.) |
| `users` table key | `backend/app/db/models/user.py` | `spotify_id` is the unique business key (not email). |
| `spotify_tokens.user_id` | model | UNIQUE — one Spotify token per user. |

### 10.6 Frontend token-refresh details (worth re-using when frontend ships)

`frontend/src/lib/api.ts`:

- `refreshPromise: Promise<string> | null` deduplication: many concurrent 401s during a token expiry window must hit `POST /auth/refresh` exactly once. Reset to `null` in `finally`.
- 401 retry: max **1** retry after refresh (no exponential backoff — refresh either fixes it or kicks the user to login).
- Token storage: refresh-token in `localStorage` (survives reload), access-token in memory or `sessionStorage`.

### 10.7 Background processing

| Item | Old file | Value |
|------|----------|-------|
| Beatport raw-batch processing chunk | `backend/app/services/data_processing.py` | `BATCH_SIZE = 500` records per processing chunk. |
| Progress-callback signature | data_processing / enrichment | `Callable[[Dict[str, Any]], Awaitable[None]]` — payload typically `{"processed": int, "failed": int, "total": int}`. |
| Concurrency model | services | `asyncio.gather()` for parallelism within a worker; no distributed lock — relies on DB unique constraints to win races. New arch (SQS workers) must add idempotent upserts since multiple Lambdas can race. |

### 10.8 Schema & migration gotchas worth porting

- Track uniqueness: `UniqueConstraint("name", "release_id", "isrc", name="uq_track_name_release_id_isrc")` — the trio is the natural key. New arch already has UUID PKs but should keep the equivalent unique index.
- Artist/label `name` was UNIQUE globally. Re-evaluate in new arch: with multi-vendor sources, the same name can be two different entities (handled today via `identity_map`).
- The `1a2b3c4d5e6f_standardize_enum_casing.py` migration exists because Postgres ENUMs were stored mixed-case originally — the migration normalized to UPPER. **Lesson:** in new arch, store enum-like fields as `String(N)` (already done) instead of Postgres ENUM types — avoids this whole class of migration pain.

### 10.9 Constants and magic strings to preserve

```
VALID_SPOTIFY_ALBUM_TYPES   = ("album", "single")
SPOTIFY_NOT_FOUND_PREFIX    = "NOT_FOUND_"
ARTIST_FUZZY_MATCH_THRESHOLD = 85   # default, overridable per-call
SPOTIFY_SEARCH_BATCH_SIZE   = 50
SPOTIFY_ADD_ITEMS_BATCH     = 100   # Spotify hard limit
SPOTIFY_PROPAGATION_DELAY_S = 0.5
ACCESS_TOKEN_EXPIRE_MIN     = 30
REFRESH_TOKEN_EXPIRE_DAYS   = 7
OAUTH_COOKIE_TTL_S          = 600
PKCE_VERIFIER_BYTES         = 32
PKCE_CHALLENGE_METHOD       = "S256"
SPOTIFY_SCOPES              = "user-read-email user-read-private playlist-modify-public playlist-modify-private"
PROCESS_BATCH_SIZE          = 500   # Beatport raw rows per chunk
```

### 10.10 Anti-patterns from old code worth NOT repeating

- **Implicit transactions across Spotify + DB.** Old code relies on SQLAlchemy session rollback; if Spotify partially succeeds and DB rolls back, orphan playlists remain. New arch must make the compensating delete explicit.
- **Sync-style `asyncio.gather` with shared DB session.** Caused subtle session-leak bugs in the old code. New arch (SQS workers) sidesteps this by isolating each worker invocation.
- **Two `similarity_threshold` defaults** (80 in API surface, 85 in constants). Pick one source of truth in new arch.
- **`external_data` table mixing "raw response cache" and "process status"** (`processed=false`). New arch separates this cleanly: `source_entities` for raw, `identity_map` for resolution status. Don't re-merge them.
- **Frontend storing both app refresh-token and Spotify access-token in localStorage.** Spotify access-token is short-lived and should be re-fetched via app refresh; keeping it in localStorage adds attack surface for no benefit.

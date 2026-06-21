# CLOUDER system map

CLOUDER is a serverless ingest pipeline plus a React 19 SPA for DJ track curation. The backend is a set of Python 3.12 Lambdas under `src/collector/`; the SPA under `frontend/src/`; infrastructure is Terraform under `infra/`. Aurora PostgreSQL (Serverless v2) is reached **only via the RDS Data API** at runtime — never `psycopg`. This map traces every HTTP entry point, the ingest/canonicalization data flow, vendor-call fan-out, the data-access layer, the infrastructure that hosts it, and the frontend, then summarizes the attack surface, Aurora write points, and money-spend points across all of them.

---

## 1. API surface & auth flow

### Architecture overview

All HTTP traffic lands on one API Gateway v2 HTTP API, `aws_apigatewayv2_api.collector` (`infra/api_gateway.tf:1`), single `$default` auto-deploy stage (`infra/api_gateway.tf:201`). CORS allows methods GET/POST/PUT/PATCH/DELETE/OPTIONS, headers `authorization,content-type,x-correlation-id`, `allow_credentials = false` (`infra/api_gateway.tf:5-15`); CORS is only configured when `cors_allowed_origins` is non-empty (default empty → CORS off at API GW, handled at CloudFront instead) (`infra/variables.tf:431-435`). Routes fan out across three Lambda integrations:

- `collector_lambda` — `src/collector/handler.py` (`infra/api_gateway.tf:18-23`).
- `curation` — `src/collector/curation_handler.py` (`infra/curation.tf:49-54`).
- `auth_lambda` — `src/collector/auth_handler.py` (`infra/auth.tf:149-154`).

A single REQUEST-type Lambda authorizer `aws_apigatewayv2_authorizer.jwt` (`infra/auth.tf:156-165`) protects every non-public route. It is simple-response (`enable_simple_responses = true`), identity source `$request.header.Authorization`, backed by `auth_authorizer` Lambda (`src/collector/auth_authorizer.py`), result cached `var.auth_authorizer_cache_ttl_seconds` (300s; `infra/auth.tf:163`).

### How identity reaches handlers

The authorizer verifies the HS256 access JWT and returns `{isAuthorized, context:{user_id, session_id, is_admin}}` (`src/collector/auth_authorizer.py:59-66`). API Gateway exposes that under `event.requestContext.authorizer.lambda`. Each downstream handler reads it there:

- collector identity for user-scoped routes: `label_enrichment/routes.py:61-70` (`_extract_user_id`), mirrored in artist routes; admin gate `_require_admin` reads `...authorizer.lambda.is_admin` (`src/collector/handler.py:89-97`).
- curation identity: `_user_id_or_none` reads `...authorizer.lambda.user_id`, returns 401 if missing (`src/collector/curation_handler.py:171-181`, enforced at `:447-449`).
- auth_handler identity (for protected `/me`-family routes): `_authorizer_context` reads the same path (`src/collector/auth_handler.py:537-545`).

Admin enforcement is application-level only: the authorizer admits any valid token, and `handler.py` calls `_require_admin` for the `_ADMIN_ROUTES` frozenset (`src/collector/handler.py:60-86`, dispatched at `:158-159`). The curation Lambda has no admin routes.

### Route inventory

All routes below carry `authorization_type = "CUSTOM"` + the JWT authorizer **except** the four public auth routes (noted). "Admin" = additionally gated in-app via `_require_admin`.

**collector_lambda** (`handler.py`; routes in `infra/api_gateway.tf`):

| Method/Path | Authorizer | Identity source | Notes |
|---|---|---|---|
| POST /collect_bp_releases | yes | — | admin (`handler.py:60-86`), legacy |
| GET /runs/{run_id} | yes | — | non-admin |
| GET /tracks, /artists, /albums, /labels, /styles | yes | per-route | list routes |
| GET /tracks/spotify-not-found | yes | — | admin |
| POST /admin/beatport/ingest | yes | — | admin |
| GET /admin/coverage, GET /admin/runs | yes | — | admin |
| POST /admin/labels/enrich | yes | `_extract_user_id` (created_by) | admin |
| POST /admin/labels/{label_id}/enrich-auto | yes | — | admin |
| GET /admin/labels/enrich-runs, .../{run_id}, /enrich/options, /backlog, /{label_id}, /{label_id}/history | yes | — | admin |
| GET /labels/{label_id} | yes | `_extract_user_id` | user overlay (`handler.py:236-239`) |
| PUT /labels/{label_id}/preference | yes | `_extract_user_id` (required, else ValidationError) | user; `routes.py:275-277` |
| GET /me/label-preferences | yes | `_extract_user_id` (required) | user; `routes.py:319-321` |
| GET/PUT /admin/auto-enrich/labels | yes | — | admin |
| POST /admin/artists/enrich, .../{artist_id}/enrich-auto | yes | `_extract_user_id` | admin |
| GET /admin/artists/enrich-runs, .../{run_id}, /enrich/options, /backlog, /{artist_id}, /{artist_id}/history | yes | — | admin |
| GET/PUT /admin/auto-enrich/artists | yes | — | admin |
| GET /artists/{artist_id} | yes | `_extract_user_id` | user overlay (`handler.py:305-306`) |
| PUT /artists/{artist_id}/preference | yes | `_extract_user_id` | user |
| GET /me/artist-preferences | yes | `_extract_user_id` | user |

**curation** (`curation_handler.py`; every route JWT-gated, all scoped by `user_id` via `_ROUTE_TABLE`):

- Categories (`infra/curation.tf:58-71`): POST/GET `/styles/{style_id}/categories`, PUT `/styles/{style_id}/categories/order`, GET `/categories`, GET/PATCH/DELETE `/categories/{id}`, GET/POST `/categories/{id}/tracks`, DELETE `/categories/{id}/tracks/{track_id}`.
- Playlists (`infra/curation_routes_playlists.tf:6-24`): POST/GET `/playlists`, GET/PATCH/DELETE `/playlists/{id}`, GET/POST `/playlists/{id}/tracks`, DELETE `/playlists/{id}/tracks/{track_id}`, POST `/playlists/{id}/tracks/order`, POST `/playlists/{id}/cover/upload-url`, POST `/playlists/{id}/cover/confirm`, DELETE `/playlists/{id}/cover`, POST `/playlists/{id}/tracks/import-spotify`, POST `/playlists/{id}/publish`, POST `/playlists/{id}/publish-ytmusic`, GET `/playlists/{id}/tracks/{track_id}/match-candidates`, POST `/playlists/{id}/tracks/{track_id}/match-resolve`.
- Tags (`infra/curation_routes_tags.tf:6-15`): POST/GET `/tags`, PATCH/DELETE `/tags/{tag_id}`, GET/PUT/POST `/tracks/{track_id}/tags`, DELETE `/tracks/{track_id}/tags/{tag_id}`.
- Triage (`infra/curation_routes_triage.tf:6-16`): POST `/triage/blocks`, GET `/styles/{style_id}/triage/blocks`, GET `/triage/blocks`, GET `/triage/blocks/{id}`, GET `/triage/blocks/{id}/buckets/{bucket_id}/tracks`, POST `/triage/blocks/{id}/move`, POST `/triage/blocks/{src_id}/transfer`, POST `/triage/blocks/{id}/finalize`, DELETE `/triage/blocks/{id}`.

**auth_lambda** (`auth_handler.py`; routes in `infra/auth.tf`; internal dispatch `auth_handler.py:133-160`):

| Method/Path | Authorizer | Identity source |
|---|---|---|
| GET /auth/login | **no (public)** | — (`infra/auth.tf:169-173`) |
| GET /auth/callback | **no (public)** | Spotify profile after code exchange (`infra/auth.tf:175-179`) |
| POST /auth/refresh | **no (public)** | refresh-cookie JWT (`infra/auth.tf:181-185`) |
| POST /auth/logout | **no (public)** | refresh-cookie JWT (`infra/auth.tf:187-191`) |
| GET /me | yes | `_authorizer_context` user_id/session_id (`infra/auth.tf:195-201`) |
| DELETE /me/sessions/{session_id} | yes | `_authorizer_context` (`infra/auth.tf:203-209`) |
| POST /auth/ytmusic/device-code | yes | `_authorizer_context` (`infra/auth.tf:211-217`) |
| POST /auth/ytmusic/poll | yes | `_authorizer_context` (`infra/auth.tf:219-225`) |
| DELETE /auth/ytmusic | yes | `_authorizer_context` (`infra/auth.tf:227-233`) |

### JWT / refresh flow end to end

**Tokens.** Two HS256 JWTs signed with one shared secret (`src/collector/auth/jwt_utils.py:12`). Access token: claims `sub`(user_id), `session_id`, `is_admin`, `typ:"access"`, `iat`, `exp`; default TTL 1800s (`jwt_utils.py:34-51`; TTL `auth_settings.py:39-41`). Refresh token: `sub`, `session_id`, `typ:"refresh"`, `jti`, `iat`, `exp`; default TTL 604800s/7d (`jwt_utils.py:54-70`; `auth_settings.py:42-44`). The signing key is a 64-char random_password in SSM SecureString (`infra/auth.tf:16-30`); both Lambdas resolve it via `resolve_jwt_signing_key` (env override else SSM, `auth_settings.py:52-63`). `_decode` requires `exp,iat,sub,typ,session_id`, enforces type match and manual expiry (`jwt_utils.py:100-127`).

**Login (`GET /auth/login`, `auth_handler.py:163-207`).** Optional `redirect_uri` checked against `ALLOWED_FRONTEND_REDIRECTS` allow-list (`auth_settings.py:22-23`). Generates CSRF `state` + PKCE verifier/challenge, sets short HttpOnly/Secure/SameSite=Lax cookies `oauth_state`, `oauth_verifier`, optional `oauth_redirect` (max-age 600s, `auth_handler.py:192-198, 210-214`), 302-redirects to Spotify authorize URL with scopes at `auth_handler.py:59-63`.

**Callback (`GET /auth/callback`, `auth_handler.py:270-391`).** Validates `code`+`state`, checks `oauth_state` cookie equals returned state else `CsrfStateMismatchError` (`:281-285`), exchanges code with PKCE verifier, fetches Spotify profile. Requires `product == "premium"` else `PremiumRequiredError` (`:294-295`). Upserts user (admin if spotify_id in `ADMIN_SPOTIFY_IDS`, `auth_settings.py:19-20`); encrypts Spotify access+refresh tokens via KMS envelope and stores in `user_vendor_tokens` (`:314-327`). Creates a session storing the **SHA-256 hash** of the refresh JWT (`_sha256_hex`, `:338-347, 746-747`). Returns 200 JSON `{access_token, spotify_access_token, expires_in, user}` plus a `refresh_token` cookie scoped `Path=/auth/refresh; HttpOnly; Secure; SameSite=Strict` (`_refresh_cookie`, `:739-743`), and clears the oauth_state/verifier cookies.

**Refresh (`POST /auth/refresh`, `auth_handler.py:394-504`).** Reads `refresh_token` cookie, verifies refresh JWT, looks up active session (`:410`), ensures `session.user_id == claims.user_id`. **Replay detection:** if the inbound token's hash ≠ stored hash, it revokes ALL of the user's sessions and raises `RefreshReplayDetectedError` (`:414-417`) — this is the ADR-0015 "replay revokes every session" behavior. It decrypts the stored Spotify refresh token, calls Spotify refresh (revoked → revoke session + delete vendor token + `SpotifyRevokedError`, `:432-435`), re-encrypts and upserts new Spotify tokens, issues a NEW refresh JWT, rotates the session hash (`rotate_session`, `:464-468`), issues a new access JWT, and returns tokens + a rolled `refresh_token` cookie. Rotation is the reason concurrent double-refresh triggers replay (mitigated frontend-side, see §6).

**Logout (`POST /auth/logout`, `auth_handler.py:507-534`).** Best-effort: verifies refresh cookie, revokes that one session, returns 204 with an expired `refresh_token` cookie.

**Authorizer (`auth_authorizer.py`).** Caches the signing key 300s (`:14-36`), requires `Authorization: Bearer <token>` (`:42-46`), verifies access token, returns `isAuthorized:false` on any failure (`:51-57`), else returns the identity context (`:59-66`).

**Frontend auth** is detailed in §6.

**Notable observations:**
- Admin authorization is enforced only in `handler.py` application code, not at the gateway; the curation and auth Lambdas have no admin concept. A token with `is_admin:false` still passes the authorizer for every admin route — protection depends entirely on `_require_admin` being wired for each route in `_ADMIN_ROUTES` (`handler.py:60-86`). Any new `/admin/*` route added to the gateway but omitted from that frozenset would be reachable by any authenticated user.
- `jwt_utils._decode` sets `verify_iat:False` "iat may be in the future in tests" (`jwt_utils.py:112-113`) — production tokens accept future-issued `iat`.
- The authorizer result is cached (`infra/auth.tf:163`); admin/identity changes propagate only after cache TTL expiry.

---

## 2. Ingest & canonicalization data flow

The pipeline has two Lambdas joined by one SQS queue: the **API Lambda** (`handler.py`) fetches from Beatport, persists a raw S3 snapshot, writes an `ingest_runs` row, and enqueues a canonicalization message; the **worker Lambda** (`worker_handler.py`) reads the snapshot back, normalizes it, and canonicalizes it into Aurora.

### 2.1 Trigger & request shapes (API Lambda)

Two routes reach the same ingest core `_run_beatport_ingest` (`handler.py:341`):
- **Legacy ISO path** — `POST /collect_bp_releases` → `_handle_collect` (`handler.py:501`). Body validated by `CollectRequestIn` (`schemas.py:18`): `bp_token`, `style_id>0`, `iso_year∈[2000,2100]`, `iso_week∈[1,53]`, `extra="forbid"`, with a cross-field check that `date.fromisocalendar(iso_year, iso_week, 1)` is valid (`schemas.py:34-40`). Period bounds come from `compute_iso_week_date_range` using `date.fromisocalendar` Monday→Sunday (`models.py:139-144`). Sets `week_year/week_number=None`, `is_custom_range=False` (`handler.py:514-516`).
- **Admin path** — `POST /admin/beatport/ingest` → `_handle_admin_ingest` (`handler.py:521`), gated by `_require_admin` via `_ADMIN_ROUTES` (`handler.py:60`, `89`, `158`). Body validated by `AdminIngestRequestIn` (`schemas.py:112`): `style_id`, `week_year`, `week_number`, optional `period_start/period_end`, `bp_token`, `extra="forbid"`. The model enforces both period dates present-or-absent together, `period_end>=period_start`, and `week_number<=weeks_in_year(week_year)` (`schemas.py:130-146`).

Admin period resolution (`handler.py:530-540`): if `period_start` is omitted, the period is derived from the Saturday-week math `saturday_week_range(week_year, week_number)` and `is_custom_range=False`; if dates are supplied they are used verbatim and `is_custom_range=True`. ISO fields are forced to `None` on the admin path (`handler.py:547-548`).

`_IngestParams` (`handler.py:317`) documents the three valid field combinations (legacy ISO / admin Saturday-week / admin custom-range).

### 2.2 Beatport fetch

`registry.get_ingest("beatport")` returns `BeatportProvider`, a thin adapter over `BeatportClient` (`providers/beatport.py:18-25`, `providers/registry.py:31-37`); base URL is `ApiSettings.beatport_api_base_url`. `fetch_weekly_releases` (`beatport_client.py:44`) is called with `bp_token`, `style_id`, `period_start`, `period_end`, `correlation_id` (`handler.py:376-383`).

Fetch details (`beatport_client.py:52-84`):
- `GET {base}/tracks/` with query `genre_id=style_id`, `publish_date={week_start}:{week_end}`, `page=1`, `per_page=100`, `order_by=-publish_date`.
- Paginates by following the response `next` URL (re-parsing its query into params, `beatport_client.py:80`, `167-171`); stops when `next` is absent/blank. Safety cap **300 pages** → raises `UpstreamUnavailableError` if exceeded (`beatport_client.py:52`, `84`).
- Items extracted from the first matching key among `results/items/releases/data` (`beatport_client.py:158-165`).
- Per-page retry: up to `max_retries=4` with exponential backoff + jitter (`beatport_client.py:153-156`); retryable on `{408,429,500,502,503,504}` (`beatport_client.py:22`); `401/403` → `UpstreamAuthError` (`beatport_client.py:133-134`); `urllib` request via stdlib (no `requests`).
- Returns `(all_items, pages_fetched)`. `bp_token` is sent only as the `Authorization: Bearer` header and never logged — log events emit only a SHA-256 URL hash (`beatport_client.py:18-19`, `101-108`).

### 2.3 S3 layout (`storage.py`)

`_run_beatport_ingest` builds a `meta` dict including `style_id`, both week schemes, `period_start/end`, `is_custom_range`, `run_id`, correlation/request IDs, `collected_at_utc` (Z-suffixed), `item_count`, `api_pages_fetched`, `duration_ms` (`handler.py:387-407`), then calls `S3Storage.write_run_artifacts(releases, meta)` (`handler.py:409-414`).

`write_run_artifacts` (`storage.py:27`):
- Resolves year/week as `iso_year`/`iso_week` if present else `week_year`/`week_number`; raises `StorageError` if neither pair present (`storage.py:32-37`).
- Base key: `{raw_prefix}/style_id={style_id}/year={year}/week={week:02d}` (`_base_key`, `storage.py:245-248`). `raw_prefix` defaults to `raw/bp/releases` (`settings.py:123`).
- Writes two objects: `…/releases.json.gz` (gzip-compressed minified JSON array; `Content-Encoding: gzip`) and `…/meta.json` (uncompressed) (`storage.py:43-73`). Any S3 failure → `StorageError` (`storage.py:81-82`).
- Returns `(releases_key, meta_key)`; only `releases_key` is used downstream (`handler.py:414`). The key is keyed by style+year+week only — **re-running the same style/week overwrites the S3 snapshot** (no run-id in the path).

### 2.4 ingest_runs row creation (API side)

A fresh `run_id = uuid4()` (`handler.py:360`). After S3 write, if a repository is configured, `create_ingest_run` is called with `status=RAW_SAVED`, `processed_count` literal `0`, `started_at=utc_now()` and the same `meta` (`handler.py:416-436`).

`create_ingest_run` (`repositories.py:151`) is an `INSERT … ON CONFLICT (run_id) DO UPDATE` that, on conflict, overwrites all columns from EXCLUDED and **clears** `error_code/error_message/finished_at` (`repositories.py:169-185`) — making a retry of the same `run_id` idempotent and resetting prior failure state. This call is **not** in an explicit transaction (auto-commit single statement). If the repository is `None` (DB unconfigured) the row is silently skipped (`handler.py:417`).

### 2.5 SQS enqueue & message shape

`_enqueue_canonicalization` (`handler.py:878`) gates on `ApiSettings.canonicalization_enabled` and a non-empty `canonicalization_queue_url` (`settings.py:127-139`); when disabled/missing it returns `FAILED_TO_QUEUE` + `DISABLED` without raising (`handler.py:889-919`). On success it sends:

```json
{"run_id","source":"beatport","s3_key","style_id","iso_year","iso_week","attempt":1}
```

(`handler.py:921-929`) — minified JSON body, with `correlation_id` as an SQS `MessageAttribute` (`handler.py:936-942`). The message carries **`iso_year/iso_week` only** — the Saturday-week fields are not propagated (they're `None` on the admin path), but the worker does not need them (S3 key already resolved in `s3_key`). Enqueue failures are caught and reported as `ENQUEUE_FAILED` (`handler.py:957-974`); the API still returns 200 with `run_status=RAW_SAVED` plus `processing_status/outcome/reason` (`handler.py:448-498`). So a run can be permanently stuck at `RAW_SAVED` if enqueue fails.

`CanonicalizationMessage` (`schemas.py:43`) validates: `run_id` and `s3_key` non-empty, `source` default `"beatport"`, `attempt>=1`, `extra="ignore"`.

### 2.6 Worker: read → normalize → canonicalize (`worker_handler.py`)

`lambda_handler` (`worker_handler.py:24`) processes each SQS record independently in a `for` loop (`worker_handler.py:50`). Per record:
1. Parse body via `CanonicalizationMessage.model_validate_json`; on validation error it logs and `continue`s (drops the message) (`worker_handler.py:57-67`).
2. `correlation_id` = message attribute else `run_id` (`worker_handler.py:71`).
3. **Phase `read_s3`**: `storage.read_releases(s3_key)` — get object, gzip-decompress, JSON-parse, filter to dict items; any failure → `StorageError` (`storage.py:92-107`).
4. **Phase `normalize`**: `normalize_tracks(raw_tracks)` (`worker_handler.py:94`).
5. **Phase `canonicalize`**: `Canonicalizer(repository).process_run(run_id, bundle)` (`worker_handler.py:108-109`).
6. **Phase `mark_completed`**: `repository.set_run_completed(run_id, processed_count=result.tracks_processed, finished_at=utc_now())` (`worker_handler.py:112-116`).
7. **Phase `enqueue_followups`**: enqueues a Spotify ISRC search message `{"batch_size":2000}` onto `spotify_search_queue_url` if configured (`worker_handler.py:134-138`, `185-221`).

Worker requires a configured repository or it raises `RuntimeError` (`worker_handler.py:37-41`).

**Error handling / DLQ semantics** (`worker_handler.py:139-180`): any exception → `set_run_failed` with `error_code` chosen by `isinstance(exc, _PERMANENT_ERRORS)` where `_PERMANENT_ERRORS = (ValueError, TypeError, KeyError, StorageError)` (`worker_handler.py:21`). Permanent errors → log + `continue` (message deleted, no DLQ cycling); transient errors → `raise` (message returns to queue → retries → DLQ). `set_run_failed` records the failing `phase` as a `[phase=…]` prefix on `error_message` (`repositories.py:235-238`), surfaced split-back-out by `_split_phase_prefix` in `GET /runs/{run_id}` (`handler.py:17-23`, `700-708`). A failure inside `set_run_failed` itself is caught and logged but doesn't mask the original (`worker_handler.py:154-163`).

### 2.7 Normalization (`normalize.py`)

`normalize_tracks` (`normalize.py:39`) walks raw items once, de-duplicating each entity by Beatport id into ordered dicts, and emitting relations:
- **Track** keyed by `item.id` (positive int; bool rejected — `_as_positive_int`, `normalize.py:217-222`); skipped if id or `name` missing (`normalize.py:51-52`, `140-142`). Fields: `mix_name`, `isrc`, `bpm`, `length_ms`, `key_name`+`key_camelot` (from `item.key`, camelot built only if both `camelot_number` int and `camelot_letter` present — `_as_key`, `normalize.py:232-246`), `publish_date` (first 10 chars of `publish_date` or `new_release_date`, only if `YYYY-MM-DD` shaped — `_as_date_str`, `normalize.py:255-263`), `bp_release_id`, `bp_genre_id`, `bp_artist_ids` (dedup-ordered).
- **Artists** from `item.artists[]` (each needs id+name); **Album** from `item.release` (id+name); **Label** from `release.label`; **Style** from `item.genre`. Album release_date comes from the track's `publish_date`/`new_release_date` (`normalize.py:88-90`).
- **Relations** (deduped via `_dedupe_relations`, `normalize.py:197`): `track_artist`, `track_album`, `album_label`, `track_style` (`models.py:55-59`).
- `normalize_text` = strip→lower→collapse whitespace (`models.py:147-148`).

Returns a `NormalizedBundle` of immutable tuples (`normalize.py:29-36`, `187-194`).

### 2.8 Canonicalization & Aurora writes (`canonicalize.py`)

`Canonicalizer.process_run` (`canonicalize.py:36`) runs phases in this order, recording `completed_phases` for diagnostics: **labels → styles → artists → albums → relations → tracks** (`canonicalize.py:53-83`). Order matters: labels precede albums (album FK `label_id`), and styles/albums/artists precede tracks (track FK `style_id`/`album_id`, and track-artist join). Tracks are processed in **chunks of 200** (`canonicalize.py:346-349`).

**Transaction boundaries: one transaction per phase, and one transaction per 200-track chunk** — each opened via `self._repository.transaction()` (`canonicalize.py:121`, `166`, `211`, `260`, `311`, `359`). `transaction()` → `DataAPIClient.transaction()` is a context manager: `begin_transaction` → yield `transaction_id` → `commit_transaction`, with `rollback_transaction` on any exception (`data_api.py:99-107`, `repositories.py:1000-1001`). **There is no single transaction spanning the whole message** — a worker crash mid-run can leave some phases committed and the `ingest_runs` row still `RAW_SAVED` (or `FAILED` if `set_run_failed` ran). This is safe because every write is idempotent and re-running the `run_id` replays cleanly.

The shared two-step pattern inside each entity phase:
1. `batch_upsert_source_entities` writes the raw provenance copy.
2. For each entity, `find_identity` looks up an existing canonical id; if found, reuse it (no insert command); if absent, mint `uuid4()`, call `create_*` (the canonical row), and queue an `UpsertIdentityCmd`. Then `batch_upsert_identities` writes all new mappings (`canonicalize.py:138-152`, `_resolve_label` `443-476`, etc.).

#### Every Aurora table written by ingest, with conflict strategy

DDL primarily in `alembic/versions/20260301_01_init_clouder_schema.py`.

- **`ingest_runs`** (PK `run_id`, init `20260301_01:22-39`; Saturday-week cols + `idx_ingest_runs_coverage` added `20260509_16`). Written by API `create_ingest_run` (`ON CONFLICT (run_id) DO UPDATE` resetting error/finished, `repositories.py:169`) and by worker `set_run_completed` / `set_run_failed` (`UPDATE … WHERE run_id`, `repositories.py:206`, `227`). **Not written by the Canonicalizer.**
- **`source_entities`** (PK `(source, entity_type, external_id)`; FK `last_run_id→ingest_runs.run_id`, made nullable in `20260315_06`; `idx_source_entities_run`). `batch_upsert_source_entities`: `ON CONFLICT (source,entity_type,external_id) DO UPDATE` of `name, normalized_name, payload, payload_hash, last_seen_at, last_run_id`; `first_seen_at` preserved (`repositories.py:312-344`). One row per entity per phase; `payload_hash` is SHA-256 of canonical-sorted JSON (`canonicalize.py:659-663`). The `last_run_id` FK means the `ingest_runs` row must already exist — it does, written by the API before enqueue.
- **`identity_map`** (PK `(source, entity_type, external_id)`; `idx_identity_map_clouder`; `confidence` `NUMERIC(4,3)`). `batch_upsert_identities`: `ON CONFLICT DO UPDATE` of `clouder_entity_type, clouder_id, match_type, confidence, last_seen_at` (`repositories.py:482-512`). New mappings use `match_type="auto_create"`, `confidence=0.600` (`MATCH_AUTO_CREATE`, `canonicalize.py:29`). `MATCH_IDENTITY=1.000` is defined but unused here.
- **`source_relations`** (PK = all six relation columns; FK `last_run_id→ingest_runs`; extra index in `20260308_02`). `batch_upsert_source_relations`: `ON CONFLICT (all six) DO UPDATE SET last_run_id` (`repositories.py:383-411`). One transaction for the whole relations batch (`canonicalize.py:308-326`).
- **`clouder_labels`** / **`clouder_styles`** / **`clouder_artists`** (PK `id`). `create_label/create_style/create_artist`: `INSERT … ON CONFLICT (id) DO NOTHING` (`repositories.py:537-581`, `514-535`). Since `id` is a freshly minted uuid only created when no identity exists, `DO NOTHING` is just a race guard. `clouder_styles` added in `20260314_04`.
- **`clouder_albums`** (PK `id`; FK `label_id→clouder_labels`; `idx_album_match` on `(normalized_title, release_date, label_id)`). `create_album`: `INSERT … ON CONFLICT (id) DO NOTHING` (`repositories.py:583-611`). `label_id` resolved from the `label_ids` map (`canonicalize.py:279-291`).
- **`clouder_tracks`** (PK `id`; FK `album_id→clouder_albums`, `style_id→clouder_styles`; partial `idx_tracks_isrc`; spotify cols from `20260315_05`; `release_type`/`ai` from `09`; `key_camelot` from `30`). **New track**: `create_track` `INSERT … ON CONFLICT (id) DO NOTHING` (`repositories.py:613-645`). **Existing track**: `conservative_update_track` (`repositories.py:647-694`) — a field-by-field merge: `mix_name/key_name/key_camelot/publish_date/album_id/style_id` use `COALESCE(:new, existing)` (only fill nulls); `isrc/bpm/length_ms` use a `CASE` that keeps existing when new is null, fills when existing is null, and **overwrites when the values differ** (`repositories.py:654-671`). `updated_at` always bumped. This is the one place an existing canonical row is mutated during ingest. (Spotify fields `spotify_id/spotify_searched_at/release_type` are written later by the separate Spotify search Lambda via `batch_update_spotify_results`, `repositories.py:802`, not the canonicalizer.)
- **`clouder_track_artists`** (PK `(track_id, artist_id, role)`; FKs to tracks & artists). `batch_upsert_track_artists`: `INSERT … ON CONFLICT (track_id,artist_id,role) DO NOTHING` (`repositories.py:713-735`), role hard-coded `"main"` (`canonicalize.py:417`). Commands deduped via a `set` before insert (`canonicalize.py:376`, `421-425`).

All entity writes for a phase/chunk (source_entities + the canonical `create_*` calls + identities + track-artists) share that phase's/chunk's `transaction_id`, so a phase either fully commits or rolls back.

### 2.9 ingest_runs lifecycle

`RunStatus` enum has exactly three states (`models.py:24-28`): `RAW_SAVED → COMPLETED | FAILED`.
- **RAW_SAVED** — set by API immediately after S3 write (`handler.py:431`, `repositories.py:151`); error/finished cleared on conflict.
- **COMPLETED** — set by worker after all canonicalization phases succeed, with `processed_count=tracks_processed`, `finished_at`, and nulled error fields (`worker_handler.py:112`, `repositories.py:206`).
- **FAILED** — set by worker on any exception, with `error_code` (permanent vs transient), `[phase=…]`-prefixed `error_message` (truncated to 2000 incl. prefix), `finished_at` (`worker_handler.py:147`, `repositories.py:227-257`).

There is **no in-progress status** — a run sits at `RAW_SAVED` while the worker runs, and (per the MEMORY note on silent Lambda failures) a worker timeout is not a Python exception, so a timed-out run can remain `RAW_SAVED` indefinitely.

Read surfaces: `GET /runs/{run_id}` returns status + `{processed,total}` + split-out error phase (`handler.py:665-723`); `GET /admin/runs` lists runs for a `(style_id, week_year, week_number)` cell ordered by `started_at DESC` (`handler.py:621`, `repositories.py:1118`); `GET /admin/coverage` builds the year matrix joining `clouder_styles → identity_map → ingest_runs` and selecting the latest run per cell via a `LATERAL` + `NOT EXISTS` newest-wins filter (`handler.py:556`, `repositories.py:1070-1116`).

### 2.10 Saturday-week period logic (`saturday_week.py`)

Canonical period for the admin UI (not ISO week):
- `first_saturday(year)` = first Saturday on/after Jan 1 (`saturday_week.py:18-21`, `_SATURDAY=5`).
- `saturday_week_range(year, week)` = `start = first_saturday + (week-1)*7`, `end = start+6` (Saturday→Friday); raises `ValueError` if `week` outside `1..weeks_in_year` (`saturday_week.py:35-43`).
- `weeks_in_year(year)` counts Saturdays from `first_saturday(year)` to the last Saturday on/before Dec 31 (`saturday_week.py:29-32`); used by both `AdminIngestRequestIn` validation (`schemas.py:141-145`) and `GET /admin/coverage` (`handler.py:613`).
- `week_of_date(d)` maps a date back to `(year, week)`, attributing pre-first-Saturday days to the previous year's last week (`saturday_week.py:46-57`).

Both week schemes are stored on `ingest_runs` (ISO via legacy route, Saturday via admin route; the other pair is `NULL`), and the S3 key prefers ISO then falls back to Saturday `week_year/week_number` (`storage.py:33-34`).

### Notable observations
- **S3 snapshot overwrite**: `releases.json.gz` key omits `run_id`, so two runs of the same style/week clobber each other's raw snapshot (`storage.py:245-248`); only the `ingest_runs` row preserves per-run identity.
- **No whole-message transaction**: per-phase/per-chunk commits (`canonicalize.py`) mean partial canonicalization is possible on crash; idempotency (identity-map lookup + `ON CONFLICT`) makes replay safe, but a timed-out worker leaves the run at `RAW_SAVED` with partial data committed.
- **Enqueue failure is non-fatal to the API** (`handler.py:957-974`) → run can be stranded at `RAW_SAVED` with no automatic retry.
- **`conservative_update_track` overwrites `isrc/bpm/length_ms` on any change** (`repositories.py:654-671`) — the only non-additive mutation in the ingest path; worth flagging if upstream Beatport data is ever noisier than the canonical record.

---

## 3. Enrichment & vendor calls

External-vendor call sites fall into four families: **Beatport ingest** (admin weekly fetch, see §2.2), **track-matching lookups** (Spotify ISRC search, YT Music metadata search), **LLM enrichment** (label/artist fan-out to Gemini/OpenAI/Tavily+DeepSeek), and **playlist publish/import** (user-OAuth Spotify + YouTube Data API). Aggregate fan-out is the dominant cost driver: enrichment multiplies as `labels|artists × vendors × (1 generate + 1 merge)`, and publish/import multiplies per-track.

### 3.1 Beatport ingest (admin → canonicalization)

| Item | Detail |
|---|---|
| Vendor / endpoint | Beatport `GET {base_url}/tracks/` (`beatport_client.py:55`), auth `Bearer {bp_token}` (`beatport_client.py:96`) |
| Trigger | `BeatportProvider.fetch_weekly_releases` (`providers/beatport.py:27`), built via registry `_build_beatport` (`providers/registry.py:31`) |
| Caching | None at the HTTP layer; results land in raw S3 + `source_entities`. No per-call cache table |
| Retry | `for attempt in range(self.max_retries + 1)` (`beatport_client.py:100`); 401/403 short-circuit (`beatport_client.py:132`) |
| Call-volume multiplier | **Paginated loop**: `while pages_fetched < max_pages` with `max_pages = 300`, `per_page=100` (`beatport_client.py:52,60,64`) — follows `payload["next"]` (`beatport_client.py:76`); raises `UpstreamUnavailableError` if the 300-page safety cap is exceeded (`beatport_client.py:84`). One weekly fetch = up to 300 Beatport calls per style_id |

### 3.2 Spotify ISRC search (canonicalization → SQS → worker)

| Item | Detail |
|---|---|
| Vendor / endpoint | Spotify Web API. Token: `POST https://accounts.spotify.com/api/token` Client-Credentials (`spotify_client.py:22,390`). Search: `GET https://api.spotify.com/v1/search` (`spotify_client.py:23,246,369`) |
| Trigger | After canonicalization, `_enqueue_spotify_search_after_canonicalization` sends `{"batch_size": 2000}` to `SPOTIFY_SEARCH_QUEUE_URL` (`worker_handler.py:135,185,197`). The `spotify_handler` SQS worker consumes it (`spotify_handler.py:83`), pulls tracks via `find_tracks_needing_spotify_search(limit=message.batch_size)` (`spotify_handler.py:182`) and calls `registry.get_lookup("spotify").lookup_batch_by_isrc` (`spotify_handler.py:199,212`) → `SpotifyLookup` (`providers/spotify/lookup.py:32`) → `SpotifyClient.search_tracks_by_isrc` (`spotify_client.py:58`) |
| Caching | Results persisted to S3 (`storage.write_spotify_results`, `spotify_handler.py:245`) and DB tables `source_entities` + `identity_map` + `clouder_tracks.spotify_id/searched_at` (`spotify_handler.py:300-343`). DB is the de-facto cache: `find_tracks_needing_spotify_search` only returns un-searched tracks. OAuth token cached in-process (`spotify_client.py:386,425-428`, refresh 60 s early) |
| Retry | `_request` loops `range(self.max_retries + 1)` with `max_retries=4` (`spotify_client.py:45,444`). 429 → respects `Retry-After`, **caps at `_MAX_RETRY_AFTER_SECONDS = 120`** and raises `SpotifyUnavailableError` above that so SQS visibility timeout becomes cool-down (`spotify_client.py:28,465-491`). Transient set `{408,429,500,502,503,504}` → exponential backoff w/ jitter (`spotify_client.py:21,493,510-513`). 401/403 → `SpotifyAuthError` triggers one token re-auth + retry (`spotify_client.py:108-113`). In the worker, `SpotifyAuthError`/`SpotifyUnavailableError` are non-permanent → message re-raised → SQS redrive (`spotify_handler.py:30,152-169`) |
| Call-volume multiplier | **Per-track cascade on ISRC miss.** Each track is 1 ISRC search (`_search_by_isrc`, `spotify_client.py:357`). On miss with `metadata_fallback_enabled`, adds up to **4 neighbour-ISRC searches** (`_isrc_neighbours` returns ±1/±2, `spotify_client.py:123,553-571`) **+ 1 metadata text search** (`_search_by_metadata`, `spotify_client.py:156,219`) → "5+ Spotify API calls per ISRC miss" per the code comment (`spotify_handler.py:32-36`). Batch is `batch_size=2000` enqueued, follow-up batches capped at `_MAX_FOLLOW_UP_BATCH_SIZE = 200` (`spotify_handler.py:36,374`). Self-perpetuating: `auto_continue` re-enqueues a follow-up while tracks remain (`spotify_handler.py:267,353-403`). Deadline guard aborts the loop when `remaining_ms < 60_000` (`spotify_client.py:85-98`) |

### 3.3 Vendor match — YT Music (track-add → SQS → worker)

| Item | Detail |
|---|---|
| Vendor / endpoint | YT Music via unauthenticated `ytmusicapi` `YTMusic().search(...)` (`providers/ytmusic/lookup.py:21-24,70`). No public ISRC endpoint, so ISRC fast-path is a no-op (`lookup.py:51-53`) |
| Trigger | Producer `enqueue_vendor_matches` sends one `VendorMatchMessage` **per track** to `VENDOR_MATCH_QUEUE_URL` (`vendor_match/enqueue.py:24,41,59`). Called best-effort from `_enqueue_ytmusic` after track-add/import (`curation_handler.py:388,410`, invoked at `curation_handler.py:924,1132`). Consumer `vendor_match_handler.lambda_handler` (`vendor_match_handler.py:28`) processes one message per record via `_process_one` (`vendor_match_handler.py:69`) |
| Caching | **`vendor_match` table**: `get_vendor_match` short-circuits on cache hit (`vendor_match_handler.py:79-87`); writes via `upsert_vendor_match` (`vendor_match_handler.py:105,145`). No-match → `mark_no_match`; ambiguous → `insert_review_candidate` stores top-5 (`vendor_match_handler.py:178,193`) |
| Retry | `_try_isrc` / `_try_metadata` wrapped in `@retry_vendor(max_retries=3)` (`vendor_match_handler.py:207,214`); full-jitter backoff on `VendorUnavailableError`/`VendorQuotaError`, `VendorQuotaError.retry_after` dominates (`vendor_match/retry.py:14,17,39-44`). Enqueue itself never propagates failures (`vendor_match/enqueue.py:58-65`) |
| Call-volume multiplier | One message **per added track** (`enqueue.py:41`). Inside `_process_one`, metadata lookup does **2 YT Music searches** — `songs` filter, then `videos` fallback if empty (`providers/ytmusic/lookup.py:64-67`), each `limit=10` (`lookup.py:18,70`). Scored against `fuzzy_match_threshold=0.92` (`vendor_match_handler.py:142`, `settings.py:184`). deezer/apple/tidal lookups are **stubs** that raise `VendorDisabledError` (`providers/{deezer,apple,tidal}/lookup.py`), so YT Music is the only live `vendor_match` vendor |

### 3.4 LLM enrichment — labels (admin/auto → SQS → worker)

| Item | Detail |
|---|---|
| Vendors / endpoints | **Gemini** `genai.Client(...).models.generate_content` with `google_search` tool (`vendors/gemini.py:82,99-113`); **OpenAI** `responses.parse` Responses API w/ `web_search` tool, `max_retries=0` (`vendors/openai_gpt.py:43-44,58-64`); **Tavily+DeepSeek** two-stage — `POST https://api.tavily.com/search` ×2 (general + social-domain pass), then DeepSeek `chat.completions.create` at `https://api.deepseek.com` (`vendors/tavily_deepseek.py:81-85,100,132,179`); **merge/narrative** DeepSeek `chat.completions.create` (`label_enrichment_handler.py:56`, `aggregator.py:345`) |
| Trigger (manual) | `POST` enrich → `handle_post_enrich`: creates one run, sends **one SQS message per label** to `LABEL_ENRICHMENT_QUEUE_URL` (`label_enrichment/routes.py:74,127,129-136`). Admin single-label button → `handle_post_enrich_auto` (`routes.py:141,175,179`) |
| Trigger (auto) | Block finalize enqueues a single `{block_id,user_id}` to `AUTO_ENRICH_DISPATCH_QUEUE_URL` (`curation/auto_enrich_dispatch.py:29`, `curation_handler.py:1534`); `auto_enrich_dispatch_handler` (`auto_enrich_dispatch_handler.py:19,26`) calls `try_dispatch_for_triage_block` → `_dispatch_labels` (`label_enrichment/auto_dispatch.py:57,155`). Single-track inline path `try_dispatch_for_track` (`auto_dispatch.py:145`, `curation_handler.py:724`). Dispatch `claim_labels` dedups (`auto_dispatch.py:73`), `create_run`, then `send_message_batch` in batches of `_SQS_BATCH = 10` (`auto_dispatch.py:24,106,121-123`) |
| Worker | `label_enrichment_handler.lambda_handler` — one label per record (`label_enrichment_handler.py:59,114`); builds adapters from run config (`label_enrichment_handler.py:106`, `orchestrator.py:159`), runs `enrich_label_for_run` (`orchestrator.py:73`) |
| Caching | Per-run cells in DB (`insert_cell`, `orchestrator.py:105`); merged result `upsert_label_info` + provenance (`orchestrator.py:120`). No idempotency on the LLM calls themselves — a re-run re-hits every vendor. `claim_labels` is the only dedup gate for auto-dispatch (`auto_dispatch.py:73`) |
| Retry | **Gemini**: in-adapter loop, up to 5 attempts on `RESOURCE_EXHAUSTED`/429/503/`UNAVAILABLE`, deadline `timeout_s*6`, backoff floor 10→60 s, parses Gemini's `retryDelay` (`vendors/gemini.py:104-137,51-61`). **OpenAI**: SDK retries disabled (`max_retries=0`) — comment: "the SQS/worker layer owns retry" (`vendors/openai_gpt.py:41-45`). **Tavily/DeepSeek**: no internal retry; errors captured into `VendorResponse.error`. Adapters **never raise** — all return error-bearing `VendorResponse` (`gemini.py:139`, `openai_gpt.py:65`, `tavily_deepseek.py:116`); `run_vendors_parallel` also catches (`orchestrator.py:59`). Worker has no try/except around `enrich_label_for_run`, so an unparseable SQS body skips (`label_enrichment_handler.py:87`) but other failures propagate → SQS redrive |
| Call-volume multiplier | **`labels × vendors` generate calls + 1 merge call per label.** `run_vendors_parallel` dispatches all adapters concurrently via `ThreadPoolExecutor(max_workers=len(adapters))`, exactly `len(adapters)` calls, one cell each (`orchestrator.py:34,44,89`). Then `merge_cells` adds **one DeepSeek narrative call per label** when ≥2 parseable cells (`aggregator.py:331,381,426,432`); 0 or 1 cells skip the merge call (`aggregator.py:392-424`). Tavily adapter alone is **3 upstream calls** (2 Tavily + 1 DeepSeek) per cell (`tavily_deepseek.py:100,132,179`). Default vendor set = gemini/openai/tavily_deepseek (`routes.py:337`). A 3-vendor run over N labels ≈ `N × (3 generate + 1 merge)` LLM calls, where the Tavily cell is internally 3 HTTP calls → ~`N × 6` upstream calls. Per-call timeout default 300 s (`settings.py:200`) |

### 3.5 LLM enrichment — artists (same shape as labels)

`artist_enrichment_handler.py` and `artist_enrichment/orchestrator.py` are a near-exact mirror of the label path, **reusing the same Gemini/OpenAI/Tavily+DeepSeek adapters** (`artist_enrichment/orchestrator.py:155-157`) and the **label** `merge_cells` aggregator (`orchestrator.py:8,113`). Trigger: `artist_enrichment/routes.py:119,166` (manual) and `artist_enrichment/auto_dispatch.py:101,118` via `try_dispatch_artists_for_triage_block` (called alongside labels in the same dispatch worker, `auto_enrich_dispatch_handler.py:27`). Queue `ARTIST_ENRICHMENT_QUEUE_URL` (`auto_dispatch.py:48`). Extra step vs labels: `derive_artist_context` runs first (`orchestrator.py:89`). Same multiplier: `artists × vendors generate + 1 merge per artist`, `_SQS_BATCH=10` (`auto_dispatch.py:21,116`). `SpotifyEnricher` (`providers/spotify/enrich.py`) is the only `EnrichProvider` in the registry but is **dead code** — "Currently NOT wired to any handler" (`enrich.py:5`).

### 3.6 Playlist publish / import (user-OAuth → API handler, synchronous)

| Item | Detail |
|---|---|
| Spotify publish | `SpotifyUserClient` (user-OAuth, distinct from the client-credentials `spotify_client.py`) `POST/PUT https://api.spotify.com/v1/...` (`curation/spotify_user_client.py:25,83,123,132`). Trigger `_handle_publish` (`curation_handler.py:1178`) → `PlaylistsPublishService.publish` (`playlists_publish_service.py:50`). Retry: 429 once respecting `Retry-After`, 5xx once, 401→`SpotifyNotAuthorizedError`, 403 scope→`SpotifyScopeInsufficientError` (`spotify_user_client.py:26-27,185-211`). Multiplier: 1 create/edit + **`replace_tracks(uris[:100])` then `append_tracks` per 100-URI chunk** (`playlists_publish_service.py:122-124`) → `ceil(tracks/100)` track-write calls + optional cover upload |
| Spotify import | `_handle_import_spotify` (`curation_handler.py:1063`) calls `sp_client.get_track(sid)` **once per submitted ref** in a loop (`curation_handler.py:1092-1094`, `spotify_user_client.py:66`). Then best-effort `_enqueue_ytmusic` fans newly-added tracks into the vendor-match queue (`curation_handler.py:1132`) — so import chains into family §3.3 |
| YT Music publish | `YtmusicPublishService.publish` (`ytmusic_publish_service.py:51`) via **YouTube Data API v3** `YoutubeDataApiClient` (`youtube_data_api_client.py:18,30`) — not ytmusicapi (broken for writes, `youtube_data_api_client.py:3-8`). Trigger `_handle_publish_ytmusic` (`curation_handler.py:1148`). Multiplier: **no bulk insert — one `playlistItems.insert` POST per video** (`youtube_data_api_client.py:90-102`), one `DELETE` per removed item (`remove_items`, `youtube_data_api_client.py:86-88`), and `get_existing_items` paginates `maxResults=50` (`youtube_data_api_client.py:72-83`). Incremental-sync diff added specifically to avoid `~100×N` quota per republish (`ytmusic_publish_service.py:120-134`, comment notes 50 quota units per insert/delete). Cover via `playlistImages.insert` is best-effort (`youtube_data_api_client.py:104`, `ytmusic_publish_service.py:138-149`) |
| Export provider stubs | `providers/{spotify,ytmusic,deezer,apple,tidal}/export.py` `create_playlist` all raise `VendorDisabledError` — the registry `ExportProvider` surface is **unused**; real publish goes through the `curation/*_publish_service.py` path above |

### Cross-cutting notes
- **Registry gates every lookup/ingest** behind `VENDORS_ENABLED` env var; disabled vendors raise `VendorDisabledError` and are never instantiated (`providers/registry.py:104-132`). Bundles are lazily built and cached in-process (`registry.py:97,111-123`).
- **Secrets**: enrichment API keys (`gemini/openai/tavily/deepseek`) loaded from worker settings (`settings.py:192-221`); Spotify client-credentials from `SpotifyWorkerSettings` (`registry.py:48`).
- **Largest fan-out risk**: auto-enrichment over a triage block — `label_ids_for_triage_block` + `artist_ids_for_triage_block` can each enqueue many items, each item then costing `vendors × (1 generate + 1 merge)` LLM calls with the Tavily adapter tripling its share (`auto_dispatch.py:155-162`, `aggregator.py:432`, `tavily_deepseek.py:100-179`). Block size is the uncapped multiplier; only `claim_labels`/`claim_artists` dedup limits re-dispatch.

---

## 4. Data-access layer

### 4.1 How SQL reaches Aurora

There is no ORM at runtime and no `psycopg`. Every runtime query goes through one thin client, `DataAPIClient` (`src/collector/data_api.py:14`), which calls the AWS RDS Data API via a boto3 `rds-data` client (`src/collector/data_api.py:113-119`). Repositories hold a `DataAPIClient` and pass raw SQL strings plus a `Mapping[str, Any]` of named parameters. `db_models.py` is **SQLAlchemy models used only as the Alembic schema source of truth** (`src/collector/db_models.py:1`); these classes are never queried at runtime — they exist so `alembic` can autogenerate migrations.

The four execution primitives on `DataAPIClient`:
- `execute(sql, params, transaction_id)` → `execute_statement`, returns parsed rows (`data_api.py:27-49`).
- `batch_execute(sql, parameter_sets, transaction_id)` → `batch_execute_statement`; **skips the call entirely when `parameterSets` is empty** (`data_api.py:51-72`).
- `begin_transaction()` → returns `transactionId` (`data_api.py:74-81`).
- `commit_transaction` / `rollback_transaction` (`data_api.py:83-97`).
- `transaction()` context manager (`data_api.py:99-107`).

Every request dict always carries `resourceArn`, `secretArn`, `database`; `execute` also sets `includeResultMetadata: True` (needed so `_to_rows` can name columns). The client is constructed from `get_data_api_settings()` and returns `None` when unconfigured (`repositories.py:1218-1228`).

### 4.2 Statement building and parameterization

**Parameters are always bound, never interpolated.** `params.items()` are converted to RDS Data API parameter objects by `_to_parameter` (`data_api.py:123-138`), which sets `typeHint` for `datetime`→`TIMESTAMP`, `date`→`DATE`, `dict`/`list`→`JSON`, `Decimal`→`DECIMAL`. Values are encoded by `_to_field` (`data_api.py:141-163`):
- `None`→`{isNull:True}`; `bool`→`booleanValue`; `int`→`longValue`; `float`→`doubleValue`.
- `Decimal`→stringValue of `str(value)` (`data_api.py:150-151`).
- `datetime`: tz-aware values are converted to UTC and **stripped of tzinfo**, then formatted `"%Y-%m-%d %H:%M:%S.%f"` (no `Z`/offset) because the Data API TIMESTAMP parser rejects a tz suffix (`data_api.py:152-156`) — a documented sharp edge.
- `date`→ISO string; `dict`/`list`→compact `json.dumps(..., ensure_ascii=False, separators=(",",":"))` (`data_api.py:159-162`).
- Fallback: `str(value)`.

**Result decoding.** `_to_rows` (`data_api.py:166-187`) zips `columnMetadata` names against each record; columns missing a name fall back to `col_{idx}`; extra fields beyond the column list are dropped. `_from_field` (`data_api.py:190-211`) returns the first of `stringValue/longValue/doubleValue/booleanValue`, recursively unwraps `arrayValue.arrayValues`, passes `blobValue` through, and returns `None` for `isNull` or unrecognized shapes. JSONB columns come back as raw `stringValue` (JSON text) unless the caller json-decodes — `get_vendor_match` guards `payload` with an `isinstance(..., dict)` check and coerces to `{}` (`repositories.py:1024-1026`), and re-wraps `confidence` via `Decimal(str(...))` and `matched_at` via `datetime.fromisoformat` when it arrives as a string (`repositories.py:1021-1033`).

**SQL strings are static literals** in the vast majority of call sites (38 `execute`/`batch_execute` calls in `repositories.py` alone). Dynamic SQL is built only by structural interpolation — never value interpolation:
- **`IN (...)` placeholder lists**: `placeholders = ", ".join(f":id_{i}" ...)` then `f"... IN ({placeholders})"`, with values supplied as bound params `{f"id_{i}": tid}`. In this file: `propagate_release_type_to_albums` (`repositories.py:846-861`).
- **Conditional WHERE fragments** appended for optional search: `find_tracks_not_found_on_spotify` (`repositories.py:761-781`), `count_tracks_not_found_on_spotify` (`repositories.py:783-799`), `list_tracks`/`count_tracks` (`repositories.py:866-905`), `list_artists`/`count_artists` (`repositories.py:907-935`), `list_albums`/`count_albums` (`repositories.py:937-968`), `list_styles`/`count_styles` (`repositories.py:970-998`). The fragment is a constant string literal (`"WHERE normalized_title LIKE :search"`); only the user's search term goes through `:search` as a bound param. These use `LIKE` with a Python-side `f"%{search.lower()}%"` and no `ESCAPE` clause, so `%`/`_` in user input act as wildcards (not an injection, but a correctness/footgun note).

Verified across the whole `src/collector` tree: no SQL f-string interpolates a user value — only placeholder names (`:t{i}`), VALUES-row tuples, and branch-selected constant fragments (`status_clause`, `count_clause`, `stale_clause`, `_SCOPE_CHECK_SQL_TEMPLATE`) are ever interpolated.

### 4.3 Transactions: where started/committed

The only transaction machinery lives in `data_api.py`. `begin_transaction` returns an id; the `transaction()` context manager (`data_api.py:99-107`) yields it, **commits on clean exit, rolls back and re-raises on any exception**. There is no nesting/savepoint support. `ClouderRepository.transaction()` just re-exposes `self._data_api.transaction()` (`repositories.py:1000-1001`).

Repository write methods accept an optional `transaction_id` that they thread straight into `execute`/`batch_execute` (e.g. `upsert_source_entity` `repositories.py:271-303`); when `None`, each statement auto-commits as its own implicit transaction on the Data API.

**Within `repositories.py`, no method opens a transaction itself** — callers do. The actual `with ...transaction()` orchestration sites (caller layer) are: `canonicalize.py:121,166,211,260,311,359`; `curation/categories_repository.py:76,350,423,626`; `curation/playlists_repository.py:216,416,506,549,864,1044,1068`; `curation/triage_repository.py:143,465,613`; `curation/tags_repository.py:323,362`. Multi-statement atomic units (canonicalization upserts, bucket moves, multi-row category/tag inserts) are wrapped; single-statement upserts generally run untransacted relying on `ON CONFLICT`.

### 4.4 Retry behavior and idempotency

`data_api_retry.py` provides two decorators, both implemented by `_retry` (`data_api_retry.py:77-111`): catch `ClientError`, look up `Error.Code`, and if it is in the allowed set and attempts remain, sleep and retry; otherwise re-raise. Backoff is exponential with **full jitter** — `cap = min(max_delay, base_delay*2^(attempt-1))`, `sleep = random.uniform(0, cap)` — defaults `max_attempts=5, base_delay=1.0, max_delay=30.0` (`data_api_retry.py:38-42, 95-98`). Each retry emits a `WARN` `data_api_retry` log event (`data_api_retry.py:99-106`). The sleep uses `time.sleep` (blocking, fine in Lambda).

Two code-set policies:
- **`retry_data_api()`** — broad set `TRANSIENT_ERROR_CODES` = `DatabaseResumingException, StatementTimeoutException, InternalServerErrorException, ServiceUnavailableError, ThrottlingException` (`data_api_retry.py:17-25`). Applied to `execute`, `batch_execute`, and `begin_transaction` (`data_api.py:27,51,74`). Note `DatabaseResumingException` is the Aurora-wakeup retry — see spend points.
- **`retry_data_api_pre_execution()`** — narrow set `PRE_EXECUTION_ERROR_CODES` = `DatabaseResumingException, ServiceUnavailableError, ThrottlingException` (`data_api_retry.py:27-33`), i.e. only codes meaning the request never hit the engine. Applied to `commit_transaction` and `rollback_transaction` (`data_api.py:83,91`), because re-issuing those after partial server-side completion could corrupt state.

**Idempotency contract (documented at `data_api_retry.py:43-56`):** the broad retry can re-run a statement that the server may have already partially applied (`StatementTimeoutException`, `InternalServerErrorException`). Callers must therefore make retried writes idempotent — either run them inside an explicit transaction (so a retried `execute(transaction_id=...)` replays atomically) or use UPSERT / `ON CONFLICT` semantics. In practice every write in `repositories.py` is idempotent by construction: inserts use `ON CONFLICT ... DO UPDATE` (source_entities `repositories.py:283`, source_relations `:358`, identity_map `:455`, vendor_track_map `:1051`, ingest_runs `:169`) or `ON CONFLICT ... DO NOTHING` (artist/label/style/album/track creates `:526,:549,:572,:600,:627`, track_artists `:703`); `mark_no_match`/`insert_review_candidate` rely on partial-unique-index `ON CONFLICT ... WHERE status=... DO NOTHING` (`:1158-1160,:1190-1192`); `set_run_completed`/`set_run_failed`/`conservative_update_track`/`batch_update_spotify_results` are `UPDATE ... WHERE id=...` which are naturally idempotent. A subtle gap: `batch_execute` is decorated with the broad retry but a partial `StatementTimeoutException` on a non-idempotent batch SQL would replay the whole batch — safe here only because all batch SQL is UPSERT/UPDATE.

### 4.5 Every raw-SQL construction site in `repositories.py`

`db_models.py`, `data_api.py`, and `data_api_retry.py` contain **no SQL strings** (models are declarative; client/retry are generic). All raw SQL in scope lives in `repositories.py`:

| Method | Kind | Lines | Conflict/idempotency |
|---|---|---|---|
| `create_ingest_run` | INSERT…ON CONFLICT DO UPDATE | `151-204` | `ON CONFLICT (run_id) DO UPDATE`, clears error/finished |
| `set_run_completed` | UPDATE | `206-225` | by `run_id` |
| `set_run_failed` | UPDATE | `227-257` | by `run_id`; truncates message to 2000, optional `[phase=…]` prefix |
| `get_run` | SELECT | `259-269` | — |
| `upsert_source_entity` | INSERT…ON CONFLICT DO UPDATE | `271-303` | key `(source,entity_type,external_id)` |
| `batch_upsert_source_entities` | batch INSERT…ON CONFLICT | `305-344` | same key |
| `upsert_source_relation` | INSERT…ON CONFLICT DO UPDATE | `346-374` | 6-col key |
| `batch_upsert_source_relations` | batch INSERT…ON CONFLICT | `376-411` | 6-col key |
| `find_identity` | SELECT | `413-441` | — |
| `upsert_identity` | INSERT…ON CONFLICT DO UPDATE | `443-473` | key `(source,entity_type,external_id)` |
| `batch_upsert_identities` | batch INSERT…ON CONFLICT | `475-512` | same |
| `create_artist` | INSERT…ON CONFLICT DO NOTHING | `514-535` | by `id` |
| `create_label` | INSERT…ON CONFLICT DO NOTHING | `537-558` | by `id` |
| `create_style` | INSERT…ON CONFLICT DO NOTHING | `560-581` | by `id` |
| `create_album` | INSERT…ON CONFLICT DO NOTHING | `583-611` | by `id` |
| `create_track` | INSERT…ON CONFLICT DO NOTHING | `613-645` | by `id` |
| `conservative_update_track` | UPDATE w/ COALESCE & CASE | `647-694` | by `id`; null-preserving merge |
| `upsert_track_artist` | INSERT…ON CONFLICT DO NOTHING | `696-711` | 3-col key |
| `batch_upsert_track_artists` | batch INSERT…ON CONFLICT | `713-735` | 3-col key |
| `find_tracks_needing_spotify_search` | SELECT + JOIN + GROUP BY | `739-755` | — |
| `find_tracks_not_found_on_spotify` | **dynamic** SELECT (`{where_extra}`) | `757-781` | f-string + `:search` LIKE |
| `count_tracks_not_found_on_spotify` | **dynamic** SELECT count | `783-800` | f-string + `:search` |
| `batch_update_spotify_results` | batch UPDATE | `802-832` | by `id`, COALESCE-merges release fields |
| `propagate_release_type_to_albums` | **dynamic** UPDATE…FROM (`{placeholders}` IN-list) | `834-862` | bound `:id_{i}` params |
| `list_tracks` | **dynamic** SELECT (`{where}`) | `866-894` | — |
| `count_tracks` | **dynamic** SELECT count | `896-905` | — |
| `list_artists` / `count_artists` | **dynamic** SELECT | `907-935` | — |
| `list_albums` / `count_albums` | **dynamic** SELECT | `937-968` | — |
| `list_styles` / `count_styles` | **dynamic** SELECT | `970-998` | — |
| `get_vendor_match` | SELECT | `1003-1035` | decodes payload/confidence/matched_at |
| `upsert_vendor_match` | INSERT…ON CONFLICT DO UPDATE | `1037-1068` | key `(clouder_track_id,vendor)` |
| `coverage_for_year` | SELECT + LATERAL + NOT EXISTS | `1070-1116` | latest-run-per-cell matrix |
| `list_runs_for_cell` | SELECT | `1118-1139` | — |
| `insert_review_candidate` | INSERT…ON CONFLICT(partial idx) DO NOTHING | `1141-1170` | `WHERE status='pending'` |
| `mark_no_match` | INSERT…ON CONFLICT(partial idx) DO NOTHING | `1172-1202` | `WHERE status='no_match'`, generates `uuid4()` id |

Helpers: `parse_iso_date` (`repositories.py:1205-1211`), `utc_now` (`:1214-1215`), env factory `create_clouder_repository_from_env` (`:1218-1228`).

### 4.6 Beyond `repositories.py` (same data-access path)

`repositories.py` is only the ingest-side repository. The Data API client is shared by parallel repositories that build SQL the same way (static literals + structural-only f-strings): `curation/playlists_repository.py` (39 calls), `curation/triage_repository.py` (33), `curation/categories_repository.py` (24), `curation/tags_repository.py` (15), `artist_enrichment/repository.py` (28) + `auto_repository.py` (8), `label_enrichment/repository.py` (27) + `auto_repository.py` (8), `auth/auth_repository.py` (12), and the token resolvers/publish service. Their dynamic-SQL sites use the identical `", ".join(f":t{i}" …)` placeholder and multi-row `VALUES {", ".join(value_rows)}` patterns with all values bound (e.g. `triage_repository.py:475-491`, `categories_repository.py:544-564`), confirming the parameterization discipline is uniform across the codebase. These repos also own the `with self._data_api.transaction()` blocks enumerated in §4.3.

---

## 5. Infrastructure

All Terraform under `infra/`. Resource name prefix is `beatport-prod-*` (`local.name_prefix = "${var.project}-${var.environment}"`, defaults `beatport` + `prod`, `main.tf:2`, `variables.tf:1-11`). Region default `us-east-1` (`variables.tf:13-17`). Provider AWS `~> 5.0`, S3 backend, default tags `Project/Environment/ManagedBy=terraform` (`providers.tf:4-28`).

### 5.1 Lambdas

All functions are `python3.12`, packaged from one zip (`dist/collector.zip`, `variables.tf:49-53`), and all but `auth_authorizer` share the single IAM role `aws_iam_role.collector_lambda` (`iam.tf:14`).

| Function | file:line | Memory (MB) | Timeout (s) | Reserved concurrency | Trigger / notes |
|---|---|---|---|---|---|
| collector (API) | `lambda.tf:1-34` | 512 (`variables.tf:37-41`) | 120 (`variables.tf:31-35`) | none | API GW proxy. No VPC config |
| canonicalization_worker | `lambda.tf:36-62` | 1024 (`variables.tf:91-95`) | 900 (`variables.tf:85-89`) | none | SQS ESM batch_size 1 (`lambda.tf:97-101`, `variables.tf:79-83`) |
| db_migration | `lambda.tf:64-95` | 1024 (`variables.tf:103-107`) | 900 (`variables.tf:97-101`) | none | **Only VPC-attached Lambda** (`lambda.tf:75-78`); subnets db_a/db_b + `migration_lambda` SG |
| spotify_search_worker | `lambda.tf:105-138` | 512 (`variables.tf:200-204`) | 900 (`variables.tf:194-198`) | 3, gated by `enable_lambda_reserved_concurrency` else -1 (`lambda.tf:114`, `variables.tf:212-216`) | SQS ESM batch_size 1 (`lambda.tf:140-144`) |
| vendor_match_worker | `lambda.tf:148-179` | 512 (`variables.tf:274-278`) | 120 (`variables.tf:268-272`) | 2, gated (`lambda.tf:157`, `variables.tf:286-290`) | SQS ESM batch_size 1, `enabled = var.vendor_match_enabled` (default false) (`lambda.tf:181-186`, `variables.tf:262-266`) |
| label_enricher_worker | `lambda.tf:190-221` | 1024 (`variables.tf:461-465`) | 900 (`variables.tf:455-459`) | 10, gated (`lambda.tf:199`, `variables.tf:467-471`) | SQS ESM batch_size 1 + `scaling_config.maximum_concurrency = 8` (`lambda.tf:223-235`, `variables.tf:479-488`) |
| artist_enricher_worker | `lambda.tf:239-270` | 1024 (`variables.tf:514-518`) | 900 (`variables.tf:508-512`) | 10, gated (`lambda.tf:248`, `variables.tf:520-524`) | SQS ESM batch_size 1 + `maximum_concurrency = 8` (`lambda.tf:272-284`, `variables.tf:532-541`) |
| auto_enrich_dispatch_worker | `lambda.tf:288-313` | 512 (`variables.tf:597-601`) | 300 (`variables.tf:591-595`) | none | SQS ESM batch_size 1 + `maximum_concurrency = 2` (`lambda.tf:315-323`, `variables.tf:609-618`) |
| auth_handler | `auth.tf:42-74` | 512 (`variables.tf:395-399`) | 30 (`variables.tf:389-393`) | none | Public + JWT routes; reuses collector role |
| auth_authorizer | `auth.tf:112-131` | 256 (`variables.tf:407-411`) | 5 (`variables.tf:401-405`) | none | **Own narrow role** `aws_iam_role.auth_authorizer` (`auth.tf:78`); API GW REQUEST authorizer, cache TTL 300s (`auth.tf:156-165`, `variables.tf:413-417`) |
| curation | `curation.tf:6-39` | 512 (`variables.tf:425-429`) | 30 (`variables.tf:419-423`) | none | 10 curation routes, all JWT-gated (`curation.tf:58-82`); reuses collector role |

Notes / risks:
- **No Lambda has a `dead_letter_config`** on the function itself; failure handling is the SQS redrive only (async paths). API/auth/curation Lambdas have no async failure target.
- Reserved concurrency is **disabled by default** (`enable_lambda_reserved_concurrency` default false, `variables.tf:292-296`) because new-account ConcurrentExecutions quota is 10; workers fall back to SQS `maximum_concurrency` caps which don't reserve from the account pool.
- `LOG_LEVEL=INFO` hard-coded in every function's env (e.g. `lambda.tf:26`). `bp_token` never appears in any env var (consistent with policy).
- Sensitive values are referenced via SSM parameter **names**/secret ARNs in env, not the secrets themselves (e.g. `auth.tf:59-64`, `lambda.tf:120-122`).

### 5.2 Queues (SQS)

Every worker queue has a paired DLQ + `redrive_policy`. Visibility timeout is computed `max(var.<queue>_visibility_timeout, worker_lambda_timeout)` so a message can't reappear mid-processing (`sqs.tf:8-11` etc.). DLQs themselves have **no redrive policy** (terminal) and only `message_retention_seconds`.

| Queue | file:line | maxReceiveCount | Visibility (effective) | Retention (s) |
|---|---|---|---|---|
| canonicalization | `sqs.tf:6-18` | **5** (hardcoded, `sqs.tf:16`) | max(180, 900)=900 | 1209600 (14d) (`variables.tf:73-77`) |
| spotify_search | `sqs.tf:27-39` | **3** (hardcoded, `sqs.tf:37`) | max(960, 900)=960 (`variables.tf:218-222`) | 1209600 (14d) |
| vendor_match | `sqs.tf:48-60` | 5 (`variables.tf:310-314`) | max(180, 120)=180 | 1209600 (14d) |
| label_enrichment | `sqs.tf:69-81` | 3 (`variables.tf:449-453`) | max(1000, 900)=1000 | 345600 (4d) (`variables.tf:443-447`) |
| artist_enrichment | `sqs.tf:90-102` | 3 (`variables.tf:502-506`) | max(1000, 900)=1000 | 345600 (4d) |
| auto_enrich_dispatch | `sqs.tf:111-123` | 3 (`variables.tf:585-589`) | max(360, 300)=360 | 86400 (1d) (`variables.tf:579-583`) |

DLQ retention mirrors each queue's retention var (e.g. `sqs.tf:1-4` canonicalization DLQ = 14d). `canonicalization` and `spotify_search` use **hardcoded** maxReceiveCount (5 / 3) while the rest are variable-driven — inconsistency.

### 5.3 Aurora (`rds.tf`)

- Engine `aurora-postgresql` v `16.11` (`rds.tf:3-4`, `variables.tf:115-119`); DB `clouder`, master user `clouder_admin` (`variables.tf:109-125`).
- **Serverless v2**: min ACU **0** (auto-pause), max ACU **2**, `seconds_until_auto_pause = 300` (`rds.tf:21-25`, `variables.tf:127-143`). min_acu=0 is the documented cold-start-503 source (ADR-0014). Single writer instance `db.serverless`, `publicly_accessible = false` (`rds.tf:28-35`).
- `enable_http_endpoint = true` → RDS Data API (`rds.tf:14`). `storage_encrypted = true` (`rds.tf:15`). `iam_database_authentication_enabled = true` (`rds.tf:9`). `manage_master_user_password = true` → Secrets Manager managed secret (`rds.tf:8`).
- **`deletion_protection = false` and `skip_final_snapshot = true`** (`rds.tf:18-19`) — destroy leaves no final snapshot and is not blocked. `copy_tags_to_snapshot = true` (`rds.tf:16`). **No `backup_retention_period` / `preferred_backup_window` set** → relies on AWS default (1 day automated backups); no explicit backup config.

### 5.4 S3 buckets

**raw bucket** (`s3.tf:1-3`, name `beatport-prod-raw-<acct>` or override `variables.tf:55-59`):
- Versioning Enabled (`s3.tf:5-11`); SSE-S3 AES256 (`s3.tf:13-21`).
- Public access fully blocked — all four flags true (`s3.tf:23-30`).
- CORS allows PUT/GET/HEAD from CloudFront domain + localhost:5173 for presigned cover uploads (`s3.tf:36-50`).
- **No lifecycle configuration** — raw + cover objects (and all versions, since versioning is on) accumulate indefinitely. Cost/retention risk.

**frontend bucket** (`frontend.tf:4-6`, `beatport-prod-frontend`):
- Public access fully blocked (`frontend.tf:8-14`); served only via CloudFront OAC (`frontend.tf:16-21`), bucket policy restricts `s3:GetObject` to the CloudFront service principal scoped by `AWS:SourceArn` (`frontend.tf:88-101`).
- **No versioning, no SSE config, no lifecycle** on the frontend bucket.

CloudFront (`frontend.tf:150-238`): default cert (no custom domain), `PriceClass_100`, TLS1.2_2021 min, two CF Functions (spa_router rewrite, spa_html_fallback 302). API GW origin is `https-only`. `geo_restriction = none` (`frontend.tf:233-237`).

### 5.5 IAM

Two roles. Both assume via `lambda.amazonaws.com` only (`iam.tf:1-12`).

**`collector_lambda`** (shared by 9 Lambdas) — inline policy `data.aws_iam_policy_document.collector_lambda` (`iam.tf:19-240`):
- Logs scoped to the explicit log-group ARNs (`iam.tf:20-38`).
- S3 PutObject/GetObject/HeadObject scoped to `raw/`, `spotify_raw/`, `covers/*` prefixes; ListBucket scoped with `s3:prefix` condition (`iam.tf:40-79`). Well-scoped.
- SQS SendMessage and Receive/Delete/ChangeVisibility scoped to the six queue ARNs (`iam.tf:81-117`).
- RDS Data API actions scoped to the cluster ARN (`iam.tf:119-130`).
- `secretsmanager:GetSecretValue` on the master secret — **but resource falls back to `"*"` via `try(...,"*")`** if the managed secret isn't resolvable (`iam.tf:132-139`). Wildcard-on-fallback flag.
- External-API secret read scoped to `spotify_credentials_secret_arn` (conditional) (`iam.tf:141-151`).
- SSM `GetParameter` scoped to constructed parameter ARNs for spotify/ytmusic/gemini/openai/tavily/deepseek (`iam.tf:153-179`).
- `kms:Decrypt` for SSM scoped to `alias/aws/ssm` (`iam.tf:181-198`); `kms:GenerateDataKey`+`Decrypt` scoped to the user_tokens CMK (`iam.tf:200-208`).
- SSM read for JWT signing key scoped to its ARN (`iam.tf:210-217`).
- `rds-db:connect` scoped to the migration dbuser ARN (`iam.tf:219-226`).
- **VPC networking block: `resources = ["*"]` wildcard** for `ec2:CreateNetworkInterface`/`DescribeNetworkInterfaces`/`DeleteNetworkInterface`/`Assign`/`Unassign` (`iam.tf:228-239`). EC2 ENI actions don't support resource-level scoping, so `*` is expected, but it is granted to **all 9 Lambdas** when only db_migration is VPC-attached — broader than needed.

**`auth_authorizer`** (`auth.tf:78-110`) — minimal: logs to its own group, SSM GetParameter for the JWT key only, KMS Decrypt for `alias/aws/ssm`. Properly least-privilege.

Flags: the `secretsmanager` `"*"` fallback (`iam.tf:138`) and the shared role granting the broad EC2/secrets/SSM surface to all non-VPC Lambdas are the main over-grants. No `Action: "*"` or `Resource: "*"` admin-style statements.

### 5.6 Alarms (`alarms.tf`) + DLQ alarms (`logging.tf`)

- **Lambda Errors** alarm per function for the 8 functions in `local.all_lambdas` (4 api + 4 worker; **artist_enricher and auto_enrich_dispatch are NOT in the map** — no error alarm, `alarms.tf:14-22`). Threshold ≥1 error / 5min, `treat_missing_data = notBreaching` (so a fully-dead, zero-invocation Lambda won't fire — called out in the comment `alarms.tf:24-28`) (`alarms.tf:29-49`).
- **Duration p95** alarm only on the 4 api_lambdas, threshold 20000ms (9s buffer to API GW 29s) (`alarms.tf:51-74`).
- **label_enricher Throttles** alarm only created when `enable_lambda_reserved_concurrency` is true (`count`, `alarms.tf:80-100`).
- **Aurora ACU near-max** alarm at 90% of `max_acu` (=1.8 ACU) (`alarms.tf:103-121`).
- **DLQ depth** alarm per DLQ for all six DLQs, fires on >0 visible messages (`logging.tf:58-90`).
- All alarms route to `var.alarm_sns_topic_arn`, which **defaults to `""` → no alarm_actions/ok_actions wired** unless supplied (`variables.tf:230-234`; e.g. `alarms.tf:47-48`). Alarms exist but page nobody by default.

### 5.7 Logging (`logging.tf:1-54`)

11 explicit CloudWatch log groups (`/aws/lambda/<name>`), each `retention_in_days = var.log_retention_days`, default **30 days** (`variables.tf:43-47`). Covers all functions incl. artist_enricher and auto_enrich_dispatch.

### 5.8 Network topology (`network.tf`)

- VPC `10.60.0.0/16`, DNS support + hostnames on (`network.tf:5-9`, `variables.tf:145-149`).
- **Two private subnets only**: db_a (`10.60.1.0/24`, AZ[0]) and db_b (`10.60.2.0/24`, AZ[1]), both `map_public_ip_on_launch = false` (`network.tf:11-23`). DB subnet group spans both (`network.tf:25-28`).
- **No public subnets, no Internet Gateway, no NAT Gateway, no EIP, no route tables** anywhere in infra. The VPC uses the default route table with no internet egress. Egress for the VPC-attached migration Lambda to Secrets Manager is provided **only** by an optional Secrets Manager **interface VPC endpoint** (`enable_secretsmanager_vpc_endpoint`, default false) (`network.tf:64-93`, `variables.tf:163-167`). With that flag off, a VPC-attached migration Lambda using `password` auth mode (needs Secrets Manager) has **no path to reach it** — implicit operational dependency.
- Most Lambdas run **outside the VPC** (no `vpc_config`) and reach Aurora via the public Data API endpoint — that's why no NAT is needed for normal runtime.
- Security groups: `aurora` SG (egress all, ingress only via rule from migration_lambda SG on tcp/5432) (`network.tf:30-41`, `network.tf:56-62`); `migration_lambda` SG (egress all) (`network.tf:43-54`); optional `vpc_endpoints` SG ingress 443 from migration SG (`network.tf:64-83`). Aurora SG has **no ingress for non-VPC Lambdas** — fine because they use the Data API, not TCP.

### 5.9 Other

- **KMS CMK** `user_tokens` for `user_vendor_tokens` envelope encryption: `enable_key_rotation = true`, `deletion_window_in_days = 30` (`auth.tf:3-12`).
- **JWT signing key**: `random_password` (64 chars) written to SSM SecureString with `lifecycle.ignore_changes = [value]` (`auth.tf:16-30`).
- API Gateway HTTP API `$default` stage, `auto_deploy = true` (`api_gateway.tf:201-205`); CORS only configured when `cors_allowed_origins` non-empty (default empty → CORS off at API GW, handled at CloudFront instead) (`api_gateway.tf:5-15`, `variables.tf:431-435`). All non-auth routes are JWT-gated via the custom authorizer.

---

## 6. Frontend

CLOUDER's SPA is `frontend/src` — Vite + React 19 + Mantine 9 + TanStack Query 5 + React Router (data-router/`createBrowserRouter`). Entry is `main.tsx`, which wraps `RouterProvider` in `MantineProvider` → `ModalsProvider` → `Notifications` → `QueryClientProvider` → `AuthProvider` (main.tsx:23-36). Provider order matters: `AuthProvider` is inside `QueryClientProvider` (so hooks can use the client) but the router's loaders read auth via a singleton snapshot, not context (see Auth gating below).

### 6.1 API client (`api/`)

- **Single fetch wrapper** `api<T>()` in `api/client.ts:48-79`. Base URL is `window.location.origin` (client.ts:5-6) — the SPA is served same-origin with the API, so `VITE_API_BASE_URL`/`lib/env.ts` is **defined but unused by the runtime client** (`parseEnv` is only referenced in `lib/__tests__/env.test.ts`; the only non-test reference to the env var is the type decl `vite-env.d.ts:4`). Discrepancy worth flagging: CLAUDE.md gotcha #9 and the dev-setup instructions assume `VITE_API_BASE_URL` drives requests, but `api/client.ts` ignores it entirely.
- Sets `Accept: application/json` always, `Authorization: Bearer <token>` from `tokenStore.get()` when present, and `Content-Type: application/json` only when a body exists (client.ts:51-54). All requests send `credentials: 'include'` (client.ts:56) — required for the refresh cookie.
- **204 handling**: returns `undefined as T` on 204 (client.ts:69, 77).
- **Error normalization** in `api/error.ts`. `ApiError.from(res)` (error.ts:13-44) reads `x-correlation-id` header, parses JSON body, and maps:
  - `{error_code, message, correlation_id}` → `ApiError(error_code, status, …)` (error.ts:22-31). Canonical backend error envelope; `error_code` becomes `ApiError.code`.
  - 503 with body `{message:"Service Unavailable"}` → synthetic `ApiError('cold_start', 503, 'Backend warming up')` (error.ts:33-41) — the Aurora cold-start path (CLAUDE.md gotcha #7).
  - Fallthrough → `ApiError('unknown', status, statusText)` (error.ts:43).

### 6.2 401 / refresh / 503 handling

- **Silent 401 retry** lives in the client (client.ts:58-74). On `401` *and only if a token was present*, it calls `tryRefreshOnce()` (client.ts:17-40): a module-level `inflightRefresh` promise dedupes concurrent refreshes, POSTs `/auth/refresh` with `credentials:'include'`, stores the new `access_token`/`spotify_access_token`, dispatches a `window` `auth:refreshed` CustomEvent, then the original request is retried once with the fresh token (client.ts:60-70). If refresh fails, `notifyAuthFailure()` clears both token stores and dispatches `auth:expired` (client.ts:42-46, 72).
- **Cross-layer event bus**: client.ts dispatches DOM CustomEvents (`auth:refreshed`, `auth:expired`); `AuthProvider` listens for both (AuthProvider.tsx:215-256). This is the seam connecting the imperative fetch layer to React state. Note `AuthProvider.refresh()` (AuthProvider.tsx:156-174) *also* calls `api('/auth/refresh')` itself and re-fetches `/me` — so there are **two refresh paths** (the client's silent retry, and AuthProvider's scheduled/bootstrap refresh) that can race; the `inflightRefresh` dedupe only covers the client path, not AuthProvider's own POST.
- **503 / cold-start UX** is per-feature, not centralized:
  - `useCreateTriageBlock.ts:92-111` catches 503/`cold_start` → `PendingCreateError`, schedules background recovery via `schedulePendingCreateRecovery` (`lib/pendingCreateRecovery.ts`) — the create may have actually succeeded server-side, so it polls the list tabs.
  - `FinalizeModal.tsx:108,291` and `pendingFinalizeRecovery.ts` do the equivalent for finalize (relevant to the triage-finalize async dispatch in PR #183).
  - `useCurateSession.ts:379,386` shows a yellow `service_unavailable` toast on 503.
  - `components/LongOperationOverlay.tsx:17` shows a `cold_start` copy overlay for slow operations.
- **TanStack retry policy** (`lib/queryClient.ts:8-17`): queries retry up to 2× *except* `forbidden`/`not_found` codes; `staleTime` 30s; `refetchOnWindowFocus:false`; mutations never retry. 503/`cold_start` queries DO retry (not in the no-retry list).

### 6.3 Auth & token storage (`auth/`)

- **Tokens live in memory only.** `auth/tokenStore.ts` and `auth/spotifyTokenStore.ts` are identical module-level `let token` closures with `get`/`set` (tokenStore.ts:1-10, spotifyTokenStore.ts:1-10). **Nothing writes the access token or spotify token to localStorage, sessionStorage, or cookies** — verified by grep: the only persisted token-ish value is the *device id* (`lastDeviceStore`), never a credential. No `console.log`/structlog of tokens either. This satisfies CLAUDE.md gotcha #5 / the "bp_token never persisted" memory.
- **`bp_token`** (Beatport ingest token) is held in `features/admin/lib/bpTokenStore.ts` — a `useSyncExternalStore`-backed in-memory store (bpTokenStore.ts:1-33), entered via a `PasswordInput` (`BpTokenInput.tsx:19-25`, `autoComplete="off"`) and passed straight into the ingest POST body (`IngestForm.tsx:47` → `useStartIngest.ts:9,26`). Never persisted; cleared via `bpTokenStore.clear()` (BpTokenInput.tsx:12).
- **AuthProvider** (`auth/AuthProvider.tsx`) is a `useReducer` state machine: `idle | loading | authenticated | unauthenticated | error` (AuthProvider.tsx:40-50). Key mechanisms:
  - **Singleton snapshot** `snapshot`/`getAuthSnapshot()` (AuthProvider.tsx:81-84) mirrors state for non-React readers (the router loaders). `signIn` updates the snapshot *synchronously* before dispatch (AuthProvider.tsx:149) to avoid a race where `requireAuth` reads a stale `loading` snapshot and bounces a just-authenticated user to `/login` (comment AuthProvider.tsx:145-148).
  - **Bootstrap-once guard** `bootstrapStarted` ref (AuthProvider.tsx:115, 196-197) prevents StrictMode's double-mount from firing two `/auth/refresh` calls — which would trip backend refresh-token replay detection and revoke ALL sessions (CLAUDE.md gotcha #10, ADR-0015; comment AuthProvider.tsx:109-114).
  - **Proactive refresh scheduling**: `scheduleRefresh` sets a timer for `expiresIn - 5min` (`REFRESH_LEEWAY_MS`, AuthProvider.tsx:100, 129-138) via a `refreshRef` forward-ref to break a `signIn`↔`refresh`↔`scheduleRefresh` dependency cycle (AuthProvider.tsx:105-108).
  - **`signOut`** POSTs `/auth/logout`, swallows errors, clears both token stores, clears timer, sets unauthenticated (AuthProvider.tsx:181-192).
- **Bootstrap gating** (`auth/bootstrap.ts`): a module-level promise resolved by `completeBootstrap()` (bootstrap.ts:1-15). `AuthProvider`'s mount effect calls bootstrap-refresh then `completeBootstrap()` (AuthProvider.tsx:200-207). Route loaders `requireAuth`/`redirectIfAuthenticated` (`auth/requireAuth.ts:5-17`) and `requireAdmin` (`auth/requireAdmin.ts:5-11`) `await bootstrapPromise()` then read `getAuthSnapshot()` and `throw redirect(...)`. So **route protection is loader-based off the singleton snapshot**, decoupled from React context — `useAuth()` (`auth/useAuth.ts`) is only for components. `requireAdmin` redirects to `/` unless `user.is_admin`; `is_admin` originates from the access-token claim surfaced via `/me`.
- **OAuth return** (`routes/auth.return.tsx`): exchanges `?code&state` at `/auth/callback`, calls `signIn`, navigates to `/`. Guards the single-use `code` against StrictMode double-fetch with an `exchanged` ref (auth.return.tsx:37,44-45) — deliberately *no* `cancelled` flag (comment auth.return.tsx:47-54). Maps `account_error` → premium-required copy (auth.return.tsx:63-67). `routes/login.tsx` reads `?error=premium_required` for a banner and links to `/auth/login` via `window.location.href` (login.tsx:11-18).

### 6.4 Route structure (`routes/router.tsx`)

Flat declaration in `routes/router.tsx:41-136`:
- Public: `/login` (loader `redirectIfAuthenticated`), `/auth/return` (no loader — must be reachable mid-auth).
- Protected tree under `<AppShellLayout>` with `loader: requireAuth` and `errorElement: <RouteErrorBoundary/>` (router.tsx:53-57). Children: `/` index → `HomePage`; `categories/:styleId(/:id)` (+ nested `player`), index → `CategoriesIndexRedirect`; `triage/:styleId(/:id(/buckets/:bucketId))` (+ `player`), index → `TriageIndexRedirect`; `curate/:styleId` (resume), `curate/:styleId/:blockId/:bucketId` (session), index → `CurateIndexRedirect`; `library/:styleId(/artists)` plus top-level `artists/:artistId`, `labels/:labelId`; `playlists(/:id)` (+ `player`); `profile`; `admin` with its own `loader: requireAdmin` and `<AdminLayout>`, children `coverage`, `spotify-not-found`, `labels/enrich(/runs(/:runId))`, `artists/enrich(/runs(/:runId))`, `auto-enrich`; index redirects to `/admin/coverage` (router.tsx:117-132).
- Catch-all `*` → `NotFoundPage` (router.tsx:135).
- **Index redirects** (`*IndexRedirect.tsx`) resolve a default `:styleId` from `useStyles()` + a last-visited localStorage value (e.g. `CategoriesIndexRedirect.tsx:21-24`, `TriageIndexRedirect.tsx:30-33`, `CurateIndexRedirect.tsx:13-16`). The `:player` nested routes render a player panel inside the parent detail page's `<Outlet>`.
- **`RouteErrorBoundary`** (`components/RouteErrorBoundary.tsx`) renders router error responses, `ApiError` (shows status code + message + `correlationId` as `<Code>`), or generic `Error` (RouteErrorBoundary.tsx:15-24).
- **AppShell** (`routes/_layout.tsx`) wraps everything in `<PlaybackProvider>` (so playback state spans all protected routes), renders desktop navbar / mobile footer nav from `NAV_ITEMS` (+ conditional `/admin` when `is_admin`, _layout.tsx:54-62), mounts `DevicePickerSurface` as global chrome (_layout.tsx:153-158). Reads admin status directly from `AuthContext` (_layout.tsx:53-55).

### 6.5 Curation / triage / playback feature surfaces (`features/`)

Feature-sliced: each `features/<x>/` has `routes/`, `components/`, `hooks/` (TanStack query/mutation wrappers), `lib/` (pure helpers + schemas).

- **Curate** (`features/curate/`): `hooks/useCurateSession.ts` is a ~640-line `useReducer` session engine driving tap-to-assign curation. It composes `useTriageBlock` + `useBucketTracks` (infinite query) + `useMoveTracks`, binds the queue into `PlaybackProvider` via `bindQueue` (useCurateSession.ts:299-306), prefetches pages when the queue drains below `QUEUE_REFILL_THRESHOLD=40` (useCurateSession.ts:199, 252-265), has a 200ms `PENDING_ADVANCE_MS` debounce window allowing same-destination re-tap and "replace" with imperative rollback (assign useCurateSession.ts:436-535; undo useCurateSession.ts:537-586). Error toasts map specific codes (`tracks_not_in_source`, `block_not_editable`, `triage_block_not_found`, `target_bucket_inactive`, 503) to i18n keys (useCurateSession.ts:374-391). "Force" mode (useCurateSession.ts:445-448) additionally adds to a category via `useAddTrackToCategory`, with partial-failure toast and undo (useCurateSession.ts:407-421, 546-561).
- **Triage** (`features/triage/`): pages `TriageListPage`, `TriageDetailPage`, `BucketDetailPage`, `BucketPlayerPage`. Mutations: `useMoveTracks` (optimistic), `useTransferTracks`, `useCreateTriageBlock`, `useFinalizeTriageBlock`, `useDeleteTriageBlock`, `useBucketDistribute`. `useFinalizeTriageBlock.ts:48-73` does a broad invalidation fan-out (block, all byStyle status tabs, categories list, per-promoted-category detail+tracks via predicate). Finalize/create both have **async-dispatch cold-start recovery** (`lib/pendingFinalizeRecovery.ts`, `lib/pendingCreateRecovery.ts`) — tied to the "triage-finalize fan-out now async via dispatch worker (PR #183)" + "silent Lambda failures" memory: the client cannot rely on a synchronous response, so it polls.
- **Playback** (`features/playback/`): `PlaybackProvider.tsx` (~735 lines) owns the Spotify Web Playback SDK + Connect device management. The Spotify token is read lazily from `spotifyTokenStore` in the SDK's `getOAuthToken` callback (PlaybackProvider.tsx:176-181) and in every `spotifyWebApi.ts` call (spotifyWebApi.ts:31). Direct Spotify Web API calls go to `https://api.spotify.com` (`api/spotifyWebApi.ts:4`) with their own 401→`onAuthExpired()`→retry-once logic (spotifyWebApi.ts:48-59), where `onAuthExpired` is wired to `AuthProvider.refresh` (PlaybackProvider.tsx:112-114). On SDK `authentication_error` it calls `refresh()`; on `account_error` it navigates to `/auth/premium-required` (PlaybackProvider.tsx:312-319) — **note that route is not registered in router.tsx**, so this navigation hits the `*` NotFoundPage (a likely bug). Devices polled via `usePolling` at 30s (picker closed) / 5s (open) (PlaybackProvider.tsx:655-660). `lastDeviceStore` (`lib/lastDeviceStore.ts`) is the only credential-adjacent localStorage writer and stores only a device id, guarded against quota/private-mode throws.
- **Playlists** (`features/playlists/`): `PlaylistDetailPage` (with nested `player`), publish flows (`usePublishPlaylist`, `usePublishYtmusic.ts`, YtMusic connect via device-flow in `useYtmusicConnect.ts` — `/auth/ytmusic/device-code` + poll). Drag reorder debounced 200ms (`useReorderPlaylistTracks.ts:9,55-62`) and on `order_mismatch` (400) invalidates + toasts a "reorder race" warning (useReorderPlaylistTracks.ts:28-42).

### 6.6 Optimistic updates — where client state is mutated

All optimistic writes follow the TanStack `onMutate`(snapshot+write)/`onError`(restore)/`onSettled|onSuccess`(invalidate) pattern, mutating the query cache via `setQueryData`/`setQueriesData`. Inventory:

- **Triage moves** — `useMoveTracks.ts`: `onMutate` cancels queries, snapshots source bucket-tracks + block, removes tracks and decrements `track_count`/`total` (`applyOptimisticMove` useMoveTracks.ts:43-77); `onError` restores. Exposes `undoMoveDirect` (useMoveTracks.ts:102-134) which **bypasses the hook** to synchronously restore the snapshot then fire the inverse HTTP call (comment useMoveTracks.ts:92-101); on inverse failure re-applies the optimistic write (useMoveTracks.ts:122-126). `useTransferTracks.ts` deliberately has **no** optimistic write (snapshot semantics server-side, comment useTransferTracks.ts:44-47).
- **Categories** — `useMoveTrackBetweenCategories.ts` (optimistic shrink of source; `MovePartialError` if add succeeds but source-delete fails, :5-10, :56-60), `useRemoveTrackOptimistic.ts` (shrink; treats 404 `track_not_in_category` as idempotent success, :48-50), `useRenameCategory.ts`.
- **Tags** — `useAddTrackTag.ts` (patches `tags[]` on cached category-tracks rows, dedupes, :20-41), `useRemoveTrackTag.ts`. These mutate the shared `['categories','tracks',categoryId]` infinite-query cache.
- **Playlists** — `useRemoveTrackFromPlaylist.ts` (filter + `total-1` on `playlistTracksKey`, :26-38; invalidates `['categories','tracks']` because `used_in_playlist` may flip), `useAddTracksToPlaylist.ts`, `usePatchPlaylist.ts`, `usePlaylistTrackTag.ts`, `useTogglePlaylistStatus.ts`, `useResolveMatch.ts`, `useUploadCover.ts`.
- **Library preferences** — `useSetArtistPreference.ts` / `useSetLabelPreference.ts`: write `my_preference` across multiple keys (info, detail, matching `['library','artists']` list pages), snapshotting each (useSetArtistPreference.ts:27-57); restore-all on error.

Query keys are mostly inline tuples except playlists which centralizes them in `features/playlists/lib/queryKeys.ts`. The shared cache key family `['categories','tracks',categoryId, search?]` is touched by categories, tags, and playlist-removal hooks — a coupling point where invalidation predicates hit all search variants (e.g. `useFinalizeTriageBlock.ts:63-72`).

**Cross-cutting observations:** (1) `VITE_API_BASE_URL` is dead at runtime vs. documented as live; (2) `navigate('/auth/premium-required')` in PlaybackProvider targets an unregistered route; (3) two independent `/auth/refresh` callers (client `tryRefreshOnce` vs. `AuthProvider.refresh`) share no dedupe — a potential replay-detection trigger if both fire near-simultaneously despite the bootstrap guard.

---

## 7. Attack surface, DB write points, spend points

This section summarizes across §1–§6. Citations are the canonical ones from the sections above.

### (a) Unauthenticated or weakly-authorized entry points

**Fully unauthenticated (no JWT authorizer)** — the four public auth routes (`infra/auth.tf:169-191`):
- `GET /auth/login` — initiates OAuth; `redirect_uri` constrained to `ALLOWED_FRONTEND_REDIRECTS` allow-list (`auth_settings.py:22-23`). Sets short-lived oauth cookies. Open-redirect risk is bounded by the allow-list.
- `GET /auth/callback` — exchanges the OAuth `code`; CSRF-protected by the `oauth_state` cookie equality check (`auth_handler.py:281-285`), PKCE verifier, and `product=="premium"` gate (`:294-295`). Writes a user row, `user_vendor_tokens`, and a session (DB writes from an unauthenticated path — see (b)).
- `POST /auth/refresh` — authorized solely by the `refresh_token` HttpOnly cookie; replay (hash mismatch) revokes **all** of the user's sessions (`auth_handler.py:414-417`, ADR-0015). Writes/rotates session + vendor tokens.
- `POST /auth/logout` — authorized by the refresh cookie; best-effort single-session revoke.

**Weakly-authorized (valid JWT passes the authorizer, finer authz is app-level only):**
- **All `/admin/*` routes on `collector_lambda`.** The JWT authorizer admits any valid token regardless of `is_admin`; admin gating exists only in `handler.py` via the `_ADMIN_ROUTES` frozenset + `_require_admin` (`handler.py:60-86`, dispatched `:158-159`). **A new `/admin/*` gateway route omitted from that frozenset is reachable by any authenticated (non-admin) user.** The curation and auth Lambdas have no admin concept at all.
- **Authorizer caching (300s, `infra/auth.tf:163`)** means a revoked/role-changed token can still authorize for up to the cache TTL.
- **`verify_iat:False`** (`jwt_utils.py:112-113`) — future-issued tokens are accepted in production.
- **User-scoped curation/preference routes** rely entirely on `user_id` from the authorizer context being threaded into every `WHERE user_id=...` clause (`curation_handler.py:171-181, 447-449`; `routes.py:275-277, 319-321`). Tenant isolation is therefore a per-query discipline, not a gateway guarantee.
- **Frontend admin/route guards are advisory** — `requireAdmin` only redirects in the SPA (`auth/requireAdmin.ts:5-11`); real enforcement is the backend `_require_admin`. The `is_admin` claim is minted at login from `ADMIN_SPOTIFY_IDS` (`auth_settings.py:19-20`).
- **Direct Spotify Web API calls from the browser** (`spotifyWebApi.ts`, PlaybackProvider) use the user's Spotify access token directly against `https://api.spotify.com` — outside CLOUDER's authorizer entirely (vendor-side authz only).

### (b) Code paths that write to Aurora

Grouped by writer. All writes go through `DataAPIClient` (§4); idempotency is by `ON CONFLICT`/`UPDATE … WHERE id`.

**Unauthenticated (auth path):**
- `GET /auth/callback` → user upsert + `user_vendor_tokens` (KMS-encrypted) upsert + session create (`auth_handler.py:314-347`), via `auth/auth_repository.py`.
- `POST /auth/refresh` → vendor-token re-encrypt/upsert + `rotate_session` (or revoke-all on replay) (`auth_handler.py:432-468`).
- `POST /auth/logout` / `DELETE /me/sessions/{id}` → session revoke.

**Admin / ingest path:**
- API Lambda `create_ingest_run` → `ingest_runs` (`INSERT … ON CONFLICT (run_id) DO UPDATE`, clears error/finished) (`handler.py:416-436`, `repositories.py:151-204`). Triggered by `POST /collect_bp_releases` (admin) and `POST /admin/beatport/ingest` (admin).

**Canonicalization worker (`worker_handler.py` → `canonicalize.py`):** writes — per phase/chunk transaction — `source_entities`, `identity_map`, `source_relations`, `clouder_labels`, `clouder_styles`, `clouder_artists`, `clouder_albums`, `clouder_tracks` (insert **or** `conservative_update_track`, the one non-additive mutation, `repositories.py:647-694`), `clouder_track_artists`; plus `set_run_completed`/`set_run_failed` on `ingest_runs` (§2.8, §2.9). This is the only path that writes the canonical catalogue.

**Spotify search worker (`spotify_handler.py`):** `batch_update_spotify_results` → `clouder_tracks.spotify_id/spotify_searched_at/release_type` + `source_entities` + `identity_map` (`spotify_handler.py:300-343`, `repositories.py:802-832`); `propagate_release_type_to_albums` → `clouder_albums` (`repositories.py:834-862`).

**Vendor-match worker (`vendor_match_handler.py`):** `upsert_vendor_match` / `mark_no_match` / `insert_review_candidate` → `vendor_match` table (`vendor_match_handler.py:105,145,178,193`; `repositories.py:1037-1068, 1141-1202`).

**Enrichment workers (label/artist):** per-run enrichment cells + merged `label_info`/`artist_info` + provenance + run rows (`orchestrator.py:105,120`; `label_enrichment/repository.py`, `artist_enrichment/repository.py`, `auto_repository.py` `claim_*`/`create_run`).

**Curation API (`curation_handler.py` + `curation/*_repository.py`), all JWT-gated and `user_id`-scoped:** categories, playlists (incl. cover refs, publish status, imported tracks), tags, triage blocks/buckets/moves/transfers/finalize. Multi-statement units wrapped in `with self._data_api.transaction()` (`categories_repository.py`, `playlists_repository.py`, `triage_repository.py`, `tags_repository.py` — sites in §4.3).

**Migrations:** `db_migration` Lambda applies Alembic DDL (the only VPC-attached Lambda; schema-level writes, not row writes).

### (c) Code paths that spend money

**Vendor API calls (per-unit cost / quota):**
- **Beatport ingest** — up to **300 paginated GETs per style/week** (`beatport_client.py:52,60,64`). Admin-triggered.
- **Spotify ISRC search** — client-credentials; **5+ calls per ISRC miss** (1 ISRC + up to 4 neighbour + 1 metadata, `spotify_client.py:123,156,553-571`; `spotify_handler.py:32-36`), self-perpetuating via `auto_continue` re-enqueue (`spotify_handler.py:267,353-403`). Batches of 2000, follow-ups capped at 200.
- **YT Music vendor-match** — 1 message per added track; **2 searches per metadata lookup** (`providers/ytmusic/lookup.py:64-67`). Gated by `vendor_match_enabled` (default false).
- **LLM enrichment (labels + artists)** — the dominant fan-out: `items × vendors × (1 generate + 1 merge)`; a 3-vendor run over N items ≈ `N × (3 generate + 1 merge)` LLM calls, and the Tavily adapter is internally 3 HTTP calls (2 Tavily + 1 DeepSeek) → ~`N × 6` upstream calls (`orchestrator.py:34,44,89`; `aggregator.py:331,381,426,432`; `tavily_deepseek.py:100,132,179`). Vendors: Gemini, OpenAI, Tavily, DeepSeek. **Largest uncapped multiplier**: auto-enrichment over a whole triage block (`auto_dispatch.py:155-162`); only `claim_labels`/`claim_artists` dedup limits re-dispatch.
- **Playlist publish/import (user-OAuth, synchronous)** — Spotify publish `ceil(tracks/100)` write calls + cover; Spotify import 1 `get_track` per ref; YT Music publish **1 `playlistItems.insert` per video** (50 quota units each) mitigated by incremental-sync diff (`ytmusic_publish_service.py:120-134`). Import also chains into the vendor-match queue.

**Aurora wakeups (Serverless v2, min ACU 0, 300s auto-pause, `rds.tf:21-25`):**
- Any code path issuing a Data API statement after idle resumes the cluster — first request pays the cold-start (the `DatabaseResumingException` retry in `data_api_retry.py:17-33` and the 503/`cold_start` frontend handling, §6.2). The cheapest unauthenticated wakeup trigger is any DB-touching request; **`/auth/refresh` and the scheduled frontend proactive refresh keep the auth path warm**, but enrichment/search workers and the curation API all independently resume the cluster. Max ACU is capped at 2 (alarm at 1.8, `alarms.tf:103-121`), bounding peak compute cost.

**Log volume / storage:**
- `LOG_LEVEL=INFO` hard-coded on every Lambda (`lambda.tf:26`); 11 log groups at **30-day retention** (`logging.tf`, `variables.tf:43-47`). `data_api_retry` emits a WARN per retry (`data_api_retry.py:99-106`) — a retry storm (e.g. repeated Aurora resume or throttling) multiplies log volume.
- **S3 raw bucket has no lifecycle policy and versioning is on** (`s3.tf:5-11`, `_base_key` overwrites create new versions per re-run) — raw snapshots, Spotify results, and all object versions accumulate indefinitely (`storage.py:245-248`). Frontend bucket has no lifecycle either.
- **SQS retention** 14d (canonicalization, spotify_search, vendor_match) / 4d (enrichment) / 1d (auto_enrich_dispatch); DLQs mirror queue retention and are terminal (§5.2).

**Cost-control gaps worth flagging:** reserved concurrency disabled by default (workers fall back to SQS `maximum_concurrency`); alarms route to an SNS topic that **defaults to empty** so nothing pages (`variables.tf:230-234`); no Lambda `dead_letter_config`; auto-enrich block fan-out has no size cap beyond the claim-dedup gate.

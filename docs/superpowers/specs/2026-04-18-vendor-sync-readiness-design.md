# Vendor-Sync Readiness — Design Spec

**Date:** 2026-04-18
**Status:** approved (brainstorm stage)
**Author:** @tarodo (via brainstorming session)

## 1. Context and Goal

Clouder Core already ingests weekly Beatport releases, canonicalizes entities into `clouder_*` tables, matches tracks to Spotify by ISRC, and enriches labels via Perplexity AI.

The product direction is a DJ-curation service:

1. Collect weekly new releases from Beatport per style.
2. Match each track to Spotify and to additional vendors (YouTube Music, Deezer, Apple Music, Tidal).
3. User curates playlists on Spotify (source of truth).
4. On "release", the service mirrors the Spotify playlist to every configured vendor.
5. Enrichment surfaces `is_ai_suspected` and `release_type` flags so the user-facing layer (out of scope here) can filter.

This spec covers **only the backend readiness** for the above: data model, provider abstraction, vendor match + release-mirror workers, secrets migration, and infrastructure cost cleanup. User-facing tables (users, tags, playlists) and UI are explicitly out of scope.

## 2. Scope

**In scope:**

- Provider abstraction with roles: `INGEST`, `LOOKUP`, `ENRICH`, `EXPORT`.
- Generic search worker: replace `LabelSearchMessage` with `EntitySearchMessage`.
- Ingestion enrichment: `release_type` on tracks/albums (Beatport + Spotify reconcile), `is_ai_suspected` propagation from `ai_search_results` onto canonical entities.
- Vendor stubs for YT Music / Deezer / Apple / Tidal (Protocol-compliant, `NotImplementedError` bodies, feature-flagged off).
- Vendor match cache (`vendor_track_map`) and review queue (`match_review_queue`).
- Release mirror flow: `POST /release_mirror` → SQS → `release_mirror_worker` → per-vendor `create_playlist`.
- User OAuth token storage (`user_vendor_tokens`) with KMS envelope encryption — table + crypto, without OAuth flow.
- Secrets: migrate service creds from Secrets Manager to SSM Parameter Store SecureString; remove Secrets Manager VPC endpoint via Aurora IAM auth for migration Lambda.

**Out of scope:**

- Users / user_tags / user_track_tags / user_playlists tables (user-layer UI backend).
- OAuth authorize/callback flow for vendors.
- Read API for canonical data beyond existing endpoints.
- Artist-level AI detection (Perplexity) — only schema readiness.
- Spotify as ingestion source (release collection) — Spotify stays LOOKUP + ENRICH + EXPORT only.
- Three-layer model (raw / period+tagged / gold): layer 1 (raw + canonical) already covered; layers 2 and 3 are user-part.

## 3. Architecture Overview

```
Beatport (INGEST)
     │
     ▼
 collector.handler ──► S3 raw ──► SQS canonicalization ──► collector.worker_handler
                                                                │
                                                                ├──► ai_search SQS ──► generic search worker ──► Perplexity (ENRICH:label)
                                                                │
                                                                └──► spotify_search SQS ──► Spotify (LOOKUP + ENRICH:release_type)
                                                                             │
                                                                             ▼
                                                                 clouder_* (canonical) + is_ai_suspected + release_type

 POST /release_mirror ──► SQS release_mirror ──► release_mirror_worker
                                                       │
                                                       ├── fetch Spotify playlist (user OAuth token from user_vendor_tokens, KMS-decrypted)
                                                       ├── map spotify_track_ids → clouder_track_ids (identity_map)
                                                       ├── for each vendor:
                                                       │      check vendor_track_map cache
                                                       │      miss → LookupProvider.lookup_by_isrc|metadata
                                                       │      low confidence → match_review_queue
                                                       │      high confidence → vendor_track_map
                                                       ├── ExportProvider.create_playlist(user_token, name, refs)
                                                       └── write release_mirror_runs.results
```

All runtime Lambdas (collector, canonicalization worker, search worker, spotify search worker, vendor match worker, release mirror worker) stay out of VPC and access Aurora via Data API, SSM / KMS via public AWS endpoints.

Migration Lambda remains inside VPC (needs direct Postgres for alembic) but switches to Aurora IAM auth, removing the Secrets Manager VPC endpoint.

## 4. Provider Abstraction

### 4.1 Protocols

Defined in `src/collector/providers/base.py`. All optional — a provider implements only the roles it supports.

```python
class IngestProvider(Protocol):
    source_name: str
    def fetch_releases(self, style_id: int, iso_year: int, iso_week: int, token: str) -> RawIngestPayload: ...

class LookupProvider(Protocol):
    vendor_name: str
    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None: ...
    def lookup_by_metadata(self, artist: str, title: str, duration_ms: int, album: str | None) -> list[VendorTrackRef]: ...

class EnrichProvider(Protocol):
    vendor_name: str
    entity_types: tuple[str, ...]     # {"label", "artist", "track"}
    prompt_slug: str
    prompt_version: str
    def enrich(self, entity_type: str, entity_id: str, payload: dict) -> EnrichResult: ...

class ExportProvider(Protocol):
    vendor_name: str
    def create_playlist(self, user_token: str, name: str, track_refs: list[VendorTrackRef]) -> VendorPlaylistRef: ...
```

`VendorTrackRef` is a frozen dataclass: `{vendor, vendor_track_id, isrc, artist_names, title, duration_ms, album_name, raw_payload}`.

### 4.2 Registry

`src/collector/providers/registry.py` holds a `dict[str, ProviderBundle]`. `ProviderBundle` groups the optional roles per provider name.

```python
PROVIDERS: dict[str, ProviderBundle] = {
    "beatport":         ProviderBundle(ingest=BeatportProvider()),
    "spotify":          ProviderBundle(lookup=SpotifyLookup(), enrich=SpotifyEnricher(), export=SpotifyExporter()),
    "perplexity_label": ProviderBundle(enrich=PerplexityLabelEnricher()),
    "ytmusic":          ProviderBundle(lookup=YTMusicProvider(), export=YTMusicExporter()),
    "deezer":           ProviderBundle(lookup=DeezerProvider(), export=DeezerExporter()),
    "apple":            ProviderBundle(lookup=AppleProvider(), export=AppleExporter()),
    "tidal":            ProviderBundle(lookup=TidalProvider(), export=TidalExporter()),
}
```

Registry accessors: `get_ingest`, `get_lookup(name)`, `get_enricher(prompt_slug)`, `get_exporter(name)`, `list_enabled_exporters()`.

Enabled state driven by `settings.VENDORS_ENABLED` (comma-separated env var). Disabled vendors stay in the registry but raise `VendorDisabledError` at call time, so stubs are always discoverable by contract tests.

### 4.3 Directory layout

```
src/collector/providers/
  __init__.py
  base.py
  registry.py
  beatport.py                 # existing BeatportClient moved here
  spotify/
    __init__.py
    lookup.py                 # from spotify_client.py
    enrich.py                 # new: album.album_type extraction
    export.py                 # new: create_playlist scaffold
  perplexity/
    label.py                  # existing LabelEnricher moved here
    artist.py                 # stub, NotImplementedError
  ytmusic/
  deezer/
  apple/
  tidal/
```

Each vendor folder has `__init__.py`, `lookup.py`, `export.py`. Stub vendor methods raise `VendorDisabledError("vendor_name=ytmusic")`.

Existing modules to retire as part of this work (content moves under `providers/` in the order in §10):

- `src/collector/beatport_client.py` → `providers/beatport.py`
- `src/collector/spotify_client.py` → `providers/spotify/lookup.py`
- `src/collector/spotify_handler.py` — logic split: enrich path → `providers/spotify/enrich.py`, SQS wiring stays but imports are updated.
- `src/collector/search_handler.py` / `src/collector/search/*` → `providers/perplexity/label.py` and the generic `EntitySearchMessage` dispatch (§6.4).

## 5. Data Model Changes

One alembic migration: `alembic/versions/20260419_07_vendor_sync_readiness.py`.

### 5.1 New tables

**`vendor_track_map`** — vendor match cache.

| Column           | Type         | Constraints                           |
|------------------|--------------|---------------------------------------|
| clouder_track_id | String(36)   | PK (composite), FK `clouder_tracks.id`|
| vendor           | String(32)   | PK (composite)                        |
| vendor_track_id  | String(128)  | NOT NULL                              |
| match_type       | String(32)   | NOT NULL (`isrc`/`fuzzy`/`manual`)    |
| confidence       | Numeric(4,3) | NOT NULL                              |
| matched_at       | DateTime(tz) | NOT NULL                              |
| payload          | JSONB        | NOT NULL                              |

Index: `idx_vtm_vendor_track (vendor, clouder_track_id)`.

**`match_review_queue`** — low-confidence matches awaiting manual approval.

| Column            | Type         | Constraints                              |
|-------------------|--------------|------------------------------------------|
| id                | String(36)   | PK                                       |
| clouder_track_id  | String(36)   | NOT NULL, FK                             |
| vendor            | String(32)   | NOT NULL                                 |
| candidates        | JSONB        | NOT NULL                                 |
| status            | String(32)   | NOT NULL (`pending`/`approved`/`rejected`)|
| created_at        | DateTime(tz) | NOT NULL                                 |
| resolved_at       | DateTime(tz) | nullable                                 |

Unique partial index: `(clouder_track_id, vendor)` WHERE `status='pending'`.

**`user_vendor_tokens`** — per-user OAuth tokens with KMS envelope.

| Column            | Type         | Constraints                  |
|-------------------|--------------|------------------------------|
| user_id           | String(36)   | PK (composite)               |
| vendor            | String(32)   | PK (composite)               |
| access_token_enc  | BYTEA        | NOT NULL                     |
| refresh_token_enc | BYTEA        | nullable                     |
| data_key_enc      | BYTEA        | NOT NULL                     |
| scope             | Text         | nullable                     |
| expires_at        | DateTime(tz) | nullable                     |
| updated_at        | DateTime(tz) | NOT NULL                     |

`users` table does not exist yet (user-layer out of scope). `user_id` is a free-form UUID string; FK constraint deferred until user-layer lands. Tests insert arbitrary UUIDs.

**`release_mirror_runs`** — mirror-invocation log.

| Column             | Type         | Constraints                                                       |
|--------------------|--------------|-------------------------------------------------------------------|
| run_id             | String(36)   | PK                                                                |
| user_id            | String(36)   | NOT NULL                                                          |
| source_vendor      | String(32)   | NOT NULL (`spotify`)                                              |
| source_playlist_id | String(128)  | NOT NULL                                                          |
| target_vendors     | JSONB        | NOT NULL                                                          |
| status             | String(32)   | NOT NULL (`QUEUED`/`RUNNING`/`COMPLETED`/`PARTIAL`/`FAILED`)      |
| started_at         | DateTime(tz) | NOT NULL                                                          |
| finished_at        | DateTime(tz) | nullable                                                          |
| results            | JSONB        | NOT NULL (`{vendor: {playlist_id, matched, missing, unmapped}}`)  |

### 5.2 New columns

- `clouder_tracks.is_ai_suspected BOOLEAN NOT NULL DEFAULT FALSE`
- `clouder_tracks.release_type VARCHAR(16) NULLABLE` — `single/ep/album/compilation`
- `clouder_albums.release_type VARCHAR(16) NULLABLE`
- `clouder_labels.is_ai_suspected BOOLEAN NOT NULL DEFAULT FALSE`
- `clouder_artists.is_ai_suspected BOOLEAN NOT NULL DEFAULT FALSE` (unused now, artist enricher readiness)

## 6. Ingestion Enhancements

### 6.1 `release_type` from Beatport

Extend `NormalizedAlbum` with `release_type: str | None`. Mapping rules in `canonicalize.py`:

- Beatport `Release` with one track → `single`.
- Beatport `Album` with 1–3 tracks → `ep`.
- Beatport `Album` with 4+ tracks → `album`.
- Any object with explicit compilation marker (`is_compilation=true` or `various artists` flag) → `compilation`.
- Heuristic fallback: `release_type=album` with `len(unique(artist_ids)) >= 4` → treat as `compilation`. Threshold `4` configurable via `settings.COMPILATION_ARTIST_THRESHOLD`, default 4.

Exact marker field names must be confirmed before coding. See §9.3.

`CreateAlbumCmd` / `UpsertAlbumCmd` receive `release_type`. Tracks inherit `release_type` from their album at canonicalize time.

### 6.2 `release_type` reconcile with Spotify

`providers/spotify/enrich.py` extracts `album.album_type` alongside `spotify_id` during ISRC lookup. Stored in the spotify raw payload. A new canonicalize step `reconcile_release_type` runs after Spotify enrich:

- If Beatport said `album` and Spotify says `compilation` → prefer `compilation` (Spotify more reliable for this field).
- If Beatport and Spotify agree → keep.
- If Spotify missing (no ISRC match) → keep Beatport value.

Rule codified as a small dispatch table, not scattered conditions.

### 6.3 `is_ai_suspected` propagation

After a successful `ai_search_results` insert, a propagation step runs inside the same transaction:

- Read the latest AI result for the entity across all prompt slugs.
- If `ai_content in ("suspected","confirmed")` and `confidence >= settings.AI_FLAG_CONFIDENCE_THRESHOLD` (default `0.6`) → set `is_ai_suspected = TRUE` on the matching canonical row.
- If all recent results say `none_detected` with confidence above the threshold → clear the flag.

Applies to `clouder_labels` today, `clouder_artists` / `clouder_tracks` as the corresponding enrichers come online.

### 6.4 Generic search worker

Introduce `EntitySearchMessage`:

```python
class EntitySearchMessage(BaseModel):
    entity_type: str            # "label"|"artist"|"track"
    entity_id: str
    prompt_slug: str
    prompt_version: str
    context: dict[str, Any]     # e.g. {"label_name": ..., "styles": ...}
```

Worker resolves the enricher via `registry.get_enricher(prompt_slug)` and dispatches.

`LabelSearchMessage` remains a pydantic alias that translates into `EntitySearchMessage` on ingress (backward compat for in-flight SQS messages). Flag for removal after one deploy cycle.

## 7. Vendor Match and Release Mirror

### 7.1 Match workflow (cache-first, on-demand)

**`vendor_match_worker`** (new Lambda, SQS-triggered):

1. Message: `{clouder_track_id, vendor, isrc?, artist, title, duration_ms, album}`.
2. `SELECT ... FROM vendor_track_map WHERE clouder_track_id=? AND vendor=?`. Hit → return, done.
3. Miss → call `LookupProvider.lookup_by_isrc(isrc)`. If the provider returns a single ref → upsert `vendor_track_map` with `match_type='isrc', confidence=1.000`.
4. If ISRC lookup empty or vendor lacks ISRC support → `LookupProvider.lookup_by_metadata(artist, title, duration_ms, album)` returns candidates.
5. Score each candidate:
   - `title_sim = normalized_levenshtein(title, candidate.title)`
   - `artist_sim = max over permutations on artist list`
   - `duration_ok = abs(duration_ms - candidate.duration_ms) <= 3000 ms`
   - `album_bonus = 0.05 if normalized_album equal`
   - `score = 0.5 * title_sim + 0.4 * artist_sim + 0.05 * duration_ok + album_bonus`
6. Best candidate with `score >= 0.92` → `vendor_track_map` with `match_type='fuzzy', confidence=score`.
7. Otherwise → insert top 5 candidates into `match_review_queue` with `status='pending'`.

Idempotency via UPSERT on the PK.

### 7.2 Release mirror workflow

**`release_mirror_worker`** (new Lambda, SQS-triggered):

1. Message: `{run_id, user_id, source_playlist_id, target_vendors}`.
2. Mark `release_mirror_runs.status='RUNNING'`.
3. Decrypt Spotify user token from `user_vendor_tokens` via KMS envelope.
4. Fetch Spotify playlist items. For each item:
   - Map `spotify_track_id → clouder_track_id` via `identity_map(source='spotify', entity_type='track', external_id=spotify_id)`.
   - Miss → record as `unmapped_in_canonical` in per-vendor result, skip for all vendors.
5. For each `(clouder_track_id, target_vendor)`:
   - Check `vendor_track_map`. Hit → use cached `vendor_track_id`.
   - Miss → call `LookupProvider` inline (same scoring as §7.1). Write cache or review queue accordingly.
6. Per vendor, collect matched `VendorTrackRef` list. Decrypt per-vendor user token. Call `ExportProvider.create_playlist(user_token, name, refs)`.
7. Write `release_mirror_runs.results[vendor] = {playlist_id, matched, missing_in_vendor, unmapped_in_canonical}`. Status `COMPLETED` if all vendors succeeded, `PARTIAL` if at least one vendor created a playlist, `FAILED` otherwise.

Inline match during mirror with bounded concurrency (asyncio, gather, N=10). Lambda timeout 5 min. Fan-out to `vendor_match_worker` only if a pre-warm step is requested; current spec keeps it inline.

### 7.3 API surface

**`POST /release_mirror`**

Request:

```json
{
  "user_id": "uuid",
  "source_playlist_id": "spotify_playlist_id",
  "target_vendors": ["ytmusic", "deezer", "apple", "tidal"],
  "name": "DJ Set — 2026 Apr"
}
```

Response: `{run_id, correlation_id, status: "QUEUED"}`. Rejects disabled vendors with `400 vendor_disabled`.

**`GET /release_mirror/{run_id}`** — returns `release_mirror_runs` row as JSON, mirror of `GET /runs/{run_id}` shape.

### 7.4 User token flow (partial)

- `user_vendor_tokens` table created.
- `src/collector/crypto.py` implements KMS envelope encrypt/decrypt.
- `scripts/store_user_token.py user_id vendor access_token [refresh_token]` seeds rows for tests.
- OAuth authorize/callback flow deferred.
- `ExportProvider` signature accepts a `refresh_fn` callable parameter for later 401-retry logic; implementations ignore it for now.

## 8. Secrets, Infra, Error Handling

### 8.1 SSM migration

- New `src/collector/secrets.py` with `get_parameter(name)` using boto3 SSM, `WithDecryption=True`, `lru_cache` on a container-level wrapper.
- `settings.py` API unchanged; `_fetch_secret_string` replaced by `_fetch_ssm_parameter`. Direct env var still wins.
- Terraform: new SSM SecureString resources; deprecate existing Secrets Manager entries after a deploy.
- Parameters to create: `/clouder/perplexity/api_key`, `/clouder/spotify/client_id`, `/clouder/spotify/client_secret`, per-vendor slots for future `/clouder/{vendor}/client_*`.

### 8.2 Aurora IAM auth for migration Lambda

- Add `rds-db:connect` IAM permission on migration Lambda role, resource `arn:aws:rds-db:<region>:<account>:dbuser/clouder_migrator`.
- Create DB role `clouder_migrator` with `GRANT rds_iam TO clouder_migrator`.
- Migration handler uses `rds.generate_db_auth_token(...)` as psycopg password.
- Terraform: set `enable_secretsmanager_vpc_endpoint = false`, remove VPC endpoint resource. Saves ~$7.2/month.

### 8.3 KMS envelope

- Terraform: KMS CMK `alias/clouder-user-tokens`.
- `src/collector/crypto.py`:
  - `encrypt_token(plaintext: bytes) -> (ciphertext, data_key_enc)`: `kms.generate_data_key(KeySpec='AES_256')` → AES-GCM on `Plaintext` → return `Ciphertext` and `CiphertextBlob`.
  - `decrypt_token(ciphertext, data_key_enc) -> bytes`: `kms.decrypt(CiphertextBlob=data_key_enc)` → AES-GCM decrypt.
- IAM: `vendor_match_worker` and `release_mirror_worker` roles get `kms:GenerateDataKey` and `kms:Decrypt` on the CMK ARN.

### 8.4 Error classes

Add to `src/collector/errors.py`:

| Error                   | status | error_code         |
|-------------------------|--------|--------------------|
| `VendorUnavailableError`| 502    | `vendor_unavailable`|
| `VendorAuthError`       | 403    | `vendor_auth_failed`|
| `VendorQuotaError`      | 429    | `vendor_quota`      |
| `VendorDisabledError`   | 400    | `vendor_disabled`   |
| `MatchFailedError`      | (non-HTTP, worker-internal) | `match_failed` |
| `UserTokenMissingError` | 400    | `user_token_missing`|

### 8.5 Retries and DLQs

- `vendor_match_worker` and `release_mirror_worker` wrap vendor calls in a `retry_vendor` decorator analogous to `retry_data_api`: full jitter, 3 retries on timeouts, 5xx, and 429 with `Retry-After` honored. 4xx non-429 fails fast.
- SQS DLQs for both workers with `maxReceiveCount=5`.
- CloudWatch alarms on DLQ `ApproximateNumberOfMessagesVisible > 0` for both, mirroring the existing canonicalization DLQ alarm.

## 9. Testing Strategy

### 9.1 Unit tests

- `tests/unit/test_providers_registry.py` — role lookup, disabled providers raise `VendorDisabledError`.
- `tests/unit/test_vendor_match.py` — scoring thresholds, ISRC vs metadata paths, review-queue routing.
- `tests/unit/test_reconcile_release_type.py` — Beatport × Spotify conflict matrix.
- `tests/unit/test_ai_flag_propagation.py` — set/clear behaviour, threshold edges.
- `tests/unit/test_crypto_envelope.py` — encrypt/decrypt roundtrip using `moto` KMS.
- `tests/unit/test_ssm_settings.py` — env > SSM > raise precedence.

### 9.2 Integration tests (ephemeral pg + moto)

- `tests/integration/test_release_mirror_worker.py` — full flow using `FakeSpotifySource` and `FakeVendorExporter`; covers cache hit, cache miss + auto-match, cache miss + review-queue routing, unmapped-in-canonical path.
- `tests/integration/test_match_review_queue.py` — low-confidence → queue row; approval → `vendor_track_map` upsert.
- `tests/integration/test_generic_search_worker.py` — `LabelSearchMessage` translated, `EntitySearchMessage` dispatched to registry.

### 9.3 Contract/inventory tests

- `tests/contract/test_vendor_stubs.py` — each stub vendor is `isinstance` of required Protocol; calling raises `VendorDisabledError` when disabled.
- `scripts/inspect_raw_sample.py` — pulls one `releases.json.gz` from S3 and prints keys relevant to `release_type` / compilation detection. Run **before** implementing §6.1 to pin the mapping rules to real Beatport shape.

### 9.4 Fixtures

Extend `tests/conftest.py`:

- `fake_vendor_bundle` — registered provider with Protocol-compliant fakes for all four roles.
- `kms_client_mock` — moto KMS CMK + DEK.
- `ssm_client_mock` — moto SSM with prepared SecureStrings.

## 10. Implementation Order

1. Generic search worker + `EntitySearchMessage` (backward-compat alias for `LabelSearchMessage`).
2. SSM migration + Aurora IAM auth (cost cleanup, removes Secrets Manager VPC endpoint).
3. Alembic migration `07_vendor_sync_readiness`: all new tables + columns.
4. `release_type` normalization + Spotify reconcile + inventory script run.
5. `is_ai_suspected` propagation from `ai_search_results`.
6. Provider abstraction scaffolding + migration of Beatport / Spotify / Perplexity clients into `providers/`.
7. Stub vendors (YT Music / Deezer / Apple / Tidal): Protocol-compliant, `VendorDisabledError` bodies, registry entries, contract tests.
8. `vendor_match_worker` Lambda + `vendor_track_map` + `match_review_queue` logic.
9. KMS envelope + `user_vendor_tokens` + `scripts/store_user_token.py`.
10. `release_mirror_worker` Lambda + `POST /release_mirror` + `GET /release_mirror/{run_id}`.
11. CloudWatch alarms, DLQs, README + data-model docs update.

Each step should land as an independent PR with its own tests, so the branch stays shippable after any step.

## 11. Open Questions / Follow-ups

- Exact Beatport marker for compilation (`release_type` field, `is_compilation`, or VA artist flag). Resolve via §9.3 inventory script before coding §6.1.
- Refresh-token flow for expired vendor OAuth tokens — deferred until user-layer lands.
- FK on `user_vendor_tokens.user_id → users.id` — deferred until `users` table exists.
- Whether to pre-warm the vendor match cache on every Spotify-ISRC lookup hit (would avoid first-release latency) — deferred; revisit after first real release mirror measurement.

# Lambda Handlers Reference

## Overview

All Lambda functions share a single Python package: `src/collector/`. Each Lambda has its own entry-point module; there is no shared `lambda_handler` dispatcher. The six functions are:

| Lambda (AWS name) | Entry-point module | Trigger |
|---|---|---|
| `beatport-prod-collector-api` | `collector.handler` | HTTP API Gateway |
| `beatport-prod-canonicalization-worker` | `collector.worker_handler` | SQS |
| `beatport-prod-ai-search-worker` | `collector.search_handler` | SQS |
| `beatport-prod-spotify-search-worker` | `collector.spotify_handler` | SQS |
| `beatport-prod-vendor-match-worker` | `collector.vendor_match_handler` | SQS |
| `beatport-prod-migration` | `collector.migration_handler` | Direct invoke (post-deploy) |

Auth flows are handled by a seventh Lambda (`collector.auth_handler`) documented separately; see [Auth handler](#auth-handler) below.

The AWS resource prefix is `beatport-prod-` regardless of the repository name (`clouder-core`). It is derived from `var.project = "beatport"` + `var.environment = "prod"` in Terraform.

See also: [data-api.md](data-api.md), [providers.md](providers.md), [ADR-0001](../adr/0001-data-api-runtime.md), [ADR-0004](../adr/0004-provider-abstraction.md).

---

## API Lambda (`collector.handler`)

**Entry point:** `src/collector/handler.py:lambda_handler`

### Routes served

| Route key | Admin-only | Description |
|---|---|---|
| `POST /collect_bp_releases` | Yes | Legacy ingest; internally calls `_run_beatport_ingest` |
| `POST /admin/beatport/ingest` | Yes | Current ingest path (Saturday-week or custom range) |
| `GET /runs/{run_id}` | No | Run status lookup |
| `GET /admin/coverage` | Yes | Per-style weekly coverage grid |
| `GET /admin/runs` | Yes | Runs for a specific style+week cell |
| `GET /tracks/spotify-not-found` | Yes | Tracks whose Spotify ISRC search has no result |
| `GET /tracks` | No | Paginated canonical track list |
| `GET /artists` | No | Paginated canonical artist list |
| `GET /albums` | No | Paginated canonical album list |
| `GET /labels` | No | Paginated canonical label list |
| `GET /styles` | No | Paginated style list |

`POST /collect_bp_releases` is deprecated; new ingests must use `POST /admin/beatport/ingest`. Both routes call `_run_beatport_ingest` internally.

### Admin gate

Admin-only routes call `_require_admin(event)` which inspects `event.requestContext.authorizer.lambda.is_admin`. The authorizer Lambda sets this field; if absent, the request gets HTTP 403.

### Request validation

Body parsing is handled by `_parse_json_body`: base64-decodes when `isBase64Encoded` is true, then validates with Pydantic (`CollectRequestIn` / `AdminIngestRequestIn`). Validation failures raise `ValidationError` which the top-level handler catches and returns as HTTP 400.

### Ingest flow (`_run_beatport_ingest`)

1. Fetch releases from Beatport via `registry.get_ingest("beatport").fetch_weekly_releases(...)`.
2. Write raw JSON + metadata to S3 (`RAW_BUCKET_NAME`, `RAW_PREFIX`).
3. Optionally create an `ingest_runs` DB row via `ClouderRepository.create_ingest_run` (skipped when `AURORA_*` vars are absent — this is a known degraded mode, not a bug).
4. Enqueue a canonicalization SQS message (`CANONICALIZATION_QUEUE_URL`).
5. Optionally enqueue label AI-search messages (`AI_SEARCH_QUEUE_URL`) when `search_label_count` is set and `AI_SEARCH_ENABLED=true`.
6. Return 200 JSON with `run_id`, `s3_object_key`, and processing status.

The `bp_token` from the request body must never be logged or written to S3. Structlog calls in this path deliberately exclude it.

### `GET /runs/{run_id}`

Returns 503 with `error_code: db_not_configured` when `AURORA_CLUSTER_ARN` / `AURORA_SECRET_ARN` are not set. This is expected in environments without Aurora configured; it is not a bug.

### Error response shape

All errors (both `AppError` subclasses and unexpected exceptions) return JSON with this envelope:

```json
{
  "error_code": "validation_error",
  "message": "human-readable text",
  "correlation_id": "...",
  "api_request_id": "...",
  "lambda_request_id": "..."
}
```

API Gateway hard-timeout errors (`{"message":"Service Unavailable"}`) use capital S/U and are **not** produced by this code — they come from API Gateway itself after 29 seconds.

See also: [data-api.md](data-api.md), [gotchas.md](gotchas.md), [ADR-0003](../adr/0003-saturday-week.md).

---

## Canonicalization Worker (`collector.worker_handler`)

**Entry point:** `src/collector/worker_handler.py:lambda_handler`

### Trigger

SQS (`CANONICALIZATION_QUEUE_URL`). Batch size is set by the SQS event-source mapping (typically 1 record per invocation). Records carry a `correlation_id` message attribute.

### Processing flow

For each SQS record:

1. Parse `CanonicalizationMessage` (Pydantic). Invalid JSON/schema → log error, skip record (message is deleted).
2. Read raw Beatport releases from S3 (`payload.s3_key`).
3. Normalize via `normalize_tracks` → a `NormalizedBundle` of tracks, artists, labels, albums, relations.
4. Canonicalize via `Canonicalizer(repository).process_run(run_id, bundle)` — upserts into Aurora.
5. Mark run `COMPLETED` in `clouder_ingest_runs`.
6. Enqueue follow-up AI-search messages (up to 500 labels) and a Spotify-search message.

### Retry and DLQ behavior

- **Transient failures** (any exception that is not `ValueError`, `TypeError`, `KeyError`, or `StorageError`) re-raise, which causes SQS to retry up to the configured maximum (`maxReceiveCount`). After that, the message goes to the DLQ.
- **Permanent failures** (`_PERMANENT_ERRORS`) log the error, mark the run `FAILED` in Aurora, then `continue` — the message is **not** re-raised, so SQS deletes it without DLQ. This prevents pointless cycling of malformed data.

### Idempotency

The canonicalization upserts use `ON CONFLICT DO UPDATE` so retrying a message that was already partially processed is safe. However, the follow-up enqueue (step 6) is best-effort; duplicate search messages are harmless because search results are also upserted.

Keep `CANONICALIZATION_QUEUE_VISIBILITY_TIMEOUT_SECONDS >= CANONICALIZATION_WORKER_LAMBDA_TIMEOUT_SECONDS` in Terraform to avoid duplicate processing while a worker is still running.

See also: [data-api.md](data-api.md), [gotchas.md](gotchas.md).

---

## AI Search Worker (`collector.search_handler`)

**Entry point:** `src/collector/search_handler.py:lambda_handler`

### Trigger

SQS (`AI_SEARCH_QUEUE_URL`). Messages are sent by the API Lambda (on ingest) and by the canonicalization worker (post-run).

### Message schema

`EntitySearchMessage` — fields: `entity_type`, `entity_id`, `prompt_slug`, `prompt_version`, `context` (dict). Current entity type: `label`. The `context` dict for labels carries `label_name` and `styles`.

### Processing flow

1. Parse message; invalid records are skipped without DLQ.
2. Resolve enricher: `registry.get_enricher_for_prompt(prompt_slug)`. If no enabled vendor handles this slug, logs a warning and returns `False` (message deleted, not retried).
3. Call `enricher.enrich(entity_type, entity_id, context, correlation_id)` — for labels this is `PerplexityLabelEnricher`.
4. Persist result to `ai_search_results` via `repository.save_search_result`.
5. Call `propagate_ai_flag` which sets/clears `is_ai_suspected` on the canonical entity row when `result.confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` (default 0.6).

### AI flag propagation rules

Defined in `propagate_ai_flag` (`src/collector/search_handler.py:26`):

- `confidence < threshold` → no-op.
- `ai_content in {suspected, confirmed}` → set `is_ai_suspected = True`.
- `ai_content == none_detected` → set `is_ai_suspected = False` (explicit clear).
- `ai_content == unknown` → no-op.

`ai_content = unknown` is a no-op; results with weak confidence are also no-ops. The authoritative AI finding is always in `ai_search_results.result` (JSONB).

### Retry behavior

Same permanent/transient split as the canonicalization worker. `ValueError`, `TypeError`, `KeyError`, `NotImplementedError` → permanent (message deleted). All other exceptions re-raise → SQS retry → DLQ.

See also: [providers.md](providers.md), [ADR-0008](../adr/0008-ai-suspected-flag.md).

---

## Spotify Search Worker (`collector.spotify_handler`)

**Entry point:** `src/collector/spotify_handler.py:lambda_handler`

### Trigger

SQS (`SPOTIFY_SEARCH_QUEUE_URL`). Messages are sent by the canonicalization worker post-run. A single message triggers a batch search for up to `batch_size` tracks (default 2000 from the worker; follow-up messages cap at 200).

### Processing flow

1. Parse `SpotifySearchMessage` (Pydantic).
2. Query Aurora for tracks needing ISRC search: `repository.find_tracks_needing_spotify_search(limit=batch_size)`. This query JOINs `clouder_track_artists`/`clouder_artists` to project `length_ms` for metadata-fallback scoring.
3. Call `registry.get_lookup("spotify").lookup_batch_by_isrc(...)`. This delegates to `SpotifyClient.search_tracks_by_isrc`.
4. Write raw batch results to S3 (`SPOTIFY_RAW_PREFIX`).
5. Process in 200-record chunks: upsert `source_entities`, `identity_map` rows, batch-update `clouder_tracks` with `spotify_id`, `release_type`, `spotify_release_date`.
6. Propagate `release_type` to parent albums for any track where a type was found.
7. Optionally enqueue a follow-up message when `auto_continue=True` and more tracks remain.

### Metadata fallback

Controlled by `SPOTIFY_METADATA_FALLBACK_ENABLED` (default `false`). When enabled, ISRC-miss tracks first try sibling ISRCs (±1, ±2 on the last digit), then a `q=track:title artist:first_artist` search with strict/relaxed acceptance tiers. See CLAUDE.md for full tier logic and tuning env vars (`SPOTIFY_FUZZY_TITLE_MIN`, `SPOTIFY_FUZZY_ARTIST_MIN`, `SPOTIFY_FUZZY_DURATION_TOLERANCE_MS`).

### `release_type` notes

`release_type` is Spotify-only. Beatport payloads do not carry this field. A track's `release_type` is NULL until its ISRC lookup succeeds. After a successful lookup, `propagate_release_type_to_albums` sets the value on the parent `clouder_albums` row.

### Deadline-aware execution

The worker passes `context.get_remaining_time_in_millis` as `deadline_provider` to `SpotifyClient`, which can abort a batch early when less than a safety margin of Lambda time remains. This avoids timeout-kills mid-batch.

See also: [providers.md](providers.md), [ADR-0006](../adr/0006-spotify-metadata-fallback.md), [ADR-0007](../adr/0007-release-type-propagation.md).

---

## Vendor Match Worker (`collector.vendor_match_handler`)

**Entry point:** `src/collector/vendor_match_handler.py:lambda_handler`

### Trigger

SQS. Messages are enqueued externally (e.g., by an admin operation) and carry `clouder_track_id`, `vendor`, `isrc`, `artist`, `title`, `duration_ms`, `album`.

### Processing flow

1. Parse `VendorMatchMessage`.
2. Check cache: `repository.get_vendor_match(track_id, vendor)`. If hit, return immediately (idempotent).
3. Resolve lookup provider via `registry.get_lookup(vendor)`. If vendor is disabled, log warning and return.
4. **ISRC path** (if `message.isrc` is set): call `lookup.lookup_by_isrc(isrc)` with `@retry_vendor(max_retries=3)`. On hit, upsert match with `match_type="isrc"`, `confidence=1.000`.
5. **Metadata path**: call `lookup.lookup_by_metadata(artist, title, duration_ms, album)` with `@retry_vendor(max_retries=3)`. Score each candidate via `score_candidate` (title sim, artist sim, duration window, album bonus). Sort descending by `total`.
6. If best score >= `FUZZY_MATCH_THRESHOLD` (default 0.92), upsert as `match_type="fuzzy"`.
7. Otherwise, insert top-5 candidates into `match_review_queue` for manual review (partial unique index on `status='pending'` prevents duplicate rows).

### Match cache PK

`(clouder_track_id, vendor)` — the upsert is idempotent. Retrying a message that already produced a match is a cache hit and exits immediately.

### Tuning

- `FUZZY_MATCH_THRESHOLD` (float 0..1, default 0.92) — minimum score to auto-cache.
- `FUZZY_DURATION_TOLERANCE_MS` (int, default 3000) — duration window used by `score_candidate`.

See also: [providers.md](providers.md), [ADR-0004](../adr/0004-provider-abstraction.md).

---

## Migration Lambda (`collector.migration_handler`)

**Entry point:** `src/collector/migration_handler.py:lambda_handler`

### Trigger

Direct invocation (not HTTP, not SQS). The deploy workflow invokes it via AWS SDK after `terraform apply`. The event payload is a `MigrationCommand` with optional `revision` (default `"head"`).

### Alembic invocation

The handler builds a database URL (`_build_alembic_database_url`) and calls `alembic.command.upgrade(config, revision)`. At Lambda runtime, migration scripts live in `db_migrations/` (the package zip renames `alembic/` → `db_migrations/`). Locally they live in `alembic/`. The handler locates the script directory relative to its own file path.

### Auth modes

`AURORA_AUTH_MODE` (env var, default `password`):

- `password` — reads `username`/`password` from the Secrets Manager secret at `AURORA_SECRET_ARN`. The master RDS secret (`rds!cluster-...`) must not be deleted.
- `iam` — generates an RDS IAM auth token via `boto3.client("rds").generate_db_auth_token(...)` using `AURORA_DB_USER`. Does not need `AURORA_SECRET_ARN`.

Both modes construct a `postgresql+psycopg://` URL passed to Alembic. `psycopg` is intentionally used only here (local + Lambda migration path); it must not be imported in any handler Lambda path.

See also: [data-api.md](data-api.md), [gotchas.md](gotchas.md), [ADR-0005](../adr/0005-iam-auth-migration.md).

---

## Auth Handler

**Entry point:** `src/collector/auth_handler.py`

The auth handler is a separate Lambda (`beatport-prod-auth-handler`) behind the same HTTP API Gateway. It handles:

- `GET /auth/login` — initiates Spotify PKCE OAuth flow, sets `oauth_state` cookie.
- `GET /auth/callback` — exchanges the code, issues CLOUDER access + refresh tokens, stores Spotify tokens.
- `POST /auth/refresh` — validates the refresh cookie, issues new token pair. Reusing the same refresh cookie revokes **all** user sessions (replay detection).
- `POST /auth/logout` — revokes the current session.
- `GET /me` — returns the authenticated user profile.

OAuth redirect target is set via `SPOTIFY_OAUTH_REDIRECT_URI` on the Lambda. It defaults to the CloudFront distribution URL (`https://<cloudfront_domain>/auth/return`) via Terraform coalescing. For detailed flow diagrams and cookie mechanics, see `docs/api/auth-flow.md` (forward reference).

See also: [ADR-0011](../adr/0011-spotify-token-bundling.md), [ADR-0015](../adr/0015-refresh-cookie-replay.md).

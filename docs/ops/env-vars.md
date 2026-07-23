# Environment Variables Reference

All Lambda functions are deployed and configured by Terraform (`infra/lambda.tf`). Values that are sensitive credentials are stored in SSM Parameter Store (SecureString) and referenced by parameter name; the Lambda reads them at cold start via the AWS SDK.

Secrets are cached per container via `lru_cache` in `src/collector/settings.py`. Rotated credentials require a Lambda cold start (deploy new version or update function configuration) to take effect.

---

## API and worker Lambda (`clouder-prod-collector-api`)

| Name | Type | Default | Source / Purpose |
|------|------|---------|-----------------|
| `RAW_BUCKET_NAME` | string | — | S3 bucket for raw Beatport snapshots (`infra/s3.tf`) |
| `RAW_PREFIX` | string | `raw/bp/releases` | S3 key prefix for raw payloads |
| `BEATPORT_API_BASE_URL` | string | `https://api.beatport.com/v4/catalog` | Beatport API base URL |
| `CANONICALIZATION_ENABLED` | bool | `false` | Set `true` in prod to enqueue canonicalization after ingest |
| `CANONICALIZATION_QUEUE_URL` | string | — | SQS queue URL for canonicalization tasks |
| `AURORA_CLUSTER_ARN` | string | — | Aurora cluster ARN for RDS Data API calls |
| `AURORA_SECRET_ARN` | string | — | Secrets Manager ARN (`rds!cluster-...`) for Data API auth |
| `AURORA_DATABASE` | string | `clouder` | Database name passed to Data API `ExecuteStatement` |
| `LOG_LEVEL` | string | `INFO` | structlog minimum level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

Also applies to: `clouder-prod-canonicalization-worker`, `clouder-prod-curation` (shared Aurora / SQS vars only).

---

## `VENDORS_ENABLED`

Applies to any Lambda that uses `src/collector/providers/registry.py`. Comma-separated list of vendor names that the registry allows. Vendors not in this list raise `VendorDisabledError` from all registry accessors — their adapter code is never instantiated.

| Value | Status | Notes |
|-------|--------|-------|
| `beatport` | Active | Ingest adapter |
| `spotify` | Active | ISRC lookup + enrichment |
| `perplexity_label` | Active | AI label content analysis |
| `perplexity_artist` | Stub | Raises `VendorDisabledError` on use |
| `ytmusic` | Stub | Raises `VendorDisabledError` on use |
| `deezer` | Stub | Raises `VendorDisabledError` on use |
| `apple` | Stub | Raises `VendorDisabledError` on use |
| `tidal` | Stub | Raises `VendorDisabledError` on use |

Example: `VENDORS_ENABLED=beatport,spotify,perplexity_label`

Adding a new vendor: create the adapter under `src/collector/providers/<vendor>/`, register a builder in `src/collector/providers/registry.py`, and add the name to `VENDORS_ENABLED`. See `docs/backend/providers.md` and ADR-0004.

---

## AI search worker (superseded — Lambda no longer exists)

> **Superseded.** There is no `ai-search-worker` Lambda in prod and no `src/collector/search_handler.py` in the codebase; the Perplexity screening path was replaced by the label and artist enrichment subsystems ([ADR-0016](../adr/0016-label-enrichment.md), [ADR-0017](../adr/0017-artist-enrichment.md)), which run on `clouder-prod-label-enricher-worker` / `clouder-prod-artist-enricher-worker` and use the OpenAI / Tavily / DeepSeek credentials synced by the deploy workflow. `AI_FLAG_CONFIDENCE_THRESHOLD` now lives on those two Lambdas. The table below is retained for history and needs a refresh pass.

| Name | Type | Default | Source / Purpose |
|------|------|---------|-----------------|
| `PERPLEXITY_API_KEY` | string | — | **Direct** — highest precedence; skips SSM/SM lookup |
| `PERPLEXITY_API_KEY_SSM_PARAMETER` | string | `/clouder/perplexity/api_key` | SSM SecureString parameter name — used in prod (synced by deploy workflow) |
| `PERPLEXITY_API_KEY_SECRET_ARN` | string | — | Legacy Secrets Manager ARN — used only if neither of the above is set |
| `AI_FLAG_CONFIDENCE_THRESHOLD` | float | `0.6` | Minimum confidence from a label search result to set/clear `is_ai_suspected`; below this threshold the flag is unchanged |
| `VENDORS_ENABLED` | string | — | Must include `perplexity_label` for this worker to function |
| `AURORA_CLUSTER_ARN` | string | — | Aurora cluster ARN |
| `AURORA_SECRET_ARN` | string | — | Aurora master secret ARN |
| `AURORA_DATABASE` | string | `clouder` | Database name |

Credential resolution order: `PERPLEXITY_API_KEY` (env) > `PERPLEXITY_API_KEY_SSM_PARAMETER` > `PERPLEXITY_API_KEY_SECRET_ARN`.

See also `docs/data/search-and-enrichment.md` for the AI search pipeline.

---

## Spotify search worker (`clouder-prod-spotify-search-worker`)

| Name | Type | Default | Source / Purpose |
|------|------|---------|-----------------|
| `SPOTIFY_CLIENT_ID` | string | — | **Direct** — highest precedence |
| `SPOTIFY_CLIENT_SECRET` | string | — | **Direct** — highest precedence; both must be set together |
| `SPOTIFY_CLIENT_ID_SSM_PARAMETER` | string | `/clouder/spotify/client_id` | SSM SecureString — used in prod; both SSM params must be set or the resolver falls through |
| `SPOTIFY_CLIENT_SECRET_SSM_PARAMETER` | string | `/clouder/spotify/client_secret` | SSM SecureString — see above |
| `SPOTIFY_CREDENTIALS_SECRET_ARN` | string | — | Legacy SM JSON `{"client_id": "...", "client_secret": "..."}` — lowest precedence |
| `SPOTIFY_METADATA_FALLBACK_ENABLED` | bool | `false` | Enable multi-stage fallback search when ISRC lookup returns 0 results |
| `SPOTIFY_FUZZY_TITLE_MIN` | float | `0.90` | Minimum title similarity for strict-tier acceptance (stage 2) |
| `SPOTIFY_FUZZY_ARTIST_MIN` | float | `0.85` | Minimum artist similarity for strict-tier acceptance (stage 2) |
| `SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` | int | `3000` | Max duration delta (ms) for strict-tier acceptance; relaxed tier ignores this |
| `VENDORS_ENABLED` | string | — | Must include `spotify` |
| `AURORA_CLUSTER_ARN` | string | — | Aurora cluster ARN |
| `AURORA_SECRET_ARN` | string | — | Aurora master secret ARN |
| `AURORA_DATABASE` | string | `clouder` | Database name |

Credential resolution order: direct env (`SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`) > SSM (both `*_SSM_PARAMETER` vars must be set) > `SPOTIFY_CREDENTIALS_SECRET_ARN`.

Fallback search stages (when `SPOTIFY_METADATA_FALLBACK_ENABLED=true`):

1. Sibling ISRCs (`±1`, `±2` on last digit) verified by title + artist similarity (no duration check).
2. Metadata search (`?q=track:<title> artist:<first_artist>`) with two acceptance tiers:
   - **Strict**: `title_sim >= SPOTIFY_FUZZY_TITLE_MIN`, `artist_sim >= SPOTIFY_FUZZY_ARTIST_MIN`, `|dur_diff| <= SPOTIFY_FUZZY_DURATION_TOLERANCE_MS`
   - **Relaxed**: `title_sim >= 0.95`, `artist_sim >= 0.95`, no duration check

See `docs/data/search-and-enrichment.md` and ADR-0006 for full fallback logic.

---

## Vendor match worker (`clouder-prod-vendor-match-worker`)

| Name | Type | Default | Source / Purpose |
|------|------|---------|-----------------|
| `VENDORS_ENABLED` | string | — | Comma-separated; must include `spotify` for Spotify matching |
| `SPOTIFY_CLIENT_ID` | string | — | Same credential resolution as Spotify search worker (above) |
| `SPOTIFY_CLIENT_SECRET` | string | — | Same credential resolution as Spotify search worker (above) |
| `SPOTIFY_CLIENT_ID_SSM_PARAMETER` | string | — | SSM path |
| `SPOTIFY_CLIENT_SECRET_SSM_PARAMETER` | string | — | SSM path |
| `SPOTIFY_CREDENTIALS_SECRET_ARN` | string | — | Legacy SM ARN |
| `FUZZY_MATCH_THRESHOLD` | float | `0.92` | Minimum fuzzy score to cache a vendor match; scores below this go to `match_review_queue` |
| `FUZZY_DURATION_TOLERANCE_MS` | int | `3000` | Duration match window (ms) for the `duration_ok` scoring component |
| `AURORA_CLUSTER_ARN` | string | — | Aurora cluster ARN |
| `AURORA_SECRET_ARN` | string | — | Aurora master secret ARN |
| `AURORA_DATABASE` | string | `clouder` | Database name |

Note: `vendor_match_handler` upserts on cache hit (PK `(clouder_track_id, vendor)`); the operation is idempotent on retry.

---

## Migration Lambda (`clouder-prod-db-migration`)

| Name | Type | Default | Source / Purpose |
|------|------|---------|-----------------|
| `AURORA_WRITER_ENDPOINT` | string | — | Aurora writer endpoint for direct psycopg connection |
| `AURORA_PORT` | int | `5432` | Aurora port |
| `AURORA_DATABASE` | string | `clouder` | Database name |
| `AURORA_AUTH_MODE` | string | `password` | `password` or `iam` — selects credential resolution path |
| `AURORA_SECRET_ARN` | string | — | Required when `AURORA_AUTH_MODE=password`; Secrets Manager ARN with `{username, password}` |
| `AURORA_DB_USER` | string | `clouder_migrator` | Required when `AURORA_AUTH_MODE=iam`; PostgreSQL role that has `rds_iam` granted |

Auth mode details (see `src/collector/migration_handler.py`):

- **`password`** (legacy): reads `AURORA_SECRET_ARN` from Secrets Manager, extracts `username`/`password`, builds psycopg URL.
- **`iam`** (prod default since deploy cutover): calls `rds.generate_db_auth_token()` for `AURORA_DB_USER`, builds psycopg URL with the token as password. The DB role must have `rds_iam` granted by the master user (see `docs/ops/aurora.md`).

See `docs/ops/aurora.md` for the IAM grant procedure and `rds!cluster-...` master secret retention requirements.

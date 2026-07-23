# Logs

CLOUDER uses structlog for Lambda logging. All events are written to CloudWatch Logs in JSON format.

## Tailing Lambda logs

Get function names from Terraform output, then tail with `aws logs tail`:

```bash
# API / collector Lambda
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" \
  --follow

# Canonicalization worker
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw canonicalization_worker_lambda_function_name)" \
  --follow

# Migration Lambda (typically short-lived; omit --follow)
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw migration_lambda_function_name)"

# AI search worker
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw ai_search_worker_lambda_function_name)" \
  --follow

# Spotify search worker
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw spotify_search_worker_lambda_function_name)" \
  --follow

# Vendor match worker
aws logs tail \
  "/aws/lambda/$(cd infra && terraform output -raw vendor_match_worker_lambda_function_name)" \
  --follow
```

All commands must be run from the repo root (or prefix `cd infra &&` so Terraform can resolve the output). Log group names follow the pattern `/aws/lambda/<function-name>`.

Log retention is 30 days (configurable via `var.log_retention_days` in `infra/variables.tf`).

---

## Structlog events

All events are JSON objects. Common fields: `event`, `level`, `timestamp`, `correlation_id`. Additional fields vary per event.

### API Lambda (`clouder-prod-collector-api`)

| Event | Meaning |
|-------|---------|
| `request_received` | Incoming HTTP request logged at handler entry; includes HTTP method, path, `correlation_id` |
| `request_validated` | Request body parsed and validated against schema; logged before downstream calls |
| `beatport_request` | Outbound call to Beatport API; includes URL and page number |
| `beatport_response` | Response from Beatport API received; includes HTTP status and item count |
| `collection_completed` | Full ingest run finished; includes `run_id`, total tracks fetched, S3 key written |

Note: `bp_token` is sanitized before structlog — it must never appear in log output (CLAUDE.md constraint).

### Canonicalization worker (`clouder-prod-canonicalization-worker`)

| Event | Meaning |
|-------|---------|
| `canonicalization_completed` | One SQS message fully processed; entity counts inserted/updated |
| `canonicalization_failed` | Unhandled exception during canonicalization; includes exception type and `correlation_id` |

### Migration Lambda (`clouder-prod-db-migration`)

| Event | Meaning |
|-------|---------|
| `migration_started` | Alembic `upgrade` invoked; logged at Lambda entry |
| `migration_completed` | Migrations finished successfully; includes `duration_ms` |

### Spotify search worker (`clouder-prod-spotify-search-worker`)

| Event | Meaning |
|-------|---------|
| `spotify_isrc_neighbour_match` | Stage-1 hit: a sibling ISRC (`±1`/`±2` last digit) matched by title + artist gate |
| `spotify_metadata_fallback_attempted` | Stage-2 metadata search issued (title + first artist query) |
| `spotify_metadata_fallback_match` | Stage-2 strict-tier acceptance: `title_sim >= SPOTIFY_FUZZY_TITLE_MIN`, `artist_sim >= SPOTIFY_FUZZY_ARTIST_MIN`, duration within tolerance |
| `spotify_metadata_fallback_match_relaxed` | Stage-2 relaxed-tier acceptance: `title_sim >= 0.95`, `artist_sim >= 0.95`, no duration check |
| `spotify_metadata_fallback_rejected` | Stage-2 attempted but no candidate met either tier's thresholds |
| `spotify_metadata_fallback_scores` | Emitted on stage-2 reject; contains best `title_sim` and `artist_sim` observed — use for tuning `SPOTIFY_FUZZY_TITLE_MIN` / `SPOTIFY_FUZZY_ARTIST_MIN` |

Fallback search is disabled by default (`SPOTIFY_METADATA_FALLBACK_ENABLED=false`). When disabled, only the direct ISRC lookup runs and none of the fallback events are emitted.

---

## Aurora PostgreSQL logs

Aurora server-side logs are not exported to CloudWatch by default.

**Enable once** (only needed when debugging auth failures, query errors, or Data API `BadRequestException`):

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier clouder-prod-aurora \
  --cloudwatch-logs-export-configuration '{"EnableLogTypes":["postgresql"]}' \
  --apply-immediately
```

**Tail after enabling:**

```bash
aws logs tail /aws/rds/cluster/clouder-prod-aurora/postgresql --follow
```

Disable when no longer needed to avoid log storage costs:

```bash
aws rds modify-db-cluster \
  --db-cluster-identifier clouder-prod-aurora \
  --cloudwatch-logs-export-configuration '{"DisableLogTypes":["postgresql"]}' \
  --apply-immediately
```

The cluster identifier `clouder-prod-aurora` is derived from `var.project=beatport` + `var.environment=prod` + suffix `-aurora` (defined in `infra/main.tf` as `local.db_cluster_identifier`).

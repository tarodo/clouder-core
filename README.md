# Beatport Weekly Releases Collector

Serverless ingestion + canonicalization pipeline.

The service performs weekly track collection from Beatport, stores raw snapshots in S3, triggers asynchronous canonicalization via an SQS worker, and writes canonical entities to Aurora PostgreSQL through RDS Data API.

## Current Architecture

```mermaid
flowchart TD
    A["POST /collect_bp_releases"] --> B["API Lambda (collector.handler)"]
    B --> C["Beatport API fetch + pagination"]
    C --> D["S3 raw: releases.json.gz + meta.json"]
    D --> E["ingest_runs status=RAW_SAVED (Data API)"]
    E --> F{"CANONICALIZATION_ENABLED=true\nand queue URL is set"}
    F -- yes --> G["SQS message (run_id,s3_key,...)"]
    F -- no --> H["processing_status=FAILED_TO_QUEUE"]
    G --> I["Worker Lambda (collector.worker_handler)"]
    I --> J["Read raw from S3"]
    J --> K["Normalize: tracks/artists/albums/labels"]
    K --> L["Canonicalize: clouder_* + identity_map"]
    L --> M["ingest_runs status=COMPLETED"]
    L --> N["on error -> status=FAILED, retry, DLQ"]
```

## API

### `POST /collect_bp_releases`

Purpose: start weekly Beatport snapshot collection.

Request body:

```json
{
  "bp_token": "string",
  "style_id": 5,
  "iso_year": 2026,
  "iso_week": 9
}
```

Response body:

- `run_id`
- `correlation_id`
- `api_request_id`
- `lambda_request_id`
- `iso_year`
- `iso_week`
- `s3_object_key`
- `item_count`
- `duration_ms`
- `run_status` (`RAW_SAVED`)
- `processing_status` (`QUEUED` or `FAILED_TO_QUEUE`)
- `processing_outcome` (`ENQUEUED|DISABLED|ENQUEUE_FAILED`)
- `processing_reason` (`null|config_disabled|queue_missing|enqueue_exception`)

### `GET /runs/{run_id}`

Purpose: fetch processing status for a run.

Response body:

- `run_id`
- `status` (`RAW_SAVED|COMPLETED|FAILED`)
- `processed_counts.processed`
- `processed_counts.total`
- `error` (`null` or `{code,message}`)
- `started_at`
- `finished_at`

Important: this endpoint returns `503 db_not_configured` if Data API env vars (`AURORA_*`) are not configured for the Lambda.

## Data Storage

### S3 raw data

```text
raw/bp/releases/
  style_id=<style_id>/
    year=<YYYY>/
      week=<WW>/
        releases.json.gz
        meta.json
```

### Aurora PostgreSQL (via Data API)

- `ingest_runs`
- `source_entities`
- `source_relations`
- `clouder_artists`
- `clouder_labels`
- `clouder_albums`
- `clouder_tracks`
- `clouder_track_artists`
- `identity_map`

## Infrastructure (Terraform)

Current setup in `infra/`:

- HTTP API Gateway routes:
  - `POST /collect_bp_releases`
  - `GET /runs/{run_id}`
- Lambda functions:
  - API handler: `collector.handler.lambda_handler`
  - Worker handler: `collector.worker_handler.lambda_handler`
  - Migration handler: `collector.migration_handler.lambda_handler`
- SQS queue + DLQ (`maxReceiveCount=5`)
- Aurora PostgreSQL Serverless v2 + Data API (`enable_http_endpoint=true`)
- VPC interface endpoint for Secrets Manager (required for migration Lambda in private subnets)

Current Aurora scaling:

- `aurora_serverless_min_acu = 0`
- `aurora_serverless_max_acu = 2`
- `aurora_auto_pause_seconds = 300`

## Local Run

### 1) Provision infra

```bash
cd infra
terraform init
terraform apply
```

### 2) Get API endpoint

```bash
cd infra
terraform output -raw api_endpoint
```

### 3) Trigger collection

```bash
scripts/invoke_collect.sh \
  --api-url "$(cd infra && terraform output -raw api_endpoint)" \
  --style-id 5 \
  --iso-year 2026 \
  --iso-week 9 \
  --bp-token "<your_short_lived_bp_token>"
```

### 4) Check run status

```bash
RUN_ID="<run_id_from_collect_response>"
API_URL="$(cd infra && terraform output -raw api_endpoint)"
awscurl --service execute-api --region us-east-1 "$API_URL/runs/$RUN_ID"
```

## Lambda Environment Variables

Key runtime env vars:

- `RAW_BUCKET_NAME`
- `RAW_PREFIX`
- `BEATPORT_API_BASE_URL`
- `CANONICALIZATION_ENABLED`
- `CANONICALIZATION_QUEUE_URL`
- `AURORA_CLUSTER_ARN`
- `AURORA_SECRET_ARN`
- `AURORA_DATABASE`
- `LOG_LEVEL`

Migration Lambda uses:

- `AURORA_WRITER_ENDPOINT`
- `AURORA_PORT`
- `AURORA_SECRET_ARN`
- `AURORA_DATABASE`

## Database Migrations

Database schema is managed via SQLAlchemy/Alembic.

- SQLAlchemy models: `src/collector/db_models.py`
- Alembic: `alembic/`

Run locally:

```bash
python -m pip install -r requirements-dev.txt
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
```

## CI/CD

### PR Checks (`.github/workflows/pr.yml`)

- `alembic-check` job: migrations against ephemeral Postgres
- `terraform` job: fmt/validate/plan
- `tests` job: `pytest -q`

### Deploy (`.github/workflows/deploy.yml`)

- package Lambda zip (`scripts/package_lambda.sh`, artifact includes `db_migrations/` and `alembic.ini`)
- `terraform apply` with `canonicalization_enabled=true` for prod
- invoke migration Lambda (`action=upgrade`, `revision=head`)

## Logs and Diagnostics

Get function names:

```bash
cd infra
terraform output -raw lambda_function_name
terraform output -raw canonicalization_worker_lambda_function_name
terraform output -raw migration_lambda_function_name
```

Tail logs:

```bash
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" --follow
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw canonicalization_worker_lambda_function_name)" --follow
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw migration_lambda_function_name)" --follow
```

Main events:

- `request_received`
- `request_validated`
- `beatport_request`
- `beatport_response`
- `collection_completed`
- `canonicalization_completed`
- `canonicalization_failed`
- `migration_started`
- `migration_completed`

## Known Operational Notes

- `processing_status=FAILED_TO_QUEUE` means raw data was saved, but canonicalization message was not enqueued.
- Use `processing_outcome`/`processing_reason` to distinguish disabled routing vs enqueue failures.
- For reliable queue processing, keep `canonicalization_queue_visibility_timeout_seconds >= canonicalization_worker_lambda_timeout_seconds` to avoid duplicate parallel processing of long-running messages.
- Migrations run automatically in deploy workflow via migration Lambda; a separate `ALEMBIC_DATABASE_URL` GitHub secret is no longer required.

## Security

- `bp_token` is not stored in S3 and is not logged in plaintext.
- API errors are returned in a sanitized form.

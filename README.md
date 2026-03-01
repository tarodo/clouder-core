# Beatport Weekly Releases Collector

Serverless ingestion + canonicalization pipeline.

Сервис делает weekly сбор треков из Beatport, сохраняет raw в S3, запускает асинхронную канонизацию через SQS worker и пишет каноничные сущности в Aurora PostgreSQL через RDS Data API.

## Текущая схема

```mermaid
flowchart TD
    A["POST /collect_bp_releases"] --> B["API Lambda (collector.handler)"]
    B --> C["Beatport API fetch + pagination"]
    C --> D["S3 raw: releases.json.gz + meta.json"]
    D --> E["ingest_runs status=RAW_SAVED (Data API)"]
    E --> F{"CANONICALIZE_ENABLED=true\nи queue url задан"}
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

Назначение: запустить сбор weekly Beatport snapshot.

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
- `processing_status` (`QUEUED` или `FAILED_TO_QUEUE`)

### `GET /runs/{run_id}`

Назначение: получить статус обработки run.

Response body:

- `run_id`
- `status` (`RAW_SAVED|COMPLETED|FAILED`)
- `processed_counts.processed`
- `processed_counts.total`
- `error` (`null` или `{code,message}`)
- `started_at`
- `finished_at`

Важно: endpoint вернет `503 db_not_configured`, если для Lambda не заданы Data API env (`AURORA_*`).

## Где хранятся данные

### S3 raw

```text
raw/bp/releases/
  style_id=<style_id>/
    year=<YYYY>/
      week=<WW>/
        releases.json.gz
        meta.json
```

### Aurora PostgreSQL (через Data API)

- `ingest_runs`
- `source_entities`
- `source_relations`
- `clouder_artists`
- `clouder_labels`
- `clouder_albums`
- `clouder_tracks`
- `clouder_track_artists`
- `identity_map`

## Инфраструктура (Terraform)

Текущее состояние в `infra/`:

- HTTP API Gateway с route:
  - `POST /collect_bp_releases`
  - `GET /runs/{run_id}`
- Lambda:
  - API handler: `collector.handler.lambda_handler`
  - Worker handler: `collector.worker_handler.lambda_handler`
- SQS queue + DLQ (`maxReceiveCount=5`)
- Aurora PostgreSQL Serverless v2 + Data API (`enable_http_endpoint=true`)

Aurora scaling сейчас:

- `aurora_serverless_min_acu = 0`
- `aurora_serverless_max_acu = 2`
- `aurora_auto_pause_seconds = 300`

## Локальный запуск

### 1) Поднять infra

```bash
cd infra
terraform init
terraform apply
```

### 2) Получить endpoint

```bash
cd infra
terraform output -raw api_endpoint
```

### 3) Запустить сбор

```bash
scripts/invoke_collect.sh \
  --api-url "$(cd infra && terraform output -raw api_endpoint)" \
  --style-id 5 \
  --iso-year 2026 \
  --iso-week 9 \
  --bp-token "<your_short_lived_bp_token>"
```

### 4) Проверить статус run

```bash
RUN_ID="<run_id_from_collect_response>"
API_URL="$(cd infra && terraform output -raw api_endpoint)"
awscurl --service execute-api --region us-east-1 "$API_URL/runs/$RUN_ID"
```

## Переменные окружения Lambda

Ключевые runtime env:

- `RAW_BUCKET_NAME`
- `RAW_PREFIX`
- `BEATPORT_API_BASE_URL`
- `CANONICALIZE_ENABLED`
- `CANONICALIZE_QUEUE_URL`
- `AURORA_CLUSTER_ARN`
- `AURORA_SECRET_ARN`
- `AURORA_DATABASE`
- `LOG_LEVEL`

## Миграции БД

Схема БД хранится в SQLAlchemy/Alembic.

- SQLAlchemy models: `src/collector/db_models.py`
- Alembic: `alembic/`

Локально:

```bash
python -m pip install -r requirements-dev.txt
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
alembic upgrade head
```

## CI/CD

### PR Checks (`.github/workflows/pr.yml`)

- `alembic-check` job: миграции на ephemeral Postgres
- `terraform` job: fmt/validate/plan
- `tests` job: `pytest -q`

### Deploy (`.github/workflows/deploy.yml`)

- package lambda zip
- `terraform apply`
- `alembic upgrade head` (только если задан `ALEMBIC_DATABASE_URL` secret)

## Логи и диагностика

Получить имена функций:

```bash
cd infra
terraform output -raw lambda_function_name
terraform output -raw worker_lambda_function_name
```

Смотреть логи:

```bash
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" --follow
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw worker_lambda_function_name)" --follow
```

Основные события:

- `request_received`
- `request_validated`
- `beatport_request`
- `beatport_response`
- `collection_completed`
- `canonicalization_completed`
- `canonicalization_failed`

## Известные operational notes

- `processing_status=FAILED_TO_QUEUE` означает, что raw сохранен, но задача канонизации не отправлена.
- Для надежной очереди рекомендуется держать `canonicalize_queue_visibility_timeout_seconds >= worker_lambda_timeout_seconds`, чтобы избежать повторной параллельной обработки long-running сообщений.

## Безопасность

- `bp_token` не сохраняется в S3 и не логируется открытым текстом.
- API ошибки возвращаются в санитизированном виде.

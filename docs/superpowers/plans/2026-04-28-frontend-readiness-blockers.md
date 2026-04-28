# Frontend Readiness — Critical Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть production-critical блокеры, выявленные архитектурным аудитом 2026-04-28, и подготовить backend к разработке frontend (single-tenant: только владелец проекта пользуется до публичного запуска).

**Архитектура:** Точечные правки `infra/*.tf` (CORS, ACU, reserved concurrency, alarms), генератор OpenAPI (`scripts/generate_openapi.py`) с реальным staging URL и examples, новый README для frontend-разработки в `docs/frontend.md`. Никаких изменений в логике handler-ов или БД.

**Tech Stack:** Terraform AWS provider, Python 3.12 (`scripts/generate_openapi.py` использует `pydantic`+`yaml`), pytest, AWS API Gateway v2 HTTP, Aurora Serverless v2, Lambda.

**Что НЕ входит** (отложено до публичного запуска):
- WAF, per-user rate limiting / quotas
- DLQ recovery Lambda (re-drive)
- X-Ray tracing
- Read replicas Aurora
- Idempotency на дубли SQS-сообщений
- Frontend сам по себе (это отдельная работа)

**Что вошло** (6 задач):
1. CORS на API Gateway HTTP API
2. Aurora `min_acu = 0.5` (избавляет от 503 на cold-start)
3. Reserved concurrency = 2 на `ai_search_worker` (не выжигать Perplexity)
4. CloudWatch alarms: Lambda errors + duration p95 + RDS ACU
5. OpenAPI: staging server URL, BearerAuth howto, примеры request bodies
6. `docs/frontend.md` — старт-гайд для frontend-разработки (auth flow, sample API calls, test data)

---

## Task 1: CORS на API Gateway

**Цель:** Frontend на любом origin (`http://localhost:5173` для Vite, `https://app.example.com` для прода) должен иметь возможность вызывать API. Сейчас `aws_apigatewayv2_api` создан без `cors_configuration` → preflight `OPTIONS` падает, browser блокирует запросы.

**Files:**
- Modify: `infra/api_gateway.tf:1-4`
- Modify: `infra/variables.tf` (добавить `cors_allowed_origins`)
- Modify: `infra/terraform.tfvars.example` (показать пример)

- [ ] **Step 1: Добавить переменную `cors_allowed_origins`**

В конец `infra/variables.tf` добавить:

```hcl
variable "cors_allowed_origins" {
  description = "Список origin-ов для CORS на API Gateway. Пустой список = CORS отключён."
  type        = list(string)
  default     = []
}
```

- [ ] **Step 2: Включить `cors_configuration` на API**

Заменить блок `aws_apigatewayv2_api.collector` в `infra/api_gateway.tf:1-4` на:

```hcl
resource "aws_apigatewayv2_api" "collector" {
  name          = local.api_name
  protocol_type = "HTTP"

  dynamic "cors_configuration" {
    for_each = length(var.cors_allowed_origins) > 0 ? [1] : []
    content {
      allow_origins  = var.cors_allowed_origins
      allow_methods  = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
      allow_headers  = ["authorization", "content-type", "x-correlation-id"]
      expose_headers = ["x-correlation-id"]
      max_age        = 600
      allow_credentials = false
    }
  }
}
```

- [ ] **Step 3: Документировать пример в `terraform.tfvars.example`**

В `infra/terraform.tfvars.example` добавить (если файл уже существует — append; если нет — создать с этой строкой):

```hcl
# CORS: укажи origin-ы фронта. Пустой список = CORS отключён (только server-to-server).
cors_allowed_origins = ["http://localhost:5173", "http://localhost:3000"]
```

- [ ] **Step 4: Прогнать `terraform fmt` + `terraform validate`**

Run:
```bash
cd infra && terraform fmt && terraform validate
```
Expected: `Success! The configuration is valid.`

- [ ] **Step 5: Прогнать `terraform plan`**

Run:
```bash
cd infra && terraform plan -var='cors_allowed_origins=["http://localhost:5173"]'
```
Expected: единственный diff — `aws_apigatewayv2_api.collector` получит `cors_configuration` block.

- [ ] **Step 6: Commit**

```bash
git add infra/api_gateway.tf infra/variables.tf infra/terraform.tfvars.example
git commit -m "feat(infra): add CORS to API Gateway HTTP API"
```

---

## Task 2: Aurora `min_acu = 0.5` (убрать 503 на cold-start)

**Цель:** API Gateway имеет hard timeout 29s. Aurora с `min_acu=0` уходит в auto-pause после 300s, и первый запрос после простоя часто превышает 29s → юзер видит 503. Поднимаем floor до 0.5 ACU. Цена: ~$43/мес, но UX становится приемлемым для разработки фронта.

**Files:**
- Modify: `infra/variables.tf:127-131`

- [ ] **Step 1: Поднять default min ACU**

В `infra/variables.tf` найти блок `variable "aurora_serverless_min_acu"` и заменить `default = 0` на `default = 0.5`:

```hcl
variable "aurora_serverless_min_acu" {
  description = "Aurora Serverless v2 min ACU. 0 = auto-pause после aurora_auto_pause_seconds (риск 503 cold-start через API GW). 0.5 = всегда warm."
  type        = number
  default     = 0.5
}
```

- [ ] **Step 2: Прогнать `terraform fmt` + `terraform validate`**

Run:
```bash
cd infra && terraform fmt && terraform validate
```
Expected: `Success!`

- [ ] **Step 3: `terraform plan` — убедиться что diff только в `min_capacity`**

Run:
```bash
cd infra && terraform plan
```
Expected diff: `aws_rds_cluster.aurora.serverlessv2_scaling_configuration[0].min_capacity: 0 -> 0.5`. Никаких replace/destroy.

- [ ] **Step 4: Commit**

```bash
git add infra/variables.tf
git commit -m "fix(infra): raise Aurora min ACU to 0.5 to avoid 503 cold-start"
```

---

## Task 3: Reserved concurrency = 2 на `ai_search_worker`

**Цель:** Bulk-ингест недели (~1000 labels) сейчас выпускает столько же параллельных Perplexity-запросов, сколько SQS закидывает в Lambda. Perplexity отдаёт 429 → SQS retry → DLQ. CLAUDE.md прямо рекомендует `reserved_concurrent_executions = 1..2`.

**Files:**
- Modify: `infra/lambda.tf:106-132` (resource `ai_search_worker`)
- Modify: `infra/variables.tf` (новая переменная)

- [ ] **Step 1: Добавить переменную `ai_search_worker_reserved_concurrency`**

В `infra/variables.tf` добавить:

```hcl
variable "ai_search_worker_reserved_concurrency" {
  description = "Reserved concurrent executions для ai_search_worker. Ограничивает параллельные вызовы Perplexity API (rate limit ≈ 5 RPS на платном тарифе). 2 — безопасный default."
  type        = number
  default     = 2
}
```

- [ ] **Step 2: Применить лимит в Lambda ресурсе**

В `infra/lambda.tf:106-132` добавить строку `reserved_concurrent_executions = var.ai_search_worker_reserved_concurrency` после `memory_size`:

```hcl
resource "aws_lambda_function" "ai_search_worker" {
  function_name = local.ai_search_worker_lambda_name
  role          = aws_iam_role.collector_lambda.arn
  runtime       = "python3.12"
  handler       = "collector.search_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = var.ai_search_worker_lambda_timeout_seconds
  memory_size   = var.ai_search_worker_lambda_memory_mb

  reserved_concurrent_executions = var.ai_search_worker_reserved_concurrency

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      PERPLEXITY_API_KEY_SECRET_ARN    = var.perplexity_api_key_secret_arn
      PERPLEXITY_API_KEY_SSM_PARAMETER = var.perplexity_api_key_ssm_parameter
      AURORA_CLUSTER_ARN               = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN                = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                  = var.aurora_database_name
      LOG_LEVEL                        = "INFO"
      VENDORS_ENABLED                  = "perplexity_label,perplexity_artist"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.ai_search_worker,
  ]
}
```

- [ ] **Step 3: `terraform fmt` + `validate`**

Run:
```bash
cd infra && terraform fmt && terraform validate
```
Expected: `Success!`

- [ ] **Step 4: `terraform plan`**

Run:
```bash
cd infra && terraform plan
```
Expected diff: `aws_lambda_function.ai_search_worker.reserved_concurrent_executions: -1 -> 2` (in-place update).

- [ ] **Step 5: Commit**

```bash
git add infra/lambda.tf infra/variables.tf
git commit -m "feat(infra): cap ai_search_worker concurrency at 2 to avoid Perplexity 429"
```

---

## Task 4: CloudWatch alarms — Lambda errors, duration, RDS ACU

**Цель:** Сейчас единственный сигнал о проблемах — рост DLQ. Добавляем минимально-достаточный набор alarms, чтобы на этапе самостоятельного использования frontend-разработчиком (= ты сам) сразу видеть что Lambda падает или Aurora уперлась в потолок.

**Files:**
- Create: `infra/alarms.tf`

- [ ] **Step 1: Создать `infra/alarms.tf` с тремя alarm-классами**

Создать файл `infra/alarms.tf`:

```hcl
# ── Lambda error rate (любая Lambda, любая ошибка) ───────────────
locals {
  monitored_lambdas = {
    collector            = aws_lambda_function.collector.function_name
    canonicalization     = aws_lambda_function.canonicalization_worker.function_name
    ai_search            = aws_lambda_function.ai_search_worker.function_name
    spotify_search       = aws_lambda_function.spotify_search_worker.function_name
    vendor_match         = aws_lambda_function.vendor_match_worker.function_name
    auth                 = aws_lambda_function.auth.function_name
    curation             = aws_lambda_function.curation.function_name
  }
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = local.monitored_lambdas

  alarm_name          = "${each.value}-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda ${each.value} ругнулась хотя бы раз за 5 мин"

  dimensions = {
    FunctionName = each.value
  }
}

# ── Lambda duration p95 — раннее предупреждение о деградации ─────
resource "aws_cloudwatch_metric_alarm" "lambda_duration_p95" {
  for_each = local.monitored_lambdas

  alarm_name          = "${each.value}-duration-p95"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "Duration"
  namespace           = "AWS/Lambda"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 20000 # 20 секунд (API GW timeout = 29s)
  treat_missing_data  = "notBreaching"
  alarm_description   = "Lambda ${each.value} p95 latency > 20s — подползаем к API GW timeout"

  dimensions = {
    FunctionName = each.value
  }
}

# ── Aurora ACU upper bound ──────────────────────────────────────
resource "aws_cloudwatch_metric_alarm" "aurora_acu_max" {
  alarm_name          = "${aws_rds_cluster.aurora.cluster_identifier}-acu-near-max"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ServerlessDatabaseCapacity"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = var.aurora_serverless_max_acu * 0.9
  treat_missing_data  = "notBreaching"
  alarm_description   = "Aurora ACU > 90% от max — пора увеличивать max_acu или оптимизировать запросы"

  dimensions = {
    DBClusterIdentifier = aws_rds_cluster.aurora.cluster_identifier
  }
}
```

- [ ] **Step 2: Убедиться что имена Lambda-ресурсов в локальной мапе совпадают с реальными**

Прогнать:
```bash
grep -E '^resource "aws_lambda_function"' infra/lambda.tf infra/auth.tf infra/curation.tf
```

Сверить с ключами `local.monitored_lambdas`. Если ресурс `auth` или `curation` лежит под другим именем (например `aws_lambda_function.auth_handler`) — поправить ссылку в `alarms.tf`.

- [ ] **Step 3: `terraform fmt` + `validate`**

Run:
```bash
cd infra && terraform fmt && terraform validate
```
Expected: `Success!`

- [ ] **Step 4: `terraform plan`**

Run:
```bash
cd infra && terraform plan
```
Expected: 7 × `aws_cloudwatch_metric_alarm.lambda_errors[...]` + 7 × `lambda_duration_p95[...]` + 1 × `aurora_acu_max` = **15 новых ресурсов**.

- [ ] **Step 5: Commit**

```bash
git add infra/alarms.tf
git commit -m "feat(infra): add CloudWatch alarms for Lambda errors, p95, Aurora ACU"
```

---

## Task 5: OpenAPI — staging URL, BearerAuth howto, примеры payload

**Цель:** `docs/openapi.yaml` сейчас имеет шаблонный server URL `https://{api_id}.execute-api.{region}.amazonaws.com` и ноль `examples`. Frontend-разработчик не может из спеки понять реальный URL и формат payload. Чиним генератор.

**Files:**
- Modify: `scripts/generate_openapi.py` (поправить `servers`, добавить `info.description`, прокинуть `examples` в request bodies)
- Modify: `infra/outputs.tf` (выгрузить `api_invoke_url` если ещё не выгружен)
- Regenerate: `docs/openapi.yaml`

- [ ] **Step 1: Найти где в генераторе формируется `servers` и `info`**

Run:
```bash
grep -n '"servers"\|"info"\|invoke_url' scripts/generate_openapi.py
```

Запомни строки. Это место правки в Step 2.

- [ ] **Step 2: Поправить `servers` на конкретный URL + добавить богатый `info.description`**

В `scripts/generate_openapi.py` найти словарь `info` и `servers`. Заменить на следующую структуру (точные ключи могут уже существовать — заменяй значения):

```python
info = {
    "title": "Beatport Weekly Releases Collector API",
    "version": "0.1.0",
    "description": (
        "Backend API для еженедельной выгрузки Beatport-релизов, AI-обогащения, "
        "категоризации и triage.\n\n"
        "## Authentication\n\n"
        "Все эндпоинты (кроме `/auth/login` и `/auth/callback`) требуют JWT Bearer "
        "токен в заголовке `Authorization: Bearer <token>`.\n\n"
        "**Как получить токен:**\n"
        "1. `GET /auth/login` → вернёт redirect на Spotify OAuth.\n"
        "2. После approve Spotify редиректит на `/auth/callback?code=...&state=...`.\n"
        "3. Callback возвращает JSON `{access_token, refresh_token, expires_in}`.\n"
        "4. Используй `access_token` в заголовке `Authorization: Bearer ...`.\n"
        "5. Когда `access_token` истечёт — `POST /auth/refresh` с `refresh_token`.\n\n"
        "## Admin endpoints\n\n"
        "`POST /collect_bp_releases` и `GET /tracks/spotify-not-found` требуют admin-флаг "
        "(Spotify ID юзера должен быть в `ADMIN_SPOTIFY_IDS` env var).\n\n"
        "## Error envelope\n\n"
        "Все ошибки (кроме API GW 503) возвращаются в формате "
        "`{error_code, message, correlation_id}`."
    ),
}

servers = [
    {
        "url": os.environ.get(
            "OPENAPI_SERVER_URL",
            "https://REPLACE_ME.execute-api.us-east-1.amazonaws.com",
        ),
        "description": "Staging (заполни OPENAPI_SERVER_URL перед публикацией спеки)",
    },
]
```

Убедись что в начале файла есть `import os`.

- [ ] **Step 3: Добавить `examples` в request bodies для триаж-эндпоинтов**

Найти в `scripts/generate_openapi.py` место где собираются `requestBody.content."application/json".schema`. Добавить поле `example` рядом со `schema` для следующих моделей (в Pydantic есть `model_json_schema(mode="serialization")` — проще руками вписать):

```python
REQUEST_EXAMPLES = {
    "CreateTriageBlockIn": {
        "style_id": "house",
        "from_date": "2026-04-21",
        "to_date": "2026-04-28",
        "name": "House — week 17",
    },
    "MoveTracksIn": {
        "from_bucket_id": "bucket_uuid_a",
        "to_bucket_id": "bucket_uuid_b",
        "track_ids": ["track_uuid_1", "track_uuid_2"],
    },
    "TransferTracksIn": {
        "to_block_id": "another_block_uuid",
        "to_bucket_id": "another_bucket_uuid",
        "track_ids": ["track_uuid_1"],
    },
    "CollectRequestIn": {
        "year": 2026,
        "week": 17,
        "bp_token": "REDACTED",
    },
}
```

В месте формирования request body (поиск по слову `requestBody` в генераторе) добавить:

```python
schema_name = ...  # имя текущей Pydantic модели
body_schema = {"$ref": f"#/components/schemas/{schema_name}"}
content = {"schema": body_schema}
if schema_name in REQUEST_EXAMPLES:
    content["example"] = REQUEST_EXAMPLES[schema_name]
request_body = {
    "required": True,
    "content": {"application/json": content},
}
```

(Точная интеграция зависит от текущей формы цикла генерации — главное: где формируется `content` для `application/json`, дописать `content["example"] = REQUEST_EXAMPLES.get(schema_name)` если есть.)

- [ ] **Step 4: Регенерировать `docs/openapi.yaml`**

Run:
```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/arch_control && \
PYTHONPATH=src OPENAPI_SERVER_URL="https://REPLACE_ME.execute-api.us-east-1.amazonaws.com" \
.venv/bin/python scripts/generate_openapi.py
```
Expected: файл `docs/openapi.yaml` обновлён без ошибок.

- [ ] **Step 5: Проверить что новые поля попали в спеку**

Run:
```bash
grep -A 3 "## Authentication" docs/openapi.yaml | head -8
grep -B 1 -A 6 "example:" docs/openapi.yaml | head -30
```
Expected: первая команда показывает раздел `## Authentication` в `info.description`, вторая — несколько `example:` блоков под request body schemas.

- [ ] **Step 6: Записать инструкцию по подстановке реального URL**

В `scripts/generate_openapi.py` сверху (после shebang/imports) добавить однострочный комментарий:

```python
# Перед публикацией спеки в Postman / Swagger UI выставить OPENAPI_SERVER_URL
# в реальный invoke URL API Gateway. Пример: terraform output -raw api_invoke_url
```

- [ ] **Step 7: Commit**

```bash
git add scripts/generate_openapi.py docs/openapi.yaml
git commit -m "docs(api): enrich OpenAPI with auth howto, examples, configurable server URL"
```

---

## Task 6: `docs/frontend.md` — старт-гайд для разработки фронта

**Цель:** Frontend-разработчику (= ты сам) нужен один документ: как локально получить токен, какие endpoints вызывать в каком порядке, какие env vars выставить, какой staging URL использовать. Без него каждый раз будешь копаться в коде.

**Files:**
- Create: `docs/frontend.md`

- [ ] **Step 1: Создать `docs/frontend.md`**

Создать файл со следующим содержимым:

```markdown
# Frontend Integration Guide

Backend API контракт см. `docs/openapi.yaml` (импортируй в Postman / Swagger UI / Insomnia).

## Окружения

| Окружение | Invoke URL | Как получить |
|-----------|-----------|--------------|
| Production | `terraform output -raw api_invoke_url` (из `infra/`) | После `terraform apply` |
| Local dev | Не поддерживается — Lambdas не запускаются локально. Тестируй против prod / staging. | — |

CORS allowed origins выставляется через `terraform.tfvars` → `cors_allowed_origins`. Дефолт пуст. Для Vite фронта добавь `"http://localhost:5173"`.

## Auth Flow (OAuth + JWT)

```
[Frontend] ──GET /auth/login──▶ [API]
                                  │
                                  └──302 redirect──▶ [Spotify OAuth]
                                                       │
[Browser] ◀──redirect /auth/callback?code=...&state=...
                                  │
[Frontend] ──GET /auth/callback?code=...&state=...──▶ [API]
                                                       │
                                                       └──200 {access_token, refresh_token, expires_in}
```

После получения `access_token`:
- В каждый запрос: `Authorization: Bearer <access_token>`
- На 401 → `POST /auth/refresh` с `{"refresh_token": "..."}` → новый `access_token`
- Logout: `POST /auth/logout` с `{"refresh_token": "..."}`

## Test User Setup

1. Получи Spotify Premium-аккаунт.
2. На бэке выставить env var `ADMIN_SPOTIFY_IDS = "<твой_spotify_id>"` (через Terraform var) — это даст admin-доступ к `/collect_bp_releases` и `/tracks/spotify-not-found`.
3. Залогинься через `/auth/login` → `/auth/callback`.

## Главные user flows

### 1. Просмотр треков

```
GET /tracks?style=house&limit=50&offset=0
GET /artists?limit=50
GET /labels?limit=50
GET /albums?limit=50
GET /styles
```

Все списки поддерживают `limit` (1..200) + `offset`, многие — `search`.

### 2. Категории (Spec-C)

```
GET    /categories
POST   /categories                       {style_id, name}
GET    /categories/{id}/tracks?limit=&offset=&search=
POST   /categories/{id}/tracks           {track_ids: [...]}
DELETE /categories/{id}/tracks/{track_id}
DELETE /categories/{id}
```

### 3. Triage (Spec-D) — сессионная работа

```
POST   /triage/blocks                                              {style_id, from_date, to_date, name?}
GET    /triage/blocks
GET    /triage/blocks/{id}                                         # detail с buckets
POST   /triage/blocks/{id}/buckets/{bucket_id}/tracks              # listing
POST   /triage/blocks/{id}/move                                    {from_bucket_id, to_bucket_id, track_ids}
POST   /triage/blocks/{src_id}/transfer                            {to_block_id, to_bucket_id, track_ids}
POST   /triage/blocks/{id}/finalize                                # promote staging → categories
DELETE /triage/blocks/{id}                                         # soft delete
```

Bucket types: `NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED` (technical) + `STAGING` (per category snapshot).

## Error envelope

Все доменные ошибки:
```json
{
  "error_code": "validation_error|not_found|forbidden|...",
  "message": "Human-readable причина",
  "correlation_id": "uuid-v4"
}
```

Исключение: API Gateway 503 (cold-start timeout) → `{"message": "Service Unavailable"}` (capital S/U) — retry на следующий запрос.

## Quirks

- **Cold-start первого запроса.** Aurora min ACU = 0.5 (после Task 2 этого плана), но всё равно первая после ночи Lambda может занять 3-8s. Делай в UI `loading state` минимум 10s tolerance.
- **Long-running collect.** `POST /collect_bp_releases` может выполняться > 29s → API GW отдаст 503, но Lambda продолжит работу в фоне. Проверь статус через `GET /runs/{run_id}`.
- **Pagination на triage bucket-tracks.** Эндпоинт `/triage/blocks/{id}/buckets/{bucket_id}/tracks` поддерживает `limit`+`offset`+`search` (см. `_list_bucket_tracks` в `curation_handler.py`).
- **Rate limits.** Сейчас не выставлены. Не насилуй `/collect_bp_releases` (внутри использует Beatport API с собственными лимитами).

## Локальный запуск тестов API

```bash
PYTHONPATH=src pytest tests/integration -q
```

(Использует моки AWS — не требует реальных креденшелов.)
```

- [ ] **Step 2: Проверить что markdown валиден**

Run:
```bash
head -20 docs/frontend.md
```
Expected: видишь `# Frontend Integration Guide` и таблицу окружений.

- [ ] **Step 3: Commit**

```bash
git add docs/frontend.md
git commit -m "docs: add frontend integration guide with auth flow and user flows"
```

---

## Финальная проверка

После всех 6 задач прогнать:

- [ ] **Self-check 1: Все Terraform изменения собираются вместе**

```bash
cd infra && terraform fmt -check && terraform validate && terraform plan
```
Expected: 15+ новых alarm-ресурсов, in-place updates на API GW (CORS), Aurora (min_capacity), ai_search Lambda (reserved concurrency). Никаких replace/destroy.

- [ ] **Self-check 2: Тесты не сломались**

```bash
PYTHONPATH=src pytest -q
```
Expected: 614 passed (без regressions). Никакой код handler-ов не правился — должно зелёное.

- [ ] **Self-check 3: OpenAPI валиден**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('docs/openapi.yaml'))"
```
Expected: тишина (нет exception).

- [ ] **Self-check 4: Импорт в Swagger UI**

Открой https://editor.swagger.io/, вставь содержимое `docs/openapi.yaml`. Не должно быть красных ошибок (warnings about server URL — ок, заменишь после `terraform apply`).

- [ ] **Self-check 5: README ссылается на новый guide**

Проверить `README.md`: если есть раздел «Frontend» — добавить ссылку `[Frontend integration guide](docs/frontend.md)`. Если нет — добавить однострочную секцию.

---

## Deployment последовательность

1. PR с этими 6 коммитами → merge в `main`
2. CI прогонит `pr.yml` (alembic-check / terraform plan / pytest) — должно зелёное
3. `deploy.yml` применит Terraform → CORS, ACU, concurrency, alarms живут
4. Проверить вручную: `curl -i -X OPTIONS -H "Origin: http://localhost:5173" -H "Access-Control-Request-Method: GET" "$(cd infra && terraform output -raw api_invoke_url)/tracks"` → должен вернуться `204` с `access-control-allow-origin: http://localhost:5173`
5. Поднять `OPENAPI_SERVER_URL` в `terraform output -raw api_invoke_url`, перегенерировать `docs/openapi.yaml`, закоммитить (опционально автоматизировать в CI)
6. Можно начинать фронт

## Откат

Все 6 задач реверсируются `git revert <commit>` без миграций БД и без data loss. Aurora ACU = 0 безопасно вернуть, alarms удалить, CORS снять, reserved concurrency убрать.

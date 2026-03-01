# Beatport Weekly Releases Collector

Serverless collector: локально запускаешь скрипт, он вызывает API Gateway, а тот триггерит Lambda и сохраняет сырые данные в S3.

## Что происходит в запросе

- Входная точка: `POST /collect_bp_releases`
- Авторизация: AWS SigV4 (`execute-api:Invoke`)
- Lambda валидирует вход, собирает данные из Beatport, пишет артефакты в S3

Запрос:

```json
{
  "bp_token": "string",
  "style_id": 5,
  "iso_year": 2026,
  "iso_week": 9
}
```

Ответ:

- `run_id`, `correlation_id`, `api_request_id`, `lambda_request_id`
- `iso_year`, `iso_week`, `s3_object_key`, `item_count`, `duration_ms`

## Локальный запуск к Lambda (через API Gateway)

Ниже минимальный рабочий путь от нуля.

### 1) Подготовь инфраструктуру (если еще не задеплоено)

```bash
cd infra
terraform init
terraform apply
```

Если используешь remote state:

```bash
terraform init -backend-config=backend.hcl
```

### 2) Получи endpoint API

```bash
cd infra
terraform output -raw api_endpoint
```

Пример значения:

```text
https://abc123.execute-api.us-east-1.amazonaws.com
```

### 3) Проверь локальные зависимости

Нужны команды:

- `awscurl` (опционально)
- `curl` с поддержкой `--aws-sigv4`
- `python3`
- `uuidgen`
- `aws` CLI

Скрипт сначала пытается использовать `awscurl`, а если его нет, автоматически переключается на `curl --aws-sigv4`.

Установить `awscurl` можно так:

```bash
pip install awscurl
```

### 4) Подготовь AWS credentials

У пользователя/роли должны быть права на `execute-api:Invoke` для этого API.

Проверь, что креды подхватились:

```bash
aws sts get-caller-identity
```

Если работаешь через профиль:

```bash
export AWS_PROFILE=<your-profile>
```

Регион по умолчанию в скрипте: `us-east-1`.

### 5) Запусти вызов

```bash
scripts/invoke_collect.sh \
  --api-url "$(cd infra && terraform output -raw api_endpoint)" \
  --style-id 5 \
  --iso-year 2026 \
  --iso-week 9 \
  --bp-token "<your_short_lived_bp_token>"
```

Опционально можно передать:

- `--correlation-id <id>`
- `--region <aws-region>`

Если `--bp-token` не передать, скрипт попросит ввести токен интерактивно.

## Как посмотреть логи после запуска

Получи имя функции:

```bash
cd infra
terraform output -raw lambda_function_name
```

Смотри поток логов:

```bash
aws logs tail "/aws/lambda/$(cd infra && terraform output -raw lambda_function_name)" --follow
```

Полезные события:

- `request_received`
- `request_validated`
- `beatport_request` (каждый запрос в Beatport)
- `beatport_response`
- `collection_completed`

## Где лежат данные в S3

```text
raw/bp/releases/
  style_id=<style_id>/
    year=<YYYY>/
      week=<WW>/
        releases.json.gz
        meta.json
```

## Частые проблемы

- `403` при вызове API: нет/не те AWS credentials или нет `execute-api:Invoke`.
- `beatport_auth_failed`: невалидный/просроченный `bp_token`.
- `beatport_unavailable`: временная проблема Beatport API или сетевой сбой.

## Безопасность

- `bp_token` не сохраняется в S3 и не логируется открытым текстом
- ошибки в API-ответах отдаются в санитизированном виде

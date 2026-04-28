# Frontend Integration Guide

Backend API контракт см. `docs/openapi.yaml` (импортируй в Postman / Swagger UI / Insomnia).

## Окружения

| Окружение | Invoke URL | Как получить |
|-----------|-----------|--------------|
| Production | `terraform output -raw api_invoke_url` (из `infra/`) | После `terraform apply` |
| Local dev | Не поддерживается — Lambdas не запускаются локально. Тестируй против prod / staging. | — |

CORS allowed origins выставляется через `terraform.tfvars` → `cors_allowed_origins`. Дефолт пуст. Для Vite фронта добавь `"http://localhost:5173"`.

Чтобы вставить реальный staging URL в `docs/openapi.yaml`:

```bash
cd infra && URL=$(terraform output -raw api_invoke_url) && cd ..
OPENAPI_SERVER_URL="$URL" PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```

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
- На 401 → `POST /auth/refresh` (refresh JWT читается из cookie, body не нужен) → новый `access_token`
- Logout: `POST /auth/logout`

## Test User Setup

1. Получи Spotify Premium-аккаунт.
2. Выставь Terraform var `admin_spotify_ids = ["<твой_spotify_id>"]` — это даст admin-доступ к `/collect_bp_releases` и `/tracks/spotify-not-found`.
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
GET    /categories                                # все категории текущего user-а
POST   /styles/{style_id}/categories              {name}                  # создать
PUT    /styles/{style_id}/categories/order        {category_ids: [...]}   # переупорядочить
PATCH  /categories/{id}                           {name}                  # переименовать
GET    /categories/{id}/tracks?limit=&offset=&search=
POST   /categories/{id}/tracks                    {track_id}              # add (single)
DELETE /categories/{id}/tracks/{track_id}
DELETE /categories/{id}
```

### 3. Triage (Spec-D) — сессионная работа

```
POST   /triage/blocks                                              {style_id, date_from, date_to, name}
GET    /triage/blocks
GET    /triage/blocks/{id}                                         # detail с buckets
GET    /triage/blocks/{id}/buckets/{bucket_id}/tracks?limit=&offset=&search=
POST   /triage/blocks/{id}/move                                    {from_bucket_id, to_bucket_id, track_ids}
POST   /triage/blocks/{src_id}/transfer                            {target_bucket_id, track_ids}
POST   /triage/blocks/{id}/finalize                                # promote staging → categories
DELETE /triage/blocks/{id}                                         # soft delete
```

Bucket types: `NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED` (technical) + `STAGING` (per category snapshot).

`style_id` — UUID (36 chars), не slug. `date_from`/`date_to` — ISO date.

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

- **Cold-start первого запроса.** Aurora `min_acu = 0.5` (всегда warm), но первая Lambda после ночи может занять 3-8s. UI loading state ставь tolerance минимум 10s.
- **Long-running collect.** `POST /collect_bp_releases` может выполняться > 29s → API GW отдаст 503, но Lambda продолжит работу в фоне. Проверь статус через `GET /runs/{run_id}`.
- **Pagination на triage bucket-tracks.** Эндпоинт `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` поддерживает `limit`+`offset`+`search`.
- **Rate limits.** Сейчас не выставлены на API Gateway. Внутренние воркеры имеют reserved concurrency (`ai_search_worker = 2`) — соблюдай vendor rate limits через размер batch.
- **Sensitive data.** `bp_token` отправляй ровно один раз в `POST /collect_bp_releases`. Не логируй на фронте, не клади в localStorage.

## Локальный запуск тестов API

```bash
PYTHONPATH=src pytest tests/integration -q
```

Использует моки AWS — не требует реальных креденшелов.

## CloudWatch alarms

Деплой добавляет CloudWatch alarms (см. `infra/alarms.tf`):
- Lambda errors на всех 8 runtime Lambdas
- Lambda duration p95 > 20s на 4 API-facing Lambdas
- ai_search_worker throttles
- Aurora ACU > 90% от max

`alarm_actions` подключаются если задана Terraform var `alarm_sns_topic_arn`. Без неё — мониторь CloudWatch UI вручную.

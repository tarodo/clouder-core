# Spotify ISRC Search — Process Overview

> Поиск треков на Spotify по ISRC-коду для связывания данных между Beatport и Spotify.

---

## Общая схема

```
Canonicalization Worker
    |
    | SpotifySearchMessage → SQS (spotify_search)
    v
Spotify Search Worker (Lambda)
    |
    |── [1] Загрузка треков из БД (isrc IS NOT NULL, spotify_searched_at IS NULL)
    |── [2] Аутентификация на Spotify (Client Credentials)
    |── [3] Поиск по ISRC через Spotify Web API
    |── [4] Сохранение результатов в S3
    |── [5] Запись в source_entities + identity_map
    |── [6] Обновление clouder_tracks (spotify_id + spotify_searched_at)
    |── [7] Если остались необработанные треки → follow-up SQS message
    v
GET /tracks/spotify-not-found → ненайденные треки для вторичного поиска
```

---

## Этап 0: Триггер

**Файл:** `src/collector/worker_handler.py`

После завершения канонализации (step 2 основного пайплайна) worker автоматически
отправляет `SpotifySearchMessage` в SQS-очередь `spotify_search`:

```json
{
  "batch_size": 2000
}
```

Условия отправки:
- Задана `SPOTIFY_SEARCH_QUEUE_URL`
- Канонализация завершилась успешно

Сообщение не содержит iso_year/iso_week — worker сам определяет какие треки
ещё не обработаны, запрашивая их из БД.

---

## Этап 1: Загрузка треков из БД

**Файл:** `src/collector/repositories.py` → `find_tracks_needing_spotify_search()`

```sql
SELECT id, isrc, title, normalized_title
FROM clouder_tracks
WHERE isrc IS NOT NULL
  AND spotify_searched_at IS NULL
ORDER BY created_at DESC
LIMIT :batch_size
```

Логика выборки:
- Только треки с ISRC (у большинства Beatport-треков есть ISRC)
- `spotify_searched_at IS NULL` — ещё не искали
- Лимит по `batch_size` из сообщения (по умолчанию 2000)

Если треков нет — worker логирует `spotify_search_skipped` и завершается.

---

## Этап 2: Аутентификация на Spotify

**Файл:** `src/collector/spotify_client.py` → `SpotifyClient._authenticate()`

Используется **Client Credentials Flow** (server-to-server, без участия пользователя):

1. `POST https://accounts.spotify.com/api/token`
2. Header: `Authorization: Basic base64(client_id:client_secret)`
3. Body: `grant_type=client_credentials`
4. Ответ: `{"access_token": "...", "token_type": "Bearer", "expires_in": 3600}`

Токен кешируется в экземпляре клиента. Автоматическое обновление:
- За 60 секунд до истечения срока
- При получении 401 во время батч-поиска

**Env-переменные:** `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`

---

## Этап 3: Поиск по ISRC

**Файл:** `src/collector/spotify_client.py` → `search_tracks_by_isrc()`

Для каждого трека выполняется запрос:

```
GET https://api.spotify.com/v1/search?q=isrc:{ISRC}&type=track&limit=1
```

Результат:
- **Найден:** первый трек из `tracks.items[0]` → `SpotifySearchResult(spotify_id=..., spotify_track={...})`
- **Не найден:** `SpotifySearchResult(spotify_id=None, spotify_track=None)`

### Обработка ошибок и retry

| HTTP код | Поведение |
|----------|-----------|
| 200 | Успех |
| 401, 403 | `SpotifyAuthError` — re-auth происходит на уровне `search_tracks_by_isrc()`: сбрасывает токен, повторно аутентифицируется, retry текущего трека |
| 429 | Rate limit — ждём `Retry-After` секунд |
| 408, 500, 502, 503, 504 | Transient — exponential backoff (max 4 retry) |
| Остальные | Permanent error — пропускаем трек |

### Производительность

- ~100ms на запрос
- 2000 треков ≈ 200 секунд
- Lambda timeout: 900 секунд (запас на retry и rate limiting)

---

## Этап 4: Сохранение в S3

**Файл:** `src/collector/storage.py` → `write_spotify_results()`

Все результаты батча сохраняются в **один** gzip-архив (не по одному треку).
Ключ партиционирован по дате и correlation_id:

```
s3://bucket/raw/sp/tracks/date=2026-03-14/{correlation_id}/results.json.gz
s3://bucket/raw/sp/tracks/date=2026-03-14/{correlation_id}/meta.json
```

### results.json.gz

```json
[
  {
    "isrc": "GBDVB2100123",
    "clouder_track_id": "uuid-1",
    "spotify_id": "4iV5W9uYEdYUVa79Axb7Rh",
    "spotify_track": { "id": "4iV5W9...", "name": "Track Name", "artists": [...], ... }
  },
  {
    "isrc": "USRC12345678",
    "clouder_track_id": "uuid-2",
    "spotify_id": null,
    "spotify_track": null
  }
]
```

### meta.json

```json
{
  "correlation_id": "corr-uuid",
  "searched_at_utc": "2026-03-14T10:30:00Z",
  "total_tracks": 2000,
  "found": 1850,
  "not_found": 150
}
```

---

## Этап 5: Запись в source_entities + identity_map

**Файл:** `src/collector/spotify_handler.py` → `_process_results_chunk()`

Для **найденных** треков (spotify_id IS NOT NULL):

### source_entities

```
source       = "spotify"
entity_type  = "track"
external_id  = spotify_id (например "4iV5W9uYEdYUVa79Axb7Rh")
name         = spotify_track.name
payload      = полный JSON-объект трека от Spotify
payload_hash = SHA-256 от payload
```

### identity_map

```
source              = "spotify"
entity_type         = "track"
external_id         = spotify_id
clouder_entity_type = "track"
clouder_id          = clouder_track.id
match_type          = "isrc_match"
confidence          = 1.000
```

Confidence = 1.0, так как ISRC — уникальный международный код записи.

### Chunking

Обработка идёт чанками по 200 записей для оптимизации транзакций в Aurora Data API.

---

## Этап 6: Обновление clouder_tracks

**Файл:** `src/collector/repositories.py` → `batch_update_spotify_results()`

Для **всех** треков (найденных и ненайденных):

```sql
UPDATE clouder_tracks
SET spotify_id = :spotify_id,           -- ID трека на Spotify или NULL
    spotify_searched_at = :searched_at,  -- время поиска (всегда NOT NULL)
    updated_at = :searched_at
WHERE id = :track_id
```

### Состояния трека после поиска

| spotify_searched_at | spotify_id | Статус |
|---------------------|------------|--------|
| NULL | NULL | Ещё не искали |
| NOT NULL | NOT NULL | Найден на Spotify |
| NOT NULL | NULL | Искали, не нашли |

---

## Этап 7: Follow-up (автопродолжение)

**Файл:** `src/collector/spotify_handler.py` → `_enqueue_follow_up_if_needed()`

После обработки батча worker проверяет, остались ли ещё необработанные треки:

```python
remaining = repository.find_tracks_needing_spotify_search(limit=1)
```

Если треки остались и задан `SPOTIFY_SEARCH_QUEUE_URL` — отправляет **новый SQS message**
с тем же `batch_size`:

```json
{"batch_size": 2000}
```

Это создаёт цепочку:

```
Batch 1 (2000 треков) → follow-up → Batch 2 (2000 треков) → follow-up → ... → 0 треков → стоп
```

Цепочка автоматически завершается, когда все треки обработаны.
Это решает проблему больших объёмов (10000+ треков) и backfill.

---

## Эндпоинт: GET /tracks/spotify-not-found

**Файл:** `src/collector/handler.py`

Возвращает пагинированный список треков, которые искали на Spotify, но не нашли.
Предназначен для вторичного поиска (по title + artist).

### Параметры

| Параметр | Тип | По умолчанию | Описание |
|----------|-----|--------------|----------|
| limit | int | 50 | Кол-во записей (max 200) |
| offset | int | 0 | Смещение |
| search | str | — | Фильтр по title/artist |

### Ответ

```json
{
  "items": [
    {
      "id": "uuid-2",
      "title": "Some Track",
      "isrc": "USRC12345678",
      "bpm": 128,
      "publish_date": "2026-03-10",
      "artist_names": "Artist A, Artist B"
    }
  ],
  "total": 150,
  "limit": 50,
  "offset": 0
}
```

---

## Конфигурация

### Env-переменные

| Переменная | Lambda | Описание |
|------------|--------|----------|
| `SPOTIFY_CLIENT_ID` | spotify_search_worker | Client ID из Spotify Developer Dashboard |
| `SPOTIFY_CLIENT_SECRET` | spotify_search_worker | Client Secret |
| `RAW_BUCKET_NAME` | spotify_search_worker | S3 bucket для raw-данных |
| `SPOTIFY_RAW_PREFIX` | spotify_search_worker | Префикс в S3 (default: `raw/sp/tracks`) |
| `SPOTIFY_SEARCH_QUEUE_URL` | collector, canonicalization_worker, spotify_search_worker | URL SQS-очереди (триггер из UI, триггер после канонализации, follow-up) |
| `SPOTIFY_SEARCH_ENABLED` | collector | Флаг в настройках (определён, но триггер фактически контролируется наличием `SPOTIFY_SEARCH_QUEUE_URL`) |

### Terraform-переменные

| Переменная | Тип | Default |
|------------|-----|---------|
| `spotify_search_enabled` | bool | false |
| `spotify_client_id` | string | "" (sensitive) |
| `spotify_client_secret` | string | "" (sensitive) |
| `spotify_raw_prefix` | string | "raw/sp/tracks" |
| `spotify_search_worker_lambda_timeout_seconds` | number | 900 |
| `spotify_search_worker_lambda_memory_mb` | number | 512 |
| `spotify_search_batch_size` | number | 1 |

### GitHub Secrets

| Secret | Назначение |
|--------|-----------|
| `SPOTIFY_CLIENT_ID` | → `var.spotify_client_id` → Lambda env |
| `SPOTIFY_CLIENT_SECRET` | → `var.spotify_client_secret` → Lambda env |

---

## Инфраструктура

```
SQS: spotify_search          (visibility: 960s, DLQ после 3 попыток)
SQS: spotify_search_dlq      (retention: 14 дней)
Lambda: spotify_search_worker (timeout: 900s, memory: 512MB)
S3: raw/sp/tracks/            (batch results + meta)
CloudWatch: /aws/lambda/spotify_search_worker
API Gateway: GET /tracks/spotify-not-found
```

---

## Мониторинг (CloudWatch Logs)

Ключевые события:

| Event | Level | Описание |
|-------|-------|----------|
| `spotify_worker_invoked` | INFO | Worker запущен |
| `spotify_search_started` | INFO | Начало поиска для batch |
| `spotify_search_tracks_loaded` | INFO | Загружено N треков из БД |
| `spotify_search_completed` | INFO | Поиск завершён (total, found, not_found) |
| `spotify_search_skipped` | INFO | Нет треков для поиска |
| `spotify_follow_up_enqueued` | INFO | Отправлен follow-up message (ещё есть треки) |
| `spotify_follow_up_skipped` | WARNING | Есть треки, но нет QUEUE_URL |
| `spotify_message_invalid` | ERROR | Невалидное SQS-сообщение |
| `spotify_search_failed` | ERROR | Ошибка поиска (permanent/transient) |
| `spotify_follow_up_enqueue_failed` | ERROR | Не удалось отправить follow-up |

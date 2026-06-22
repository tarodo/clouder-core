# Перенос сбора YouTube-комментариев на финализацию триажа + показ в плеере категорий

**Дата:** 2026-06-22
**Статус:** одобрен к реализации (ожидает ревью спека)

## Контекст

YouTube-комментарии для треков собираются асинхронным воркером
(`comments_collect_handler`) в таблицы `comment_collections` / `external_comments`.
Сегодня сбор запускается из двух мест:

1. **Vendor-match worker** (`vendor_match_handler._maybe_dispatch_comments`,
   строки 136 и 177) — автоматически после успешного ISRC/fuzzy матча трека на
   YouTube-видео (vendor `ytmusic`).
2. **Ручной accept матча** (`curation_handler._handle_resolve_match`, строка 376) —
   когда пользователь вручную подтверждает совпадение.

Vendor-match, в свою очередь, ставится в очередь при **добавлении трека в плейлист**
(`curation_handler._enqueue_ytmusic`, вызовы на строках 929 и 1137). Поэтому с точки
зрения пользователя комментарии «появляются после добавления трека в плейлист».

Финализация триажа (`POST /triage/blocks/{id}/finalize` →
`TriageRepository.finalize_block`) промоутит треки из активных `STAGING`-бакетов в
категории (`category_tracks`, с `source_triage_block_id = block_id`) и асинхронно
запускает per-block фан-аут обогащения через воркер `auto_enrich_dispatch`
(label + artist enrichment).

## Цели

- **Собирать комментарии раньше в воркфлоу** — чтобы они были готовы уже к этапу
  курации категорий (до сборки плейлистов), а не после.
- **Охват:** только треки, промоутнутые в категории на финализации (STAGING → категория).
- **Триггеры:** финализация триажа + ручной accept. Авто-дёрганье из vendor-match
  убрать.
- **Показывать комментарии в плеере категорий** (сейчас они есть только в плеере
  плейлистов).

## Не-цели

- Не меняем механику самого сбора комментариев (provider, fallback на альтернативные
  видео, лимиты, бюджет в 1 запрос).
- Не меняем vendor-match как механизм резолва видео для публикации в YT Music — он
  по-прежнему запускается при добавлении в плейлист.
- Не трогаем плеер плейлистов / бакетов / curate.
- Без новых таблиц и миграций схемы.

## Принятые решения (из брейншторма)

1. **Главная цель** — комментарии готовы раньше (к курации категорий).
2. **Охват** — только промоутнутые в категории треки.
3. **Старые триггеры** — финализация + ручной accept; авто-дёрганье из vendor-match
   убрать.
4. **Резолв видео — развязанный подход (decoupled):** comment-воркер сам резолвит
   видео по метаданным трека (артист + название + длительность), **без зависимости от
   vendor-match**.

### Почему развязка, а не флаг на vendor-match

Изначально рассматривался вариант «засидить» сбор комментариев videoId из
ytmusic-матча (флаг `collect_comments` в `VendorMatchMessage`). От него отказались:

- Способность найти видео по артисту+названию **уже есть** в comment-провайдере —
  `YouTubeCommentsProvider.resolve_alternate_videos` (`providers/youtube/comments.py:90`)
  ищет видео в YT Music тем же скорером `score_candidate`, что и vendor-match. Сейчас
  она используется лишь как fallback, когда у засиженного «art track»-видео
  комментарии отключены.
- «Art track» / «- Topic» видео из ytmusic-матча **часто имеют комментарии
  отключёнными**, поэтому засиженный videoId всё равно бесполезен и fallback-поиск
  запускается. Для комментариев нужно обычное видео, которое и находит поиск.
- Поиск (`resolve_alternate_videos`) идёт через `ytmusicapi` (неофициальный клиент,
  скрейп YT Music) и **не расходует квоту YouTube Data API**. Квоту ест только
  `collect` (`commentThreads.list`). Поэтому развязка по квоте практически бесплатна.

Развязка проще: финализация и vendor-match не усложняются, нет флага в сообщении
матча и нет краевого случая «матч открыл review → комментарии только после ручного
accept».

## Архитектура

```
finalize API (_finalize_triage_block)
  ├─ promote STAGING → categories                       (как сейчас)
  └─ enqueue_block_auto_enrich({block_id, user_id})  →  auto_enrich_dispatch queue
        │
auto_enrich_dispatch_handler  (async worker, off request path)
  ├─ try_dispatch_for_triage_block            (labels — как сейчас)
  ├─ try_dispatch_artists_for_triage_block    (artists — как сейчас)
  └─ try_dispatch_comments_for_triage_block   (НОВОЕ)
        └─ для каждого промоутнутого трека:
             try_dispatch_comment_collection(track_id, platform="youtube")   # без video_id
                 │
comments_collect queue → comments_collect worker
  └─ video_id пустой → resolve_alternate_videos(artist, title, duration) → лучшее видео
       → collect (+ существующий fallback на другие альтернативы)
```

Финализация остаётся миллисекундной: вся работа в async-воркере, который уже бежит на
каждый финал-блок.

## Изменения — backend

### 1. Сделать `video_id` опциональным (резолв по метаданным)

**`src/collector/comments/messages.py`** — `CommentCollectMessage.video_id: str = ""`
(пустая строка = резолвить по метаданным). `ConfigDict(extra="ignore")` уже есть →
старые in-flight сообщения с непустым `video_id` парсятся без изменений.

**`src/collector/comments/dispatch.py`** —
`try_dispatch_comment_collection(*, track_id, video_id="", platform="youtube", user_id=None)`:
- убрать ранний выход `if not video_id: return` (строка 52);
- разрешить пустой `video_id` в `start_collection` и в `CommentCollectMessage`.

**`src/collector/comments/repository.py`** — `start_collection` (строки 48–83):
скорректировать гард идемпотентности. Сейчас повтор пропускается только при
`status == 'collected' AND external_video_id == video_id`. Новое поведение:
- если `video_id` пустой → пропускать, когда для `(track_id, platform)` уже есть строка
  со `status == 'collected'` (с любым `external_video_id`);
- если `video_id` непустой (путь сида из ручного accept) → текущее поведение.

Это чинит идемпотентность при повторной финализации блока.

### 2. Воркер резолвит основное видео поиском, когда сида нет

**`src/collector/comments_collect_handler.py`** — `_resolve_and_collect`
(строки 35–72): если `primary_video_id` пустой:
- если `meta is None` → вернуть статус `"failed"` (нет метаданных — резолвить не из
  чего); сохранить с ошибкой вроде `"no track metadata"`;
- иначе вызвать `provider.resolve_alternate_videos(artist, title, duration_ms,
  exclude_video_id="")`, взять **лучший** (топ-1) результат как основное видео и
  продолжить существующей логикой (collect; на `CommentsDisabledError` — fallback на
  остальные альтернативы, исключая выбранное);
- если поиск ничего не вернул (нет кандидатов ≥ порога) → новый статус `"no_video"`,
  сохранить пустой список без ошибки.

Резолв основного видео берёт **топ-1** результат поиска (лучший по скореру);
существующий fallback на остальные альтернативы остаётся как есть на случай отключённых
комментариев у топ-1.

Рекомендуется выделить хелпер `_resolve_primary(provider, meta, seed) -> str | None`,
чтобы `_resolve_and_collect` оставался читаемым.

Статус `"no_video"`: колонка `comment_collections.status` — `TEXT` без enum-ограничения
в схеме, поэтому новое значение требует правок только в коде (worker + сериализация
ответа read-роута, если она маппит статусы — проверить
`curation_handler._handle_list_track_comments` и OpenAPI enum).

### 3. Фан-аут на финализации

**`src/collector/comments/auto_dispatch.py`** (НОВЫЙ модуль, зеркало
`label_enrichment/auto_dispatch.py`):
`try_dispatch_comments_for_triage_block(*, block_id, user_id)`:
- best-effort (`_safe`), никогда не роняет воркер;
- перечислить промоутнутые треки блока новым repo-методом
  `promoted_track_ids_for_block(block_id, user_id)`:
  ```sql
  SELECT ct.track_id
  FROM category_tracks ct
  JOIN categories c ON c.id = ct.category_id
  WHERE ct.source_triage_block_id = :block_id AND c.user_id = :user_id
  ```
- для каждого трека вызвать `try_dispatch_comment_collection(track_id=tid,
  platform="youtube")` (без `video_id`). Идемпотентно.

`promoted_track_ids_for_block` добавить в `CommentsRepository`
(`comments/repository.py`) — модуль `comments/auto_dispatch.py` всё равно строит этот
репозиторий, держим перечисление промоутнутых треков рядом со сбором.

**`src/collector/auto_enrich_dispatch_handler.py`**: добавить вызов
`try_dispatch_comments_for_triage_block(block_id=block_id, user_id=user_id)` рядом с
label/artist диспетчерами.

### 4. Убрать комментарии из vendor-match

**`src/collector/vendor_match_handler.py`**: удалить функцию `_maybe_dispatch_comments`
(строки 70–78), оба её вызова (строки 136 и 177) и импорт
`from .comments.dispatch import try_dispatch_comment_collection` (строка 13).
Vendor-match больше не касается комментариев. Флаг в `VendorMatchMessage` **не вводится**.

### 5. Без изменений

Ручной accept (`curation_handler._handle_resolve_match`, строка 376) остаётся как есть —
передаёт выбранный пользователем videoId как сид
(`video_id=body.vendor_track_id`). Путь сида (непустой `video_id`) сохраняется.

## Изменения — frontend

Всё необходимое уже есть и используется в плеере плейлистов: read-роут
`GET /tracks/{track_id}/comments`, хук `useTrackComments`
(`frontend/src/features/playlists/hooks/useTrackComments.ts`) и компонент
`CommentsPanel` (`frontend/src/features/playlists/components/CommentsPanel.tsx`,
уже рендерится в `PlaylistPlayerPanel.tsx:238`).

**`frontend/src/features/categories/components/CategoryPlayerPanel.tsx`**:
- импортировать `CommentsPanel` из `../../playlists/components/CommentsPanel`;
- отрендерить `<CommentsPanel trackId={current.id} />` сразу после
  `<ArtistsPanel artists={effectiveRich?.artists ?? []} />` (строка 292) — консистентно
  с плеером плейлистов. `CommentsPanel` сам обрабатывает состояния
  pending/empty/disabled/failed.

Новых компонентов, хуков, API-роутов и типов не требуется.

## Инфраструктура

- **`infra/lambda.tf`** — Lambda `auto_enrich_dispatch_worker`: добавить env
  `COMMENT_COLLECT_QUEUE_URL = aws_sqs_queue.comments_collect.url` (воркер теперь шлёт
  в очередь сбора комментариев).
- **`infra/iam.tf`** — убедиться, что роль `collector_lambda` имеет `sqs:SendMessage`
  на `aws_sqs_queue.comments_collect` (роль уже шлёт в label/artist очереди; при
  необходимости расширить ARNs).
- Vendor-match queue воркеру auto-enrich **не нужна** (развязка) — добавляется только
  `COMMENT_COLLECT_QUEUE_URL`.

## Краевые случаи

- **Видео не найдено** (нет кандидатов ≥ порога): статус `"no_video"`, видно в БД и
  через read-роут. Комментариев нет (видео нет — иначе никак).
- **Уже собрано** для `(track_id, youtube)`: `start_collection` вернёт None → skip,
  включая повторную финализацию блока.
- **Нет метаданных трека**: статус `"failed"` с понятной ошибкой.
- **Двойной матч/публикация**: vendor-match по-прежнему ставится при добавлении в
  плейлист — это нужно для публикации и не зависит от комментариев.
- **Трек попал в категорию мимо триажа** (не через финализацию): комментарии для него
  не дёрнутся автоматически; остаётся ручной accept.

## Тестирование

### Backend (pytest)

- `CommentCollectMessage`: парсит старый payload с непустым `video_id` и новый с пустым.
- `try_dispatch_comment_collection`: вызов без `video_id` ставит сообщение с пустым
  видео и создаёт pending-коллекцию; пропуск, когда уже `collected` (новый гард).
- `start_collection`: пустой `video_id` + существующая `collected`-строка → None
  (skip); пустой `video_id` без строки → создаёт pending; непустой `video_id` → текущее
  поведение.
- `_resolve_and_collect`: (а) пустой сид + meta + поиск находит → collect с найденным
  видео; (б) пустой сид + поиск пуст → `"no_video"`; (в) пустой сид + нет meta →
  `"failed"`; (г) непустой сид → поведение без изменений (collect + fallback).
- `try_dispatch_comments_for_triage_block`: перечисляет промоутнутые треки и дёргает
  сбор для каждого; пустой блок → no-op; внутренняя ошибка не всплывает.
- `auto_enrich_dispatch_handler`: новый вызов выполняется для каждого record.
- `vendor_match_handler`: регрессия — сбор комментариев из матча больше не дёргается
  (ни ISRC, ни fuzzy путь).
- `promoted_track_ids_for_block`: возвращает только треки блока, скоупленные по
  `user_id`.

### Frontend (vitest + typecheck + lint)

- `CategoryPlayerPanel.test.tsx`: замокать `CommentsPanel` (как уже моканы
  `ArtistsPanel`/`LabelTile`) и проверить, что он рендерится с `trackId` текущего трека.
- Гейты: `pnpm typecheck && pnpm lint && pnpm test` из `frontend/`.

## Порядок реализации (черновик)

1. Backend: опциональный `video_id` (messages/dispatch/repository) + воркер-резолв +
   статус `"no_video"`.
2. Backend: `comments/auto_dispatch.py` + `promoted_track_ids_for_block` + вызов в
   `auto_enrich_dispatch_handler`.
3. Backend: убрать `_maybe_dispatch_comments` из vendor-match.
4. Infra: env + IAM для `auto_enrich_dispatch_worker`.
5. Frontend: `CommentsPanel` в плеере категорий + тест.
6. Если меняется enum статусов в OpenAPI — регенерировать
   `scripts/generate_openapi.py` и `frontend/src/api/schema.d.ts`.

## Открытые вопросы

Нет — решения по резолву (топ-1) и размещению `promoted_track_ids_for_block`
(`CommentsRepository`) зафиксированы выше.

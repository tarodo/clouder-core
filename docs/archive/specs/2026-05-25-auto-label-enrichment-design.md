# Автоматический поиск по лейблам — дизайн

- **Дата:** 2026-05-25
- **Статус:** утверждён к реализации
- **Область:** backend (`src/collector/`), frontend (`frontend/`), миграции (`alembic/`), OpenAPI

## Проблема и цель

Сейчас обогащение лейблов (label enrichment, в коде — «поиск по лейблам») запускается только вручную: админ выбирает лейблы в бэклоге, открывает `EnqueueDrawer`, задаёт вендоров/модели/промпт и стартует пачку. Лейблы новых треков, которые курируют пользователи, не обогащаются, пока админ не сделает это руками.

Цель — автоматически отправлять лейбл на поиск, когда пользователь добавляет трек в категорию, **если по этому лейблу поиска ещё не было**. Параметры авто-поиска (вендоры, модели, промпт, модель саммари) настраиваются админом в новом окне.

Эта фича — первый из трёх типов авто-поиска. Окно настроек сразу имеет вкладки **Лейблы**, **Артисты**, **Треки**; в этой итерации активна только вкладка «Лейблы», остальные — заглушки.

## Контекст: как устроен ручной поиск (переиспользуем)

- Запуск: `POST /admin/labels/enrich` → `handle_post_enrich` (`src/collector/label_enrichment/routes.py:61`). Создаёт run в `clouder_label_enrichment_runs` через `repo.create_run(RunSpec)` и шлёт по одному SQS-сообщению на лейбл в очередь `LABEL_ENRICHMENT_QUEUE_URL`. Сообщение: `{run_id, label_id, label_name, style}`.
- Конфиг enqueue (`EnrichLabelsRequestIn`, `src/collector/label_enrichment/messages.py:40`): `labels[]`, `vendors[]`, `models{vendor:model}`, `prompt_slug`, `prompt_version`, `merge_vendor`, `merge_model`.
- Опции формы: `GET /admin/labels/enrich/options` → `handle_get_options` (`routes.py:266`): `vendors=["gemini","openai","tavily_deepseek"]`, `prompt_versions`, `default_models`, `merge={vendor:"deepseek", default_model:...}`.
- Worker обрабатывает сообщения асинхронно, по завершении merge пишет результат в `clouder_label_info` (статусы бэклога: `none` / `completed` / `outdated`).
- Frontend: `EnqueueDrawer` (`frontend/src/features/admin/components/enrichment/EnqueueDrawer.tsx`), хуки `useEnrichmentOptions`, `useEnqueueEnrichment`; страница бэклога `AdminEnrichmentBacklogPage.tsx`.
- Связь трек→лейбл: `category_tracks.track_id` → `clouder_tracks.album_id` → `clouder_albums.label_id` → `clouder_labels`.
- Admin-роуты гейтятся набором `_ADMIN_ROUTES` в `src/collector/handler.py`.

Авто-поиск переиспользует пайплайн без изменений в worker, кроме одного небольшого добавления (см. ниже): тот же run, та же очередь, тот же merge.

## Ключевые решения

1. **Дедуп.** Лейбл считается «уже искали» (авто-поиск пропускается), если есть готовый merged-результат. При провале прошлого авто-поиска делаем **ровно один** ретрай — токены не жжём. In-flight (поиск уже в очереди/выполняется) пропускаем.
2. **Включение.** Явный тоггл `Enabled` на окне настроек, по умолчанию **OFF**. Пока OFF (или конфиг не сохранён) — добавление трека ничего не триггерит.
3. **Группировка в runs.** Каждый диспетч создаёт один run с пометкой `source='auto'`. Основной поток — финализация триажа: много треков разом → лейблы ищутся блоком одним раном. Одиночный add — частный случай (1 лейбл). В списке runs добавляется фильтр по `source`.
4. **Архитектура — inline best-effort (подход A).** Хелпер вызывается прямо из пути курации **после** коммита, только ставит задачи в очередь (несколько Data API запросов + SQS-батч, доли секунды). Сам LLM-поиск идёт фоном в worker — финализация не ждёт результатов, пользователь получает треки сразу. Падение авто-поиска не ломает курацию.

## Модель данных

### Новая таблица `auto_enrich_config` (singleton по типу)

Одна строка на тип авто-поиска. В этой итерации заполняется только `labels`.

| колонка | тип | смысл |
|---|---|---|
| `kind` | text PK | `'labels'` \| `'artists'` \| `'tracks'` |
| `enabled` | bool not null default false | мастер-тоггл |
| `vendors` | jsonb not null default `'[]'` | как в ручном enqueue |
| `models` | jsonb not null default `'{}'` | `{vendor: model}` для поиска |
| `prompt_slug` | text | промпт |
| `prompt_version` | text | версия промпта |
| `merge_vendor` | text | вендор саммари (пока `'deepseek'`) |
| `merge_model` | text | модель саммари |
| `updated_at` | timestamptz not null | аудит |
| `updated_by_user_id` | uuid/text null | кто менял |

### Новая таблица `label_auto_enrich_state` (атомарный claim + счётчик ретраев + in-flight гард)

| колонка | тип | смысл |
|---|---|---|
| `label_id` | PK FK → `clouder_labels.id` | лейбл |
| `attempts` | int not null default 0 | сколько авто-ранов запущено |
| `status` | text | `'queued'` \| `'completed'` \| `'failed'` |
| `last_run_id` | FK → `clouder_label_enrichment_runs.id` null | последний авто-ран |
| `first_enqueued_at` | timestamptz | первое попадание в авто-поиск |
| `updated_at` | timestamptz not null | время |

### Новая колонка на `clouder_label_enrichment_runs`

- `source` text not null default `'manual'` — значения `'manual'` / `'auto'`. Для фильтра в списке runs.

Миграция — новый файл в `alembic/versions/` (следующий порядковый номер после `20260522_24`).

## Диспетч и дедуп

Новый модуль (например `src/collector/label_enrichment/auto_dispatch.py`), функция:

```
dispatch_labels(label_ids: set[str], *, source_hint: str, user_id: str | None) -> None
```

Шаги:

1. **Читаем конфиг** `auto_enrich_config['labels']`. Если строки нет или `enabled = false` → лог `auto_enrich_skipped_disabled` и выход.
2. **Атомарный claim** — один `INSERT ... ON CONFLICT (label_id) DO UPDATE ... WHERE ... RETURNING label_id` сразу по всем `label_ids`. Застолбляются только подходящие:
   - есть готовый результат в `clouder_label_info` (status `completed`/`outdated`) → **skip** (искали раньше, в т.ч. вручную);
   - строки state нет → claim: `attempts = 1`, `status = 'queued'`, `first_enqueued_at = now`;
   - `state.status = 'failed'` и `attempts < 2` → claim ретрая: `attempts = attempts + 1`, `status = 'queued'`;
   - `state.status = 'queued'` → in-flight → **skip**;
   - `state.status = 'completed'` → **skip**.

   `RETURNING` отдаёт реально застолблённые `label_id`. Гонка двух одновременных add/finalize по одному лейблу закрыта: выигрывает единственный writer, прошедший условие `ON CONFLICT ... WHERE`.
3. Если застолблённых **0** → выход.
4. Иначе резолвим имя и style каждого застолблённого лейбла (как в ручном пути: `derive_style_for_label` → fallback `"music"`), создаём **один** run: `create_run(RunSpec(..., source='auto', config из auto_enrich_config))`, затем шлём `SQS SendMessageBatch` (по ≤10 в вызове) в существующую `LABEL_ENRICHMENT_QUEUE_URL` — те же сообщения `{run_id, label_id, label_name, style}`.
5. Всё тело обёрнуто в `try/except`: исключение логируется (`auto_enrich_dispatch_error`), курация возвращает успех.

Лог успеха: `auto_enrich_dispatched` с `{claimed, skipped, run_id, source_hint}`.

### Один тач worker'а

При завершении рана worker проставляет `label_auto_enrich_state.status` для лейблов рана: `queued` → `completed` (merge успешен) или `failed` (ошибка). Это снимает in-flight и открывает ровно один ретрай при провале. `RunSpec` несёт `source`, чтобы worker трогал state только для авто-ранов (для ручных — не обязательно, но безвредно).

## Точки врезки (триггеры)

### Финализация триажа

`triage_repository.finalize_block` (`src/collector/curation/triage_repository.py:530`) уже собирает `track_ids` всех промоутнутых треков по staging-бакетам. После коммита транзакции:

1. Один запрос distinct `label_id` по этим `track_ids` через `clouder_albums`.
2. `auto_dispatch.dispatch_labels(label_ids, source_hint='triage', user_id=...)`.

Вызов — best-effort, после коммита, чтобы треки уже были сохранены и ответ `_finalize_triage_block` (`curation_handler.py:1309`) не зависел от исхода поиска. Удобнее всего вернуть собранные `track_ids`/`label_ids` из `finalize_block` и звать диспетч в хендлере (после успешного return репозитория), либо звать диспетч в хендлере по результату запроса лейблов.

### Одиночное добавление трека

`_handle_add_track` (`curation_handler.py:551`): после `repo.add_track(...)` → резолв одного `label_id` трека → `dispatch_labels({label_id}, source_hint='single', user_id=...)`. Частный случай батча (1 лейбл → run из 1).

Оба места оборачивают вызов в best-effort.

## Админ-API

Оба роута — admin-only (добавить в `_ADMIN_ROUTES` и диспетчер `handler.py`), зарегистрировать в `scripts/generate_openapi.py:ROUTES`.

- `GET /admin/auto-enrich/labels` → текущий конфиг + те же опции, что `/admin/labels/enrich/options` (`vendors`, `prompt_versions`, `default_models`, `merge`). Если строки конфига нет — отдаём дефолты и `enabled=false`.
- `PUT /admin/auto-enrich/labels` → апсерт конфига: `enabled`, `vendors`, `models`, `prompt_slug`, `prompt_version`, `merge_model` (вендор саммари фиксирован `deepseek`, как сейчас). Валидация — переиспользуем правила `EnrichLabelsRequestIn` (непустые vendors при `enabled=true`, известный `prompt_slug`).

Пути для `artists`/`tracks` не заводим, пока вкладки не активны.

После правки роутов — регенерация `docs/api/openapi.yaml` и `frontend/src/api/schema.d.ts` (`PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`).

## Окно настроек (frontend)

Новый роут `/admin/auto-enrich` в `features/admin`. Mantine `Tabs` с тремя вкладками:

- **Лейблы** — активна.
- **Артисты**, **Треки** — `disabled`, заглушка «скоро».

Вкладка «Лейблы»:

- `Switch` **Enabled** сверху.
- Ниже — те же контролы, что в `EnqueueDrawer`: чекбоксы `vendors`, `Select` промпта, `TextInput` модели на каждого вендора, merge: `Badge` `deepseek` + `TextInput` модели.
- Кнопка **Save** → `PUT`.

**Рефактор:** вынести контролы конфига из `EnqueueDrawer` в переиспользуемый компонент `EnrichConfigForm`. Его используют и `EnqueueDrawer` (ручной запуск), и новое окно (настройка авто). `EnqueueDrawer` сохраняет свою кнопку запуска и список выбранных лейблов; окно настроек — тоггл + Save.

Хуки рядом с существующими: `useAutoEnrichConfig` (GET), `useSaveAutoEnrichConfig` (PUT).

## Края и обработка ошибок

- **Трек без альбома/лейбла** (`album_id` null или `albums.label_id` null) → лейбл не резолвится, молча пропускаем.
- **`enabled=true`, но конфиг битый/неполный** → `PUT` отклоняет на валидации; при диспетче с битым конфигом — лог и выход (курация не страдает).
- **Ретрай-кап:** после второго провала (`attempts = 2`, `status='failed'`) лейбл больше не триггерится авто — только ручной enqueue из бэклога.
- **Дубли в батче финализации:** distinct по `label_id` до claim + атомарный claim снимают и внутрибатчевые, и межзапросные дубли.
- **Best-effort:** любое исключение в диспетче логируется и проглатывается; курация всегда успешна.

## Наблюдаемость

Структурные события (через существующий `log_event`):

- `auto_enrich_dispatched` — `{claimed, skipped, run_id, source_hint}`.
- `auto_enrich_skipped_disabled` — конфиг выключен/отсутствует.
- `auto_enrich_dispatch_error` — поймано исключение в best-effort обёртке.

## Тестирование

**Unit (Data API замокан):**

- claim-логика: первый запуск; ретрай после `failed` при `attempts<2`; skip при `completed` в `label_info`; skip при `status='queued'` (in-flight); skip при достижении кап (`attempts=2`); гонка дублей (двойной claim даёт один claimed).
- пустой набор `label_ids` → no-op;
- `enabled=false`/нет конфига → no-op + лог;
- трек без лейбла → пропуск;
- батч финализации с несколькими лейблами → один run, корректные SQS-сообщения;
- worker обновляет `label_auto_enrich_state.status` на исход рана.

**Frontend:**

- рендер окна: вкладка «Лейблы» активна, «Артисты»/«Треки» `disabled`;
- save-флоу: загрузка конфига, изменение, `PUT`, нотификация;
- `EnrichConfigForm` рендерится одинаково в `EnqueueDrawer` и в окне настроек.

## За рамками этой итерации

- Активные вкладки **Артисты** и **Треки** (та же модель: свой `kind` в `auto_enrich_config`, свой диспетч и точка врезки).
- Дебаунс/агрегация частых одиночных add (сейчас каждый add — потенциальный диспетч; claim-таблица защищает от дублей, отдельный дебаунс не нужен).
- Полностью нулевой оверхед на путь курации (потребовал бы асинхронного диспетчера — подход B).

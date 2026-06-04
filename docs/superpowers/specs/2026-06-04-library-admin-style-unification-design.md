# Дизайн: единый стиль Library + Admin

**Дата:** 2026-06-04
**Статус:** утверждён (brainstorming), ждёт плана реализации
**Область:** `frontend/src/features/library`, `frontend/src/features/admin`, `frontend/src/components`

## Контекст и проблема

Дизайн-система проекта (`frontend/src/theme.ts` + `frontend/src/tokens.css`) — сильная и
полная: семантические токены, шкала отступов `theme.other.space`, типографика, тёмная тема
и акцент через CSS-переменные. Проблема **не в системе, а в неровном её применении** на
страницах Library, detail артиста/лейбла и Admin. Пользователь (в роли дизайнера) ощущает
отсутствие единого стиля и небрежное исполнение.

Аудит выявил 6 очагов расхождений:

1. **Ширина / контейнер.** Library-страницы обёрнуты в `Container size="xl"/"lg"`, Admin-страницы
   контейнера не имеют и растекаются во всю ширину `AppShell.Main` → ощущение «разных приложений».
2. **Иерархия заголовков.** `Title order={2}` на Library и Admin Coverage/Spotify-Not-Found, но
   `order={3}` на Admin Backlog/Runs/Auto-enrich → размер заголовка «прыгает» между разделами.
3. **Дублирование в шапках detail.** AI-тултип захардкожен inline-объектами стилей в трёх местах:
   `library/lib/aiContent.tsx`, `library/components/LabelDetailHeader.tsx`,
   `library/components/LabelTile.tsx`. `ArtistDetailHeader` делегирует в общий `AiContentBadge` и
   выглядит «причёсанным», `LabelDetailHeader` переписан руками.
4. **Состояния.** Загрузка: Skeleton у Library-таблиц, у части Admin — ничего. Пусто: где-то
   `EmptyState`, где-то голый `Text c="dimmed"`, где-то ничего. Ошибка: где-то `Text c="red"`,
   где-то нет.
5. **Хардкод вместо токенов.** `w={320}` (ArtistTile/LabelTile), `minWidth: 200/240/180`
   (LibraryFilters), `whiteSpace: 'pre-wrap'` (×4), строковые `'white'/'black'`, разнобой
   `gap={4}` / `gap={6}`. Сырые значения не тянутся за тёмной темой и акцентом.
6. **Tile vs Card.** `ArtistTile`/`LabelTile` прибиты к `w={320}` (не адаптивны), `ArtistCard`/
   `LabelCard` — резиновые. Списки выглядят по-разному в зависимости от использованного примитива.

## Цель и не-цель

**Цель:** убрать ощущение «разных приложений» и небрежности — единый каркас, единая шапка, единые
состояния, токены вместо хардкода. Уровень амбиций: **консистентность + лёгкий полиш** (без редизайна).

**Не-цель:**
- Редизайн визуала, новые экраны, смена навигации.
- Переверстка таблиц по содержанию (колонки, сортировки, пагинация остаются как есть).
- Изменение бизнес-логики, хуков данных, роутинга.

## Контракт стиля (7 правил)

1. **Ширина.** Списки и таблицы (Library list, Artists list, все 10 Admin-страниц) —
   `Container size="xl" py="md"`. Detail артиста и лейбла — `Container size="lg" py="md"` (узкий,
   читабельнее для био-текста). Решение осознанное (вариант «ширина по типу»).
2. **Шапка.** Общий компонент `PageHeader` со слотами:
   back-link (только detail) → `Title order={2}` + бейджи → справа слот действий → подзаголовок
   (`c="dimmed"`, `size="sm"`) → нижний слот для Tabs / Filters / Toolbar.
3. **Заголовки.** `order={2}` на всех страницах. Admin Backlog/Runs/Auto-enrich: `order={3}` →
   `order={2}` + короткий подзаголовок-описание раздела (Admin получает подзаголовки).
4. **Состояния.**
   - Загрузка: Skeleton по форме контента; detail-страницы — `FullScreenLoader`. Без «пустых дыр».
   - Пусто: компонент `EmptyState` (инлайн-режим для пустых таблиц, полноэкранный — для 404).
   - Ошибка: единый `Alert` с действием «Повторить». Не «красный текст» в одном месте и «ничего» в другом.
5. **Сущности.** `ArtistTile`/`LabelTile` + `ArtistCard`/`LabelCard` → один резиновый `EntityTile`.
   Убрать `w={320}`, ширину отдать сетке/контейнеру.
6. **AI-бейдж.** Единственный источник — `AiContentBadge`. `LabelDetailHeader` и `LabelTile`
   перестают дублировать inline-тултип и используют общий компонент.
7. **Токены.** Убрать `minWidth: 200/240/180` → `maw`; `whiteSpace: 'pre-wrap'` (×4) → общий
   util/className `prewrap`; `'white'/'black'` → семантические токены; разнобой `gap={4}/{6}` →
   `theme.other.space` / именованные ключи. Где нужно raw-значение — через токен-шкалу.

## Затронутые и новые компоненты

### Новые
- **`PageHeader`** — `frontend/src/components/PageHeader.tsx`. Пропсы (слоты):
  - `backTo?: { onClick: () => void; label: string }` — рендерит `Anchor`-back, только detail.
  - `title: ReactNode` — `Title order={2}`.
  - `badges?: ReactNode` — инлайн рядом с заголовком (AI-бейдж, статус).
  - `actions?: ReactNode` — правый слот (кнопки, preference-кнопки).
  - `subtitle?: ReactNode` — строка метаданных / описания раздела (`c="dimmed"`, `size="sm"`).
  - `children?: ReactNode` — нижний слот (Tabs / Filters / Toolbar), без смены внешнего ритма.
  - Внутренний ритм: `Stack gap="xs"`, верхняя строка — `Group justify="space-between"`.
- **`EntityTile`** — слияние `ArtistTile`/`LabelTile`/`ArtistCard`/`LabelCard`. Резиновая ширина
  (ширину задаёт родительская сетка/`Container`), один набор слотов под имя, бейджи, метаданные,
  preference-кнопки. Размещение: `frontend/src/features/library/components/EntityTile.tsx`.
- **`prewrap`** — общий util или CSS-класс для `white-space: pre-wrap` вместо 4× inline-стиля.
  Кандидат: добавить класс в `tokens.css` / общий `*.module.css`, либо хелпер-стиль.

### Изменённые
- **`EmptyState`** (`frontend/src/components/EmptyState.tsx`) — сейчас полноэкранный
  (`Center mih="60vh"`). Добавить лёгкий **инлайн-режим** (`variant?: 'page' | 'inline'`,
  default `'page'`) без `60vh` для пустых таблиц. Полноэкранный остаётся для 404 detail.
- **`AiContentBadge`** (`frontend/src/features/library/lib/aiContent.tsx`) — единственный рендер
  AI-бейджа и тултипа. Внутренние хардкод-цвета (`'white'/'black'`, padding-литералы) перевести
  на семантические токены. Экспорт переиспользуют `LabelDetailHeader` и `LabelTile`.
- **`LabelDetailHeader`** — переписать под паттерн `ArtistDetailHeader` (back → H2 → `AiContentBadge`
  → preference/actions → метаданные), убрать inline-тултип.
- **`ArtistDetailHeader` / `LabelDetailHeader`** — обернуть в `PageHeader` (или построить из его
  слотов), чтобы шапки detail и списков делили один компонент.
- **`LibraryFilters`** — `style={{ minWidth: ... }}` → `maw`.

## Изменения по областям

### Library lists (`LibraryListPage`, `ArtistsListPage`)
- Заголовок + `EntityTabs` + `LibraryFilters` собрать в `PageHeader` (`title` = заголовок,
  нижний слот = `EntityTabs`, ниже — `LibraryFilters`). `Container size="xl"` уже на месте.
- `LibraryFilters`: `minWidth` → `maw`.
- Пустая таблица → `EmptyState variant="inline"` (внутри `LabelsTable`/`ArtistsTable` или на странице).

### Artist / Label detail (`ArtistDetailPage`, `LabelDetailPage`)
- `Container size="lg" py="md"` (уже на месте, проверить ровность).
- `LabelDetailHeader` → паттерн Artist + `AiContentBadge`; обе шапки на `PageHeader`.
- 404 / отсутствие сущности → `EmptyState variant="page"`.
- `whiteSpace: 'pre-wrap'` в `ArtistOverviewTab`/`LabelOverviewTab`/тайлах → `prewrap`.

### Admin (10 страниц)
`AdminCoveragePage`, `AdminSpotifyNotFoundPage`, `AdminEnrichmentBacklogPage`,
`AdminEnrichmentRunsPage`, `AdminEnrichmentRunDetailPage`, `AdminArtistEnrichmentBacklogPage`,
`AdminArtistEnrichmentRunsPage`, `AdminArtistEnrichmentRunDetailPage`, `AdminAutoEnrichPage`,
плюс `AdminLayout`.
- Обернуть контент каждой страницы в `Container size="xl"` (или вынести Container в `AdminLayout`
  вокруг `Outlet`, оставив Tabs над ним — решается на этапе плана).
- `PageHeader` с `Title order={2}` + короткий подзаголовок-описание раздела.
- Добавить Skeleton там, где сейчас пусто (Backlog/Runs).
- Пустые состояния → `EmptyState variant="inline"`; ошибки → единый `Alert` с «Повторить».
- Пагинация «Load more» остаётся как есть (не-цель — не трогаем поведение).

### Токен-гигиена (сквозная)
- `w={320}` → удалить (резиновый `EntityTile`).
- `minWidth: 200/240/180` → `maw`.
- `whiteSpace: 'pre-wrap'` ×4 → `prewrap`.
- `'white'/'black'`, padding-литералы в тултипах → семантические токены.
- `gap={4}/{6}` вперемешку → именованные ключи (`xs`/`sm`) или `theme.other.space`.

## Проверка

- `cd frontend && pnpm test` (jsdom) — обязательно.
- `pnpm typecheck` и `pnpm lint` — обязательно перед мерджем (фронт-CI прогоняет tsc; vitest один не ловит typecheck/eslint).
- `pnpm test:browser` (Playwright, `*.browser.test.tsx`) — для `PageHeader`, `EntityTile` и
  состояний: jsdom не применяет стили и не доказывает визуал.
- Скриншоты до/после ключевых страниц (Library list, Artist detail, Label detail, Admin Runs).

## Последовательность (вход для плана реализации)

1. **Фундамент:** `PageHeader`, `EmptyState variant="inline"`, `prewrap` util + их browser-тесты.
2. **Library lists** на новый каркас (`PageHeader`, `maw` в `LibraryFilters`, пустая таблица).
3. **Artist/Label detail:** `AiContentBadge` как единый источник, `LabelDetailHeader` под паттерн
   Artist, `EntityTile` (слияние Tile/Card).
4. **Admin** (10 страниц) пачкой: Container, `PageHeader` + подзаголовки, Skeleton, EmptyState, Alert.
5. **Токен-чистка** сквозным проходом + полный прогон тестов/линта/typecheck.

## Открытые вопросы для этапа плана

- Контейнер Admin: оборачивать каждую страницу или вынести `Container` в `AdminLayout` вокруг `Outlet`.
- `prewrap`: CSS-класс в `tokens.css` vs util-хелпер.
- `EntityTile`: где сейчас используются `ArtistCard`/`LabelCard` vs `ArtistTile`/`LabelTile` — свести
  список потребителей перед слиянием (не сломать существующие места рендера).

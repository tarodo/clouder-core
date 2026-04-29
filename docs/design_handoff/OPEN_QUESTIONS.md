# OPEN QUESTIONS · CLOUDER iter-2a → frontend

Список вопросов, на которые дизайн осознанно не дал финальных ответов
и которые фронтендер должен либо уточнить с продуктом, либо реализовать
по-своему с пометкой в PR. Не блокеры — все имеют рабочий fallback.

---

## Q1 — Dark theme parity (iter-2a)

**Status:** дизайн отдал только light. Tokens.css содержит `.theme-dark`
ramp (готовый, проверенный визуально на Sprint-1 anchor scenes), но
production-страницы (P-04..P-25) в pages-catalog отрисованы только в
light.

**Что делать:** считать tokens.css canonical для dark, применять
`.theme-dark` на root и проверить визуально каждую страницу. На любые
расхождения (например, состояние `just-tapped` на DestinationButton в
dark, тени на Dialog в dark) — заводить тикет и просить дизайн.

---

## Q2 — Иконки

**Status:** в макетах используется кастомный inline-SVG `Icon` с ~20
именами (`play`, `pause`, `prev`, `next`, `chevron`, `close`, `search`,
`grid`, `list`, `filter`, `calendar`, `check`, …). Это design
placeholder, не библиотечный набор.

**Что делать:** взять **lucide-react** (рекомендация — уже в Mantine
ecosystem) или **@tabler/icons-react** и сделать 1:1 mapping. Размеры
(`size={12|14|16|18|20|22}`) сохранить. Названия иконок (`prev` →
`SkipBack`, `next` → `SkipForward`, и т.д.) — задокументировать в
`/components/icons.ts`.

---

## Q3 — DatePicker мобильный fullscreen vs popover

**Status:** P-15 Create Triage Block sheet содержит два DatePicker
(`date_from`, `date_to`). На desktop — popover (Mantine
`@mantine/dates` `DatePickerInput` стандартный). На mobile — макет
показывает full-screen sheet.

**Что делать:** Mantine `DatePickerInput` сам по себе на мобиле
отрисуется как popover. Для full-screen sheet поведения — обернуть в
`Drawer` с `position="bottom"` + custom `<DatePicker>` внутри. Уточнить
у дизайна, full-screen sheet это hard requirement или достаточно
default popover-поведения.

---

## Q4 — Reorder в Categories list (P-09)

**Status:** дизайн рисует ↑/↓ кнопки рядом с каждым пунктом. Бриф
явно говорит **no drag-and-drop**.

**Что делать:** реализовать через простые ↑/↓ ActionIcon, дёргающие
`PATCH /categories/{id}/reorder` (или batch reorder endpoint).
Disabled-состояние первой/последней позиции — уже в макете.

---

## Q5 — Web Playback SDK / device picker (P-25)

**Status:** макет статический. Реальная логика (когда показывать
"Open Spotify, transfer playback to CLOUDER", когда auto-connect, как
обрабатывать `transferPlayback` ошибку) — на стороне фронта.

**Что делать:** P-25 — единственный экран, где правда нужно проверять
SDK state. Критерии показа:

- `playerReady === false` → `connecting` state (skeleton)
- `playerReady === true && devices.length === 0` → empty state с
  инструкцией
- `playerReady === true && devices.length > 0` → list

Уточнить с бэкендом, как именно фронт получает список девайсов
(probably через Web Playback SDK напрямую, не через CLOUDER API).

---

## Q6 — Hotkey scope в Curate

**Status:** дизайн: `0` → DISCARD, `1`–`6` → staging categories,
`7`–`9` → NEW/OLD/NOT, `Space` → play/pause, `J/K` → prev/next, `U` →
undo, `?` → overlay, `Esc` → close.

**Edge case** не покрыт: что если у блока 7+ staging categories
(пользователь в House style имеет много жанров)?

**Что делать:** на момент iter-2a показывать только первые 6 staging
categories с хоткеями 1–6. Остальные доступны только через клик. В
hotkey overlay явно об этом сказать. Долгосрочно — отдельный тикет в
iter-2b на категории-без-хоткеев.

---

## Q7 — Just-tapped анимация

**Status:** макет показывает `just-tapped` state на DestinationButton
как accent-magenta заливку с scale(0.97). Длительность не указана.

**Что делать:** использовать `--motion-pulse: 80ms` (есть в tokens) +
плавный fade-out за `--motion-base: 160ms`. Реализуется через CSS
transition без `framer-motion`. Если попросят более выразительно —
flip-card / particle effect — это отдельный тикет.

---

## Q8 — Auto-advance в Curate

**Status:** бриф: "auto-advance to the next track" после выбора
destination. Время переключения не указано.

**Что делать:** 200ms задержки после `just-tapped` пика, потом
переключение на следующий трек + auto-play. Если пользователь успел
нажать `U` (undo) в эти 200ms — отменить переключение.

---

## Q9 — Долгие операции (P-15 create block, P-20 finalize)

**Status:** бриф B7 — "≥10s tolerance + creation may have succeeded —
refresh copy variant where applicable". Дизайн отрисовал generic
pending state (skeleton + "Creating block, this may take a moment…").

**Что делать:**

- **t < 5s:** spinner на CTA, остальной UI disabled.
- **5s ≤ t < 15s:** показать `<Loader>` поверх формы + копи "Cold
  start, hang on…".
- **t ≥ 15s:** показать "Это занимает дольше обычного. Если ничего не
  произойдёт — обновите страницу, блок мог уже создаться."

Точные тексты — у дизайна (или копирайтера). Сейчас в макете только
generic placeholder.

---

## Q10 — Mobile thumb-zone vs design intent в Curate

**Status:** дизайн положил DISCARD сверху (по запросу: "самая
частая кнопка должна быть первой"). На mobile это противоречит
thumb-zone (большой палец естественно тянется к нижней половине
экрана).

**Что делать:** оставить как в макете для iter-2a (visual hierarchy
важнее мускульной памяти на старте). Через 2 недели после релиза —
посмотреть Hotjar / posthog session-recordings: если пользователи
переключают руки чтобы дотянуться, делать тикет на reflow в iter-2b.

---

## Q11 — Theme switching без FOUC

**Status:** tokens.css использует CSS `:root` + `.theme-dark` class.
Mantine 7 имеет встроенный `ColorSchemeScript` для предотвращения
FOUC.

**Что делать:**

```tsx
// app/layout.tsx (Next.js) или index.html (Vite)
<head>
  <ColorSchemeScript defaultColorScheme="auto" />
  <link rel="stylesheet" href="/tokens.css" />
</head>
```

И слушать `useMantineColorScheme()` чтобы добавлять/убирать
`theme-dark` class на `<html>` или `<body>`.

---

## Q12 — Accent magenta scope

**Status:** tokens.css определяет `.accent-magenta` modifier. Дизайн
использовал её только в Sprint-1 anchor scenes (Now Playing dot,
just-tapped). В production pages (Pass2) accent опционален.

**Что делать:** добавить per-user setting в Profile / Settings (которая
будет в iter-2b). До тех пор — accent ВЫКЛЮЧЕН по умолчанию.
Применять `<body class="accent-magenta">` только за тоглом.

---

## Q13 — Empty states · "Coming soon" pages

**Status:** Library tab (mobile) и Profile / Settings — пока EmptyState
с "Coming soon". Дизайн дал generic exemplar в S-02.

**Что делать:** копировать exemplar 1:1, использовать тот же
`<EmptyState>` компонент (см. spec sheet § EmptyState). Ссылка "Back
to Home" — обязательна.

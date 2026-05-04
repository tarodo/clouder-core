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

**Что делать (зафиксированный фронт-fallback):**

iter-2a ship `defaultColorScheme="light"` — auto-detect системного dark отключён до визуальной QA. tokens.css `.theme-dark` остаётся как готовый ramp для iter-2b. Toggle переключения темы — отдельный тикет в Profile/Settings (iter-2b). Дизайн может перебить решение после визуальной QA production-страниц в dark; до тех пор любая попытка автодетекта = риск показать пользователю не отрисованное состояние.

---

## Q2 — Иконки

**Status (CLOSED · 2026-04-29):** выбрана `@tabler/icons-react`. Snippets в spec sheet уже использовали `IconPlayer*` имена — ratify de facto. Полный mapping (~22 имени) — в § Icon mapping в `04 Component spec sheet.html`. Re-export pattern через `src/components/icons.ts` зафиксирован.

---

## Q3 — DatePicker мобильный fullscreen vs popover

**Status:** P-15 Create Triage Block sheet содержит два DatePicker
(`date_from`, `date_to`). На desktop — popover (Mantine
`@mantine/dates` `DatePickerInput` стандартный). На mobile — макет
показывает full-screen sheet.

**Что делать (зафиксированный фронт-fallback):**

Custom-компонент `DateRangeField`: `useMediaQuery('(max-width: 64em)')` → на mobile рендерит `<Drawer position="bottom">` с inline `<DatePicker>`, на desktop — стандартный `<DatePickerInput>` с popover. ~30 строк wrapper'а. Совпадает с макетом. Дизайн может перебить, если full-screen sheet это hard requirement (запасной вариант: popover-везде, тоже работает на 420px wide, но без air space).

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

**Что делать (зафиксированный фронт-контракт):**

- Frontend держит Spotify access token in-memory (НЕ localStorage).
- Refresh через CLOUDER backend endpoint `/auth/spotify/refresh` за 5 минут до экспирации; endpoint должен вернуть `{access_token, expires_in}`. Это единственное, что нужно подтвердить с бэком — маленький параллельный запрос, не блокер handoff.
- `Spotify.Player` SDK инициализируется при mount AppShell.
- `playerReady` state из `player.addListener('ready', ...)` callback.
- Devices list: poll `getMyDevices` (Spotify Web API напрямую, не CLOUDER backend) каждые 30s + immediate refresh при window focus.
- Transfer playback: `transferMyPlayback` с device_id из picker.
- Errors:
  - `account_error` → P-03 Premium-required state.
  - `playback_error` → toast + retry кнопка.

Критерии показа P-25 device picker (как было в исходной формулировке):

- `playerReady === false` → `connecting` skeleton.
- `playerReady === true && devices.length === 0` → empty state с инструкцией "Open Spotify, transfer playback to CLOUDER".
- `playerReady === true && devices.length > 0` → list.

---

## Q6 — Hotkey scope в Curate

**Status (amended 2026-05-04 with F5):** дизайн: `0` → DISCARD,
`1`–`9` → staging categories по `position` ASC (active only),
`Q` / `W` / `E` → NEW / OLD / NOT, `Space` → open-in-Spotify
(placeholder; F6 promotes to play/pause), `J`/`K` → skip/prev,
`U` → undo (history depth 1), `?` → overlay, `Esc` → close overlay
or exit Curate, `Enter` → accept EndOfQueue suggestion (via
autoFocus on primary CTA, not global binding).

**Edge case покрыт:** если у блока > 9 staging categories, первые 9
получают хоткеи `1`–`9`, остальные доступны через "More categories…"
menu в DestinationGrid. Footer overlay явно сообщает об этом.

**Что делать (выполнено F5):** хоткеи биндятся через
`useCurateHotkeys` по `event.code` (layout-safe — Cyrillic / Dvorak
попадают на физическую позицию). `?` биндится через `event.key`
(shifted character, layout-dependent intent). Mobile (`< 64em`)
хоткеи не биндятся; кнопки заменяют их.

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

**Status (UPDATED 2026-04-29):** iter-2a ship `defaultColorScheme="light"` (см. Q1). FOUC не возникает потому что `ColorSchemeScript defaultColorScheme="light"` matches `MantineProvider defaultColorScheme="light"` — Mantine 9 inlines the value before hydration. Тёмная тема и переключатель прибудут с iter-2b; тогда же добавим `useMantineColorScheme()`-bridge на root-class, который уже описан в README "Переключение темы".

**Что делать:** ничего. Setup snippet в README уже корректный.

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

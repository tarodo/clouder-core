# CLOUDER · iter-2a · Дизайн-хэндовер

> **Кратко** — все дизайн-артефакты iter-2a (Auth → Categories → Triage Blocks → Curate → Patterns), упакованные для одного фронт-инженера на стеке **Mantine 9 / TypeScript / React 18+**. English version: `README.md`.

---

## Что в этой папке

| Файл | Назначение |
|---|---|
| **`index.html`** | Лендинг — начни отсюда, ссылки на всё остальное. |
| `01 Design system · Sprint-1 (standalone).html` | Standalone-каталог дизайн-системы из Sprint-1. Foundations + Mantine alignment. |
| `02 Pages catalog · Pass 1 (Auth-Triage).html` | Все экраны P-01..P-21 (Auth, AppShell, Home, Categories, Triage Blocks). Standalone. |
| `03 Pages catalog · Pass 2 (Curate-Patterns).html` | P-22..P-25 (Curate mobile + desktop, Mini-player, Device picker) + S-01..S-10 системные паттерны. Standalone. |
| `04 Component spec sheet.html` | Anatomy, states, props, Mantine mapping для каждого компонента. Начинай отсюда при реализации. |
| `tokens.css` | Source of truth для дизайн-токенов. Импортировать один раз в корне приложения. |
| `theme.ts` | Mantine `MantineThemeOverride`, отзеркаливает tokens.css. |
| `OPEN_QUESTIONS.md` | То, что дизайн осознанно не решал — с рабочими fallback'ами. |
| `MANTINE_9_NOTES.md` | Mantine 7→9 breaking changes ADR. Читай ПЕРВЫМ если копируешь любой code snippet. |
| `a11y.md` | Минимальный accessibility чеклист. |
| `i18n.md` | i18n setup (EN-only iter-2a, react-i18next infra). |

Все три `.html` файла — **standalone**: внутри инлайнено всё CSS/JS/шрифты, работают офлайн, ничего не качают из сети. Можешь отправить почтой, кинуть на флешку, захостить где угодно.

---

## Как читать (порядок)

1. **Открой `index.html`** — визуальная карта всех артефактов.
2. **Прочти OPEN_QUESTIONS.md** — 13 известных открытых вопросов с рекомендуемыми fallback'ами. ~10 минут.
3. **Прочти `04 Component spec sheet.html`** целиком — это контракт. Анатомия, состояния, Mantine mapping, code snippets для каждого компонента.
4. **Пробегись по `02` и `03` Pages catalogs** — все экраны и паттерны на одном холсте. Используй как визуальный референс при реализации.
5. **Загляни в `01 Design system`** когда нужно посмотреть токены, шрифты, цвета.

---

## Setup

Стек: **Mantine 9 / TypeScript / React 18+**. Подробности 7→9 миграции — `MANTINE_9_NOTES.md`.

```bash
pnpm add @mantine/core@9 @mantine/hooks@9 @mantine/dates@9 \
         @mantine/notifications@9 @mantine/form@9 \
         dayjs zod react-i18next i18next @tabler/icons-react
```

```tsx
// app/layout.tsx (Next.js) — или main.tsx (Vite)
import "./tokens.css";              // 1. tokens (CSS vars) ПЕРВЫМ
import "@mantine/core/styles.css";  // 2. Mantine reset + utility classes
import "@mantine/dates/styles.css"; // 3. DatePicker (string values, не Date — см. MANTINE_9_NOTES.md)
import "@mantine/notifications/styles.css";

import { MantineProvider, ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { clouderTheme } from "./theme";
import "./i18n";  // i18next init, см. i18n.md

export default function RootLayout({ children }) {
  return (
    <html lang="en" {...mantineHtmlProps}>
      <head>
        <ColorSchemeScript defaultColorScheme="light" />
      </head>
      <body>
        <MantineProvider theme={clouderTheme} defaultColorScheme="light">
          <Notifications position="top-right" />
          {children}
        </MantineProvider>
      </body>
    </html>
  );
}
```

### iter-2a решения (зафиксировано 2026-04-29)

| Тема | Решение | Файл |
|---|---|---|
| Mantine | 9.x; light variant без `v8CssVariablesResolver` | `MANTINE_9_NOTES.md` |
| Иконки | `@tabler/icons-react` через `src/components/icons.ts` re-export | spec sheet § Icon mapping |
| i18n | EN-only iter-2a, `react-i18next` infra с дня-1, RU копируется в iter-2b | `i18n.md` |
| Breakpoints | 2-step layout, `md=64em` (1024px) — единственный flip; iPhone Air 420×912 — primary mobile | spec sheet § Breakpoints, `theme.ts` |
| Dark theme | iter-2a — `defaultColorScheme="light"`. tokens готовы для iter-2b | OPEN_QUESTIONS Q1 |
| DatePicker | sheet (Drawer bottom) на mobile, popover на desktop | OPEN_QUESTIONS Q3 |
| Spotify SDK | direct browser-side, backend только `/auth/spotify/refresh` | OPEN_QUESTIONS Q5 |

### Переключение темы

В iter-2a переключения нет (`defaultColorScheme="light"` зафиксирован). Когда iter-2b добавит toggle — связать `useMantineColorScheme()` с root-классом:

```tsx
import { useMantineColorScheme } from "@mantine/core";
import { useEffect } from "react";

function ColorSchemeBridge() {
  const { colorScheme } = useMantineColorScheme();
  useEffect(() => {
    document.documentElement.classList.toggle("theme-dark", colorScheme === "dark");
  }, [colorScheme]);
  return null;
}
```

---

## Дизайн-язык — шпаргалка

- **Type** — Geist (sans) + Geist Mono (тех. метки). Размеры 11/12/13/14/16/18/24/32.
- **Spacing** — шкала на 4: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64 / 80.
- **Radii** — 4 / 6 / 10 / 14 / 999. По умолчанию `md` = 10.
- **Color** — чистый monochrome neutral ramp (oklch). Опциональный magenta accent только для "just-tapped" feedback в Curate.
- **Motion** — fast=120 / base=160 / slow=200 / pulse=80. Easing `--ease-out` для interaction, `--ease-in-out` для transition'ов.
- **Hit targets** — mobile primary ≥44px. Destination buttons 52 (md) / 64 (lg).

Нельзя (по дизайн-системе):
- Эмодзи в UI (только тех. метки, и то осторожно — в spec sheet их нет).
- Drop-shadows вне документированных `--shadow-sm/md/lg/xl`.
- Дефолтное синее focus-кольцо Mantine — переопределено на `--color-border-focus` (neutral).
- Mantine `<Kbd>` для хоткеев — используй кастомный `HotkeyHint` (см. § HotkeyHint в spec sheet).

---

## Приоритеты реализации

Бриф называет non-functional requirements, которые ложатся на конкретные импл-решения:

- **B1 · klavtatura parity в Curate** — у каждого действия есть hotkey. См. `04 Component spec sheet.html` § Hotkey overlay для полной key map.
- **B5 · empty/loading/error parity** — Pass 2 § S-01 (loading), S-02 (empty), S-03 (error) показывают treatment для каждой async-поверхности. В Pages catalog есть skeleton-варианты для Home, Triage Blocks list, Bucket detail, Player.
- **B7 · ≥10s tolerance** — длинные операции (create block, finalize) требуют 3-стадийного UX: spinner < 5s, "cold start" сообщение 5–15s, hint про восстановление > 15s. См. OPEN_QUESTIONS Q9.
- **B11 · DatePicker** — добавлен в Sprint-1.5 delta. См. spec sheet § DatePicker.

---

## Что делать, если столкнулся с тем, чего нет

Порядок:

1. Поищи в Pages catalogs (Pass 1 + Pass 2) — большинство edge cases отрисовано.
2. Проверь `OPEN_QUESTIONS.md` — 13 известных пробелов с рекомендуемыми fallback'ами.
3. Загляни в `tokens.css` и `theme.ts` за raw-значениями.
4. Если всё ещё затык — пингуй дизайн со скрином production-состояния и ссылкой на ближайший подходящий artboard.

Не изобретай новые токены, размеры шрифта или spacing-значения молча. Система намеренно узкая; расширение требует разговора с дизайном.

---

## Совместимость

Все HTML-артефакты протестированы и поставляются с:
- React 18.3.1 + ReactDOM 18.3.1 + Babel Standalone 7.29.0 (пиннинг + SRI).
- Geist + Geist Mono через Google Fonts (graceful fallback на system).
- Все ассеты инлайнены → работает офлайн после first paint.

Проверено в актуальных Chrome / Safari / Firefox. IE / legacy Edge не поддерживается намеренно.

---

## Контакт

Открытые вопросы, правки, accessibility audit — оставляй комментариями на artboard'ах. Дизайн отвечает в течение рабочего дня.

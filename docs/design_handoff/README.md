# CLOUDER · iter-2a · Design handoff

> **TL;DR** — All design artefacts for iter-2a (Auth → Categories → Triage Blocks → Curate → Patterns), packaged for one frontend engineer working in **Mantine 9 / TypeScript / React 18+**. Read `README.ru.md` if you prefer Russian.

---

## What's in this folder

| File | Purpose |
|---|---|
| **`index.html`** | Landing page — start here, links to everything. |
| `01 Design system · Sprint-1 (standalone).html` | Standalone offline-capable DS catalog from Sprint-1. Foundations + Mantine alignment. |
| `02 Pages catalog · Pass 1 (Auth-Triage).html` | All P-01..P-21 screens (Auth, AppShell, Home, Categories, Triage Blocks). Standalone. |
| `03 Pages catalog · Pass 2 (Curate-Patterns).html` | P-22..P-25 (Curate mobile + desktop, Mini-player, Device picker) + S-01..S-10 system patterns. Standalone. |
| `04 Component spec sheet.html` | Anatomy, states, props, Mantine mapping for every component used. Start here when implementing. |
| `tokens.css` | Source of truth for design tokens. Import once at app root. |
| `theme.ts` | Mantine `MantineThemeOverride` mirroring tokens.css. |
| `OPEN_QUESTIONS.md` | Things the design intentionally didn't decide — fallbacks documented. |
| `MANTINE_9_NOTES.md` | Mantine 7→9 breaking-changes ADR. Read FIRST before copying any code snippet. |
| `a11y.md` | Minimal accessibility checklist. |
| `i18n.md` | i18n setup (EN-only iter-2a, react-i18next infra). |

The three `.html` files are **standalone**: each has all CSS + JS + fonts inlined, runs offline, no network needed. You can email them, drop them on a USB stick, host them anywhere.

---

## How to read these in order

1. **Skim `index.html`** — quick visual map of all artefacts.
2. **Read OPEN_QUESTIONS.md** — 13 known unknowns with recommended fallbacks. ~10 minutes.
3. **Read `04 Component spec sheet.html`** end-to-end — this is the contract. Anatomy, states, Mantine mapping, code snippets for every component.
4. **Browse `02` and `03` Pages catalogs** — every screen and pattern, side-by-side artboards. Use as visual reference while implementing.
5. **Reference `01 Design system`** when you need to look up tokens, type, color details.

---

## Setup

Stack: **Mantine 9 / TypeScript / React 18+**. See `MANTINE_9_NOTES.md` for 7→9 migration notes.

```bash
pnpm add @mantine/core@9 @mantine/hooks@9 @mantine/dates@9 \
         @mantine/notifications@9 @mantine/form@9 \
         dayjs zod react-i18next i18next @tabler/icons-react
```

```tsx
// app/layout.tsx (Next.js) or main.tsx (Vite)
import "./tokens.css";              // 1. tokens (CSS vars) FIRST
import "@mantine/core/styles.css";  // 2. Mantine reset + utility classes
import "@mantine/dates/styles.css"; // 3. DatePicker (string values, not Date — see MANTINE_9_NOTES.md)
import "@mantine/notifications/styles.css";

import { MantineProvider, ColorSchemeScript, mantineHtmlProps } from "@mantine/core";
import { Notifications } from "@mantine/notifications";
import { clouderTheme } from "./theme";
import "./i18n";  // i18next init, see i18n.md

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

### iter-2a decisions (locked 2026-04-29)

| Topic | Decision | Source |
|---|---|---|
| Mantine | 9.x; light variant without `v8CssVariablesResolver` | `MANTINE_9_NOTES.md` |
| Icons | `@tabler/icons-react` via `src/components/icons.ts` re-export | spec sheet § Icon mapping |
| i18n | EN-only iter-2a, `react-i18next` infra from day-1, RU added in iter-2b | `i18n.md` |
| Breakpoints | 2-step layout, `md=64em` (1024px) is the only meaningful flip; iPhone Air 420×912 is primary mobile | spec sheet § Breakpoints, `theme.ts` |
| Dark theme | iter-2a ships `defaultColorScheme="light"`. tokens ready for iter-2b | OPEN_QUESTIONS Q1 |
| DatePicker | bottom Drawer on mobile, popover on desktop | OPEN_QUESTIONS Q3 |
| Spotify SDK | direct browser-side, backend only handles `/auth/spotify/refresh` | OPEN_QUESTIONS Q5 |

### Theme switching

iter-2a has no toggle (`defaultColorScheme="light"` locked). When iter-2b adds the toggle, bridge `useMantineColorScheme()` to the root class:

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

## Design language quick reference

- **Type** — Geist (sans) + Geist Mono (technical labels). Sizes 11/12/13/14/16/18/24/32.
- **Spacing** — 4-based scale: 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 / 64 / 80.
- **Radii** — 4 / 6 / 10 / 14 / 999. Default `md` = 10.
- **Color** — Pure monochrome neutral ramp (oklch). Optional magenta accent for "just-tapped" feedback in Curate.
- **Motion** — fast=120 / base=160 / slow=200 / pulse=80. Easing `--ease-out` for interaction, `--ease-in-out` for transitions.
- **Hit targets** — mobile primary ≥44px. Destination buttons 52 (md) / 64 (lg).

Never use these (per design system):
- Emoji as UI (technical labels only — e.g. spec sheet has none).
- Drop-shadows besides the documented `--shadow-sm/md/lg/xl`.
- Mantine's default blue focus ring — overridden to `--color-border-focus` (neutral).
- Mantine's `<Kbd>` for hotkeys — use the custom `HotkeyHint` component (see § HotkeyHint in spec sheet).

---

## Implementation priorities

The brief calls out non-functional requirements that map to specific implementation choices:

- **B1 · keyboard parity in Curate** — every action has a hotkey. See `04 Component spec sheet.html` § Hotkey overlay for the full key map.
- **B5 · empty/loading/error parity** — Pass 2 § S-01 (loading), S-02 (empty), S-03 (error) shows treatment for every async surface. Pages catalog has skeleton variants for Home, Triage Blocks list, Bucket detail, Player.
- **B7 · ≥10s tolerance** — Long operations (create block, finalize) need a 3-stage UX: spinner < 5s, "cold start" message 5–15s, recovery hint > 15s. See OPEN_QUESTIONS Q9.
- **B11 · DatePicker** — fixed in Sprint-1.5 delta. See spec sheet § DatePicker.

---

## When you hit something not covered

The order to follow:

1. Search the page catalogs (Pass 1 + Pass 2) — most edge cases are drawn.
2. Check `OPEN_QUESTIONS.md` — 13 known gaps with recommended fallbacks.
3. Inspect `tokens.css` and `theme.ts` for raw values.
4. If still stuck — ping design with a screenshot of the production state and a link to the closest matching artboard.

Don't invent new tokens, type sizes, or spacing values silently. The system is intentionally narrow; widening it requires a design conversation.

---

## Frame compatibility

All HTML artefacts are tested and ship with:
- React 18.3.1 + ReactDOM 18.3.1 + Babel Standalone 7.29.0 (pinned with SRI hashes).
- Geist + Geist Mono via Google Fonts (graceful fallback to system).
- All assets inlined → works fully offline after first paint.

Tested in latest Chrome / Safari / Firefox. No IE / legacy Edge support intended.

---

## Contact

Open questions, edits, accessibility audits — leave them as comments on the artboards. Design will respond within one working day.

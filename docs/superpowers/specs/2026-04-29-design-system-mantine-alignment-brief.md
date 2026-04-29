# CLOUDER · Design System Sprint-1.5 — Mantine Alignment

> Patch brief for the designer. Aligns sprint-1 Design System with the chosen frontend stack (Mantine). Sprint-1 is **not** thrown away — this document augments it.

**Date:** 2026-04-29
**Author:** Roman (product / engineer)
**Audience:** UI/UX designer for CLOUDER
**Predecessor:** [`2026-04-28-clouder-design-system-brief.md`](./2026-04-28-clouder-design-system-brief.md) — sprint-1 DS. The Section 2 paragraph naming Tailwind v4 + shadcn/ui as the stack is **superseded** by this document; everything else in sprint-1 stays valid.
**Related:** [`2026-04-29-designer-pages-brief.md`](./2026-04-29-designer-pages-brief.md) — iter-2a pages brief that depends on this alignment for DatePicker, AppShell nav, and token export shape.

---

## 1. Why this exists

Sprint-1 was built against a Tailwind + shadcn/ui assumption. The actual frontend stack is **Mantine** (`@mantine/core`, `@mantine/dates`, `@mantine/hooks`, `@mantine/notifications`). The two stacks share design vocabulary (Radix-style primitives, accessible-by-default), but diverge on:

1. **Component naming** — sprint-1 uses `Sheet`, `Dialog`, `Toast`. Mantine uses `Drawer`, `Modal`, `Notifications`. The same pattern, different vocabulary.
2. **Component coverage** — Mantine ships components sprint-1 does not name (`ActionIcon`, `NavLink`, `Indicator`, `ScrollArea`, `Combobox`, `AppShell`).
3. **Theme export shape** — Tailwind `@theme` accepts a flat token map. Mantine accepts a typed theme object via `createTheme()` with specific keys (`primaryColor`, `colors` as `MantineColorsTuple`, `defaultRadius`, `headings`, etc.). Token semantics survive; the export shape changes.
4. **Defaults that bleed** — Mantine ships its own focus rings, transitions, default radii. Without explicit overrides, the visual identity from sprint-1 will drift.

This brief closes those four gaps. Nothing in sprint-1's tokens, product components, anchor scenes, or visual direction is changed.

---

## 2. What stays from sprint-1 (do not redo)

- **All foundations / tokens.** Color ramps (oklch, light + dark), type scale (11–32 with line-heights and tracking), spacing (0–20), radii (xs/sm/md/lg/full), shadows (sm/md), motion (fast/base/slow/pulse), control heights (sm/md/lg/xl), borders.
- **All product components.** TrackRow, DestinationButton, PlayerCard, NowPlayingDot, CategoryPill, StyleSelector, TriageBucket, BlockHeader, CollectionStat, HotkeyHint, AppShell. They remain CLOUDER-specific composites; only their internal primitives switch to Mantine.
- **Anchor scenes.** Already redrawn in the iter-2a pages brief — not in scope here.
- **Wordmark + brand assets.**

---

## 3. Vocabulary map (sprint-1 base catalog → Mantine)

Every sprint-1 base component maps to one Mantine component. Where the rename is non-trivial, the right-hand column carries a note.

| Sprint-1 base | Mantine equivalent | Notes |
|---|---|---|
| Button | `Button` | Same. `loading` and `loaderProps` replace the sprint-1 loading state. |
| Input (text) | `TextInput` | `leftSection` / `rightSection` replace sprint-1 leading-icon / clear-action slots. |
| Input (search) | `TextInput` + search icon in `leftSection` | No dedicated Search variant. |
| Input (password) | `PasswordInput` | Used for sensitive tokens (admin `bp_token` in iter-2b). |
| Textarea | `Textarea` | Same. |
| Select | `Select` | Same. |
| Combobox (search-in-select) | `Combobox` | Composable primitive. Used for StyleSelector mobile dropdown. |
| Checkbox | `Checkbox` | Same. |
| Radio | `Radio.Group` + `Radio` | Group required. |
| Switch | `Switch` | Same. |
| Tabs (underline / pill) | `Tabs` with `variant="default" \| "pills"` | Pill is the CLOUDER default. |
| Card | `Card` (which wraps `Paper`) | Use `Card` for product cards, `Paper` for raw surface. |
| Badge / Tag | `Badge` | `variant="dot"` covers the sprint-1 dot variant. |
| Table | `Table` | Compact + sticky header are achievable via props. |
| ListItem | composed: `Group` (icon + text) inside a `Card` or `UnstyledButton`, or `NavLink` for nav lists | No direct Mantine ListItem. Designer specifies one composition pattern, reused. |
| Skeleton | `Skeleton` | Same. |
| **Toast** | **`Notifications` (`@mantine/notifications`)** | Different package. Position: top-right on desktop, top on mobile (matches sprint-1 spec). |
| **Dialog** | **`Modal`** | Mantine *also* exposes a minor `Dialog` component — that is **not** the sprint-1 Dialog. Always map sprint-1 Dialog → Mantine `Modal`. |
| **Sheet** | **`Drawer`** | `position="bottom"` for mobile, `position="right"` for desktop. |
| Popover | `Popover` | Same. |
| Tooltip | `Tooltip` | `keyboard` shortcut variant lives in CLOUDER product layer (HotkeyHint, sprint-1). |
| Progress (linear) | `Progress` | Player progress, run-status. |
| Progress (circular) | `RingProgress` | Loading spinner alternative; loader otherwise via `Loader`. |
| Avatar | `Avatar` | Initials fallback handled via `name` prop. |
| EmptyState | composed: `Stack` + Icon + `Text` + `Button` | No direct Mantine component. Designer provides one canonical composition. |
| Separator | `Divider` | Horizontal + vertical. |
| Breadcrumb | `Breadcrumbs` | Same. |

---

## 4. New Mantine-native components to specify

These are not in sprint-1 but the iter-2a pages brief assumes them. The designer specs each one as a CLOUDER variant of the Mantine component.

| Component | Source | Used in | What the designer delivers |
|---|---|---|---|
| **DatePicker / DateInput** | `@mantine/dates` `DatePickerInput`, `DateInput` | P-15 (Create Triage Block) | Visual treatment: input field (TextInput-based), calendar Popover, day cells (selected / hovered / today / out-of-month / disabled), range selection, header with month/year navigation. Light + dark. |
| **ActionIcon** | `@mantine/core` `ActionIcon` | P-09 reorder ↑/↓, P-10 trash, P-22/P-23 transport controls, top-bar actions | Icon-only button. Sizes (sm/md/lg matching control heights), variants (subtle / filled / default), states (idle / hover / active / disabled). |
| **NavLink** | `@mantine/core` `NavLink` | P-04 desktop side rail (if chosen), Avatar menu | Selected / unselected, with icon, with badge / counter. |
| **Indicator** | `@mantine/core` `Indicator` | P-04 Avatar (admin badge), NowPlayingDot reference | Dot or count, positioned on a child. |
| **ScrollArea** | `@mantine/core` `ScrollArea` | P-16 horizontal lane scroll on desktop, P-17 long lists, P-22/P-23 destination overflow | Custom scrollbar styling that matches CLOUDER tokens (rail + thumb). |
| **AppShell** | `@mantine/core` `AppShell` | P-04 | The CLOUDER product `AppShell` (sprint-1 catalog) is composed on top of Mantine's `AppShell` slots: `Header`, `Navbar` (desktop side rail) or `Footer` (mobile bottom tabs), `Main`. Designer specifies the breakpoint at which the layout flips and the responsive collapse behaviour. |
| **Combobox (StyleSelector mobile)** | `@mantine/core` `Combobox` | P-04 mobile StyleSelector | Trigger as a button-style input + dropdown with optional search. |
| **Loader** | `@mantine/core` `Loader` | P-02, P-15, P-20 long-running pending | Variant + size palette aligned with motion tokens (≤200 ms `ease-out`). |
| **Notifications** | `@mantine/notifications` | S-03 error envelope, success toasts | Visual: icon + title + body + close. Colour by status (success / warning / danger). Position rule: top-right desktop, top mobile. Auto-dismiss 5 s default; 0 s for errors. |

---

## 5. MantineProvider theme export

The designer ships token sources in **two formats** (the engineer wires both):

### 5.1 `tokens.css`
CSS custom properties — same shape sprint-1 already produces. `:root { ... }` for light, `.dark { ... }` for dark. Used by global styles and CLOUDER product components.

### 5.2 `theme.ts` — MantineProvider theme object

A TypeScript file that exports a `createTheme()` object covering every token sprint-1 defines. The shape:

```ts
import { createTheme, MantineColorsTuple } from '@mantine/core';

const neutral: MantineColorsTuple = [
  // Mantine requires exactly 10 shades, lightest → darkest.
  // Map sprint-1 neutrals (0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000)
  // by dropping 0 and 1000 (use as bg/fg-inverse semantics, not in the tuple).
  /* 0 */ 'oklch(0.985 0 0)',  // sprint-1 neutral-50
  /* 1 */ 'oklch(0.965 0 0)',  // sprint-1 neutral-100
  /* 2 */ 'oklch(0.925 0 0)',  // sprint-1 neutral-200
  /* 3 */ 'oklch(0.875 0 0)',  // sprint-1 neutral-300
  /* 4 */ 'oklch(0.715 0 0)',  // sprint-1 neutral-400
  /* 5 */ 'oklch(0.555 0 0)',  // sprint-1 neutral-500
  /* 6 */ 'oklch(0.395 0 0)',  // sprint-1 neutral-600
  /* 7 */ 'oklch(0.265 0 0)',  // sprint-1 neutral-700
  /* 8 */ 'oklch(0.175 0 0)',  // sprint-1 neutral-800
  /* 9 */ 'oklch(0.095 0 0)',  // sprint-1 neutral-900
];

const magenta: MantineColorsTuple = [ /* 10 shades, optional accent */ ];

export const clouderTheme = createTheme({
  primaryColor: 'neutral',
  primaryShade: { light: 9, dark: 9 },        // selected = inverted fg in CLOUDER
  colors: { neutral, magenta },

  defaultRadius: 'md',                         // sprint-1 radius-md = 10px
  radius: { xs: '4px', sm: '6px', md: '10px', lg: '14px' },

  spacing: {
    xs: '4px',  sm: '8px',  md: '12px',
    lg: '16px', xl: '24px',
    // sprint-1 has 0/1/2/3/4/5/6/8/10/12/16/20 — Mantine takes 5 named slots,
    // remaining values stay accessible via tokens.css and inline `style`.
  },

  fontFamily: '"Geist", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif',
  fontFamilyMonospace: '"Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace',

  fontSizes: {
    xs: '11px', sm: '12px', md: '13px', lg: '14px', xl: '16px',
    // sprint-1 also has 18/24/32 — ship as additional theme.other entries.
  },

  lineHeights: {
    xs: '14px', sm: '16px', md: '18px', lg: '20px', xl: '24px',
  },

  headings: {
    fontFamily: '"Geist", ui-sans-serif, system-ui, sans-serif',
    sizes: {
      h1: { fontSize: '32px', lineHeight: '38px', fontWeight: '600' },
      h2: { fontSize: '24px', lineHeight: '30px', fontWeight: '600' },
      h3: { fontSize: '18px', lineHeight: '26px', fontWeight: '500' },
      h4: { fontSize: '16px', lineHeight: '24px', fontWeight: '500' },
      h5: { fontSize: '14px', lineHeight: '20px', fontWeight: '500' },
      h6: { fontSize: '13px', lineHeight: '18px', fontWeight: '500' },
    },
  },

  shadows: {
    sm: '0 2px 6px -2px oklch(0 0 0 / 0.10), 0 1px 2px -1px oklch(0 0 0 / 0.08)',
    md: '0 12px 32px -8px oklch(0 0 0 / 0.18), 0 4px 8px -4px oklch(0 0 0 / 0.10)',
  },

  defaultProps: {
    Button:    { radius: 'md' },
    Modal:     { radius: 'md', overlayProps: { backgroundOpacity: 0.55, blur: 0 } },
    Drawer:    { radius: 'md', overlayProps: { backgroundOpacity: 0.55, blur: 0 } },
    TextInput: { radius: 'md' },
    Card:      { radius: 'md', withBorder: true, shadow: 'none' },
    Paper:     { radius: 'md', withBorder: true, shadow: 'none' },
    Notifications: { position: 'top-right', autoClose: 5000 },
  },

  other: {
    // sprint-1 tokens that have no first-class slot in Mantine theme:
    fontSize18: '18px',
    fontSize24: '24px',
    fontSize32: '32px',
    spacing0: '0px',
    spacing20: '20px',
    spacing64: '64px',
    spacing80: '80px',
    motionFast: '120ms',
    motionBase: '160ms',
    motionSlow: '200ms',
    motionPulse: '80ms',
    easeOut:    'cubic-bezier(0.2, 0.7, 0.2, 1)',
    easeInOut:  'cubic-bezier(0.5, 0, 0.2, 1)',
    controlSm:  '28px',
    controlMd:  '36px',
    controlLg:  '44px',
    controlXl:  '56px',
  },
});
```

**Constraints to respect:**

- `MantineColorsTuple` is **exactly 10 shades**. Sprint-1 has 12 neutrals (0 / 50 / 100 / … / 1000). Drop 0 and 1000 from the tuple; expose them via `tokens.css` and `theme.other` instead.
- `primaryColor` must name a key in `colors`. CLOUDER uses `'neutral'` as primary; the optional magenta accent flips selected/focus states by switching `primaryColor` at runtime.
- `defaultRadius` is a single key. CLOUDER picks `md`; per-component overrides via `radius` prop.
- Mantine's `headings.sizes` keys are h1–h6. The full sprint-1 type scale (11/12/13/14/16/18/24/32) maps to `fontSizes` (xs–xl) + `headings` + `theme.other` for the remainder.
- Dark-theme support uses Mantine's `colorScheme` pivot. The same `colors.neutral` tuple is reused; CLOUDER overrides happen at the CSS-variable layer (`tokens.css`), not by shipping a second tuple. The designer documents the mapping.

The designer ships the `theme.ts` file (or its visual equivalent — token-by-token mapping table) so the engineer drops it into the codebase verbatim.

---

## 6. Override checklist (kill the Mantine defaults)

Without explicit overrides, Mantine's defaults bleed through and the CLOUDER identity drifts. The designer specifies the override for each item below; the engineer wires it via `defaultProps`, `classNames`, or component-level `styles`.

| # | Component | Default to override |
|---|---|---|
| **O1** | `Button` | Disable Mantine's loader spin animation if it conflicts with the sprint-1 80 ms tap-pulse on DestinationButton. Confirm focus ring is `--color-border-focus`. |
| **O2** | `ActionIcon` | Hover = `--color-hover` background, not Mantine's default tinted overlay. |
| **O3** | `Modal` (sprint-1 Dialog) | Backdrop = `oklch(0 0 0 / 0.55)` (no blur). Close button uses `ActionIcon` styling. |
| **O4** | `Drawer` (sprint-1 Sheet) | Same backdrop rule as Modal. Mobile bottom drawer rounds top corners only (`radius-lg` top, 0 bottom). |
| **O5** | `Tabs` | `variant="pills"` is the CLOUDER default in `defaultProps`. Underline variant available on opt-in. |
| **O6** | `Checkbox` / `Radio` / `Switch` | Filled state uses `--color-accent` (mono = `neutral-900`; magenta accent = magenta). |
| **O7** | `TextInput` / `PasswordInput` / `Textarea` | Border `1px solid --color-border`. Focus = 1 px ring `--color-border-focus`, no Mantine glow. |
| **O8** | `Notifications` | Position: `top-right` desktop, `top` mobile. Auto-close 5 s for success/info, **disabled** for error (user copies `correlation_id`). |
| **O9** | `Loader` | Replace Mantine's default oval spinner with a token-aligned variant (designer's choice from `bars` / `dots` / `oval` Mantine built-ins, no custom SVG). |
| **O10** | `ScrollArea` | Scrollbar rail = `--color-bg-muted`, thumb = `--color-border-strong`, thumb hover = `--color-fg-muted`. |
| **O11** | `Tooltip` | Background = `--color-fg`, foreground = `--color-bg-elevated` (inverted). Mono-font for keyboard variant (`HotkeyHint` style). |
| **O12** | `Card` / `Paper` | Border-driven (`withBorder`), `shadow="none"` by default. Shadow only on opt-in (`shadow="sm"` for popover floats, `shadow="md"` for modals). |

---

## 7. Out of scope

- New visual identity work — sprint-1 stands.
- Adding magenta accent if not already designed — accent token policy from sprint-1 unchanged.
- Mantine packages not listed: `@mantine/charts`, `@mantine/carousel`, `@mantine/code-highlight`, `@mantine/dropzone`, `@mantine/form`, `@mantine/modals`, `@mantine/nprogress`, `@mantine/spotlight`, `@mantine/tiptap`. They may be adopted later; this brief does not define their CLOUDER skin.
- Wiring Mantine in code — engineer's job. Designer ships `theme.ts` as a hand-off artefact, engineer imports it.

---

## 8. Deliverables

1. **Vocabulary map (§3)** — published as a one-page table inside the catalog or README.
2. **New Mantine-native components (§4)** — designed in light + dark, all states from sprint-1 §6.2 acceptance (default / hover / focus / active / disabled / loading where applicable).
3. **DatePicker** — full visual spec (calendar Popover, day cells, range selection, month/year nav). Reused by the iter-2a P-15 brief.
4. **`theme.ts` MantineProvider theme object** — TypeScript file or the equivalent token-by-token mapping table covering every sprint-1 token. Format per §5.2.
5. **Override checklist resolution (§6)** — designer fills in the override for each O1–O12 row with concrete token references.
6. **Updated tokens.css** — same shape as sprint-1 if any new tokens are introduced for the new components. No regression to existing tokens.
7. **README delta** — short changelog: «Mantine alignment patch — vocabulary map, N new components, theme.ts». Filed alongside the existing sprint-1 README.

---

## 9. Acceptance criteria

| # | Criterion |
|---|---|
| **M1** | Every sprint-1 base component has exactly one Mantine equivalent listed in §3, with non-trivial renames (Toast → Notifications, Dialog → Modal, Sheet → Drawer) explicitly noted. |
| **M2** | Every component listed in §4 has light + dark + (default / hover / focus / active / disabled) where applicable. |
| **M3** | DatePicker is delivered as a full visual spec, not as «use Mantine default». |
| **M4** | `theme.ts` covers every sprint-1 token. Tokens that have no first-class Mantine slot are exposed via `theme.other`. The 12-step neutral ramp is mapped to a 10-step `MantineColorsTuple` with explicit notes for the dropped shades. |
| **M5** | Each O1–O12 row carries a concrete resolution naming token references — no «Mantine default OK». |
| **M6** | `defaultRadius`, `primaryColor`, `defaultProps` are set in `theme.ts` per §5.2. |
| **M7** | `tokens.css` and `theme.ts` agree on every shared value (colour, space, radius, font, motion). No drift. |
| **M8** | The README delta enumerates every change in one place — designer-facing changelog. |

---

## 10. Process

- **Kickoff (~15 min):** walk §3 + §4, confirm the vocabulary map. No design work yet.
- **Mid-point (~3 days in):** vocabulary map + DatePicker + `theme.ts` draft. Direction-level feedback.
- **Final (~5 days in):** all of §4 + §6 + deliverables §8. Formal acceptance against §9.

---

## Appendix · Mantine package list (reference)

The frontend will install the following Mantine packages. The designer does **not** need to design every package's components — only those listed in §3 and §4.

- `@mantine/core` — base components (everything in §3 and most of §4).
- `@mantine/hooks` — non-visual.
- `@mantine/dates` — DatePicker + DateInput (§4).
- `@mantine/notifications` — Toast replacement (§3 row «Toast», §4 row «Notifications»).
- `@mantine/form` — non-visual; form state.

Other Mantine packages (`@mantine/charts`, `@mantine/spotlight`, `@mantine/dropzone`, etc.) are out of scope for this sprint.

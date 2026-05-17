# Design Handoff Readiness — iter-2a → Mantine 9

**Date:** 2026-04-29
**Status:** Design (awaiting user review before writing-plans)
**Owners:** Claude (writing), Roman (review)
**Scope:** Bring `docs/design_handoff/` from "Mantine 7 first draft" to "Mantine 9 ready-to-implement" without starting actual frontend development.

---

## Goal

Designer delivered iter-2a handoff (`docs/design_handoff/`). It is ~70% production-ready: tokens, theme projection, spec sheet for primitives, OPEN_QUESTIONS file, three standalone HTML page catalogs. Five gaps prevent a frontend engineer (or frontend agent) from starting without invented details:

1. Stack mismatch — handoff written for Mantine 7; user mandate is Mantine 9.
2. Six components have placeholder-only spec entries.
3. OPEN_QUESTIONS Q1/Q3/Q5 lack frontend-side fallbacks.
4. Icon library, breakpoints, i18n, a11y not decided.
5. Setup snippet missing Mantine 9 idioms (`mantineHtmlProps`, dates string semantics, `schemaResolver`).

This spec defines the targeted edits to close those gaps. No code is written; outcome is updated documentation in `docs/design_handoff/` plus two new ADR-style files.

## Non-goals

- Implementing any component in TypeScript/React.
- Creating a frontend project scaffold (Vite/Next.js).
- Replacing the static HTML page catalogs (`02`, `03`) with live components.
- Full WCAG 2.2 AA audit (only minimal a11y checklist is in scope).
- Visual QA of dark theme on production pages (designer's job in iter-2b).
- Backend contract changes (Spotify SDK token endpoint coordinated separately).

## Decisions log (from brainstorming)

| # | Topic | Decision |
|---|---|---|
| 1 | Scope size | Full Mantine 9 readiness (option B), not minimal patch. |
| 2 | Division of labor | Claude writes, Roman reviews. No second agent during spec phase. |
| 3 | Icon library | `@tabler/icons-react`. Snippets in current spec already use `IconPlayer*` names; ratify what's there. |
| 4 | i18n | EN-only copy, `react-i18next` infrastructure from day-1. Domain terms (NEW/OLD/NOT/DISCARD/BPM/key) untranslated. |
| 5 | Breakpoints | 2-step layout, `md = 64em` (1024px) is mobile↔desktop flip. Lower breakpoints (`xs = 20em` / 320px, `sm = 30em` / 480px) provided as Mantine plumbing only — no layout flip in that range. Min mobile width target 420px (iPhone Air, primary device, 2736×1260 @ DPR 3 = 420×912 CSS). iPhone Air sits between `xs` and `sm`, classified as "phone". |
| 6 | Q3 mobile DatePicker | Bottom Drawer on mobile (< md), Mantine `DatePickerInput` popover on desktop. |
| 7 | Q1 dark theme | Ship `defaultColorScheme="light"` for iter-2a. Keep `.theme-dark` ramp in tokens.css for iter-2b. Toggle exposed in Profile (iter-2b ticket). |
| 8 | Q5 Spotify Web Playback SDK | Direct browser-side: frontend holds access token in-memory, refreshes via backend `/auth/spotify/refresh`. No backend playback proxy. |
| 9 | a11y scope | Minimal checklist file, not full WCAG audit. Focus visible, ARIA on icon buttons + custom components, contrast verified, reduced-motion guard. |
| 10 | Deliverable form | Worktree-only edits during spec phase. Atomic PRs after writing-plans → implementation kicks off. |

## Architecture of changes

8 file-blocks under `docs/design_handoff/`. No deletions.

### Edits to existing files

| File | Change |
|---|---|
| `README.ru.md` | Replace setup snippet (Mantine 9: `mantineHtmlProps`, `defaultColorScheme="light"`, dates string note, `schemaResolver` hint). Add cross-references to new ADR files. Document i18n + icon library + breakpoints decisions. |
| `README.md` | Mirror `README.ru.md` updates. |
| `OPEN_QUESTIONS.md` | Update Q1, Q3, Q5 with frontend-side fallback decisions (with "product/design may override" note). Mark Q2 closed (tabler chosen). |
| `theme.ts` | Add `breakpoints: { xs: '20em', sm: '30em', md: '64em', lg: '80em', xl: '96em' }`. Single-property addition. `md = 64em` (1024px) is the only meaningful flip; `xs`/`sm` are below the iPhone Air threshold (420px) so default `visibleFrom="md"` correctly hides desktop-only content on the primary mobile device. |
| `04 Component spec sheet.html` | (a) New section "Breakpoints" between Tokens recap and Vocabulary map. (b) New section "Icon mapping" after Vocabulary map. (c) Extend specs for CategoryPill, StyleSelector, BucketCounters, BlockHeader, PlayerCard, TrackRow to Button-level depth (anatomy + states table + props + Mantine mapping). (d) Inline Mantine 9 callouts on DatePicker (string values), Button (focus variable rename), and a new Form snippet showing `schemaResolver` for the P-15 create-block form. |

### New files

| File | Purpose |
|---|---|
| `MANTINE_9_NOTES.md` | ADR. List breaking changes from Mantine 7 → 9 that affect this handoff. Decision: do NOT use `v8CssVariablesResolver` — accept Mantine 9 light-variant colors. Recipe table mapping each impacted spec snippet to its v9 form. |
| `a11y.md` | Minimal checklist: focus visible, ARIA labels on icon-only buttons, ARIA on DestinationButton/ListItem, focus trap on Modal/Drawer, contrast verification (already passes via tokens), reduced-motion guard for just-tapped scale + slide-up transitions. |
| `i18n.md` | `react-i18next` setup, `src/i18n/en.json` flat-by-screen structure (e.g. `auth.signin`, `triage.discard`), domain-term policy (NEW/OLD/NOT/DISCARD/BPM/key never translated), `t()` wrapper usage example for `notifications.show()`. |

Breakpoints documentation lives inline in `04 Component spec sheet.html` (new "Breakpoints" section), not a separate file. Single source of truth.

## Component spec extension template

Each of the six undercooked components (CategoryPill, StyleSelector, BucketCounters, BlockHeader, PlayerCard, TrackRow) gets a section structured identically to Button:

```
## <ComponentName>
Mantine: <mapping>
Used in: <P-IDs>
Variants: <list>

### Anatomy
<short visual description + minimal markup sketch>

### States
| State | Visual change | Implementation |

### Props
<TypeScript type signature>

### Mantine mapping
<code snippet>
```

Depth target: matches DestinationButton, no deeper. PlayerCard adds a per-state visual matrix (idle/playing/buffering/paused/error/disconnected → icon, scrub opacity, copy variant) because that mapping is currently absent.

## Mantine 9 migration impact audit

Existing spec snippets to amend:

| Location | Issue | Fix in spec |
|---|---|---|
| Button § States, focus-ring row | References `--mantine-color-blue-filled` (Mantine 7 idiom) | Replace with `--mantine-primary-color-filled` OR note that the CSS-var override (`--color-border-focus`) supersedes Mantine's variable so no rename needed. |
| DatePicker § Mantine mapping | Implicitly assumes `Date` value | Add `value: string \| null` (YYYY-MM-DD) note + `dayjs` conversion example for timezone-aware logic. |
| (New) Form snippet for P-15 | No current form spec, but P-15 will use validated form | Add example using `useForm({ validate: schemaResolver(zodSchema, { sync: true }) })` with `zod/v4` import. |
| Carousel | Not used in handoff | No change. |
| Collapse | Not currently in spec | Add brief note in MANTINE_9_NOTES.md for future use (`in` → `expanded`). |
| `useMutationObserver` | Not used | Note in MANTINE_9_NOTES.md only. |

## Sequencing (writing order)

1. `MANTINE_9_NOTES.md` — foundation; everything else references it.
2. `theme.ts` breakpoints addition — one-line change unblocks the Breakpoints section.
3. `04 Component spec sheet.html`: Breakpoints + Icon mapping sections (small).
4. `04 Component spec sheet.html`: six component extensions (largest chunk).
5. `04 Component spec sheet.html`: Mantine 9 callouts inline.
6. `a11y.md` + `i18n.md` (small).
7. `OPEN_QUESTIONS.md`: Q1/Q2/Q3/Q5 updates.
8. `README.ru.md` + `README.md`: final sync, cross-references.

## OPEN_QUESTIONS resolutions to record

### Q1 — Dark theme parity
**Recorded fallback:** iter-2a ships `defaultColorScheme="light"`. `.theme-dark` ramp in `tokens.css` stays for iter-2b. Toggle exposed in Profile (iter-2b ticket). Designer visual QA of production pages in dark is iter-2b prerequisite. Frontend does NOT auto-detect system color scheme until QA passes.

### Q2 — Icons
**Closed:** `@tabler/icons-react`. 1:1 mapping table added to spec sheet (§ Icon mapping). Sizes 12/14/16/18/20/22 → tabler `size` prop. Names file: `src/components/icons.ts` re-export pattern (frontend implementation detail, mentioned in spec but not implemented now).

### Q3 — Mobile DatePicker
**Recorded fallback:** Bottom `Drawer` on mobile (< `md` breakpoint), Mantine `DatePickerInput` popover on desktop. Custom wrapper component `DateRangeField` composes `useMediaQuery('(max-width: 64em)')` + `Drawer position="bottom"` + inline `DatePicker`. Designer may override if full-screen sheet is hard requirement; popover-everywhere is the next safest fallback.

### Q5 — Web Playback SDK contract
**Recorded fallback:**
- Frontend holds Spotify access token in-memory (not localStorage).
- Refresh via CLOUDER backend endpoint `/auth/spotify/refresh` returning `{access_token, expires_in}` 5 minutes before expiry.
- `Spotify.Player` SDK initialized at AppShell mount.
- `playerReady` from `player.addListener('ready', ...)` callback.
- Devices list: poll `getMyDevices` (Spotify Web API direct) every 30s + immediate refresh on focus.
- Transfer playback: `transferMyPlayback` with picker's `device_id`.
- Errors: `account_error` → P-03 Premium-required state; `playback_error` → toast + retry.

Backend confirmation needed only that `/auth/spotify/refresh` exists. Small ask, parallel to handoff doc work, not blocking.

## a11y checklist (going into `a11y.md`)

1. **Focus visible.** All `UnstyledButton`/`<button>`/interactive `<div>`-as-button get `:focus-visible` ring with `--color-border-focus`, offset 2px. Mantine 9 default is theme-driven; rely on it.
2. **Icon-only buttons.** `ActionIcon` instances must have `aria-label`. Spec sheet examples updated.
3. **DestinationButton.** `aria-keyshortcuts="<digit>"` when `hotkey` prop is present. `aria-pressed={state === "primary"}`.
4. **Hotkey overlay (S-08).** `Modal` provides focus trap by default; verify focus returns to trigger on close (Mantine handles).
5. **ListItem (P-18, P-19, P-25).** Container `role="listbox"`, items `role="option"` with `aria-selected`.
6. **Contrast.** Tokens ramp pre-verified: `--color-fg` (neutral-900) on `--color-bg` (neutral-0) ≈ 21:1; `--color-fg-muted` (neutral-500) on `--color-bg` ≈ 4.5:1. Document in `a11y.md` so future palette tweaks have a baseline.
7. **Reduced motion.** `@media (prefers-reduced-motion: reduce)` disables: just-tapped `scale(0.97)`, slide-up Transition on multi-select bar, skeleton shimmer if perceptible.
8. **Lang attribute.** `<html lang="en">` (per i18n decision EN-only iter-2a).

## i18n setup (going into `i18n.md`)

- Library: `react-i18next` + `i18next` (~13KB gz combined).
- Catalog file: `src/i18n/en.json`. Structure: `{ "<screen>": { "<element>": "..." } }`. Examples: `auth.signin`, `categories.empty.title`, `triage.discard`, `notifications.error.networkLost`.
- Domain terms NEVER translated (frozen as English): `NEW`, `OLD`, `NOT`, `DISCARD`, `STAGING` (uppercase status labels), `BPM`, `key` (musical key like 9A), `Now Playing`, `Curate`, `Triage Block`. Document this list explicitly.
- Hooks: `useTranslation()` in components; `i18next.t()` for `notifications.show()` and other non-component contexts.
- Init: `i18next.init({ lng: 'en', resources: { en: { translation: enJson } } })` at app root, before `<MantineProvider>`.

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Spec sheet HTML grows large; inline edit risks breaking layout | Medium (file is currently 47KB, adding ~6 sections doubles it) | Edit in small chunks, verify rendering after each section by opening in browser. |
| Mantine 9 light-variant color shift may surprise frontend during impl | Low | MANTINE_9_NOTES.md flags this; if visual mismatch surfaces during build, easy fix is wrapping in `<MantineProvider cssVariablesResolver={v8CssVariablesResolver}>`. |
| Designer disagrees with Q1/Q3/Q5 fallbacks | Low | Fallbacks marked "product/design may override". OPEN_QUESTIONS.md remains the source of pending decisions. |
| iPhone Air min-width 420px assumption wrong (e.g. user has older device fallback) | Low | DestinationButton lg=64 height fits 420px wide cleanly; spec doesn't drop below 420 anywhere. If min target needs to drop to 360px, only DestinationButton text truncation needs review. |

## Acceptance criteria

- All 8 file-blocks updated/created in `docs/design_handoff/`.
- HTML catalogs (`01`, `02`, `03`) untouched.
- `04 Component spec sheet.html` opens cleanly in browser (visual smoke test).
- README setup snippet copy-pastes into a Mantine 9 project without further edits beyond actual app structure.
- A frontend engineer reading the updated handoff for first time can answer, without external clarification:
  - Which Mantine version, which icon lib, which i18n lib.
  - The mobile↔desktop breakpoint and the min-mobile-width target.
  - All six previously-undercooked components have anatomy/states/props.
  - OPEN_QUESTIONS Q1/Q2/Q3/Q5 have a recorded fallback or are marked closed.
  - The Spotify Web Playback SDK contract.

## Out of this spec, into next phases

- Writing-plans skill produces an ordered implementation plan for the edits above (one section at a time).
- Actual implementation: edit the documentation files. Then split into atomic PRs:
  1. Mantine 9 setup snippet (READMEs).
  2. theme.ts breakpoints + spec sheet Breakpoints + Icon mapping sections.
  3. Six component spec extensions.
  4. MANTINE_9_NOTES.md.
  5. a11y.md + i18n.md.
  6. OPEN_QUESTIONS.md updates.
- After all merged, frontend-design / frontend-agent can start implementation against this contract.

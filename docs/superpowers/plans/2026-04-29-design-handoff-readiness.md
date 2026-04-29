# Design Handoff Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `docs/design_handoff/` from "Mantine 7 first draft" to "Mantine 9 ready-to-implement" by editing/creating documentation only — no application code, no tests.

**Architecture:** All edits land under `docs/design_handoff/`. Two new files (`MANTINE_9_NOTES.md`, `a11y.md`, `i18n.md`), four edits (`theme.ts`, `04 Component spec sheet.html`, `OPEN_QUESTIONS.md`, both READMEs). HTML page catalogs (`01`, `02`, `03`) untouched. Spec source: `docs/superpowers/specs/2026-04-29-design-handoff-readiness-design.md`.

**Tech Stack:** Markdown, HTML5 (inline CSS), TypeScript (theme.ts edit only).

**Commit policy:** Per `CLAUDE.md`, every commit message MUST come from the `caveman:caveman-commit` skill. The example messages in this plan are illustrative — invoke the skill to generate the actual subject line, then `git commit -m "<skill output>"`.

**Conventions:**
- Each task ends with one commit, scoped to the files changed in that task.
- Smoke test for HTML edits: open `04 Component spec sheet.html` in browser after each edit, confirm no rendering breakage.
- Smoke test for Markdown: render preview (e.g. `mdcat`, VS Code preview, GitHub).

---

## File structure

| File | Action | Owner concern |
|---|---|---|
| `docs/design_handoff/MANTINE_9_NOTES.md` | Create | Mantine 7→9 breaking-change ADR |
| `docs/design_handoff/theme.ts` | Modify (one-property add) | Breakpoints |
| `docs/design_handoff/04 Component spec sheet.html` | Modify (multiple sections) | Component contracts + Mantine 9 callouts |
| `docs/design_handoff/a11y.md` | Create | Minimal a11y checklist |
| `docs/design_handoff/i18n.md` | Create | i18n setup decision |
| `docs/design_handoff/OPEN_QUESTIONS.md` | Modify (Q1/Q2/Q3/Q5) | Recorded fallbacks |
| `docs/design_handoff/README.md` | Modify | Sync with new decisions + Mantine 9 setup snippet |
| `docs/design_handoff/README.ru.md` | Modify | RU mirror of README.md |

---

## Task 1: Create MANTINE_9_NOTES.md ADR

**Files:**
- Create: `docs/design_handoff/MANTINE_9_NOTES.md`

- [ ] **Step 1: Write the ADR file**

Write the following content to `docs/design_handoff/MANTINE_9_NOTES.md`:

````markdown
# Mantine 7 → 9 Migration Notes · CLOUDER iter-2a

> Source-of-truth list of Mantine breaking changes that affect this handoff. Read first if you wrote a code snippet referencing Mantine 7 idioms.

## Decision: do NOT use `v8CssVariablesResolver`

Mantine 9 changed the colour math behind `variant="light"` (lighter, less saturated than 8.x). We accept the new defaults. Rationale:

- CLOUDER ramp is monochrome neutral; the visible delta on `variant="light"` is tiny against a no-saturation palette.
- `v8CssVariablesResolver` is a temporary escape hatch documented to be removed in 10.x. Building on it now creates a second migration.

Escape hatch (only if visual QA finds a critical regression):

```tsx
import { MantineProvider, v8CssVariablesResolver } from '@mantine/core';
<MantineProvider cssVariablesResolver={v8CssVariablesResolver}>...
```

## Breaking changes that touch this handoff

| Area | 7.x | 9.x | Where it shows up |
|---|---|---|---|
| Form resolvers | `import { zodResolver } from '@mantine/form'` | `import { schemaResolver } from '@mantine/form'` + `zod/v4` | P-15 Create Triage Block form |
| `@mantine/dates` values | `onChange(date: Date)` | `onChange(value: string)` (YYYY-MM-DD) | P-15 `date_from`/`date_to` |
| `Collapse` toggle prop | `<Collapse in={open}>` | `<Collapse expanded={open}>` | Anywhere expandable rows are added (currently none in spec, future-proofing) |
| `useMutationObserver` hook | Single hook with optional target arg | Renamed `useMutationObserverTarget` when target is required | Internal — only matters if a custom hook needs DOM observation |
| `Carousel` config | Props `loop`, `dragFree`, `align` | `emblaOptions={{ loop, dragFree, align }}` | Not used in iter-2a; note for future |
| HTML hydration | manual `lang` only | spread `mantineHtmlProps` on `<html>` | App root (READMEs updated) |
| Light variant colour math | 8.x ramp | 9.x ramp (lighter) | Badges (`variant="light"`), buttons with `variant="light"` |

## Spec snippet patches

These edits are applied directly in `04 Component spec sheet.html` (Task 11 of the implementation plan). Listed here as a single source of truth.

### DatePicker — `onChange` returns string

Current snippet implies `Date`:

```tsx
<DatePickerInput value={value} onChange={setValue} />
```

In 9.x the second arg is `string | null` (e.g. `'2026-04-29'`). Three integration patterns:

1. **Native string state** (recommended, no conversion):
   ```tsx
   const [value, setValue] = useState<string | null>(null);
   <DatePickerInput value={value} onChange={setValue} />
   ```

2. **Date state with conversion** (when downstream needs `Date`):
   ```tsx
   const [value, setValue] = useState<Date | null>(null);
   <DatePickerInput
     value={value ? value.toISOString().slice(0, 10) : null}
     onChange={(v) => setValue(v ? new Date(v) : null)}
   />
   ```

3. **Timezone-aware via dayjs**:
   ```tsx
   import dayjs from 'dayjs';
   const dateInTz = dayjs(value).tz('Europe/Berlin').toDate();
   ```

### Form validation — `schemaResolver` instead of `zodResolver`

P-15 Create Triage Block form (the only form with non-trivial validation in iter-2a):

```tsx
import { useForm, schemaResolver } from '@mantine/form';
import { z } from 'zod/v4';

const schema = z.object({
  name: z.string().min(1, { error: 'Name required' }),
  style: z.string().min(1, { error: 'Style required' }),
  date_from: z.string().min(1, { error: 'Start date required' }),
  date_to: z.string().min(1, { error: 'End date required' }),
});

const form = useForm({
  initialValues: { name: '', style: '', date_from: '', date_to: '' },
  validate: schemaResolver(schema, { sync: true }),
});
```

Note `zod/v4` import path — Mantine 9 expects Standard Schema, which Zod 4 implements.

### Button focus override

Current spec mentions `--mantine-color-blue-filled` as the variable to override. In Mantine 9 the variable is rebased onto `primaryColor` (renamed `--mantine-primary-color-filled`). Practical guidance: **do nothing**. CLOUDER's CSS-variable layer in `tokens.css` (`--color-border-focus`) supersedes Mantine's focus-ring colour through the component CSS in `theme.ts` defaults; no Mantine-internal override is required.

## Versions to install

```bash
pnpm add @mantine/core@9 @mantine/hooks@9 @mantine/dates@9 @mantine/notifications@9 @mantine/form@9 dayjs zod react-i18next i18next @tabler/icons-react
```

`@mantine/carousel` is NOT installed — not used in iter-2a.

## Migration checklist (frontend)

- [ ] `<html {...mantineHtmlProps} lang="en">` at app root.
- [ ] `<ColorSchemeScript defaultColorScheme="light" />` in `<head>` (matches `MantineProvider` setting — see `Q1` in OPEN_QUESTIONS).
- [ ] All `@mantine/dates` callbacks treated as `string`, not `Date`.
- [ ] If a form is added beyond P-15, validation goes through `schemaResolver` (not `zodResolver`).
- [ ] If a `<Collapse>` is added, prop is `expanded` (not `in`).
- [ ] No usage of `v8CssVariablesResolver` unless a visual regression is reported and triaged.
````

- [ ] **Step 2: Smoke-test the markdown**

Open the file in any markdown previewer. Confirm:
- All code fences render with language hint.
- No broken table.
- All links to OPEN_QUESTIONS / spec sheet are textual references (no broken file paths).

- [ ] **Step 3: Commit**

Stage only this file. Generate the commit subject via `caveman:caveman-commit` skill, e.g. `docs(handoff): add Mantine 9 migration notes ADR`. Then:

```bash
git add docs/design_handoff/MANTINE_9_NOTES.md
git commit -m "<caveman-commit output>"
```

---

## Task 2: Add breakpoints to theme.ts

**Files:**
- Modify: `docs/design_handoff/theme.ts` (insert before the closing `}` of the `createTheme(...)` call, after the `cursorType` block, before `components`)

- [ ] **Step 1: Read current theme.ts**

Use the Read tool on `docs/design_handoff/theme.ts`. Locate the `cursorType: "pointer",` line (line ~135) and the `components: {` line that follows it.

- [ ] **Step 2: Insert breakpoints block**

Add this block right after `cursorType: "pointer",` and before `/* ── Component defaults ───…`:

```typescript
  /* ── Breakpoints ──────────────────────────────────────── */
  // Layout flip rule: only `md` (1024px) is meaningful. `xs`/`sm`
  // sit below the iPhone Air threshold (420px CSS, primary device)
  // so `visibleFrom="md"` correctly hides desktop-only content on
  // the smallest supported screen. `lg`/`xl` are guides for max-
  // width containers on wide desktops.
  breakpoints: {
    xs: "20em",   // 320px — iPhone SE 1 narrowest
    sm: "30em",   // 480px — phablet edge
    md: "64em",   // 1024px — DESKTOP FLIP (only meaningful one)
    lg: "80em",   // 1280px — wide desktop
    xl: "96em",   // 1536px — ultrawide
  },
```

- [ ] **Step 3: Verify TypeScript syntax**

Read the modified file. Confirm:
- No trailing comma after the final breakpoint property.
- Block sits inside the `createTheme({ ... })` call.
- The `components: {` block immediately follows.

There is no TS pipeline to run; visual inspection is sufficient.

- [ ] **Step 4: Commit**

```bash
git add docs/design_handoff/theme.ts
git commit -m "<caveman-commit output, e.g. 'feat(handoff): add Mantine 9 breakpoints to theme'>"
```

---

## Task 3: Add Breakpoints section to spec sheet

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — insert new section between the existing `<section id="tokens">…</section>` and `<section id="vocabulary">…</section>`. Also add a TOC entry.

- [ ] **Step 1: Add TOC entry**

In the `<aside class="toc">` block, find the line `<a href="#vocabulary">Vocabulary map</a>` (around line 297). Add immediately before it:

```html
  <a href="#breakpoints">Breakpoints</a>
```

- [ ] **Step 2: Insert the Breakpoints section**

Find the closing `</section>` of `<section id="tokens">` (the one ending `<p>Шкала <code>0/1/2/3/4/5/6/8/10/12/16/20</code>...`). Insert immediately after that closing tag:

```html
<section id="breakpoints">
  <h2>Breakpoints</h2>
  <p>2-step layout: mobile (&lt; <code>md</code>) and desktop (&ge; <code>md</code>). Only <code>md</code> at 1024px is a meaningful flip; lower breakpoints are Mantine plumbing for narrow phones, higher ones are guides for max-width containers.</p>

  <table>
    <thead><tr><th>Key</th><th>em</th><th>px</th><th>Use</th></tr></thead>
    <tbody>
      <tr><td><code>xs</code></td><td>20em</td><td>320</td><td>iPhone SE 1 narrowest — no layout flip</td></tr>
      <tr><td><code>sm</code></td><td>30em</td><td>480</td><td>phablet edge — no layout flip</td></tr>
      <tr><td><code>md</code></td><td>64em</td><td>1024</td><td>⚠️ MAIN FLIP · mobile↔desktop</td></tr>
      <tr><td><code>lg</code></td><td>80em</td><td>1280</td><td>wide desktop max-width guide</td></tr>
      <tr><td><code>xl</code></td><td>96em</td><td>1536</td><td>ultrawide max-width guide</td></tr>
    </tbody>
  </table>

  <h3>Primary mobile target</h3>
  <p>iPhone Air, 6.5", 2736×1260 physical @ DPR 3 = <strong>420×912 CSS px</strong> portrait. Min-width target across all components is 420px; 360px (older devices) is best-effort, not a guarantee.</p>

  <h3>Per-page layout flip rules</h3>
  <table>
    <thead><tr><th>Page</th><th>&lt; <code>md</code> (mobile)</th><th>&ge; <code>md</code> (desktop)</th></tr></thead>
    <tbody>
      <tr><td>P-08 Home</td><td>single column, sticky bottom-tabs</td><td>two-column with side rail</td></tr>
      <tr><td>P-15 Create Triage Block</td><td>full-screen form; DatePicker → bottom Drawer</td><td>modal form; DatePicker → popover</td></tr>
      <tr><td>P-16 Block detail</td><td>stack: header above counters</td><td>row: header left, counters right</td></tr>
      <tr><td>P-22 Curate (mobile)</td><td>this layout — single-track + DISCARD top + staging row</td><td>—</td></tr>
      <tr><td>P-23 Curate (desktop)</td><td>—</td><td>this layout — left queue + center player + right destinations</td></tr>
      <tr><td>P-25 Device picker</td><td>full-screen sheet</td><td>centered modal</td></tr>
    </tbody>
  </table>

  <h3>Mantine usage</h3>
  <p>Use <code>visibleFrom="md"</code> / <code>hiddenFrom="md"</code> on layout primitives. For conditional logic in JS use <code>useMediaQuery('(min-width: 64em)')</code>.</p>
<pre><code>import { useMediaQuery } from "@mantine/hooks";

const isDesktop = useMediaQuery("(min-width: 64em)");
return isDesktop ? &lt;DesktopCurate /&gt; : &lt;MobileCurate /&gt;;</code></pre>
</section>
```

- [ ] **Step 3: Smoke test**

Open `docs/design_handoff/04 Component spec sheet.html` in browser. Click the new TOC link "Breakpoints" — should scroll to the section. Tables render with borders, no overflow.

- [ ] **Step 4: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add Breakpoints section to spec sheet'>"
```

---

## Task 4: Add Icon mapping section to spec sheet

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — insert section after `<section id="vocabulary">…</section>`, before `<section id="button">`.

- [ ] **Step 1: Add TOC entry**

In `<aside class="toc">` find `<a href="#vocabulary">Vocabulary map</a>`. Add immediately after it:

```html
  <a href="#icons">Icon mapping</a>
```

- [ ] **Step 2: Insert Icon mapping section**

Find the closing `</section>` of `<section id="vocabulary">`. Insert this section right after it, before `<section id="button">`:

```html
<section id="icons">
  <h2>Icon mapping</h2>
  <dl class="meta-grid">
    <dt>Library</dt><dd><code>@tabler/icons-react</code></dd>
    <dt>Used in</dt><dd>everywhere with an icon</dd>
    <dt>Sizes</dt><dd>12 / 14 / 16 / 18 / 20 / 22 (px) — passed via tabler's <code>size</code> prop</dd>
  </dl>

  <p>Design system uses ~20 named icon roles. Each maps 1:1 to a tabler component. Centralise in <code>src/components/icons.ts</code> as named re-exports so renames touch one file.</p>

  <h3>Mapping</h3>
  <table>
    <thead><tr><th>Design name</th><th>Tabler component</th><th>Note</th></tr></thead>
    <tbody>
      <tr><td>play</td><td><code>IconPlayerPlay</code></td><td>player + scrub bar</td></tr>
      <tr><td>pause</td><td><code>IconPlayerPause</code></td><td>player + scrub bar</td></tr>
      <tr><td>prev</td><td><code>IconPlayerSkipBack</code></td><td>J hotkey</td></tr>
      <tr><td>next</td><td><code>IconPlayerSkipForward</code></td><td>K hotkey</td></tr>
      <tr><td>chevron-right</td><td><code>IconChevronRight</code></td><td>nav-rows, list disclosure</td></tr>
      <tr><td>chevron-down</td><td><code>IconChevronDown</code></td><td>StyleSelector trigger</td></tr>
      <tr><td>close</td><td><code>IconX</code></td><td>modal/drawer close, multi-select cancel</td></tr>
      <tr><td>search</td><td><code>IconSearch</code></td><td>search inputs, P-17</td></tr>
      <tr><td>grid</td><td><code>IconLayoutGrid</code></td><td>view toggle</td></tr>
      <tr><td>list</td><td><code>IconList</code></td><td>view toggle</td></tr>
      <tr><td>filter</td><td><code>IconFilter</code></td><td>P-14 status filter</td></tr>
      <tr><td>calendar</td><td><code>IconCalendar</code></td><td>DatePicker trigger leading slot</td></tr>
      <tr><td>check</td><td><code>IconCheck</code></td><td>selected state, success notifications</td></tr>
      <tr><td>trash</td><td><code>IconTrash</code></td><td>destructive actions</td></tr>
      <tr><td>alert</td><td><code>IconAlertTriangle</code></td><td>error states (S-03)</td></tr>
      <tr><td>wifi-off</td><td><code>IconWifiOff</code></td><td>player disconnected state</td></tr>
      <tr><td>undo</td><td><code>IconArrowBackUp</code></td><td>U hotkey, undo discard</td></tr>
      <tr><td>help</td><td><code>IconHelp</code></td><td>hotkey overlay trigger (?)</td></tr>
      <tr><td>menu</td><td><code>IconDots</code></td><td>kebab on track row</td></tr>
      <tr><td>arrow-up</td><td><code>IconArrowUp</code></td><td>P-09 reorder</td></tr>
      <tr><td>arrow-down</td><td><code>IconArrowDown</code></td><td>P-09 reorder</td></tr>
      <tr><td>plus</td><td><code>IconPlus</code></td><td>new category, new block</td></tr>
    </tbody>
  </table>

  <h3>Re-export pattern</h3>
<pre><code>// src/components/icons.ts
export {
  IconPlayerPlay        as PlayIcon,
  IconPlayerPause       as PauseIcon,
  IconPlayerSkipBack    as PrevIcon,
  IconPlayerSkipForward as NextIcon,
  IconX                 as CloseIcon,
  IconSearch            as SearchIcon,
  // ...
} from "@tabler/icons-react";</code></pre>
  <p>Components import from <code>./icons</code>, never from <code>@tabler/icons-react</code> directly. A future swap (e.g. to lucide) becomes a one-file change.</p>
</section>
```

- [ ] **Step 3: Smoke test**

Reload the HTML in browser. New TOC link "Icon mapping" scrolls correctly. Table renders, no horizontal overflow at desktop width.

- [ ] **Step 4: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add Icon mapping section to spec sheet'>"
```

---

## Task 5: Extend CategoryPill spec

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace the existing brief `<section id="categorypill">…</section>` with a full spec.

- [ ] **Step 1: Locate existing block**

Find `<section id="categorypill">` and its closing `</section>` (around lines 990–998). Note the surrounding context (preceded by TrackRow's closing, followed by StyleSelector).

- [ ] **Step 2: Replace with full spec**

Replace the entire `<section id="categorypill">…</section>` block with:

```html
<section id="categorypill">
  <h2>CategoryPill</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd><code>&lt;Badge&gt;</code> with <code>radius="xl"</code> (full)</dd>
    <dt>Used in</dt><dd>P-09 categories list, P-08 Home current style chip, P-10 category detail header, P-22 Curate destination row labels</dd>
    <dt>Variants</dt><dd>idle · hover · selected · disabled</dd>
  </dl>

  <h3>Anatomy</h3>
  <p>Pill: radius full, padding 4×10, mono font 11/14. Optional trailing count badge (number, mono, opacity 0.7). Min height 24.</p>

  <h3>States</h3>
  <table>
    <thead><tr><th>State</th><th>bg</th><th>fg</th><th>border</th></tr></thead>
    <tbody>
      <tr><td>idle</td><td><code>--color-bg-muted</code></td><td><code>--color-fg</code></td><td>none</td></tr>
      <tr><td>hover</td><td><code>--color-bg-subtle</code> + <code>--color-border</code></td><td><code>--color-fg</code></td><td>1px <code>--color-border</code></td></tr>
      <tr><td>selected</td><td><code>--color-fg</code></td><td><code>--color-fg-inverse</code></td><td>none</td></tr>
      <tr><td>disabled</td><td><code>--color-bg-subtle</code></td><td><code>--color-fg-subtle</code></td><td>none</td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type CategoryPillProps = {
  label: string;
  count?: number;            // optional trailing count
  selected?: boolean;
  disabled?: boolean;
  onClick?: () =&gt; void;
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>&lt;Badge
  variant={selected ? "filled" : "default"}
  color="neutral.9"
  radius="xl"
  size="sm"
  onClick={disabled ? undefined : onClick}
  style={{ cursor: disabled ? "default" : "pointer", textTransform: "none" }}
&gt;
  {label}
  {count != null &amp;&amp; (
    &lt;span style={{ marginLeft: 6, opacity: 0.7, fontFamily: "var(--font-mono)" }}&gt;
      {count}
    &lt;/span&gt;
  )}
&lt;/Badge&gt;</code></pre>
  <p>Override Mantine's <code>textTransform: "uppercase"</code> default — CategoryPill is mixed-case. Mono trailing count must NOT inherit the badge's tracking.</p>
</section>
```

- [ ] **Step 3: Smoke test**

Reload HTML. CategoryPill section now has Anatomy / States / Props / Mantine mapping. Existing in-page anchor `#categorypill` still works.

- [ ] **Step 4: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): expand CategoryPill spec to full contract'>"
```

---

## Task 6: Extend StyleSelector spec

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace existing brief `<section id="styleselector">…</section>`.

- [ ] **Step 1: Replace section**

Find `<section id="styleselector">…</section>` (around lines 1000–1008). Replace with:

```html
<section id="styleselector">
  <h2>StyleSelector</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd><code>&lt;Menu&gt;</code> + <code>&lt;UnstyledButton&gt;</code> trigger</dd>
    <dt>Used in</dt><dd>top bar (always visible), P-08 Home, P-15 Create Triage Block form, P-19 Transfer step-1</dd>
    <dt>Variants</dt><dd>compact (32 height, top bar) · regular (44 height, forms)</dd>
  </dl>

  <h3>Anatomy</h3>
  <p>Trigger: <code>{styleName}</code> in 14/600 + chevron-down 14px on the right, 8px gap. Background <code>--color-bg-subtle</code>, border 1px <code>--color-border</code>, radius <code>sm</code>. On open: dropdown anchored bottom-start, min-width = trigger width, max-width 320, max-height 360 with scroll.</p>

  <p>Dropdown content: list of user's styles (regular MenuItem). Selected style has check icon (16px) on the right + <code>fontWeight: 600</code>. Below the list, a 1px divider, then a fixed footer item "Manage styles…" (mono, 11px, links to P-09 Categories).</p>

  <h3>States</h3>
  <table>
    <thead><tr><th>State</th><th>Visual change</th></tr></thead>
    <tbody>
      <tr><td>idle</td><td>baseline</td></tr>
      <tr><td>hover</td><td>trigger bg <code>--color-bg-muted</code></td></tr>
      <tr><td>open</td><td>trigger border <code>--color-border-strong</code>, chevron rotated 180°</td></tr>
      <tr><td>empty</td><td>dropdown shows EmptyState body "No styles yet" + button "Create style" (links to P-09)</td></tr>
      <tr><td>disabled</td><td>opacity 0.4, no dropdown on click</td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type StyleSelectorProps = {
  styles: { id: string; name: string }[];
  selectedId: string | null;
  size?: "compact" | "regular";   // default "regular"
  disabled?: boolean;
  onSelect: (id: string) =&gt; void;
  onManage?: () =&gt; void;          // links to /categories
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>&lt;Menu position="bottom-start" width="target" withinPortal&gt;
  &lt;Menu.Target&gt;
    &lt;UnstyledButton
      disabled={disabled}
      style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        padding: "0 12px", height: size === "compact" ? 32 : 44,
        background: "var(--color-bg-subtle)",
        border: "1px solid var(--color-border)",
        borderRadius: "var(--mantine-radius-sm)",
        fontWeight: 600,
      }}
    &gt;
      {selected?.name ?? "Select style"}
      &lt;ChevronDownIcon size={14} /&gt;
    &lt;/UnstyledButton&gt;
  &lt;/Menu.Target&gt;

  &lt;Menu.Dropdown&gt;
    {styles.length === 0 ? (
      &lt;Menu.Item disabled&gt;No styles yet&lt;/Menu.Item&gt;
    ) : (
      styles.map((s) =&gt; (
        &lt;Menu.Item
          key={s.id}
          onClick={() =&gt; onSelect(s.id)}
          rightSection={s.id === selectedId ? &lt;CheckIcon size={16} /&gt; : null}
          style={{ fontWeight: s.id === selectedId ? 600 : 400 }}
        &gt;
          {s.name}
        &lt;/Menu.Item&gt;
      ))
    )}
    &lt;Menu.Divider /&gt;
    &lt;Menu.Item onClick={onManage} ff="monospace" fz={11}&gt;
      Manage styles…
    &lt;/Menu.Item&gt;
  &lt;/Menu.Dropdown&gt;
&lt;/Menu&gt;</code></pre>
</section>
```

- [ ] **Step 2: Smoke test**

Reload HTML. StyleSelector section now full. Code snippet renders inside `<pre><code>`.

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): expand StyleSelector spec to full contract'>"
```

---

## Task 7: Extend BucketCounters spec

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace existing brief `<section id="bucketcounters">…</section>`.

- [ ] **Step 1: Replace section**

Find `<section id="bucketcounters">…</section>` (around lines 1010–1018). Replace with:

```html
<section id="bucketcounters">
  <h2>BucketCounters</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd>composition (<code>&lt;SimpleGrid&gt;</code> + per-cell <code>&lt;UnstyledButton&gt;</code>)</dd>
    <dt>Used in</dt><dd>P-16 BlockHeader (right column), P-17 bucket detail (header)</dd>
    <dt>Cell variants</dt><dd>active · inactive (deleted-category, S-10) · empty (count=0)</dd>
  </dl>

  <h3>Anatomy</h3>
  <p>Grid of 6+ cells: <code>NEW · OLD · NOT · UNCLASSIFIED · DISCARD · STAGING-per-category</code>. Each cell: uppercase mono label (11/14, tracking 0.04em) above a large number (28/32, semibold). Optional below-number progress hint (mono 11, e.g. "<code>12 / 38</code>").</p>

  <h3>Layout</h3>
  <table>
    <thead><tr><th>Viewport</th><th>Grid</th><th>Cell padding</th></tr></thead>
    <tbody>
      <tr><td>&lt; <code>md</code> (mobile)</td><td><code>SimpleGrid cols={3}</code></td><td>12 / 8</td></tr>
      <tr><td>&ge; <code>md</code> (desktop)</td><td><code>SimpleGrid cols={6}</code></td><td>16 / 12</td></tr>
    </tbody>
  </table>

  <h3>States</h3>
  <table>
    <thead><tr><th>State</th><th>Visual change</th></tr></thead>
    <tbody>
      <tr><td>active (count &gt; 0, has destination)</td><td>baseline; clickable cell (UnstyledButton); hover bg <code>--color-bg-muted</code></td></tr>
      <tr><td>empty (count = 0)</td><td>number colour <code>--color-fg-subtle</code>; not clickable</td></tr>
      <tr><td>inactive (S-10 deleted-category bucket)</td><td>opacity 0.5; small badge "DELETED" in <code>--color-danger</code> below number; clickable but routes to S-10 explainer</td></tr>
      <tr><td>active (selected)</td><td>cell bg <code>--color-bg-muted</code>, border 1px <code>--color-border-strong</code></td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type Bucket = {
  key: "NEW" | "OLD" | "NOT" | "UNCLASSIFIED" | "DISCARD" | string; // string for staging-{categoryId}
  label: string;     // display label (uppercase or category name)
  count: number;
  total?: number;    // for "x / total" hint
  deleted?: boolean; // S-10 inactive variant
  selected?: boolean;
};

type BucketCountersProps = {
  buckets: Bucket[];
  onSelect?: (key: string) =&gt; void;
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>import { SimpleGrid, UnstyledButton, Stack, Text, Badge } from "@mantine/core";

&lt;SimpleGrid cols={{ base: 3, md: 6 }} spacing="xs" verticalSpacing="xs"&gt;
  {buckets.map((b) =&gt; (
    &lt;UnstyledButton
      key={b.key}
      disabled={b.count === 0 &amp;&amp; !b.deleted}
      onClick={() =&gt; onSelect?.(b.key)}
      style={{
        padding: "12px 8px",
        opacity: b.deleted ? 0.5 : 1,
        background: b.selected ? "var(--color-bg-muted)" : "transparent",
        border: b.selected ? "1px solid var(--color-border-strong)" : "1px solid transparent",
        borderRadius: "var(--mantine-radius-sm)",
        textAlign: "left",
      }}
    &gt;
      &lt;Stack gap={4}&gt;
        &lt;Text ff="monospace" fz={11} tt="uppercase" c="dimmed"&gt;
          {b.label}
        &lt;/Text&gt;
        &lt;Text fw={600} fz={28} c={b.count === 0 ? "var(--color-fg-subtle)" : undefined}&gt;
          {b.count}
        &lt;/Text&gt;
        {b.total != null &amp;&amp; (
          &lt;Text ff="monospace" fz={11} c="dimmed"&gt;
            {b.count} / {b.total}
          &lt;/Text&gt;
        )}
        {b.deleted &amp;&amp; (
          &lt;Badge variant="light" color="red.7" size="xs"&gt;DELETED&lt;/Badge&gt;
        )}
      &lt;/Stack&gt;
    &lt;/UnstyledButton&gt;
  ))}
&lt;/SimpleGrid&gt;</code></pre>
</section>
```

- [ ] **Step 2: Smoke test**

Reload HTML. BucketCounters section renders with 3 tables (Layout, States, plus implicit Anatomy / Props / Mantine).

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): expand BucketCounters spec to full contract'>"
```

---

## Task 8: Extend BlockHeader spec

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace existing brief `<section id="blockheader">…</section>`.

- [ ] **Step 1: Replace section**

Find `<section id="blockheader">…</section>` (around lines 1020–1028). Replace with:

```html
<section id="blockheader">
  <h2>BlockHeader</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd>composition (<code>&lt;Group&gt;</code> + <code>&lt;Stack&gt;</code> + <code>&lt;Button&gt;</code>)</dd>
    <dt>Used in</dt><dd>P-16 Triage Block detail (top of page)</dd>
  </dl>

  <h3>Anatomy</h3>
  <p>Two-column row at <code>&ge; md</code>; vertical stack at <code>&lt; md</code>.</p>
  <ul>
    <li><strong>Left column:</strong> Block name (h2, 24/30, semibold), style CategoryPill (small), week range (mono 12/16, e.g. "Apr 21 — Apr 27 · 38 tracks").</li>
    <li><strong>Right column:</strong> BucketCounters mini-row + finalize CTA (Button primary, size lg).</li>
  </ul>

  <h3>States</h3>
  <table>
    <thead><tr><th>State</th><th>Visual change</th><th>Finalize button</th></tr></thead>
    <tbody>
      <tr><td>in_progress (untouched)</td><td>baseline</td><td>disabled — tooltip "Triage all tracks first"</td></tr>
      <tr><td>in_progress (some triaged)</td><td>baseline</td><td>disabled until UNCLASSIFIED count = 0</td></tr>
      <tr><td>ready (UNCLASSIFIED = 0)</td><td>baseline</td><td>enabled, primary CTA</td></tr>
      <tr><td>finalized</td><td>name has trailing badge "FINALIZED" (filled neutral.9)</td><td>replaced with read-only "Finalized {date}" mono caption</td></tr>
      <tr><td>finalizing (long-op, B7)</td><td>baseline</td><td>loading spinner; copy variants by elapsed time (see OPEN_QUESTIONS Q9)</td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type BlockHeaderProps = {
  block: {
    id: string;
    name: string;
    style: { id: string; name: string };
    weekRange: { from: string; to: string }; // ISO date strings
    trackCount: number;
    status: "in_progress" | "ready" | "finalized" | "finalizing";
    finalizedAt?: string;
    unclassifiedCount: number;
  };
  buckets: Bucket[];
  onFinalize: () =&gt; void;
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>import { Group, Stack, Title, Button, Text, Badge } from "@mantine/core";

&lt;Group justify="space-between" align="flex-start" wrap="nowrap"
       style={{ flexDirection: isMobile ? "column" : "row", gap: 24 }}&gt;
  &lt;Stack gap="xs"&gt;
    &lt;Group gap="sm"&gt;
      &lt;Title order={2}&gt;{block.name}&lt;/Title&gt;
      {block.status === "finalized" &amp;&amp; (
        &lt;Badge variant="filled" color="neutral.9"&gt;FINALIZED&lt;/Badge&gt;
      )}
    &lt;/Group&gt;
    &lt;CategoryPill label={block.style.name} /&gt;
    &lt;Text ff="monospace" fz={12} c="dimmed"&gt;
      {formatRange(block.weekRange)} · {block.trackCount} tracks
    &lt;/Text&gt;
  &lt;/Stack&gt;

  &lt;Stack gap="md" align={isMobile ? "stretch" : "flex-end"}&gt;
    &lt;BucketCounters buckets={buckets} /&gt;
    {block.status === "finalized" ? (
      &lt;Text ff="monospace" fz={12} c="dimmed"&gt;
        Finalized {formatDate(block.finalizedAt)}
      &lt;/Text&gt;
    ) : (
      &lt;Button
        size="lg"
        disabled={block.unclassifiedCount &gt; 0}
        loading={block.status === "finalizing"}
        onClick={onFinalize}
      &gt;
        Finalize
      &lt;/Button&gt;
    )}
  &lt;/Stack&gt;
&lt;/Group&gt;</code></pre>
</section>
```

- [ ] **Step 2: Smoke test**

Reload HTML. BlockHeader section renders.

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): expand BlockHeader spec to full contract'>"
```

---

## Task 9: Extend PlayerCard spec (per-state visual matrix)

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace existing `<section id="playercard">…</section>` with extended version that includes per-state visual matrix.

- [ ] **Step 1: Locate existing block**

Find `<section id="playercard">` (line ~919). It already has decent prose; the gap is the per-state matrix. Replace the entire section.

- [ ] **Step 2: Replace section**

```html
<section id="playercard">
  <h2>PlayerCard</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd>composition (<code>&lt;Paper&gt;</code> + custom layout)</dd>
    <dt>Used in</dt><dd>P-22, P-23, P-24 mini-player</dd>
    <dt>Variants</dt><dd>full · sticky-mini · mobile · desktop · accent</dd>
  </dl>

  <p>Composition: cover (square), title (size 22 desktop / 18 mobile, ellipsis on overflow), artists (muted), metadata row (mono — BPM · key · duration), scrub bar, transport (prev/play/next).</p>

  <h3>States — visual matrix</h3>
  <table>
    <thead><tr><th>State</th><th>Center button icon</th><th>Scrub opacity</th><th>Subline copy</th></tr></thead>
    <tbody>
      <tr><td>idle</td><td><code>PlayIcon</code> filled</td><td>1.0</td><td>artist names</td></tr>
      <tr><td>playing</td><td><code>PauseIcon</code> filled</td><td>1.0</td><td>artist names</td></tr>
      <tr><td>buffering</td><td><code>&lt;Loader size={20} /&gt;</code></td><td>0.4</td><td>artist names + small "Buffering…" mono badge</td></tr>
      <tr><td>paused</td><td><code>PlayIcon</code> filled</td><td>0.6</td><td>artist names</td></tr>
      <tr><td>error</td><td><code>AlertIcon</code> in <code>--color-danger</code></td><td>0.4 + scrub disabled</td><td>"Playback failed · <a>Retry</a>"</td></tr>
      <tr><td>disconnected</td><td><code>WifiOffIcon</code> in <code>--color-fg-muted</code></td><td>0.3 + scrub disabled</td><td>"Reconnect Spotify · <a>Open device picker</a>"</td></tr>
    </tbody>
  </table>

  <h3>Variants — sizing</h3>
  <table>
    <thead><tr><th>Variant</th><th>Cover</th><th>Title</th><th>Show transport</th><th>Use case</th></tr></thead>
    <tbody>
      <tr><td>full · desktop</td><td>108×108</td><td>22/30</td><td>yes</td><td>P-23 center column</td></tr>
      <tr><td>full · mobile</td><td>square 100% width × 320</td><td>18/26</td><td>yes</td><td>P-22 top section</td></tr>
      <tr><td>sticky-mini · desktop</td><td>40×40</td><td>14/20</td><td>compact</td><td>P-08 Home bottom rail</td></tr>
      <tr><td>sticky-mini · mobile</td><td>40×40</td><td>14/20</td><td>play only</td><td>mobile sticky</td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type PlayerState =
  | "idle" | "playing" | "buffering" | "paused" | "error" | "disconnected";

type PlayerCardProps = {
  track: { title: string; artists: string; cover: string; bpm?: number; key?: string; duration: number };
  state: PlayerState;
  progress: number;     // 0..1
  variant: "full" | "mini";
  onPlayPause: () =&gt; void;
  onPrev?: () =&gt; void;
  onNext?: () =&gt; void;
  onRetry?: () =&gt; void;
  onOpenDevicePicker?: () =&gt; void;
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>// Mini variant shown; full variant adds prev/next ActionIcons + larger title.
import { Paper, Group, Stack, Text, Title, ActionIcon, Progress, Loader } from "@mantine/core";
import { PlayIcon, PauseIcon, AlertIcon, WifiOffIcon } from "./icons";

const centerIcon = {
  idle: &lt;PlayIcon /&gt;,
  playing: &lt;PauseIcon /&gt;,
  buffering: &lt;Loader size={20} /&gt;,
  paused: &lt;PlayIcon /&gt;,
  error: &lt;AlertIcon style={{ color: "var(--color-danger)" }} /&gt;,
  disconnected: &lt;WifiOffIcon style={{ color: "var(--color-fg-muted)" }} /&gt;,
}[state];

const scrubOpacity = state === "buffering" ? 0.4
  : state === "paused" ? 0.6
  : state === "error" ? 0.4
  : state === "disconnected" ? 0.3
  : 1.0;

&lt;Paper p={variant === "mini" ? "sm" : "lg"} radius="md" withBorder={variant === "mini"}&gt;
  &lt;Group align="center" gap="lg" wrap="nowrap"&gt;
    &lt;Cover size={variant === "mini" ? 40 : 108} src={track.cover} /&gt;
    &lt;Stack gap={4} flex={1}&gt;
      &lt;Text size="xs" tt="uppercase" c="dimmed" ff="monospace"&gt;Now Playing&lt;/Text&gt;
      &lt;Title order={variant === "mini" ? 5 : 3} truncate&gt;{track.title}&lt;/Title&gt;
      {state === "error" ? (
        &lt;Text size="sm" c="var(--color-danger)"&gt;Playback failed · &lt;a onClick={onRetry}&gt;Retry&lt;/a&gt;&lt;/Text&gt;
      ) : state === "disconnected" ? (
        &lt;Text size="sm" c="dimmed"&gt;Reconnect Spotify · &lt;a onClick={onOpenDevicePicker}&gt;Open device picker&lt;/a&gt;&lt;/Text&gt;
      ) : (
        &lt;Text size="sm" c="dimmed"&gt;{track.artists}&lt;/Text&gt;
      )}
    &lt;/Stack&gt;
    &lt;ActionIcon
      size={variant === "mini" ? "lg" : 44}
      radius="xl"
      variant="filled"
      color="neutral.9"
      onClick={onPlayPause}
      disabled={state === "error" || state === "disconnected"}
    &gt;
      {centerIcon}
    &lt;/ActionIcon&gt;
  &lt;/Group&gt;
  &lt;Progress
    value={progress * 100}
    size={4}
    color="neutral.9"
    style={{ opacity: scrubOpacity, marginTop: variant === "mini" ? 4 : 16 }}
  /&gt;
&lt;/Paper&gt;</code></pre>
</section>
```

- [ ] **Step 3: Smoke test**

Reload HTML. Visual matrix table renders. Code snippet has no escaped-character display issues.

- [ ] **Step 4: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add PlayerCard state matrix'>"
```

---

## Task 10: Extend TrackRow spec

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — replace existing `<section id="trackrow">…</section>`.

- [ ] **Step 1: Replace section**

Find `<section id="trackrow">` (line ~960). Replace with:

```html
<section id="trackrow">
  <h2>TrackRow</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd>composition (<code>&lt;Group&gt;</code> + <code>&lt;UnstyledButton&gt;</code>)</dd>
    <dt>Used in</dt><dd>P-10 (category detail), P-17 (bucket detail), P-23 left queue</dd>
    <dt>Variants</dt><dd>compact (48 height) · regular (64 height) · with-checkbox</dd>
  </dl>

  <h3>Anatomy</h3>
  <p>Three slots:</p>
  <ul>
    <li><strong>Leading</strong> (32×32, optional): index number (mono, dimmed) OR cover (regular variant) OR Checkbox (multi-select).</li>
    <li><strong>Middle</strong> (flex 1): title (14/20, semibold, ellipsis), artists (12/16, dimmed, ellipsis).</li>
    <li><strong>Trailing</strong>: badges row (key 9A, BPM, source flag) + actions (kebab Menu, optional duration mono).</li>
  </ul>

  <h3>States</h3>
  <table>
    <thead><tr><th>State</th><th>Visual change</th></tr></thead>
    <tbody>
      <tr><td>idle</td><td>baseline; bottom border 1px <code>--color-border</code></td></tr>
      <tr><td>hover</td><td>bg <code>--color-bg-muted</code></td></tr>
      <tr><td>selected (multi-select)</td><td>checkbox checked; bg <code>--color-bg-muted</code></td></tr>
      <tr><td>currently playing</td><td>left border 2px <code>--color-fg</code> (replaces 1px); bg <code>--color-bg-subtle</code>; small <code>NowPlayingDot</code> in trailing slot</td></tr>
      <tr><td>focus (keyboard)</td><td>2px ring <code>--color-border-focus</code> with inset (avoids horizontal-scroll jitter)</td></tr>
      <tr><td>disabled (e.g. unavailable in market)</td><td>opacity 0.5; not clickable; tooltip "Unavailable"</td></tr>
    </tbody>
  </table>

  <h3>Props</h3>
<pre><code>type Track = {
  id: string;
  title: string;
  artists: string;
  cover?: string;
  durationMs: number;
  key?: string;     // 9A
  bpm?: number;
  source: "beatport" | "spotify";
  unavailable?: boolean;
};

type TrackRowProps = {
  track: Track;
  index?: number;        // shown in leading slot if cover/checkbox absent
  variant?: "compact" | "regular";
  selectable?: boolean;  // shows leading checkbox
  selected?: boolean;
  playing?: boolean;     // currently playing track
  onClick?: () =&gt; void;
  onKebab?: () =&gt; void;
  onSelectChange?: (next: boolean) =&gt; void;
};</code></pre>

  <h3>Mantine mapping</h3>
<pre><code>import { Group, Stack, Text, Checkbox, Badge, ActionIcon, UnstyledButton } from "@mantine/core";

&lt;UnstyledButton
  onClick={track.unavailable ? undefined : onClick}
  data-playing={playing || undefined}
  style={(t) =&gt; ({
    display: "flex", alignItems: "center", gap: t.spacing.md,
    padding: variant === "regular" ? "12px 16px" : "8px 16px",
    minHeight: variant === "regular" ? 64 : 48,
    borderBottom: "1px solid var(--color-border)",
    borderLeft: playing ? "2px solid var(--color-fg)" : "1px solid transparent",
    background: playing ? "var(--color-bg-subtle)" : selected ? "var(--color-bg-muted)" : undefined,
    opacity: track.unavailable ? 0.5 : 1,
  })}
&gt;
  {selectable ? (
    &lt;Checkbox checked={selected} onChange={(e) =&gt; onSelectChange?.(e.currentTarget.checked)} /&gt;
  ) : variant === "regular" &amp;&amp; track.cover ? (
    &lt;Cover size={48} src={track.cover} /&gt;
  ) : (
    &lt;Text ff="monospace" fz={12} c="dimmed" w={32} ta="right"&gt;{index}&lt;/Text&gt;
  )}

  &lt;Stack gap={2} flex={1} miw={0}&gt;
    &lt;Text fw={600} truncate&gt;{track.title}&lt;/Text&gt;
    &lt;Text size="sm" c="dimmed" truncate&gt;{track.artists}&lt;/Text&gt;
  &lt;/Stack&gt;

  &lt;Group gap="xs" wrap="nowrap"&gt;
    {track.key &amp;&amp; &lt;Badge variant="outline" size="sm" color="neutral.5" ff="monospace"&gt;{track.key}&lt;/Badge&gt;}
    {track.bpm &amp;&amp; &lt;Badge variant="outline" size="sm" color="neutral.5" ff="monospace"&gt;{track.bpm}&lt;/Badge&gt;}
    &lt;Text ff="monospace" fz={12} c="dimmed"&gt;{formatDuration(track.durationMs)}&lt;/Text&gt;
    {playing &amp;&amp; &lt;NowPlayingDot /&gt;}
    &lt;ActionIcon variant="subtle" onClick={(e) =&gt; { e.stopPropagation(); onKebab?.(); }}&gt;
      &lt;MenuIcon size={16} /&gt;
    &lt;/ActionIcon&gt;
  &lt;/Group&gt;
&lt;/UnstyledButton&gt;</code></pre>
</section>
```

- [ ] **Step 2: Smoke test**

Reload HTML. TrackRow section now full. Note `NowPlayingDot` referenced — already documented in vocabulary map.

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): expand TrackRow spec to full contract'>"
```

---

## Task 11: Add Mantine 9 callouts to existing spec sections

**Files:**
- Modify: `docs/design_handoff/04 Component spec sheet.html` — small inline edits in three places.

- [ ] **Step 1: DatePicker — append callout box**

Find `<section id="datepicker">` (line ~733). Locate the closing `</pre>` of the existing Mantine mapping block. Immediately after that `</pre>`, before the section's closing `</section>`, insert:

```html
  <div class="callout">
    <div>
      <strong>Mantine 9 callout — value type is <code>string</code></strong>
      <p>From Mantine 8 onward, <code>onChange</code> receives <code>string | null</code> in <code>YYYY-MM-DD</code> form. Three integration patterns documented in <a href="MANTINE_9_NOTES.md">MANTINE_9_NOTES.md</a>. Native string state is recommended.</p>
    </div>
  </div>
  <div class="callout">
    <div>
      <strong>Mobile pattern — bottom Drawer</strong>
      <p>On <code>&lt; md</code> the popover is replaced with a bottom <code>&lt;Drawer position="bottom"&gt;</code> wrapping an inline <code>&lt;DatePicker&gt;</code>. Wrapper component <code>&lt;DateRangeField&gt;</code> uses <code>useMediaQuery('(max-width: 64em)')</code>. Recorded in OPEN_QUESTIONS Q3.</p>
    </div>
  </div>
```

- [ ] **Step 2: Button — fix focus row**

Find Button section's States table (line ~439). Locate the row:

```html
<tr><td>focus</td><td>2px focus ring цвета <code>--color-border-focus</code> с offset 2px</td><td>Mantine default + override <code>--mantine-color-blue-filled</code></td></tr>
```

Replace the third cell (`<td>Mantine default + override...</td>`) with:

```html
<td>Mantine default — focus ring colour comes from <code>--color-border-focus</code> via the <code>theme.ts</code> CSS-variable layer; no Mantine-internal override needed in 9.x</td>
```

- [ ] **Step 3: Add Form snippet for P-15**

Find the section `<section id="input">` (line ~481). After its closing `</section>`, before `<section id="select">`, insert a new mini-section about form validation:

```html
<section id="form-snippet">
  <h2>Form (P-15) — schemaResolver</h2>
  <dl class="meta-grid">
    <dt>Mantine</dt><dd><code>@mantine/form</code> with <code>schemaResolver</code> + Zod 4</dd>
    <dt>Used in</dt><dd>P-15 Create Triage Block</dd>
  </dl>

  <p>Mantine 9 removed <code>zodResolver</code>. Use <code>schemaResolver</code> with a Standard-Schema-compliant validator. Zod v4 is the recommended choice.</p>

<pre><code>import { useForm, schemaResolver } from "@mantine/form";
import { z } from "zod/v4";

const schema = z.object({
  name: z.string().min(1, { error: "Name required" }),
  style: z.string().min(1, { error: "Style required" }),
  date_from: z.string().min(1, { error: "Start date required" }),
  date_to: z.string().min(1, { error: "End date required" }),
});

const form = useForm({
  initialValues: { name: "", style: "", date_from: "", date_to: "" },
  validate: schemaResolver(schema, { sync: true }),
});</code></pre>
</section>
```

Also add a TOC entry: in `<aside class="toc">`, find `<a href="#input">Input</a>`, add immediately after it:

```html
  <a href="#form-snippet">Form (schemaResolver)</a>
```

- [ ] **Step 4: Smoke test**

Reload HTML. New callouts render in Datepicker section, Button focus row reads cleanly, Form section appears in TOC and renders.

- [ ] **Step 5: Commit**

```bash
git add docs/design_handoff/04\ Component\ spec\ sheet.html
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add Mantine 9 callouts and form snippet'>"
```

---

## Task 12: Create a11y.md

**Files:**
- Create: `docs/design_handoff/a11y.md`

- [ ] **Step 1: Write the file**

```markdown
# Accessibility Checklist · CLOUDER iter-2a

> Minimal a11y baseline. Not a full WCAG 2.2 AA audit. Public-launch audit is a separate ticket.

## 1. Focus visible

All interactive elements (`<button>`, `UnstyledButton`, custom button-divs) must show a visible focus ring on `:focus-visible` of colour `var(--color-border-focus)` with 2px offset. Mantine 9 renders this by default for its primitives once the theme exposes the CSS variable. Custom components (`DestinationButton`, `ListItem`) add the same ring manually.

## 2. Icon-only buttons require `aria-label`

Every `<ActionIcon>` and any custom icon-only button has an explicit `aria-label`. Examples:

- Hotkey overlay trigger: `aria-label="Show keyboard shortcuts"`.
- TrackRow kebab: `aria-label={`Actions for ${track.title}`}`.
- Player play/pause: `aria-label={state === "playing" ? "Pause" : "Play"}`.

## 3. Custom components — ARIA contract

### DestinationButton
- `role="button"` (UnstyledButton already provides).
- `aria-keyshortcuts="<digit>"` when `hotkey` prop is set (`aria-keyshortcuts="1"`).
- `aria-pressed={state === "primary"}` when `primary` is the meaningful selected state.
- `aria-disabled={state === "disabled"}` (UnstyledButton's `disabled` prop already handles this).

### ListItem
- Container has `role="listbox"` (or `role="menu"` for action menus).
- Items have `role="option"` (or `role="menuitem"`) with `aria-selected` reflecting state.
- Keyboard: ↑/↓ moves focus, Enter activates. Use Mantine's `useUncontrolled` + `useFocusReturn` patterns; do not roll a hand-coded loop.

### Hotkey overlay (Modal)
- Mantine `Modal` provides focus trap by default.
- On open: focus moves to first interactive child (the close button).
- On close: focus returns to the trigger (Mantine handles via `useFocusReturn` if `returnFocus` prop is `true`, which it is by default).

## 4. Contrast — pre-verified ramp

Tokens.css ramp passes WCAG AA at the relevant pairings (oklch sources rounded to perceptual lightness):

| Pair | Ratio | Status |
|---|---|---|
| `--color-fg` (neutral-900) on `--color-bg` (neutral-0) | ≈ 21:1 | ✅ AAA |
| `--color-fg-muted` (neutral-500) on `--color-bg` | ≈ 4.6:1 | ✅ AA body |
| `--color-fg-subtle` (neutral-400) on `--color-bg` | ≈ 3.1:1 | ✅ AA non-text |
| `--color-fg-inverse` (neutral-0) on `--color-fg` (neutral-900) | ≈ 21:1 | ✅ AAA |
| `--color-fg` on `--color-bg-muted` (neutral-100) | ≈ 19:1 | ✅ AAA |
| `--color-danger` text on `--color-bg` | ≈ 4.6:1 | ✅ AA |

Document this baseline so future palette tweaks have a regression target.

## 5. Reduced motion

Wrap motion-sensitive transitions in `@media (prefers-reduced-motion: reduce)`:

- DestinationButton `just-tapped` `scale(0.97)` → omit transform, only colour change.
- Multi-select bar slide-up → fade-in only, no translateY.
- Skeleton shimmer → static placeholder background, no animation loop.

Implementation hint:

```css
@media (prefers-reduced-motion: reduce) {
  * { animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; }
}
```

Plus per-component opt-outs for the few cases where state-driven transitions still make sense (e.g. focus ring fade).

## 6. Lang attribute

Per the i18n decision, iter-2a ships English copy: `<html lang="en" {...mantineHtmlProps}>`.

## 7. Out of scope (iter-2a)

- Full screen-reader audit (NVDA / VoiceOver).
- Keyboard-only navigation walkthrough across all 25 pages.
- Colour-blind verification beyond the contrast ratios above.
- High-contrast Windows mode.

These belong in a pre-public-launch a11y ticket.
```

- [ ] **Step 2: Smoke test**

Render the markdown. Confirm tables render and code fences display with language hint.

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/a11y.md
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add minimal a11y checklist'>"
```

---

## Task 13: Create i18n.md

**Files:**
- Create: `docs/design_handoff/i18n.md`

- [ ] **Step 1: Write the file**

```markdown
# i18n Setup · CLOUDER iter-2a

> Decision: EN-only copy for iter-2a, but i18n infrastructure in place from day-1 so adding RU later is a catalog-copy operation, not a refactor.

## Library

`react-i18next` + `i18next`. Combined ≈ 13 KB gz. No `i18next-browser-languagedetector` for iter-2a — locale is hard-coded `en`.

## Catalog file

`src/i18n/en.json`. Flat-by-screen structure:

```json
{
  "common": {
    "cancel": "Cancel",
    "save": "Save",
    "loading": "Loading…"
  },
  "auth": {
    "signin": "Sign in",
    "signup": "Sign up",
    "premiumRequired": "CLOUDER requires Spotify Premium"
  },
  "categories": {
    "empty": {
      "title": "No categories yet",
      "body": "Create your first category to start organising tracks.",
      "cta": "Create category"
    }
  },
  "triage": {
    "createBlock": "Create Triage Block",
    "discard": "DISCARD",
    "finalize": "Finalize",
    "longOp": {
      "warm": "Cold start, hang on…",
      "hot": "This is taking longer than usual. If nothing happens, refresh — the block may already exist."
    }
  },
  "notifications": {
    "error": {
      "networkLost": "Network lost",
      "spotifyDisconnected": "Spotify disconnected"
    }
  }
}
```

Naming: `<screen>.<element>` or `<screen>.<group>.<element>`. Two-level max. Avoid keys that mix concerns (`auth.errors.cancel` is wrong — make it `common.cancel`).

## Domain terms — never translated

These are part of the product vocabulary and stay English even after RU is added:

- `NEW`, `OLD`, `NOT`, `DISCARD`, `STAGING` (uppercase status labels in UI).
- `BPM`, `key` (musical key, like `9A`).
- `Now Playing`.
- `Curate`, `Triage Block`, `Finalize` (uppercase doesn't matter — these are product nouns).

If a future RU translator asks: those keys live as-is in `ru.json` too. Document this in the catalog file as a header comment.

## Init

```tsx
import i18next from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./i18n/en.json";

i18next.use(initReactI18next).init({
  lng: "en",
  fallbackLng: "en",
  resources: { en: { translation: en } },
  interpolation: { escapeValue: false }, // React already escapes
});
```

Init runs before `<MantineProvider>` mounts. If init takes more than a few ms, render a Suspense fallback at the app root.

## Usage

```tsx
import { useTranslation } from "react-i18next";

function CreateBlockButton() {
  const { t } = useTranslation();
  return <Button>{t("triage.createBlock")}</Button>;
}
```

For non-component contexts (e.g. `notifications.show()`), import `i18next` directly:

```tsx
import i18next from "i18next";
import { notifications } from "@mantine/notifications";

notifications.show({
  title: i18next.t("notifications.error.networkLost"),
  message: i18next.t("common.loading"),
});
```

## Adding RU later

1. Copy `en.json` → `ru.json`.
2. Translate values, leave keys + domain terms untouched.
3. Add to `resources` in init.
4. Add a locale switcher; persist user choice in localStorage; update `<html lang>` reactively.

Schema validation (key parity between catalogs) belongs in the build step then — not in iter-2a.
```

- [ ] **Step 2: Smoke test**

Render markdown. JSON block displays correctly.

- [ ] **Step 3: Commit**

```bash
git add docs/design_handoff/i18n.md
git commit -m "<caveman-commit output, e.g. 'docs(handoff): add i18n setup decision'>"
```

---

## Task 14: Update OPEN_QUESTIONS.md

**Files:**
- Modify: `docs/design_handoff/OPEN_QUESTIONS.md` — update Q1, Q2, Q3, Q5 sections.

- [ ] **Step 1: Q1 — record dark-theme fallback**

Find the `## Q1 — Dark theme parity (iter-2a)` section. Replace its `**Что делать:**` paragraph with:

```markdown
**Что делать (зафиксированный фронт-fallback):**

iter-2a ship `defaultColorScheme="light"` — auto-detect системного dark отключён до визуальной QA. tokens.css `.theme-dark` остаётся как готовый ramp для iter-2b. Toggle переключения темы — отдельный тикет в Profile/Settings (iter-2b). Дизайн может перебить решение после визуальной QA production-страниц в dark; до тех пор любая попытка автодетекта = риск показать пользователю не отрисованное состояние.
```

- [ ] **Step 2: Q2 — mark closed**

Find `## Q2 — Иконки`. Replace `**Status:**` block + `**Что делать:**` with:

```markdown
**Status (CLOSED · 2026-04-29):** выбрана `@tabler/icons-react`. Snippets в spec sheet уже использовали `IconPlayer*` имена — ratify de facto. Полный mapping (~22 имени) — в § Icon mapping в `04 Component spec sheet.html`. Re-export pattern через `src/components/icons.ts` зафиксирован.
```

- [ ] **Step 3: Q3 — record DatePicker fallback**

Find `## Q3 — DatePicker мобильный fullscreen vs popover`. Replace `**Что делать:**` paragraph with:

```markdown
**Что делать (зафиксированный фронт-fallback):**

Custom-компонент `DateRangeField`: `useMediaQuery('(max-width: 64em)')` → на mobile рендерит `<Drawer position="bottom">` с inline `<DatePicker>`, на desktop — стандартный `<DatePickerInput>` с popover. ~30 строк wrapper'а. Совпадает с макетом. Дизайн может перебить, если full-screen sheet это hard requirement (запасной вариант: popover-везде, тоже работает на 420px wide, но без air space).
```

- [ ] **Step 4: Q5 — record Spotify SDK contract**

Find `## Q5 — Web Playback SDK / device picker (P-25)`. Replace `**Что делать:**` paragraph + bullet list with:

```markdown
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
```

- [ ] **Step 5: Smoke test**

Render markdown. All four Q-sections updated; rest untouched.

- [ ] **Step 6: Commit**

```bash
git add docs/design_handoff/OPEN_QUESTIONS.md
git commit -m "<caveman-commit output, e.g. 'docs(handoff): record Q1/Q2/Q3/Q5 frontend fallbacks'>"
```

---

## Task 15: Sync README.md and README.ru.md

**Files:**
- Modify: `docs/design_handoff/README.md`
- Modify: `docs/design_handoff/README.ru.md`

- [ ] **Step 1: Update README.ru.md "Setup" section**

Find the `## Setup` section. Replace the entire section (from `## Setup` heading through the end of the second code-fence — about lines 34-66) with:

````markdown
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
````

- [ ] **Step 2: Update README.ru.md "Что в этой папке" table**

Find the table at the top of "Что в этой папке". Add three new rows after the `OPEN_QUESTIONS.md` row:

```markdown
| `MANTINE_9_NOTES.md` | Mantine 7→9 breaking changes ADR. Читай ПЕРВЫМ если копируешь любой code snippet. |
| `a11y.md` | Минимальный accessibility чеклист. |
| `i18n.md` | i18n setup (EN-only iter-2a, react-i18next infra). |
```

- [ ] **Step 3: Update README.md (English mirror)**

Open `docs/design_handoff/README.md`. Make the same three changes:
1. Replace the entire `## Setup` block with the same content as Step 1 above, translated to English (Mantine version, breakpoint values, decision table).
2. Add the same three table rows under "Files in this folder", in English.

(The English README is shorter/lighter than the RU one in the source; mirror only what's there.)

- [ ] **Step 4: Smoke test**

Render both READMEs. Verify:
- Decision tables render correctly.
- Code fence with `pnpm add ...` does not wrap awkwardly.
- Cross-links to `MANTINE_9_NOTES.md`, `a11y.md`, `i18n.md`, `OPEN_QUESTIONS.md` are all valid file paths.

- [ ] **Step 5: Commit**

```bash
git add docs/design_handoff/README.md docs/design_handoff/README.ru.md
git commit -m "<caveman-commit output, e.g. 'docs(handoff): sync READMEs to Mantine 9 + iter-2a decisions'>"
```

---

## Task 16: Final consistency pass

After all previous tasks are committed, do one final read-through.

- [ ] **Step 1: Cross-link check**

Search the four primary documents for filename references:

```bash
grep -n "MANTINE_9_NOTES\|OPEN_QUESTIONS\|a11y\.md\|i18n\.md" \
  docs/design_handoff/README.md \
  docs/design_handoff/README.ru.md \
  docs/design_handoff/04\ Component\ spec\ sheet.html \
  docs/design_handoff/OPEN_QUESTIONS.md
```

Confirm all references point to actual existing files. Fix any typos.

- [ ] **Step 2: Spec sheet TOC check**

Open `04 Component spec sheet.html`. Click every TOC link (Breakpoints, Icon mapping, Form (schemaResolver), all six extended component sections). Each must scroll to the right section.

- [ ] **Step 3: Browser sanity check**

Final browser open of `04 Component spec sheet.html`. Scroll top to bottom. No layout breakage, no overlapping text, no escaped-character display issues in code blocks.

- [ ] **Step 4: Acceptance-criteria sweep**

From the spec's Acceptance Criteria section, confirm:

- [ ] All 8 file-blocks updated/created.
- [ ] HTML catalogs `01`, `02`, `03` untouched (`git diff` should show no changes there).
- [ ] `04 Component spec sheet.html` opens cleanly.
- [ ] README setup snippet copy-pastes into a Mantine 9 project as-is.
- [ ] A frontend engineer reading the handoff can identify Mantine version, icon lib, i18n lib, breakpoint, six new component contracts, OPEN_QUESTIONS fallbacks, Spotify SDK contract.

- [ ] **Step 5: No commit needed if no changes**

If grep / TOC / browser checks reveal issues, fix and commit per-issue. If no issues found, do not create an empty commit.

---

## Self-review reminders for the executor

- Every task is independent: stop at any task, ship what's done.
- Smoke tests are visual — open the file. Trust your eyes.
- If a step's content references a file path / component name that doesn't yet exist (because an earlier task hasn't run), do tasks in order — don't skip ahead.
- When a commit subject is generated by `caveman:caveman-commit`, paste exactly what the skill produces. Do not edit it.
- The HTML spec sheet uses inline CSS classes (`callout`, `meta-grid`, `eyebrow`, `pill`, etc.). Reuse those classes in new sections — don't inline new styles.

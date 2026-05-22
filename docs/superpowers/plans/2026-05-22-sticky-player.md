# Sticky Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the desktop category + triage player panels `position: sticky` so they stay pinned below the header while the long track list scrolls.

**Architecture:** CSS-only. Add `position: sticky` + a header-height `top` offset + `align-self: flex-start` + a viewport-bounded `max-height`/`overflow-y` to each player panel's root. The page (document) is the scroll container; the desktop split `Flex` already uses `align="flex-start"` so the panel has room to move.

**Tech Stack:** React 19, Mantine 9, CSS modules + inline styles, Vitest (no new tests — sticky is CSS, not jsdom-assertable).

**Spec:** `docs/superpowers/specs/2026-05-22-sticky-player-design.md`

---

## File structure

**Changed**
- `frontend/src/features/categories/components/CategoryPlayerPanel.module.css` — `.root` becomes sticky.
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — both `<Stack>` roots become sticky (inline style).

No new files, no backend/router change, no new tests.

---

### Task 1: Category player — sticky `.root`

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.module.css`

- [ ] **Step 1: Update `.root`**

The current `.root` is:
```css
.root {
  width: 442px;
  flex-shrink: 0;
  padding: var(--mantine-spacing-md);
  border-right: 1px solid var(--mantine-color-default-border);
  height: 100%;
  overflow-y: auto;
}
```
Replace it with (drop the inert `height: 100%`; add `align-self`, `position: sticky`, `top`, `max-height`):
```css
.root {
  width: 442px;
  flex-shrink: 0;
  align-self: flex-start;
  position: sticky;
  top: calc(var(--app-shell-header-offset, 3.5rem) + var(--mantine-spacing-sm));
  max-height: calc(100vh - var(--app-shell-header-offset, 3.5rem) - var(--mantine-spacing-md));
  padding: var(--mantine-spacing-md);
  border-right: 1px solid var(--mantine-color-default-border);
  overflow-y: auto;
}
```

- [ ] **Step 2: Typecheck + run category player tests**

From `frontend/`:
```
pnpm typecheck && pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
```
Expected: no type errors; tests pass (the style change doesn't affect rendering/queries).

- [ ] **Step 3: Commit**

NO `Co-Authored-By` trailer (pre-commit hook rejects it).
```bash
git add frontend/src/features/categories/components/CategoryPlayerPanel.module.css
git commit -m "feat(categories): make the player panel sticky on desktop"
```

---

### Task 2: Triage player — sticky `<Stack>` roots

**Files:**
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`

- [ ] **Step 1: Update both Stack roots**

`BucketPlayerPanel` has TWO `<Stack>` roots — the empty-state branch and the playing-state branch — each currently:
```tsx
style={{ width: 442, flexShrink: 0, minWidth: 0 }}
```
Change BOTH to:
```tsx
style={{
  width: 442,
  flexShrink: 0,
  minWidth: 0,
  alignSelf: 'flex-start',
  position: 'sticky',
  top: 'calc(var(--app-shell-header-offset, 3.5rem) + var(--mantine-spacing-sm))',
  maxHeight: 'calc(100vh - var(--app-shell-header-offset, 3.5rem) - var(--mantine-spacing-md))',
  overflowY: 'auto',
}}
```

- [ ] **Step 2: Typecheck + run triage player tests**

From `frontend/`:
```
pnpm typecheck && pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
```
Expected: no type errors; tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx
git commit -m "feat(triage): make the bucket player panel sticky on desktop"
```

---

### Task 3: Full verification

- [ ] **Step 1: Whole suite + typecheck + lint**

From `frontend/`: `pnpm test && pnpm typecheck && pnpm lint`
Expected: all tests pass (use `pnpm test` — it sets `NODE_OPTIONS=--no-experimental-webstorage`; running `vitest` directly without that flag causes unrelated localStorage-env failures); typecheck clean; lint 0 errors (only the 2 pre-existing warnings in `useCurateSession.ts` + `theme.ts`).

- [ ] **Step 2: Manual smoke test (desktop)**

Start `pnpm dev` from `frontend/`. On a category and a triage staging bucket with a long track list (100+):
- Scroll the list → the player panel stays pinned below the header (does not scroll away).
- A short list (no page scroll) → player renders normally at the top.
- If the player content is taller than the viewport → it scrolls internally; nothing is clipped.
- Mobile width → no regression (player is on its own route; sticky is inert).

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** category `.root` sticky (Task 1); triage both roots sticky (Task 2); header-offset `top`, `max-height`+`overflow-y` for tall players, `align-self: flex-start`, both players, desktop-only (inert on mobile) — all covered. No backend/test additions per the spec.
- **Consistency:** identical `top` / `max-height` calc expressions in both files (`--app-shell-header-offset, 3.5rem` + spacing). Category keeps its `width: 442` / `border-right`; triage keeps `width: 442` / `minWidth: 0`.
- **Placeholder scan:** none.

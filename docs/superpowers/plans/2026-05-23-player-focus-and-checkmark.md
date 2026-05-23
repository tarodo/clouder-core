# Remove Focus Ring + Tag Checkmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide the redundant checkmark on selected tags in the category player, and remove the (near-black) focus ring app-wide.

**Architecture:** Two independent frontend changes. (1) In `PlayerPanelTagCloud`, hide the Mantine `Chip` check icon via `styles.iconWrapper: { display: 'none' }` — the soft tint already conveys selection. (2) In the Mantine theme, set `focusRing: 'never'`, which removes the focus ring from every Mantine component (play `ActionIcon`/`Button`, tag `Chip`, category row, text inputs). All interactive elements in the players are Mantine components, so no global CSS reset is needed.

**Tech Stack:** React 19 + Mantine 9 + TypeScript, Vitest + @testing-library/react. Run all commands from `frontend/`.

---

## File Structure

**Modify:**
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — Chip `iconWrapper` → `display: 'none'`.
- `frontend/src/theme.ts` — add `focusRing: "never"` to `createTheme({...})`.

**Tests (modify/create):**
- `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx` — assert the assigned chip's checkmark wrapper is hidden.
- `frontend/src/__tests__/theme.test.ts` — assert `clouderTheme.focusRing === 'never'` (create if no theme test exists; otherwise add the assertion to the existing theme test).

---

## Task 1: Hide the tag checkmark (category player)

**Files:**
- Modify: `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`
- Test: `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`

- [ ] **Step 1: Write the failing test**

Add this test inside the `describe('PlayerPanelTagCloud', …)` block in `PlayerPanelTagCloud.test.tsx`:

```tsx
  it('hides the checkmark on assigned chips (color conveys selection)', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidChip = screen.getByText('acid').closest('.mantine-Chip-root')! as HTMLElement;
    const iconWrapper = acidChip.querySelector('.mantine-Chip-iconWrapper') as HTMLElement | null;
    expect(iconWrapper).not.toBeNull();
    expect(iconWrapper!.style.display).toBe('none');
  });
```

(Note: `iconWrapper` is a confirmed Chip styles slot — `ChipStylesNames = 'root' | 'input' | 'iconWrapper' | 'checkIcon' | 'label'`. The mock in this test file already gives `tg-a` the name `acid` with a 6-digit color.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- PlayerPanelTagCloud`
Expected: FAIL — the iconWrapper currently has `color` styling, not `display: none` (its `style.display` is empty, not `'none'`).

- [ ] **Step 3: Hide the icon wrapper**

In `PlayerPanelTagCloud.tsx`, in the Chip's `styles` prop, replace the `iconWrapper` line:

```tsx
                iconWrapper: { color: selected ? sc.fg : 'var(--mantine-color-dimmed)' },
```

with:

```tsx
                iconWrapper: { display: 'none' },
```

(Leave the `label` styling — the soft tint for assigned, neutral for unassigned — exactly as is. Only the `iconWrapper` line changes.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- PlayerPanelTagCloud`
Expected: PASS — all existing tests (renders tags, checked state, onAdd/onRemove, add button, soft-tint) plus the new checkmark-hidden test.

- [ ] **Step 5: Commit**

```bash
git add src/features/categories/components/PlayerPanelTagCloud.tsx src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx
git commit -m "fix(categories): drop redundant checkmark on selected tag chips"
```

---

## Task 2: Remove the focus ring app-wide

**Files:**
- Modify: `frontend/src/theme.ts` (the `createTheme({...})` object, near `primaryShade` at line ~69)
- Test: `frontend/src/__tests__/theme.test.ts` (create, or add the assertion to an existing theme test)

- [ ] **Step 1: Write the failing test**

First check whether a theme test already exists: `ls src/__tests__/theme.test.ts 2>/dev/null; grep -rl "clouderTheme" src/**/__tests__ 2>/dev/null`.

If none exists, create `frontend/src/__tests__/theme.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { clouderTheme } from '../theme';

describe('clouderTheme', () => {
  it('disables the focus ring app-wide', () => {
    expect(clouderTheme.focusRing).toBe('never');
  });
});
```

If a theme test already exists, add the single `it('disables the focus ring app-wide', …)` assertion to it instead (same import of `clouderTheme`).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- theme`
Expected: FAIL — `clouderTheme.focusRing` is currently `undefined` (defaults to `'auto'`), not `'never'`.

- [ ] **Step 3: Set `focusRing: "never"`**

In `frontend/src/theme.ts`, inside `createTheme({...})`, add the `focusRing` line immediately after the `primaryShade` line (line 69):

```ts
  primaryColor: "neutral",
  primaryShade: { light: 9, dark: 0 }, // dark inverts the ramp
  focusRing: "never", // mouse + hotkey app — the ring is noise, not navigation
  white: "#ffffff",
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- theme`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/theme.ts src/__tests__/theme.test.ts
git commit -m "fix(frontend): disable focus ring app-wide (focusRing never)"
```

---

## Task 3: Full frontend verification

**Files:** none (verification only)

- [ ] **Step 1: Typecheck + lint + full test run**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
Expected: all PASS, no type or lint errors (pre-existing lint WARNINGS are acceptable). Paste the summary lines.

- [ ] **Step 2: Commit (only if a fix was needed)**

If Step 1 surfaced a fix, commit it:

```bash
git add -A
git commit -m "chore(frontend): fix lint/type issues for focus-ring/checkmark change"
```

If nothing needed fixing, skip this step.

---

## Done criteria

- The category player's selected tags show no checkmark; selection stays obvious via the soft tint (`PlayerPanelTagCloud` test passes).
- `clouderTheme.focusRing === 'never'`; the focus ring is gone from all Mantine components (play, tags, category rows, text inputs) on mouse and keyboard.
- `pnpm typecheck && pnpm lint && pnpm test` all green.

## Post-merge verification (user, visual)

After deploy, click play / a tag / a category on the category, triage, and curate players and confirm no black outline remains. All three controls are Mantine components, so `focusRing: 'never'` covers them; if any *non-Mantine native* element still shows a UA outline, follow up with a scoped `:focus { outline: none }` in `tokens.css` (not expected — noted only as a safety net).

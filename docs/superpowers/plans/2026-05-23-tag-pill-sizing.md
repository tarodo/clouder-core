# Tag Pill Sizing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the category-player tag chip from resizing when selected, and make 1- and 2-character pills in the track-table tags column share one width (longer tags grow).

**Architecture:** Two independent frontend changes. (1) In `PlayerPanelTagCloud`, pin the Mantine `Chip` label's horizontal padding to the unchecked value in both states so the checked-state padding rule can't shrink it. (2) In the shared `TagPill`, render in the mono font with `min-width: calc(2ch + 16px)` and center the text, so any ≤2-char tag is identical width and 3+ grows. Load-bearing assertions run in the browser harness (`*.browser.test.tsx`), with cheap jsdom structural guards in the default suite.

**Tech Stack:** React 19 + Mantine 9 + TypeScript. Default tests: Vitest + jsdom + @testing-library/react. Browser tests: `@vitest/browser` + Playwright/chromium. Run all commands from `frontend/`.

---

## File Structure

**Modify (source):**
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — add `paddingLeft`/`paddingRight: 'var(--chip-padding)'` to both `styles.label` branches.
- `frontend/src/features/tags/components/TagPill.tsx` — add `fontFamily`, `minWidth`, `justifyContent` to the pill `Box` `style`.

**Modify (jsdom guards):**
- `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx` — assert both labels carry the pinned padding.
- `frontend/src/features/tags/components/__tests__/TagPill.test.tsx` — assert the pill carries mono font + min-width + centering.

**Create (browser regression tests):**
- `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.browser.test.tsx` — assert the 'acid' chip label width is equal unchecked vs checked.
- `frontend/src/features/tags/components/__tests__/TagPill.browser.test.tsx` — assert width('A') == width('AB') and width(5-char) > width('AB'), font is monospace.

**Context — why these exact values (read before editing):**
- Mantine Chip label CSS (`@mantine/core/styles.css`): base `.mantine-Chip-label { padding-inline: var(--chip-padding); }`; checked `.mantine-Chip-label:where([data-checked]) { padding-inline: var(--chip-checked-padding); }`. `--chip-padding` (sm) = `1.25rem` (20px), `--chip-checked-padding` (sm) = `0.625rem` (10px). The checked rule uses `:where()` → **0 specificity**, so an inline style on the label wins without `!important`. The 10px normally holds the (now hidden) check icon; with the icon hidden the checked chip is just ~20px narrower. Pinning the inline padding to `var(--chip-padding)` in both states removes the jump while keeping the current unchecked look byte-identical. `--chip-padding` cascades down to the label from the chip root, so `var(--chip-padding)` resolves correctly there.
- `TagPill` is `display: inline-flex`, `px={8}` (8px each side), no `min-width`. The design system ships `--font-mono: "Geist Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace` in `tokens.css`. In a monospace font every glyph is one `ch` wide, so `min-width: calc(2ch + 16px)` (2ch content + the 8px×2 padding; global `box-sizing: border-box` makes min-width include padding) makes every ≤2-char tag the same width. Any monospace fallback preserves this, so the browser test does not depend on the web font loading.

---

## Task 1: Pin the chip label padding (category player)

**Files:**
- Modify: `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`
- Test (jsdom guard): `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
- Test (browser): `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.browser.test.tsx` (create)

- [ ] **Step 1: Write the failing jsdom guard**

Add this test inside the `describe('PlayerPanelTagCloud', …)` block in `PlayerPanelTagCloud.test.tsx`:

```tsx
  it('pins label padding so selecting a tag does not resize it', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidLabel = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    const bangerLabel = screen
      .getByText('banger')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    // selected and unselected chips carry the SAME pinned inline padding
    expect(acidLabel.style.paddingLeft).toBe('var(--chip-padding)');
    expect(acidLabel.style.paddingRight).toBe('var(--chip-padding)');
    expect(bangerLabel.style.paddingLeft).toBe('var(--chip-padding)');
    expect(bangerLabel.style.paddingRight).toBe('var(--chip-padding)');
  });
```

- [ ] **Step 2: Run the jsdom guard to verify it fails**

Run: `pnpm test -- PlayerPanelTagCloud`
Expected: FAIL — `paddingLeft` is currently `''` (no inline padding is set on the label).

- [ ] **Step 3: Write the failing browser test**

Create `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.browser.test.tsx`:

```tsx
/**
 * Browser-mode regression: selecting a tag must NOT change the chip's width.
 *
 * Mantine's Chip label switches `padding-inline` from --chip-padding (20px)
 * to --chip-checked-padding (10px) when checked. With the check icon hidden,
 * that made a selected chip ~20px narrower. PlayerPanelTagCloud now pins the
 * inline padding in both states. This test renders the SAME tag unchecked then
 * checked and asserts its label width is unchanged.
 */
import type { ReactNode } from 'react';
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';
import '../../../../i18n';

vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [{ id: 'tg-a', name: 'acid', color: '#ff0000' }],
    isLoading: false,
  }),
  TrackTagsPopover: ({ target }: { target: ReactNode }) => <div>{target}</div>,
}));

import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

const base = { categoryId: 'c1', trackId: 't-1', onAdd: vi.fn(), onRemove: vi.fn() };

function acidLabelWidth(container: HTMLElement): number {
  const label = container.querySelector('.mantine-Chip-label') as HTMLElement;
  return label.getBoundingClientRect().width;
}

describe('PlayerPanelTagCloud — chip width stable on select (browser)', () => {
  test('the same tag has equal label width unchecked and checked', () => {
    const { container, rerender } = render(
      <MantineProvider defaultColorScheme="light">
        <PlayerPanelTagCloud {...base} assignedTagIds={[]} />
      </MantineProvider>,
    );
    const unchecked = acidLabelWidth(container);

    rerender(
      <MantineProvider defaultColorScheme="light">
        <PlayerPanelTagCloud {...base} assignedTagIds={['tg-a']} />
      </MantineProvider>,
    );
    const checked = acidLabelWidth(container);

    expect(unchecked).toBeGreaterThan(0);
    expect(checked).toBeCloseTo(unchecked, 1);
  });
});
```

- [ ] **Step 4: Run the browser test to verify it fails**

Run: `pnpm test:browser -- PlayerPanelTagCloud`
Expected: FAIL — `checked` width is ~20px less than `unchecked` (the bug), so `toBeCloseTo(unchecked, 1)` fails.

(If Playwright's chromium is not installed, run `pnpm exec playwright install chromium` once, then re-run.)

- [ ] **Step 5: Pin the padding**

In `PlayerPanelTagCloud.tsx`, in the Chip's `styles.label`, add the pinned padding to **both** branches. Replace:

```tsx
                label: selected
                  ? {
                      backgroundColor: sc.bg,
                      color: sc.fg,
                      border: `1px solid ${sc.border}`,
                    }
                  : {
                      backgroundColor: 'transparent',
                      color: 'var(--mantine-color-dimmed)',
                      border: '1px solid var(--mantine-color-default-border)',
                    },
```

with:

```tsx
                label: selected
                  ? {
                      backgroundColor: sc.bg,
                      color: sc.fg,
                      border: `1px solid ${sc.border}`,
                      // pin padding so the checked-state rule can't resize the chip
                      paddingLeft: 'var(--chip-padding)',
                      paddingRight: 'var(--chip-padding)',
                    }
                  : {
                      backgroundColor: 'transparent',
                      color: 'var(--mantine-color-dimmed)',
                      border: '1px solid var(--mantine-color-default-border)',
                      paddingLeft: 'var(--chip-padding)',
                      paddingRight: 'var(--chip-padding)',
                    },
```

(Leave `iconWrapper: { display: 'none' }` unchanged.)

- [ ] **Step 6: Run both tests to verify they pass**

Run: `pnpm test -- PlayerPanelTagCloud`
Expected: PASS — all existing tests plus the new padding guard.

Run: `pnpm test:browser -- PlayerPanelTagCloud`
Expected: PASS — unchecked and checked label widths are now equal.

- [ ] **Step 7: Commit**

```bash
git add src/features/categories/components/PlayerPanelTagCloud.tsx src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx src/features/categories/components/__tests__/PlayerPanelTagCloud.browser.test.tsx
git commit -m "fix(categories): keep tag chip width constant when selected"
```

---

## Task 2: Uniform short pills (global TagPill)

**Files:**
- Modify: `frontend/src/features/tags/components/TagPill.tsx`
- Test (jsdom guard): `frontend/src/features/tags/components/__tests__/TagPill.test.tsx`
- Test (browser): `frontend/src/features/tags/components/__tests__/TagPill.browser.test.tsx` (create)

- [ ] **Step 1: Write the failing jsdom guard**

Add this test inside the `describe('TagPill', …)` block in `TagPill.test.tsx`:

```tsx
  it('renders mono, centered, with a 2-char min-width for uniform short pills', () => {
    render(
      <W>
        <TagPill name="A" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.fontFamily).toBe('var(--font-mono)');
    expect(el.style.minWidth).toBe('calc(2ch + 16px)');
    expect(el.style.justifyContent).toBe('center');
  });
```

- [ ] **Step 2: Run the jsdom guard to verify it fails**

Run: `pnpm test -- TagPill`
Expected: FAIL — `fontFamily`, `minWidth`, `justifyContent` are all currently `''`.

- [ ] **Step 3: Write the failing browser test**

Create `frontend/src/features/tags/components/__tests__/TagPill.browser.test.tsx`:

```tsx
/**
 * Browser-mode regression: 1- and 2-char tag pills share one width; longer grow.
 *
 * TagPill renders in the mono font with min-width: calc(2ch + 16px). In any
 * monospace font 1ch == one glyph, so a 1-char and a 2-char tag both clamp to
 * the 2ch min-width (equal), while a 5-char tag exceeds it (wider). This holds
 * even if the Geist Mono web font fails to load (the fallback stack is mono).
 */
import { MantineProvider } from '@mantine/core';
import { render } from '@testing-library/react';
import { describe, expect, test } from 'vitest';
import { TagPill } from '../TagPill';

function widths() {
  const { container } = render(
    <MantineProvider defaultColorScheme="light">
      <TagPill name="A" color="#3b82f6" data-testid="p1" />
      <TagPill name="AB" color="#3b82f6" data-testid="p2" />
      <TagPill name="ABCDE" color="#3b82f6" data-testid="p5" />
    </MantineProvider>,
  );
  const w = (id: string) =>
    (container.querySelector(`[data-testid="${id}"]`) as HTMLElement).getBoundingClientRect()
      .width;
  return { container, w1: w('p1'), w2: w('p2'), w5: w('p5') };
}

describe('TagPill — uniform short pills (browser)', () => {
  test('1-char and 2-char pills are equal width; 5-char is wider', () => {
    const { container, w1, w2, w5 } = widths();
    expect(w1).toBeGreaterThan(0);
    expect(w1).toBeCloseTo(w2, 1); // 1-char clamps to the same 2ch min-width
    expect(w5).toBeGreaterThan(w2 + 1); // longer tag grows

    const pill = container.querySelector('[data-testid="p1"]') as HTMLElement;
    expect(window.getComputedStyle(pill).fontFamily.toLowerCase()).toContain('mono');
  });
});
```

- [ ] **Step 4: Run the browser test to verify it fails**

Run: `pnpm test:browser -- TagPill`
Expected: FAIL — without min-width, `w1` (1 char) is narrower than `w2` (2 chars), so `toBeCloseTo(w2, 1)` fails; the font is also not monospace yet.

- [ ] **Step 5: Add the mono / min-width / centering style**

In `TagPill.tsx`, in the `Box`'s `style` object, add three properties. Change:

```tsx
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        borderRadius: 999,
        fontSize: 12,
        lineHeight: 1.4,
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
      }}
```

to:

```tsx
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 4,
        borderRadius: 999,
        fontFamily: 'var(--font-mono)',
        fontSize: 12,
        lineHeight: 1.4,
        minWidth: 'calc(2ch + 16px)',
        backgroundColor: bg,
        color: fg,
        border: `1px solid ${border}`,
      }}
```

(Leave `px={8}`, `py={2}`, the `name` span and optional `onRemove` `×` unchanged.)

- [ ] **Step 6: Run both tests to verify they pass**

Run: `pnpm test -- TagPill`
Expected: PASS — existing soft-tint/neutral tests plus the new style guard.

Run: `pnpm test:browser -- TagPill`
Expected: PASS — `w1 ≈ w2`, `w5 > w2`, font is monospace.

- [ ] **Step 7: Commit**

```bash
git add src/features/tags/components/TagPill.tsx src/features/tags/components/__tests__/TagPill.test.tsx src/features/tags/components/__tests__/TagPill.browser.test.tsx
git commit -m "fix(tags): uniform mono pill width for short tags"
```

---

## Task 3: Full frontend verification

**Files:** none (verification only)

- [ ] **Step 1: Typecheck + lint + full jsdom suite**

Run: `pnpm typecheck && pnpm lint && pnpm test`
Expected: all PASS, no type or lint errors (pre-existing lint WARNINGS are acceptable). Paste the summary lines.

- [ ] **Step 2: Full browser suite**

Run: `pnpm test:browser`
Expected: all PASS — the two new browser tests plus the existing focus-ring/smoke browser tests.

- [ ] **Step 3: Commit (only if a fix was needed)**

If Step 1 or 2 surfaced a fix, commit it:

```bash
git add -A
git commit -m "chore(frontend): fix lint/type issues for tag pill sizing"
```

If nothing needed fixing, skip this step.

---

## Done criteria

- Selecting/deselecting a tag in the category player changes only its color/fill — the chip width does not change (`PlayerPanelTagCloud` jsdom guard + browser width-equality test pass).
- In the track table tags column, every 1-char and 2-char tag is the same width; 3+ char tags are wider (`TagPill` jsdom guard + browser width tests pass); the treatment applies wherever `TagPill` is used.
- `pnpm typecheck && pnpm lint && pnpm test` all green; `pnpm test:browser` all green.

## Post-merge verification (user, visual)

After deploy: (1) in the category player, click a tag — only the color changes, no width jump; (2) in the track table, confirm 1- and 2-char tags line up at one width and a long tag is wider.

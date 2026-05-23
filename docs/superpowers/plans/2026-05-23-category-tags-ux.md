# Category Tags UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two issues with label tags on the category-detail page: clicking a tag no longer kills the keyboard shortcuts, and tags render as soft tinted labels instead of a loud full fill.

**Architecture:** Frontend-only. (1) Refine the `isEditable` guard in the category hotkey hook so a focused tag Chip's checkbox `<input>` stops suppressing shortcuts. (2) Add a `softTagColors(hex)` helper that derives `{bg, fg, border}` from the stored tag colour (light tint bg, darkened text, subtle border), and apply it to the track-row `TagPill` and the player-panel Chip. No backend, DB, API, or palette changes.

**Tech Stack:** React 19 + Mantine 9 + TypeScript, Vitest + @testing-library/react. Run all commands from `frontend/`.

---

## File Structure

**Modify:**
- `frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts` — `isEditable` guard (lines 22-28).
- `frontend/src/features/tags/lib/tagPalette.ts` — add `softTagColors` + `SoftTagColors` type (keep existing exports).
- `frontend/src/features/tags/components/TagPill.tsx` — render via `softTagColors`.
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — Chip soft-tint via `styles`.

**Tests (modify):**
- `frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx`
- `frontend/src/features/tags/lib/__tests__/tagPalette.test.ts`
- `frontend/src/features/tags/components/__tests__/TagPill.test.tsx`
- `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`

**Constants (do not rename):** helper `softTagColors`, type `SoftTagColors`, fields `bg`/`fg`/`border`.

---

## Task 1: Refine the hotkey `isEditable` guard

**Files:**
- Modify: `frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts:22-28`
- Test: `frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx`

- [ ] **Step 1: Write the failing test**

Add this test inside the `describe('useCategoryPlayerHotkeys', …)` block in `useCategoryPlayerHotkeys.test.tsx` (after the existing `'ignores keydown when target is an input'` test):

```tsx
  it('fires shortcuts when the target is a checkbox input (e.g. a tag chip)', () => {
    renderHook(() => useCategoryPlayerHotkeys({ ...callbacks, active: true, playlistCount: 10 }));
    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    document.body.appendChild(checkbox);
    checkbox.dispatchEvent(new KeyboardEvent('keydown', { code: 'KeyJ', bubbles: true }));
    expect(callbacks.onPrev).toHaveBeenCalledOnce();
    document.body.removeChild(checkbox);
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- useCategoryPlayerHotkeys`
Expected: FAIL — `onPrev` was not called (the current guard treats the checkbox `<input>` as editable and suppresses the key). The existing `'ignores keydown when target is an input'` test still passes.

- [ ] **Step 3: Replace `isEditable`**

In `useCategoryPlayerHotkeys.ts`, replace the `isEditable` function (lines 22-28) with:

```ts
// <input> types that are widgets, not text entry — they should NOT suppress
// shortcuts (e.g. a Mantine Chip is a focusable <input type="checkbox">).
const NON_EDITABLE_INPUT_TYPES = new Set([
  'checkbox',
  'radio',
  'button',
  'submit',
  'reset',
  'file',
  'range',
  'color',
  'image',
]);

function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type.toLowerCase();
    return !NON_EDITABLE_INPUT_TYPES.has(type);
  }
  if (target.isContentEditable) return true;
  return false;
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- useCategoryPlayerHotkeys`
Expected: PASS — all tests, including the new checkbox test and the existing text-input test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts frontend/src/features/categories/hooks/__tests__/useCategoryPlayerHotkeys.test.tsx
git commit -m "fix(categories): hotkeys keep working after clicking a tag chip"
```

---

## Task 2: Add the `softTagColors` helper

**Files:**
- Modify: `frontend/src/features/tags/lib/tagPalette.ts` (append; keep `TAG_PALETTE`, `isPaletteColor`, `pickPillTextColor`)
- Test: `frontend/src/features/tags/lib/__tests__/tagPalette.test.ts`

- [ ] **Step 1: Write the failing test**

Add to `tagPalette.test.ts` — extend the import on line 2 to include `softTagColors`, then add a new `describe` block:

```ts
import { TAG_PALETTE, pickPillTextColor, isPaletteColor, softTagColors } from '../tagPalette';

describe('softTagColors', () => {
  it('produces a soft tint from a hex colour', () => {
    const sc = softTagColors('#ef4444');
    expect(sc.bg).toBe('rgba(239, 68, 68, 0.13)');
    expect(sc.border).toBe('rgba(239, 68, 68, 0.3)');
    // fg = each channel * 0.55, rounded: 131,37,37
    expect(sc.fg).toBe('#832525');
  });

  it('returns a neutral grey tint for null/invalid colour', () => {
    const neutral = {
      bg: 'rgba(100, 116, 139, 0.12)',
      fg: '#475569',
      border: 'rgba(100, 116, 139, 0.3)',
    };
    expect(softTagColors(null)).toEqual(neutral);
    expect(softTagColors('not-a-hex')).toEqual(neutral);
  });

  it('keeps very dark colours as dark text on a light tint', () => {
    const sc = softTagColors('#0f172a');
    expect(sc.bg).toBe('rgba(15, 23, 42, 0.13)');
    expect(sc.fg).toBe('#080d17'); // 15*.55=8, 23*.55=13, 42*.55=23
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- tagPalette`
Expected: FAIL — `softTagColors is not a function` / not exported.

- [ ] **Step 3: Implement `softTagColors`**

Append to `tagPalette.ts`:

```ts
export interface SoftTagColors {
  /** Low-alpha tint for the pill background. */
  bg: string;
  /** Darkened, readable foreground text colour. */
  fg: string;
  /** Subtle hairline border colour. */
  border: string;
}

const NEUTRAL_SOFT: SoftTagColors = {
  bg: 'rgba(100, 116, 139, 0.12)',
  fg: '#475569',
  border: 'rgba(100, 116, 139, 0.3)',
};

/**
 * Derives a soft "label" treatment from a stored tag colour: a light tint
 * background, a darkened readable text colour, and a subtle border. Computed
 * client-side so existing tags soften without any data migration.
 */
export function softTagColors(hex: string | null | undefined): SoftTagColors {
  const m =
    typeof hex === 'string'
      ? /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex)
      : null;
  if (!m) return NEUTRAL_SOFT;
  const r = parseInt(m[1]!, 16);
  const g = parseInt(m[2]!, 16);
  const b = parseInt(m[3]!, 16);
  const darken = (c: number) =>
    Math.round(c * 0.55)
      .toString(16)
      .padStart(2, '0');
  return {
    bg: `rgba(${r}, ${g}, ${b}, 0.13)`,
    fg: `#${darken(r)}${darken(g)}${darken(b)}`,
    border: `rgba(${r}, ${g}, ${b}, 0.3)`,
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- tagPalette`
Expected: PASS (all `tagPalette` tests, including the existing `pickPillTextColor`/`isPaletteColor` ones).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/lib/tagPalette.ts frontend/src/features/tags/lib/__tests__/tagPalette.test.ts
git commit -m "feat(tags): add softTagColors helper for soft-tint tag labels"
```

---

## Task 3: Apply soft tint to `TagPill` (track-row tags)

**Files:**
- Modify: `frontend/src/features/tags/components/TagPill.tsx`
- Test: `frontend/src/features/tags/components/__tests__/TagPill.test.tsx`

- [ ] **Step 1: Update the failing tests**

In `TagPill.test.tsx`, replace the two style assertions (`'uses the colour as background when provided'` and `'falls back to a neutral outline when colour is null'`) with:

```tsx
  it('renders a soft tint background derived from the colour', () => {
    render(
      <W>
        <TagPill name="Vocal" color="#ff8800" data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgba(255, 136, 0, 0.13)');
    // fg darkened: 255*.55=140, 136*.55=75, 0 → #8c4b00
    expect(el.style.color).toBe('rgb(140, 75, 0)');
  });

  it('falls back to a neutral grey tint when colour is null', () => {
    render(
      <W>
        <TagPill name="Vocal" color={null} data-testid="pill" />
      </W>,
    );
    const el = screen.getByTestId('pill');
    expect(el.style.backgroundColor).toBe('rgba(100, 116, 139, 0.12)');
    expect(el.style.color).toBe('rgb(71, 85, 105)'); // #475569
  });
```

(Keep the first test, `'renders the tag name'`, unchanged.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- TagPill`
Expected: FAIL — backgroundColor is still the full fill `rgb(255, 136, 0)`, not the tint.

- [ ] **Step 3: Implement the soft tint in `TagPill`**

Replace the body of `TagPill.tsx` (the import line 2 and the `baseStyle`/`Box` usage) with:

```tsx
import { Box, type BoxProps } from '@mantine/core';
import { softTagColors } from '../lib/tagPalette';

export interface TagPillProps extends BoxProps {
  name: string;
  color: string | null;
  /** Render an additional `×` to the right; emits `onRemove` when clicked. */
  onRemove?: () => void;
}

export function TagPill({ name, color, onRemove, ...rest }: TagPillProps) {
  const { bg, fg, border } = softTagColors(color);
  return (
    <Box
      component="span"
      px={8}
      py={2}
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
      {...rest}
    >
      <span>{name}</span>
      {onRemove && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onRemove();
          }}
          aria-label={`Remove ${name}`}
          style={{
            all: 'unset',
            cursor: 'pointer',
            opacity: 0.7,
            fontSize: 12,
            lineHeight: 1,
          }}
        >
          ×
        </button>
      )}
    </Box>
  );
}
```

(`pickPillTextColor` is no longer imported here. Leave it in `tagPalette.ts` — it stays exported and is still covered by its own test.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- TagPill`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/tags/components/TagPill.tsx frontend/src/features/tags/components/__tests__/TagPill.test.tsx
git commit -m "feat(tags): soft-tint TagPill instead of full fill"
```

---

## Task 4: Soft tint + assigned/unassigned states on the player-panel Chip

**Files:**
- Modify: `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`
- Test: `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`

- [ ] **Step 1: Update the test mock + add the failing test**

In `PlayerPanelTagCloud.test.tsx`, change the mocked tag colours (lines 14-15) from 3-digit to 6-digit hex so `softTagColors` produces a real tint:

```tsx
    data: [
      { id: 'tg-a', name: 'acid', color: '#ff0000' },
      { id: 'tg-b', name: 'banger', color: '#00ff00' },
    ],
```

Then add this test inside the `describe('PlayerPanelTagCloud', …)` block:

```tsx
  it('assigned chip shows a soft tint, unassigned chip is transparent', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidLabel = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    const bangerLabel = screen
      .getByText('banger')
      .closest('.mantine-Chip-root')!
      .querySelector('.mantine-Chip-label')! as HTMLElement;
    expect(acidLabel.style.backgroundColor).toBe('rgba(255, 0, 0, 0.13)');
    expect(bangerLabel.style.backgroundColor).toBe('transparent');
  });
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && pnpm test -- PlayerPanelTagCloud`
Expected: FAIL — the assigned label has no inline tint background yet (the current Chip uses `variant="filled"`/`color`, not the soft `styles`).

- [ ] **Step 3: Implement the soft-tint Chip**

In `PlayerPanelTagCloud.tsx`:

Add the import (deep path — NOT the `../../tags` barrel, which the test mocks):

```tsx
import { softTagColors } from '../../tags/lib/tagPalette';
```

Replace the `tags.map(...)` Chip block (lines 41-55) with:

```tsx
        {tags.map((tg) => {
          const selected = assigned.has(tg.id);
          const sc = softTagColors(tg.color);
          return (
            <Chip
              key={tg.id}
              checked={selected}
              size="sm"
              variant="outline"
              onChange={() => (selected ? onRemove(tg.id) : onAdd(tg.id))}
              styles={{
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
                iconWrapper: { color: selected ? sc.fg : 'var(--mantine-color-dimmed)' },
              }}
            >
              {tg.name}
            </Chip>
          );
        })}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && pnpm test -- PlayerPanelTagCloud`
Expected: PASS — all existing behaviour tests (renders tags, checked state, onAdd/onRemove, add button) plus the new tint test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/PlayerPanelTagCloud.tsx frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx
git commit -m "feat(categories): soft-tint player-panel tag chips, clearer selected state"
```

---

## Task 5: Full frontend verification

**Files:** none (verification only)

- [ ] **Step 1: Typecheck + lint + full test run**

Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm test`
Expected: all PASS, no type or lint errors. (Pre-existing lint WARNINGS are acceptable; new ERRORS are not.) Paste the summary lines.

- [ ] **Step 2: Commit (only if a fix was needed)**

If Step 1 surfaced a fix, commit it:

```bash
git add -A
git commit -m "chore(categories): fix lint/type issues for tag UX"
```

If nothing needed fixing, skip this step.

---

## Done criteria

- Clicking a label tag on `/categories/:styleId/:id`, then pressing a/s/d/f/g/j/k/u/0–9, triggers the shortcut without first clicking empty space (`useCategoryPlayerHotkeys` checkbox test passes).
- `softTagColors` derives `{bg, fg, border}` from a stored colour (and a neutral grey for null), covered by unit tests.
- Track-row `TagPill` and player-panel chips render the soft tint; assigned vs unassigned chips stay visually distinct.
- `pnpm typecheck && pnpm lint && pnpm test` all green; no backend/DB/palette changes.

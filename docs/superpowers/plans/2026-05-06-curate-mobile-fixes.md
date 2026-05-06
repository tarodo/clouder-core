# Curate Mobile Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three small Curate UX fixes — mobile seek chips (0/20/40/60/80%), compact destination buttons on mobile, and remap DISCARD hotkey from `0` to `Z`.

**Architecture:** All changes confined to `frontend/`. Task 1 extends `PlayerCard` with an opt-in mobile seek-chip row inside the Paper; Task 2 adds a `compact` prop to `DestinationButton` and threads `isMobile` from `DestinationGrid`; Task 3 swaps `Digit0`→`KeyZ` in the hotkey table and updates the rendered Kbd hint + i18n + tests.

**Tech Stack:** React 19, Mantine 9, vitest, react-i18next, CSS Modules.

---

## File Structure

**Modified files:**

- `frontend/src/features/playback/PlayerCard.tsx` — add `mobileSeekChips?: boolean` prop, render chip row below `Slider`.
- `frontend/src/features/playback/PlayerCard.module.css` — styles for new chip row.
- `frontend/src/features/playback/__tests__/PlayerCard.test.tsx` — add tests for seek chips.
- `frontend/src/features/curate/components/CurateSession.tsx` — pass `mobileSeekChips={isMobile}` to `PlayerCard`.
- `frontend/src/features/curate/components/DestinationButton.tsx` — add `compact?: boolean` prop, vary `px`/`py`/font.
- `frontend/src/features/curate/components/DestinationButton.module.css` — `.compact` modifier with reduced height + font.
- `frontend/src/features/curate/components/DestinationGrid.tsx` — thread `compact={isMobile}` into `renderBtn`.
- `frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx` — add compact test.
- `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx` — flip `0` Kbd assertion to `Z`.
- `frontend/src/features/curate/hooks/useCurateHotkeys.ts` — `case 'Digit0'` → `case 'KeyZ'`.
- `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx` — flip `Digit0` test to `KeyZ`.
- `frontend/src/features/curate/components/HotkeyOverlay.tsx` — change `keys: ['0']` row to `keys: ['Z']`, label key updated.
- `frontend/src/i18n/en.json` — rename `key_zero_label` → `key_z_label`, add `playback.seek_chip_aria_pct` (used by chips).

No new files.

---

## Task 1: Mobile seek chips under progress bar

PlayerCard already owns the `Slider`. Add an opt-in chip row of `[0, 20, 40, 60, 80]` rendered inside the same `Paper`, directly below the slider, only when `mobileSeekChips` prop is true. CurateSession sets the prop based on its existing `isMobile` media query (no new media-query wiring inside PlayerCard — keep PlayerCard layout-agnostic).

Each chip: a Mantine `Button` (variant=`light`, size=`compact-xs`) labelled `0%`, `20%`, etc. Click computes `pctToMs(pct, durationMs)` and calls `onSeekMs(ms)`. Disabled when scrub is disabled (same condition that disables the Slider).

**Files:**

- Modify: `frontend/src/features/playback/PlayerCard.tsx`
- Modify: `frontend/src/features/playback/PlayerCard.module.css`
- Modify: `frontend/src/features/curate/components/CurateSession.tsx`
- Modify: `frontend/src/features/playback/__tests__/PlayerCard.test.tsx`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add i18n key for chip aria-label**

Open `frontend/src/i18n/en.json`. Find the `"playback"` block (line ~406) and inside `"controls"` (line ~415), add a new line after `"scrub_aria"`:

```json
      "scrub_aria": "Scrub bar",
      "seek_chip_aria_pct": "Seek to {{pct}}%",
      "close_aria": "Close player"
```

- [ ] **Step 2: Write the failing test for seek chips**

Find `frontend/src/features/playback/__tests__/PlayerCard.test.tsx`. Append (inside the existing `describe('PlayerCard')` block, before its closing brace) this test block:

```tsx
  it('renders 5 seek chips when mobileSeekChips is true and clicking 40% chip calls onSeekMs(0.4 * duration)', () => {
    const onSeekMs = vi.fn();
    const track: PlaybackTrack = {
      id: 't1',
      title: 'T',
      artists: 'A',
      duration_ms: 200_000,
      spotify_id: 'sp1',
      cover_url: null,
    };
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="playing"
          track={track}
          positionMs={0}
          mobileSeekChips
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={onSeekMs}
        />,
      ),
    );
    const chip0 = screen.getByRole('button', { name: /Seek to 0%/i });
    const chip20 = screen.getByRole('button', { name: /Seek to 20%/i });
    const chip40 = screen.getByRole('button', { name: /Seek to 40%/i });
    const chip60 = screen.getByRole('button', { name: /Seek to 60%/i });
    const chip80 = screen.getByRole('button', { name: /Seek to 80%/i });
    expect(chip0).toBeInTheDocument();
    expect(chip20).toBeInTheDocument();
    expect(chip60).toBeInTheDocument();
    expect(chip80).toBeInTheDocument();
    fireEvent.click(chip40);
    expect(onSeekMs).toHaveBeenCalledWith(80_000);
  });

  it('omits seek chips when mobileSeekChips is false / undefined', () => {
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="playing"
          track={null}
          positionMs={0}
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={() => {}}
        />,
      ),
    );
    expect(screen.queryByRole('button', { name: /Seek to 40%/i })).toBeNull();
  });

  it('seek chips are disabled when state is disconnected', () => {
    const onSeekMs = vi.fn();
    render(
      wrap(
        <PlayerCard
          variant="full"
          state="disconnected"
          track={null}
          positionMs={0}
          mobileSeekChips
          onPlayPause={() => {}}
          onPrev={() => {}}
          onNext={() => {}}
          onRetry={() => {}}
          onOpenDevicePicker={() => {}}
          onSeekMs={onSeekMs}
        />,
      ),
    );
    const chip40 = screen.getByRole('button', { name: /Seek to 40%/i });
    expect(chip40).toBeDisabled();
    fireEvent.click(chip40);
    expect(onSeekMs).not.toHaveBeenCalled();
  });
```

If the test file does not already import `PlaybackTrack`, add at the top alongside other imports:

```tsx
import type { PlaybackTrack } from '../lib/types';
```

If `fireEvent` is not yet imported, change the existing `import { render, screen } from '@testing-library/react';` to `import { render, screen, fireEvent } from '@testing-library/react';`.

- [ ] **Step 3: Run the new tests — expect failure**

Run from `frontend/`:

```bash
pnpm vitest run src/features/playback/__tests__/PlayerCard.test.tsx -t "seek chip"
```

Expected: 3 failures (chips not rendered).

- [ ] **Step 4: Implement seek chips in PlayerCard**

Open `frontend/src/features/playback/PlayerCard.tsx`. Add the import of `Button` to the existing Mantine import:

```tsx
import { Paper, Group, Stack, Text, Title, ActionIcon, Anchor, Slider, Button } from '@mantine/core';
```

Add `pctToMs` import next to existing local imports (the function lives in `lib/seekHotkeys.ts`):

```tsx
import { pctToMs } from './lib/seekHotkeys';
```

Add the constant just below the `SCRUB_OPACITY` map (around line 68):

```tsx
const SEEK_CHIP_PCTS = [0, 0.2, 0.4, 0.6, 0.8] as const;
```

In `PlayerCardProps`, add the new prop next to `metaRow`:

```tsx
  /**
   * When true, renders a row of 5 chips (0/20/40/60/80%) directly below the
   * progress slider for fast mobile seeking. CurateSession sets this only on
   * mobile breakpoints; PlayerCard itself stays layout-agnostic.
   */
  mobileSeekChips?: boolean;
```

Destructure it in the component body next to `metaRow`:

```tsx
    metaRow,
    mixName,
    mobileSeekChips = false,
```

After the existing `<Slider .../>` JSX (line ~249), add the chip row inside the `Paper` (still children of `Paper`):

```tsx
      {mobileSeekChips ? (
        <Group gap={4} wrap="nowrap" mt={6} justify="space-between">
          {SEEK_CHIP_PCTS.map((pct) => {
            const label = `${Math.round(pct * 100)}%`;
            return (
              <Button
                key={pct}
                size="compact-xs"
                variant="light"
                color="gray"
                disabled={scrubDisabled}
                onClick={() => onSeekMs(pctToMs(pct, progressMax))}
                aria-label={t('playback.controls.seek_chip_aria_pct', { pct: Math.round(pct * 100) })}
                className={classes.seekChip}
              >
                {label}
              </Button>
            );
          })}
        </Group>
      ) : null}
```

- [ ] **Step 5: Add chip styling**

Open `frontend/src/features/playback/PlayerCard.module.css`. Append:

```css
.seekChip {
  flex: 1;
  min-width: 0;
}
```

- [ ] **Step 6: Wire CurateSession to enable chips on mobile**

Open `frontend/src/features/curate/components/CurateSession.tsx`. Find the `<PlayerCard ... />` block (line ~144). Add the prop next to `showText`:

```tsx
        showText={!isMobile}
        mobileSeekChips={isMobile}
```

- [ ] **Step 7: Re-run the seek-chip tests — expect pass**

```bash
pnpm vitest run src/features/playback/__tests__/PlayerCard.test.tsx -t "seek chip"
```

Expected: 3 passing tests.

- [ ] **Step 8: Run the full PlayerCard + CurateSession test files**

```bash
pnpm vitest run src/features/playback/__tests__/PlayerCard.test.tsx src/features/curate/components/__tests__/CurateSession.test.tsx
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/playback/PlayerCard.tsx \
        frontend/src/features/playback/PlayerCard.module.css \
        frontend/src/features/playback/__tests__/PlayerCard.test.tsx \
        frontend/src/features/curate/components/CurateSession.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(curate): add 0/20/40/60/80% seek chips below progress bar on mobile"
```

(Use the `caveman:caveman-commit` skill to generate the commit message per project policy. Subject must match `^(feat|fix|chore|...)(\(.+\))?!?: `.)

---

## Task 2: Compact destination buttons on mobile (≈20% smaller)

Reduce the destination tile footprint on mobile so DISCARD + Staging block + Q/W/E + counter row all coexist without scroll. Current desktop/mobile shared `min-height` is 56px (mobile) / 64px (≥64em). Drop mobile to 44px (~21% reduction), tighten inner padding to `px="sm"` + `py={4}`, and shrink the label from `--text-14` to 12px.

Add `compact?: boolean` prop to `DestinationButton`. `DestinationGrid` already detects `isMobile` via `useMediaQuery` and passes `compact={isMobile}` into every `renderBtn` call.

**Files:**

- Modify: `frontend/src/features/curate/components/DestinationButton.tsx`
- Modify: `frontend/src/features/curate/components/DestinationButton.module.css`
- Modify: `frontend/src/features/curate/components/DestinationGrid.tsx`
- Modify: `frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx`

- [ ] **Step 1: Write the failing test for compact mode**

Open `frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx`. Add this test inside the existing `describe('DestinationButton')` (or top-level if there's no describe — check the file first; if no describe wrap exists, just append the `it(...)` calls):

```tsx
  it('renders with data-compact="true" attribute when compact prop is set', () => {
    const bucket: TriageBucket = {
      id: 'b1',
      bucket_type: 'STAGING',
      inactive: false,
      track_count: 0,
      category_id: 'c1',
      category_name: 'Big Room',
    };
    render(
      wrap(
        <DestinationButton
          bucket={bucket}
          hotkeyHint={null}
          justTapped={false}
          disabled={false}
          compact
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toHaveAttribute(
      'data-compact',
      'true',
    );
  });

  it('renders with data-compact="false" by default', () => {
    const bucket: TriageBucket = {
      id: 'b1',
      bucket_type: 'STAGING',
      inactive: false,
      track_count: 0,
      category_id: 'c1',
      category_name: 'Big Room',
    };
    render(
      wrap(
        <DestinationButton
          bucket={bucket}
          hotkeyHint={null}
          justTapped={false}
          disabled={false}
          onClick={() => {}}
        />,
      ),
    );
    expect(screen.getByRole('button', { name: /Assign to Big Room/i })).toHaveAttribute(
      'data-compact',
      'false',
    );
  });
```

If the existing test file does not already import `TriageBucket`, add:

```tsx
import type { TriageBucket } from '../../../triage/lib/bucketLabels';
```

- [ ] **Step 2: Run the new tests — expect failure**

```bash
pnpm vitest run src/features/curate/components/__tests__/DestinationButton.test.tsx -t "compact"
```

Expected: 2 failures (no `data-compact` attribute yet).

- [ ] **Step 3: Add compact prop to DestinationButton**

Open `frontend/src/features/curate/components/DestinationButton.tsx`. Replace the entire component file with:

```tsx
import { Group, Kbd, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import classes from './DestinationButton.module.css';
import {
  bucketLabel,
  type TriageBucket,
} from '../../triage/lib/bucketLabels';

export interface DestinationButtonProps {
  bucket: TriageBucket;
  hotkeyHint: string | null;
  justTapped: boolean;
  disabled: boolean;
  /** When true, renders a tighter layout for mobile (smaller height + padding + font). */
  compact?: boolean;
  onClick: () => void;
}

export function DestinationButton({
  bucket,
  hotkeyHint,
  justTapped,
  disabled,
  compact = false,
  onClick,
}: DestinationButtonProps) {
  const { t } = useTranslation();
  const label = bucketLabel(bucket, t);

  let title: string | undefined;
  if (disabled) {
    title =
      bucket.bucket_type === 'STAGING' && bucket.inactive
        ? t('curate.destination.inactive_disabled_title')
        : t('curate.destination.self_disabled_title');
  }

  return (
    <UnstyledButton
      onClick={onClick}
      disabled={disabled}
      className={classes.button}
      data-just-tapped={justTapped ? 'true' : 'false'}
      data-disabled={disabled ? 'true' : 'false'}
      data-compact={compact ? 'true' : 'false'}
      aria-label={t('curate.destination.assign_aria', { label })}
      title={title}
    >
      <Group
        justify={hotkeyHint === null ? 'center' : 'space-between'}
        gap="sm"
        wrap="nowrap"
        px={compact ? 'sm' : 'md'}
        py={compact ? 4 : 'xs'}
      >
        <span className={classes.label} data-centered={hotkeyHint === null ? 'true' : 'false'}>
          {label}
        </span>
        {hotkeyHint !== null && <Kbd>{hotkeyHint}</Kbd>}
      </Group>
    </UnstyledButton>
  );
}
```

- [ ] **Step 4: Add compact CSS modifier**

Open `frontend/src/features/curate/components/DestinationButton.module.css`. Replace the entire file with:

```css
.button {
  width: 100%;
  min-height: var(--control-xl, 56px);
  border-radius: var(--radius-md);
  border: var(--border-thin) solid var(--color-border);
  background: var(--color-bg-elevated);
  color: var(--color-fg);
  transition:
    transform var(--motion-pulse) var(--ease-out),
    background var(--motion-base) var(--ease-out);
}
.button[data-compact='true'] {
  min-height: 44px;
}
.button[data-compact='true'] .label {
  font-size: 12px;
}
.button:hover:not([data-disabled='true']) {
  background: var(--color-hover);
}
.button[data-disabled='true'] {
  opacity: 0.4;
  pointer-events: none;
}
.button[data-just-tapped='true'] {
  transform: scale(0.97);
}
.label {
  font-size: var(--text-14);
  font-weight: var(--weight-medium);
  text-align: left;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.label[data-centered='true'] {
  text-align: center;
  flex: 0 1 auto;
}
@media (prefers-reduced-motion: reduce) {
  .button[data-just-tapped='true'] {
    transform: none;
  }
  .button {
    transition: background var(--motion-base) var(--ease-out);
  }
}
@media (min-width: 64em) {
  .button {
    min-height: 64px;
  }
  /* Compact mode is mobile-only by intent; desktop ignores the hint. */
}
```

- [ ] **Step 5: Thread compact through DestinationGrid**

Open `frontend/src/features/curate/components/DestinationGrid.tsx`. Find `renderBtn` (line ~65). Replace the function body so it forwards `compact={isMobile}`:

```tsx
  const renderBtn = (
    bucket: TriageBucket | null,
    hotkeyHint: string | null,
  ) => {
    if (!bucket) return null;
    const isSelf = bucket.id === currentBucketId;
    return (
      <DestinationButton
        key={bucket.id}
        bucket={bucket}
        hotkeyHint={isMobile ? null : hotkeyHint}
        justTapped={lastTappedBucketId === bucket.id}
        disabled={isSelf}
        compact={isMobile}
        onClick={() => onAssign(bucket.id)}
      />
    );
  };
```

Also update the inline `<DestinationButton>` used as the More… `Menu.Target` (line ~94) so the overflow tile compacts the same way:

```tsx
                <Menu.Target>
                  <DestinationButton
                    bucket={{
                      id: '__overflow__',
                      bucket_type: 'STAGING',
                      inactive: false,
                      track_count: 0,
                      category_id: null,
                      category_name: t('curate.destination.more_categories'),
                    }}
                    hotkeyHint={null}
                    justTapped={false}
                    disabled={false}
                    compact={isMobile}
                    onClick={() => {}}
                  />
                </Menu.Target>
```

- [ ] **Step 6: Run the new + existing button tests — expect pass**

```bash
pnpm vitest run src/features/curate/components/__tests__/DestinationButton.test.tsx \
                src/features/curate/components/__tests__/DestinationGrid.test.tsx
```

Expected: all tests pass (compact tests added in Step 1 now pass; pre-existing tests unaffected because default `compact={false}` preserves desktop sizing).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/curate/components/DestinationButton.tsx \
        frontend/src/features/curate/components/DestinationButton.module.css \
        frontend/src/features/curate/components/DestinationGrid.tsx \
        frontend/src/features/curate/components/__tests__/DestinationButton.test.tsx
git commit -m "feat(curate): compact destination buttons on mobile (~20% smaller)"
```

(Use `caveman:caveman-commit` skill for the actual subject.)

---

## Task 3: Remap DISCARD hotkey 0 → Z

Three call sites swap from `Digit0`/`'0'` to `KeyZ`/`'Z'`:

1. `useCurateHotkeys.ts` event handler.
2. `DestinationGrid.tsx` Kbd hint passed to `renderBtn(discardBucket, ...)`.
3. `HotkeyOverlay.tsx` `ASSIGN` row + i18n label rename.

**Files:**

- Modify: `frontend/src/features/curate/hooks/useCurateHotkeys.ts`
- Modify: `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx`
- Modify: `frontend/src/features/curate/components/DestinationGrid.tsx`
- Modify: `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx`
- Modify: `frontend/src/features/curate/components/HotkeyOverlay.tsx`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Update the failing-side tests first**

Edit `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx`. Replace the test starting at line 114:

```tsx
  it('Digit0 calls onAssign with DISCARD', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit0' }));
    expect(onAssign).toHaveBeenCalledWith('b-disc');
  });
```

with:

```tsx
  it('KeyZ calls onAssign with DISCARD', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyZ' }));
    expect(onAssign).toHaveBeenCalledWith('b-disc');
  });

  it('Digit0 no longer fires DISCARD', () => {
    mount(false);
    act(() => dispatchKey({ code: 'Digit0' }));
    expect(onAssign).not.toHaveBeenCalled();
  });
```

Edit `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx`. Replace the test starting at line 72 (`renders Q/W/E and 0 hotkey badges`):

```tsx
  it('renders Q/W/E and Z hotkey badges', () => {
    render(
      wrap(
        <DestinationGrid
          buckets={buckets}
          currentBucketId="b-current"
          lastTappedBucketId={null}
          onAssign={() => {}}
        />,
      ),
    );
    expect(screen.getByText('Q')).toBeInTheDocument();
    expect(screen.getByText('W')).toBeInTheDocument();
    expect(screen.getByText('E')).toBeInTheDocument();
    expect(screen.getByText('Z')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the updated tests — expect failure**

```bash
pnpm vitest run src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx \
                src/features/curate/components/__tests__/DestinationGrid.test.tsx \
                -t "KeyZ|Z hotkey|no longer fires"
```

Expected: failures because the implementation still uses `Digit0`.

- [ ] **Step 3: Update the keyboard handler**

Open `frontend/src/features/curate/hooks/useCurateHotkeys.ts`. Replace the `case 'Digit0'` block (line ~93):

```ts
        case 'Digit0': {
          event.preventDefault();
          const b = byDiscard(buckets);
          if (b) onAssign(b.id);
          return;
        }
```

with:

```ts
        case 'KeyZ': {
          event.preventDefault();
          const b = byDiscard(buckets);
          if (b) onAssign(b.id);
          return;
        }
```

- [ ] **Step 4: Update the rendered Kbd hint**

Open `frontend/src/features/curate/components/DestinationGrid.tsx`. Find line 85:

```tsx
      {discardBucket && renderBtn(discardBucket, '0')}
```

Replace with:

```tsx
      {discardBucket && renderBtn(discardBucket, 'Z')}
```

- [ ] **Step 5: Update the help overlay table**

Open `frontend/src/features/curate/components/HotkeyOverlay.tsx`. Replace line 20:

```ts
  { keys: ['0'], labelKey: 'curate.hotkeys.key_zero_label' },
```

with:

```ts
  { keys: ['Z'], labelKey: 'curate.hotkeys.key_z_label' },
```

- [ ] **Step 6: Rename the i18n key**

Open `frontend/src/i18n/en.json`. Find line 357:

```json
      "key_zero_label": "Assign to DISCARD",
```

Replace with:

```json
      "key_z_label": "Assign to DISCARD",
```

- [ ] **Step 7: Run the full test suite for curate + playback**

```bash
pnpm vitest run src/features/curate src/features/playback
```

Expected: all tests pass.

- [ ] **Step 8: Verify no stale references to `key_zero_label` or DISCARD-on-`0`**

```bash
grep -rn "key_zero_label\|Digit0" frontend/src
```

Expected: no matches anywhere except potentially the explicit "no-longer-fires" negative test from Step 1 (which only references the code string `'Digit0'` to assert it does nothing).

- [ ] **Step 9: Run typecheck + lint**

```bash
cd frontend && pnpm typecheck && pnpm lint
```

Expected: no errors.

- [ ] **Step 10: Manual smoke (browser, optional but recommended)**

Per CLAUDE.md frontend gotcha: `pnpm dev` from `frontend/` (requires `frontend/.env.local`). Open Curate session on desktop, press `Z` → DISCARD bucket fires; open in mobile viewport (DevTools <64em), confirm Discard button height ≈44px and seek chips appear under the progress bar with working 0/20/40/60/80 navigation. If you cannot run the browser, state so explicitly.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateHotkeys.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx \
        frontend/src/features/curate/components/DestinationGrid.tsx \
        frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx \
        frontend/src/features/curate/components/HotkeyOverlay.tsx \
        frontend/src/i18n/en.json
git commit -m "feat(curate): remap DISCARD hotkey from 0 to Z"
```

(Use `caveman:caveman-commit` skill for the actual subject.)

---

## Self-Review Notes

- **Spec coverage:**
  - "Кнопки перемотки 0/20/40/60/80 на мобильной под прогрессом" → Task 1 (chips inside PlayerCard, gated by `mobileSeekChips` flag CurateSession sets on mobile).
  - "Кнопки категорий на мобильном меньше на ~20% чтобы Staging влезал" → Task 2 (44px vs 56px = 21% reduction; padding + font tightened).
  - "Discard: вместо 0 поставить Z" → Task 3 (handler + Kbd hint + overlay row + i18n).
- **Type consistency:** `compact` is `boolean | undefined` everywhere; default `false`. `mobileSeekChips` is `boolean | undefined`; default `false`. `pctToMs` already exported from `lib/seekHotkeys.ts`. `seek_chip_aria_pct` interpolation key matches its `t(..., { pct })` call.
- **No placeholders:** every step shows the full code or exact replacement; commands include expected output.
- **Existing keyboard hotkey for `Z`:** none — `usePlaybackHotkeys` uses `KeyA/S/D/F/G/J/K`, `Space`, `Shift+J/K`; `useCurateHotkeys` uses `KeyQ/W/E/U`, digits, `Escape`, `?`. No collision.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-06-curate-mobile-fixes.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch execution with checkpoints.

**Which approach?**

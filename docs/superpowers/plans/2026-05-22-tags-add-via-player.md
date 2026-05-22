# Move Tag-Adding to the Player Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the category table's Tags column read-only (remove the inline "+") and add a "+" in the player's Tags block that opens the existing pick/create popover.

**Architecture:** `TrackTagsCell` becomes display-only. `PlayerPanelTagCloud` gains a `categoryId` prop and a trailing "+" that anchors `TrackTagsPopover` (reused unchanged) for the current track. Frontend-only.

**Tech Stack:** React 19, TypeScript, Mantine 9, react-i18next (EN-only), Vitest + Testing Library. pnpm; run frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-22-tags-add-via-player-design.md`

---

## File structure

**Changed**
- `frontend/src/features/tags/components/TrackTagsCell.tsx` — read-only display. (+test)
- `frontend/src/features/categories/components/TrackRow.tsx` — update `TrackTagsCell` usage.
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — add `categoryId` + "+" + `TrackTagsPopover`. (+test, + CategoryPlayerPanel test mock update)
- `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — pass `categoryId` to the tag cloud.

`TrackTagsPopover` reused unchanged. No backend/router change. `TrackTagsCell` is used only by `TrackRow` (verified) + the `tags/index.ts` barrel export (type/component name unchanged).

---

### Task 1: Table Tags column → read-only `TrackTagsCell`

**Files:**
- Modify: `frontend/src/features/tags/components/TrackTagsCell.tsx`
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`
- Test: `frontend/src/features/tags/components/__tests__/TrackTagsCell.test.tsx`

- [ ] **Step 1: Rewrite the TrackTagsCell test for read-only**

Replace the ENTIRE contents of `frontend/src/features/tags/components/__tests__/TrackTagsCell.test.tsx` (the old tests asserted a "+" and popover, which are removed):

```tsx
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { TrackTagsCell } from '../TrackTagsCell';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('TrackTagsCell', () => {
  it('renders pills for current tags', () => {
    r(
      <TrackTagsCell
        tags={[
          { id: 'tg1', name: 'Vocal', color: '#ff8800' },
          { id: 'tg2', name: 'Dark', color: null },
        ]}
      />,
    );
    expect(screen.getByText('Vocal')).toBeInTheDocument();
    expect(screen.getByText('Dark')).toBeInTheDocument();
  });

  it('renders no add button (read-only)', () => {
    r(<TrackTagsCell tags={[]} />);
    expect(screen.queryByRole('button', { name: /add tag/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `pnpm test src/features/tags/components/__tests__/TrackTagsCell.test.tsx`
Expected: type/compile FAIL — current `TrackTagsCell` still requires `categoryId`/`trackId` and renders a button; the new test passes only `tags`.

- [ ] **Step 3: Rewrite `TrackTagsCell` as read-only**

Replace the ENTIRE contents of `frontend/src/features/tags/components/TrackTagsCell.tsx`:

```tsx
import { Group } from '@mantine/core';
import { TagPill } from './TagPill';

export interface TrackTagsCellTag {
  id: string;
  name: string;
  color: string | null;
}

export interface TrackTagsCellProps {
  tags: readonly TrackTagsCellTag[];
}

export function TrackTagsCell({ tags }: TrackTagsCellProps) {
  return (
    <Group gap={4} wrap="wrap">
      {tags.map((tag) => (
        <TagPill key={tag.id} name={tag.name} color={tag.color} />
      ))}
    </Group>
  );
}
```

(Drops `categoryId`/`trackId`, the `+` button, the popover, and the `useState`/`useTranslation` imports. `TrackTagsCellTag` is kept and still re-exported by `tags/index.ts`.)

- [ ] **Step 4: Update the `TrackRow` call site**

In `frontend/src/features/categories/components/TrackRow.tsx`, the cell is rendered as:
```tsx
const tagsCell = (
  <TrackTagsCell categoryId={categoryId} trackId={track.id} tags={track.tags} />
);
```
Change it to:
```tsx
const tagsCell = <TrackTagsCell tags={track.tags} />;
```
(Keep `TrackRow`'s own `categoryId` prop — it's still used by `TrackRowActions` elsewhere in the row; only the `TrackTagsCell` args change.)

- [ ] **Step 5: Run the cell + row tests**

From `frontend/`: `pnpm test src/features/tags/components/__tests__/TrackTagsCell.test.tsx src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: PASS. (`TrackRow.test` renders the cell but does not exercise the removed popover, so it stays green.)

- [ ] **Step 6: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/tags/components/TrackTagsCell.tsx frontend/src/features/tags/components/__tests__/TrackTagsCell.test.tsx frontend/src/features/categories/components/TrackRow.tsx
git commit -m "feat(categories): make table Tags column read-only"
```

(NO `Co-Authored-By` trailer — a pre-commit hook rejects it.)

---

### Task 2: Player Tags block → add "+" with the pick/create popover

**Files:**
- Modify: `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Test: `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
- Test: `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx` (mock update only)

- [ ] **Step 1: Rewrite the PlayerPanelTagCloud test**

Replace the ENTIRE contents of `frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';

// Mock the tags barrel: real-ish useTags + a stub TrackTagsPopover that renders
// its target and a marker input when opened (so we can assert the "+" opens it
// without pulling React Query / the popover's own mutations).
vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [
      { id: 'tg-a', name: 'acid', color: '#f00' },
      { id: 'tg-b', name: 'banger', color: '#0f0' },
    ],
    isLoading: false,
  }),
  TrackTagsPopover: ({
    opened,
    target,
  }: {
    opened: boolean;
    target: React.ReactNode;
  }) => (
    <div data-testid="tags-popover">
      {target}
      {opened && <input placeholder="search or create" />}
    </div>
  ),
}));

import { PlayerPanelTagCloud } from '../PlayerPanelTagCloud';

function ui(props: Parameters<typeof PlayerPanelTagCloud>[0]) {
  return (
    <MantineProvider>
      <PlayerPanelTagCloud {...props} />
    </MantineProvider>
  );
}

const base = { categoryId: 'c1', trackId: 't-1', onAdd: vi.fn(), onRemove: vi.fn() };

describe('PlayerPanelTagCloud', () => {
  it('renders all user tags', () => {
    render(ui({ ...base, assignedTagIds: [] }));
    expect(screen.getByText('acid')).toBeInTheDocument();
    expect(screen.getByText('banger')).toBeInTheDocument();
  });

  it('marks assigned tags as checked', () => {
    render(ui({ ...base, assignedTagIds: ['tg-a'] }));
    const acidInput = screen
      .getByText('acid')
      .closest('.mantine-Chip-root')!
      .querySelector('input')! as HTMLInputElement;
    expect(acidInput.checked).toBe(true);
  });

  it('click on unassigned chip calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ ...base, assignedTagIds: [], onAdd }));
    await userEvent.click(screen.getByText('acid'));
    expect(onAdd).toHaveBeenCalledWith('tg-a');
  });

  it('click on assigned chip calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ ...base, assignedTagIds: ['tg-a'], onRemove }));
    await userEvent.click(screen.getByText('acid'));
    expect(onRemove).toHaveBeenCalledWith('tg-a');
  });

  it('renders an add button that opens the tag popover', async () => {
    render(ui({ ...base, assignedTagIds: [] }));
    const add = screen.getByRole('button', { name: /add tag/i });
    expect(add).toBeInTheDocument();
    await userEvent.click(add);
    expect(screen.getByPlaceholderText(/search or create/i)).toBeInTheDocument();
  });
});
```

(`import '../../../../i18n'` makes `t('tags.cell.add_aria')` resolve to "Add tag" so the role query matches. The stub `TrackTagsPopover` renders the `target` (the "+") always and the marker input when `opened`.)

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
Expected: FAIL — `PlayerPanelTagCloud` has no `categoryId` prop / no add button yet.

- [ ] **Step 3: Add "+" + popover to `PlayerPanelTagCloud`**

Replace the ENTIRE contents of `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`:

```tsx
import { useMemo, useState } from 'react';
import { ActionIcon, Chip, Group, Stack, Text } from '@mantine/core';
import { IconPlus } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useTags, TrackTagsPopover } from '../../tags';

export interface PlayerPanelTagCloudProps {
  categoryId: string;
  trackId: string;
  assignedTagIds: readonly string[];
  onAdd: (tagId: string) => void;
  onRemove: (tagId: string) => void;
}

export function PlayerPanelTagCloud(props: PlayerPanelTagCloudProps) {
  const { categoryId, trackId, assignedTagIds, onAdd, onRemove } = props;
  const { t } = useTranslation();
  const tagsQuery = useTags();
  const [opened, setOpened] = useState(false);
  const assigned = useMemo(() => new Set(assignedTagIds), [assignedTagIds]);

  const tags = useMemo(
    () => (tagsQuery.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name)),
    [tagsQuery.data],
  );

  const addButton = (
    <ActionIcon
      variant="subtle"
      size="sm"
      aria-label={t('tags.cell.add_aria')}
      onClick={() => setOpened((o) => !o)}
    >
      <IconPlus size={14} />
    </ActionIcon>
  );

  return (
    <Stack gap="xs">
      <Group gap="xs" wrap="wrap" align="center">
        {tags.map((tg) => {
          const selected = assigned.has(tg.id);
          return (
            <Chip
              key={tg.id}
              checked={selected}
              size="sm"
              variant={selected ? 'filled' : 'outline'}
              color={tg.color ?? 'gray'}
              onChange={() => (selected ? onRemove(tg.id) : onAdd(tg.id))}
            >
              {tg.name}
            </Chip>
          );
        })}
        {tags.length === 0 && (
          <Text c="dimmed" size="sm">
            No tags yet
          </Text>
        )}
        <TrackTagsPopover
          opened={opened}
          onClose={() => setOpened(false)}
          target={addButton}
          categoryId={categoryId}
          trackId={trackId}
          currentTagIds={assignedTagIds}
        />
      </Group>
    </Stack>
  );
}
```

(The "+" renders unconditionally (after the chips, or after the "No tags yet" hint when empty), so the first tag can always be created. The chips keep their toggle behavior. `TrackTagsPopover` handles its own pick/create/assign.)

- [ ] **Step 4: Run the cloud test**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Pass `categoryId` from `CategoryPlayerPanel`**

In `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`, find the `<PlayerPanelTagCloud ... />` render (in the Tags section) and add the `categoryId` prop:
```tsx
      <PlayerPanelTagCloud
        categoryId={categoryId}
        trackId={current.id}
        assignedTagIds={assignedTagIds}
        onAdd={(id) => void onAddTag(id)}
        onRemove={(id) => void onRemoveTag(id)}
      />
```
(Match the existing prop names/handlers in the file; only ADD `categoryId={categoryId}`. `categoryId` is already a prop of `CategoryPlayerPanel`.)

- [ ] **Step 6: Update the CategoryPlayerPanel test's tags-barrel mock**

`CategoryPlayerPanel.test.tsx` mocks `'../../../tags'` providing only `useTags`. Since the panel now renders `PlayerPanelTagCloud` which imports `TrackTagsPopover` from that barrel, add a stub to the mock so it resolves. In `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`, find:
```tsx
vi.mock('../../../tags', () => ({
  useTags: () => ({ data: [...], isLoading: false }),
}));
```
and add a `TrackTagsPopover` stub key (render only the `target` so the existing assertions are unaffected):
```tsx
vi.mock('../../../tags', () => ({
  useTags: () => ({
    data: [{ id: 'tag-1', name: 'Acid', color: 'red' }],
    isLoading: false,
  }),
  TrackTagsPopover: ({ target }: { target: React.ReactNode }) => <>{target}</>,
}));
```
(Keep the existing `useTags` return value exactly as it was in the file; only add the `TrackTagsPopover` key. Ensure `React` is imported in the test file — it already renders JSX; if not present, add `import React from 'react';`.)

- [ ] **Step 7: Typecheck + lint + run category tests**

From `frontend/`:
```
pnpm typecheck && pnpm lint && pnpm test src/features/categories
```
Expected: no type/lint errors (only the 2 pre-existing warnings in `useCurateSession.ts` + `theme.ts`); all category tests pass (incl. the updated `CategoryPlayerPanel.test`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/categories/components/PlayerPanelTagCloud.tsx frontend/src/features/categories/components/CategoryPlayerPanel.tsx frontend/src/features/categories/components/__tests__/PlayerPanelTagCloud.test.tsx frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx
git commit -m "feat(categories): add tag picker to the player tags block"
```

---

### Task 3: Full verification

- [ ] **Step 1: Whole suite**

From `frontend/`: `pnpm test`
Expected: all tests pass. (Use `pnpm test` — it sets `NODE_OPTIONS=--no-experimental-webstorage`; running `vitest` directly without that flag causes unrelated localStorage-env failures.)

- [ ] **Step 2: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: clean (only the 2 pre-existing warnings).

- [ ] **Step 3: Manual smoke test (golden path)**

Start `pnpm dev` from `frontend/`. On a category page:
- The table Tags column shows tag pills but no "+" and pills are not clickable.
- Play a track → the player Tags block shows the existing tag chips (toggle) plus a "+" after them.
- Click the "+" → the pick/create popover opens; pick an existing tag (assigns) or create a new one (name + color) → it assigns to the playing track and appears as a chip; the table row's pills update too.
- A track with no tags still shows the "+" in the player.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** read-only table cell + call-site update (Task 1); player "+" opening `TrackTagsPopover` + `categoryId` thread + empty-state "+" (Task 2). `TrackTagsPopover` reused unchanged. No backend/router change.
- **Cross-file test integrity:** both `PlayerPanelTagCloud.test` and `CategoryPlayerPanel.test` mock the `tags` barrel; both must add a `TrackTagsPopover` stub once the panel/cloud import it (Task 2 Steps 1 & 6) — otherwise the barrel mock yields `undefined` and rendering crashes.
- **Type/name consistency:** `TrackTagsCellProps` now `{ tags }`; `PlayerPanelTagCloudProps` gains `categoryId: string`; `TrackTagsPopover` props (`opened`, `onClose`, `target`, `categoryId`, `trackId`, `currentTagIds`) match its definition. `tags.cell.add_aria` reused for the player "+".
- **Placeholder scan:** none.

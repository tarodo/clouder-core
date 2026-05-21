# Distribution Buttons Style Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `Chip`-style distribution controls with `Button`s — triage distribute buttons (2/row mobile, 3/row desktop, DISCARD light red) and the category playlist cloud (2/row toggle buttons).

**Architecture:** Two focused presentational rewrites. `BucketDistributeButtons` reverts from `Chip` to a `SimpleGrid` of `Button`s. `PlayerPanelPlaylistCloud` switches from a `Chip` group to a 2-column `SimpleGrid` of full-width toggle `Button`s (filled = member), keeping the numeric hotkey badge. Frontend-only.

**Tech Stack:** React 19, TypeScript, Mantine 9, TanStack Query v5, react-i18next (EN-only), Vitest + Testing Library. pnpm; run frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-21-distribution-buttons-style-design.md`

---

## File structure

**Changed**
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` — `Chip` → `Button` grid. (+test)
- `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx` — `Chip` → 2/row toggle `Button`s. (+test)

Untouched: `PlayerPanelTagCloud` (stays colored chips), player layout/width/gate, `useBucketDistribute`, `useCategoryPlayerHotkeys` (hotkeys work regardless of rendering). No backend/router change.

**Verified-still-green (no edits expected):** `BucketPlayerPanel.test.tsx` (its distribute queries are text-based → match buttons), `CategoryPlayerPanel.test.tsx` (asserts playlist text), and the categories hotkey integration test `frontend/src/features/categories/__tests__/integration.player.test.tsx` (hotkey path unchanged). Run them in Task 3; adapt only if a test queried a chip-specific selector.

---

### Task 1: Triage `BucketDistributeButtons` — Chip → Button

**Files:**
- Modify: `frontend/src/features/triage/components/BucketDistributeButtons.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`

- [ ] **Step 1: Update the test to button-role queries**

Replace the first two tests' bodies in `BucketDistributeButtons.test.tsx` (keep the third "renders nothing when there are no destinations" test unchanged):

```tsx
  it('renders a button per destination with bucket labels', () => {
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={vi.fn()} />);
    expect(screen.getByText('Move current track to')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Techno' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DISCARD' })).toBeInTheDocument();
  });

  it('calls onDistribute with the bucket id on click', async () => {
    const onDistribute = vi.fn();
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={onDistribute} />);
    await userEvent.click(screen.getByRole('button', { name: 'Techno' }));
    expect(onDistribute).toHaveBeenCalledWith('bk2');
  });
```

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: the button-role queries FAIL — the current implementation renders `Chip`s (role checkbox), not buttons.

- [ ] **Step 3: Convert the component to `Button`s**

Replace the ENTIRE contents of `frontend/src/features/triage/components/BucketDistributeButtons.tsx`:

```tsx
import { Button, SimpleGrid, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketDistributeButtonsProps {
  destinations: TriageBucket[];
  onDistribute: (toBucketId: string) => void;
}

export function BucketDistributeButtons({
  destinations,
  onDistribute,
}: BucketDistributeButtonsProps) {
  const { t } = useTranslation();
  if (destinations.length === 0) return null;
  return (
    <Stack gap="xs" data-testid="bucket-distribute">
      <Text
        ff="monospace"
        fz={10}
        c="var(--color-fg-muted)"
        tt="uppercase"
        style={{ letterSpacing: '0.1em' }}
      >
        {t('triage.bucket_player.distribute.heading')}
      </Text>
      <SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs">
        {destinations.map((b) => {
          const label = bucketLabel(b, t);
          return (
            <Button
              key={b.id}
              variant={b.bucket_type === 'DISCARD' ? 'light' : 'default'}
              color={b.bucket_type === 'DISCARD' ? 'red' : undefined}
              size="sm"
              onClick={() => onDistribute(b.id)}
              aria-label={label}
              styles={{ label: { whiteSpace: 'normal' } }}
            >
              {label}
            </Button>
          );
        })}
      </SimpleGrid>
    </Stack>
  );
}
```

(2 per row on mobile, 3 on desktop. DISCARD = `variant="light" color="red"` = light red.)

- [ ] **Step 4: Run the component test**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the panel test (should still pass — text queries)**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: PASS — the panel test queries distribute destinations by text (`getByText('Techno')`), which matches buttons. If any assertion there used a chip-specific selector, switch it to text/button-role; otherwise no change.

- [ ] **Step 6: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/triage/components/BucketDistributeButtons.tsx frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx
git commit -m "feat(triage): use button style for bucket distribution buttons"
```

(NO `Co-Authored-By` trailer — a pre-commit hook rejects it.)

---

### Task 2: Category `PlayerPanelPlaylistCloud` — Chip → 2/row toggle Buttons

**Files:**
- Modify: `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx`
- Test: `frontend/src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`

- [ ] **Step 1: Rewrite the test for buttons**

Replace the two chip-specific tests; keep the hotkey-badge test and the click tests (they work for buttons). Full new test file body for `PlayerPanelPlaylistCloud.test.tsx` (the mocks/`ui` helper at the top are unchanged):

```tsx
describe('PlayerPanelPlaylistCloud', () => {
  it('renders hotkey badges 1-9 then 0 on first 10', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('9')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.queryByText('11')).not.toBeInTheDocument();
  });

  it('marks the selected playlist button as filled', () => {
    render(
      ui({ trackId: 't-1', trackPlaylistIds: ['pl-2'], onAdd: vi.fn(), onRemove: vi.fn() }),
    );
    const btn = screen.getByText('Playlist 2').closest('button')!;
    expect(btn).toHaveAttribute('data-variant', 'filled');
  });

  it('renders an unselected playlist button as default variant', () => {
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd: vi.fn(), onRemove: vi.fn() }));
    const btn = screen.getByText('Playlist 0').closest('button')!;
    expect(btn).toHaveAttribute('data-variant', 'default');
  });

  it('click on a default button calls onAdd', async () => {
    const onAdd = vi.fn();
    render(ui({ trackId: 't-1', trackPlaylistIds: [], onAdd, onRemove: vi.fn() }));
    await userEvent.click(screen.getByText('Playlist 0'));
    expect(onAdd).toHaveBeenCalledWith('pl-0');
  });

  it('click on a filled button calls onRemove', async () => {
    const onRemove = vi.fn();
    render(ui({ trackId: 't-1', trackPlaylistIds: ['pl-0'], onAdd: vi.fn(), onRemove }));
    await userEvent.click(screen.getByText('Playlist 0'));
    expect(onRemove).toHaveBeenCalledWith('pl-0');
  });
});
```

(Mantine `Button` exposes `data-variant` on its root `<button>` — verified.)

- [ ] **Step 2: Run to verify the variant test fails**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`
Expected: the "marks the selected playlist button as filled" / "default variant" tests FAIL — current rendering is `Chip` (`.mantine-Chip-root`, no `data-variant` on a `<button>`).

- [ ] **Step 3: Convert the component to 2/row toggle Buttons**

Replace the ENTIRE contents of `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx`:

```tsx
import { useMemo } from 'react';
import { Badge, Button, SimpleGrid, Text } from '@mantine/core';
import { usePlaylists } from '../../playlists/hooks/usePlaylists';

export interface PlayerPanelPlaylistCloudProps {
  trackId: string;
  trackPlaylistIds: readonly string[];
  onAdd: (playlistId: string) => void;
  onRemove: (playlistId: string) => void;
}

const HOTKEY_LABELS = ['1', '2', '3', '4', '5', '6', '7', '8', '9', '0'];

export function PlayerPanelPlaylistCloud(props: PlayerPanelPlaylistCloudProps) {
  const { trackPlaylistIds, onAdd, onRemove } = props;
  // usePlaylists signature: { search?, status?, limit?, offset?, enabled? }.
  // Pull a wide page so the active set fits without pagination on the panel.
  const query = usePlaylists({ status: 'active', limit: 100 });
  const playlists = query.data?.items ?? [];

  const inPlaylist = useMemo(() => new Set(trackPlaylistIds), [trackPlaylistIds]);

  if (playlists.length === 0) {
    return (
      <Text c="dimmed" size="sm">
        No active playlists
      </Text>
    );
  }

  return (
    <SimpleGrid cols={2} spacing="xs" verticalSpacing="xs">
      {playlists.map((pl, idx) => {
        const selected = inPlaylist.has(pl.id);
        const hotkey = idx < HOTKEY_LABELS.length ? HOTKEY_LABELS[idx] : null;
        return (
          <Button
            key={pl.id}
            fullWidth
            size="sm"
            variant={selected ? 'filled' : 'default'}
            onClick={() => (selected ? onRemove(pl.id) : onAdd(pl.id))}
            leftSection={
              hotkey ? (
                <Badge variant="default" size="xs" radius="sm">
                  {hotkey}
                </Badge>
              ) : undefined
            }
            styles={{
              label: { whiteSpace: 'normal' },
              inner: { justifyContent: 'flex-start' },
            }}
          >
            {pl.name}
          </Button>
        );
      })}
    </SimpleGrid>
  );
}
```

(2 per row everywhere via `cols={2}`. `filled` = the track is in that playlist; `default` otherwise. Hotkey badge kept in `leftSection`; the numeric hotkeys still work through `useCategoryPlayerHotkeys`. Empty state preserved.)

- [ ] **Step 4: Run the playlist-cloud test**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the category player tests (should stay green)**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx src/features/categories/__tests__/integration.player.test.tsx`
Expected: PASS. `CategoryPlayerPanel.test.tsx` asserts playlist text (`getAllByText('Acid')`), which matches buttons; the integration test exercises the hotkey path (`useCategoryPlayerHotkeys`), unaffected by the chip→button swap. If either queried a `.mantine-Chip-root` selector, switch it to the button/text equivalent; otherwise no change.

- [ ] **Step 6: Typecheck + lint + commit**

```bash
cd frontend && pnpm typecheck && pnpm lint && cd ..
git add frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx frontend/src/features/categories/components/__tests__/PlayerPanelPlaylistCloud.test.tsx
git commit -m "feat(categories): use 2-per-row toggle buttons for playlist cloud"
```

Expected lint: no errors (2 pre-existing warnings in `useCurateSession.ts` + `theme.ts` are OK).

---

### Task 3: Full verification

- [ ] **Step 1: Run the whole frontend suite**

From `frontend/`: `pnpm test`
Expected: all tests pass.

- [ ] **Step 2: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: clean (only the 2 pre-existing warnings).

- [ ] **Step 3: Manual smoke test (golden path)**

Start `pnpm dev` from `frontend/` (needs `frontend/.env.local` with `VITE_API_BASE_URL`). Then:
- Triage staging bucket player: distribution controls are `Button`s — 2 per row on a narrow window, 3 per row on desktop; the DISCARD button is light red; tapping one moves the track + advances.
- Category player: the playlist section shows 2-per-row buttons; a playlist the current track belongs to is filled, others are default; clicking toggles membership; the numeric hotkey badge shows and pressing the number still toggles the matching playlist. The tag section is still colored chips.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** triage Chip→Button 2/3-per-row + light-red DISCARD (Task 1); category playlist Chip→Button 2-per-row + filled toggle + hotkey badge (Task 2); tag cloud untouched; no backend change. 
- **Type/name consistency:** `BucketDistributeButtonsProps` and `PlayerPanelPlaylistCloudProps` signatures unchanged (drop-in rewrites). `bucketLabel`, `usePlaylists`, `HOTKEY_LABELS` reused as-is.
- **Test integrity across tasks:** Task 1 reverts the triage component test to button-role queries; the panel test already uses text queries (works for buttons), so it needs no change (verified in Task 1 Step 5). Task 2 rewrites the playlist-cloud test from chip-checkbox assertions to `data-variant` button assertions (Mantine Button `data-variant` confirmed present).
- **Placeholder scan:** none.

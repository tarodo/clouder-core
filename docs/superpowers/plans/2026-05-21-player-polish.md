# Triage / Category Player Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict the triage player to staging buckets, match its width to the category player, and unify the distribution-button style + layout (controls → Chip buttons → LabelTile) across both players.

**Architecture:** Gate all player wiring in `BucketDetailPage` on `bucket_type === 'STAGING'`. Widen `BucketPlayerPanel` to 520px and add the full `LabelTile` below the distribution buttons. Convert `BucketDistributeButtons` from `Button` to `Chip`. Reorder `CategoryPlayerPanel` so its `LabelTile` sits at the bottom. Frontend-only.

**Tech Stack:** React 19, TypeScript, Mantine 9, TanStack Query v5, react-i18next (EN-only), Vitest + Testing Library. pnpm; run frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-21-player-polish-design.md`

---

## File structure

**Changed**
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — staging gate (queue/Play/panel/mobile-redirect). (+test)
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` — `Button` → `Chip`. (+test, + panel test query fixes)
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — width 520, `LabelTile` below buttons. (+test)
- `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — move `LabelTile` to the bottom. (+test)

No backend/API/schema/router-config changes (the mobile redirect uses `<Navigate>`, not a route definition).

---

### Task 1: Restrict the triage player to staging buckets

**Files:**
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx`
- Test: `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`

- [ ] **Step 1: Add the failing test (technical bucket hides Play)**

The existing integration test mocks `usePlayback` and has `inProgressBlock` with `bk1` (NEW, technical) and `bk3` (STAGING). Add a test asserting a technical bucket renders NO per-row Play buttons, and (contrast) a staging bucket does. Append inside the `describe('BucketDetailPage integration', ...)`:

```tsx
  it('hides per-row Play on a technical bucket', async () => {
    const playable = { ...track('t1'), spotify_id: 'sp-t1' };
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [playable], total: 1, limit: 50, offset: 0 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    expect(screen.queryByRole('button', { name: /Play track/i })).not.toBeInTheDocument();
  });

  it('shows per-row Play on a staging bucket', async () => {
    const playable = { ...track('t1'), spotify_id: 'sp-t1' };
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk3/tracks', () =>
        HttpResponse.json({ items: [playable], total: 1, limit: 50, offset: 0 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk3');
    expect(await screen.findByRole('button', { name: /Play track/i })).toBeInTheDocument();
  });
```

(`track(id)` is the existing fixture; it titles tracks `Track ${id}`. If the existing "plays a track" test already covers the staging case, the second test is a light reaffirmation — keep it, it documents the contrast.)

- [ ] **Step 2: Run tests to verify the new technical-bucket test fails**

From `frontend/`: `pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`
Expected: the "hides per-row Play on a technical bucket" test FAILS (Play buttons currently render on all buckets).

- [ ] **Step 3: Implement the staging gate**

Edit `frontend/src/features/triage/routes/BucketDetailPage.tsx`:

1. Add a type import (with the existing imports near the top):
```tsx
import type { PlaybackTrack } from '../../playback/lib/types';
```

2. Add a module-level constant (after the imports, before `export function BucketDetailPage`):
```tsx
const EMPTY_TRACKS: PlaybackTrack[] = [];
```

3. In `BucketDetailInner`, derive `isStagingBucket` from the block, placed right before the `// Playback wiring` comment (after the `useState`/`useBucketTracks` lines, ~line 59):
```tsx
  const isStagingBucket =
    block?.buckets.find((b) => b.id === bucketId)?.bucket_type === 'STAGING';
```

4. Change the queue binding (currently `useBucketPlayerQueue(blockId, bucketId, playerTracks);`):
```tsx
  useBucketPlayerQueue(blockId, bucketId, isStagingBucket ? playerTracks : EMPTY_TRACKS);
```

5. In `playTrack`, add a guard as the FIRST line of the callback body and add `isStagingBucket` to the dependency array:
```tsx
  const playTrack = useCallback(
    (tr: BucketTrack) => {
      if (!isStagingBucket) return;
      if (!tr.spotify_id) return;
      void playback.controls.prewarm();
      const queueIdx = playback.queue.tracks.findIndex((q) => q.id === tr.track_id);
      if (queueIdx >= 0) {
        void playback.controls.play(queueIdx);
      } else {
        void playback.controls.play(undefined, toPlaybackTrack(tr));
      }
      if (!isDesktop) {
        navigate(`/triage/${styleId}/${blockId}/buckets/${bucketId}/player`);
      }
    },
    [isStagingBucket, playback.controls, playback.queue.tracks, isDesktop, navigate, styleId, blockId, bucketId],
  );
```

6. Update the mobile player outlet short-circuit (currently the `if (onPlayerSubpath) { return <Outlet ... />; }` block, ~line 142). Redirect technical buckets back to their detail page:
```tsx
  if (onPlayerSubpath) {
    if (!isStagingBucket) {
      return (
        <Navigate to={`/triage/${styleId}/${blockId}/buckets/${bucketId}`} replace />
      );
    }
    return (
      <Outlet context={{ items: playerItems } satisfies BucketDetailOutletContext} />
    );
  }
```

7. In the `const tracksList = (...)` element, gate the play props:
```tsx
      onPlay={isStagingBucket ? playTrack : undefined}
      currentTrackId={isStagingBucket ? (playback.track.current?.id ?? null) : null}
```

8. Change the desktop-split render branch (currently `{isDesktop ? (<Flex>…panel…{tracksList}</Flex>) : (tracksList)}`) so the panel only shows for staging buckets:
```tsx
      {isDesktop && isStagingBucket ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <BucketPlayerPanel blockId={blockId} bucketId={bucketId} items={playerItems} />
          <div style={{ flex: 1, minWidth: 0 }}>{tracksList}</div>
        </Flex>
      ) : (
        tracksList
      )}
```

- [ ] **Step 4: Run the integration tests**

From `frontend/`: `pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`
Expected: PASS — new technical-bucket test passes; the existing "plays a track" (bk3 staging) test still passes.

- [ ] **Step 5: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: no errors (2 pre-existing warnings in `useCurateSession.ts` + `theme.ts` are OK).

- [ ] **Step 6: Commit**

NO `Co-Authored-By` trailer (pre-commit hook rejects it).
```bash
git add frontend/src/features/triage/routes/BucketDetailPage.tsx frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
git commit -m "feat(triage): restrict bucket player to staging buckets"
```

---

### Task 2: `BucketDistributeButtons` → Chip style

Convert the distribution buttons from `Button` to `Chip` (mirroring the category playlist/tag clouds). Fix the affected queries in both the component test and the panel test so the suite stays green.

**Files:**
- Modify: `frontend/src/features/triage/components/BucketDistributeButtons.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`

- [ ] **Step 1: Update the `BucketDistributeButtons` test to chip-friendly queries**

Mantine `Chip` renders a hidden `<input>` + a `<label>`; the role is not `button`. Query by text and click the label. Replace the first two tests' body in `BucketDistributeButtons.test.tsx` (keep the empty-state test as-is):

```tsx
  it('renders a chip per destination with bucket labels', () => {
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={vi.fn()} />);
    expect(screen.getByText('Move current track to')).toBeInTheDocument();
    expect(screen.getByText('Techno')).toBeInTheDocument();
    expect(screen.getByText('DISCARD')).toBeInTheDocument();
  });

  it('calls onDistribute with the bucket id on click', async () => {
    const onDistribute = vi.fn();
    r(<BucketDistributeButtons destinations={[staging, discard]} onDistribute={onDistribute} />);
    await userEvent.click(screen.getByText('Techno'));
    expect(onDistribute).toHaveBeenCalledWith('bk2');
  });
```

- [ ] **Step 2: Run to verify the click test fails**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: the current implementation still uses `Button`; the text-based render test passes but you are about to change the impl. (If you prefer strict red-green: this step mainly re-baselines the queries — proceed to impl.)

- [ ] **Step 3: Convert the component to `Chip`**

Replace the entire body of `frontend/src/features/triage/components/BucketDistributeButtons.tsx`:

```tsx
import { Chip, Group, Stack, Text } from '@mantine/core';
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
      <Group gap="xs" wrap="wrap">
        {destinations.map((b) => (
          <Chip
            key={b.id}
            checked={false}
            size="sm"
            variant="outline"
            color={b.bucket_type === 'DISCARD' ? 'red' : undefined}
            onChange={() => onDistribute(b.id)}
          >
            {bucketLabel(b, t)}
          </Chip>
        ))}
      </Group>
    </Stack>
  );
}
```

(`checked={false}` keeps every chip in the unchecked state — distribution is a one-shot action, not a membership toggle. `onChange` fires on tap.)

- [ ] **Step 4: Run the component test**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Fix the panel test's button-role queries**

`BucketPlayerPanel.test.tsx` queries the distribute buttons by `role: 'button'`, which no longer matches a `Chip`. READ the file, then change every distribute-chip query from button-role to text:
- `screen.getByRole('button', { name: 'Techno' })` → `screen.getByText('Techno')`
- `screen.getByRole('button', { name: 'DISCARD' })` → `screen.getByText('DISCARD')`
- `screen.queryByRole('button', { name: 'NEW' })` → `screen.queryByText('NEW')`
- `screen.queryByRole('button', { name: 'Cur' })` → `screen.queryByText('Cur')`
- the click `userEvent.click(screen.getByRole('button', { name: 'Techno' }))` → `userEvent.click(screen.getByText('Techno'))`

Leave the player-control assertions (PlayerCard's real `<button>`s like play/pause) untouched — only the distribute-destination queries change.

- [ ] **Step 6: Run the panel test**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: PASS (existing 6 tests, now chip-query-based).

- [ ] **Step 7: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/triage/components/BucketDistributeButtons.tsx frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx
git commit -m "feat(triage): use chip style for bucket distribution buttons"
```

---

### Task 3: `BucketPlayerPanel` width 520 + LabelTile below buttons

**Files:**
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`

- [ ] **Step 1: Add the failing test (LabelTile below buttons)**

In `BucketPlayerPanel.test.tsx`, mock `LabelTile` to a marker so the test stays provider-light (LabelTile uses `useLabelInfo`, a `useQuery`). Add this `vi.mock` near the other mocks at the top (BEFORE `import { BucketPlayerPanel }`):

```tsx
vi.mock('../../../library/components/LabelTile', () => ({
  LabelTile: () => <div data-testid="label-tile" />,
}));
```

Then add a test inside `describe('BucketPlayerPanel', ...)`:

```tsx
  it('renders the LabelTile after the distribute buttons when playing', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    const heading = screen.getByText('Move current track to');
    const labelTile = screen.getByTestId('label-tile');
    expect(
      heading.compareDocumentPosition(labelTile) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
```

(`item` and `current` are existing fixtures in the file; the default `mockBlock` is IN_PROGRESS with destinations, so the buttons render.)

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: FAIL — `label-tile` testid not found (LabelTile not rendered yet).

- [ ] **Step 3: Add LabelTile + width to the panel**

Edit `frontend/src/features/triage/components/BucketPlayerPanel.tsx`:

1. Add the import (with the other imports):
```tsx
import { LabelTile } from '../../library/components/LabelTile';
```

2. Change BOTH `<Stack>` roots (the empty-state branch and the playing branch) width style from `{ minWidth: 0, flex: '0 0 360px', maxWidth: 360 }` to:
```tsx
style={{ width: 520, flexShrink: 0, minWidth: 0 }}
```

3. In the playing-state `<Stack>`, after `<BucketDistributeButtons ... />`, add the LabelTile as the last child:
```tsx
      <BucketDistributeButtons destinations={destinations} onDistribute={distribute} />
      <LabelTile
        labelId={effectiveRich?.label_id ?? null}
        labelName={effectiveRich?.label_name ?? null}
        styleId={block?.style_id ?? ''}
      />
```

(`effectiveRich` is the rich `BucketTrack` already computed in the panel; it carries `label_id`/`label_name`. `block` is from the existing `useTriageBlock(blockId)`. `LabelTile` returns null when `labelId` is falsy, so no label → nothing renders.)

- [ ] **Step 4: Run the panel test**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: PASS (existing tests + the new order test).

- [ ] **Step 5: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx
git commit -m "feat(triage): widen bucket player and show LabelTile below buttons"
```

---

### Task 4: `CategoryPlayerPanel` — move LabelTile to the bottom

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Test: `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`

- [ ] **Step 1: Add the failing order test**

In `CategoryPlayerPanel.test.tsx`:

1. Mock `LabelTile` to a marker (add near the other `vi.mock`s, before `import { CategoryPlayerPanel }`):
```tsx
vi.mock('../../../library/components/LabelTile', () => ({
  LabelTile: () => <div data-testid="label-tile" />,
}));
```

2. Make the `ui()` helper accept items (it currently hardcodes `items={[]}`):
```tsx
function ui(items: CategoryTrack[] = []) {
  const qc = new QueryClient();
  return (
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <Notifications />
        <CategoryPlayerPanel categoryId="c1" styleId="s1" items={items} />
      </MantineProvider>
    </QueryClientProvider>
  );
}
```
Add the import: `import type { CategoryTrack } from '../../hooks/useCategoryTracks';`

3. Add a labeled-track fixture + the order test:
```tsx
const labeledTrack: CategoryTrack = {
  id: 't1', title: 'X', mix_name: null, artists: [{ id: 'a1', name: 'A' }],
  label: { id: 'lbl1', name: 'L' }, bpm: 120, length_ms: 200000,
  publish_date: null, spotify_release_date: null, isrc: null,
  spotify_id: 'sp1', release_type: null, is_ai_suspected: false,
  used_in_playlist: false, added_at: '2026-01-01T00:00:00Z',
  source_triage_block_id: null, tags: [],
};

it('renders the LabelTile after the playlists section', () => {
  render(ui([labeledTrack]));
  const playlistsHeading = screen.getByText('Playlists');
  const labelTile = screen.getByTestId('label-tile');
  expect(
    playlistsHeading.compareDocumentPosition(labelTile) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});
```

(The mocked `usePlayback` already sets `track.current.id = 't1'`; passing `labeledTrack` as items makes `effectiveRich.label.id` truthy so the panel renders the LabelTile. `'Playlists'` is the rendered `category_player.sections.playlists` heading.)

- [ ] **Step 2: Run to verify it fails**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: FAIL — currently the LabelTile renders ABOVE the playlists section, so it does NOT follow the playlists heading.

- [ ] **Step 3: Move the LabelTile to the bottom**

In `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`, the return currently is (roughly):
```tsx
    <Stack className={classes.root} gap="md">
      <PlayerCard ... />
      {effectiveRich?.label?.id && (
        <LabelTile labelId={effectiveRich.label.id} labelName={effectiveRich.label.name ?? null} styleId={styleId} />
      )}
      <Divider />
      <Text fw={500} size="sm">{t('category_player.sections.tags')}</Text>
      <PlayerPanelTagCloud ... />
      <Divider />
      <Text fw={500} size="sm">{t('category_player.sections.playlists')}</Text>
      <PlayerPanelPlaylistCloud ... />
    </Stack>
```
DELETE the `{effectiveRich?.label?.id && (<LabelTile ... />)}` block from its position after `<PlayerCard>`, and RE-ADD the identical block as the LAST child, after `<PlayerPanelPlaylistCloud ... />`:
```tsx
      <Text fw={500} size="sm">{t('category_player.sections.playlists')}</Text>
      <PlayerPanelPlaylistCloud ... />
      {effectiveRich?.label?.id && (
        <LabelTile
          labelId={effectiveRich.label.id}
          labelName={effectiveRich.label.name ?? null}
          styleId={styleId}
        />
      )}
    </Stack>
```
Keep the exact prop values from the original block. No other change.

- [ ] **Step 4: Run the categories test**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: PASS (existing tests + the new order test).

- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/categories/components/CategoryPlayerPanel.tsx frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx
git commit -m "feat(categories): move player LabelTile below the chip clouds"
```

---

### Task 5: Full verification

- [ ] **Step 1: Run the whole frontend suite**

From `frontend/`: `pnpm test`
Expected: all tests pass.

- [ ] **Step 2: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: clean (only the 2 pre-existing warnings).

- [ ] **Step 3: Manual smoke test (golden path)**

Start `pnpm dev` from `frontend/` (needs `frontend/.env.local` with `VITE_API_BASE_URL`). Then:
- Open an IN_PROGRESS triage block → open a **technical** bucket (NEW): no player panel, no per-row Play buttons; the "Curate from bucket" button still works.
- Open a **staging category** bucket: the player panel shows at ~520px (same width as the categories player), distribution buttons are Chips below the track controls, and the LabelTile renders below the chips. Tap a chip → track moves + next plays.
- Mobile width: Play opens the fullscreen player (staging only); manually visiting a technical bucket's `/player` URL redirects back to the bucket detail.
- Open the general categories player (`/categories/:styleId/:id`): the LabelTile now sits at the bottom, below the playlists section; tags/playlists still work.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** staging gate — queue/Play/panel/mobile-redirect (Task 1); width 520 (Task 3); Chip style (Task 2); triage LabelTile below buttons (Task 3); categories LabelTile to bottom (Task 4); both players → controls → buttons → label (Tasks 3+4). No backend/router-config change.
- **Cross-task test integrity:** Task 2 changes `BucketDistributeButtons` to `Chip`, which breaks the panel test's `getByRole('button', …)` distribute queries — Task 2 fixes those same-task so the suite stays green before Task 3 touches the panel test again.
- **Type/name consistency:** `EMPTY_TRACKS: PlaybackTrack[]`; `isStagingBucket` derived once and reused; `LabelTile` props `{ labelId, labelName, styleId }` match the library component; `effectiveRich.label_id`/`label_name` are `BucketTrack` fields (triage), `effectiveRich.label.id`/`.name` are `CategoryTrack` fields (categories) — correctly distinct per panel.
- **Placeholder scan:** none.
- **Deviation:** width uses an inline style (`{ width: 520, flexShrink: 0, minWidth: 0 }`) rather than a new CSS module — simpler, testable, and sufficient for size parity; the category module additionally sets padding/border-right/overflow for its full-height sidebar context, which the triage split layout supplies separately.

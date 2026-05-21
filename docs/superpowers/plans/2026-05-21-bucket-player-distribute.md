# Bucket Player Quick-Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lean Curate-style destination buttons to the bucket player so a user can tap a staging category (or DISCARD) to move the currently-playing track there and auto-advance.

**Architecture:** A new presentational `BucketDistributeButtons` + a `useBucketDistribute` hook (optimistic move via the existing `useMoveTracks` + undo-toast + play-the-successor). `BucketPlayerPanel` self-fetches the block via `useTriageBlock` (cache hit), derives destinations, and renders the buttons when the block is `IN_PROGRESS` and a track is playing. Frontend-only; reuses the existing `POST /triage/blocks/{id}/move` endpoint.

**Tech Stack:** React 19, TypeScript, Mantine 9, TanStack Query v5, react-i18next (EN-only), Vitest + Testing Library. pnpm; run frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-21-bucket-player-distribute-design.md`

---

## File structure

**New**
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` — presentational destination button grid (+ test).
- `frontend/src/features/triage/hooks/useBucketDistribute.tsx` — move-current-track-and-advance hook (+ test). `.tsx` because the success toast builds JSX (inline Undo).

**Changed**
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — fetch block, compute destinations, render buttons; update its test (mock `useTriageBlock` + `useBucketDistribute`).
- `frontend/src/i18n/en.json` — distribute heading key.

**Reused (no change):** `useMoveTracks` (`takeSnapshot`/`undoMoveDirect`/`MoveInput`/`MoveSnapshot`), `bucketLabel`/`moveDestinationsFor` (`lib/bucketLabels.ts`), `useTriageBlock`, `usePlayback`.

**Test boundary note:** distribution is covered by three focused tests — the `useBucketDistribute` hook test (move input + successor advance), the `BucketDistributeButtons` component test (rendering + click), and the `BucketPlayerPanel` test (gating + wiring with the hook mocked). A page-level integration test in `BucketDetailPage` is intentionally NOT added: in jsdom `useMediaQuery` is falsy so the panel renders only on the mobile `/player` route (stubbed in that test), making a DOM-level distribution assertion there brittle. The component+hook tests cover the full wiring.

---

### Task 1: i18n key

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add `distribute.heading` under `triage.bucket_player`**

Find the existing `"bucket_player"` object under `"triage"` (it has `empty`, `back_aria`, `open_in_spotify_aria`). Add a `distribute` block:

```json
"open_in_spotify_aria": "Open {{title}} in Spotify (new tab)",
"distribute": {
  "heading": "Move current track to"
}
```

(Place the comma correctly — `open_in_spotify_aria` is currently the last key in `bucket_player`, so it gains a trailing comma and `distribute` follows.)

- [ ] **Step 2: Verify JSON parses**

Run from the worktree root: `node -e "const e=require('./frontend/src/i18n/en.json'); console.log(e.triage.bucket_player.distribute.heading)"`
Expected: prints `Move current track to`.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(triage): add i18n key for bucket player distribution"
```

---

### Task 2: `BucketDistributeButtons` component

A presentational grid of destination buttons. The caller passes a pre-filtered `destinations` list.

**Files:**
- Create: `frontend/src/features/triage/components/BucketDistributeButtons.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { BucketDistributeButtons } from '../BucketDistributeButtons';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const staging: TriageBucket = {
  id: 'bk2', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Techno',
  inactive: false, track_count: 0,
};
const discard: TriageBucket = {
  id: 'disc', bucket_type: 'DISCARD', category_id: null, category_name: null,
  inactive: false, track_count: 0,
};

describe('BucketDistributeButtons', () => {
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

  it('renders nothing when there are no destinations', () => {
    const { container } = r(<BucketDistributeButtons destinations={[]} onDistribute={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: FAIL — cannot resolve `../BucketDistributeButtons`.

- [ ] **Step 3: Write the component**

`frontend/src/features/triage/components/BucketDistributeButtons.tsx`:

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

- [ ] **Step 4: Run test to verify it passes**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/triage/components/BucketDistributeButtons.tsx frontend/src/features/triage/components/__tests__/BucketDistributeButtons.test.tsx
git commit -m "feat(triage): add BucketDistributeButtons component"
```

(NO `Co-Authored-By` trailer — a pre-commit hook rejects it.)

---

### Task 3: `useBucketDistribute` hook

Move the currently-playing track to a destination bucket (optimistic move + undo toast), then play the successor.

**Files:**
- Create: `frontend/src/features/triage/hooks/useBucketDistribute.tsx`
- Test: `frontend/src/features/triage/hooks/__tests__/useBucketDistribute.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/triage/hooks/__tests__/useBucketDistribute.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PlaybackTrack } from '../../../playback/lib/types';
import type { TriageBucket } from '../../lib/bucketLabels';

const moveMutate = vi.fn();
const playSpy = vi.fn();
let current: PlaybackTrack | null = null;
let queueTracks: PlaybackTrack[] = [];

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    track: { current, positionMs: 0, durationMs: 0 },
    queue: { source: null, tracks: queueTracks, cursor: 0, status: 'playing' },
    controls: { play: playSpy },
  }),
}));

vi.mock('../useMoveTracks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../useMoveTracks')>();
  return {
    ...actual,
    useMoveTracks: () => ({ mutate: moveMutate, isPending: false }),
  };
});

import { useBucketDistribute } from '../useBucketDistribute';

const T = (id: string): PlaybackTrack => ({
  id, title: id, artists: '', cover_url: null, duration_ms: 0, spotify_id: `sp-${id}`,
});

const buckets: TriageBucket[] = [
  { id: 'bk1', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Cur', inactive: false, track_count: 1 },
  { id: 'dst', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Dst', inactive: false, track_count: 0 },
];

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderDistribute() {
  const { result } = renderHook(
    () => useBucketDistribute({ blockId: 'b1', bucketId: 'bk1', styleId: 's1', buckets }),
    { wrapper },
  );
  return result;
}

beforeEach(() => {
  moveMutate.mockReset();
  playSpy.mockReset();
  current = null;
  queueTracks = [];
});

describe('useBucketDistribute', () => {
  it('moves the current track and plays the successor', () => {
    current = T('t1');
    queueTracks = [T('t1'), T('t2'), T('t3')];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).toHaveBeenCalledTimes(1);
    expect(moveMutate.mock.calls[0][0]).toEqual({
      fromBucketId: 'bk1', toBucketId: 'dst', trackIds: ['t1'],
    });
    expect(playSpy).toHaveBeenCalledWith(undefined, queueTracks[1]);
  });

  it('is a no-op when nothing is playing', () => {
    current = null;
    queueTracks = [];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).not.toHaveBeenCalled();
    expect(playSpy).not.toHaveBeenCalled();
  });

  it('moves but does not advance when the current track is last', () => {
    current = T('t3');
    queueTracks = [T('t1'), T('t2'), T('t3')];
    const distribute = renderDistribute();
    distribute.current('dst');
    expect(moveMutate).toHaveBeenCalledTimes(1);
    expect(playSpy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

From `frontend/`: `pnpm test src/features/triage/hooks/__tests__/useBucketDistribute.test.tsx`
Expected: FAIL — cannot resolve `../useBucketDistribute`.

- [ ] **Step 3: Write the hook**

`frontend/src/features/triage/hooks/useBucketDistribute.tsx`:

```tsx
import { useCallback, useRef } from 'react';
import { Anchor, Group, Text } from '@mantine/core';
import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { usePlayback } from '../../playback/usePlayback';
import {
  takeSnapshot,
  undoMoveDirect,
  useMoveTracks,
  type MoveInput,
  type MoveSnapshot,
} from './useMoveTracks';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface UseBucketDistributeArgs {
  blockId: string;
  bucketId: string;
  styleId: string;
  /** Block buckets — used to label the destination in the success toast. */
  buckets: TriageBucket[];
}

/**
 * Move the currently-playing track from `bucketId` into `toBucketId`
 * (optimistic, with an Undo toast) and immediately play the next queued track.
 * No-op when nothing is playing. Undo restores the track to the bucket but does
 * not rewind playback (lean — unlike the full Curate undo).
 */
export function useBucketDistribute({
  blockId,
  bucketId,
  styleId,
  buckets,
}: UseBucketDistributeArgs): (toBucketId: string) => void {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const playback = usePlayback();
  const move = useMoveTracks(blockId, styleId);
  const undoInflight = useRef(false);

  return useCallback(
    (toBucketId: string) => {
      const current = playback.track.current;
      if (!current) return;
      const tracks = playback.queue.tracks;
      const idx = tracks.findIndex((q) => q.id === current.id);
      const successor = idx >= 0 ? tracks[idx + 1] ?? null : null;
      const toBucket = buckets.find((b) => b.id === toBucketId);

      const input: MoveInput = {
        fromBucketId: bucketId,
        toBucketId,
        trackIds: [current.id],
      };
      const snapshot: MoveSnapshot = takeSnapshot(qc, blockId, bucketId);

      move.mutate(input, {
        onSuccess: () => {
          const toastId = `bucket-distribute-${Date.now()}-${current.id}`;
          notifications.show({
            id: toastId,
            color: 'green',
            autoClose: 5000,
            message: (
              <Group justify="space-between" gap="md">
                <Text size="sm">
                  {t('triage.move.toast.moved', {
                    count: 1,
                    to: toBucket ? bucketLabel(toBucket, t) : '',
                  })}
                </Text>
                <Anchor
                  component="button"
                  onClick={async () => {
                    if (undoInflight.current || move.isPending) return;
                    undoInflight.current = true;
                    notifications.hide(toastId);
                    try {
                      await undoMoveDirect(qc, blockId, styleId, input, snapshot);
                      notifications.show({
                        message: t('triage.move.toast.undone'),
                        color: 'green',
                      });
                    } catch {
                      notifications.show({
                        message: t('triage.move.toast.undo_failed'),
                        color: 'red',
                      });
                    } finally {
                      undoInflight.current = false;
                    }
                  }}
                >
                  {t('triage.move.toast.undo_action')}
                </Anchor>
              </Group>
            ),
          });
        },
        onError: (err) => {
          const code = err instanceof ApiError ? err.code : 'unknown';
          let messageKey = 'triage.move.toast.error';
          if (code === 'target_bucket_inactive' || code === 'invalid_state') {
            messageKey = 'triage.move.toast.invalid_target';
          } else if (
            code === 'triage_block_not_found' ||
            code === 'bucket_not_found' ||
            code === 'tracks_not_in_source'
          ) {
            messageKey = 'triage.move.toast.stale_state';
          }
          notifications.show({ message: t(messageKey), color: 'red' });
        },
      });

      if (successor) {
        void playback.controls.play(undefined, successor);
      }
    },
    [playback, buckets, bucketId, blockId, styleId, qc, move, t],
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

From `frontend/`: `pnpm test src/features/triage/hooks/__tests__/useBucketDistribute.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Typecheck + commit**

```bash
cd frontend && pnpm typecheck && cd ..
git add frontend/src/features/triage/hooks/useBucketDistribute.tsx frontend/src/features/triage/hooks/__tests__/useBucketDistribute.test.tsx
git commit -m "feat(triage): add useBucketDistribute hook"
```

---

### Task 4: Wire distribution into `BucketPlayerPanel`

**Files:**
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`

- [ ] **Step 1: Update the panel test first (mock the new deps + add gating tests)**

The panel will now call `useTriageBlock(blockId)` (a `useQuery`) and `useBucketDistribute`. Mock both so the panel tests stay provider-light. READ the current test file, then apply these edits:

1. Add a mutable mock block + a distribute spy near the top, and the two `vi.mock` calls (place them with the existing `vi.mock('../../../playback/usePlayback', ...)`, BEFORE the `import { BucketPlayerPanel }` line):

```tsx
import type { TriageBlock } from '../../hooks/useTriageBlock';

const distributeSpy = vi.fn();
let mockBlock: TriageBlock | undefined;

vi.mock('../../hooks/useTriageBlock', () => ({
  useTriageBlock: () => ({ data: mockBlock }),
}));
vi.mock('../../hooks/useBucketDistribute', () => ({
  useBucketDistribute: () => distributeSpy,
}));
```

2. In `beforeEach`, reset the spy and set a default IN_PROGRESS block whose current bucket is `bk1`:

```tsx
beforeEach(() => {
  togglePlayPause.mockReset();
  distributeSpy.mockReset();
  current = null;
  mockBlock = {
    id: 'b1', style_id: 's1', style_name: 'House', name: 'W1',
    date_from: '2026-01-01', date_to: '2026-01-07', status: 'IN_PROGRESS',
    created_at: '', updated_at: '', finalized_at: null,
    buckets: [
      { id: 'bk1', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Cur', inactive: false, track_count: 1 },
      { id: 'bk2', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Techno', inactive: false, track_count: 0 },
      { id: 'disc', bucket_type: 'DISCARD', category_id: null, category_name: null, inactive: false, track_count: 0 },
      { id: 'nw', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    ],
  };
});
```

(The three existing tests — empty state, current track + meta, stale-meta — keep working: `useTriageBlock` is mocked so no provider is needed, and the distribute hook is a no-op spy.)

3. Add new tests at the end of the `describe`:

```tsx
  it('shows distribute buttons for staging + DISCARD (not technical) when IN_PROGRESS and playing', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText('Move current track to')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Techno' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'DISCARD' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'NEW' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Cur' })).not.toBeInTheDocument();
  });

  it('hides distribute buttons when the block is FINALIZED', () => {
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    mockBlock = { ...mockBlock!, status: 'FINALIZED' };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.queryByText('Move current track to')).not.toBeInTheDocument();
  });

  it('calls distribute with the destination bucket id on tap', async () => {
    const userEvent = (await import('@testing-library/user-event')).default;
    current = { id: 't1', title: 'Test Track', artists: 'A', duration_ms: 1, spotify_id: 'sp1', cover_url: null };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    await userEvent.click(screen.getByRole('button', { name: 'Techno' }));
    expect(distributeSpy).toHaveBeenCalledWith('bk2');
  });
```

- [ ] **Step 2: Run tests to verify the new ones fail**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: the 3 new tests FAIL (no distribute buttons yet); the 3 existing tests should still pass once the `useTriageBlock` mock is in place. (If the existing tests error on a missing `useTriageBlock` mock, that confirms the mock is required — it's added in Step 1.)

- [ ] **Step 3: Wire the panel**

Edit `frontend/src/features/triage/components/BucketPlayerPanel.tsx`:

1. Add imports:

```tsx
import { useTriageBlock } from '../hooks/useTriageBlock';
import { useBucketDistribute } from '../hooks/useBucketDistribute';
import { BucketDistributeButtons } from './BucketDistributeButtons';
import { moveDestinationsFor } from '../lib/bucketLabels';
```

2. Update the props destructure to use `blockId` and `bucketId`, and drop the "reserved" comment on the interface:

```tsx
export interface BucketPlayerPanelProps {
  blockId: string;
  bucketId: string;
  /** Visible bucket tracks, used to look up label/BPM for the playing track. */
  items: BucketTrack[];
}

export function BucketPlayerPanel({ blockId, bucketId, items }: BucketPlayerPanelProps) {
```

3. Inside the component, ABOVE the early `if (!current)` return (Rules of Hooks — `useTriageBlock` and `useBucketDistribute` are hooks), add:

```tsx
  const { data: block } = useTriageBlock(blockId);
  const blockBuckets = block?.buckets ?? [];
  const distribute = useBucketDistribute({
    blockId,
    bucketId,
    styleId: block?.style_id ?? '',
    buckets: blockBuckets,
  });
  const destinations =
    block?.status === 'IN_PROGRESS'
      ? moveDestinationsFor(blockBuckets, bucketId).filter(
          (b) => b.bucket_type === 'STAGING' || b.bucket_type === 'DISCARD',
        )
      : [];
```

Place these near the other hook calls (e.g. right after `const current = playback.track.current;` and before the `useMemo`/`useEffect` block, or anywhere above the early return — just keep all hooks unconditional).

4. In the playing `return (...)` (the `<Stack>` that contains `<PlayerCard .../>`), add the buttons as the last child, after `</PlayerCard>`:

```tsx
      <PlayerCard
        ...
      />
      <BucketDistributeButtons destinations={destinations} onDistribute={distribute} />
    </Stack>
```

- [ ] **Step 4: Run the panel tests**

From `frontend/`: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: PASS (3 existing + 3 new = 6).

- [ ] **Step 5: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: no errors (2 pre-existing warnings in `useCurateSession.ts` + `theme.ts` are OK).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx
git commit -m "feat(triage): distribute current track from the bucket player"
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
- Open an IN_PROGRESS triage block → open a staging bucket with playable tracks → Play a track.
- Confirm the destination buttons appear below the player: other staging categories + DISCARD, NOT the current bucket, NOT NEW/OLD/NOT.
- Tap a destination → the track moves out, the next track starts playing, a green toast with "Undo" appears; tapping Undo restores the track to the bucket (playback stays on the advanced track).
- Open a FINALIZED block's bucket → confirm NO distribute buttons.
- Confirm the existing row move-menu, transfer, and player controls still work.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** lean buttons (Task 2); move-current+advance hook (Task 3); panel gating on IN_PROGRESS + current, destinations = staging + DISCARD via `moveDestinationsFor` filter, self-fetch block, mobile route inherits it (Task 4); i18n (Task 1); auto-advance via `play(undefined, successor)` (Task 3); undo toast mirrors `handleMove`; no backend/router change. 
- **Deviations from spec:** (1) `useBucketDistribute` takes an extra `buckets` arg so the success toast can label the destination — the spec's signature omitted it. (2) Destinations reuse the existing `moveDestinationsFor` helper (which also drops inactive staging) then filter to STAGING/DISCARD, rather than an inline filter. (3) The page-level `BucketDetailPage` integration test is replaced by the hook + button + panel tests (jsdom media-query renders the panel only on the stubbed mobile `/player` route, making a DOM distribution assertion there brittle). All three are noted in the File-structure test boundary section.
- **Type consistency:** `useBucketDistribute({ blockId, bucketId, styleId, buckets })` returns `(toBucketId: string) => void`; `BucketDistributeButtons` `onDistribute: (toBucketId: string) => void` matches; `MoveInput` shape `{ fromBucketId, toBucketId, trackIds }` matches `useMoveTracks`. `bucketLabel`/`moveDestinationsFor`/`TriageBucket` imported from `lib/bucketLabels`.
- **Placeholder scan:** none.

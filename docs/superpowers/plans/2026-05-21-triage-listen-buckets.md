# Triage — Listen to Bucket Tracks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add audio playback to the triage bucket-detail view so a user can audition the tracks in any bucket (staging + technical) before finalizing a triage block.

**Architecture:** Mirror the existing category listen UX. The bucket-detail page binds its visible (search-filtered) track list to the global `PlaybackProvider` singleton queue via a new `useBucketPlayerQueue` hook (queue `source` type `bucket` already exists). Each track row gets a Play button; a lean `BucketPlayerPanel` renders the shared `PlayerCard`. Desktop shows a split (panel + list); mobile pushes a nested fullscreen `/player` route. No backend, schema, or API changes.

**Tech Stack:** React 19, TypeScript, Mantine 9, TanStack Query v5, react-router, react-i18next (EN-only), Vitest + Testing Library + MSW. Package manager: pnpm. Run all frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-20-triage-listen-buckets-design.md`

---

## File structure

**New files**
- `frontend/src/features/triage/lib/toPlaybackTrack.ts` — map `BucketTrack` → `PlaybackTrack` (shared with curate).
- `frontend/src/features/triage/lib/__tests__/toPlaybackTrack.test.ts`
- `frontend/src/features/triage/hooks/useBucketPlayerQueue.ts` — bind bucket tracks to the global queue.
- `frontend/src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx`
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — lean player panel (PlayerCard, no tags/playlists).
- `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
- `frontend/src/features/triage/routes/BucketPlayerPage.tsx` — mobile fullscreen player route.

**Modified files**
- `frontend/src/i18n/en.json` — new keys.
- `frontend/src/features/curate/hooks/useCurateSession.ts` — import shared `toPlaybackTrack`.
- `frontend/src/features/triage/components/BucketTrackRow.tsx` — Play button + `isCurrent` highlight.
- `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx` — Play tests.
- `frontend/src/features/triage/components/BucketTracksList.tsx` — controlled search + `onPlay`/`currentTrackId` props.
- `frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx` — updated for controlled search.
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — own search state, bind queue, player layout, mobile nav.
- `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx` — mock `usePlayback`, player tests.
- `frontend/src/routes/router.tsx` — nested `player` route.

**Design decisions locked from the spec:** Play enabled on ALL bucket-detail pages (staging + technical). Mobile = fullscreen nested route (mirrors categories). Playback is read-only; works in any block status. EN-only i18n (no `ru.json` exists — confirmed in `frontend/src/i18n/index.ts`).

---

### Task 1: i18n keys

Add the strings every later component/test resolves. Doing this first means component tests can assert on real labels.

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add the `play_aria` / `play_unavailable` keys to `triage.tracks_table`**

Find the existing `"tracks_table"` object under `"triage"` (it currently ends with `"actions_header": "Actions"`). Add two keys:

```json
"actions_header": "Actions",
"play_aria": "Play track",
"play_unavailable": "No Spotify track available"
```

- [ ] **Step 2: Add a `bucket_player` block under `triage`**

Add a new sibling object inside `"triage"` (e.g. right after `"bucket"`):

```json
"bucket_player": {
  "empty": {
    "pick_track": "Pick a track to start playing"
  },
  "back_aria": "Back to tracks",
  "open_in_spotify_aria": "Open {{title}} in Spotify (new tab)"
}
```

- [ ] **Step 3: Verify JSON is valid**

Run: `node -e "require('./frontend/src/i18n/en.json'); console.log('ok')"`
Expected: prints `ok` (no parse error). Run from the repo root, or drop the `frontend/` prefix if your shell is already in `frontend/`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(triage): add i18n keys for bucket playback"
```

---

### Task 2: Shared `toPlaybackTrack` helper

Extract the `BucketTrack → PlaybackTrack` mapper (currently inlined in `useCurateSession`) so triage + curate share one copy.

**Files:**
- Create: `frontend/src/features/triage/lib/toPlaybackTrack.ts`
- Test: `frontend/src/features/triage/lib/__tests__/toPlaybackTrack.test.ts`
- Modify: `frontend/src/features/curate/hooks/useCurateSession.ts`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/triage/lib/__tests__/toPlaybackTrack.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { toPlaybackTrack } from '../toPlaybackTrack';
import type { BucketTrack } from '../../hooks/useBucketTracks';

const base: BucketTrack = {
  track_id: 't1',
  title: 'Title',
  mix_name: null,
  isrc: null,
  bpm: 128,
  length_ms: 200_000,
  publish_date: null,
  spotify_release_date: null,
  spotify_id: 'sp1',
  release_type: null,
  is_ai_suspected: false,
  artists: ['A', 'B'],
  label_id: null,
  label_name: null,
  added_at: '2026-01-01T00:00:00Z',
};

describe('toPlaybackTrack', () => {
  it('maps BucketTrack fields to PlaybackTrack', () => {
    expect(toPlaybackTrack(base)).toEqual({
      id: 't1',
      title: 'Title',
      artists: 'A, B',
      cover_url: null,
      duration_ms: 200_000,
      spotify_id: 'sp1',
    });
  });

  it('defaults duration to 0 when length_ms is null', () => {
    expect(toPlaybackTrack({ ...base, length_ms: null }).duration_ms).toBe(0);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/features/triage/lib/__tests__/toPlaybackTrack.test.ts`
Expected: FAIL — cannot resolve `../toPlaybackTrack`.

- [ ] **Step 3: Write the helper**

`frontend/src/features/triage/lib/toPlaybackTrack.ts`:

```ts
import type { BucketTrack } from '../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../playback/lib/types';

export function toPlaybackTrack(t: BucketTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.join(', '),
    cover_url: null,
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test src/features/triage/lib/__tests__/toPlaybackTrack.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 5: Refactor `useCurateSession` to use the shared helper**

In `frontend/src/features/curate/hooks/useCurateSession.ts`:

1. Delete the inline function (lines ~25-34):

```ts
function toPlaybackTrack(t: BucketTrack): PlaybackTrack {
  return {
    id: t.track_id,
    title: t.title,
    artists: t.artists.join(', '),
    cover_url: null,
    duration_ms: t.length_ms ?? 0,
    spotify_id: t.spotify_id,
  };
}
```

2. Add the import near the other triage imports at the top:

```ts
import { toPlaybackTrack } from '../../triage/lib/toPlaybackTrack';
```

3. The existing `import type { PlaybackTrack } from '../../playback/lib/types';` line is still used elsewhere in the file — leave it. If `tsc`/eslint reports `PlaybackTrack` as now-unused, remove that import line.

- [ ] **Step 6: Verify curate tests still pass + typecheck**

Run: `pnpm test src/features/curate && pnpm typecheck`
Expected: PASS; no type errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/triage/lib/toPlaybackTrack.ts \
        frontend/src/features/triage/lib/__tests__/toPlaybackTrack.test.ts \
        frontend/src/features/curate/hooks/useCurateSession.ts
git commit -m "refactor(triage): extract shared toPlaybackTrack helper"
```

---

### Task 3: `useBucketPlayerQueue` hook

Bind a bucket's visible tracks to the global queue with `source.type === 'bucket'`. Direct analogue of `useCategoryPlayerQueue` — same cursor-recompute/shrink logic.

**Files:**
- Create: `frontend/src/features/triage/hooks/useBucketPlayerQueue.ts`
- Test: `frontend/src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import { useBucketPlayerQueue } from '../useBucketPlayerQueue';
import type { PlaybackTrack } from '../../../playback/lib/types';

const bindQueue = vi.fn();
const clearQueue = vi.fn();
const playback = {
  controls: { bindQueue, clearQueue },
  queue: { source: null, tracks: [] as PlaybackTrack[], cursor: 0, status: 'idle' as const },
  track: { current: null as PlaybackTrack | null, positionMs: 0, durationMs: 0 },
  sdk: { ready: false, error: null },
  devices: undefined as never,
};

vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => playback,
}));

const T = (id: string): PlaybackTrack => ({
  id,
  title: `t-${id}`,
  artists: '',
  duration_ms: 200000,
  spotify_id: `sp-${id}`,
  cover_url: null,
});

beforeEach(() => {
  bindQueue.mockReset();
  clearQueue.mockReset();
  playback.queue.tracks = [];
  playback.queue.cursor = 0;
  playback.track.current = null;
});

describe('useBucketPlayerQueue', () => {
  it('binds queue on mount with a bucket source and cursor 0 when nothing playing', () => {
    const tracks = [T('a'), T('b'), T('c')];
    renderHook(() => useBucketPlayerQueue('blk-1', 'bk-1', tracks));
    expect(bindQueue).toHaveBeenCalledWith({
      source: { type: 'bucket', blockId: 'blk-1', bucketId: 'bk-1' },
      tracks,
      cursor: 0,
      onCursorChange: expect.any(Function),
    });
  });

  it('preserves the playing track id when the list identity changes', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 1;
    playback.track.current = T('b');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    const next = [T('a'), T('b'), T('c'), T('d')];
    rerender({ tracks: next });
    expect(bindQueue).toHaveBeenCalledWith(
      expect.objectContaining({ tracks: next, cursor: 1 }),
    );
  });

  it('cursor = -1 when the top track is removed (advance lands on new tracks[0])', () => {
    playback.queue.tracks = [T('a'), T('b'), T('c')];
    playback.queue.cursor = 0;
    playback.track.current = T('a');
    const { rerender } = renderHook(
      ({ tracks }) => useBucketPlayerQueue('blk-1', 'bk-1', tracks),
      { initialProps: { tracks: playback.queue.tracks as PlaybackTrack[] } },
    );
    bindQueue.mockReset();
    rerender({ tracks: [T('b'), T('c')] });
    expect(bindQueue).toHaveBeenCalledWith(expect.objectContaining({ cursor: -1 }));
  });

  it('calls clearQueue on unmount', () => {
    const { unmount } = renderHook(() =>
      useBucketPlayerQueue('blk-1', 'bk-1', [T('a')]),
    );
    unmount();
    expect(clearQueue).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx`
Expected: FAIL — cannot resolve `../useBucketPlayerQueue`.

- [ ] **Step 3: Write the hook**

`frontend/src/features/triage/hooks/useBucketPlayerQueue.ts`:

```ts
import { useEffect, useRef } from 'react';
import { usePlayback } from '../../playback/usePlayback';
import type { PlaybackTrack } from '../../playback/lib/types';

/**
 * Bind a bucket's track list to PlaybackProvider's singleton queue. Mirror of
 * useCategoryPlayerQueue: on every tracks-identity change recompute the cursor
 * (keep the playing track id if it still exists, else clamp using the same
 * shrink logic so a natural-end advance lands on the right successor). Unmount
 * clears the queue.
 */
export function useBucketPlayerQueue(
  blockId: string,
  bucketId: string,
  tracks: readonly PlaybackTrack[],
): void {
  const playback = usePlayback();
  const cursorRef = useRef(playback.queue.cursor);

  useEffect(() => {
    cursorRef.current = playback.queue.cursor;
  }, [playback.queue.cursor]);

  useEffect(() => {
    const currentId = playback.track.current?.id ?? null;
    let cursor = 0;
    if (currentId) {
      const idx = tracks.findIndex((t) => t.id === currentId);
      if (idx >= 0) {
        cursor = idx;
      } else {
        cursor = Math.max(-1, cursorRef.current - 1);
      }
    }
    playback.controls.bindQueue({
      source: { type: 'bucket', blockId, bucketId },
      tracks,
      cursor,
      onCursorChange: (next) => {
        cursorRef.current = next;
      },
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tracks, blockId, bucketId]);

  useEffect(() => {
    return () => {
      playback.controls.clearQueue();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/hooks/useBucketPlayerQueue.ts \
        frontend/src/features/triage/hooks/__tests__/useBucketPlayerQueue.test.tsx
git commit -m "feat(triage): add useBucketPlayerQueue hook"
```

---

### Task 4: `BucketTrackRow` Play button + current-row highlight

Add an optional Play affordance (mirrors the category `TrackRow`) and a `data-current` marker for the playing row. All existing props/behavior stay; new props are optional so existing call sites keep compiling.

**Files:**
- Modify: `frontend/src/features/triage/components/BucketTrackRow.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx`

- [ ] **Step 1: Write the failing tests (append to the existing file)**

Add these `it` blocks inside the existing `describe('BucketTrackRow desktop', ...)` in `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx`. They reuse the file's existing `r()` helper, `track`, and `buckets` fixtures (note: the existing `track` fixture has `spotify_id: null`).

```tsx
  it('renders an enabled Play button and calls onPlay when track has spotify_id', async () => {
    const onPlay = vi.fn();
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
            onPlay={onPlay}
          />
        </Table.Tbody>
      </Table>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Play track/i }));
    expect(onPlay).toHaveBeenCalledTimes(1);
  });

  it('disables the Play button when spotify_id is null', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
            onPlay={vi.fn()}
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByRole('button', { name: /Play track/i })).toBeDisabled();
  });

  it('marks the row data-current when isCurrent', () => {
    const { container } = r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
            onPlay={vi.fn()}
            isCurrent
          />
        </Table.Tbody>
      </Table>,
    );
    expect(container.querySelector('[data-current="true"]')).not.toBeNull();
  });

  it('renders no Play button when onPlay is omitted', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, spotify_id: 'sp1' }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.queryByRole('button', { name: /Play track/i })).not.toBeInTheDocument();
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pnpm test src/features/triage/components/__tests__/BucketTrackRow.test.tsx`
Expected: FAIL — no Play button rendered / `onPlay` prop not accepted.

- [ ] **Step 3: Implement the Play button + highlight**

Edit `frontend/src/features/triage/components/BucketTrackRow.tsx`:

1. Update the imports at the top:

```tsx
import { ActionIcon, Card, Group, Stack, Table, Text, Tooltip } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconAlertTriangle, IconPlayerPlayFilled } from '../../../components/icons';
```

> If `IconPlayerPlayFilled` is not re-exported from `../../../components/icons`, import it directly: `import { IconPlayerPlayFilled } from '@tabler/icons-react';` (that is the source the category `TrackRow` uses). Verify with: `grep -n "IconPlayerPlayFilled" frontend/src/components/icons.ts*`.

2. Extend the props interface:

```tsx
export interface BucketTrackRowProps {
  track: BucketTrack;
  variant: 'desktop' | 'mobile';
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  onTransfer?: () => void;
  showMoveMenu: boolean;
  blockStatus?: 'IN_PROGRESS' | 'FINALIZED';
  onPlay?: () => void;
  isCurrent?: boolean;
}
```

3. Destructure the new props:

```tsx
export function BucketTrackRow({
  track,
  variant,
  buckets,
  currentBucketId,
  onMove,
  onTransfer,
  showMoveMenu,
  blockStatus,
  onPlay,
  isCurrent,
}: BucketTrackRowProps) {
  const { t } = useTranslation();
```

4. Build the play button just after the `moveMenu` const:

```tsx
  const canPlay = !!onPlay && !!track.spotify_id;
  const playButton = onPlay ? (
    <Tooltip
      label={
        track.spotify_id
          ? t('triage.tracks_table.play_aria')
          : t('triage.tracks_table.play_unavailable')
      }
    >
      <ActionIcon
        variant="subtle"
        size="md"
        disabled={!canPlay}
        onClick={canPlay ? onPlay : undefined}
        aria-label={t('triage.tracks_table.play_aria')}
      >
        <IconPlayerPlayFilled size={16} />
      </ActionIcon>
    </Tooltip>
  ) : null;
```

5. In the **desktop** branch, add `data-current` to the row and `{playButton}` as the first child of the title cell's `Group`:

```tsx
    return (
      <Table.Tr data-current={isCurrent ? 'true' : undefined}>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
            {playButton}
            {aiBadge}
            <Stack gap={0}>
              <Text fw={500}>{track.title}</Text>
              {track.mix_name && (
                <Text size="xs" c="dimmed">
                  {track.mix_name}
                </Text>
              )}
            </Stack>
          </Group>
        </Table.Td>
```

(Leave the rest of the desktop row unchanged.)

6. In the **mobile** branch, add `data-current` to the `Card` and `{playButton}` as the first child of the title `Group`:

```tsx
  return (
    <Card withBorder padding="sm" data-current={isCurrent ? 'true' : undefined}>
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs">
            {playButton}
            {aiBadge}
            <Text fw={500}>{track.title}</Text>
          </Group>
          {moveMenu}
        </Group>
```

(Leave the rest of the mobile card unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pnpm test src/features/triage/components/__tests__/BucketTrackRow.test.tsx`
Expected: PASS (existing tests + 4 new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/components/BucketTrackRow.tsx \
        frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx
git commit -m "feat(triage): add Play button to bucket track row"
```

---

### Task 5: `BucketTracksList` — controlled search + play props

Lift the search **state** up to the page so the player queue can mirror the visible (filtered) list, and thread the new play props to rows. The list keeps its own `useBucketTracks` instance (deduped by query key with the page's). `BucketDetailPage` is updated in the same task to own the search state — no player wiring yet (that is Task 8).

**Files:**
- Modify: `frontend/src/features/triage/components/BucketTracksList.tsx`
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx`

- [ ] **Step 1: Rewrite `BucketTracksList` with controlled search**

Replace the props interface + the internal state + the search input wiring. Full new file:

```tsx
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconSearch, IconX } from '../../../components/icons';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useBucketTracks, type BucketTrack } from '../hooks/useBucketTracks';
import { BucketTrackRow } from './BucketTrackRow';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketTracksListProps {
  blockId: string;
  bucket: TriageBucket;
  buckets: TriageBucket[];
  showMoveMenu: boolean;
  onMove: (trackId: string, toBucket: TriageBucket) => void;
  onTransfer?: (trackId: string) => void;
  blockStatus?: 'IN_PROGRESS' | 'FINALIZED';
  rawSearch: string;
  onRawSearchChange: (value: string) => void;
  debouncedSearch: string;
  onPlay?: (track: BucketTrack) => void;
  currentTrackId?: string | null;
}

export function BucketTracksList({
  blockId,
  bucket,
  buckets,
  showMoveMenu,
  onMove,
  onTransfer,
  blockStatus,
  rawSearch,
  onRawSearchChange,
  debouncedSearch,
  onPlay,
  currentTrackId,
}: BucketTracksListProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useBucketTracks(
    blockId,
    bucket.id,
    debouncedSearch,
  );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('triage.bucket.search_placeholder')}
      leftSection={<IconSearch size={16} />}
      value={rawSearch}
      onChange={(e) => onRawSearchChange(e.currentTarget.value)}
      rightSection={
        rawSearch ? (
          <IconX
            size={16}
            role="button"
            onClick={() => onRawSearchChange('')}
            style={{ cursor: 'pointer' }}
            aria-label={t('triage.bucket.empty.search_miss_clear')}
          />
        ) : null
      }
    />
  );

  if (isLoading) {
    return (
      <Stack gap="md">
        {searchInput}
        <FullScreenLoader />
      </Stack>
    );
  }

  if (items.length === 0) {
    if (debouncedSearch) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('triage.bucket.empty.search_miss_title')}
            body={
              <Button variant="default" onClick={() => onRawSearchChange('')}>
                {t('triage.bucket.empty.search_miss_clear')}
              </Button>
            }
          />
        </Stack>
      );
    }
    const bodyKey =
      bucket.bucket_type === 'UNCLASSIFIED'
        ? 'triage.bucket.empty.no_tracks_body_unclassified'
        : 'triage.bucket.empty.no_tracks_body_default';
    return (
      <Stack gap="md">
        {searchInput}
        <EmptyState
          title={t('triage.bucket.empty.no_tracks_title')}
          body={t(bodyKey)}
        />
      </Stack>
    );
  }

  const rows = items.map((tr) => (
    <BucketTrackRow
      key={tr.track_id}
      track={tr}
      variant={isMobile ? 'mobile' : 'desktop'}
      buckets={buckets}
      currentBucketId={bucket.id}
      onMove={(b) => onMove(tr.track_id, b)}
      onTransfer={onTransfer ? () => onTransfer(tr.track_id) : undefined}
      showMoveMenu={showMoveMenu}
      blockStatus={blockStatus}
      onPlay={onPlay ? () => onPlay(tr) : undefined}
      isCurrent={currentTrackId != null && tr.track_id === currentTrackId}
    />
  ));

  if (isMobile) {
    return (
      <Stack gap="md">
        {searchInput}
        {rows}
        {hasNextPage && (
          <Button
            onClick={() => fetchNextPage()}
            loading={isFetchingNextPage}
            variant="default"
          >
            {t('triage.bucket.load_more')}
            {remaining > 0 ? ` (${remaining})` : ''}
          </Button>
        )}
      </Stack>
    );
  }

  return (
    <Stack gap="md">
      {searchInput}
      <Table>
        <Table.Thead>
          <Table.Tr>
            <Table.Th>{t('triage.tracks_table.title_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.artists_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.label_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.bpm_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.length_header')}</Table.Th>
            <Table.Th>{t('triage.tracks_table.released_header')}</Table.Th>
            <Table.Th aria-label={t('triage.tracks_table.actions_header')} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>{rows}</Table.Tbody>
      </Table>
      {hasNextPage && (
        <Group justify="center">
          <Button
            onClick={() => fetchNextPage()}
            loading={isFetchingNextPage}
            variant="default"
          >
            {t('triage.bucket.load_more')}
            {remaining > 0 ? ` (${remaining})` : ''}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
```

Note: `useState`/`useDebouncedValue` imports were removed because the list no longer owns search state.

- [ ] **Step 2: Update `BucketDetailPage` to own the search state**

In `frontend/src/features/triage/routes/BucketDetailPage.tsx`:

1. Add imports:

```tsx
import { useRef, useState } from 'react';
import { useDebouncedValue } from '@mantine/hooks';
```

(Keep the other existing imports. `useState`/`useRef` are already imported on line 1 — merge, don't duplicate.)

2. Inside `BucketDetailInner`, add search state near the other hooks:

```tsx
  const [rawSearch, setRawSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(rawSearch.trim(), 300);
```

3. Pass the new props to the `<BucketTracksList>` element (extend the existing JSX):

```tsx
      <BucketTracksList
        blockId={blockId}
        bucket={bucket}
        buckets={block.buckets}
        showMoveMenu={showMoveMenu}
        onMove={handleMove}
        onTransfer={(trackId) => setTransferTrackId(trackId)}
        blockStatus={block.status}
        rawSearch={rawSearch}
        onRawSearchChange={setRawSearch}
        debouncedSearch={debouncedSearch}
      />
```

(`onPlay` / `currentTrackId` are added in Task 8.)

- [ ] **Step 3: Update the `BucketTracksList` test for controlled search**

`BucketTracksList.test.tsx` currently renders the list with the old (uncontrolled) props. Wrap renders in a tiny stateful harness so the search input stays interactive. At the top of the test file add:

```tsx
import { useState } from 'react';
import { useDebouncedValue } from '@mantine/hooks';

function Harness(props: Omit<
  React.ComponentProps<typeof BucketTracksList>,
  'rawSearch' | 'onRawSearchChange' | 'debouncedSearch'
>) {
  const [rawSearch, setRawSearch] = useState('');
  const [debouncedSearch] = useDebouncedValue(rawSearch.trim(), 0);
  return (
    <BucketTracksList
      {...props}
      rawSearch={rawSearch}
      onRawSearchChange={setRawSearch}
      debouncedSearch={debouncedSearch}
    />
  );
}
```

Then replace every `<BucketTracksList ... />` render in the file with `<Harness ... />` (same props minus the three search props). The debounce delay is `0` in the harness so searches apply synchronously in tests. Existing assertions (rows render, search filters, load-more, move/transfer) stay the same.

- [ ] **Step 4: Run the list + page tests**

Run: `pnpm test src/features/triage/components/__tests__/BucketTracksList.test.tsx src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`
Expected: PASS. (The integration test does not yet touch playback, so it still passes.)

- [ ] **Step 5: Typecheck**

Run: `pnpm typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/components/BucketTracksList.tsx \
        frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx \
        frontend/src/features/triage/routes/BucketDetailPage.tsx
git commit -m "refactor(triage): lift bucket track search state to the page"
```

---

### Task 6: `BucketPlayerPanel` component

A lean player panel: the shared `PlayerCard` + label/BPM meta lookup, no tag/playlist clouds.

**Files:**
- Create: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`
- Test: `frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`

- [ ] **Step 1: Write the failing test**

`frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import type { BucketTrack } from '../hooks/useBucketTracks';
import type { PlaybackTrack } from '../../playback/lib/types';

const togglePlayPause = vi.fn();
let current: PlaybackTrack | null = null;

vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: { type: 'bucket', blockId: 'b1', bucketId: 'bk1' }, tracks: [], cursor: 0, status: 'playing' },
    track: { current, positionMs: 0, durationMs: 200000 },
    sdk: { ready: true, error: null },
    controls: {
      prewarm: async () => {},
      play: async () => {},
      pause: async () => {},
      togglePlayPause,
      next: async () => {},
      prev: async () => {},
      seekMs: async () => {},
      seekPct: async () => {},
      bindQueue: () => {},
      clearQueue: () => {},
      cancelPendingAdvance: () => {},
      openSpotifyExternal: () => {},
    },
    devices: {
      list: [], active: null, cloderTabId: null, isLoading: false, error: null,
      isOpen: false, pickerAnchor: null,
      open: () => {}, close: () => {}, refresh: async () => {}, pick: async () => {},
    },
  }),
}));

import { BucketPlayerPanel } from '../BucketPlayerPanel';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const item: BucketTrack = {
  track_id: 't1', title: 'Test Track', mix_name: null, isrc: null, bpm: 124,
  length_ms: 200000, publish_date: null, spotify_release_date: null,
  spotify_id: 'sp1', release_type: null, is_ai_suspected: false,
  artists: ['Artist A'], label_id: null, label_name: 'Anjunadeep',
  added_at: '2026-04-21T00:00:00Z',
};

beforeEach(() => {
  togglePlayPause.mockReset();
  current = null;
});

describe('BucketPlayerPanel', () => {
  it('shows the empty state when nothing is playing', () => {
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText(/Pick a track to start playing/i)).toBeInTheDocument();
  });

  it('renders the current track and label meta when playing', () => {
    current = {
      id: 't1', title: 'Test Track', artists: 'Artist A',
      duration_ms: 200000, spotify_id: 'sp1', cover_url: null,
    };
    r(<BucketPlayerPanel blockId="b1" bucketId="bk1" items={[item]} />);
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText('Anjunadeep')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: FAIL — cannot resolve `../BucketPlayerPanel`.

- [ ] **Step 3: Write the component**

`frontend/src/features/triage/components/BucketPlayerPanel.tsx`:

```tsx
import { useEffect, useMemo, useRef } from 'react';
import { Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { usePlayback } from '../../playback/usePlayback';
import { PlayerCard, type PlayerCardState } from '../../playback/PlayerCard';
import { DeviceIndicator } from '../../playback/DeviceIndicator';
import type { BucketTrack } from '../hooks/useBucketTracks';

export interface BucketPlayerPanelProps {
  blockId: string;
  bucketId: string;
  /** Visible bucket tracks, used to look up label/BPM for the playing track. */
  items: BucketTrack[];
}

export function BucketPlayerPanel({ items }: BucketPlayerPanelProps) {
  const { t } = useTranslation();
  const playback = usePlayback();
  const current = playback.track.current;

  // Rich-meta lookup with a "last seen" fallback so label/BPM survive a list
  // shrink (e.g. the current track gets moved out) until natural-end → next.
  const richTrack = useMemo<BucketTrack | null>(() => {
    const id = current?.id;
    if (!id) return null;
    return items.find((it) => it.track_id === id) ?? null;
  }, [items, current?.id]);
  const lastRichRef = useRef<BucketTrack | null>(null);
  useEffect(() => {
    if (richTrack) lastRichRef.current = richTrack;
  }, [richTrack]);
  useEffect(() => {
    if (!current) lastRichRef.current = null;
  }, [current]);
  const effectiveRich = richTrack ?? lastRichRef.current;

  const playerState: PlayerCardState = (() => {
    if (playback.sdk.error?.kind === 'init') return 'disconnected';
    const status = playback.queue.status;
    if (status === 'error') return 'error';
    if (status === 'idle' || status === 'ended') return 'idle';
    if (status === 'loading' || status === 'buffering') return 'buffering';
    if (status === 'disconnected') return 'disconnected';
    return status; // 'playing' | 'paused'
  })();

  if (!current) {
    return (
      <Stack gap="md" style={{ minWidth: 0, flex: '0 0 360px', maxWidth: 360 }}>
        <Text c="dimmed">{t('triage.bucket_player.empty.pick_track')}</Text>
      </Stack>
    );
  }

  const spotifyHref = current.spotify_id
    ? `https://open.spotify.com/track/${current.spotify_id}`
    : undefined;

  const metaRow =
    effectiveRich != null ? (
      <Group gap="md" wrap="wrap" mt={4} style={{ minWidth: 0 }}>
        {effectiveRich.label_name ? (
          <Text size="sm" c="var(--color-fg-muted)" truncate style={{ flex: 1 }}>
            {effectiveRich.label_name}
          </Text>
        ) : null}
        {effectiveRich.bpm != null ? (
          <Text size="sm" c="var(--color-fg-muted)" className="font-mono">
            {effectiveRich.bpm} BPM
          </Text>
        ) : null}
      </Group>
    ) : null;

  return (
    <Stack gap="md" style={{ minWidth: 0, flex: '0 0 360px', maxWidth: 360 }}>
      <PlayerCard
        variant="full"
        state={playerState}
        track={current}
        positionMs={playback.track.positionMs}
        mixName={effectiveRich?.mix_name ?? null}
        belowMainRow={metaRow}
        showTimes
        spotifyHref={spotifyHref}
        spotifyAriaLabel={t('triage.bucket_player.open_in_spotify_aria', {
          title: current.title,
        })}
        deviceIndicator={
          <DeviceIndicator
            mode="full"
            active={playback.devices.active}
            cloderTabId={playback.devices.cloderTabId}
            onOpen={(anchor) => playback.devices.open(anchor)}
          />
        }
        onPlayPause={() => void playback.controls.togglePlayPause()}
        onPrev={() => void playback.controls.prev()}
        onNext={() => void playback.controls.next()}
        onRetry={() => void playback.controls.play()}
        onOpenDevicePicker={() => playback.devices.open(null)}
        onSeekMs={(ms) => void playback.controls.seekMs(ms)}
      />
    </Stack>
  );
}
```

> Verify the `DeviceIndicator` prop names against `frontend/src/features/categories/components/CategoryPlayerPanel.tsx:248-255` — they are copied from there. If `DeviceIndicator` exposes a different prop shape, match the CategoryPlayerPanel usage exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Typecheck**

Run: `pnpm typecheck`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx \
        frontend/src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx
git commit -m "feat(triage): add BucketPlayerPanel"
```

---

### Task 7: Mobile player route + router

Add the nested fullscreen player route mirroring `CategoryPlayerPage`. The parent `BucketDetailPage` owns the queue binding + search and forwards visible `items` via outlet context.

**Files:**
- Create: `frontend/src/features/triage/routes/BucketPlayerPage.tsx`
- Modify: `frontend/src/routes/router.tsx`

- [ ] **Step 1: Create the player route component**

`frontend/src/features/triage/routes/BucketPlayerPage.tsx`:

```tsx
import { Stack, ActionIcon, Group } from '@mantine/core';
import { IconArrowLeft } from '@tabler/icons-react';
import { useNavigate, useOutletContext, useParams, Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketPlayerPanel } from '../components/BucketPlayerPanel';
import type { BucketTrack } from '../hooks/useBucketTracks';

export interface BucketDetailOutletContext {
  items: BucketTrack[];
}

// Nested under BucketDetailPage; the parent owns the queue binding + search
// state. This page renders the panel + a back link for the mobile layout.
export function BucketPlayerPage() {
  const { styleId, id, bucketId } = useParams<{
    styleId: string;
    id: string;
    bucketId: string;
  }>();
  if (!styleId || !id || !bucketId) return <Navigate to="/triage" replace />;
  return <BucketPlayerPageInner styleId={styleId} blockId={id} bucketId={bucketId} />;
}

function BucketPlayerPageInner({
  styleId,
  blockId,
  bucketId,
}: {
  styleId: string;
  blockId: string;
  bucketId: string;
}) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const ctx = useOutletContext<BucketDetailOutletContext | undefined>();
  const items = ctx?.items ?? [];
  return (
    <Stack gap="md" p="md">
      <Group>
        <ActionIcon
          variant="subtle"
          onClick={() => navigate(`/triage/${styleId}/${blockId}/buckets/${bucketId}`)}
          aria-label={t('triage.bucket_player.back_aria')}
        >
          <IconArrowLeft />
        </ActionIcon>
      </Group>
      <BucketPlayerPanel blockId={blockId} bucketId={bucketId} items={items} />
    </Stack>
  );
}
```

- [ ] **Step 2: Register the nested route**

In `frontend/src/routes/router.tsx`:

1. Add the import next to the other triage route imports:

```tsx
import { BucketPlayerPage } from '../features/triage/routes/BucketPlayerPage';
```

2. Change the bucket route (currently a leaf) to have a `player` child:

```tsx
          {
            path: ':styleId/:id/buckets/:bucketId',
            element: <BucketDetailPage />,
            children: [{ path: 'player', element: <BucketPlayerPage /> }],
          },
```

- [ ] **Step 3: Typecheck**

Run: `pnpm typecheck`
Expected: no errors. (`BucketDetailPage` does not yet render an `<Outlet>` — wired in Task 8 — but the route compiles.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/routes/BucketPlayerPage.tsx \
        frontend/src/routes/router.tsx
git commit -m "feat(triage): add nested bucket player route"
```

---

### Task 8: `BucketDetailPage` — bind queue, player layout, mobile nav

Wire the player into the bucket-detail page: bind the visible tracks to the queue, render the desktop split, push the mobile `/player` route on Play, and highlight the current row.

**Files:**
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx`
- Test: `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`

- [ ] **Step 1: Add the failing integration tests (mock `usePlayback`)**

Adding `usePlayback` to `BucketDetailPage` would throw in the existing test (no `PlaybackProvider`). Mock it at module scope — a no-op mock keeps the existing tests green and lets new tests spy on `play`. At the TOP of `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx` (before the `import { BucketDetailPage }` line), add:

```tsx
import { vi } from 'vitest';

const playSpy = vi.fn();
const bindQueueSpy = vi.fn();
const playbackState = {
  queue: { source: null as unknown, tracks: [] as unknown[], cursor: 0, status: 'idle' as const },
  track: { current: null as { id: string } | null, positionMs: 0, durationMs: 0 },
  sdk: { ready: true, error: null },
  controls: {
    prewarm: async () => {},
    play: playSpy,
    pause: async () => {},
    togglePlayPause: async () => {},
    next: async () => {},
    prev: async () => {},
    seekMs: async () => {},
    seekPct: async () => {},
    bindQueue: bindQueueSpy,
    clearQueue: () => {},
    cancelPendingAdvance: () => {},
    openSpotifyExternal: () => {},
  },
  devices: {
    list: [], active: null, cloderTabId: null, isLoading: false, error: null,
    isOpen: false, pickerAnchor: null,
    open: () => {}, close: () => {}, refresh: async () => {}, pick: async () => {},
  },
};

vi.mock('../../playback/usePlayback', () => ({
  usePlayback: () => playbackState,
}));
```

> `vi` may already be imported on line 1 of the file (`import { describe, it, expect, beforeEach, afterEach } from 'vitest';`). If so, add `vi` to that import instead of adding a second `import { vi }` line.

Then nest the player route inside the test router so mobile navigation has a target. Update the `renderAt` route array:

```tsx
      { path: '/triage/:styleId/:id/buckets/:bucketId', element: <BucketDetailPage />, children: [
        { path: 'player', element: <div data-testid="player-page" /> },
      ] },
```

Reset the spies in `beforeEach`:

```tsx
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
    playSpy.mockReset();
    bindQueueSpy.mockReset();
    playbackState.track.current = null;
  });
```

Add a new test. Note the existing `track()` fixture has `spotify_id: null`; define a playable variant inline:

```tsx
  it('plays a track when its Play button is clicked', async () => {
    const playable = { ...track('t1'), spotify_id: 'sp-t1' };
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk3/tracks', () =>
        HttpResponse.json({ items: [playable], total: 1, limit: 50, offset: 0 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk3');
    const playBtn = await screen.findByRole('button', { name: /Play track/i });
    await userEvent.click(playBtn);
    await waitFor(() => expect(playSpy).toHaveBeenCalled());
  });
```

- [ ] **Step 2: Run tests to verify the new one fails**

Run: `pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`
Expected: the new test FAILS (no Play button yet); existing tests still PASS (no-op mock).

- [ ] **Step 3: Wire the player into `BucketDetailPage`**

Apply these edits to `frontend/src/features/triage/routes/BucketDetailPage.tsx`:

1. Imports — add to the existing list:

```tsx
import { Flex, Stack, Text, Title, Anchor, Button, Group } from '@mantine/core';
import { useMediaQuery, useDebouncedValue } from '@mantine/hooks';
import { Link, Navigate, useNavigate, useMatch, useParams, Outlet } from 'react-router';
import { useMantineTheme } from '@mantine/core';
import { useBucketPlayerQueue } from '../hooks/useBucketPlayerQueue';
import { toPlaybackTrack } from '../lib/toPlaybackTrack';
import { usePlayback } from '../../playback/usePlayback';
import { BucketPlayerPanel } from '../components/BucketPlayerPanel';
import type { BucketDetailOutletContext } from './BucketPlayerPage';
```

> Merge with existing imports — do not duplicate `Stack`, `Anchor`, etc. `Flex`, `useMantineTheme`, `useMediaQuery`, `useNavigate`, `useMatch`, `Outlet`, `Group`, `Button` may be new. `useDebouncedValue` was added in Task 5.

2. Inside `BucketDetailInner`, after the existing `useBucketTracks(blockId, bucketId, '')` line and the search state from Task 5, add the playback wiring:

```tsx
  const navigate = useNavigate();
  const playback = usePlayback();
  const theme = useMantineTheme();
  const isDesktop = useMediaQuery(`(min-width: ${theme.breakpoints.md})`);
  const onPlayerSubpath = useMatch({
    path: '/triage/:styleId/:id/buckets/:bucketId/player',
    end: false,
  });

  // Player queue mirrors the visible (search-filtered) list. Deduped by query
  // key with the list's own useBucketTracks(blockId, bucketId, debouncedSearch).
  const playerQuery = useBucketTracks(blockId, bucketId, debouncedSearch);
  const playerItems = useMemo(
    () => playerQuery.data?.pages.flatMap((p) => p.items) ?? [],
    [playerQuery.data],
  );
  const playerTracks = useMemo(() => playerItems.map(toPlaybackTrack), [playerItems]);
  useBucketPlayerQueue(blockId, bucketId, playerTracks);

  useEffect(() => {
    void playback.controls.prewarm();
  }, [playback.controls]);

  const playTrack = useCallback(
    (tr: BucketTrack) => {
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
    [playback.controls, playback.queue.tracks, isDesktop, navigate, styleId, blockId, bucketId],
  );
```

3. Add the new imports for React hooks at the top (merge with line 1):

```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
```

4. Add `BucketTrack` to the existing `useBucketTracks` import:

```tsx
import { useBucketTracks, type BucketTrack } from '../hooks/useBucketTracks';
```

5. After the early returns (the `if (!bucket)` block), and before the main `return`, short-circuit to the mobile player outlet when on the `/player` subpath. Forward the visible items via outlet context:

```tsx
  if (onPlayerSubpath) {
    return (
      <Outlet
        context={{ items: playerItems } satisfies BucketDetailOutletContext}
      />
    );
  }
```

6. Replace the final `<BucketTracksList .../>` render with a desktop split (panel + list) and pass the play props. The current `currentTrackId` comes from `playback.track.current?.id`:

```tsx
      {isDesktop ? (
        <Flex gap="lg" align="flex-start" wrap="nowrap">
          <BucketPlayerPanel blockId={blockId} bucketId={bucketId} items={playerItems} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <BucketTracksList
              blockId={blockId}
              bucket={bucket}
              buckets={block.buckets}
              showMoveMenu={showMoveMenu}
              onMove={handleMove}
              onTransfer={(trackId) => setTransferTrackId(trackId)}
              blockStatus={block.status}
              rawSearch={rawSearch}
              onRawSearchChange={setRawSearch}
              debouncedSearch={debouncedSearch}
              onPlay={playTrack}
              currentTrackId={playback.track.current?.id ?? null}
            />
          </div>
        </Flex>
      ) : (
        <BucketTracksList
          blockId={blockId}
          bucket={bucket}
          buckets={block.buckets}
          showMoveMenu={showMoveMenu}
          onMove={handleMove}
          onTransfer={(trackId) => setTransferTrackId(trackId)}
          blockStatus={block.status}
          rawSearch={rawSearch}
          onRawSearchChange={setRawSearch}
          debouncedSearch={debouncedSearch}
          onPlay={playTrack}
          currentTrackId={playback.track.current?.id ?? null}
        />
      )}
```

(This replaces the single `<BucketTracksList>` block added in Task 5. Keep the surrounding `<Stack>`, header, back link, and `TransferModal`s unchanged.)

- [ ] **Step 4: Run the integration tests**

Run: `pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`
Expected: PASS — new "plays a track" test passes; all existing tests still pass.

> The integration test runs in jsdom where `useMediaQuery` returns `false` (no `matchMedia` match), so `isDesktop` is falsy → the list renders standalone and Play navigates to the player route. The `playSpy` assertion covers the click → play path. This matches how `useMediaQuery('(max-width: 64em)')` already behaves in the existing `BucketTracksList` mobile/desktop tests.

- [ ] **Step 5: Typecheck + lint**

Run: `pnpm typecheck && pnpm lint`
Expected: no errors. Fix any unused-import warnings (e.g. remove `useRef` if it ended up unused).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/routes/BucketDetailPage.tsx \
        frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
git commit -m "feat(triage): play bucket tracks from the bucket detail page"
```

---

### Task 9 (optional): Keyboard hotkeys

Wire the generic playback hotkeys on the bucket-detail surface (Space = play/pause, J/K = prev/next, Shift+J/K = seek ±10s, A/S/D/F/G = seek %). Only do this if you want parity with the curate/category players. Skip if scope-constrained — buttons already work.

**Files:**
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`

- [ ] **Step 1: Add hotkeys to the panel**

In `BucketPlayerPanel.tsx`, import and call the generic hook (it has no `active` gate; the panel only mounts on the bucket-detail route, so there is no competing player):

```tsx
import { usePlaybackHotkeys } from '../../playback/usePlaybackHotkeys';
```

Inside the component body (before the early `if (!current)` return):

```tsx
  usePlaybackHotkeys({
    onTogglePlayPause: () => void playback.controls.togglePlayPause(),
    onPrev: () => void playback.controls.prev(),
    onNext: () => void playback.controls.next(),
    onSeekRelative: (deltaMs) =>
      void playback.controls.seekMs(playback.track.positionMs + deltaMs),
    onSeekPct: (p) => void playback.controls.seekPct(p),
  });
```

- [ ] **Step 2: Run the panel test + typecheck**

Run: `pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx && pnpm typecheck`
Expected: PASS; no type errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/components/BucketPlayerPanel.tsx
git commit -m "feat(triage): keyboard hotkeys for bucket player"
```

---

### Task 10: Full verification

- [ ] **Step 1: Run the whole frontend test suite**

Run: `pnpm test`
Expected: all tests pass.

- [ ] **Step 2: Typecheck + lint**

Run: `pnpm typecheck && pnpm lint`
Expected: clean.

- [ ] **Step 3: Manual smoke test (golden path)**

Start the dev server from `frontend/` (`pnpm dev`, requires `frontend/.env.local` with `VITE_API_BASE_URL`). Then:
- Open a triage block → open a **staging** bucket with tracks that have Spotify IDs.
- Desktop: confirm the player panel sits beside the list; click a row's Play → audio starts, the row shows the `data-current` highlight, prev/next walk the bucket, the Spotify link works.
- Resize to mobile width: click Play → navigates to the fullscreen player; back arrow returns to the list with the queue intact.
- Open a **technical** bucket (e.g. NEW): confirm Play works there too and the existing "Curate from bucket" button is unchanged.
- Confirm the move/transfer menus still work while a track is playing.
- A track with no Spotify ID shows a disabled Play button.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** `useBucketPlayerQueue` (§1.1, Task 3); shared `toPlaybackTrack` (§1.2, Task 2); row Play (§1.3, Task 4); list playback props + search hoist (§1.4, Task 5); `BucketPlayerPanel` (§1.5, Task 6); mobile route (§1.6, Task 7); page wiring (§1.7, Task 8); router (§1.8, Task 7); i18n (§4, Task 1); all-buckets scope + read-only (§Decisions, honored by not gating on `bucket_type`/status). Hotkeys (§1.5) = optional Task 9.
- **Deviation from spec:** §1.4 says "consolidate to a single `useBucketTracks` instance." The plan keeps the list's query and adds a deduped page-level query (same `queryKey`) instead, which avoids turning the list fully presentational and matches the existing pattern where `BucketDetailPage` already runs a second `useBucketTracks(…, '')` for the bulk-transfer drain. React Query dedupes by key, so there is no extra network request. Same user-visible behavior, lower refactor risk.
- **Type consistency:** `BucketDetailOutletContext` is defined once in `BucketPlayerPage.tsx` and imported by `BucketDetailPage.tsx`. `useBucketPlayerQueue(blockId, bucketId, tracks)` signature matches every call site. `toPlaybackTrack` signature matches curate + page usage.
- **i18n:** EN-only confirmed — keys land in `frontend/src/i18n/en.json` only; no `ru.json`.

# Categories Track Move/Remove Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-row kebab menu on the Category Detail page that lets the user move a single track to another category in the same style or remove it from the current category, with optimistic UI updates and a 5-second Undo toast.

**Architecture:** Two new TanStack Query mutation hooks (`useMoveTrackBetweenCategories`, `useRemoveTrackOptimistic`) own optimistic cache writes against `['categories', 'tracks', categoryId]`. A new presentational component `TrackRowActions` renders an `ActionIcon` + flat Mantine `Menu` (no nested submenu — Mantine 9 lacks `Menu.Sub`; we mirror the triage `MoveToMenu` pattern). `TrackRow` gains an optional `actions` slot, `TracksTab` accepts `styleId` and plumbs the actions through, `CategoryDetailPage` passes `styleId` down. Move = sequential client-side `POST /categories/{toId}/tracks` then `DELETE /categories/{fromId}/tracks/{trackId}`; partial failure (POST ok, DELETE failed) surfaces a Retry toast. Undo invokes the inverse operation through existing hooks.

**Tech Stack:** React 19, Mantine 9 (`Menu`, `notifications`), TanStack Query 5, MSW 2, vitest 2, react-i18next.

**Spec:** `docs/superpowers/specs/2026-05-10-categories-track-move-remove-design.md`

---

## File map

**New:**

- `frontend/src/features/categories/hooks/useRemoveTrackOptimistic.ts`
- `frontend/src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx`
- `frontend/src/features/categories/hooks/useMoveTrackBetweenCategories.ts`
- `frontend/src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`
- `frontend/src/features/categories/components/TrackRowActions.tsx`
- `frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx`

**Modified:**

- `frontend/src/i18n/en.json` — add `categories.row_actions.*` and extend `categories.toast.*`.
- `frontend/src/features/categories/components/TrackRow.tsx` — add `actions?: ReactNode` slot.
- `frontend/src/features/categories/components/TracksTab.tsx` — accept `styleId`, render kebab column.
- `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx` — provide `styleId` prop and assert actions column.
- `frontend/src/features/categories/routes/CategoryDetailPage.tsx` — pass `styleId` to `<TracksTab>`.
- `frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx` — extend with move / undo / partial-fail flow.

---

### Task 1: i18n strings

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Add new i18n keys**

Open `frontend/src/i18n/en.json`. Find the `categories.tracks_table` block (around line 143) and add a sibling `row_actions` object inside `categories`. Find the `categories.toast` block (around line 112) and append the new toast keys before the closing `}`.

After edit, the relevant section reads:

```json
    "toast": {
      "created": "Category created.",
      "renamed": "Category renamed.",
      "deleted": "Category deleted.",
      "race_refreshed": "List changed elsewhere — refreshed.",
      "generic_error": "Couldn't save changes. Please retry.",
      "track_moved": "Moved to {{name}}.",
      "track_moved_partial": "Track is in both categories — couldn't remove from source.",
      "track_move_failed": "Move failed.",
      "track_removed": "Removed from category.",
      "track_remove_failed": "Couldn't remove track.",
      "undo_action": "Undo",
      "undone": "Undone.",
      "undo_failed": "Undo failed.",
      "retry": "Retry"
    },
```

And add the new `row_actions` block inside `categories`, e.g. right after `tracks_table`:

```json
    "row_actions": {
      "trigger_aria": "Track actions",
      "move_label": "Move to",
      "move_empty": "No other categories",
      "remove_label": "Remove from category",
      "current_marker": "(current)"
    }
```

- [ ] **Step 2: Verify JSON parses**

Run: `cd frontend && pnpm exec tsc --noEmit -p tsconfig.app.json`
Expected: passes (no behavior change yet, but JSON import is type-checked).

- [ ] **Step 3: Commit**

Use the `caveman:caveman-commit` skill to generate the message, then:

```bash
git add frontend/src/i18n/en.json
git commit -m "<subject from skill>"
```

---

### Task 2: `useRemoveTrackOptimistic` — happy path test + impl

**Files:**
- Create: `frontend/src/features/categories/hooks/useRemoveTrackOptimistic.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx`

- [ ] **Step 1: Write the failing test (happy path + 404 idempotent + invalidation)**

Create `frontend/src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import { useRemoveTrackOptimistic } from '../useRemoveTrackOptimistic';
import { categoryTracksKey, type PaginatedTracks } from '../useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function seed(qc: QueryClient, categoryId: string, ids: string[]): PaginatedTracks {
  const items = ids.map((id) => ({
    id,
    title: id,
    mix_name: null,
    artists: [],
    label: null,
    bpm: null,
    length_ms: null,
    publish_date: null,
    spotify_release_date: null,
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
  const page: PaginatedTracks = { items, total: items.length, limit: 50, offset: 0 };
  qc.setQueryData(categoryTracksKey(categoryId, '', 'added_at', 'desc'), {
    pages: [page],
    pageParams: [0],
  });
  return page;
}

describe('useRemoveTrackOptimistic', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs and resolves on 204', async () => {
    let hit = false;
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(hit).toBe(true);
  });

  it('treats 404 track_not_in_category as success (idempotent)', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () =>
        HttpResponse.json(
          { error_code: 'track_not_in_category', message: 'gone' },
          { status: 404 },
        ),
      ),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).resolves.toBeUndefined();
  });

  it('invalidates source list and ["categories"] after success', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    seed(qc, 'c1', ['t1']);
    qc.setQueryData(['categories'], { sentinel: true });
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(qc.getQueryState(categoryTracksKey('c1', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories'])?.isInvalidated).toBe(true);
  });

  it('optimistically shrinks source list on mutate', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', async () => {
        // Hold the response so the optimistic state is observable.
        await new Promise((r) => setTimeout(r, 30));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    let mutatePromise!: Promise<unknown>;
    act(() => {
      mutatePromise = result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    // Microtask flush — onMutate runs synchronously after mutateAsync starts.
    await Promise.resolve();
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0].items.map((x) => x.id)).toEqual(['t2']);
    expect(cached?.pages[0].total).toBe(1);
    await act(async () => {
      await mutatePromise;
    });
  });

  it('rolls back source list on error', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useRemoveTrackOptimistic(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).rejects.toBeInstanceOf(ApiError);
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0].items.map((x) => x.id)).toEqual(['t1', 't2']);
    expect(cached?.pages[0].total).toBe(2);
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd frontend && pnpm exec vitest run src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx`
Expected: FAIL with `Cannot find module '../useRemoveTrackOptimistic'`.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/features/categories/hooks/useRemoveTrackOptimistic.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import type { InfiniteData } from '@tanstack/react-query';
import type { PaginatedTracks } from './useCategoryTracks';

export interface RemoveTrackInput {
  categoryId: string;
  trackId: string;
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function shrink(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  let removed = 0;
  const pages = data.pages.map((p) => {
    const before = p.items.length;
    const items = p.items.filter((it) => it.id !== trackId);
    removed += before - items.length;
    return { ...p, items };
  });
  if (removed === 0) return data;
  return {
    ...data,
    pages: pages.map((p, idx) =>
      idx === 0 ? { ...p, total: Math.max(0, p.total - removed) } : p,
    ),
  };
}

export function useRemoveTrackOptimistic(): UseMutationResult<
  void,
  Error,
  RemoveTrackInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, RemoveTrackInput, MutationContext>({
    mutationFn: async ({ categoryId, trackId }) => {
      try {
        await api(`/categories/${categoryId}/tracks/${trackId}`, { method: 'DELETE' });
      } catch (err) {
        if (err instanceof ApiError && err.status === 404 && err.code === 'track_not_in_category') {
          return; // idempotent: post-state already matches goal
        }
        throw err;
      }
    },
    onMutate: async ({ categoryId, trackId }) => {
      const key = ['categories', 'tracks', categoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key }, (old) =>
        shrink(old, trackId),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) {
        qc.setQueryData(key, data);
      }
    },
    onSettled: (_d, _e, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
      qc.invalidateQueries({ queryKey: ['categories'] });
    },
  });
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd frontend && pnpm exec vitest run src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/hooks/useRemoveTrackOptimistic.ts \
        frontend/src/features/categories/hooks/__tests__/useRemoveTrackOptimistic.test.tsx
git commit -m "<subject from skill>"
```

---

### Task 3: `useMoveTrackBetweenCategories` — composition + partial-fail

**Files:**
- Create: `frontend/src/features/categories/hooks/useMoveTrackBetweenCategories.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { ApiError } from '../../../../api/error';
import {
  useMoveTrackBetweenCategories,
  MovePartialError,
} from '../useMoveTrackBetweenCategories';
import { categoryTracksKey, type PaginatedTracks } from '../useCategoryTracks';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function seed(qc: QueryClient, categoryId: string, ids: string[]): void {
  const items = ids.map((id) => ({
    id,
    title: id,
    mix_name: null,
    artists: [],
    label: null,
    bpm: null,
    length_ms: null,
    publish_date: null,
    spotify_release_date: null,
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
  const page: PaginatedTracks = { items, total: items.length, limit: 50, offset: 0 };
  qc.setQueryData(categoryTracksKey(categoryId, '', 'added_at', 'desc'), {
    pages: [page],
    pageParams: [0],
  });
}

describe('useMoveTrackBetweenCategories', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs to target then DELETEs from source on happy path', async () => {
    const calls: string[] = [];
    server.use(
      http.post('http://localhost/categories/c2/tracks', async ({ request }) => {
        calls.push(`POST ${(await request.json() as { track_id: string }).track_id}`);
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        calls.push('DELETE');
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });
    expect(calls).toEqual(['POST t1', 'DELETE']);
  });

  it('rejects without calling DELETE when POST fails', async () => {
    let deleteHit = false;
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => new HttpResponse(null, { status: 500 })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      }),
    ).rejects.toBeInstanceOf(ApiError);
    expect(deleteHit).toBe(false);
  });

  it('throws MovePartialError when POST succeeds but DELETE fails', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      }),
    ).rejects.toBeInstanceOf(MovePartialError);
  });

  it('optimistically shrinks the source list on mutate', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', async () => {
        await new Promise((r) => setTimeout(r, 30));
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    let p!: Promise<unknown>;
    act(() => {
      p = result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });
    await Promise.resolve();
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0].items.map((x) => x.id)).toEqual(['t2']);
    await act(async () => {
      await p;
    });
  });

  it('rolls back source list when POST fails', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    seed(qc, 'c1', ['t1', 't2']);
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({
          trackId: 't1',
          fromCategoryId: 'c1',
          toCategoryId: 'c2',
        });
      }),
    ).rejects.toBeTruthy();
    const cached = qc.getQueryData<{ pages: PaginatedTracks[] }>(
      categoryTracksKey('c1', '', 'added_at', 'desc'),
    );
    expect(cached?.pages[0].items.map((x) => x.id)).toEqual(['t1', 't2']);
  });

  it('invalidates both categories and ["categories"] on settle', async () => {
    server.use(
      http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    qc.setQueryData(categoryTracksKey('c1', '', 'added_at', 'desc'), { pages: [], pageParams: [] });
    qc.setQueryData(categoryTracksKey('c2', '', 'added_at', 'desc'), { pages: [], pageParams: [] });
    qc.setQueryData(['categories'], { sentinel: true });
    const { result } = renderHook(() => useMoveTrackBetweenCategories(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({
        trackId: 't1',
        fromCategoryId: 'c1',
        toCategoryId: 'c2',
      });
    });
    expect(qc.getQueryState(categoryTracksKey('c1', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(categoryTracksKey('c2', '', 'added_at', 'desc'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(['categories'])?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd frontend && pnpm exec vitest run src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/features/categories/hooks/useMoveTrackBetweenCategories.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { PaginatedTracks } from './useCategoryTracks';

export class MovePartialError extends Error {
  constructor(readonly cause: unknown) {
    super('Move partially completed: track was added to target but could not be removed from source');
    this.name = 'MovePartialError';
  }
}

export interface MoveTrackInput {
  trackId: string;
  fromCategoryId: string;
  toCategoryId: string;
}

interface MutationContext {
  prev: Array<[readonly unknown[], InfiniteData<PaginatedTracks> | undefined]>;
}

function shrink(
  data: InfiniteData<PaginatedTracks> | undefined,
  trackId: string,
): InfiniteData<PaginatedTracks> | undefined {
  if (!data) return data;
  let removed = 0;
  const pages = data.pages.map((p) => {
    const before = p.items.length;
    const items = p.items.filter((it) => it.id !== trackId);
    removed += before - items.length;
    return { ...p, items };
  });
  if (removed === 0) return data;
  return {
    ...data,
    pages: pages.map((p, idx) =>
      idx === 0 ? { ...p, total: Math.max(0, p.total - removed) } : p,
    ),
  };
}

export function useMoveTrackBetweenCategories(): UseMutationResult<
  void,
  Error,
  MoveTrackInput,
  MutationContext
> {
  const qc = useQueryClient();
  return useMutation<void, Error, MoveTrackInput, MutationContext>({
    mutationFn: async ({ trackId, fromCategoryId, toCategoryId }) => {
      await api(`/categories/${toCategoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_id: trackId }),
      });
      try {
        await api(`/categories/${fromCategoryId}/tracks/${trackId}`, { method: 'DELETE' });
      } catch (err) {
        throw new MovePartialError(err);
      }
    },
    onMutate: async ({ trackId, fromCategoryId }) => {
      const key = ['categories', 'tracks', fromCategoryId] as const;
      await qc.cancelQueries({ queryKey: key });
      const prev = qc.getQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key });
      qc.setQueriesData<InfiniteData<PaginatedTracks>>({ queryKey: key }, (old) =>
        shrink(old, trackId),
      );
      return { prev };
    },
    onError: (_err, _input, ctx) => {
      if (!ctx) return;
      for (const [key, data] of ctx.prev) {
        qc.setQueryData(key, data);
      }
    },
    onSettled: (_d, _e, { fromCategoryId, toCategoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', fromCategoryId] });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', toCategoryId] });
      qc.invalidateQueries({ queryKey: ['categories'] });
    },
  });
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd frontend && pnpm exec vitest run src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx`
Expected: PASS (6 tests).

> **Note on rollback semantics:** `MovePartialError` does NOT roll back the source cache (the POST already happened, so the row's true location is "in both"). The optimistic shrink in this case is consistent with the post-condition the user asked for; the partial-fail toast in TrackRowActions tells them the source DELETE didn't land. `onError` still runs, but the rollback that runs there will be overwritten by `onSettled` invalidation a moment later, so it's harmless. If a future test asserts the optimistic state survives across a `MovePartialError`, change `onError` to skip rollback when `_err instanceof MovePartialError`.

- [ ] **Step 5: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/hooks/useMoveTrackBetweenCategories.ts \
        frontend/src/features/categories/hooks/__tests__/useMoveTrackBetweenCategories.test.tsx
git commit -m "<subject from skill>"
```

---

### Task 4: `TrackRow` — `actions` slot prop

**Files:**
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`

- [ ] **Step 1: Add the `actions` prop and render slot**

Edit `frontend/src/features/categories/components/TrackRow.tsx`:

Add `actions?: ReactNode` to the props interface; render it as a trailing `<Table.Td>` on desktop and as an absolutely-positioned element in the top-right of the mobile card.

```tsx
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { ReactNode } from 'react';
import { formatAdded, formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  actions?: ReactNode;
}

export function TrackRow({ track, variant, actions }: TrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('categories.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;

  if (variant === 'desktop') {
    return (
      <Table.Tr>
        <Table.Td>
          <Group gap="xs" wrap="nowrap">
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
        <Table.Td>{joinArtists(track.artists)}</Table.Td>
        <Table.Td>{track.label?.name ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">
          {formatReleaseDate(track.spotify_release_date)}
        </Table.Td>
        <Table.Td>{formatAdded(track.added_at)}</Table.Td>
        <Table.Td style={{ width: 40 }}>{actions ?? null}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm" style={{ position: 'relative' }}>
      {actions && (
        <div style={{ position: 'absolute', top: 8, right: 8 }}>{actions}</div>
      )}
      <Stack gap={4}>
        <Group gap="xs">
          {aiBadge}
          <Text fw={500}>{track.title}</Text>
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">
            {track.mix_name}
          </Text>
        )}
        <Text size="sm">{joinArtists(track.artists)}</Text>
        {track.label && (
          <Text size="xs" c="dimmed">
            {track.label.name}
          </Text>
        )}
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          {track.spotify_release_date && (
            <Text size="xs" c="dimmed" className="font-mono">
              {track.spotify_release_date}
            </Text>
          )}
          <Text size="xs" c="dimmed">
            {formatAdded(track.added_at)}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 2: Run the existing TrackRow tests**

Run: `cd frontend && pnpm exec vitest run src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: PASS (the new prop is optional; existing tests provide no `actions`, so behavior is unchanged).

- [ ] **Step 3: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/components/TrackRow.tsx
git commit -m "<subject from skill>"
```

---

### Task 5: `TrackRowActions` component

**Files:**
- Create: `frontend/src/features/categories/components/TrackRowActions.tsx`
- Create: `frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TrackRowActions } from '../TrackRowActions';
import type { CategoryTrack } from '../../hooks/useCategoryTracks';
import { testTheme } from '../../../../test/theme';
import '../../../../i18n';

const TRACK: CategoryTrack = {
  id: 't1',
  title: 'Lift Off',
  mix_name: null,
  artists: [],
  label: null,
  bpm: null,
  length_ms: null,
  publish_date: null,
  spotify_release_date: null,
  isrc: null,
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  added_at: '2026-01-01T00:00:00Z',
  source_triage_block_id: null,
};

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

function categoriesPayload(items: Array<{ id: string; name: string }>) {
  return {
    items: items.map((c, i) => ({
      id: c.id,
      style_id: 's1',
      style_name: 'House',
      name: c.name,
      position: i,
      track_count: 0,
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })),
    total: items.length,
    limit: 200,
    offset: 0,
  };
}

describe('TrackRowActions', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('opens the menu and lists categories under Move to', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          categoriesPayload([
            { id: 'c1', name: 'Energetic' },
            { id: 'c2', name: 'Deep' },
            { id: 'c3', name: 'Sunset' },
          ]),
        ),
      ),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    expect(within(menu).getByText('Move to')).toBeInTheDocument();
    expect(within(menu).getByText('Deep')).toBeInTheDocument();
    expect(within(menu).getByText('Sunset')).toBeInTheDocument();
    expect(within(menu).getByText(/Energetic.*current/i)).toBeInTheDocument();
    expect(within(menu).getByRole('menuitem', { name: /Energetic/ })).toHaveAttribute(
      'data-disabled',
      'true',
    );
    expect(within(menu).getByRole('menuitem', { name: /Remove from category/ })).toBeInTheDocument();
  });

  it('disables Move to when no other categories exist', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(categoriesPayload([{ id: 'c1', name: 'Only' }])),
      ),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    const moveLabel = within(menu).getByText(/No other categories/);
    expect(moveLabel).toBeInTheDocument();
  });

  it('move click triggers POST + DELETE and shows success toast with Undo', async () => {
    let postHit = false;
    let deleteHit = false;
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          categoriesPayload([
            { id: 'c1', name: 'Energetic' },
            { id: 'c2', name: 'Deep' },
          ]),
        ),
      ),
      http.post('http://localhost/categories/c2/tracks', () => {
        postHit = true;
        return HttpResponse.json({ ok: true });
      }),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
    await waitFor(() => expect(postHit).toBe(true));
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });

  it('remove click triggers DELETE and shows success toast with Undo', async () => {
    let deleteHit = false;
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(categoriesPayload([{ id: 'c1', name: 'Energetic' }])),
      ),
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    render(
      <Wrapper>
        <TrackRowActions track={TRACK} currentCategoryId="c1" styleId="s1" />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
    const menu = await screen.findByRole('menu');
    await userEvent.click(within(menu).getByRole('menuitem', { name: /Remove from category/ }));
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(await screen.findByText(/Removed from category/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test — verify it fails**

Run: `cd frontend && pnpm exec vitest run src/features/categories/components/__tests__/TrackRowActions.test.tsx`
Expected: FAIL — `Cannot find module '../TrackRowActions'`.

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/categories/components/TrackRowActions.tsx`:

```tsx
import { ActionIcon, Anchor, Group, Menu, Text } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { IconDotsVertical } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useCategoriesByStyle } from '../hooks/useCategoriesByStyle';
import { useRemoveTrackOptimistic } from '../hooks/useRemoveTrackOptimistic';
import {
  MovePartialError,
  useMoveTrackBetweenCategories,
} from '../hooks/useMoveTrackBetweenCategories';
import { useAddTrackToCategory } from '../hooks/useAddTrackToCategory';
import { api } from '../../../api/client';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

export interface TrackRowActionsProps {
  track: CategoryTrack;
  currentCategoryId: string;
  styleId: string;
}

export function TrackRowActions({ track, currentCategoryId, styleId }: TrackRowActionsProps) {
  const { t } = useTranslation();
  const categoriesQ = useCategoriesByStyle(styleId);
  const moveMut = useMoveTrackBetweenCategories();
  const removeMut = useRemoveTrackOptimistic();
  const addMut = useAddTrackToCategory();

  const allCategories = categoriesQ.data?.items ?? [];
  const others = allCategories.filter((c) => c.id !== currentCategoryId);
  const moveDisabled = categoriesQ.isLoading || others.length === 0;

  const fireUndoToast = (
    successMsg: string,
    runUndo: () => Promise<void>,
  ) => {
    const toastId = `cat-track-${Date.now()}-${track.id}`;
    notifications.show({
      id: toastId,
      color: 'green',
      autoClose: 5000,
      message: (
        <Group justify="space-between" gap="md">
          <Text size="sm">{successMsg}</Text>
          <Anchor
            component="button"
            onClick={async () => {
              notifications.hide(toastId);
              try {
                await runUndo();
                notifications.show({
                  message: t('categories.toast.undone'),
                  color: 'green',
                });
              } catch {
                notifications.show({
                  message: t('categories.toast.undo_failed'),
                  color: 'red',
                });
              }
            }}
          >
            {t('categories.toast.undo_action')}
          </Anchor>
        </Group>
      ),
    });
  };

  const handleMove = (toCategoryId: string, toCategoryName: string) => {
    moveMut.mutate(
      {
        trackId: track.id,
        fromCategoryId: currentCategoryId,
        toCategoryId,
      },
      {
        onSuccess: () => {
          fireUndoToast(
            t('categories.toast.track_moved', { name: toCategoryName }),
            () =>
              moveMut.mutateAsync({
                trackId: track.id,
                fromCategoryId: toCategoryId,
                toCategoryId: currentCategoryId,
              }) as unknown as Promise<void>,
          );
        },
        onError: (err) => {
          if (err instanceof MovePartialError) {
            const partialId = `cat-track-partial-${Date.now()}-${track.id}`;
            notifications.show({
              id: partialId,
              color: 'red',
              autoClose: 8000,
              message: (
                <Group justify="space-between" gap="md">
                  <Text size="sm">{t('categories.toast.track_moved_partial')}</Text>
                  <Anchor
                    component="button"
                    onClick={async () => {
                      notifications.hide(partialId);
                      try {
                        await api(
                          `/categories/${currentCategoryId}/tracks/${track.id}`,
                          { method: 'DELETE' },
                        );
                        notifications.show({
                          message: t('categories.toast.track_removed'),
                          color: 'green',
                        });
                      } catch {
                        notifications.show({
                          message: t('categories.toast.track_remove_failed'),
                          color: 'red',
                        });
                      }
                    }}
                  >
                    {t('categories.toast.retry')}
                  </Anchor>
                </Group>
              ),
            });
          } else {
            notifications.show({
              message: t('categories.toast.track_move_failed'),
              color: 'red',
            });
          }
        },
      },
    );
  };

  const handleRemove = () => {
    removeMut.mutate(
      { categoryId: currentCategoryId, trackId: track.id },
      {
        onSuccess: () => {
          fireUndoToast(
            t('categories.toast.track_removed'),
            () =>
              addMut.mutateAsync({
                categoryId: currentCategoryId,
                trackId: track.id,
              }) as unknown as Promise<void>,
          );
        },
        onError: () => {
          notifications.show({
            message: t('categories.toast.track_remove_failed'),
            color: 'red',
          });
        },
      },
    );
  };

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label={t('categories.row_actions.trigger_aria')}>
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>
          {moveDisabled && others.length === 0
            ? t('categories.row_actions.move_empty')
            : t('categories.row_actions.move_label')}
        </Menu.Label>
        {allCategories.map((c) =>
          c.id === currentCategoryId ? (
            <Menu.Item key={c.id} disabled>
              {c.name} {t('categories.row_actions.current_marker')}
            </Menu.Item>
          ) : (
            <Menu.Item key={c.id} onClick={() => handleMove(c.id, c.name)}>
              {c.name}
            </Menu.Item>
          ),
        )}
        <Menu.Divider />
        <Menu.Item color="red" onClick={handleRemove}>
          {t('categories.row_actions.remove_label')}
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}
```

- [ ] **Step 4: Run the test — verify it passes**

Run: `cd frontend && pnpm exec vitest run src/features/categories/components/__tests__/TrackRowActions.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/components/TrackRowActions.tsx \
        frontend/src/features/categories/components/__tests__/TrackRowActions.test.tsx
git commit -m "<subject from skill>"
```

---

### Task 6: `TracksTab` — `styleId` prop and actions integration

**Files:**
- Modify: `frontend/src/features/categories/components/TracksTab.tsx`
- Modify: `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`

- [ ] **Step 1: Update the existing TracksTab tests to pass `styleId` and assert actions slot**

Edit `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`:

Replace every `<TracksTab categoryId="c1" />` with `<TracksTab categoryId="c1" styleId="s1" />`.

Add this MSW handler to every test that does not already define `/styles/s1/categories` (categories list is fetched by the action menu):

```tsx
http.get('http://localhost/styles/s1/categories', () =>
  HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
),
```

Add a new test at the end of the `describe('TracksTab', ...)` block:

```tsx
it('renders an actions column with a kebab trigger per row (desktop)', async () => {
  server.use(
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: mkTracks(0, 2), total: 2, limit: 50, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
    ),
  );
  render(
    <Wrapper>
      <TracksTab categoryId="c1" styleId="s1" />
    </Wrapper>,
  );
  await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
  expect(screen.getAllByRole('button', { name: /Track actions/i })).toHaveLength(2);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/features/categories/components/__tests__/TracksTab.test.tsx`
Expected: FAIL — TS error on `styleId` prop and `Track actions` button missing.

- [ ] **Step 3: Update TracksTab to accept `styleId` and render actions**

Edit `frontend/src/features/categories/components/TracksTab.tsx`:

Add `styleId: string` to `TracksTabProps`. Import `TrackRowActions`. Add a trailing empty `<Table.Th />` to the desktop header. Pass an `actions` prop to each `TrackRow`.

Final file:

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import {
  useCategoryTracks,
  type CategoryTrackSort,
  type SortOrder,
} from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { TrackRowActions } from './TrackRowActions';
import { SortableTh } from './SortableTh';
import { EmptyState } from '../../../components/EmptyState';

export interface TracksTabProps {
  categoryId: string;
  styleId: string;
}

export function TracksTab({ categoryId, styleId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);
  const [sortKey, setSortKey] = useState<CategoryTrackSort>('added_at');
  const [sortDir, setSortDir] = useState<SortOrder>('desc');

  const handleSort = (key: CategoryTrackSort) => {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'title' ? 'asc' : 'desc');
    }
  };

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useCategoryTracks(categoryId, debounced, sortKey, sortDir);

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('categories.detail.tracks_search_placeholder')}
      leftSection={<IconSearch size={16} />}
      value={rawSearch}
      onChange={(e) => setRawSearch(e.currentTarget.value)}
      rightSection={
        rawSearch ? (
          <IconX
            size={16}
            role="button"
            onClick={() => setRawSearch('')}
            style={{ cursor: 'pointer' }}
          />
        ) : null
      }
    />
  );

  if (!isLoading && items.length === 0) {
    if (debounced) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('categories.empty_state.no_search_results_title', { term: debounced })}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
                {t('categories.empty_state.clear_search')}
              </Button>
            }
          />
        </Stack>
      );
    }
    return (
      <Stack gap="md">
        {searchInput}
        <EmptyState
          title={t('categories.empty_state.no_tracks_title')}
          body={t('categories.empty_state.no_tracks_body')}
        />
      </Stack>
    );
  }

  if (isMobile) {
    return (
      <Stack gap="md">
        {searchInput}
        {items.map((tr) => (
          <TrackRow
            key={tr.id}
            track={tr}
            variant="mobile"
            actions={
              <TrackRowActions
                track={tr}
                currentCategoryId={categoryId}
                styleId={styleId}
              />
            }
          />
        ))}
        {hasNextPage && (
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
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
            <SortableTh
              active={sortKey === 'title'}
              dir={sortDir}
              onClick={() => handleSort('title')}
            >
              {t('categories.tracks_table.title')}
            </SortableTh>
            <Table.Th>{t('categories.tracks_table.artists')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.label')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.bpm')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.length')}</Table.Th>
            <SortableTh
              active={sortKey === 'spotify_release_date'}
              dir={sortDir}
              onClick={() => handleSort('spotify_release_date')}
            >
              {t('categories.tracks_table.released')}
            </SortableTh>
            <SortableTh
              active={sortKey === 'added_at'}
              dir={sortDir}
              onClick={() => handleSort('added_at')}
            >
              {t('categories.tracks_table.added')}
            </SortableTh>
            <Table.Th aria-hidden style={{ width: 40 }} />
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((track) => (
            <TrackRow
              key={track.id}
              track={track}
              variant="desktop"
              actions={
                <TrackRowActions
                  track={track}
                  currentCategoryId={categoryId}
                  styleId={styleId}
                />
              }
            />
          ))}
        </Table.Tbody>
      </Table>
      {hasNextPage && (
        <Group justify="center">
          <Button onClick={() => fetchNextPage()} loading={isFetchingNextPage} variant="default">
            {t('categories.detail.tracks_load_more', { remaining })}
          </Button>
        </Group>
      )}
    </Stack>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm exec vitest run src/features/categories/components/__tests__/TracksTab.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/components/TracksTab.tsx \
        frontend/src/features/categories/components/__tests__/TracksTab.test.tsx
git commit -m "<subject from skill>"
```

---

### Task 7: `CategoryDetailPage` — pass `styleId` to `TracksTab`

**Files:**
- Modify: `frontend/src/features/categories/routes/CategoryDetailPage.tsx`

- [ ] **Step 1: Pass styleId**

Edit `frontend/src/features/categories/routes/CategoryDetailPage.tsx`. Find:

```tsx
<TracksTab categoryId={id} />
```

Replace with:

```tsx
<TracksTab categoryId={id} styleId={styleId} />
```

- [ ] **Step 2: Run typecheck**

Run: `cd frontend && pnpm exec tsc --noEmit -p tsconfig.app.json`
Expected: passes.

- [ ] **Step 3: Run existing detail-page tests**

Run: `cd frontend && pnpm exec vitest run src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx`
Expected: existing assertions still pass; the page may now render extra MSW requests for `/styles/{id}/categories` (one per row). Add this MSW handler to each test in that file (in the per-test `server.use`) so it doesn't 404 in the console:

```tsx
http.get('http://localhost/styles/s1/categories', () =>
  HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
),
```

Re-run the file after the MSW addition.

- [ ] **Step 4: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/routes/CategoryDetailPage.tsx \
        frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
git commit -m "<subject from skill>"
```

---

### Task 8: Integration — move + undo + partial-fail flow on detail page

**Files:**
- Modify: `frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx`

- [ ] **Step 1: Add three integration tests**

Append at the bottom of `CategoryDetailPage.test.tsx` (inside the existing `describe`):

```tsx
it('move flow: kebab → pick destination → optimistic shrink + success toast', async () => {
  let postHit = false;
  let deleteHit = false;
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1',
        style_id: 's1',
        style_name: 'House',
        name: 'Energetic',
        position: 0,
        track_count: 1,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({
        items: [
          {
            id: 't1',
            title: 'Lift Off',
            mix_name: null,
            artists: [],
            label: null,
            bpm: null,
            length_ms: null,
            publish_date: null,
            spotify_release_date: null,
            isrc: null,
            spotify_id: null,
            release_type: null,
            is_ai_suspected: false,
            added_at: '2026-01-01T00:00:00Z',
            source_triage_block_id: null,
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({
        items: [
          { id: 'c1', style_id: 's1', style_name: 'House', name: 'Energetic', position: 0, track_count: 1, created_at: 'x', updated_at: 'x' },
          { id: 'c2', style_id: 's1', style_name: 'House', name: 'Deep', position: 1, track_count: 0, created_at: 'x', updated_at: 'x' },
        ],
        total: 2,
        limit: 200,
        offset: 0,
      }),
    ),
    http.post('http://localhost/categories/c2/tracks', () => {
      postHit = true;
      return HttpResponse.json({ ok: true });
    }),
    http.delete('http://localhost/categories/c1/tracks/t1', () => {
      deleteHit = true;
      return new HttpResponse(null, { status: 204 });
    }),
  );

  render(<RoutedDetail styleId="s1" id="c1" />);
  await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());

  await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
  const menu = await screen.findByRole('menu');
  await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));

  await waitFor(() => expect(postHit).toBe(true));
  await waitFor(() => expect(deleteHit).toBe(true));
  expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
});

it('undo flow: clicking Undo on the move toast posts back and deletes from target', async () => {
  const calls: string[] = [];
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1', style_id: 's1', style_name: 'House', name: 'Energetic',
        position: 0, track_count: 1,
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({
        items: [{
          id: 't1', title: 'Lift Off', mix_name: null, artists: [], label: null,
          bpm: null, length_ms: null, publish_date: null, spotify_release_date: null,
          isrc: null, spotify_id: null, release_type: null, is_ai_suspected: false,
          added_at: '2026-01-01T00:00:00Z', source_triage_block_id: null,
        }],
        total: 1, limit: 50, offset: 0,
      }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({
        items: [
          { id: 'c1', style_id: 's1', style_name: 'House', name: 'Energetic', position: 0, track_count: 1, created_at: 'x', updated_at: 'x' },
          { id: 'c2', style_id: 's1', style_name: 'House', name: 'Deep', position: 1, track_count: 0, created_at: 'x', updated_at: 'x' },
        ],
        total: 2, limit: 200, offset: 0,
      }),
    ),
    http.post('http://localhost/categories/c2/tracks', async ({ request }) => {
      calls.push(`POST c2 ${(await request.json() as { track_id: string }).track_id}`);
      return HttpResponse.json({ ok: true });
    }),
    http.delete('http://localhost/categories/c1/tracks/t1', () => {
      calls.push('DELETE c1');
      return new HttpResponse(null, { status: 204 });
    }),
    http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
      calls.push(`POST c1 ${(await request.json() as { track_id: string }).track_id}`);
      return HttpResponse.json({ ok: true });
    }),
    http.delete('http://localhost/categories/c2/tracks/t1', () => {
      calls.push('DELETE c2');
      return new HttpResponse(null, { status: 204 });
    }),
  );

  render(<RoutedDetail styleId="s1" id="c1" />);
  await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());
  await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
  const menu = await screen.findByRole('menu');
  await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
  expect(await screen.findByText(/Moved to Deep/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /Undo/ }));
  await waitFor(() => expect(calls).toEqual([
    'POST c2 t1',
    'DELETE c1',
    'POST c1 t1',
    'DELETE c2',
  ]));
  expect(await screen.findByText(/Undone/)).toBeInTheDocument();
});

it('partial-fail: POST ok + DELETE 500 → toast says "in both" with Retry that succeeds', async () => {
  let deleteAttempts = 0;
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1', style_id: 's1', style_name: 'House', name: 'Energetic',
        position: 0, track_count: 1,
        created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({
        items: [{
          id: 't1', title: 'Lift Off', mix_name: null, artists: [], label: null,
          bpm: null, length_ms: null, publish_date: null, spotify_release_date: null,
          isrc: null, spotify_id: null, release_type: null, is_ai_suspected: false,
          added_at: '2026-01-01T00:00:00Z', source_triage_block_id: null,
        }],
        total: 1, limit: 50, offset: 0,
      }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({
        items: [
          { id: 'c1', style_id: 's1', style_name: 'House', name: 'Energetic', position: 0, track_count: 1, created_at: 'x', updated_at: 'x' },
          { id: 'c2', style_id: 's1', style_name: 'House', name: 'Deep', position: 1, track_count: 0, created_at: 'x', updated_at: 'x' },
        ],
        total: 2, limit: 200, offset: 0,
      }),
    ),
    http.post('http://localhost/categories/c2/tracks', () => HttpResponse.json({ ok: true })),
    http.delete('http://localhost/categories/c1/tracks/t1', () => {
      deleteAttempts += 1;
      if (deleteAttempts === 1) return new HttpResponse(null, { status: 500 });
      return new HttpResponse(null, { status: 204 });
    }),
  );

  render(<RoutedDetail styleId="s1" id="c1" />);
  await waitFor(() => expect(screen.getByText('Lift Off')).toBeInTheDocument());
  await userEvent.click(screen.getByRole('button', { name: /Track actions/i }));
  const menu = await screen.findByRole('menu');
  await userEvent.click(within(menu).getByRole('menuitem', { name: /Deep/ }));
  expect(await screen.findByText(/Track is in both categories/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole('button', { name: /Retry/ }));
  expect(await screen.findByText(/Removed from category/)).toBeInTheDocument();
  expect(deleteAttempts).toBe(2);
});
```

> If `RoutedDetail` is not the existing fixture name in the file, replace it with whatever helper the existing tests use to mount the page; bring in `within` from `@testing-library/react` if it isn't already imported. The helper from the file already provides routing + auth + Mantine context.

- [ ] **Step 2: Run the tests**

Run: `cd frontend && pnpm exec vitest run src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx`
Expected: 3 new tests pass alongside existing.

- [ ] **Step 3: Run the full categories test bundle as a smoke check**

Run: `cd frontend && pnpm exec vitest run src/features/categories/`
Expected: all green.

- [ ] **Step 4: Run typecheck and lint**

Run: `cd frontend && pnpm exec tsc --noEmit -p tsconfig.app.json && pnpm exec eslint src/features/categories --max-warnings=0`
Expected: passes.

- [ ] **Step 5: Manual smoke (UI verification)**

Per CLAUDE.md, UI changes must be exercised in the browser. From `frontend/`:

```bash
pnpm dev
```

In the browser at `http://127.0.0.1:5173`:

1. Navigate to a category detail page (`/categories/<styleId>/<categoryId>`).
2. Verify each track row shows a `⋮` button on the right.
3. Click `⋮`. The menu shows a `Move to` label, the list of style categories (current one disabled with `(current)`), a divider, and a red `Remove from category` item.
4. Click another category. Toast `Moved to <name>` appears with `Undo`. Track is gone from list.
5. Click `Undo` on the toast. `Undone.` toast appears. Track returns.
6. Click `⋮` → `Remove from category`. Toast `Removed from category` with Undo. Click Undo → track returns.
7. Repeat on mobile viewport (resize to ≤ 1024 px). Same behavior, kebab in card top-right.
8. (If possible) Use a category whose style has only that single category. Confirm `Move to` is replaced by `No other categories` label and only the red Remove item is enabled.

If anything diverges from the spec, fix and add a regression test before the commit.

- [ ] **Step 6: Commit**

Use `caveman:caveman-commit` skill, then:

```bash
git add frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
git commit -m "<subject from skill>"
```

---

## Self-review checklist (run after Task 8)

- [ ] All five spec sections (UX, Architecture, Data flow, Error handling, Tests) are covered by tasks above.
- [ ] No `useRemoveTrackFromCategory` or `useAddTrackToCategory` modifications snuck in (curate path is preserved).
- [ ] All new toast strings are in `en.json`.
- [ ] `MovePartialError` is exported from the move hook and consumed in `TrackRowActions`.
- [ ] `pnpm exec vitest run` passes the full suite.
- [ ] `pnpm exec tsc --noEmit -p tsconfig.app.json` is clean.
- [ ] Manual smoke from Task 8 step 5 confirmed; flow matches spec.

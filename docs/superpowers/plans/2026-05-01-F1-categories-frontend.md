# F1 Categories Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Categories CRUD + DnD reorder + read-only tracks tab as the first iter-2a frontend ticket (F1), fully integrated with the existing SPA shell from A2.

**Architecture:** Feature folder `frontend/src/features/categories/` with `routes/`, `components/`, `hooks/`, `lib/`. Three new routes registered through react-router 7 data router. React-query 5 for server state with mixed optimistic (rename, reorder) / pessimistic (create, delete) mutations. `@dnd-kit/sortable` for accessible drag-and-drop reorder. Mantine 9 forms with `mantine-form-zod-resolver` for client validation that mirrors backend constraints. MSW + Vitest for tests.

**Tech Stack:** React 19, TypeScript, Mantine 9 (`core` + `form` + `dates` + `notifications` + new `modals`), `@tanstack/react-query` 5, `react-router` 7, `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, zod (existing), `mantine-form-zod-resolver` (new), Vitest + Testing Library + MSW.

**Spec:** [`../specs/2026-05-01-F1-categories-frontend-design.md`](../specs/2026-05-01-F1-categories-frontend-design.md). Read it before starting — every UX decision is referenced from there.

**Delivery model:** Direct merge to `main` from `feat/categories-crud` branch (no PR review). Commit messages via `caveman:caveman-commit` skill (CLAUDE.md mandate).

---

## Task 0: Prep — branch + deps + ModalsProvider

**Files:**

- Modify: `frontend/package.json`
- Modify: `frontend/src/main.tsx`

- [ ] **Step 1: Create the working branch**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/new_front
git checkout -b feat/categories-crud
```

- [ ] **Step 2: Install new deps**

```bash
cd frontend
pnpm add @dnd-kit/core @dnd-kit/sortable @dnd-kit/utilities @mantine/modals mantine-form-zod-resolver
```

Expected: `pnpm-lock.yaml` updated; ~5 packages added.

- [ ] **Step 3: Confirm types still build**

```bash
cd frontend
pnpm typecheck
```

Expected: no errors.

- [ ] **Step 4: Wrap the app in `<ModalsProvider>`**

Open `frontend/src/main.tsx` and add the import + wrap. The exact diff (assuming the current shape from A2):

```tsx
// near other Mantine imports
import { ModalsProvider } from '@mantine/modals';
import '@mantine/notifications/styles.css';
// add this if not already imported (modals has no css of its own beyond core)

// In the JSX tree, wrap whatever already lives inside MantineProvider:
<MantineProvider theme={clouderTheme} defaultColorScheme="light">
  <ModalsProvider>
    <Notifications position="top-right" />
    <RouterProvider router={router} />
  </ModalsProvider>
</MantineProvider>
```

If `Notifications` is currently a sibling of `RouterProvider` directly under `MantineProvider`, keep that order — `ModalsProvider` just nests them.

- [ ] **Step 5: Run existing tests, verify still green**

```bash
cd frontend
pnpm test
```

Expected: all 46 baseline tests still pass.

- [ ] **Step 6: Commit**

Generate via caveman-commit skill. Suggested message:

```
chore(frontend): add dnd-kit + mantine modals deps

@dnd-kit family for F1 categories reorder.
@mantine/modals for confirmation modals.
mantine-form-zod-resolver for form validation against
the existing zod dep.
```

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/new_front
git add frontend/package.json frontend/pnpm-lock.yaml frontend/src/main.tsx
git commit -m "chore(frontend): add dnd-kit + mantine modals deps

@dnd-kit family for F1 categories reorder.
@mantine/modals for confirmation modals.
mantine-form-zod-resolver for form validation against
the existing zod dep."
```

---

## Task 1: Feature folder skeleton + lastVisitedStyle helper

**Files:**

- Create: `frontend/src/features/categories/index.ts`
- Create: `frontend/src/features/categories/lib/lastVisitedStyle.ts`
- Create: `frontend/src/features/categories/lib/__tests__/lastVisitedStyle.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/lib/__tests__/lastVisitedStyle.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import { readLastVisitedStyle, writeLastVisitedStyle, LAST_STYLE_KEY } from '../lastVisitedStyle';

describe('lastVisitedStyle', () => {
  beforeEach(() => localStorage.clear());

  it('returns null when nothing stored', () => {
    expect(readLastVisitedStyle()).toBeNull();
  });

  it('round-trips a style id', () => {
    writeLastVisitedStyle('abc-123');
    expect(readLastVisitedStyle()).toBe('abc-123');
  });

  it('uses the documented namespace key', () => {
    expect(LAST_STYLE_KEY).toBe('clouder.lastStyleId');
  });

  it('survives a thrown SecurityError on read', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      expect(readLastVisitedStyle()).toBeNull();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});
```

- [ ] **Step 2: Run the test, verify it fails**

```bash
cd frontend
pnpm test src/features/categories/lib/__tests__/lastVisitedStyle.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the helper**

Create `frontend/src/features/categories/lib/lastVisitedStyle.ts`:

```ts
export const LAST_STYLE_KEY = 'clouder.lastStyleId';

export function readLastVisitedStyle(): string | null {
  try {
    return localStorage.getItem(LAST_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastVisitedStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_STYLE_KEY, styleId);
  } catch {
    /* private mode etc. — ignore */
  }
}
```

- [ ] **Step 4: Add the feature index barrel**

Create `frontend/src/features/categories/index.ts`:

```ts
// Re-exports populated as routes are added.
export {};
```

- [ ] **Step 5: Run the test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/lib/__tests__/lastVisitedStyle.test.ts
```

Expected: 4 passing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/categories/
git commit -m "feat(frontend): add lastVisitedStyle localStorage helper

F1 needs to redirect /categories to the user's last visited
style. Single-key namespace under clouder.* per spec D16."
```

---

## Task 2: Zod category-name schema

**Files:**

- Create: `frontend/src/features/categories/lib/categorySchemas.ts`
- Create: `frontend/src/features/categories/lib/__tests__/categorySchemas.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/lib/__tests__/categorySchemas.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { categoryNameSchema, createCategorySchema } from '../categorySchemas';

describe('categoryNameSchema', () => {
  it('rejects empty', () => {
    expect(categoryNameSchema.safeParse('').success).toBe(false);
  });

  it('rejects whitespace-only', () => {
    const r = categoryNameSchema.safeParse('   ');
    expect(r.success).toBe(false);
  });

  it('trims', () => {
    expect(categoryNameSchema.parse('  Tech House  ')).toBe('Tech House');
  });

  it('accepts 64 chars after trim', () => {
    expect(categoryNameSchema.safeParse('a'.repeat(64)).success).toBe(true);
  });

  it('rejects 65 chars', () => {
    expect(categoryNameSchema.safeParse('a'.repeat(65)).success).toBe(false);
  });

  it('rejects ASCII control bytes', () => {
    expect(categoryNameSchema.safeParse('hi\x00there').success).toBe(false);
    expect(categoryNameSchema.safeParse('hi\x1fthere').success).toBe(false);
    expect(categoryNameSchema.safeParse('hi\x7fthere').success).toBe(false);
  });

  it('accepts unicode', () => {
    expect(categoryNameSchema.safeParse('Tech House — Deep ✦').success).toBe(true);
  });
});

describe('createCategorySchema', () => {
  it('round-trips name', () => {
    expect(createCategorySchema.parse({ name: ' Deep  ' })).toEqual({ name: 'Deep' });
  });
});
```

- [ ] **Step 2: Run the test, verify failure**

```bash
cd frontend
pnpm test src/features/categories/lib/__tests__/categorySchemas.test.ts
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the schema**

Create `frontend/src/features/categories/lib/categorySchemas.ts`:

```ts
import { z } from 'zod';

const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const categoryNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(64, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const createCategorySchema = z.object({ name: categoryNameSchema });
export const renameCategorySchema = createCategorySchema;

export type CreateCategoryInput = z.infer<typeof createCategorySchema>;
export type RenameCategoryInput = z.infer<typeof renameCategorySchema>;
```

- [ ] **Step 4: Run the test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/lib/__tests__/categorySchemas.test.ts
```

Expected: 8 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/lib/categorySchemas.ts \
        frontend/src/features/categories/lib/__tests__/categorySchemas.test.ts
git commit -m "feat(frontend): add zod category-name schema

Mirrors server-side validate_category_name (spec-C 6.3): trim,
1..64 chars, no ASCII C0/DEL/C1 control bytes. Same schema for
create + rename per spec §3 D10."
```

---

## Task 3: useStyles hook (read)

**Files:**

- Create: `frontend/src/features/categories/hooks/useStyles.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useStyles.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/hooks/__tests__/useStyles.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useStyles } from '../useStyles';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useStyles', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('returns paginated items', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useStyles(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items).toHaveLength(2);
    expect(result.current.data?.items[0].name).toBe('House');
  });

  it('hits limit=200', async () => {
    let called = '';
    server.use(
      http.get('http://localhost/styles', ({ request }) => {
        called = new URL(request.url).search;
        return HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 });
      }),
    );
    const { result } = renderHook(() => useStyles(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(called).toContain('limit=200');
  });
});
```

- [ ] **Step 2: Run the test, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useStyles.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/features/categories/hooks/useStyles.ts`:

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Style {
  id: string;
  name: string;
}

export interface PaginatedStyles {
  items: Style[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export function useStyles(): UseQueryResult<PaginatedStyles> {
  return useQuery({
    queryKey: ['styles'],
    queryFn: () => api<PaginatedStyles>('/styles?limit=200&offset=0'),
    staleTime: 5 * 60 * 1000,
  });
}
```

- [ ] **Step 4: Run the test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useStyles.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useStyles.ts \
        frontend/src/features/categories/hooks/__tests__/useStyles.test.tsx
git commit -m "feat(frontend): add useStyles read hook

Powers StyleSelector + index redirect. Limit=200 single-page
fetch — 5-15 styles in practice. 5min staleTime."
```

---

## Task 4: useCategoriesByStyle hook (read)

**Files:**

- Create: `frontend/src/features/categories/hooks/useCategoriesByStyle.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCategoriesByStyle.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/hooks/__tests__/useCategoriesByStyle.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoriesByStyle } from '../useCategoriesByStyle';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCategoriesByStyle', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches categories for a style', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({
          items: [
            {
              id: 'c1',
              style_id: 's1',
              style_name: 'House',
              name: 'Deep',
              position: 0,
              track_count: 12,
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useCategoriesByStyle('s1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.items[0].name).toBe('Deep');
    expect(result.current.data?.items[0].track_count).toBe(12);
  });

  it('does not fetch when styleId is empty', () => {
    const { result } = renderHook(() => useCategoriesByStyle(''), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });
});
```

- [ ] **Step 2: Run the test, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoriesByStyle.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/features/categories/hooks/useCategoriesByStyle.ts`:

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface Category {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  position: number;
  track_count: number;
  created_at: string;
  updated_at: string;
}

export interface PaginatedCategories {
  items: Category[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

export const categoriesByStyleKey = (styleId: string) => ['categories', 'byStyle', styleId] as const;

export function useCategoriesByStyle(styleId: string): UseQueryResult<PaginatedCategories> {
  return useQuery({
    queryKey: categoriesByStyleKey(styleId),
    queryFn: () => api<PaginatedCategories>(`/styles/${styleId}/categories?limit=200&offset=0`),
    enabled: !!styleId,
  });
}
```

- [ ] **Step 4: Run the test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoriesByStyle.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCategoriesByStyle.ts \
        frontend/src/features/categories/hooks/__tests__/useCategoriesByStyle.test.tsx
git commit -m "feat(frontend): add useCategoriesByStyle hook

Single-page fetch (limit=200) — categories per user per style
≪ 200 by spec-C 5.2. Disabled when styleId empty."
```

---

## Task 5: useCategoryDetail hook (read)

**Files:**

- Create: `frontend/src/features/categories/hooks/useCategoryDetail.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCategoryDetail.test.tsx`

- [ ] **Step 1: Write the failing test**

Create the test file:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoryDetail } from '../useCategoryDetail';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCategoryDetail', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches a single category', async () => {
    server.use(
      http.get('http://localhost/categories/c1', () =>
        HttpResponse.json({
          id: 'c1',
          style_id: 's1',
          style_name: 'House',
          name: 'Deep',
          position: 0,
          track_count: 5,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        }),
      ),
    );
    const { result } = renderHook(() => useCategoryDetail('c1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe('Deep');
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoryDetail.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useCategoryDetail.ts`:

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { Category } from './useCategoriesByStyle';

export const categoryDetailKey = (id: string) => ['categories', 'detail', id] as const;

export function useCategoryDetail(id: string): UseQueryResult<Category> {
  return useQuery({
    queryKey: categoryDetailKey(id),
    queryFn: () => api<Category>(`/categories/${id}`),
    enabled: !!id,
  });
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoryDetail.test.tsx
```

Expected: 1 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCategoryDetail.ts \
        frontend/src/features/categories/hooks/__tests__/useCategoryDetail.test.tsx
git commit -m "feat(frontend): add useCategoryDetail hook

Powers CategoryDetailPage header. Returns 404 → component
maps to page-level not-found per spec §8."
```

---

## Task 6: useCategoryTracks hook (infinite read)

**Files:**

- Create: `frontend/src/features/categories/hooks/useCategoryTracks.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCategoryTracks } from '../useCategoryTracks';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: 'Original Mix',
    artists: [{ id: 'a1', name: 'Artist' }],
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
}

describe('useCategoryTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('paginates with fetchNextPage', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? '0');
        return HttpResponse.json({
          items: offset === 0 ? mkTracks(0, 50) : mkTracks(50, 10),
          total: 60,
          limit: 50,
          offset,
        });
      }),
    );
    const { result } = renderHook(() => useCategoryTracks('c1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].items).toHaveLength(50);
    expect(result.current.hasNextPage).toBe(true);

    await act(() => result.current.fetchNextPage());
    await waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.data?.pages[1].items).toHaveLength(10);
    expect(result.current.hasNextPage).toBe(false);
  });

  it('passes ?search=', async () => {
    let captured = '';
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        captured = new URL(request.url).searchParams.get('search') ?? '';
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    const { result } = renderHook(() => useCategoryTracks('c1', 'tech'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(captured).toBe('tech');
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useCategoryTracks.ts`:

```ts
import { useInfiniteQuery, type UseInfiniteQueryResult, type InfiniteData } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface TrackArtist {
  id: string;
  name: string;
}

export interface CategoryTrack {
  id: string;
  title: string;
  mix_name: string | null;
  artists: TrackArtist[];
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  isrc: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  added_at: string;
  source_triage_block_id: string | null;
}

export interface PaginatedTracks {
  items: CategoryTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export const categoryTracksKey = (id: string, search: string) =>
  ['categories', 'tracks', id, search] as const;

export function useCategoryTracks(
  categoryId: string,
  search: string,
): UseInfiniteQueryResult<InfiniteData<PaginatedTracks>> {
  return useInfiniteQuery({
    queryKey: categoryTracksKey(categoryId, search),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (search) params.set('search', search);
      return api<PaginatedTracks>(`/categories/${categoryId}/tracks?${params.toString()}`);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!categoryId,
  });
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCategoryTracks.ts \
        frontend/src/features/categories/hooks/__tests__/useCategoryTracks.test.tsx
git commit -m "feat(frontend): add useCategoryTracks infinite hook

Page size 50 per spec-C 5.8. getNextPageParam returns offset
based on accumulated items vs total. ?search= passed when
non-empty (TracksTab debounces upstream)."
```

---

## Task 7: useCreateCategory mutation (pessimistic)

**Files:**

- Create: `frontend/src/features/categories/hooks/useCreateCategory.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useCreateCategory.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useCreateCategory } from '../useCreateCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useCreateCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('posts and invalidates byStyle', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: [], total: 0, limit: 200, offset: 0 });
    server.use(
      http.post('http://localhost/styles/s1/categories', async () =>
        HttpResponse.json(
          {
            id: 'c1',
            style_id: 's1',
            style_name: 'House',
            name: 'Deep',
            position: 0,
            track_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    );
    const { result } = renderHook(() => useCreateCategory('s1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'Deep' });
    });
    expect(result.current.data?.name).toBe('Deep');
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });

  it('surfaces 409 error', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    server.use(
      http.post('http://localhost/styles/s1/categories', () =>
        HttpResponse.json(
          { error_code: 'name_conflict', message: 'duplicate', correlation_id: 'c' },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useCreateCategory('s1'), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ name: 'Deep' });
      }),
    ).rejects.toThrow();
    expect(result.current.error).toBeDefined();
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCreateCategory.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useCreateCategory.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { CreateCategoryInput } from '../lib/categorySchemas';
import { categoriesByStyleKey, type Category } from './useCategoriesByStyle';

export function useCreateCategory(
  styleId: string,
): UseMutationResult<Category, Error, CreateCategoryInput> {
  const qc = useQueryClient();
  return useMutation<Category, Error, CreateCategoryInput>({
    mutationFn: (input) =>
      api<Category>(`/styles/${styleId}/categories`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
    },
  });
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useCreateCategory.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useCreateCategory.ts \
        frontend/src/features/categories/hooks/__tests__/useCreateCategory.test.tsx
git commit -m "feat(frontend): add useCreateCategory mutation

Pessimistic per spec D4 — server assigns id/position; cache
invalidates on success. Caller maps 409 to inline form
error."
```

---

## Task 8: useRenameCategory mutation (optimistic)

**Files:**

- Create: `frontend/src/features/categories/hooks/useRenameCategory.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useRenameCategory.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRenameCategory } from '../useRenameCategory';

const baseCategory = {
  id: 'c1',
  style_id: 's1',
  style_name: 'House',
  name: 'Old',
  position: 0,
  track_count: 0,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useRenameCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('patches caches optimistically and confirms on 200', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], {
      items: [baseCategory],
      total: 1,
      limit: 200,
      offset: 0,
    });
    qc.setQueryData(['categories', 'detail', 'c1'], baseCategory);
    server.use(
      http.patch('http://localhost/categories/c1', () =>
        HttpResponse.json({ ...baseCategory, name: 'New' }),
      ),
    );
    const { result } = renderHook(() => useRenameCategory('c1', 's1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ name: 'New' });
    });
    const list = qc.getQueryData<{ items: typeof baseCategory[] }>(['categories', 'byStyle', 's1']);
    expect(list?.items[0].name).toBe('New');
  });

  it('rolls back on 409', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], {
      items: [baseCategory],
      total: 1,
      limit: 200,
      offset: 0,
    });
    server.use(
      http.patch('http://localhost/categories/c1', () =>
        HttpResponse.json(
          { error_code: 'name_conflict', message: 'dup', correlation_id: 'c' },
          { status: 409 },
        ),
      ),
    );
    const { result } = renderHook(() => useRenameCategory('c1', 's1'), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ name: 'New' });
      }),
    ).rejects.toThrow();
    const list = qc.getQueryData<{ items: typeof baseCategory[] }>(['categories', 'byStyle', 's1']);
    expect(list?.items[0].name).toBe('Old');
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useRenameCategory.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useRenameCategory.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { RenameCategoryInput } from '../lib/categorySchemas';
import {
  categoriesByStyleKey,
  type Category,
  type PaginatedCategories,
} from './useCategoriesByStyle';
import { categoryDetailKey } from './useCategoryDetail';

interface Snapshot {
  list: PaginatedCategories | undefined;
  detail: Category | undefined;
}

export function useRenameCategory(
  categoryId: string,
  styleId: string,
): UseMutationResult<Category, Error, RenameCategoryInput, Snapshot> {
  const qc = useQueryClient();
  return useMutation<Category, Error, RenameCategoryInput, Snapshot>({
    mutationFn: (input) =>
      api<Category>(`/categories/${categoryId}`, {
        method: 'PATCH',
        body: JSON.stringify(input),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({ queryKey: categoriesByStyleKey(styleId) });
      await qc.cancelQueries({ queryKey: categoryDetailKey(categoryId) });
      const list = qc.getQueryData<PaginatedCategories>(categoriesByStyleKey(styleId));
      const detail = qc.getQueryData<Category>(categoryDetailKey(categoryId));
      if (list) {
        qc.setQueryData<PaginatedCategories>(categoriesByStyleKey(styleId), {
          ...list,
          items: list.items.map((c) =>
            c.id === categoryId ? { ...c, name: input.name } : c,
          ),
        });
      }
      if (detail) {
        qc.setQueryData<Category>(categoryDetailKey(categoryId), { ...detail, name: input.name });
      }
      return { list, detail };
    },
    onError: (_err, _input, ctx) => {
      if (ctx?.list) qc.setQueryData(categoriesByStyleKey(styleId), ctx.list);
      if (ctx?.detail) qc.setQueryData(categoryDetailKey(categoryId), ctx.detail);
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
      qc.invalidateQueries({ queryKey: categoryDetailKey(categoryId) });
    },
  });
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useRenameCategory.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useRenameCategory.ts \
        frontend/src/features/categories/hooks/__tests__/useRenameCategory.test.tsx
git commit -m "feat(frontend): add useRenameCategory optimistic hook

onMutate snapshots both byStyle list and detail caches and
patches them; onError rolls back; onSettled invalidates per
spec D4 + D11."
```

---

## Task 9: useDeleteCategory mutation (pessimistic)

**Files:**

- Create: `frontend/src/features/categories/hooks/useDeleteCategory.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useDeleteCategory.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useDeleteCategory } from '../useDeleteCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useDeleteCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('deletes and invalidates byStyle', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: [], total: 0, limit: 200, offset: 0 });
    server.use(
      http.delete('http://localhost/categories/c1', () => new HttpResponse(null, { status: 204 })),
    );
    const { result } = renderHook(() => useDeleteCategory('s1'), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync('c1');
    });
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useDeleteCategory.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useDeleteCategory.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { categoriesByStyleKey } from './useCategoriesByStyle';

export function useDeleteCategory(
  styleId: string,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: async (categoryId: string) => {
      await api(`/categories/${categoryId}`, { method: 'DELETE' });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
    },
  });
}
```

The mutation takes the `categoryId` as the variable so a single hook instance can serve multiple rows on the list page.

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useDeleteCategory.test.tsx
```

Expected: 1 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useDeleteCategory.ts \
        frontend/src/features/categories/hooks/__tests__/useDeleteCategory.test.tsx
git commit -m "feat(frontend): add useDeleteCategory mutation

Pessimistic — confirm modal already provides friction; on
success invalidate byStyle cache."
```

---

## Task 10: useReorderCategories mutation (debounced + optimistic)

**Files:**

- Create: `frontend/src/features/categories/hooks/useReorderCategories.ts`
- Create: `frontend/src/features/categories/hooks/__tests__/useReorderCategories.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useReorderCategories } from '../useReorderCategories';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const cats = [
  { id: 'c1', position: 0 },
  { id: 'c2', position: 1 },
  { id: 'c3', position: 2 },
];

describe('useReorderCategories', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    vi.useFakeTimers();
  });

  it('coalesces multiple swaps into one PUT', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    let putCount = 0;
    let lastBody: { category_ids: string[] } | null = null;
    server.use(
      http.put('http://localhost/styles/s1/categories/order', async ({ request }) => {
        putCount += 1;
        lastBody = (await request.json()) as { category_ids: string[] };
        return HttpResponse.json({ items: cats });
      }),
    );
    const { result } = renderHook(() => useReorderCategories('s1'), { wrapper: wrap(qc) });

    act(() => result.current.queueOrder(['c2', 'c1', 'c3']));
    act(() => result.current.queueOrder(['c2', 'c3', 'c1']));
    act(() => result.current.queueOrder(['c3', 'c2', 'c1']));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });

    expect(putCount).toBe(1);
    expect(lastBody?.category_ids).toEqual(['c3', 'c2', 'c1']);
  });

  it('invalidates on 422 order_mismatch', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    qc.setQueryData(['categories', 'byStyle', 's1'], { items: cats, total: 3, limit: 200, offset: 0 });
    server.use(
      http.put('http://localhost/styles/s1/categories/order', () =>
        HttpResponse.json(
          { error_code: 'order_mismatch', message: 'race', correlation_id: 'c' },
          { status: 422 },
        ),
      ),
    );
    const { result } = renderHook(() => useReorderCategories('s1'), { wrapper: wrap(qc) });
    act(() => result.current.queueOrder(['c2', 'c1', 'c3']));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    await act(async () => {
      await vi.runAllTimersAsync();
    });
    const state = qc.getQueryState(['categories', 'byStyle', 's1']);
    expect(state?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useReorderCategories.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/hooks/useReorderCategories.ts`:

```ts
import { useCallback, useEffect, useRef } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { categoriesByStyleKey } from './useCategoriesByStyle';

const DEBOUNCE_MS = 200;

export interface ReorderHandle {
  queueOrder: (categoryIds: string[]) => void;
  flushNow: () => Promise<void>;
}

export function useReorderCategories(styleId: string): ReorderHandle {
  const qc = useQueryClient();
  const { t } = useTranslation();
  const latestRef = useRef<string[] | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const mutation = useMutation<unknown, Error, string[]>({
    mutationFn: (categoryIds) =>
      api(`/styles/${styleId}/categories/order`, {
        method: 'PUT',
        body: JSON.stringify({ category_ids: categoryIds }),
      }),
    onError: (err) => {
      const isMismatch =
        err instanceof ApiError && err.status === 422 && err.errorCode === 'order_mismatch';
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
      notifications.show({
        message: isMismatch
          ? t('categories.toast.race_refreshed')
          : t('categories.toast.generic_error'),
        color: isMismatch ? 'yellow' : 'red',
      });
    },
  });

  const flush = useCallback(async () => {
    const order = latestRef.current;
    latestRef.current = null;
    timerRef.current = null;
    if (!order) return;
    await mutation.mutateAsync(order);
  }, [mutation]);

  const queueOrder = useCallback(
    (categoryIds: string[]) => {
      latestRef.current = categoryIds;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = setTimeout(() => {
        void flush();
      }, DEBOUNCE_MS);
    },
    [flush],
  );

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  return { queueOrder, flushNow: flush };
}
```

- [ ] **Step 4: Patch ApiError if `errorCode` field is missing**

Open `frontend/src/api/error.ts` and confirm `ApiError` exposes `status` and `errorCode`. If `errorCode` is named differently (e.g. `code`), align the hook above to the actual field name. Read the file first:

```bash
cat frontend/src/api/error.ts
```

If a name change is required, edit the hook to match — do not change `error.ts` for this. Re-run the test after.

- [ ] **Step 5: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/hooks/__tests__/useReorderCategories.test.tsx
```

Expected: 2 passing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/categories/hooks/useReorderCategories.ts \
        frontend/src/features/categories/hooks/__tests__/useReorderCategories.test.tsx
git commit -m "feat(frontend): add useReorderCategories debounced hook

200ms coalesce of rapid swaps to one PUT body. Optimistic
cache patching is the caller's responsibility; this hook only
owns the network + race-recovery via cache invalidate +
toast (spec D7)."
```

---

## Task 11: i18n keys for categories namespace

**Files:**

- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Read the existing en.json**

```bash
cat frontend/src/i18n/en.json
```

- [ ] **Step 2: Append the `categories` namespace**

Insert the following object as a sibling of the existing top-level keys (`auth`, `appshell`, `user_menu`, `empty_state`, `errors`, `long_op`). Match existing JSON style (4-space indent, double quotes):

```json
"categories": {
  "page_title": "Categories",
  "create_cta": "Create category",
  "loading": "Loading categories…",
  "track_count_one": "{{count}} track",
  "track_count_other": "{{count}} tracks",
  "row_menu": { "rename": "Rename", "delete": "Delete" },
  "form": {
    "name_label": "Name",
    "name_description": "Up to 64 characters.",
    "name_placeholder": "Tech House",
    "create_title": "Create category",
    "rename_title": "Rename category",
    "save": "Save",
    "create_submit": "Create",
    "cancel": "Cancel"
  },
  "delete_modal": {
    "title": "Delete category?",
    "body": "Delete '{{name}}'? Tracks remain in history but become invisible.",
    "confirm": "Delete",
    "cancel": "Cancel"
  },
  "toast": {
    "created": "Category created.",
    "renamed": "Category renamed.",
    "deleted": "Category deleted.",
    "race_refreshed": "List changed elsewhere — refreshed.",
    "generic_error": "Couldn't save changes. Please retry."
  },
  "errors": {
    "name_required": "Name is required.",
    "name_too_long": "Name must be 64 characters or less.",
    "name_control_chars": "Name contains forbidden characters.",
    "name_conflict": "A category with this name already exists in this style."
  },
  "empty_state": {
    "no_categories_title": "No categories yet",
    "no_categories_body": "Create your first category for {{style_name}}.",
    "no_tracks_title": "No tracks yet",
    "no_tracks_body": "Finalize a triage block to populate this category.",
    "no_search_results_title": "No tracks match '{{term}}'.",
    "clear_search": "Clear search"
  },
  "no_styles": {
    "title": "No styles available",
    "body": "Styles are populated by admin ingest. Ask an admin to seed Beatport data."
  },
  "detail": {
    "tracks_search_placeholder": "Search by title…",
    "tracks_load_more": "Show more ({{remaining}} remaining)",
    "back_to_list": "Back to categories",
    "actions": { "rename": "Rename", "delete": "Delete" }
  },
  "tracks_table": {
    "title": "Title",
    "artists": "Artists",
    "bpm": "BPM",
    "length": "Length",
    "added": "Added",
    "ai_suspected_aria": "AI-suspected"
  }
}
```

- [ ] **Step 3: Run typecheck + tests**

```bash
cd frontend
pnpm typecheck && pnpm test
```

Expected: typecheck clean; existing tests still pass (no test references categories keys yet).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(frontend): add categories i18n namespace (en)

Full key map per F1 spec §10. RU mirror lands in iter-2b.
Domain terms (BPM, Length, Added) stay literal per CLAUDE.md
memory."
```

---

## Task 12: StyleSelector component

**Files:**

- Create: `frontend/src/features/categories/components/StyleSelector.tsx`
- Create: `frontend/src/features/categories/components/__tests__/StyleSelector.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { StyleSelector } from '../StyleSelector';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('StyleSelector', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders styles and fires onChange', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's1', name: 'House' },
            { id: 's2', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    const onChange = vi.fn();
    render(
      <Wrapper>
        <StyleSelector value="s1" onChange={onChange} />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByDisplayValue('House')).toBeInTheDocument());
    await userEvent.click(screen.getByDisplayValue('House'));
    await userEvent.click(screen.getByText('Tech House'));
    expect(onChange).toHaveBeenCalledWith('s2');
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/StyleSelector.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/components/StyleSelector.tsx`:

```tsx
import { Select } from '@mantine/core';
import { useStyles } from '../hooks/useStyles';

export interface StyleSelectorProps {
  value: string;
  onChange: (styleId: string) => void;
}

export function StyleSelector({ value, onChange }: StyleSelectorProps) {
  const { data, isLoading } = useStyles();
  const items = data?.items ?? [];
  return (
    <Select
      data={items.map((s) => ({ value: s.id, label: s.name }))}
      value={value}
      onChange={(v) => v && onChange(v)}
      disabled={isLoading || items.length === 0}
      allowDeselect={false}
      searchable
      maxDropdownHeight={300}
      w={220}
    />
  );
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/StyleSelector.test.tsx
```

Expected: 1 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/StyleSelector.tsx \
        frontend/src/features/categories/components/__tests__/StyleSelector.test.tsx
git commit -m "feat(frontend): add StyleSelector component

Mantine Select sourcing from useStyles. Search-enabled for
10+ styles. allowDeselect=false because callers expect
non-empty value at all times."
```

---

## Task 13: CategoryFormDialog component (create + rename)

**Files:**

- Create: `frontend/src/features/categories/components/CategoryFormDialog.tsx`
- Create: `frontend/src/features/categories/components/__tests__/CategoryFormDialog.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { CategoryFormDialog } from '../CategoryFormDialog';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

describe('CategoryFormDialog', () => {
  beforeEach(() => {
    Object.defineProperty(window, 'matchMedia', {
      writable: true,
      value: (q: string) => ({
        matches: false,
        media: q,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }),
    });
  });

  it('shows inline error on empty submit', async () => {
    const onSubmit = vi.fn();
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="create"
          opened
          initialName=""
          submitting={false}
          onClose={() => {}}
          onSubmit={onSubmit}
        />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    expect(await screen.findByText(/name is required/i)).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it('submits valid name', async () => {
    const onSubmit = vi.fn();
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="create"
          opened
          initialName=""
          submitting={false}
          onClose={() => {}}
          onSubmit={onSubmit}
        />
      </Wrapper>,
    );
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), 'Tech House');
    await userEvent.click(screen.getByRole('button', { name: /create/i }));
    expect(onSubmit).toHaveBeenCalledWith({ name: 'Tech House' });
  });

  it('shows server error from prop', async () => {
    render(
      <Wrapper>
        <CategoryFormDialog
          mode="rename"
          opened
          initialName="Old"
          submitting={false}
          onClose={() => {}}
          onSubmit={() => {}}
          serverError="A category with this name already exists in this style."
        />
      </Wrapper>,
    );
    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/CategoryFormDialog.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/components/CategoryFormDialog.tsx`:

```tsx
import { useEffect } from 'react';
import { Button, Drawer, Group, Modal, Stack, TextInput } from '@mantine/core';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { createCategorySchema, type CreateCategoryInput } from '../lib/categorySchemas';

export type CategoryFormMode = 'create' | 'rename';

export interface CategoryFormDialogProps {
  mode: CategoryFormMode;
  opened: boolean;
  initialName: string;
  submitting: boolean;
  onClose: () => void;
  onSubmit: (input: CreateCategoryInput) => void;
  serverError?: string;
}

export function CategoryFormDialog({
  mode,
  opened,
  initialName,
  submitting,
  onClose,
  onSubmit,
  serverError,
}: CategoryFormDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const form = useForm<CreateCategoryInput>({
    initialValues: { name: initialName },
    validate: zodResolver(createCategorySchema),
  });

  useEffect(() => {
    if (opened) form.setValues({ name: initialName });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [opened, initialName]);

  const title = mode === 'create' ? t('categories.form.create_title') : t('categories.form.rename_title');
  const submitLabel = mode === 'create' ? t('categories.form.create_submit') : t('categories.form.save');

  const errorMap: Record<string, string> = {
    name_required: t('categories.errors.name_required'),
    name_too_long: t('categories.errors.name_too_long'),
    name_control_chars: t('categories.errors.name_control_chars'),
  };
  const fieldError = (() => {
    if (serverError) return serverError;
    const e = form.errors.name;
    if (!e) return undefined;
    return errorMap[String(e)] ?? String(e);
  })();

  const body = (
    <form onSubmit={form.onSubmit((values) => onSubmit({ name: values.name.trim() }))}>
      <Stack gap="md">
        <TextInput
          label={t('categories.form.name_label')}
          description={t('categories.form.name_description')}
          placeholder={t('categories.form.name_placeholder')}
          autoFocus
          maxLength={64}
          error={fieldError}
          {...form.getInputProps('name')}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="default" onClick={onClose} disabled={submitting}>
            {t('categories.form.cancel')}
          </Button>
          <Button type="submit" loading={submitting}>
            {submitLabel}
          </Button>
        </Group>
      </Stack>
    </form>
  );

  if (isMobile) {
    return (
      <Drawer opened={opened} onClose={onClose} position="bottom" size="auto" title={title}>
        {body}
      </Drawer>
    );
  }
  return (
    <Modal opened={opened} onClose={onClose} title={title} centered>
      {body}
    </Modal>
  );
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/CategoryFormDialog.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/CategoryFormDialog.tsx \
        frontend/src/features/categories/components/__tests__/CategoryFormDialog.test.tsx
git commit -m "feat(frontend): add CategoryFormDialog (create + rename)

Modal on desktop / Drawer (bottom) on mobile per spec D5.
Mantine form + zod resolver. Server error overrides client
error when present (rename 409 path)."
```

---

## Task 14: CategoryRow sortable component

**Files:**

- Create: `frontend/src/features/categories/components/CategoryRow.tsx`
- Create: `frontend/src/features/categories/components/__tests__/CategoryRow.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { DndContext } from '@dnd-kit/core';
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable';
import { CategoryRow } from '../CategoryRow';

function Wrapper({ children }: { children: React.ReactNode }) {
  return (
    <MantineProvider>
      <MemoryRouter>
        <DndContext>
          <SortableContext items={['c1']} strategy={verticalListSortingStrategy}>
            {children}
          </SortableContext>
        </DndContext>
      </MemoryRouter>
    </MantineProvider>
  );
}

const cat = {
  id: 'c1',
  style_id: 's1',
  style_name: 'House',
  name: 'Deep',
  position: 0,
  track_count: 12,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

describe('CategoryRow', () => {
  it('renders name and track count', () => {
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={() => {}} onDelete={() => {}} />
      </Wrapper>,
    );
    expect(screen.getByText('Deep')).toBeInTheDocument();
    expect(screen.getByText('12 tracks')).toBeInTheDocument();
  });

  it('exposes drag handle with aria-roledescription', () => {
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={() => {}} onDelete={() => {}} />
      </Wrapper>,
    );
    const handle = screen.getByRole('button', { name: /drag/i });
    expect(handle).toHaveAttribute('aria-roledescription', 'sortable');
  });

  it('fires onRename when kebab → Rename clicked', async () => {
    const onRename = vi.fn();
    render(
      <Wrapper>
        <CategoryRow category={cat} onRename={onRename} onDelete={() => {}} />
      </Wrapper>,
    );
    await userEvent.click(screen.getByRole('button', { name: /actions/i }));
    await userEvent.click(screen.getByText('Rename'));
    expect(onRename).toHaveBeenCalledWith(cat);
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/CategoryRow.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/components/CategoryRow.tsx`:

```tsx
import { ActionIcon, Badge, Group, Menu, Text } from '@mantine/core';
import { useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import { IconDotsVertical, IconGripVertical } from '@tabler/icons-react';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { Category } from '../hooks/useCategoriesByStyle';

export interface CategoryRowProps {
  category: Category;
  onRename: (c: Category) => void;
  onDelete: (c: Category) => void;
}

export function CategoryRow({ category, onRename, onDelete }: CategoryRowProps) {
  const { t } = useTranslation();
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: category.id,
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  return (
    <Group
      ref={setNodeRef}
      style={style}
      gap="sm"
      wrap="nowrap"
      p="sm"
      bg="var(--color-bg-elevated)"
      bd="1px solid var(--color-border)"
    >
      <ActionIcon
        variant="subtle"
        aria-label="Drag handle"
        aria-roledescription="sortable"
        {...attributes}
        {...listeners}
        style={{ cursor: 'grab', touchAction: 'none' }}
      >
        <IconGripVertical size={18} />
      </ActionIcon>
      <Text component={Link} to={`/categories/${category.style_id}/${category.id}`} fw={500} flex={1}>
        {category.name}
      </Text>
      <Badge variant="default" size="sm">
        {t('categories.track_count', { count: category.track_count })}
      </Badge>
      <Menu>
        <Menu.Target>
          <ActionIcon variant="subtle" aria-label="Actions">
            <IconDotsVertical size={18} />
          </ActionIcon>
        </Menu.Target>
        <Menu.Dropdown>
          <Menu.Item onClick={() => onRename(category)}>{t('categories.row_menu.rename')}</Menu.Item>
          <Menu.Item color="red" onClick={() => onDelete(category)}>
            {t('categories.row_menu.delete')}
          </Menu.Item>
        </Menu.Dropdown>
      </Menu>
    </Group>
  );
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/CategoryRow.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/CategoryRow.tsx \
        frontend/src/features/categories/components/__tests__/CategoryRow.test.tsx
git commit -m "feat(frontend): add CategoryRow sortable component

useSortable from @dnd-kit/sortable. Drag listeners scoped to
the handle (not the whole row) so name link remains
clickable. Pluralised track_count via i18next."
```

---

## Task 15: CategoriesList (DndContext wrapper)

**Files:**

- Create: `frontend/src/features/categories/components/CategoriesList.tsx`

- [ ] **Step 1: Implement (no test — exercised by route integration test in Task 19)**

Create `frontend/src/features/categories/components/CategoriesList.tsx`:

```tsx
import { useMemo } from 'react';
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import { SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, arrayMove } from '@dnd-kit/sortable';
import { Stack } from '@mantine/core';
import type { Category } from '../hooks/useCategoriesByStyle';
import { CategoryRow } from './CategoryRow';

export interface CategoriesListProps {
  categories: Category[];
  onReorder: (orderedIds: string[]) => void;
  onRename: (c: Category) => void;
  onDelete: (c: Category) => void;
}

export function CategoriesList({ categories, onReorder, onRename, onDelete }: CategoriesListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );
  const ids = useMemo(() => categories.map((c) => c.id), [categories]);

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const oldIndex = ids.indexOf(String(active.id));
    const newIndex = ids.indexOf(String(over.id));
    if (oldIndex === -1 || newIndex === -1) return;
    const next = arrayMove(ids, oldIndex, newIndex);
    onReorder(next);
  }

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <SortableContext items={ids} strategy={verticalListSortingStrategy}>
        <Stack gap="xs">
          {categories.map((c) => (
            <CategoryRow key={c.id} category={c} onRename={onRename} onDelete={onDelete} />
          ))}
        </Stack>
      </SortableContext>
    </DndContext>
  );
}
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/categories/components/CategoriesList.tsx
git commit -m "feat(frontend): add CategoriesList DnD container

DndContext + SortableContext wrap. PointerSensor with 5px
activation prevents accidental drags from row clicks.
KeyboardSensor wires Tab/Space/Arrow per @dnd-kit a11y."
```

---

## Task 16: TrackRow + TracksTab components

**Files:**

- Create: `frontend/src/features/categories/components/TrackRow.tsx`
- Create: `frontend/src/features/categories/components/TracksTab.tsx`
- Create: `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`

- [ ] **Step 1: Implement TrackRow (no separate test — exercised by TracksTab test)**

Create `frontend/src/features/categories/components/TrackRow.tsx`:

```tsx
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

function formatLength(ms: number | null): string {
  if (!ms) return '—';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function formatAdded(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', year: 'numeric' }).format(date);
}

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}

export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
}

export function TrackRow({ track, variant }: TrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle size={14} aria-label={t('categories.tracks_table.ai_suspected_aria')} color="var(--color-warning)" />
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
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td>{formatAdded(track.added_at)}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm">
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
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          <Text size="xs" c="dimmed">
            {formatAdded(track.added_at)}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 2: Write failing TracksTab test**

Create `frontend/src/features/categories/components/__tests__/TracksTab.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { TracksTab } from '../TracksTab';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    </MantineProvider>
  );
}

function mkTracks(start: number, count: number) {
  return Array.from({ length: count }, (_, i) => ({
    id: `t${start + i}`,
    title: `Track ${start + i}`,
    mix_name: null,
    artists: [{ id: 'a1', name: 'Artist' }],
    bpm: 120,
    length_ms: 360000,
    publish_date: '2026-01-01',
    isrc: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    added_at: '2026-01-01T00:00:00Z',
    source_triage_block_id: null,
  }));
}

describe('TracksTab', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders first page + load-more', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset') ?? '0');
        return HttpResponse.json({
          items: offset === 0 ? mkTracks(0, 50) : mkTracks(50, 10),
          total: 60,
          limit: 50,
          offset,
        });
      }),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Track 0')).toBeInTheDocument());
    expect(screen.getByText(/Show more \(10 remaining\)/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/Show more/i));
    await waitFor(() => expect(screen.getByText('Track 50')).toBeInTheDocument());
    expect(screen.queryByText(/Show more/i)).not.toBeInTheDocument();
  });

  it('shows empty-search state', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await userEvent.type(screen.getByPlaceholderText(/search by title/i), 'zzz');
    await waitFor(() => expect(screen.getByText(/no tracks match 'zzz'/i)).toBeInTheDocument());
  });

  it('shows no-tracks empty state', async () => {
    server.use(
      http.get('http://localhost/categories/c1/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <TracksTab categoryId="c1" />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/TracksTab.test.tsx
```

Expected: FAIL.

- [ ] **Step 4: Implement TracksTab**

Create `frontend/src/features/categories/components/TracksTab.tsx`:

```tsx
import { useEffect, useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { IconSearch, IconX } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { useCategoryTracks } from '../hooks/useCategoryTracks';
import { TrackRow } from './TrackRow';
import { EmptyState } from '../../../components/EmptyState';

export interface TracksTabProps {
  categoryId: string;
}

export function TracksTab({ categoryId }: TracksTabProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim().toLowerCase(), 300);

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useCategoryTracks(
    categoryId,
    debounced,
  );

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
          <IconX size={16} role="button" onClick={() => setRawSearch('')} style={{ cursor: 'pointer' }} />
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
        {items.map((t) => (
          <TrackRow key={t.id} track={t} variant="mobile" />
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
            <Table.Th>{t('categories.tracks_table.title')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.artists')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.bpm')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.length')}</Table.Th>
            <Table.Th>{t('categories.tracks_table.added')}</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {items.map((track) => (
            <TrackRow key={track.id} track={track} variant="desktop" />
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

- [ ] **Step 5: Confirm `EmptyState` accepts `body` as ReactNode**

```bash
grep -n "body" frontend/src/components/EmptyState.tsx
```

If `body` is typed as `string` only, update it to `string | ReactNode` in `EmptyState.tsx` — the test (Task 16) renders a button as body. Single-line type widening, no behaviour change.

- [ ] **Step 6: Run test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/components/__tests__/TracksTab.test.tsx
```

Expected: 3 passing.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/categories/components/TrackRow.tsx \
        frontend/src/features/categories/components/TracksTab.tsx \
        frontend/src/features/categories/components/__tests__/TracksTab.test.tsx \
        frontend/src/components/EmptyState.tsx
git commit -m "feat(frontend): add TracksTab + TrackRow

Search debounced 300ms (lowercased trim → ?search=). Load-more
button until total reached. Table desktop, Card stack mobile,
EmptyState branches for no-tracks vs zero-results."
```

---

## Task 17: CategoriesIndexRedirect route

**Files:**

- Create: `frontend/src/features/categories/routes/CategoriesIndexRedirect.tsx`
- Create: `frontend/src/features/categories/routes/__tests__/CategoriesIndexRedirect.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { writeLastVisitedStyle } from '../../lib/lastVisitedStyle';
import { CategoriesIndexRedirect } from '../CategoriesIndexRedirect';

function Wrapper({ initialEntries }: { initialEntries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={initialEntries}>
          <Routes>
            <Route path="/categories" element={<CategoriesIndexRedirect />} />
            <Route path="/categories/:styleId" element={<div data-testid="landed">landed</div>} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>
  );
}

describe('CategoriesIndexRedirect', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
  });

  it('redirects to first style when nothing stored', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's-first', name: 'House' },
            { id: 's-other', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByTestId('landed')).toBeInTheDocument());
    expect(window.location.pathname).toBe('/'); // jsdom — actual URL handled by MemoryRouter
  });

  it('uses stored style id when present', async () => {
    writeLastVisitedStyle('s-other');
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [
            { id: 's-first', name: 'House' },
            { id: 's-other', name: 'Tech House' },
          ],
          total: 2,
          limit: 200,
          offset: 0,
        }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByTestId('landed')).toBeInTheDocument());
  });

  it('shows no-styles state when list empty', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(<Wrapper initialEntries={['/categories']} />);
    await waitFor(() => expect(screen.getByText(/no styles available/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoriesIndexRedirect.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/routes/CategoriesIndexRedirect.tsx`:

```tsx
import { Navigate } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useStyles } from '../hooks/useStyles';
import { readLastVisitedStyle } from '../lib/lastVisitedStyle';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';

export function CategoriesIndexRedirect() {
  const { t } = useTranslation();
  const { data, isLoading, isError } = useStyles();
  if (isLoading) return <FullScreenLoader />;
  if (isError || !data) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  const items = data.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState title={t('categories.no_styles.title')} body={t('categories.no_styles.body')} />
    );
  }
  const last = readLastVisitedStyle();
  const target = items.find((s) => s.id === last)?.id ?? items[0].id;
  return <Navigate to={`/categories/${target}`} replace />;
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoriesIndexRedirect.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/routes/CategoriesIndexRedirect.tsx \
        frontend/src/features/categories/routes/__tests__/CategoriesIndexRedirect.test.tsx
git commit -m "feat(frontend): add CategoriesIndexRedirect

Routes /categories → /categories/:style_id using last visited
(localStorage) or first style. Empty-styles state visible
when admin ingest hasn't seeded data."
```

---

## Task 18: CategoriesListPage route

**Files:**

- Create: `frontend/src/features/categories/routes/CategoriesListPage.tsx`
- Create: `frontend/src/features/categories/routes/__tests__/CategoriesListPage.test.tsx`

- [ ] **Step 1: Write the failing integration test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { CategoriesListPage } from '../CategoriesListPage';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/categories/s1']}>
            <Routes>
              <Route path="/categories/:styleId" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

const seed = [
  {
    id: 'c1',
    style_id: 's1',
    style_name: 'House',
    name: 'Deep',
    position: 0,
    track_count: 3,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
];

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/styles', () =>
      HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/categories', () =>
      HttpResponse.json({ items: seed, total: 1, limit: 200, offset: 0 }),
    ),
  );
});

describe('CategoriesListPage', () => {
  it('renders category rows', async () => {
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Deep')).toBeInTheDocument());
  });

  it('opens create dialog and posts new category', async () => {
    server.use(
      http.post('http://localhost/styles/s1/categories', async () =>
        HttpResponse.json(
          {
            id: 'c2',
            style_id: 's1',
            style_name: 'House',
            name: 'New',
            position: 1,
            track_count: 0,
            created_at: '2026-01-01T00:00:00Z',
            updated_at: '2026-01-01T00:00:00Z',
          },
          { status: 201 },
        ),
      ),
    );
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await userEvent.click(await screen.findByRole('button', { name: /create category/i }));
    await userEvent.type(screen.getByRole('textbox', { name: /name/i }), 'New');
    await userEvent.click(screen.getByRole('button', { name: /^create$/i }));
    // pessimistic: dialog closes after success — assert by button gone
    await waitFor(() => expect(screen.queryByRole('button', { name: /^create$/i })).not.toBeInTheDocument());
  });

  it('shows empty state when no categories', async () => {
    server.use(
      http.get('http://localhost/styles/s1/categories', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <CategoriesListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/no categories yet/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoriesListPage.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/routes/CategoriesListPage.tsx`:

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { IconPlus } from '@tabler/icons-react';
import { Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import {
  categoriesByStyleKey,
  useCategoriesByStyle,
  type Category,
  type PaginatedCategories,
} from '../hooks/useCategoriesByStyle';
import { useStyles } from '../hooks/useStyles';
import { useCreateCategory } from '../hooks/useCreateCategory';
import { useRenameCategory } from '../hooks/useRenameCategory';
import { useDeleteCategory } from '../hooks/useDeleteCategory';
import { useReorderCategories } from '../hooks/useReorderCategories';
import { StyleSelector } from '../components/StyleSelector';
import { CategoriesList } from '../components/CategoriesList';
import { CategoryFormDialog } from '../components/CategoryFormDialog';
import { writeLastVisitedStyle } from '../lib/lastVisitedStyle';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { ApiError } from '../../../api/error';

export function CategoriesListPage() {
  const { styleId } = useParams<{ styleId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const qc = useQueryClient();

  if (!styleId) return <Navigate to="/categories" replace />;

  const { data, isLoading, isError } = useCategoriesByStyle(styleId);
  const { data: stylesData } = useStyles();
  const create = useCreateCategory(styleId);
  const reorder = useReorderCategories(styleId);
  const styleName = stylesData?.items.find((s) => s.id === styleId)?.name ?? '';

  const [createOpen, setCreateOpen] = useState(false);
  const [renameTarget, setRenameTarget] = useState<Category | null>(null);
  const [createServerError, setCreateServerError] = useState<string | undefined>();
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  const renameMut = useRenameCategory(renameTarget?.id ?? '', styleId);
  const deleteMut = useDeleteCategory(styleId);

  const list = data?.items ?? [];

  function changeStyle(newStyleId: string) {
    writeLastVisitedStyle(newStyleId);
    navigate(`/categories/${newStyleId}`);
  }

  async function handleCreate(input: { name: string }) {
    setCreateServerError(undefined);
    try {
      await create.mutateAsync(input);
      notifications.show({ message: t('categories.toast.created'), color: 'green' });
      setCreateOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setCreateServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  async function handleRename(input: { name: string }) {
    if (!renameTarget) return;
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync(input);
      notifications.show({ message: t('categories.toast.renamed'), color: 'green' });
      setRenameTarget(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  function openDelete(c: Category) {
    modals.openConfirmModal({
      title: t('categories.delete_modal.title'),
      children: t('categories.delete_modal.body', { name: c.name }),
      labels: { confirm: t('categories.delete_modal.confirm'), cancel: t('categories.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(c.id);
          notifications.show({ message: t('categories.toast.deleted'), color: 'green' });
        } catch {
          notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  function onReorder(orderedIds: string[]) {
    const cur = qc.getQueryData<PaginatedCategories>(categoriesByStyleKey(styleId));
    if (!cur) return;
    const byId = new Map(cur.items.map((c) => [c.id, c]));
    qc.setQueryData<PaginatedCategories>(categoriesByStyleKey(styleId), {
      ...cur,
      items: orderedIds.map((id, idx) => ({ ...(byId.get(id) as Category), position: idx })),
    });
    reorder.queueOrder(orderedIds);
  }

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="center">
        <Title order={1}>{t('categories.page_title')}</Title>
        <Group gap="sm">
          <StyleSelector value={styleId} onChange={changeStyle} />
          <Button leftSection={<IconPlus size={16} />} onClick={() => setCreateOpen(true)}>
            {t('categories.create_cta')}
          </Button>
        </Group>
      </Group>

      {list.length === 0 ? (
        <EmptyState
          title={t('categories.empty_state.no_categories_title')}
          body={t('categories.empty_state.no_categories_body', { style_name: styleName })}
        />
      ) : (
        <CategoriesList
          categories={list}
          onReorder={onReorder}
          onRename={(c) => setRenameTarget(c)}
          onDelete={openDelete}
        />
      )}

      <CategoryFormDialog
        mode="create"
        opened={createOpen}
        initialName=""
        submitting={create.isPending}
        onClose={() => {
          setCreateOpen(false);
          setCreateServerError(undefined);
        }}
        onSubmit={handleCreate}
        serverError={createServerError}
      />
      <CategoryFormDialog
        mode="rename"
        opened={!!renameTarget}
        initialName={renameTarget?.name ?? ''}
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameTarget(null);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverError={renameServerError}
      />
    </Stack>
  );
}
```

- [ ] **Step 4: Run the page test, verify pass**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoriesListPage.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/routes/CategoriesListPage.tsx \
        frontend/src/features/categories/routes/__tests__/CategoriesListPage.test.tsx
git commit -m "feat(frontend): add CategoriesListPage

Wires StyleSelector + CategoriesList + CategoryFormDialog +
delete confirm modal. Optimistic reorder via local cache
patch + debounced PUT (useReorderCategories). 409 maps to
inline form error per spec D11."
```

---

## Task 19: CategoryDetailPage route

**Files:**

- Create: `frontend/src/features/categories/routes/CategoryDetailPage.tsx`
- Create: `frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { CategoryDetailPage } from '../CategoryDetailPage';

function Wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <MantineProvider>
      <ModalsProvider>
        <Notifications />
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={['/categories/s1/c1']}>
            <Routes>
              <Route path="/categories/:styleId/:id" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/categories/c1', () =>
      HttpResponse.json({
        id: 'c1',
        style_id: 's1',
        style_name: 'House',
        name: 'Deep',
        position: 0,
        track_count: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
      }),
    ),
    http.get('http://localhost/categories/c1/tracks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
  );
});

describe('CategoryDetailPage', () => {
  it('renders header and empty tracks state', async () => {
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('Deep')).toBeInTheDocument());
    expect(screen.getByText(/no tracks yet/i)).toBeInTheDocument();
  });

  it('shows not-found on 404', async () => {
    server.use(
      http.get('http://localhost/categories/c1', () =>
        HttpResponse.json(
          { error_code: 'category_not_found', message: 'gone', correlation_id: 'c' },
          { status: 404 },
        ),
      ),
    );
    render(
      <Wrapper>
        <CategoryDetailPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/not found/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run, verify failure**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Create `frontend/src/features/categories/routes/CategoryDetailPage.tsx`:

```tsx
import { useState } from 'react';
import { Anchor, Breadcrumbs, Button, Group, Stack, Text, Title } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { ApiError } from '../../../api/error';
import { useCategoryDetail } from '../hooks/useCategoryDetail';
import { useRenameCategory } from '../hooks/useRenameCategory';
import { useDeleteCategory } from '../hooks/useDeleteCategory';
import { CategoryFormDialog } from '../components/CategoryFormDialog';
import { TracksTab } from '../components/TracksTab';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';

export function CategoryDetailPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  if (!styleId || !id) return <Navigate to="/categories" replace />;

  const { data, isLoading, isError, error } = useCategoryDetail(id);
  const renameMut = useRenameCategory(id, styleId);
  const deleteMut = useDeleteCategory(styleId);
  const [renameOpen, setRenameOpen] = useState(false);
  const [renameServerError, setRenameServerError] = useState<string | undefined>();

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    if (error instanceof ApiError && error.status === 404) {
      return <EmptyState title={t('errors.not_found')} body={<Anchor component={Link} to={`/categories/${styleId}`}>{t('categories.detail.back_to_list')}</Anchor>} />;
    }
    return <EmptyState title={t('errors.unknown')} body={t('errors.server_error')} />;
  }
  if (!data) return null;

  const trackCountLabel = t('categories.track_count', { count: data.track_count });

  function openDelete() {
    modals.openConfirmModal({
      title: t('categories.delete_modal.title'),
      children: t('categories.delete_modal.body', { name: data.name }),
      labels: { confirm: t('categories.delete_modal.confirm'), cancel: t('categories.delete_modal.cancel') },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMut.mutateAsync(id);
          notifications.show({ message: t('categories.toast.deleted'), color: 'green' });
          navigate(`/categories/${styleId}`);
        } catch {
          notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
        }
      },
    });
  }

  async function handleRename(input: { name: string }) {
    setRenameServerError(undefined);
    try {
      await renameMut.mutateAsync(input);
      notifications.show({ message: t('categories.toast.renamed'), color: 'green' });
      setRenameOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setRenameServerError(t('categories.errors.name_conflict'));
      } else {
        notifications.show({ message: t('categories.toast.generic_error'), color: 'red' });
      }
    }
  }

  return (
    <Stack gap="lg">
      <Breadcrumbs>
        <Anchor component={Link} to="/categories">
          {t('categories.page_title')}
        </Anchor>
        <Anchor component={Link} to={`/categories/${styleId}`}>
          {data.style_name}
        </Anchor>
        <Text>{data.name}</Text>
      </Breadcrumbs>
      <Group justify="space-between" align="flex-end">
        <Stack gap={2}>
          <Title order={1}>{data.name}</Title>
          <Text c="dimmed">{trackCountLabel}</Text>
        </Stack>
        <Group gap="sm">
          <Button variant="default" onClick={() => setRenameOpen(true)}>
            {t('categories.detail.actions.rename')}
          </Button>
          <Button color="red" variant="light" onClick={openDelete}>
            {t('categories.detail.actions.delete')}
          </Button>
        </Group>
      </Group>
      <TracksTab categoryId={id} />
      <CategoryFormDialog
        mode="rename"
        opened={renameOpen}
        initialName={data.name}
        submitting={renameMut.isPending}
        onClose={() => {
          setRenameOpen(false);
          setRenameServerError(undefined);
        }}
        onSubmit={handleRename}
        serverError={renameServerError}
      />
    </Stack>
  );
}
```

- [ ] **Step 4: Run, verify pass**

```bash
cd frontend
pnpm test src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
```

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/routes/CategoryDetailPage.tsx \
        frontend/src/features/categories/routes/__tests__/CategoryDetailPage.test.tsx
git commit -m "feat(frontend): add CategoryDetailPage

Breadcrumbs + header + rename/delete actions + TracksTab.
Inline 404 not-found state with back-to-list link. Delete
navigates back to list and toasts."
```

---

## Task 20: Wire router + delete placeholder

**Files:**

- Modify: `frontend/src/routes/router.tsx`
- Delete: `frontend/src/routes/categories.tsx`

- [ ] **Step 1: Inspect current router**

```bash
cat frontend/src/routes/router.tsx
```

- [ ] **Step 2: Replace the categories route**

Edit `frontend/src/routes/router.tsx`:

Remove this line:

```ts
import { CategoriesPage } from './categories';
```

Add these imports near the existing route imports:

```ts
import { CategoriesIndexRedirect } from '../features/categories/routes/CategoriesIndexRedirect';
import { CategoriesListPage } from '../features/categories/routes/CategoriesListPage';
import { CategoryDetailPage } from '../features/categories/routes/CategoryDetailPage';
```

Inside the AppShell `children` array, replace the single line:

```ts
{ path: 'categories', element: <CategoriesPage /> },
```

with:

```ts
{
  path: 'categories',
  children: [
    { index: true, element: <CategoriesIndexRedirect /> },
    { path: ':styleId', element: <CategoriesListPage /> },
    { path: ':styleId/:id', element: <CategoryDetailPage /> },
  ],
},
```

- [ ] **Step 3: Delete the placeholder file**

```bash
git rm frontend/src/routes/categories.tsx
```

- [ ] **Step 4: Typecheck + full test run**

```bash
cd frontend
pnpm typecheck && pnpm test
```

Expected: typecheck clean; ≥ 70 tests passing (46 baseline + ≥ 24 new).

- [ ] **Step 5: Production build smoke**

```bash
cd frontend
pnpm build
```

Expected: green; bundle output reported. Note size for the smoke step.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/router.tsx
git commit -m "feat(frontend): wire categories nested routes

/categories — index redirect.
/categories/:styleId — list page.
/categories/:styleId/:id — detail page.
Removes the iter-2a A2 placeholder."
```

---

## Task 21: Manual smoke + merge to main

**Files:** none modified — verification only.

- [ ] **Step 1: Start the dev server**

In one terminal:

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/new_front/frontend
pnpm dev
```

Expected: Vite starts on `http://127.0.0.1:5173`. AuthProvider snapshot loads from existing session cookie (or sign in via Spotify).

- [ ] **Step 2: Smoke checklist**

Run through each of these, confirm visually:

1. `Categories` sidebar → lands on a style URL (e.g. `/categories/<uuid>`) without a "Coming soon" placeholder.
2. Toolbar StyleSelector switches styles; URL updates; refresh restores same style (localStorage).
3. Click "Create category" → modal (desktop) or bottom drawer (mobile). Empty submit shows inline error. Valid name creates row.
4. Open kebab on a row → "Rename" → form prefilled. Change name → save → row updates.
5. Open kebab → "Delete" → confirm modal → confirm → row removed.
6. Drag a row to reorder via grip handle. Mouse: works smoothly. Keyboard: Tab to handle, Space to pick up, ↑/↓ to move, Space to drop. Refresh → order persisted.
7. Click row name → detail page. Track count visible. Tracks tab shows either rows or "No tracks yet" empty state.
8. Type into the tracks search → debounce ~300 ms → server hit. Empty result shows clear-search state. Clear → original tracks return.
9. Resize window below `64em` (1024 px) → forms switch from Modal to Drawer; tracks tab switches from Table to Cards.
10. Browser back from detail → returns to list with order preserved.

If any step fails — stop, fix, re-run `pnpm test`, restart smoke.

- [ ] **Step 3: Final test run before merge**

```bash
cd frontend
pnpm typecheck && pnpm test && pnpm lint && pnpm build
```

Expected: all four green.

- [ ] **Step 4: Merge to main and push**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/new_front
git checkout main
git pull origin main
git merge --no-ff feat/categories-crud -m "feat(frontend): F1 Categories CRUD + DnD reorder + tracks tab

Closes iter-2a F1. Implements per-style routing,
mixed-strategy mutations, @dnd-kit reorder, Modal/Drawer
forms, read-only tracks tab.

Spec: docs/superpowers/specs/2026-05-01-F1-categories-frontend-design.md
Plan: docs/superpowers/plans/2026-05-01-F1-categories-frontend.md"
git push origin main
```

- [ ] **Step 5: Optional — delete the topic branch**

```bash
git branch -d feat/categories-crud
git push origin --delete feat/categories-crud  # only if branch was pushed
```

- [ ] **Step 6: Append a "what bit me" note to the roadmap**

Open `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md` and append a short bullet under a new section `## Lessons (post-F1)` (or extend the existing tech-debt table) listing surprises encountered during F1. Three lines max — what would help the next ticket. Commit:

```bash
git add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
git commit -m "docs(plans): append F1 lessons to iter-2a roadmap

Captures surprises that future iter-2a sessions should know
about. Per F1 spec §12 delivery step 7."
git push origin main
```

---

## Spec Coverage Map

Use this to verify each spec section is implemented:

| Spec section | Covered by tasks |
|---|---|
| §3 D1 per-style routing | Task 20 (router) |
| §3 D2 redirect | Task 17 (CategoriesIndexRedirect) + Task 1 (lastVisitedStyle) |
| §3 D3 toolbar selector | Task 12 (StyleSelector) + Task 18 (page wires it) |
| §3 D4 mixed mutations | Tasks 7–10 |
| §3 D5 Modal/Drawer + ConfirmModal | Tasks 13 + 18 + 19 |
| §3 D6 DnD reorder | Tasks 14 + 15 |
| §3 D7 debounced reorder | Task 10 |
| §3 D8 + D9 tracks tab | Task 16 |
| §3 D10 zod validation | Task 2 |
| §3 D11 error UX | Tasks 18 + 19 (page-level error mapping) |
| §3 D12 direct merge | Task 21 |
| §3 D13 feature folder | Task 1 (skeleton) |
| §3 D14 deps | Task 0 |
| §3 D15 detail route | Task 19 + Task 20 |
| §3 D16 localStorage namespace | Task 1 |
| §3 D17 four empty states | Tasks 16 + 17 + 18 |
| §4 routes | Task 20 |
| §5 components | Tasks 12–16 + 17–19 |
| §6 react-query keys + hooks | Tasks 3–10 |
| §7 zod | Task 2 |
| §8 error UX mapping | Tasks 7–10 + 18 + 19 |
| §10 i18n | Task 11 |
| §11 testing | Embedded in Tasks 1–19 |
| §12 delivery | Task 21 |
| §14 acceptance criteria | Task 21 step 2 + step 3 |

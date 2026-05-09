# F8 Home / Dashboard — Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder Home route with a working Resume + Status dashboard composing existing endpoints across all user styles.

**Architecture:** New `frontend/src/features/home/` module (hooks/components/lib/routes per CLAUDE.md feature-folder convention). `useHomeData` fans out one query per style via `useQueries`. `useResumeTarget` consumes existing `lastCurateLocation` lib for the resume hero with localStorage → freshest IN_PROGRESS → empty fallback chain. Layout is vertical stack, mobile-identical-to-desktop, max-width 720.

**Tech Stack:** React 19, Mantine 9, TanStack Query 5 (`useQueries`), react-router 7, react-i18next, Vitest 2 + MSW + RTL.

**Spec:** `docs/superpowers/specs/2026-05-09-F8-home-design.md`

**Pre-flight verification (run before Task 1):**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f8_task/frontend
pnpm install
pnpm vitest run --reporter=dot 2>&1 | tail -5
```
Expected: green baseline (no Home tests yet — placeholder only).

---

## Task 1: Scaffold feature folder + i18n keys

**Files:**
- Create: `frontend/src/features/home/hooks/.gitkeep`
- Create: `frontend/src/features/home/components/.gitkeep`
- Create: `frontend/src/features/home/lib/.gitkeep`
- Create: `frontend/src/features/home/routes/.gitkeep`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Create empty feature folders**

```bash
cd frontend/src/features
mkdir -p home/hooks/__tests__ home/components/__tests__ home/lib/__tests__ home/routes/__tests__
touch home/hooks/.gitkeep home/components/.gitkeep home/lib/.gitkeep home/routes/.gitkeep
```

- [ ] **Step 2: Add `home.*` block to `frontend/src/i18n/en.json`**

Insert under the `"empty_state"` block (alphabetical-ish with existing top-level groups). Add:

```json
  "home": {
    "resume": {
      "curate": {
        "title": "Continue curating",
        "context": "{{style}} → {{block}}",
        "cta": "Continue"
      },
      "triage": {
        "title": "Open latest active block",
        "context": "{{style}} · {{block}}",
        "cta": "Open block"
      },
      "empty": {
        "title": "No active triage yet",
        "body": "Start by creating your first triage block.",
        "cta": "Create first triage block"
      }
    },
    "counters": {
      "awaiting_triage": "Awaiting triage",
      "active_blocks": "Active blocks",
      "tracks_unit": "tracks",
      "blocks_unit": "blocks"
    },
    "active_blocks": {
      "title": "Active blocks",
      "view_all": "View all ({{count}} blocks)",
      "empty_body": "Nothing in progress."
    },
    "error": {
      "partial": "Some styles failed to load.",
      "partial_retry": "Retry"
    },
    "no_styles": {
      "title": "No styles assigned yet",
      "body": "Contact your admin to get a style assigned."
    }
  },
```

- [ ] **Step 3: Verify JSON parses**

Run: `node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/en.json','utf8'))"`
Expected: no error.

- [ ] **Step 4: Commit**

Generate commit message via `caveman:caveman-commit` skill. Suggested:

```bash
git add frontend/src/features/home frontend/src/i18n/en.json
git commit -m "chore(f8): scaffold home feature folder + i18n"
```

---

## Task 2: `weekLabel` helper (TDD)

**Files:**
- Create: `frontend/src/features/home/lib/weekLabel.ts`
- Test: `frontend/src/features/home/lib/__tests__/weekLabel.test.ts`

The helper converts an ISO date string (e.g. `2026-05-04`) into an ISO-week label `YYYY-Www` for the Active Blocks list.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/features/home/lib/__tests__/weekLabel.test.ts
import { describe, it, expect } from 'vitest';
import { weekLabel } from '../weekLabel';

describe('weekLabel', () => {
  it('formats a mid-year ISO date as YYYY-Www', () => {
    expect(weekLabel('2026-05-04')).toBe('2026-W19');
  });
  it('handles ISO week-1 (Jan 5 2026 is W02)', () => {
    expect(weekLabel('2026-01-05')).toBe('2026-W02');
  });
  it('handles year boundary (Dec 29 2025 is 2026-W01)', () => {
    expect(weekLabel('2025-12-29')).toBe('2026-W01');
  });
  it('returns empty string for an invalid input', () => {
    expect(weekLabel('not-a-date')).toBe('');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/lib/__tests__/weekLabel.test.ts`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement weekLabel**

```ts
// frontend/src/features/home/lib/weekLabel.ts
export function weekLabel(isoDate: string): string {
  const d = new Date(isoDate + 'T00:00:00Z');
  if (Number.isNaN(d.getTime())) return '';
  // ISO week algorithm: shift to nearest Thursday, then week = ((thu - jan1) / 7) + 1
  const target = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  const dayNr = (target.getUTCDay() + 6) % 7; // Mon=0 .. Sun=6
  target.setUTCDate(target.getUTCDate() - dayNr + 3); // nearest Thursday
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const diff = target.getTime() - firstThursday.getTime();
  const week = 1 + Math.round(diff / (7 * 24 * 60 * 60 * 1000));
  const year = target.getUTCFullYear();
  return `${year}-W${String(week).padStart(2, '0')}`;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/lib/__tests__/weekLabel.test.ts`
Expected: 4 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/lib
git commit -m "feat(f8): add weekLabel helper"
```

---

## Task 3: `homeActiveBlocksQueryOptions` factory (TDD)

Non-infinite, status-pinned query options keyed `['home', 'activeBlocks', styleId]`. Returns `TriageBlockSummary[]` for one style. Used by `useHomeData` via `useQueries`.

**Files:**
- Create: `frontend/src/features/home/hooks/homeActiveBlocksQueryOptions.ts`
- Test: `frontend/src/features/home/hooks/__tests__/homeActiveBlocksQueryOptions.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/hooks/__tests__/homeActiveBlocksQueryOptions.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { homeActiveBlocksQueryOptions, homeActiveBlocksKey } from '../homeActiveBlocksQueryOptions';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('homeActiveBlocksQueryOptions', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('builds a query that fetches IN_PROGRESS blocks for a style', async () => {
    let capturedUrl = '';
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({
          items: [
            {
              id: 'b1',
              style_id: 's1',
              style_name: 'House',
              name: '2026-W18',
              date_from: '2026-05-04',
              date_to: '2026-05-10',
              status: 'IN_PROGRESS',
              created_at: '2026-05-04T00:00:00Z',
              updated_at: '2026-05-05T00:00:00Z',
              finalized_at: null,
              track_count: 42,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
    );
    const { result } = renderHook(() => useQuery(homeActiveBlocksQueryOptions('s1')), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedUrl).toContain('status=IN_PROGRESS');
    expect(capturedUrl).toContain('limit=50');
    expect(result.current.data?.[0]?.id).toBe('b1');
  });

  it('exposes a stable cache key', () => {
    expect(homeActiveBlocksKey('s1')).toEqual(['home', 'activeBlocks', 's1']);
  });

  it('disables itself when styleId is empty', () => {
    const { result } = renderHook(() => useQuery(homeActiveBlocksQueryOptions('')), { wrapper: wrap() });
    expect(result.current.fetchStatus).toBe('idle');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/homeActiveBlocksQueryOptions.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the factory**

```ts
// frontend/src/features/home/hooks/homeActiveBlocksQueryOptions.ts
import { queryOptions } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type {
  TriageBlockSummary,
  PaginatedTriageBlocks,
} from '../../triage/hooks/useTriageBlocksByStyle';

const PAGE_LIMIT = 50;

export function homeActiveBlocksKey(styleId: string) {
  return ['home', 'activeBlocks', styleId] as const;
}

export function homeActiveBlocksQueryOptions(styleId: string) {
  return queryOptions({
    queryKey: homeActiveBlocksKey(styleId),
    queryFn: async (): Promise<TriageBlockSummary[]> => {
      const params = new URLSearchParams({
        status: 'IN_PROGRESS',
        limit: String(PAGE_LIMIT),
        offset: '0',
      });
      const page = await api<PaginatedTriageBlocks>(
        `/styles/${styleId}/triage/blocks?${params.toString()}`,
      );
      return page.items;
    },
    enabled: !!styleId,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/homeActiveBlocksQueryOptions.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/hooks/homeActiveBlocksQueryOptions.ts frontend/src/features/home/hooks/__tests__
git commit -m "feat(f8): add homeActiveBlocksQueryOptions factory"
```

---

## Task 4: `useHomeData` hook (TDD)

Composes `useStyles` + `useQueries` over `homeActiveBlocksQueryOptions`. Derives `activeBlocks` (sorted), `activeBlocksCount`, `awaitingTriageCount` (sum of `track_count`), `topActiveBlocks` (slice 5), `partialError`, `refetchAll`, `blocksByStyle`.

**Files:**
- Create: `frontend/src/features/home/hooks/useHomeData.ts`
- Test: `frontend/src/features/home/hooks/__tests__/useHomeData.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/hooks/__tests__/useHomeData.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useHomeData } from '../useHomeData';

function wrap() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function block(id: string, styleId: string, styleName: string, updatedAt: string, trackCount: number) {
  return {
    id,
    style_id: styleId,
    style_name: styleName,
    name: `${id}-name`,
    date_from: '2026-05-04',
    date_to: '2026-05-10',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-05-04T00:00:00Z',
    updated_at: updatedAt,
    finalized_at: null,
    track_count: trackCount,
  };
}

beforeEach(() => {
  tokenStore.set('TOK');
});

describe('useHomeData', () => {
  it('aggregates IN_PROGRESS blocks across styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({
          items: [
            block('b2', 's2', 'Techno', '2026-05-09T00:00:00Z', 50),
            block('b3', 's2', 'Techno', '2026-05-07T00:00:00Z', 12),
          ],
          total: 2, limit: 50, offset: 0,
        }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.activeBlocksCount).toBe(3);
    expect(result.current.data?.awaitingTriageCount).toBe(92);
    expect(result.current.data?.topActiveBlocks.map((b) => b.id)).toEqual(['b2', 'b1', 'b3']);
    expect(result.current.data?.partialError).toBe(false);
  });

  it('flags partialError when one style query fails', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({ error_code: 'server', message: 'boom', correlation_id: 'x' }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.partialError).toBe(true);
    expect(result.current.data?.activeBlocksCount).toBe(1);
  });

  it('returns empty aggregates when there are no styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    const { result } = renderHook(() => useHomeData(), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.data?.activeBlocksCount).toBe(0);
    expect(result.current.data?.styles).toEqual([]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/useHomeData.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `useHomeData`**

```ts
// frontend/src/features/home/hooks/useHomeData.ts
import { useQueries, useQueryClient } from '@tanstack/react-query';
import { useStyles, type Style } from '../../../hooks/useStyles';
import {
  homeActiveBlocksQueryOptions,
  homeActiveBlocksKey,
} from './homeActiveBlocksQueryOptions';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';

export interface HomeData {
  styles: Style[];
  blocksByStyle: Record<string, TriageBlockSummary[]>;
  activeBlocks: TriageBlockSummary[];
  activeBlocksCount: number;
  awaitingTriageCount: number;
  topActiveBlocks: TriageBlockSummary[];
  partialError: boolean;
}

export interface UseHomeDataResult {
  data: HomeData | undefined;
  isLoading: boolean;
  isError: boolean;
  refetchAll: () => void;
}

export function useHomeData(): UseHomeDataResult {
  const stylesQuery = useStyles();
  const qc = useQueryClient();
  const styles = stylesQuery.data?.items ?? [];

  const blockQueries = useQueries({
    queries: styles.map((s) => homeActiveBlocksQueryOptions(s.id)),
  });

  const refetchAll = () => {
    void stylesQuery.refetch();
    for (const s of styles) {
      void qc.invalidateQueries({ queryKey: homeActiveBlocksKey(s.id) });
    }
  };

  if (stylesQuery.isPending) {
    return { data: undefined, isLoading: true, isError: false, refetchAll };
  }
  if (stylesQuery.isError) {
    return { data: undefined, isLoading: false, isError: true, refetchAll };
  }
  const anyPending = blockQueries.some((q) => q.isPending);
  if (anyPending) {
    return { data: undefined, isLoading: true, isError: false, refetchAll };
  }

  const blocksByStyle: Record<string, TriageBlockSummary[]> = {};
  let partialError = false;
  styles.forEach((s, idx) => {
    const q = blockQueries[idx];
    if (q?.isError) {
      partialError = true;
      blocksByStyle[s.id] = [];
    } else {
      blocksByStyle[s.id] = q?.data ?? [];
    }
  });

  const activeBlocks = Object.values(blocksByStyle)
    .flat()
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  const activeBlocksCount = activeBlocks.length;
  const awaitingTriageCount = activeBlocks.reduce((sum, b) => sum + b.track_count, 0);
  const topActiveBlocks = activeBlocks.slice(0, 5);

  return {
    data: {
      styles,
      blocksByStyle,
      activeBlocks,
      activeBlocksCount,
      awaitingTriageCount,
      topActiveBlocks,
      partialError,
    },
    isLoading: false,
    isError: false,
    refetchAll,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/useHomeData.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/hooks/useHomeData.ts frontend/src/features/home/hooks/__tests__/useHomeData.test.tsx
git commit -m "feat(f8): add useHomeData composer hook"
```

---

## Task 5: `useResumeTarget` hook (TDD)

Pure function that takes `activeBlocks` + `blocksByStyle`, reads existing `lastCurate*` localStorage helpers, and returns a discriminated union. Side effect: clears localStorage on stale/invalid hits.

**Files:**
- Create: `frontend/src/features/home/hooks/useResumeTarget.ts`
- Test: `frontend/src/features/home/hooks/__tests__/useResumeTarget.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/hooks/__tests__/useResumeTarget.test.tsx
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook } from '@testing-library/react';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../../curate/lib/lastCurateLocation';
import { useResumeTarget } from '../useResumeTarget';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function block(id: string, styleId: string, status: 'IN_PROGRESS' | 'FINALIZED', updatedAt: string): TriageBlockSummary {
  return {
    id, style_id: styleId, style_name: 'X', name: id, date_from: '2026-05-04',
    date_to: '2026-05-10', status, created_at: '2026-05-04T00:00:00Z',
    updated_at: updatedAt, finalized_at: null, track_count: 10,
  };
}

beforeEach(() => {
  localStorage.clear();
});

describe('useResumeTarget', () => {
  it('returns curate when localStorage points to an IN_PROGRESS block', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const blocks = [block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z')];
    const { result } = renderHook(() => useResumeTarget(blocks, { s1: blocks }));
    expect(result.current.kind).toBe('curate');
    if (result.current.kind === 'curate') {
      expect(result.current.session.bucketId).toBe('bk1');
      expect(result.current.block.id).toBe('b1');
    }
  });

  it('falls back to triage when block is FINALIZED, and clears localStorage', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const finalized = block('b1', 's1', 'FINALIZED', '2026-05-08T00:00:00Z');
    const fallback = block('b2', 's1', 'IN_PROGRESS', '2026-05-09T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([fallback], { s1: [finalized, fallback] }),
    );
    expect(result.current.kind).toBe('triage');
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('falls back when block is missing', () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b-gone', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    const fallback = block('b2', 's1', 'IN_PROGRESS', '2026-05-09T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([fallback], { s1: [fallback] }),
    );
    expect(result.current.kind).toBe('triage');
  });

  it('falls back when localStorage entry is older than 7 days', () => {
    const eightDaysAgo = new Date(Date.now() - 8 * 24 * 60 * 60 * 1000).toISOString();
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: eightDaysAgo } }),
    );
    const valid = block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z');
    const { result } = renderHook(() =>
      useResumeTarget([valid], { s1: [valid] }),
    );
    expect(result.current.kind).toBe('triage');
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('returns triage when no localStorage but IN_PROGRESS blocks exist', () => {
    const b = block('b1', 's1', 'IN_PROGRESS', '2026-05-08T00:00:00Z');
    const { result } = renderHook(() => useResumeTarget([b], { s1: [b] }));
    expect(result.current.kind).toBe('triage');
  });

  it('returns empty when nothing is available', () => {
    const { result } = renderHook(() => useResumeTarget([], {}));
    expect(result.current.kind).toBe('empty');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/useResumeTarget.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `useResumeTarget`**

```ts
// frontend/src/features/home/hooks/useResumeTarget.ts
import { useMemo } from 'react';
import {
  readLastCurateStyle,
  readLastCurateLocation,
  clearLastCurateLocation,
} from '../../curate/lib/lastCurateLocation';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';

const STALE_MS = 7 * 24 * 60 * 60 * 1000;

export type ResumeSession = {
  styleId: string;
  blockId: string;
  bucketId: string;
};

export type ResumeTarget =
  | { kind: 'curate'; session: ResumeSession; block: TriageBlockSummary }
  | { kind: 'triage'; block: TriageBlockSummary }
  | { kind: 'empty' };

export function useResumeTarget(
  activeBlocks: TriageBlockSummary[],
  blocksByStyle: Record<string, TriageBlockSummary[]>,
): ResumeTarget {
  return useMemo(() => {
    const fallback = (): ResumeTarget =>
      activeBlocks[0]
        ? { kind: 'triage', block: activeBlocks[0] }
        : { kind: 'empty' };

    const styleId = readLastCurateStyle();
    if (!styleId) return fallback();

    const loc = readLastCurateLocation(styleId);
    if (!loc) return fallback();

    const updatedAtMs = new Date(loc.updatedAt).getTime();
    if (Number.isNaN(updatedAtMs) || Date.now() - updatedAtMs > STALE_MS) {
      clearLastCurateLocation(styleId);
      return fallback();
    }

    const block = blocksByStyle[styleId]?.find((b) => b.id === loc.blockId);
    if (!block || block.status !== 'IN_PROGRESS') {
      clearLastCurateLocation(styleId);
      return fallback();
    }

    return {
      kind: 'curate',
      session: { styleId, blockId: loc.blockId, bucketId: loc.bucketId },
      block,
    };
  }, [activeBlocks, blocksByStyle]);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/hooks/__tests__/useResumeTarget.test.tsx`
Expected: 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/hooks/useResumeTarget.ts frontend/src/features/home/hooks/__tests__/useResumeTarget.test.tsx
git commit -m "feat(f8): add useResumeTarget hook"
```

---

## Task 6: `ResumeHero` component (TDD)

Three render branches keyed off `ResumeTarget.kind`. Light card, primary button via Mantine `<Button component={Link}>`.

**Files:**
- Create: `frontend/src/features/home/components/ResumeHero.tsx`
- Test: `frontend/src/features/home/components/__tests__/ResumeHero.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/components/__tests__/ResumeHero.test.tsx
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { ResumeHero } from '../ResumeHero';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

const block: TriageBlockSummary = {
  id: 'b1', style_id: 's1', style_name: 'House', name: '2026-W18',
  date_from: '2026-05-04', date_to: '2026-05-10', status: 'IN_PROGRESS',
  created_at: '2026-05-04T00:00:00Z', updated_at: '2026-05-08T00:00:00Z',
  finalized_at: null, track_count: 42,
};

describe('ResumeHero', () => {
  it('renders the curate state with a deep-link to /curate/:style/:block/:bucket', () => {
    render(
      wrap(
        <ResumeHero
          target={{
            kind: 'curate',
            session: { styleId: 's1', blockId: 'b1', bucketId: 'bk1' },
            block,
          }}
        />,
      ),
    );
    const link = screen.getByRole('link', { name: /continue/i });
    expect(link.getAttribute('href')).toBe('/curate/s1/b1/bk1');
  });

  it('renders the triage state with a deep-link to /triage/:style/:id', () => {
    render(wrap(<ResumeHero target={{ kind: 'triage', block }} />));
    const link = screen.getByRole('link', { name: /open block/i });
    expect(link.getAttribute('href')).toBe('/triage/s1/b1');
  });

  it('renders the empty state with the create CTA', () => {
    render(wrap(<ResumeHero target={{ kind: 'empty' }} />));
    const link = screen.getByRole('link', { name: /create first/i });
    expect(link.getAttribute('href')).toBe('/triage?create=1');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/ResumeHero.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `ResumeHero`**

```tsx
// frontend/src/features/home/components/ResumeHero.tsx
import { Button, Card, Group, Stack, Text, Title } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { ResumeTarget } from '../hooks/useResumeTarget';

export interface ResumeHeroProps {
  target: ResumeTarget;
}

export function ResumeHero({ target }: ResumeHeroProps) {
  const { t } = useTranslation();

  if (target.kind === 'curate') {
    const { session, block } = target;
    return (
      <Card withBorder padding="lg" radius="md">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {t('home.resume.curate.title')}
          </Text>
          <Title order={3}>
            {t('home.resume.curate.context', { style: block.style_name, block: block.name })}
          </Title>
          <Text size="sm" c="dimmed">
            {block.track_count} {t('home.counters.tracks_unit')}
          </Text>
          <Group mt="sm">
            <Button
              component={Link}
              to={`/curate/${session.styleId}/${session.blockId}/${session.bucketId}`}
            >
              {t('home.resume.curate.cta')}
            </Button>
          </Group>
        </Stack>
      </Card>
    );
  }

  if (target.kind === 'triage') {
    const { block } = target;
    return (
      <Card withBorder padding="lg" radius="md">
        <Stack gap="xs">
          <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
            {t('home.resume.triage.title')}
          </Text>
          <Title order={3}>
            {t('home.resume.triage.context', { style: block.style_name, block: block.name })}
          </Title>
          <Text size="sm" c="dimmed">
            {block.track_count} {t('home.counters.tracks_unit')}
          </Text>
          <Group mt="sm">
            <Button component={Link} to={`/triage/${block.style_id}/${block.id}`}>
              {t('home.resume.triage.cta')}
            </Button>
          </Group>
        </Stack>
      </Card>
    );
  }

  return (
    <Card withBorder padding="lg" radius="md">
      <Stack gap="xs">
        <Title order={3}>{t('home.resume.empty.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('home.resume.empty.body')}
        </Text>
        <Group mt="sm">
          <Button component={Link} to="/triage?create=1">
            {t('home.resume.empty.cta')}
          </Button>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/ResumeHero.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/components/ResumeHero.tsx frontend/src/features/home/components/__tests__/ResumeHero.test.tsx
git commit -m "feat(f8): add ResumeHero component"
```

---

## Task 7: `CountersGrid` component (TDD)

Two clickable counter cards in `<SimpleGrid cols={2}>`. Each card is `<UnstyledButton component={Link} to="/triage">`.

**Files:**
- Create: `frontend/src/features/home/components/CountersGrid.tsx`
- Test: `frontend/src/features/home/components/__tests__/CountersGrid.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/components/__tests__/CountersGrid.test.tsx
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { CountersGrid } from '../CountersGrid';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

describe('CountersGrid', () => {
  it('renders both counters with values and links to /triage', () => {
    render(wrap(<CountersGrid awaitingTriage={312} activeBlocks={7} />));
    expect(screen.getByText('312')).toBeInTheDocument();
    expect(screen.getByText('7')).toBeInTheDocument();
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(2);
    expect(links[0]?.getAttribute('href')).toBe('/triage');
    expect(links[1]?.getAttribute('href')).toBe('/triage');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/CountersGrid.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `CountersGrid`**

```tsx
// frontend/src/features/home/components/CountersGrid.tsx
import { Card, SimpleGrid, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

export interface CountersGridProps {
  awaitingTriage: number;
  activeBlocks: number;
}

export function CountersGrid({ awaitingTriage, activeBlocks }: CountersGridProps) {
  const { t } = useTranslation();
  return (
    <SimpleGrid cols={2} spacing="xs">
      <UnstyledButton component={Link} to="/triage">
        <Card withBorder padding="md" radius="md">
          <Stack gap={4}>
            <Text ff="monospace" fz={32} fw={600} lh={1}>
              {awaitingTriage}
            </Text>
            <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
              {t('home.counters.awaiting_triage')}
            </Text>
          </Stack>
        </Card>
      </UnstyledButton>
      <UnstyledButton component={Link} to="/triage">
        <Card withBorder padding="md" radius="md">
          <Stack gap={4}>
            <Text ff="monospace" fz={32} fw={600} lh={1}>
              {activeBlocks}
            </Text>
            <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
              {t('home.counters.active_blocks')}
            </Text>
          </Stack>
        </Card>
      </UnstyledButton>
    </SimpleGrid>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/CountersGrid.test.tsx`
Expected: 1 test passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/components/CountersGrid.tsx frontend/src/features/home/components/__tests__/CountersGrid.test.tsx
git commit -m "feat(f8): add CountersGrid component"
```

---

## Task 8: `ActiveBlocksList` component (TDD)

Up to 5 rows. Empty state when no blocks. Footer "View all" link if total > 5.

**Files:**
- Create: `frontend/src/features/home/components/ActiveBlocksList.tsx`
- Test: `frontend/src/features/home/components/__tests__/ActiveBlocksList.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/features/home/components/__tests__/ActiveBlocksList.test.tsx
import React from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { ActiveBlocksList } from '../ActiveBlocksList';
import type { TriageBlockSummary } from '../../../triage/hooks/useTriageBlocksByStyle';

function wrap(node: React.ReactNode) {
  return (
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <MemoryRouter>{node}</MemoryRouter>
      </I18nextProvider>
    </MantineProvider>
  );
}

function block(id: string, styleName: string, dateFrom: string, count: number): TriageBlockSummary {
  return {
    id, style_id: 's1', style_name: styleName, name: id,
    date_from: dateFrom, date_to: dateFrom, status: 'IN_PROGRESS',
    created_at: '2026-05-04T00:00:00Z', updated_at: '2026-05-08T00:00:00Z',
    finalized_at: null, track_count: count,
  };
}

describe('ActiveBlocksList', () => {
  it('renders one row per block with track count and link', () => {
    const blocks = [
      block('b1', 'House', '2026-05-04', 42),
      block('b2', 'Techno', '2026-04-27', 88),
    ];
    render(wrap(<ActiveBlocksList blocks={blocks} total={2} />));
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('88')).toBeInTheDocument();
    expect(screen.getByText(/2026-W19/)).toBeInTheDocument();
    expect(screen.queryByText(/View all/)).toBeNull();
  });

  it('shows the View all footer when total exceeds the rendered slice', () => {
    const blocks = [block('b1', 'House', '2026-05-04', 10)];
    render(wrap(<ActiveBlocksList blocks={blocks} total={9} />));
    const link = screen.getByRole('link', { name: /View all \(9 blocks\)/ });
    expect(link.getAttribute('href')).toBe('/triage');
  });

  it('renders an empty hint when there are no blocks', () => {
    render(wrap(<ActiveBlocksList blocks={[]} total={0} />));
    expect(screen.getByText(/Nothing in progress/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/ActiveBlocksList.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement `ActiveBlocksList`**

```tsx
// frontend/src/features/home/components/ActiveBlocksList.tsx
import { Anchor, Card, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TriageBlockSummary } from '../../triage/hooks/useTriageBlocksByStyle';
import { weekLabel } from '../lib/weekLabel';

export interface ActiveBlocksListProps {
  blocks: TriageBlockSummary[];
  total: number;
}

export function ActiveBlocksList({ blocks, total }: ActiveBlocksListProps) {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="md" radius="md">
      <Stack gap="xs">
        <Text size="xs" c="dimmed" tt="uppercase" lts={1.2}>
          {t('home.active_blocks.title')}
        </Text>
        {blocks.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t('home.active_blocks.empty_body')}
          </Text>
        ) : (
          <Stack gap={4}>
            {blocks.map((b) => (
              <UnstyledButton key={b.id} component={Link} to={`/triage/${b.style_id}/${b.id}`}>
                <Group justify="space-between" wrap="nowrap" px="xs" py={6}>
                  <Text size="sm">
                    {weekLabel(b.date_from)} · {b.style_name}
                  </Text>
                  <Text size="sm" ff="monospace">
                    {b.track_count}
                  </Text>
                </Group>
              </UnstyledButton>
            ))}
            {total > blocks.length && (
              <Anchor component={Link} to="/triage" size="sm" mt={6}>
                {t('home.active_blocks.view_all', { count: total })}
              </Anchor>
            )}
          </Stack>
        )}
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm vitest run src/features/home/components/__tests__/ActiveBlocksList.test.tsx`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/home/components/ActiveBlocksList.tsx frontend/src/features/home/components/__tests__/ActiveBlocksList.test.tsx
git commit -m "feat(f8): add ActiveBlocksList component"
```

---

## Task 9: `HomeSkeleton` + `NoStylesEmpty`

Two simple presentational components. Skip TDD on these; cover via integration test in Task 12.

**Files:**
- Create: `frontend/src/features/home/components/HomeSkeleton.tsx`
- Create: `frontend/src/features/home/components/NoStylesEmpty.tsx`

- [ ] **Step 1: Implement `HomeSkeleton`**

```tsx
// frontend/src/features/home/components/HomeSkeleton.tsx
import { SimpleGrid, Skeleton, Stack } from '@mantine/core';

export function HomeSkeleton() {
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      <Skeleton height={88} radius="md" />
      <SimpleGrid cols={2} spacing="xs">
        <Skeleton height={72} radius="md" />
        <Skeleton height={72} radius="md" />
      </SimpleGrid>
      <Skeleton height={200} radius="md" />
    </Stack>
  );
}
```

- [ ] **Step 2: Implement `NoStylesEmpty`**

```tsx
// frontend/src/features/home/components/NoStylesEmpty.tsx
import { Card, Stack, Text, Title } from '@mantine/core';
import { useTranslation } from 'react-i18next';

export function NoStylesEmpty() {
  const { t } = useTranslation();
  return (
    <Card withBorder padding="lg" radius="md" maw={720} mx="auto">
      <Stack gap="xs">
        <Title order={3}>{t('home.no_styles.title')}</Title>
        <Text size="sm" c="dimmed">
          {t('home.no_styles.body')}
        </Text>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 3: Build & typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/home/components/HomeSkeleton.tsx frontend/src/features/home/components/NoStylesEmpty.tsx
git commit -m "feat(f8): add HomeSkeleton + NoStylesEmpty"
```

---

## Task 10: `HomePage` composer + router wiring

**Files:**
- Create: `frontend/src/features/home/routes/HomePage.tsx`
- Modify: `frontend/src/routes/router.tsx` (replace `./home` import with `../features/home/routes/HomePage`)
- Delete: `frontend/src/routes/home.tsx`

- [ ] **Step 1: Implement `HomePage`**

```tsx
// frontend/src/features/home/routes/HomePage.tsx
import { Alert, Button, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { RouteErrorBoundary } from '../../../components/RouteErrorBoundary';
import { ActiveBlocksList } from '../components/ActiveBlocksList';
import { CountersGrid } from '../components/CountersGrid';
import { HomeSkeleton } from '../components/HomeSkeleton';
import { NoStylesEmpty } from '../components/NoStylesEmpty';
import { ResumeHero } from '../components/ResumeHero';
import { useHomeData } from '../hooks/useHomeData';
import { useResumeTarget } from '../hooks/useResumeTarget';

export function HomePage() {
  const { t } = useTranslation();
  const { data, isLoading, isError, refetchAll } = useHomeData();

  if (isLoading) return <HomeSkeleton />;
  if (isError || !data) return <RouteErrorBoundary />;

  if (data.styles.length === 0) {
    return <NoStylesEmpty />;
  }

  const target = useResumeTarget(data.activeBlocks, data.blocksByStyle);

  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      {data.partialError && (
        <Alert
          color="yellow"
          variant="light"
          title={t('home.error.partial')}
          withCloseButton={false}
        >
          <Button size="xs" variant="default" onClick={refetchAll}>
            {t('home.error.partial_retry')}
          </Button>
        </Alert>
      )}
      <ResumeHero target={target} />
      <CountersGrid
        awaitingTriage={data.awaitingTriageCount}
        activeBlocks={data.activeBlocksCount}
      />
      <ActiveBlocksList blocks={data.topActiveBlocks} total={data.activeBlocksCount} />
    </Stack>
  );
}
```

> Hooks-rules note: `useResumeTarget` is called AFTER an early return. To stay rule-of-hooks compliant, wrap the inner logic in a sub-component, OR move the early return to a wrapper. Apply the wrapper-split pattern from F1 (`CategoriesListPage` / `CategoryDetailPage`) — see Step 2.

- [ ] **Step 2: Apply wrapper-split for hooks compliance**

Replace the body above with:

```tsx
// frontend/src/features/home/routes/HomePage.tsx
import { Alert, Button, Stack } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { RouteErrorBoundary } from '../../../components/RouteErrorBoundary';
import { ActiveBlocksList } from '../components/ActiveBlocksList';
import { CountersGrid } from '../components/CountersGrid';
import { HomeSkeleton } from '../components/HomeSkeleton';
import { NoStylesEmpty } from '../components/NoStylesEmpty';
import { ResumeHero } from '../components/ResumeHero';
import { useHomeData, type HomeData } from '../hooks/useHomeData';
import { useResumeTarget } from '../hooks/useResumeTarget';

export function HomePage() {
  const { data, isLoading, isError, refetchAll } = useHomeData();
  if (isLoading) return <HomeSkeleton />;
  if (isError || !data) return <RouteErrorBoundary />;
  if (data.styles.length === 0) return <NoStylesEmpty />;
  return <HomeReady data={data} refetchAll={refetchAll} />;
}

function HomeReady({ data, refetchAll }: { data: HomeData; refetchAll: () => void }) {
  const { t } = useTranslation();
  const target = useResumeTarget(data.activeBlocks, data.blocksByStyle);
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      {data.partialError && (
        <Alert color="yellow" variant="light" title={t('home.error.partial')}>
          <Button size="xs" variant="default" onClick={refetchAll}>
            {t('home.error.partial_retry')}
          </Button>
        </Alert>
      )}
      <ResumeHero target={target} />
      <CountersGrid
        awaitingTriage={data.awaitingTriageCount}
        activeBlocks={data.activeBlocksCount}
      />
      <ActiveBlocksList blocks={data.topActiveBlocks} total={data.activeBlocksCount} />
    </Stack>
  );
}
```

- [ ] **Step 3: Update router**

Edit `frontend/src/routes/router.tsx`:
- Remove: `import { HomePage } from './home';`
- Add: `import { HomePage } from '../features/home/routes/HomePage';`

- [ ] **Step 4: Delete the placeholder**

```bash
git rm frontend/src/routes/home.tsx
```

- [ ] **Step 5: Typecheck + lint**

Run: `cd frontend && pnpm tsc --noEmit && pnpm lint src/features/home src/routes/router.tsx`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/home/routes frontend/src/routes/router.tsx
git commit -m "feat(f8): wire home dashboard page into router"
```

---

## Task 11: `?create=1` query param in `TriageListPage`

The empty-state CTA in `ResumeHero` (and `ActiveBlocksList` empty footer if reused later) deep-links to `/triage?create=1`. `TriageIndexRedirect` currently picks a default style and navigates to `/triage/:styleId`; we need to preserve the `create=1` query through that redirect, then have `TriageListPage` open the create-modal on mount and strip the param.

**Files:**
- Modify: `frontend/src/features/triage/routes/TriageIndexRedirect.tsx`
- Modify: `frontend/src/features/triage/routes/TriageListPage.tsx`
- Test: `frontend/src/features/triage/routes/__tests__/TriageListPage.test.tsx` (modify existing or add new file if absent)

- [ ] **Step 1: Read `TriageIndexRedirect` to understand current behavior**

```bash
cat frontend/src/features/triage/routes/TriageIndexRedirect.tsx
```

Expected: a small component that picks `lastVisitedTriageStyle` or first style, then `<Navigate to={`/triage/${styleId}`} replace />`.

- [ ] **Step 2: Forward query string in `TriageIndexRedirect`**

In the redirect target, append `useLocation().search` so `?create=1` reaches `TriageListPage`. Example diff:

```tsx
// at the top
import { Navigate, useLocation } from 'react-router';

// inside the component, where it computes the target:
const { search } = useLocation();
return <Navigate to={`/triage/${styleId}${search}`} replace />;
```

- [ ] **Step 3: Auto-open create dialog in `TriageListPage`**

Edit `TriageListPage.tsx`:

```tsx
// add useSearchParams to imports
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router';
// ...

export function TriageListPage() {
  const { styleId } = useParams<{ styleId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: styles } = useStyles();
  const [opened, { open, close }] = useDisclosure(false);
  const [searchParams, setSearchParams] = useSearchParams();

  useEffect(() => {
    if (styleId) writeLastVisitedTriageStyle(styleId);
  }, [styleId]);

  // F8: open create dialog when arriving with ?create=1, then strip the param
  useEffect(() => {
    if (searchParams.get('create') === '1') {
      open();
      const next = new URLSearchParams(searchParams);
      next.delete('create');
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, open, setSearchParams]);

  // ... rest unchanged
```

- [ ] **Step 4: Add a test for the `?create=1` flow**

The directory `frontend/src/features/triage/routes/__tests__/` does NOT exist yet — create it. Add a fresh file:

```tsx
// frontend/src/features/triage/routes/__tests__/TriageListPage.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { TriageListPage } from '../TriageListPage';

function Wrapper({ children, initialEntries }: { children: React.ReactNode; initialEntries: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return (
    <MantineProvider theme={testTheme}>
      <ModalsProvider>
        <Notifications />
        <I18nextProvider i18n={i18n}>
          <QueryClientProvider client={qc}>
            <MemoryRouter initialEntries={initialEntries}>
              <Routes>
                <Route path="/triage/:styleId" element={children} />
              </Routes>
            </MemoryRouter>
          </QueryClientProvider>
        </I18nextProvider>
      </ModalsProvider>
    </MantineProvider>
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  server.use(
    http.get('http://localhost/styles', () =>
      HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/triage/blocks', () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0, pages: [] }),
    ),
  );
});

describe('TriageListPage ?create=1', () => {
  it('opens the create dialog when ?create=1 is present', async () => {
    render(
      <Wrapper initialEntries={['/triage/s1?create=1']}>
        <TriageListPage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
  });

  it('does not auto-open the dialog without the param', async () => {
    render(
      <Wrapper initialEntries={['/triage/s1']}>
        <TriageListPage />
      </Wrapper>,
    );
    // wait one tick for effects to flush
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });
});
```

> Note: assertion that the param was stripped from the URL is intentionally omitted. `MemoryRouter` does not update `window.location`, and probing its history via internal hooks adds boilerplate without catching real bugs. The dialog-opening assertion is sufficient; the strip is a UX nicety verified manually.

- [ ] **Step 5: Run tests**

Run: `cd frontend && pnpm vitest run src/features/triage/routes`
Expected: all tests in the dir pass, including the new one.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/routes
git commit -m "feat(f8): open create dialog on /triage?create=1"
```

---

## Task 12: Integration tests for `HomePage`

End-to-end coverage of the page wired via `MemoryRouter` + MSW.

**Files:**
- Create: `frontend/src/features/home/routes/__tests__/HomePage.test.tsx`

- [ ] **Step 1: Write the integration test file**

```tsx
// frontend/src/features/home/routes/__tests__/HomePage.test.tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Route, Routes } from 'react-router';
import { I18nextProvider } from 'react-i18next';
import { http, HttpResponse } from 'msw';
import i18n from '../../../../i18n';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import {
  LAST_CURATE_LOCATION_KEY,
  LAST_CURATE_STYLE_KEY,
} from '../../../curate/lib/lastCurateLocation';
import { HomePage } from '../HomePage';

function Wrapper({ children, initialEntries = ['/'] }: { children: React.ReactNode; initialEntries?: string[] }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  return (
    <MantineProvider theme={testTheme}>
      <Notifications />
      <I18nextProvider i18n={i18n}>
        <QueryClientProvider client={qc}>
          <MemoryRouter initialEntries={initialEntries}>
            <Routes>
              <Route path="/" element={children} />
            </Routes>
          </MemoryRouter>
        </QueryClientProvider>
      </I18nextProvider>
    </MantineProvider>
  );
}

function block(id: string, styleId: string, styleName: string, status: 'IN_PROGRESS' | 'FINALIZED', updatedAt: string, count = 10) {
  return {
    id, style_id: styleId, style_name: styleName, name: id,
    date_from: '2026-05-04', date_to: '2026-05-10', status,
    created_at: '2026-05-04T00:00:00Z', updated_at: updatedAt,
    finalized_at: status === 'FINALIZED' ? updatedAt : null, track_count: count,
  };
}

beforeEach(() => {
  tokenStore.set('TOK');
  localStorage.clear();
});

describe('HomePage', () => {
  it('renders aggregated counters across two styles', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b2', 's2', 'Techno', 'IN_PROGRESS', '2026-05-09T00:00:00Z', 50)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText('80')).toBeInTheDocument());
    expect(screen.getByText('2')).toBeInTheDocument(); // active blocks count
  });

  it('uses localStorage to render the curate resume hero', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /continue/i });
      expect(link.getAttribute('href')).toBe('/curate/s1/b1/bk1');
    });
  });

  it('falls back to triage and clears localStorage when stored block is FINALIZED', async () => {
    localStorage.setItem(LAST_CURATE_STYLE_KEY, 's1');
    localStorage.setItem(
      LAST_CURATE_LOCATION_KEY,
      JSON.stringify({ s1: { blockId: 'b1', bucketId: 'bk1', updatedAt: new Date().toISOString() } }),
    );
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [
            block('b1', 's1', 'House', 'FINALIZED', '2026-05-08T00:00:00Z', 0),
            block('b2', 's1', 'House', 'IN_PROGRESS', '2026-05-09T00:00:00Z', 12),
          ].filter((b) => b.status === 'IN_PROGRESS'),
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /open block/i });
      expect(link.getAttribute('href')).toBe('/triage/s1/b2');
    });
    expect(JSON.parse(localStorage.getItem(LAST_CURATE_LOCATION_KEY) ?? '{}')).toEqual({});
  });

  it('shows the create-first CTA when there are no IN_PROGRESS blocks', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [{ id: 's1', name: 'House' }], total: 1, limit: 200, offset: 0 }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => {
      const link = screen.getByRole('link', { name: /create first/i });
      expect(link.getAttribute('href')).toBe('/triage?create=1');
    });
  });

  it('renders the warning alert when one style query 500s', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({
          items: [{ id: 's1', name: 'House' }, { id: 's2', name: 'Techno' }],
          total: 2, limit: 200, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [block('b1', 's1', 'House', 'IN_PROGRESS', '2026-05-08T00:00:00Z', 30)],
          total: 1, limit: 50, offset: 0,
        }),
      ),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({ error_code: 'server', message: 'boom', correlation_id: 'x' }, { status: 500 }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/Some styles failed to load/)).toBeInTheDocument());
    expect(screen.getByText('30')).toBeInTheDocument();
  });

  it('renders the no-styles empty state', async () => {
    server.use(
      http.get('http://localhost/styles', () =>
        HttpResponse.json({ items: [], total: 0, limit: 200, offset: 0 }),
      ),
    );
    render(
      <Wrapper>
        <HomePage />
      </Wrapper>,
    );
    await waitFor(() => expect(screen.getByText(/No styles assigned yet/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run integration tests**

Run: `cd frontend && pnpm vitest run src/features/home/routes/__tests__/HomePage.test.tsx`
Expected: 6 tests pass.

- [ ] **Step 3: Run the full feature suite**

Run: `cd frontend && pnpm vitest run src/features/home`
Expected: all home tests green.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/home/routes/__tests__
git commit -m "test(f8): integration coverage for HomePage"
```

---

## Task 13: Final verification — typecheck, lint, full test suite, manual smoke

- [ ] **Step 1: Full typecheck**

Run: `cd frontend && pnpm tsc --noEmit`
Expected: no errors.

- [ ] **Step 2: Full lint**

Run: `cd frontend && pnpm lint`
Expected: no errors.

- [ ] **Step 3: Full test suite**

Run: `cd frontend && pnpm vitest run --reporter=dot`
Expected: every test in the repo passes (no regressions in F1–F7).

- [ ] **Step 4: Bundle check**

Run: `cd frontend && pnpm build`
Expected: build succeeds. Check the printed `dist/assets/*.js` size — should be within ~10 KB of the previous baseline (~910 KB / 271 KB gz).

- [ ] **Step 5: Manual smoke (only if `frontend/.env.local` exists)**

Per CLAUDE.md, run `pnpm dev` from `frontend/`. With a populated dev backend, exercise:

  1. Sign in.
  2. Land on `/` — see resume hero, counters, and active blocks list.
  3. Click counter card → routes to `/triage`.
  4. Click an active-block row → routes to `/triage/:styleId/:id`.
  5. With localStorage cleared, hero shows "Open latest active block" if any IN_PROGRESS exist; otherwise "Create first triage block" → `/triage?create=1` → create modal opens.
  6. Visit a curate session, return to `/` — hero now points at that session.
  7. Tab to another window and back — counters refetch on focus.

If you cannot run the dev server, document which checks were skipped in the PR description.

- [ ] **Step 6: Commit (only if any chore/lint fixes were necessary)**

If steps 1–5 produced any incidental fixes, commit them:

```bash
git add -p
git commit -m "chore(f8): post-implementation cleanup"
```

Otherwise skip this step.

---

## Self-review summary (run by author after writing the plan)

**Spec coverage:**
- Goal §1 → Tasks 10, 12.
- Behavioural contract §2 → Tasks 5, 6, 7, 8, 10, 12.
- Architecture §3 → Tasks 1, 3, 4, 5, 10.
- Components §4 → Tasks 6, 7, 8, 9, 10.
- localStorage §5 → Tasks 5, 12 (reuse-only, no new code beyond Home).
- States §6 → Tasks 9, 10, 12.
- Testing §7 → Tasks 2, 3, 4, 5, 6, 7, 8, 12.
- Out-of-scope §8 → not implemented (correct).
- Tech debt §9 → captured as accepted in spec, no plan task needed.
- Backwards compat §11 → Task 11 (TriageListPage).

**Placeholder scan:** none.

**Type consistency:** `TriageBlockSummary` reused from existing hook; `ResumeTarget` discriminated union consistent across hook + component; `HomeData` shape matches `HomePage` consumer.

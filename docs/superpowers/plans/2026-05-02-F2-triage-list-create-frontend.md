# F2 Triage List + Create Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the Triage list + create + soft-delete slice (F2 ticket from iter-2a roadmap), filling in the placeholder `Triage` route with per-style isolation, tabbed list (`Active | Finalized | All`), Modal/Drawer create form with auto-suggested name, kebab → soft-delete, and a 503 cold-start auto-recovery flow on create.

**Architecture:** New feature folder `frontend/src/features/triage/` with `routes/`, `components/`, `hooks/`, `lib/`. Three new routes registered through react-router 7. React-query 5 for server state; create + delete are pessimistic mutations (no optimistic — F1 D7 is deliberate here too). Mantine `DatePickerInput type="range"` from `@mantine/dates` for the window picker. Auto-name via `dayjs.isoWeek` in a controlled effect that respects user edits. The 503 path lives inside `useCreateTriageBlock` and orchestrates a three-tick auto-invalidate (t=0, +15s, +30s). Concurrently extracts `StyleSelector` + `useStyles` from F1's feature folder to shared `frontend/src/components/` and `frontend/src/hooks/` so both features depend on shared atoms instead of cross-importing each other.

**Tech Stack:** React 19, TypeScript, Mantine 9 (`core` + `form` + `dates` + `notifications` + `modals`), `@tanstack/react-query` 5, `react-router` 7, `dayjs` (existing — needs `isoWeek` plugin enabled), `zod`, `mantine-form-zod-resolver`, Vitest + Testing Library + MSW. Zero new npm dependencies.

**Spec:** [`../specs/2026-05-02-F2-triage-list-create-frontend-design.md`](../specs/2026-05-02-F2-triage-list-create-frontend-design.md). Read it before starting — every UX decision is referenced from there.

**Delivery model:** Direct merge to `main` from `feat/triage-list-create` branch (no PR review). Commit messages via `caveman:caveman-commit` skill (CLAUDE.md mandate).

**Working directory:** `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f2_task`. All commands run from there unless explicitly cd'd into `frontend/`.

---

## Task 0: Prep — branch + dep verification + baseline tests green

**Files:**

- None modified; verification only.

- [ ] **Step 1: Rename current worktree branch to the policy-compliant name**

The worktree was created on branch `worktree-f2_task` which violates the CLAUDE.md "no agent/user prefixes" rule. Rename to `feat/triage-list-create`:

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f2_task
git branch -m feat/triage-list-create
git status
```

Expected: `On branch feat/triage-list-create`.

- [ ] **Step 2: Verify required deps already in `frontend/package.json`**

```bash
grep -E "(@mantine/dates|@mantine/modals|@mantine/form|@mantine/notifications|dayjs|zod|mantine-form-zod-resolver|@tanstack/react-query)" frontend/package.json
```

Expected output includes all 8 lines. If anything is missing, stop and report. F2 should add **zero** new deps.

- [ ] **Step 3: Run baseline tests**

```bash
cd frontend
pnpm test
```

Expected: 91 tests passing (F1 baseline).

- [ ] **Step 4: Run typecheck + build**

```bash
cd frontend
pnpm typecheck
pnpm build
```

Expected: typecheck clean; build emits under 700 KB minified bundle.

- [ ] **Step 5: No commit** — Task 0 has no file changes.

---

## Task 1: Extract `useStyles` to shared `frontend/src/hooks/`

**Files:**

- Move: `frontend/src/features/categories/hooks/useStyles.ts` → `frontend/src/hooks/useStyles.ts`
- Move: `frontend/src/features/categories/hooks/__tests__/useStyles.test.tsx` → `frontend/src/hooks/__tests__/useStyles.test.tsx`
- Modify: every file that imports `useStyles` from the old path.

- [ ] **Step 1: Locate every import of `useStyles`**

```bash
grep -rn "features/categories/hooks/useStyles" frontend/src
```

Expected: at least `CategoriesIndexRedirect.tsx`, `CategoriesListPage.tsx`, and the StyleSelector test file. Note each path.

- [ ] **Step 2: Create the shared `frontend/src/hooks/` directory if missing**

```bash
mkdir -p frontend/src/hooks/__tests__
```

- [ ] **Step 3: Move the hook file and its test**

```bash
git mv frontend/src/features/categories/hooks/useStyles.ts frontend/src/hooks/useStyles.ts
git mv frontend/src/features/categories/hooks/__tests__/useStyles.test.tsx frontend/src/hooks/__tests__/useStyles.test.tsx
```

- [ ] **Step 4: Fix imports inside the moved files**

Open `frontend/src/hooks/useStyles.ts`. The line:

```ts
import { api } from '../../../api/client';
```

becomes:

```ts
import { api } from '../api/client';
```

Open `frontend/src/hooks/__tests__/useStyles.test.tsx`. Any relative import to `../useStyles` already resolves; no change. If the test imports anything from `../../components/` etc., adjust paths so they resolve from the new location.

- [ ] **Step 5: Update every importer found in Step 1**

Replace `from '../hooks/useStyles'` (inside categories feature folder) and similar with `from '../../../hooks/useStyles'`. The exact rewrite:

```ts
// before
import { useStyles } from '../hooks/useStyles';
// after
import { useStyles } from '../../../hooks/useStyles';
```

For `StyleSelector.tsx` (still in categories folder at this task — moves in Task 2), the import becomes:

```ts
import { useStyles } from '../../../hooks/useStyles';
```

- [ ] **Step 6: Run the moved test to verify pass**

```bash
cd frontend
pnpm test src/hooks/__tests__/useStyles.test.tsx
```

Expected: PASS, all assertions green.

- [ ] **Step 7: Run full F1 suite to verify no regression**

```bash
cd frontend
pnpm test src/features/categories
```

Expected: all F1 tests still pass.

- [ ] **Step 8: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 9: Commit**

Generate via caveman-commit skill. Suggested:

```
refactor(frontend): extract useStyles to shared hooks dir
```

```bash
git add -A
git commit -m "refactor(frontend): extract useStyles to shared hooks dir"
```

---

## Task 2: Extract `StyleSelector` to shared `frontend/src/components/`

**Files:**

- Move: `frontend/src/features/categories/components/StyleSelector.tsx` → `frontend/src/components/StyleSelector.tsx`
- Move: `frontend/src/features/categories/components/__tests__/StyleSelector.test.tsx` → `frontend/src/components/__tests__/StyleSelector.test.tsx`
- Modify: every importer of `StyleSelector`.

- [ ] **Step 1: Locate every import of `StyleSelector`**

```bash
grep -rn "components/StyleSelector" frontend/src
```

Note each path.

- [ ] **Step 2: Move the component and its test**

```bash
git mv frontend/src/features/categories/components/StyleSelector.tsx frontend/src/components/StyleSelector.tsx
git mv frontend/src/features/categories/components/__tests__/StyleSelector.test.tsx frontend/src/components/__tests__/StyleSelector.test.tsx
```

- [ ] **Step 3: Fix imports inside the moved component**

Open `frontend/src/components/StyleSelector.tsx`. Replace:

```ts
import { useStyles } from '../../../hooks/useStyles';
```

with:

```ts
import { useStyles } from '../hooks/useStyles';
```

- [ ] **Step 4: Fix imports inside the moved test**

Open `frontend/src/components/__tests__/StyleSelector.test.tsx`. Replace any `../StyleSelector` (already correct after move) and adjust other relative imports that came from the categories folder. For mocks of `useStyles`, the path becomes `../../hooks/useStyles`.

- [ ] **Step 5: Update every importer found in Step 1**

In `features/categories/routes/CategoriesListPage.tsx` (and any other categories file referencing `StyleSelector`), rewrite:

```ts
// before
import { StyleSelector } from '../components/StyleSelector';
// after
import { StyleSelector } from '../../../components/StyleSelector';
```

- [ ] **Step 6: Run StyleSelector tests**

```bash
cd frontend
pnpm test src/components/__tests__/StyleSelector.test.tsx
```

Expected: PASS.

- [ ] **Step 7: Run full F1 suite + integration**

```bash
cd frontend
pnpm test
```

Expected: all 91 tests still pass.

- [ ] **Step 8: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "refactor(frontend): extract StyleSelector to shared components"
```

---

## Task 3: Feature folder skeleton + `lastVisitedTriageStyle` helper

**Files:**

- Create: `frontend/src/features/triage/index.ts`
- Create: `frontend/src/features/triage/lib/lastVisitedTriageStyle.ts`
- Create: `frontend/src/features/triage/lib/__tests__/lastVisitedTriageStyle.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/lib/__tests__/lastVisitedTriageStyle.test.ts`:

```ts
import { describe, it, expect, beforeEach } from 'vitest';
import {
  readLastVisitedTriageStyle,
  writeLastVisitedTriageStyle,
  LAST_TRIAGE_STYLE_KEY,
} from '../lastVisitedTriageStyle';

describe('lastVisitedTriageStyle', () => {
  beforeEach(() => localStorage.clear());

  it('returns null when nothing stored', () => {
    expect(readLastVisitedTriageStyle()).toBeNull();
  });

  it('round-trips a style id', () => {
    writeLastVisitedTriageStyle('abc-123');
    expect(readLastVisitedTriageStyle()).toBe('abc-123');
  });

  it('uses the documented namespace key', () => {
    expect(LAST_TRIAGE_STYLE_KEY).toBe('clouder.lastTriageStyleId');
  });

  it('is independent of the categories key', () => {
    localStorage.setItem('clouder.lastStyleId', 'cat-style');
    writeLastVisitedTriageStyle('triage-style');
    expect(localStorage.getItem('clouder.lastStyleId')).toBe('cat-style');
    expect(readLastVisitedTriageStyle()).toBe('triage-style');
  });

  it('survives a thrown SecurityError on read', () => {
    const original = Storage.prototype.getItem;
    Storage.prototype.getItem = () => {
      throw new Error('SecurityError');
    };
    try {
      expect(readLastVisitedTriageStyle()).toBeNull();
    } finally {
      Storage.prototype.getItem = original;
    }
  });
});
```

- [ ] **Step 2: Run test, verify fails (module not found)**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/lastVisitedTriageStyle.test.ts
```

Expected: FAIL with module-not-found.

- [ ] **Step 3: Implement helper**

Create `frontend/src/features/triage/lib/lastVisitedTriageStyle.ts`:

```ts
export const LAST_TRIAGE_STYLE_KEY = 'clouder.lastTriageStyleId';

export function readLastVisitedTriageStyle(): string | null {
  try {
    return localStorage.getItem(LAST_TRIAGE_STYLE_KEY);
  } catch {
    return null;
  }
}

export function writeLastVisitedTriageStyle(styleId: string): void {
  try {
    localStorage.setItem(LAST_TRIAGE_STYLE_KEY, styleId);
  } catch {
    /* private mode etc. — ignore */
  }
}
```

- [ ] **Step 4: Add the feature index barrel**

Create `frontend/src/features/triage/index.ts`:

```ts
// Re-exports populated as routes are added.
export {};
```

- [ ] **Step 5: Run test, verify pass**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/lastVisitedTriageStyle.test.ts
```

Expected: 5 passing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage
git commit -m "feat(frontend): add lastVisitedTriageStyle helper"
```

---

## Task 4: ISO week helper

**Files:**

- Create: `frontend/src/features/triage/lib/isoWeek.ts`
- Create: `frontend/src/features/triage/lib/__tests__/isoWeek.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/lib/__tests__/isoWeek.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { isoWeekOf } from '../isoWeek';

describe('isoWeekOf', () => {
  it('returns ISO week 17 for 2026-04-20 (a Monday)', () => {
    expect(isoWeekOf(new Date('2026-04-20T00:00:00Z'))).toBe(17);
  });

  it('returns ISO week 1 for 2026-01-01 (a Thursday)', () => {
    expect(isoWeekOf(new Date('2026-01-01T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 1 for 2025-12-29 (Monday belongs to ISO week 1 of 2026)', () => {
    expect(isoWeekOf(new Date('2025-12-29T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 1 for 2024-12-30 (Monday belongs to ISO week 1 of 2025)', () => {
    expect(isoWeekOf(new Date('2024-12-30T00:00:00Z'))).toBe(1);
  });

  it('returns ISO week 53 for 2020-12-31 (Thursday in a 53-week year)', () => {
    expect(isoWeekOf(new Date('2020-12-31T00:00:00Z'))).toBe(53);
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/isoWeek.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement helper**

Create `frontend/src/features/triage/lib/isoWeek.ts`:

```ts
import dayjs from 'dayjs';
import isoWeekPlugin from 'dayjs/plugin/isoWeek';

dayjs.extend(isoWeekPlugin);

export function isoWeekOf(date: Date): number {
  return dayjs(date).isoWeek();
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 5 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/lib/isoWeek.ts frontend/src/features/triage/lib/__tests__/isoWeek.test.ts
git commit -m "feat(frontend): add isoWeekOf helper"
```

---

## Task 5: Zod schemas (`triageSchemas.ts`)

**Files:**

- Create: `frontend/src/features/triage/lib/triageSchemas.ts`
- Create: `frontend/src/features/triage/lib/__tests__/triageSchemas.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/lib/__tests__/triageSchemas.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  triageNameSchema,
  triageDateRangeSchema,
  createTriageBlockSchema,
} from '../triageSchemas';

describe('triageNameSchema', () => {
  it('accepts a normal name', () => {
    expect(triageNameSchema.safeParse('Tech House W17').success).toBe(true);
  });

  it('rejects empty / whitespace-only', () => {
    expect(triageNameSchema.safeParse('').success).toBe(false);
    expect(triageNameSchema.safeParse('   ').success).toBe(false);
  });

  it('trims surrounding whitespace before length check', () => {
    expect(triageNameSchema.safeParse('  Tech  House  ').data).toBe('Tech  House');
  });

  it('rejects 129+ chars after trim', () => {
    expect(triageNameSchema.safeParse('a'.repeat(129)).success).toBe(false);
    expect(triageNameSchema.safeParse('a'.repeat(128)).success).toBe(true);
  });

  it('rejects control characters', () => {
    expect(triageNameSchema.safeParse('AB').success).toBe(false);
    expect(triageNameSchema.safeParse('AB').success).toBe(false);
  });
});

describe('triageDateRangeSchema', () => {
  it('accepts to == from', () => {
    const d = new Date('2026-04-20');
    expect(triageDateRangeSchema.safeParse([d, d]).success).toBe(true);
  });

  it('accepts to > from', () => {
    expect(
      triageDateRangeSchema.safeParse([new Date('2026-04-20'), new Date('2026-04-26')]).success,
    ).toBe(true);
  });

  it('rejects to < from', () => {
    expect(
      triageDateRangeSchema.safeParse([new Date('2026-04-26'), new Date('2026-04-20')]).success,
    ).toBe(false);
  });

  it('rejects null entries', () => {
    // @ts-expect-error — runtime validation guards against this
    expect(triageDateRangeSchema.safeParse([null, null]).success).toBe(false);
  });
});

describe('createTriageBlockSchema', () => {
  it('round-trips a valid input', () => {
    const result = createTriageBlockSchema.safeParse({
      name: 'Tech House W17',
      dateRange: [new Date('2026-04-20'), new Date('2026-04-26')],
    });
    expect(result.success).toBe(true);
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/triageSchemas.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement schemas**

Create `frontend/src/features/triage/lib/triageSchemas.ts`:

```ts
import { z } from 'zod';

const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/;

export const triageNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(128, 'name_too_long')
  .refine((s) => !CONTROL_CHARS.test(s), 'name_control_chars');

export const triageDateRangeSchema = z
  .tuple([z.date(), z.date()])
  .refine(([from, to]) => to.getTime() >= from.getTime(), 'date_range_invalid');

export const createTriageBlockSchema = z.object({
  name: triageNameSchema,
  dateRange: triageDateRangeSchema,
});

export type CreateTriageBlockInput = z.infer<typeof createTriageBlockSchema>;
```

- [ ] **Step 4: Run test, verify pass**

Expected: ~10 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/lib/triageSchemas.ts frontend/src/features/triage/lib/__tests__/triageSchemas.test.ts
git commit -m "feat(frontend): add triage Zod schemas"
```

---

## Task 6: `useTriageBlocksByStyle` hook (infinite query)

**Files:**

- Create: `frontend/src/features/triage/hooks/useTriageBlocksByStyle.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useTriageBlocksByStyle.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/hooks/__tests__/useTriageBlocksByStyle.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import {
  useTriageBlocksByStyle,
  triageBlocksByStyleKey,
} from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
  ...overrides,
});

describe('useTriageBlocksByStyle', () => {
  it('builds a stable query key including style and status', () => {
    expect(triageBlocksByStyleKey('s1', 'IN_PROGRESS')).toEqual([
      'triage',
      'byStyle',
      's1',
      'IN_PROGRESS',
    ]);
    expect(triageBlocksByStyleKey('s1', undefined)).toEqual([
      'triage',
      'byStyle',
      's1',
      'all',
    ]);
  });

  it('fetches the first page with status filter', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.get('status')).toBe('IN_PROGRESS');
        expect(url.searchParams.get('limit')).toBe('50');
        expect(url.searchParams.get('offset')).toBe('0');
        return HttpResponse.json({
          items: [sampleBlock()],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }),
    );

    const { result } = renderHook(
      () => useTriageBlocksByStyle('s1', 'IN_PROGRESS'),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].items).toHaveLength(1);
  });

  it('omits status param when undefined (All tab)', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        expect(url.searchParams.has('status')).toBe(false);
        return HttpResponse.json({
          items: [],
          total: 0,
          limit: 50,
          offset: 0,
        });
      }),
    );

    const { result } = renderHook(() => useTriageBlocksByStyle('s1', undefined), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
  });

  it('paginates with getNextPageParam', async () => {
    let call = 0;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset'));
        call++;
        if (offset === 0) {
          return HttpResponse.json({
            items: Array.from({ length: 50 }, (_, i) =>
              sampleBlock({ id: `a${i}` }),
            ),
            total: 60,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({
          items: Array.from({ length: 10 }, (_, i) =>
            sampleBlock({ id: `b${i}` }),
          ),
          total: 60,
          limit: 50,
          offset: 50,
        });
      }),
    );

    const { result } = renderHook(
      () => useTriageBlocksByStyle('s1', 'IN_PROGRESS'),
      { wrapper: makeWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(result.current.data?.pages).toHaveLength(2);
    expect(result.current.hasNextPage).toBe(false);
    expect(call).toBe(2);
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useTriageBlocksByStyle.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement hook**

Create `frontend/src/features/triage/hooks/useTriageBlocksByStyle.ts`:

```ts
import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export type TriageStatus = 'IN_PROGRESS' | 'FINALIZED';

export interface TriageBlockSummary {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  date_from: string;
  date_to: string;
  status: TriageStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  track_count: number;
}

export interface PaginatedTriageBlocks {
  items: TriageBlockSummary[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export function triageBlocksByStyleKey(
  styleId: string,
  status: TriageStatus | undefined,
) {
  return ['triage', 'byStyle', styleId, status ?? 'all'] as const;
}

export function useTriageBlocksByStyle(
  styleId: string,
  status: TriageStatus | undefined,
): UseInfiniteQueryResult<InfiniteData<PaginatedTriageBlocks>> {
  return useInfiniteQuery({
    queryKey: triageBlocksByStyleKey(styleId, status),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (status) params.set('status', status);
      return api<PaginatedTriageBlocks>(
        `/styles/${styleId}/triage/blocks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!styleId,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 4 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/hooks/useTriageBlocksByStyle.ts frontend/src/features/triage/hooks/__tests__/useTriageBlocksByStyle.test.tsx
git commit -m "feat(frontend): add useTriageBlocksByStyle hook"
```

---

## Task 7: `useDeleteTriageBlock` hook

**Files:**

- Create: `frontend/src/features/triage/hooks/useDeleteTriageBlock.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useDeleteTriageBlock.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/hooks/__tests__/useDeleteTriageBlock.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { useDeleteTriageBlock } from '../useDeleteTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

describe('useDeleteTriageBlock', () => {
  it('invalidates all 3 status caches on success', async () => {
    server.use(
      http.delete('http://localhost/triage/blocks/b1', () =>
        new HttpResponse(null, { status: 204 }),
      ),
    );

    const qc = new QueryClient({
      defaultOptions: { mutations: { retry: false } },
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', 'IN_PROGRESS'), {
      pages: [{ items: [{ id: 'b1' }], total: 1, limit: 50, offset: 0 }],
      pageParams: [0],
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', 'FINALIZED'), {
      pages: [{ items: [], total: 0, limit: 50, offset: 0 }],
      pageParams: [0],
    });
    qc.setQueryData(triageBlocksByStyleKey('s1', undefined), {
      pages: [{ items: [{ id: 'b1' }], total: 1, limit: 50, offset: 0 }],
      pageParams: [0],
    });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteTriageBlock('s1'), {
      wrapper,
    });

    await act(async () => {
      await result.current.mutateAsync('b1');
    });

    expect(qc.getQueryState(triageBlocksByStyleKey('s1', 'IN_PROGRESS'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(triageBlocksByStyleKey('s1', 'FINALIZED'))?.isInvalidated).toBe(true);
    expect(qc.getQueryState(triageBlocksByStyleKey('s1', undefined))?.isInvalidated).toBe(true);
  });

  it('throws ApiError on 404', async () => {
    server.use(
      http.delete('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json(
          { error_code: 'triage_block_not_found', message: 'Not found', correlation_id: 'cid' },
          { status: 404 },
        ),
      ),
    );

    const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useDeleteTriageBlock('s1'), { wrapper });

    await expect(
      act(async () => {
        await result.current.mutateAsync('b1');
      }),
    ).rejects.toMatchObject({ code: 'triage_block_not_found', status: 404 });
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useDeleteTriageBlock.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement hook**

Create `frontend/src/features/triage/hooks/useDeleteTriageBlock.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import { triageBlocksByStyleKey, type TriageStatus } from './useTriageBlocksByStyle';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useDeleteTriageBlock(
  styleId: string,
): UseMutationResult<void, Error, string> {
  const qc = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (blockId) =>
      api<void>(`/triage/blocks/${blockId}`, { method: 'DELETE' }),
    onSuccess: () => {
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 2 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/hooks/useDeleteTriageBlock.ts frontend/src/features/triage/hooks/__tests__/useDeleteTriageBlock.test.tsx
git commit -m "feat(frontend): add useDeleteTriageBlock hook"
```

---

## Task 8: `pendingCreateRecovery` helper

**Files:**

- Create: `frontend/src/features/triage/lib/pendingCreateRecovery.ts`
- Create: `frontend/src/features/triage/lib/__tests__/pendingCreateRecovery.test.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/lib/__tests__/pendingCreateRecovery.test.ts`:

```ts
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { schedulePendingCreateRecovery } from '../pendingCreateRecovery';

describe('schedulePendingCreateRecovery', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('fires onSuccess when first refetch finds matching block', async () => {
    let call = 0;
    const refetch = vi.fn(async () => {
      call++;
      return [{ items: [{ name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' }], total: 1 }];
    });
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();

    // later ticks must NOT fire onSuccess again
    await vi.advanceTimersByTimeAsync(15_000);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it('fires onFailure on the third tick when no match', async () => {
    const refetch = vi.fn(async () => [{ items: [], total: 0 }]);
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(2);
    expect(onFailure).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(refetch).toHaveBeenCalledTimes(3);
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it('matches on later tick if block appears late', async () => {
    let call = 0;
    const refetch = vi.fn(async () => {
      call++;
      if (call < 3) return [{ items: [], total: 0 }];
      return [{ items: [{ name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' }], total: 1 }];
    });
    const onSuccess = vi.fn();
    const onFailure = vi.fn();

    schedulePendingCreateRecovery({
      payload: { name: 'X', date_from: '2026-04-20', date_to: '2026-04-26' },
      refetchAllTabs: refetch,
      onSuccess,
      onFailure,
    });

    await vi.advanceTimersByTimeAsync(0);
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(onSuccess).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(15_000);
    await Promise.resolve();
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/pendingCreateRecovery.test.ts
```

Expected: FAIL.

- [ ] **Step 3: Implement helper**

Create `frontend/src/features/triage/lib/pendingCreateRecovery.ts`:

```ts
export interface PendingCreatePayload {
  name: string;
  date_from: string;
  date_to: string;
}

export interface PendingPage {
  items: { name: string; date_from: string; date_to: string }[];
  total: number;
}

interface ScheduleArgs {
  payload: PendingCreatePayload;
  refetchAllTabs: () => Promise<PendingPage[]>;
  onSuccess: () => void;
  onFailure: () => void;
  delays?: number[];
}

const DEFAULT_DELAYS = [0, 15_000, 15_000];

export function schedulePendingCreateRecovery({
  payload,
  refetchAllTabs,
  onSuccess,
  onFailure,
  delays = DEFAULT_DELAYS,
}: ScheduleArgs): void {
  let resolved = false;

  const matches = (page: PendingPage) =>
    page.items.some(
      (b) =>
        b.name === payload.name &&
        b.date_from === payload.date_from &&
        b.date_to === payload.date_to,
    );

  const tickIndices = delays.map((_, idx) => idx);
  const cumulative = delays.reduce<number[]>((acc, d) => {
    acc.push((acc[acc.length - 1] ?? 0) + d);
    return acc;
  }, []);

  tickIndices.forEach((idx) => {
    const delay = cumulative[idx];
    setTimeout(async () => {
      if (resolved) return;
      try {
        const pages = await refetchAllTabs();
        if (resolved) return;
        if (pages.some(matches)) {
          resolved = true;
          onSuccess();
          return;
        }
        if (idx === delays.length - 1) {
          resolved = true;
          onFailure();
        }
      } catch {
        // refetch failure during recovery: silent for non-final ticks; on the final tick mark failure
        if (idx === delays.length - 1 && !resolved) {
          resolved = true;
          onFailure();
        }
      }
    }, delay);
  });
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/lib/pendingCreateRecovery.ts frontend/src/features/triage/lib/__tests__/pendingCreateRecovery.test.ts
git commit -m "feat(frontend): add pending-create recovery scheduler"
```

---

## Task 9: `useCreateTriageBlock` hook (with 503 path)

**Files:**

- Create: `frontend/src/features/triage/hooks/useCreateTriageBlock.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useCreateTriageBlock.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/hooks/__tests__/useCreateTriageBlock.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import {
  useCreateTriageBlock,
  PendingCreateError,
} from '../useCreateTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

const validInput = {
  style_id: 's1',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
};

function makeWrapper() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return {
    qc,
    Wrapper: ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    ),
  };
}

describe('useCreateTriageBlock', () => {
  it('happy 201 → invalidates all 3 caches', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json(
          {
            id: 'b1',
            style_id: 's1',
            style_name: 'House',
            ...validInput,
            status: 'IN_PROGRESS',
            created_at: 'now',
            updated_at: 'now',
            finalized_at: null,
            buckets: [],
          },
          { status: 201 },
        ),
      ),
    );

    const { qc, Wrapper } = makeWrapper();
    qc.setQueryData(triageBlocksByStyleKey('s1', 'IN_PROGRESS'), {
      pages: [{ items: [], total: 0, limit: 50, offset: 0 }],
      pageParams: [0],
    });

    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });
    await act(async () => {
      await result.current.mutateAsync(validInput);
    });

    expect(
      qc.getQueryState(triageBlocksByStyleKey('s1', 'IN_PROGRESS'))?.isInvalidated,
    ).toBe(true);
  });

  it('503 cold-start → throws PendingCreateError and schedules recovery', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );

    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });

    await expect(
      act(async () => {
        await result.current.mutateAsync(validInput);
      }),
    ).rejects.toBeInstanceOf(PendingCreateError);
  });

  it('non-503 error → throws ApiError', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json(
          {
            error_code: 'validation_error',
            message: 'bad',
            correlation_id: 'cid',
          },
          { status: 422 },
        ),
      ),
    );

    const { Wrapper } = makeWrapper();
    const { result } = renderHook(() => useCreateTriageBlock('s1'), {
      wrapper: Wrapper,
    });

    await expect(
      act(async () => {
        await result.current.mutateAsync(validInput);
      }),
    ).rejects.toMatchObject({ code: 'validation_error', status: 422 });
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useCreateTriageBlock.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement hook**

Create `frontend/src/features/triage/hooks/useCreateTriageBlock.ts`:

```ts
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import {
  schedulePendingCreateRecovery,
  type PendingCreatePayload,
  type PendingPage,
} from '../lib/pendingCreateRecovery';
import {
  triageBlocksByStyleKey,
  type PaginatedTriageBlocks,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export class PendingCreateError extends Error {
  readonly kind = 'pending';
  constructor() {
    super('Triage block creation is taking longer than usual.');
    this.name = 'PendingCreateError';
  }
}

export interface CreateTriageBlockInput {
  style_id: string;
  name: string;
  date_from: string;
  date_to: string;
}

export interface TriageBlockDetail {
  id: string;
  style_id: string;
  style_name: string;
  name: string;
  date_from: string;
  date_to: string;
  status: TriageStatus;
  created_at: string;
  updated_at: string;
  finalized_at: string | null;
  buckets: unknown[];
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

interface UseCreateOptions {
  onPendingSuccess?: () => void;
  onPendingFailure?: () => void;
}

export function useCreateTriageBlock(
  styleId: string,
  options: UseCreateOptions = {},
): UseMutationResult<TriageBlockDetail, Error, CreateTriageBlockInput> {
  const qc = useQueryClient();

  const refetchAllTabs = async (): Promise<PendingPage[]> => {
    const pages: PendingPage[] = [];
    for (const status of STATUSES) {
      const key = triageBlocksByStyleKey(styleId, status);
      await qc.invalidateQueries({ queryKey: key });
      const data = qc.getQueryData<{ pages: PaginatedTriageBlocks[] }>(key);
      if (data) {
        for (const page of data.pages) {
          pages.push({ items: page.items, total: page.total });
        }
      }
    }
    return pages;
  };

  return useMutation<TriageBlockDetail, Error, CreateTriageBlockInput>({
    mutationFn: async (input) => {
      try {
        return await api<TriageBlockDetail>('/triage/blocks', {
          method: 'POST',
          body: JSON.stringify(input),
        });
      } catch (err) {
        if (err instanceof ApiError && (err.status === 503 || err.code === 'cold_start')) {
          const payload: PendingCreatePayload = {
            name: input.name,
            date_from: input.date_from,
            date_to: input.date_to,
          };
          schedulePendingCreateRecovery({
            payload,
            refetchAllTabs,
            onSuccess: () => options.onPendingSuccess?.(),
            onFailure: () => options.onPendingFailure?.(),
          });
          throw new PendingCreateError();
        }
        throw err;
      }
    },
    onSuccess: () => {
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 3 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/hooks/useCreateTriageBlock.ts frontend/src/features/triage/hooks/__tests__/useCreateTriageBlock.test.tsx
git commit -m "feat(frontend): add useCreateTriageBlock with 503 recovery"
```

---

## Task 10: i18n keys

**Files:**

- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Open `frontend/src/i18n/en.json` and add the `triage` namespace**

Insert the following block at the top level of the JSON object (alongside existing `categories`, `appshell`, etc.):

```json
"triage": {
  "page_title": "Triage",
  "create_cta": "New triage block",
  "loading": "Loading triage blocks…",
  "track_count_one": "{{count}} track",
  "track_count_other": "{{count}} tracks",
  "tabs": {
    "active": "Active",
    "finalized": "Finalized",
    "all": "All",
    "counter": "{{label}} · {{count}}"
  },
  "row": {
    "date_range": "{{from}} → {{to}}",
    "menu": { "delete": "Delete" }
  },
  "form": {
    "create_title": "New triage block",
    "name_label": "Name",
    "name_description": "Up to 128 characters.",
    "name_placeholder": "Tech House W17",
    "date_range_label": "Window",
    "date_range_description": "First and last release date covered by this block.",
    "date_range_placeholder": "Pick range",
    "create_submit": "Create",
    "cancel": "Cancel"
  },
  "delete_modal": {
    "title": "Delete triage block?",
    "body": "Delete '{{name}}'? Tracks already promoted to categories stay there. Tracks still in staging are removed.",
    "confirm": "Delete",
    "cancel": "Cancel"
  },
  "toast": {
    "created": "Triage block created.",
    "deleted": "Triage block deleted.",
    "create_pending": "Creation is taking longer than usual. We'll refresh the list automatically.",
    "create_eventually_succeeded": "Triage block created (it took a moment).",
    "create_failed_to_confirm": "Couldn't confirm creation. Please refresh and try again.",
    "delete_not_found": "Block already deleted elsewhere.",
    "generic_error": "Something went wrong. Please retry."
  },
  "errors": {
    "name_required": "Name is required.",
    "name_too_long": "Name must be 128 characters or less.",
    "name_control_chars": "Name contains forbidden characters.",
    "date_range_required": "Pick a date range.",
    "date_range_invalid": "End date must be on or after start date."
  },
  "empty_state": {
    "no_active_title": "No active triage blocks",
    "no_active_body": "Create one to start sorting this style's releases.",
    "no_finalized_title": "No finalized blocks yet",
    "no_finalized_body": "Finalize a block to see it here.",
    "no_blocks_title": "No triage blocks yet",
    "no_blocks_body": "Create your first block for {{style_name}}."
  }
},
```

- [ ] **Step 2: Validate JSON parses**

```bash
cd frontend
node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8'))"
```

Expected: no output (silent success).

- [ ] **Step 3: Re-run baseline tests to confirm no regression**

```bash
cd frontend
pnpm test
```

Expected: 91 + new tests (depending on which tasks land first); zero i18n missing-key warnings in console.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(frontend): add triage i18n namespace (en)"
```

---

## Task 11: `TriageBlockRow` component

**Files:**

- Create: `frontend/src/features/triage/components/TriageBlockRow.tsx`
- Create: `frontend/src/features/triage/components/__tests__/TriageBlockRow.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/components/__tests__/TriageBlockRow.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { MantineProvider } from '@mantine/core';
import { TriageBlockRow } from '../TriageBlockRow';
import type { TriageBlockSummary } from '../../hooks/useTriageBlocksByStyle';

const block: TriageBlockSummary = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
};

function renderRow(props: Partial<React.ComponentProps<typeof TriageBlockRow>> = {}) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <TriageBlockRow block={block} styleId="s1" onDelete={vi.fn()} {...props} />
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('TriageBlockRow', () => {
  it('renders name as a link to detail', () => {
    renderRow();
    const link = screen.getByRole('link', { name: 'House W17' });
    expect(link).toHaveAttribute('href', '/triage/s1/b1');
  });

  it('renders the date range', () => {
    renderRow();
    expect(screen.getByText(/2026-04-20.*2026-04-26/)).toBeInTheDocument();
  });

  it('renders pluralised track count', () => {
    renderRow();
    expect(screen.getByText(/12 tracks/)).toBeInTheDocument();
  });

  it('renders singular track count for 1 track', () => {
    renderRow({ block: { ...block, track_count: 1 } });
    expect(screen.getByText(/1 track\b/)).toBeInTheDocument();
  });

  it('shows finalized_at on FINALIZED tab variant', () => {
    renderRow({
      block: {
        ...block,
        status: 'FINALIZED',
        finalized_at: '2026-04-26T18:00:00Z',
      },
      timeField: 'finalized_at',
    });
    // relative-time renderer just shows ISO substring; assert presence:
    expect(screen.getByText(/2026-04-26/)).toBeInTheDocument();
  });

  it('opens kebab menu and calls onDelete', async () => {
    const onDelete = vi.fn();
    renderRow({ onDelete });
    await userEvent.click(screen.getByRole('button', { name: /menu/i }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    expect(onDelete).toHaveBeenCalledWith(block);
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/TriageBlockRow.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement component**

Create `frontend/src/features/triage/components/TriageBlockRow.tsx`:

```tsx
import { ActionIcon, Badge, Group, Menu, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { IconDotsVertical, IconTrash } from '../../../components/icons';
import type { TriageBlockSummary } from '../hooks/useTriageBlocksByStyle';

export interface TriageBlockRowProps {
  block: TriageBlockSummary;
  styleId: string;
  onDelete: (block: TriageBlockSummary) => void;
  timeField?: 'created_at' | 'finalized_at';
}

export function TriageBlockRow({
  block,
  styleId,
  onDelete,
  timeField = 'created_at',
}: TriageBlockRowProps) {
  const { t } = useTranslation();
  const time = timeField === 'finalized_at' ? block.finalized_at : block.created_at;

  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      px="md"
      py="sm"
      style={{
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
        <Text
          component={Link}
          to={`/triage/${styleId}/${block.id}`}
          c="var(--color-fg)"
          td="none"
          fw={500}
          truncate
        >
          {block.name}
        </Text>
        <Group gap="md" wrap="nowrap">
          <Text size="sm" ff="var(--font-mono)" c="var(--color-fg-muted)">
            {t('triage.row.date_range', {
              from: block.date_from,
              to: block.date_to,
            })}
          </Text>
          {time && (
            <Text size="sm" c="var(--color-fg-muted)">
              {time.slice(0, 10)}
            </Text>
          )}
        </Group>
      </Stack>
      <Group gap="sm" wrap="nowrap">
        <Badge variant="light" radius="sm">
          {t('triage.track_count', { count: block.track_count })}
        </Badge>
        <Menu position="bottom-end" withinPortal>
          <Menu.Target>
            <ActionIcon
              variant="subtle"
              aria-label="menu"
              color="gray"
              size="md"
            >
              <IconDotsVertical size={18} />
            </ActionIcon>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<IconTrash size={14} />}
              color="red"
              onClick={() => onDelete(block)}
            >
              {t('triage.row.menu.delete')}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
    </Group>
  );
}
```

If `IconDotsVertical` or `IconTrash` is not yet exported from `frontend/src/components/icons.ts`, add them by importing the corresponding `@tabler/icons-react` symbols and re-exporting. Verify before continuing:

```bash
grep -E "IconDotsVertical|IconTrash" frontend/src/components/icons.ts
```

If missing, append:

```ts
export { IconDotsVertical, IconTrash } from '@tabler/icons-react';
```

- [ ] **Step 4: Run test, verify pass**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/TriageBlockRow.test.tsx
```

Expected: 6 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/components/TriageBlockRow.tsx frontend/src/features/triage/components/__tests__/TriageBlockRow.test.tsx frontend/src/components/icons.ts
git commit -m "feat(frontend): add TriageBlockRow component"
```

---

## Task 12: `CreateTriageBlockDialog` component

**Files:**

- Create: `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx`
- Create: `frontend/src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { CreateTriageBlockDialog } from '../CreateTriageBlockDialog';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function renderDialog(props: Partial<React.ComponentProps<typeof CreateTriageBlockDialog>> = {}) {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  const utils = render(
    <MantineProvider>
      <QueryClientProvider client={qc}>
        <Notifications />
        <CreateTriageBlockDialog
          opened
          onClose={vi.fn()}
          styleId="s1"
          styleName="House"
          {...props}
        />
      </QueryClientProvider>
    </MantineProvider>,
  );
  return { qc, ...utils };
}

describe('CreateTriageBlockDialog', () => {
  it('renders fields and disabled submit on empty form', () => {
    renderDialog();
    expect(screen.getByLabelText('Name')).toBeInTheDocument();
    expect(screen.getByLabelText('Window')).toBeInTheDocument();
  });

  it('submits a happy path POST', async () => {
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', async ({ request }) => {
        const body = (await request.json()) as Record<string, string>;
        expect(body.style_id).toBe('s1');
        expect(body.name).toBe('House W17');
        expect(body.date_from).toBe('2026-04-20');
        expect(body.date_to).toBe('2026-04-26');
        return HttpResponse.json(
          {
            id: 'b1',
            style_id: 's1',
            style_name: 'House',
            name: 'House W17',
            date_from: '2026-04-20',
            date_to: '2026-04-26',
            status: 'IN_PROGRESS',
            created_at: 'now',
            updated_at: 'now',
            finalized_at: null,
            buckets: [],
          },
          { status: 201 },
        );
      }),
    );

    renderDialog({ onClose });

    // Type the date range manually via the input's text mode
    const dateInput = screen.getByLabelText('Window');
    await userEvent.click(dateInput);
    // Mantine DatePickerInput accepts ISO via direct value prop in tests;
    // simulate typing the range:
    await userEvent.type(dateInput, '2026-04-20 – 2026-04-26');
    // Auto-suggested name should appear:
    await waitFor(() => {
      expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('House W17');
    });

    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('preserves user-edited name across date changes', async () => {
    server.use(
      http.post('http://localhost/triage/blocks', () => HttpResponse.json({}, { status: 201 })),
    );
    renderDialog();
    const nameInput = screen.getByLabelText('Name') as HTMLInputElement;
    await userEvent.type(nameInput, 'My Custom');
    const dateInput = screen.getByLabelText('Window');
    await userEvent.type(dateInput, '2026-04-20 – 2026-04-26');
    // Name must still be 'My Custom', not auto-replaced:
    await waitFor(() => expect(nameInput.value).toBe('My Custom'));
  });

  it('shows inline date_range_invalid when to < from', async () => {
    renderDialog();
    const dateInput = screen.getByLabelText('Window');
    await userEvent.type(dateInput, '2026-04-26 – 2026-04-20');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText(/End date must be on or after start date/i)).toBeInTheDocument();
  });

  it('shows yellow toast on 503 and closes modal', async () => {
    const onClose = vi.fn();
    server.use(
      http.post('http://localhost/triage/blocks', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );
    renderDialog({ onClose });
    await userEvent.type(
      screen.getByLabelText('Window'),
      '2026-04-20 – 2026-04-26',
    );
    await waitFor(() =>
      expect((screen.getByLabelText('Name') as HTMLInputElement).value).toBe('House W17'),
    );
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(
      await screen.findByText(/Creation is taking longer than usual/i),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement component**

Create `frontend/src/features/triage/components/CreateTriageBlockDialog.tsx`:

```tsx
import { useEffect, useRef } from 'react';
import {
  Button,
  Drawer,
  Group,
  Modal,
  Stack,
  TextInput,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { useForm } from '@mantine/form';
import { zodResolver } from 'mantine-form-zod-resolver';
import { useMediaQuery } from '@mantine/hooks';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import {
  createTriageBlockSchema,
  type CreateTriageBlockInput as ZodInput,
} from '../lib/triageSchemas';
import { isoWeekOf } from '../lib/isoWeek';
import {
  useCreateTriageBlock,
  PendingCreateError,
} from '../hooks/useCreateTriageBlock';

export interface CreateTriageBlockDialogProps {
  opened: boolean;
  onClose: () => void;
  styleId: string;
  styleName: string;
}

export function CreateTriageBlockDialog({
  opened,
  onClose,
  styleId,
  styleName,
}: CreateTriageBlockDialogProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const userEditedName = useRef(false);

  const form = useForm<ZodInput>({
    initialValues: {
      name: '',
      dateRange: [null as unknown as Date, null as unknown as Date],
    },
    validate: zodResolver(createTriageBlockSchema),
  });

  const fromDate = form.values.dateRange?.[0] ?? null;
  useEffect(() => {
    if (userEditedName.current) return;
    if (!fromDate) return;
    const week = isoWeekOf(fromDate as Date);
    form.setFieldValue('name', `${styleName} W${week}`, { validate: false });
  }, [fromDate, styleName]);

  const create = useCreateTriageBlock(styleId, {
    onPendingSuccess: () =>
      notifications.show({
        message: t('triage.toast.create_eventually_succeeded'),
        color: 'green',
      }),
    onPendingFailure: () =>
      notifications.show({
        message: t('triage.toast.create_failed_to_confirm'),
        color: 'red',
      }),
  });

  const handleSubmit = form.onSubmit(async (values) => {
    const [from, to] = values.dateRange;
    try {
      await create.mutateAsync({
        style_id: styleId,
        name: values.name.trim(),
        date_from: dayjs(from).format('YYYY-MM-DD'),
        date_to: dayjs(to).format('YYYY-MM-DD'),
      });
      notifications.show({
        message: t('triage.toast.created'),
        color: 'green',
      });
      handleClose();
    } catch (err) {
      if (err instanceof PendingCreateError) {
        notifications.show({
          message: t('triage.toast.create_pending'),
          color: 'yellow',
        });
        handleClose();
        return;
      }
      notifications.show({
        message: t('triage.toast.generic_error'),
        color: 'red',
      });
    }
  });

  const handleClose = () => {
    form.reset();
    userEditedName.current = false;
    onClose();
  };

  const body = (
    <form onSubmit={handleSubmit} noValidate>
      <Stack gap="md">
        <DatePickerInput
          type="range"
          label={t('triage.form.date_range_label')}
          description={t('triage.form.date_range_description')}
          placeholder={t('triage.form.date_range_placeholder')}
          valueFormat="YYYY-MM-DD"
          {...form.getInputProps('dateRange')}
          error={
            form.errors.dateRange && t(`triage.errors.${String(form.errors.dateRange)}`)
          }
        />
        <TextInput
          label={t('triage.form.name_label')}
          description={t('triage.form.name_description')}
          placeholder={t('triage.form.name_placeholder')}
          maxLength={128}
          {...form.getInputProps('name')}
          onChange={(e) => {
            userEditedName.current = true;
            form.getInputProps('name').onChange(e);
          }}
          error={form.errors.name && t(`triage.errors.${String(form.errors.name)}`)}
        />
        <Group justify="flex-end" gap="sm">
          <Button variant="subtle" onClick={handleClose} disabled={create.isPending}>
            {t('triage.form.cancel')}
          </Button>
          <Button type="submit" loading={create.isPending}>
            {t('triage.form.create_submit')}
          </Button>
        </Group>
      </Stack>
    </form>
  );

  if (isMobile) {
    return (
      <Drawer
        opened={opened}
        onClose={handleClose}
        position="bottom"
        title={t('triage.form.create_title')}
        size="auto"
        transitionProps={{ duration: 0 }}
      >
        {body}
      </Drawer>
    );
  }

  return (
    <Modal
      opened={opened}
      onClose={handleClose}
      title={t('triage.form.create_title')}
      transitionProps={{ duration: 0 }}
    >
      {body}
    </Modal>
  );
}
```

- [ ] **Step 4: Run test, verify pass**

Expected: 5 passing. If a Mantine `DatePickerInput` text-typing test is brittle, swap the typing approach to directly setting `form.values.dateRange` via a test-only handle (expose a `data-testid` on the input wrapper and inject ISO dates via `fireEvent.change`).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/components/CreateTriageBlockDialog.tsx frontend/src/features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx
git commit -m "feat(frontend): add CreateTriageBlockDialog"
```

---

## Task 13: `TriageBlocksList` (tabs orchestrator + load-more)

**Files:**

- Create: `frontend/src/features/triage/components/TriageBlocksList.tsx`
- Create: `frontend/src/features/triage/components/__tests__/TriageBlocksList.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/triage/components/__tests__/TriageBlocksList.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { TriageBlocksList } from '../TriageBlocksList';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'B1',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 5,
  ...overrides,
});

function renderList() {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <MemoryRouter>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <TriageBlocksList styleId="s1" />
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('TriageBlocksList', () => {
  it('renders Active tab with results and counter', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        if (status === 'IN_PROGRESS') {
          return HttpResponse.json({
            items: [sampleBlock()],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderList();
    expect(await screen.findByText('B1')).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Active.*1/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /Finalized.*0/ })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: /All.*1/ })).toBeInTheDocument();
  });

  it('switches tabs', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        if (status === 'FINALIZED') {
          return HttpResponse.json({
            items: [sampleBlock({ id: 'fb', name: 'Finalized B', status: 'FINALIZED', finalized_at: '2026-04-26T18:00:00Z' })],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );

    renderList();
    await userEvent.click(await screen.findByRole('tab', { name: /Finalized/ }));
    expect(await screen.findByText('Finalized B')).toBeInTheDocument();
  });

  it('renders empty state for Active tab when zero results', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    renderList();
    expect(await screen.findByText(/No active triage blocks/i)).toBeInTheDocument();
  });

  it('shows load-more button when total > shown', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'));
        if (offset === 0) {
          return HttpResponse.json({
            items: Array.from({ length: 50 }, (_, i) => sampleBlock({ id: `a${i}`, name: `B${i}` })),
            total: 60,
            limit: 50,
            offset: 0,
          });
        }
        return HttpResponse.json({
          items: Array.from({ length: 10 }, (_, i) => sampleBlock({ id: `b${i}`, name: `C${i}` })),
          total: 60,
          limit: 50,
          offset: 50,
        });
      }),
    );

    renderList();
    const button = await screen.findByRole('button', { name: /Show more/i });
    await userEvent.click(button);
    expect(await screen.findByText('C0')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test, verify fails**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/TriageBlocksList.test.tsx
```

Expected: FAIL.

- [ ] **Step 3: Implement component**

Create `frontend/src/features/triage/components/TriageBlocksList.tsx`:

```tsx
import { Button, Loader, Stack, Tabs, Text } from '@mantine/core';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import { useState } from 'react';
import {
  useTriageBlocksByStyle,
  type TriageStatus,
  type TriageBlockSummary,
} from '../hooks/useTriageBlocksByStyle';
import { useDeleteTriageBlock } from '../hooks/useDeleteTriageBlock';
import { TriageBlockRow } from './TriageBlockRow';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { IconLayoutColumns } from '../../../components/icons';

type TabKey = 'active' | 'finalized' | 'all';

const STATUS_FOR_TAB: Record<TabKey, TriageStatus | undefined> = {
  active: 'IN_PROGRESS',
  finalized: 'FINALIZED',
  all: undefined,
};

const TIME_FIELD_FOR_TAB: Record<TabKey, 'created_at' | 'finalized_at'> = {
  active: 'created_at',
  finalized: 'finalized_at',
  all: 'created_at',
};

export interface TriageBlocksListProps {
  styleId: string;
}

export function TriageBlocksList({ styleId }: TriageBlocksListProps) {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabKey>('active');

  const active = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const finalized = useTriageBlocksByStyle(styleId, 'FINALIZED');
  const all = useTriageBlocksByStyle(styleId, undefined);

  const queries: Record<TabKey, typeof active> = {
    active,
    finalized,
    all,
  };

  const totals = {
    active: active.data?.pages[0]?.total,
    finalized: finalized.data?.pages[0]?.total,
    all: all.data?.pages[0]?.total,
  };

  const deleteMutation = useDeleteTriageBlock(styleId);

  const handleDelete = (block: TriageBlockSummary) => {
    modals.openConfirmModal({
      title: t('triage.delete_modal.title'),
      children: <Text>{t('triage.delete_modal.body', { name: block.name })}</Text>,
      labels: {
        confirm: t('triage.delete_modal.confirm'),
        cancel: t('triage.delete_modal.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: async () => {
        try {
          await deleteMutation.mutateAsync(block.id);
          notifications.show({ message: t('triage.toast.deleted'), color: 'green' });
        } catch (err) {
          if (err instanceof ApiError && err.code === 'triage_block_not_found') {
            notifications.show({
              message: t('triage.toast.delete_not_found'),
              color: 'yellow',
            });
            return;
          }
          notifications.show({
            message: t('triage.toast.generic_error'),
            color: 'red',
          });
        }
      },
    });
  };

  const counterLabel = (label: string, value: number | undefined) =>
    value === undefined ? (
      <Loader size="xs" />
    ) : (
      t('triage.tabs.counter', { label, count: value })
    );

  return (
    <Tabs value={tab} onChange={(v) => v && setTab(v as TabKey)}>
      <Tabs.List>
        <Tabs.Tab value="active">
          {counterLabel(t('triage.tabs.active'), totals.active)}
        </Tabs.Tab>
        <Tabs.Tab value="finalized">
          {counterLabel(t('triage.tabs.finalized'), totals.finalized)}
        </Tabs.Tab>
        <Tabs.Tab value="all">
          {counterLabel(t('triage.tabs.all'), totals.all)}
        </Tabs.Tab>
      </Tabs.List>

      {(Object.keys(STATUS_FOR_TAB) as TabKey[]).map((key) => {
        const q = queries[key];
        const items = q.data?.pages.flatMap((p) => p.items) ?? [];
        const remaining = q.data
          ? (q.data.pages[0]?.total ?? 0) - items.length
          : 0;
        return (
          <Tabs.Panel value={key} key={key} pt="md">
            {q.isLoading ? (
              <Loader />
            ) : items.length === 0 ? (
              <EmptyState
                icon={<IconLayoutColumns size={32} />}
                title={t(emptyTitleKey(key))}
                body={t(emptyBodyKey(key))}
              />
            ) : (
              <Stack gap={0}>
                {items.map((block) => (
                  <TriageBlockRow
                    key={block.id}
                    block={block}
                    styleId={styleId}
                    timeField={TIME_FIELD_FOR_TAB[key]}
                    onDelete={handleDelete}
                  />
                ))}
                {q.hasNextPage && (
                  <Button
                    variant="subtle"
                    onClick={() => q.fetchNextPage()}
                    loading={q.isFetchingNextPage}
                    mt="md"
                    style={{ alignSelf: 'center' }}
                  >
                    {`Show more (${remaining} remaining)`}
                  </Button>
                )}
              </Stack>
            )}
          </Tabs.Panel>
        );
      })}
    </Tabs>
  );
}

function emptyTitleKey(tab: TabKey): string {
  return tab === 'active'
    ? 'triage.empty_state.no_active_title'
    : tab === 'finalized'
      ? 'triage.empty_state.no_finalized_title'
      : 'triage.empty_state.no_blocks_title';
}

function emptyBodyKey(tab: TabKey): string {
  return tab === 'active'
    ? 'triage.empty_state.no_active_body'
    : tab === 'finalized'
      ? 'triage.empty_state.no_finalized_body'
      : 'triage.empty_state.no_blocks_body';
}
```

If `IconLayoutColumns` is not yet exported from `frontend/src/components/icons.ts`, add it.

- [ ] **Step 4: Run test, verify pass**

Expected: 4 passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/components/TriageBlocksList.tsx frontend/src/features/triage/components/__tests__/TriageBlocksList.test.tsx frontend/src/components/icons.ts
git commit -m "feat(frontend): add TriageBlocksList tabbed view"
```

---

## Task 14: Routes — `TriageDetailStub`, `TriageIndexRedirect`, `TriageListPage`

**Files:**

- Create: `frontend/src/features/triage/routes/TriageDetailStub.tsx`
- Create: `frontend/src/features/triage/routes/TriageIndexRedirect.tsx`
- Create: `frontend/src/features/triage/routes/TriageListPage.tsx`

- [ ] **Step 1: Implement `TriageDetailStub`**

Create `frontend/src/features/triage/routes/TriageDetailStub.tsx`:

```tsx
import { useTranslation } from 'react-i18next';
import { EmptyState } from '../../../components/EmptyState';
import { IconLayoutColumns } from '../../../components/icons';

export function TriageDetailStub() {
  const { t } = useTranslation();
  return (
    <EmptyState
      icon={<IconLayoutColumns size={32} />}
      title={`${t('appshell.triage')} — ${t('empty_state.coming_soon_title').toLowerCase()}`}
      body={t('empty_state.coming_soon_body')}
    />
  );
}
```

- [ ] **Step 2: Implement `TriageIndexRedirect`**

Create `frontend/src/features/triage/routes/TriageIndexRedirect.tsx`:

```tsx
import { Navigate } from 'react-router';
import { useStyles } from '../../../hooks/useStyles';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { EmptyState } from '../../../components/EmptyState';
import { IconLayoutColumns } from '../../../components/icons';
import { useTranslation } from 'react-i18next';
import { readLastVisitedTriageStyle } from '../lib/lastVisitedTriageStyle';

export function TriageIndexRedirect() {
  const { t } = useTranslation();
  const { data, isLoading } = useStyles();

  if (isLoading) return <FullScreenLoader />;

  const items = data?.items ?? [];
  if (items.length === 0) {
    return (
      <EmptyState
        icon={<IconLayoutColumns size={32} />}
        title={t('categories.no_styles.title')}
        body={t('categories.no_styles.body')}
      />
    );
  }

  const last = readLastVisitedTriageStyle();
  const target = items.find((s) => s.id === last)?.id ?? items[0].id;
  return <Navigate to={`/triage/${target}`} replace />;
}
```

- [ ] **Step 3: Implement `TriageListPage`**

Create `frontend/src/features/triage/routes/TriageListPage.tsx`:

```tsx
import { Button, Group, Stack, Title } from '@mantine/core';
import { useDisclosure } from '@mantine/hooks';
import { useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useEffect } from 'react';
import { StyleSelector } from '../../../components/StyleSelector';
import { useStyles } from '../../../hooks/useStyles';
import { IconPlus } from '../../../components/icons';
import { TriageBlocksList } from '../components/TriageBlocksList';
import { CreateTriageBlockDialog } from '../components/CreateTriageBlockDialog';
import {
  readLastVisitedTriageStyle,
  writeLastVisitedTriageStyle,
} from '../lib/lastVisitedTriageStyle';

export function TriageListPage() {
  const { styleId } = useParams<{ styleId: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { data: styles } = useStyles();
  const [opened, { open, close }] = useDisclosure(false);

  useEffect(() => {
    if (styleId) writeLastVisitedTriageStyle(styleId);
  }, [styleId]);

  if (!styleId) return null;

  const styleName =
    styles?.items.find((s) => s.id === styleId)?.name ?? '';

  return (
    <Stack gap="lg">
      <Group justify="space-between" wrap="nowrap">
        <Title order={2}>{t('triage.page_title')}</Title>
        <Group gap="md">
          <StyleSelector
            value={styleId}
            onChange={(next) => navigate(`/triage/${next}`)}
          />
          <Button leftSection={<IconPlus size={16} />} onClick={open}>
            {t('triage.create_cta')}
          </Button>
        </Group>
      </Group>

      <TriageBlocksList styleId={styleId} />

      <CreateTriageBlockDialog
        opened={opened}
        onClose={close}
        styleId={styleId}
        styleName={styleName}
      />
    </Stack>
  );
}
```

- [ ] **Step 4: Verify `IconPlus` is exported**

```bash
grep "IconPlus" frontend/src/components/icons.ts
```

If missing, append `export { IconPlus } from '@tabler/icons-react';`.

- [ ] **Step 5: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/triage/routes frontend/src/components/icons.ts
git commit -m "feat(frontend): add triage routes (index redirect, list page, detail stub)"
```

---

## Task 15: Wire routes into router; remove legacy placeholder

**Files:**

- Modify: `frontend/src/routes/router.tsx`
- Delete: `frontend/src/routes/triage.tsx`

- [ ] **Step 1: Open `frontend/src/routes/router.tsx`**

Replace this import:

```ts
import { TriagePage } from './triage';
```

with:

```ts
import { TriageIndexRedirect } from '../features/triage/routes/TriageIndexRedirect';
import { TriageListPage } from '../features/triage/routes/TriageListPage';
import { TriageDetailStub } from '../features/triage/routes/TriageDetailStub';
```

Replace this child route:

```tsx
{ path: 'triage', element: <TriagePage /> },
```

with:

```tsx
{
  path: 'triage',
  children: [
    { index: true, element: <TriageIndexRedirect /> },
    { path: ':styleId', element: <TriageListPage /> },
    { path: ':styleId/:id', element: <TriageDetailStub /> },
  ],
},
```

- [ ] **Step 2: Delete the legacy placeholder**

```bash
git rm frontend/src/routes/triage.tsx
```

- [ ] **Step 3: Typecheck + tests**

```bash
cd frontend
pnpm typecheck
pnpm test
```

Expected: all tests still pass; no missing-module errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/router.tsx
git commit -m "feat(frontend): wire triage nested routes"
```

---

## Task 16: Integration tests — list page + redirect

**Files:**

- Create: `frontend/src/features/triage/__tests__/TriageListPage.integration.test.tsx`
- Create: `frontend/src/features/triage/__tests__/TriageRouting.integration.test.tsx`

- [ ] **Step 1: Implement `TriageListPage` integration test**

Create `frontend/src/features/triage/__tests__/TriageListPage.integration.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { TriageListPage } from '../routes/TriageListPage';

const server = setupServer();
beforeEach(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function renderApp(initialPath = '/triage/s1') {
  const qc = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity },
      mutations: { retry: false },
    },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <Routes>
              <Route path="/triage/:styleId" element={<TriageListPage />} />
            </Routes>
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

const stylesResponse = {
  items: [{ id: 's1', name: 'House' }],
  total: 1,
  limit: 200,
  offset: 0,
};

const sampleBlock = (overrides = {}) => ({
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House W17',
  date_from: '2026-04-20',
  date_to: '2026-04-26',
  status: 'IN_PROGRESS',
  created_at: '2026-04-20T10:00:00Z',
  updated_at: '2026-04-20T10:00:00Z',
  finalized_at: null,
  track_count: 12,
  ...overrides,
});

describe('TriageListPage integration', () => {
  it('happy create + delete', async () => {
    let blocks = [sampleBlock()];
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(stylesResponse)),
      http.get('http://localhost/styles/s1/triage/blocks', ({ request }) => {
        const status = new URL(request.url).searchParams.get('status');
        const filtered =
          status === 'FINALIZED'
            ? blocks.filter((b) => b.status === 'FINALIZED')
            : status === 'IN_PROGRESS'
              ? blocks.filter((b) => b.status === 'IN_PROGRESS')
              : blocks;
        return HttpResponse.json({
          items: filtered,
          total: filtered.length,
          limit: 50,
          offset: 0,
        });
      }),
      http.post('http://localhost/triage/blocks', async ({ request }) => {
        const body = (await request.json()) as Record<string, string>;
        const created = sampleBlock({
          id: 'b2',
          name: body.name,
          date_from: body.date_from,
          date_to: body.date_to,
          track_count: 0,
        });
        blocks = [created, ...blocks];
        return HttpResponse.json(created, { status: 201 });
      }),
      http.delete('http://localhost/triage/blocks/b1', () => {
        blocks = blocks.filter((b) => b.id !== 'b1');
        return new HttpResponse(null, { status: 204 });
      }),
    );

    renderApp();
    expect(await screen.findByText('House W17')).toBeInTheDocument();

    // Open create dialog and create a new block
    await userEvent.click(screen.getByRole('button', { name: /New triage block/i }));
    const dateInput = await screen.findByLabelText('Window');
    await userEvent.type(dateInput, '2026-05-01 – 2026-05-07');
    await waitFor(() => {
      const name = screen.getByLabelText('Name') as HTMLInputElement;
      expect(name.value).toContain('W18');
    });
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    await screen.findByText(/Triage block created/i);

    // Delete the original block via kebab
    const menus = screen.getAllByRole('button', { name: /menu/i });
    await userEvent.click(menus[menus.length - 1]); // last row = older B1
    await userEvent.click(screen.getByRole('menuitem', { name: 'Delete' }));
    await userEvent.click(screen.getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.queryByText('House W17')).not.toBeInTheDocument());
  });

  it('503 create — auto-recovery eventually succeeds', async () => {
    vi.useFakeTimers();
    let listResponseBlocks: ReturnType<typeof sampleBlock>[] = [];
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(stylesResponse)),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: listResponseBlocks,
          total: listResponseBlocks.length,
          limit: 50,
          offset: 0,
        }),
      ),
      http.post('http://localhost/triage/blocks', () => {
        // background-completes after the request fails: the block appears in subsequent GETs
        listResponseBlocks = [sampleBlock({ id: 'eventually', name: 'House W18', date_from: '2026-05-01', date_to: '2026-05-07', track_count: 0 })];
        return HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 });
      }),
    );

    renderApp();
    await userEvent.click(await screen.findByRole('button', { name: /New triage block/i }));
    const dateInput = await screen.findByLabelText('Window');
    await userEvent.type(dateInput, '2026-05-01 – 2026-05-07');
    await userEvent.click(screen.getByRole('button', { name: 'Create' }));
    expect(await screen.findByText(/taking longer than usual/i)).toBeInTheDocument();
    await vi.advanceTimersByTimeAsync(0);
    await waitFor(() =>
      expect(screen.getByText(/created \(it took a moment\)/i)).toBeInTheDocument(),
    );
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Implement `TriageRouting` integration test**

Create `frontend/src/features/triage/__tests__/TriageRouting.integration.test.tsx`:

```tsx
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications } from '@mantine/notifications';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter, Routes, Route } from 'react-router';
import { TriageIndexRedirect } from '../routes/TriageIndexRedirect';
import { TriageDetailStub } from '../routes/TriageDetailStub';
import { TriageListPage } from '../routes/TriageListPage';

const server = setupServer();
beforeEach(() => {
  server.listen({ onUnhandledRequest: 'error' });
  localStorage.clear();
});
afterEach(() => {
  server.resetHandlers();
  server.close();
});

function renderApp(initialPath: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MantineProvider>
        <QueryClientProvider client={qc}>
          <ModalsProvider>
            <Notifications />
            <Routes>
              <Route path="/triage" element={<TriageIndexRedirect />} />
              <Route path="/triage/:styleId" element={<TriageListPage />} />
              <Route path="/triage/:styleId/:id" element={<TriageDetailStub />} />
            </Routes>
          </ModalsProvider>
        </QueryClientProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

const stylesResponse = {
  items: [
    { id: 's1', name: 'House' },
    { id: 's2', name: 'Techno' },
  ],
  total: 2,
  limit: 200,
  offset: 0,
};

describe('Triage routing', () => {
  it('redirects index → first style when localStorage empty', async () => {
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(stylesResponse)),
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );

    renderApp('/triage');
    expect(await screen.findByText(/Triage/)).toBeInTheDocument();
  });

  it('redirects index → stored style when set', async () => {
    localStorage.setItem('clouder.lastTriageStyleId', 's2');
    server.use(
      http.get('http://localhost/styles', () => HttpResponse.json(stylesResponse)),
      http.get('http://localhost/styles/s2/triage/blocks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
    );
    renderApp('/triage');
    // After redirect the URL contains s2; title is rendered:
    await screen.findByText(/Triage/);
  });

  it('detail stub renders coming-soon EmptyState', async () => {
    renderApp('/triage/s1/abc');
    expect(await screen.findByText(/coming soon/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run integration suite, verify pass**

```bash
cd frontend
pnpm test src/features/triage/__tests__
```

Expected: 5 passing.

- [ ] **Step 4: Run full suite**

```bash
cd frontend
pnpm test
```

Expected: F1 baseline (91) + new triage tests; all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/triage/__tests__
git commit -m "test(frontend): add triage list + routing integration tests"
```

---

## Task 17: Smoke test against deployed prod API

**Files:** none (manual).

- [ ] **Step 1: Verify `frontend/.env.local` API base**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f2_task
cat frontend/.env.local
```

Expected: `VITE_API_BASE_URL=https://<api-gw>.execute-api.eu-central-1.amazonaws.com` (or whatever the current `terraform output -raw api_endpoint` returns).

If absent or wrong, regenerate:

```bash
cd infra
terraform output -raw api_endpoint
# copy output into ../frontend/.env.local
```

- [ ] **Step 2: Start dev server**

```bash
cd frontend
pnpm dev
```

Expected: SPA on `http://127.0.0.1:5173`.

- [ ] **Step 3: Manual smoke checklist**

Open `http://127.0.0.1:5173` in browser:

1. Sign in via Spotify OAuth.
2. Click `Triage` in sidebar → land on a style.
3. Click `New triage block` → form opens with empty fields.
4. Pick a date range (e.g. last 7 days).
5. Verify name auto-fills `<style> W<n>`.
6. Type into name field → confirm auto-suggest stops overwriting.
7. Click Create → list updates with new block on `Active` tab.
8. Click block name → detail stub `Coming soon` renders.
9. Back to list → kebab → Delete → confirm modal → Delete → row removed.
10. Switch styles via `StyleSelector` → URL + localStorage update.
11. Refresh page → land on same style.
12. Switch tabs `Active | Finalized | All` → counts and content update; tab switching is instant after first fetch.

- [ ] **Step 4: Stop dev server (Ctrl+C)**

- [ ] **Step 5: No commit** — smoke test is manual.

---

## Task 18: Build, typecheck, final test sweep

**Files:** none (verification only).

- [ ] **Step 1: Final typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 2: Final test sweep**

```bash
cd frontend
pnpm test
```

Expected: ≥ 110 tests passing (F1 baseline 91 + ~25 new).

- [ ] **Step 3: Production build**

```bash
cd frontend
pnpm build
```

Expected: build succeeds; bundle ≤ 700 KB minified (no new deps means modest growth from F1's 544 KB base).

- [ ] **Step 4: Lint**

```bash
cd frontend
pnpm lint
```

Expected: clean (or only pre-existing warnings unrelated to F2).

- [ ] **Step 5: No commit** — verification only.

---

## Task 19: Merge to main + push

**Files:** none.

- [ ] **Step 1: Confirm clean working tree**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f2_task
git status
```

Expected: nothing to commit.

- [ ] **Step 2: Switch to main in the primary checkout**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git checkout main
git pull origin main
```

- [ ] **Step 3: Merge the feature branch (no fast-forward)**

```bash
git merge feat/triage-list-create --no-ff -m "Merge branch 'feat/triage-list-create'"
```

Expected: merge commit created; no conflicts.

- [ ] **Step 4: Push to origin**

```bash
git push origin main
```

Expected: CI runs on `main` and validates the merge commit (pr.yml on main is informational; deploy.yml may run if configured).

- [ ] **Step 5: Roadmap follow-up**

Open `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md` and:

- Strike through the F2 row in the ticket queue (mark shipped 2026-05-02 like F1).
- Append F2 lessons learned in the same style as the F1 lessons section.

Commit roadmap update via caveman-commit:

```bash
git add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
git commit -m "docs(plans): close F2 row + capture lessons in roadmap"
git push origin main
```

- [ ] **Step 6: Worktree cleanup (optional)**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git worktree remove .claude/worktrees/f2_task
git branch -d feat/triage-list-create
```

---

## Self-Review (already performed during plan authoring)

**Spec coverage check:**

| Spec section | Implementation task |
|---|---|
| §3 D1 Per-style routing | Task 14 (`TriageIndexRedirect`, `TriageListPage`) |
| §3 D2 Sidebar redirect + localStorage | Task 3 (helper) + Task 14 (consumer) |
| §3 D3 StyleSelector toolbar | Task 2 (extract) + Task 14 (consume) |
| §3 D4 Tabs Active/Finalized/All | Task 13 (`TriageBlocksList`) |
| §3 D5 Sort created_at DESC | Task 6 (hook — backend default) |
| §3 D6 Row content + click target | Task 11 (`TriageBlockRow`) |
| §3 D7 Pessimistic mutations | Tasks 7, 9 (no optimistic onMutate) |
| §3 D8 Modal/Drawer responsive | Task 12 (`useMediaQuery` switch) |
| §3 D9 Auto-suggest with userEdited preserved | Task 12 (effect + ref) |
| §3 D10 Date range validation | Task 5 (Zod) + Task 12 (form) |
| §3 D11 503 cold-start UX | Tasks 8, 9, 12 |
| §3 D12 Soft-delete confirm | Task 13 (modals.openConfirmModal) |
| §3 D13 422 error mapping | Task 12 (form errors) |
| §3 D14 Shared StyleSelector + useStyles | Tasks 1, 2 |
| §3 D15 F3 stub | Task 14 (`TriageDetailStub`) |
| §3 D16 localStorage namespacing | Task 3 |
| §3 D17 Zero new deps | Task 0 verifies |
| §3 D18 Empty states | Task 13 |
| §3 D19 Direct merge | Task 19 |
| §6.2 hooks (4) | Tasks 6, 7, 9 (and `useStyles` reused via Task 1) |
| §6.3 pending recovery | Task 8 |
| §10 i18n | Task 10 |
| §11.1 unit tests | Tasks 3, 4, 5, 6, 7, 8, 9, 11, 12, 13 |
| §11.2 integration tests | Task 16 |
| §11.3 manual smoke | Task 17 |
| §14 acceptance criteria | Task 18 (build + tests) + Task 19 (merge) |

All 23 spec sections covered.

**Placeholder scan:** No "TBD", "TODO", or vague-direction language. Every code step contains complete, runnable code.

**Type consistency:**

- `TriageBlockSummary` defined in Task 6, consumed unchanged in Tasks 7, 11, 13.
- `TriageStatus = 'IN_PROGRESS' | 'FINALIZED'` defined in Task 6, used in Tasks 7, 9, 13.
- `triageBlocksByStyleKey(styleId, status)` defined in Task 6, called in Tasks 7, 9, 13.
- `PendingCreateError` defined in Task 9, imported in Task 12.
- `schedulePendingCreateRecovery` signature defined in Task 8, called in Task 9.

All cross-task references match.

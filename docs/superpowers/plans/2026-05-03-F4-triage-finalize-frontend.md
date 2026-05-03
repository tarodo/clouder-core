# F4 — Triage Finalize Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the real Finalize flow + bulk Transfer-from-FINALIZED-tech-bucket on top of the existing F1+F2+F3a+F3b foundation, so a user can promote staging buckets into categories and carry technical-bucket tracks forward into the next IN_PROGRESS block.

**Architecture:** New `FinalizeModal` mounts from `TriageBlockHeader`'s active CTA (replaces F3a's `disabled` placeholder). Modal branches on confirm vs blocker variant, fires `useFinalizeTriageBlock` mutation with full cache sweep, and falls back to a `pendingFinalizeRecovery` scheduler on 503. Existing `TransferModal` (F3b) is extended in-place to accept `trackIds: string[]` + `mode: 'single' \| 'bulk'`. In `'bulk'` mode it loops sequential 1000-track POSTs (snapshot semantics + `ON CONFLICT DO NOTHING` make rollback unnecessary). `BucketDetailPage` exposes `Transfer all to another block…` only on FINALIZED tech buckets with tracks; click drains the paginated `useBucketTracks` infinite query, then opens the modal pre-filled.

**Tech Stack:** React 19, Mantine 9, TanStack Query 5, Vitest + MSW, react-router 7, react-i18next 15. No new dependencies.

**Spec:** [`docs/superpowers/specs/2026-05-03-F4-triage-finalize-frontend-design.md`](../specs/2026-05-03-F4-triage-finalize-frontend-design.md).

---

## Conventions

- All commits go through `caveman:caveman-commit` skill (CLAUDE.md `Commit Policy`). Sample subjects shown below; regenerate via the skill at commit time.
- Branch: `feat/triage-finalize` (worktree `.claude/worktrees/f4_task` on branch `worktree-f4_task` already in place; merge target is `main`).
- After EVERY task: run `pnpm test`, `pnpm typecheck` from `frontend/`. Don't proceed until green.
- File-path conventions in this plan are absolute from worktree root unless noted.
- `frontend/` is the working directory for all `pnpm` commands.

---

## Task 1: `pendingFinalizeRecovery` pure scheduler

**Why first:** No React, no QueryClient — pure scheduler is independent of every other piece. Mirrors F2's `pendingCreateRecovery.ts` shape; tests-only TDD with `vi.useFakeTimers()`.

**Files:**
- Create: `frontend/src/features/triage/lib/pendingFinalizeRecovery.ts`
- Create: `frontend/src/features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts`

- [ ] **Step 1: Write the failing tests**

```ts
// frontend/src/features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  schedulePendingFinalizeRecovery,
  type PendingFinalizeBlock,
} from '../pendingFinalizeRecovery';

const inProgress: PendingFinalizeBlock = { id: 'b1', status: 'IN_PROGRESS' };
const finalized: PendingFinalizeBlock = { id: 'b1', status: 'FINALIZED' };

describe('pendingFinalizeRecovery', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('fires onSuccess when a tick observes status=FINALIZED', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<[], Promise<PendingFinalizeBlock>>()
      .mockResolvedValueOnce(inProgress)
      .mockResolvedValueOnce(finalized);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    expect(onSuccess).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledWith(finalized);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('fires onFailure on the final tick when status never flips', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi.fn<[], Promise<PendingFinalizeBlock>>().mockResolvedValue(inProgress);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('swallows refetch errors on non-final ticks; failure on final tick error', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<[], Promise<PendingFinalizeBlock>>()
      .mockRejectedValueOnce(new Error('boom-1'))
      .mockRejectedValueOnce(new Error('boom-2'))
      .mockRejectedValueOnce(new Error('boom-3'));

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    expect(onFailure).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(100);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it('does not call onSuccess twice if a later tick also reports FINALIZED', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi
      .fn<[], Promise<PendingFinalizeBlock>>()
      .mockResolvedValue(finalized);

    schedulePendingFinalizeRecovery({
      blockId: 'b1',
      refetch,
      onSuccess,
      onFailure,
      delays: [0, 100, 100],
    });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(100);
    await vi.advanceTimersByTimeAsync(100);
    expect(onSuccess).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it('uses default delays [0, 15000, 15000] when not provided', async () => {
    const onSuccess = vi.fn();
    const onFailure = vi.fn();
    const refetch = vi.fn<[], Promise<PendingFinalizeBlock>>().mockResolvedValue(inProgress);

    schedulePendingFinalizeRecovery({ blockId: 'b1', refetch, onSuccess, onFailure });

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onFailure).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(15_000);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd frontend && pnpm test src/features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts
```

Expected: FAIL with "Cannot find module '../pendingFinalizeRecovery'".

- [ ] **Step 3: Implement the scheduler**

```ts
// frontend/src/features/triage/lib/pendingFinalizeRecovery.ts
export interface PendingFinalizeBlock {
  id: string;
  status: 'IN_PROGRESS' | 'FINALIZED';
}

interface ScheduleArgs {
  blockId: string;
  refetch: () => Promise<PendingFinalizeBlock>;
  onSuccess: (block: PendingFinalizeBlock) => void;
  onFailure: () => void;
  delays?: number[];
}

const DEFAULT_DELAYS = [0, 15_000, 15_000];

export function schedulePendingFinalizeRecovery({
  refetch,
  onSuccess,
  onFailure,
  delays = DEFAULT_DELAYS,
}: ScheduleArgs): void {
  let resolved = false;

  const cumulative = delays.reduce<number[]>((acc, d) => {
    acc.push((acc[acc.length - 1] ?? 0) + d);
    return acc;
  }, []);

  delays.forEach((_, idx) => {
    const total = cumulative[idx];
    setTimeout(async () => {
      if (resolved) return;
      try {
        const block = await refetch();
        if (resolved) return;
        if (block.status === 'FINALIZED') {
          resolved = true;
          onSuccess(block);
          return;
        }
        if (idx === delays.length - 1) {
          resolved = true;
          onFailure();
        }
      } catch {
        if (idx === delays.length - 1 && !resolved) {
          resolved = true;
          onFailure();
        }
      }
    }, total);
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts
```

Expected: 5 passing.

- [ ] **Step 5: Typecheck**

```bash
pnpm typecheck
```

Expected: clean.

- [ ] **Step 6: Commit**

Generate via `caveman:caveman-commit` then run:

```bash
git add frontend/src/features/triage/lib/pendingFinalizeRecovery.ts frontend/src/features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts
git commit -m "<caveman output>"
```

Sample subject: `feat(triage): add pendingFinalizeRecovery scheduler`.

---

## Task 2: `useFinalizeTriageBlock` mutation hook with cache sweep

**Why now:** Independent of UI. Establishes the cache-invalidation contract before any modal consumes it.

**Files:**
- Create: `frontend/src/features/triage/hooks/useFinalizeTriageBlock.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useFinalizeTriageBlock.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/triage/hooks/__tests__/useFinalizeTriageBlock.test.tsx
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import {
  useFinalizeTriageBlock,
  type FinalizeResponse,
} from '../useFinalizeTriageBlock';
import { ApiError } from '../../../../api/error';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrapper(qc: QueryClient) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
  };
}

const SUCCESS: FinalizeResponse = {
  block: {
    id: 'b1',
    style_id: 's1',
    style_name: 'House',
    name: 'Block 1',
    date_from: '2026-04-21',
    date_to: '2026-04-28',
    status: 'FINALIZED',
    created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z',
    finalized_at: '2026-04-28T00:00:00Z',
    buckets: [],
  },
  promoted: { catA: 3, catB: 5 },
  correlation_id: 'cid-1',
};

describe('useFinalizeTriageBlock', () => {
  beforeEach(() => server.resetHandlers());
  afterEach(() => server.resetHandlers());

  it('invalidates triage + categories caches on success', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(SUCCESS, { status: 200 }),
      ),
    );
    const qc = makeClient();
    const spy = vi.spyOn(qc, 'invalidateQueries');

    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), { wrapper: wrapper(qc) });
    await result.current.mutateAsync();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const calls = spy.mock.calls.map((c) => c[0]);
    // triage.blockDetail
    expect(calls).toContainEqual({ queryKey: ['triage', 'blockDetail', 'b1'] });
    // triage.byStyle for all 3 status keys
    expect(calls).toContainEqual({ queryKey: ['triage', 'byStyle', 's1', 'IN_PROGRESS'] });
    expect(calls).toContainEqual({ queryKey: ['triage', 'byStyle', 's1', 'FINALIZED'] });
    expect(calls).toContainEqual({ queryKey: ['triage', 'byStyle', 's1', undefined] });
    // categories.byStyle
    expect(calls).toContainEqual({ queryKey: ['categories', 'byStyle', 's1'] });
    // categories.detail per promoted category
    expect(calls).toContainEqual({ queryKey: ['categories', 'detail', 'catA'] });
    expect(calls).toContainEqual({ queryKey: ['categories', 'detail', 'catB'] });
    // categories.tracks predicate match — verify a predicate call landed for each cat
    const predicateCalls = spy.mock.calls.filter(
      (c) => typeof (c[0] as { predicate?: unknown }).predicate === 'function',
    );
    expect(predicateCalls.length).toBeGreaterThanOrEqual(2);
  });

  it('rejects with ApiError on 503 cold start', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 }),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), { wrapper: wrapper(qc) });

    await expect(result.current.mutateAsync()).rejects.toBeInstanceOf(ApiError);
  });

  it('rejects with ApiError carrying inactive_buckets in raw on 409', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            error_code: 'inactive_buckets_have_tracks',
            message: '1 inactive staging bucket holds tracks',
            inactive_buckets: [{ id: 'bk1', category_id: 'catX', track_count: 5 }],
          },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useFinalizeTriageBlock('b1', 's1'), { wrapper: wrapper(qc) });

    await expect(result.current.mutateAsync()).rejects.toMatchObject({
      code: 'inactive_buckets_have_tracks',
      status: 409,
    });
    const err = await result.current.mutateAsync().catch((e) => e);
    expect((err.raw as { inactive_buckets: unknown[] }).inactive_buckets).toHaveLength(1);
  });
});
```

NOTE: the test relies on the existing `apiClient` base URL `https://api.test`. Confirm by reading `frontend/src/test/setup.ts`. If a different base is used, swap it in the MSW handler URLs.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pnpm test src/features/triage/hooks/__tests__/useFinalizeTriageBlock.test.tsx
```

Expected: FAIL — `useFinalizeTriageBlock` not defined.

- [ ] **Step 3: Implement the hook**

```ts
// frontend/src/features/triage/hooks/useFinalizeTriageBlock.ts
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { categoriesByStyleKey } from '../../categories/hooks/useCategoriesByStyle';
import { categoryDetailKey } from '../../categories/hooks/useCategoryDetail';
import { triageBlockKey, type TriageBlock } from './useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export interface FinalizeResponse {
  block: TriageBlock;
  promoted: Record<string, number>;
  correlation_id?: string;
}

export interface InactiveBucketRow {
  id: string;
  category_id: string;
  track_count: number;
}

export interface FinalizeErrorBody {
  error_code: string;
  message: string;
  inactive_buckets?: InactiveBucketRow[];
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useFinalizeTriageBlock(
  blockId: string,
  styleId: string,
): UseMutationResult<FinalizeResponse, ApiError, void> {
  const qc = useQueryClient();
  return useMutation<FinalizeResponse, ApiError, void>({
    mutationKey: ['triage', 'finalize', blockId],
    mutationFn: () =>
      api<FinalizeResponse>(`/triage/blocks/${blockId}/finalize`, { method: 'POST' }),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
      qc.invalidateQueries({ queryKey: categoriesByStyleKey(styleId) });
      for (const categoryId of Object.keys(data.promoted ?? {})) {
        qc.invalidateQueries({ queryKey: categoryDetailKey(categoryId) });
        qc.invalidateQueries({
          predicate: (q) =>
            Array.isArray(q.queryKey) &&
            q.queryKey[0] === 'categories' &&
            q.queryKey[1] === 'tracks' &&
            q.queryKey[2] === categoryId,
        });
      }
    },
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/hooks/__tests__/useFinalizeTriageBlock.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Typecheck**

```bash
pnpm typecheck
```

- [ ] **Step 6: Commit**

Sample subject: `feat(triage): add useFinalizeTriageBlock hook`.

---

## Task 3: i18n keys (additions only)

**Why now:** Components in Tasks 4-6 reference these keys. Adding only — `triage.detail.finalize_coming_soon` is removed in Task 7 (same commit as the placeholder swap, to avoid an intermediate commit that breaks `useTranslation` lookup in `TriageBlockHeader`).

**Files:**
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Open the file and locate the `"triage"` namespace**

The file exists at `frontend/src/i18n/en.json`. The `triage` namespace ends with the existing `"transfer"` block.

- [ ] **Step 2: Add `triage.finalize.*` keys**

Insert this block immediately after the existing `"transfer": { ... }` block but still inside `"triage": { ... }`:

```json
    "finalize": {
      "confirm": {
        "title": "Finalize {{blockName}}?",
        "body_one": "{{count}} track will be promoted into {{categoryCount}} category. This cannot be undone.",
        "body_other": "{{count}} tracks will be promoted into {{categoryCount}} categories. This cannot be undone.",
        "empty_summary": "Block has no staging buckets. Finalizing will mark it FINALIZED with no category promotions.",
        "row_count_one": "{{count}} track",
        "row_count_other": "{{count}} tracks",
        "submit": "Finalize",
        "cancel": "Cancel",
        "recovering": "Cold start, hang on…"
      },
      "blocker": {
        "title": "Cannot finalize yet",
        "body_one": "{{count}} staging bucket holds tracks but its category was deleted. Move or transfer them first.",
        "body_other": "{{count}} staging buckets hold tracks but their categories were deleted. Move or transfer them first.",
        "row_count_one": "{{count}} track",
        "row_count_other": "{{count}} tracks",
        "open": "Open",
        "dismiss": "Dismiss",
        "unknown_category": "(deleted category)"
      },
      "toast": {
        "success_one": "Finalized {{blockName}} · promoted {{count}} track across {{categoryCount}} categories.",
        "success_other": "Finalized {{blockName}} · promoted {{count}} tracks across {{categoryCount}} categories.",
        "success_recovered_one": "Finalize succeeded after retry — {{blockName}} · promoted {{count}} track.",
        "success_recovered_other": "Finalize succeeded after retry — {{blockName}} · promoted {{count}} tracks.",
        "stale_block": "Block is gone. Refreshing.",
        "already_finalized": "Block is already finalized.",
        "blocked_race_one": "{{count}} bucket needs attention before finalize.",
        "blocked_race_other": "{{count}} buckets need attention before finalize.",
        "cold_start_terminal": "Finalize is taking too long. Refresh — it may have already succeeded.",
        "error": "Finalize failed."
      }
    }
```

- [ ] **Step 3: Add `triage.transfer.bulk.*` keys**

Inside the existing `"transfer": { ... }` block, add a new `"bulk": { ... }` sibling next to `"toast"`:

```json
      "bulk": {
        "cta": "Transfer all to another block…",
        "modal": {
          "batch_progress": "Transferring batch {{k}} of {{m}}…"
        },
        "toast": {
          "success_one": "Transferred {{count}} track to {{blockName}} / {{bucketLabel}}.",
          "success_other": "Transferred {{count}} tracks to {{blockName}} / {{bucketLabel}}.",
          "partial": "Transferred {{count}} of {{total}} tracks. Source unchanged — click Transfer all again to retry."
        }
      }
```

- [ ] **Step 4: Validate JSON**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/en.json','utf8')); console.log('ok')"
```

Expected: `ok`.

- [ ] **Step 5: Run all tests**

```bash
pnpm test
```

Expected: still green (existing tests don't regress).

- [ ] **Step 6: Commit**

Sample subject: `feat(triage): add finalize + bulk transfer i18n keys`.

---

## Task 4: `FinalizeSummaryRow` leaf component

**Files:**
- Create: `frontend/src/features/triage/components/FinalizeSummaryRow.tsx`
- Create: `frontend/src/features/triage/components/__tests__/FinalizeSummaryRow.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/triage/components/__tests__/FinalizeSummaryRow.test.tsx
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { FinalizeSummaryRow } from '../FinalizeSummaryRow';
import type { TriageBucket } from '../../lib/bucketLabels';

const mkBucket = (overrides: Partial<TriageBucket> = {}): TriageBucket => ({
  id: 'bk1',
  bucket_type: 'STAGING',
  category_id: 'cat1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 7,
  ...overrides,
});

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

describe('FinalizeSummaryRow', () => {
  it('renders category name and plural count', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ track_count: 7 })} />);
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(screen.getByText('+7 tracks')).toBeInTheDocument();
  });

  it('renders singular count', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ track_count: 1 })} />);
    expect(screen.getByText('+1 track')).toBeInTheDocument();
  });

  it('renders dash when category_name is null', () => {
    r(<FinalizeSummaryRow bucket={mkBucket({ category_name: null })} />);
    expect(screen.getByText('—')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeSummaryRow.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/features/triage/components/FinalizeSummaryRow.tsx
import { Group, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { TriageBucket } from '../lib/bucketLabels';

export interface FinalizeSummaryRowProps {
  bucket: TriageBucket;
}

export function FinalizeSummaryRow({ bucket }: FinalizeSummaryRowProps) {
  const { t } = useTranslation();
  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      style={{
        padding: 'var(--mantine-spacing-xs) 0',
        borderBottom: '1px solid var(--color-border)',
      }}
    >
      <Text>{bucket.category_name ?? '—'}</Text>
      <Text className="font-mono" c="dimmed">
        +{t('triage.finalize.confirm.row_count', { count: bucket.track_count })}
      </Text>
    </Group>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeSummaryRow.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): add FinalizeSummaryRow component`.

---

## Task 5: `FinalizeBlockerRow` leaf component

**Files:**
- Create: `frontend/src/features/triage/components/FinalizeBlockerRow.tsx`
- Create: `frontend/src/features/triage/components/__tests__/FinalizeBlockerRow.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/triage/components/__tests__/FinalizeBlockerRow.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { FinalizeBlockerRow } from '../FinalizeBlockerRow';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

describe('FinalizeBlockerRow', () => {
  it('renders category name, track count, and Open link with href', () => {
    r(
      <FinalizeBlockerRow
        categoryName="Tech House"
        trackCount={3}
        href="/triage/s1/b1/buckets/bk1"
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByText('Tech House')).toBeInTheDocument();
    expect(screen.getByText('3 tracks')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Open' });
    expect(link).toHaveAttribute('href', '/triage/s1/b1/buckets/bk1');
  });

  it('calls onNavigate when Open link is clicked', async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    r(
      <FinalizeBlockerRow
        categoryName="Cat"
        trackCount={1}
        href="/triage/s1/b1/buckets/bk1"
        onNavigate={onNavigate}
      />,
    );
    await user.click(screen.getByRole('link', { name: 'Open' }));
    expect(onNavigate).toHaveBeenCalledTimes(1);
  });

  it('renders singular for trackCount=1', () => {
    r(
      <FinalizeBlockerRow
        categoryName="X"
        trackCount={1}
        href="/x"
        onNavigate={() => {}}
      />,
    );
    expect(screen.getByText('1 track')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeBlockerRow.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// frontend/src/features/triage/components/FinalizeBlockerRow.tsx
import { Anchor, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';

export interface FinalizeBlockerRowProps {
  categoryName: string;
  trackCount: number;
  href: string;
  onNavigate: () => void;
}

export function FinalizeBlockerRow({
  categoryName,
  trackCount,
  href,
  onNavigate,
}: FinalizeBlockerRowProps) {
  const { t } = useTranslation();
  return (
    <Group
      justify="space-between"
      wrap="nowrap"
      style={{
        padding: 'var(--mantine-spacing-sm)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
      }}
    >
      <Stack gap={2}>
        <Text fw={500}>{categoryName}</Text>
        <Text size="sm" c="dimmed">
          {t('triage.finalize.blocker.row_count', { count: trackCount })}
        </Text>
      </Stack>
      <Anchor component={Link} to={href} onClick={onNavigate}>
        {t('triage.finalize.blocker.open')}
      </Anchor>
    </Group>
  );
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeBlockerRow.test.tsx
```

Expected: 3 passing.

- [ ] **Step 5: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): add FinalizeBlockerRow component`.

---

## Task 6: `FinalizeModal` (confirm + blocker variants + recovery wiring)

**Why now:** Composes Tasks 1-5. The single largest component in F4.

**Files:**
- Create: `frontend/src/features/triage/components/FinalizeModal.tsx`
- Create: `frontend/src/features/triage/components/__tests__/FinalizeModal.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/triage/components/__tests__/FinalizeModal.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { testTheme } from '../../../../test/theme';
import '../../../../i18n';
import { FinalizeModal } from '../FinalizeModal';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function block(overrides: Partial<TriageBlock> = {}): TriageBlock {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'House',
    name: 'Block 1',
    date_from: '2026-04-21',
    date_to: '2026-04-28',
    status: 'IN_PROGRESS',
    created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z',
    finalized_at: null,
    buckets: [],
    ...overrides,
  };
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(blockArg: TriageBlock, qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>
        <Notifications />
        <MemoryRouter>
          <FinalizeModal opened onClose={() => {}} block={blockArg} styleId="s1" />
        </MemoryRouter>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  notifications.clean();
  server.resetHandlers();
});

describe('FinalizeModal — confirm variant', () => {
  it('renders empty-summary copy when block has no STAGING buckets', () => {
    r(block({ buckets: [] }));
    expect(screen.getByText(/no staging buckets/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Finalize' })).toBeEnabled();
  });

  it('renders summary rows + total when STAGING buckets are present', () => {
    r(
      block({
        buckets: [
          { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'A', inactive: false, track_count: 3 },
          { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'B', inactive: false, track_count: 5 },
        ],
      }),
    );
    expect(screen.getByText('A')).toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
    expect(screen.getByText('+3 tracks')).toBeInTheDocument();
    expect(screen.getByText('+5 tracks')).toBeInTheDocument();
    expect(screen.getByText(/8 tracks will be promoted into 2 categories/i)).toBeInTheDocument();
  });

  it('fires green success toast on 200 OK and closes modal', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            block: { ...block(), status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' },
            promoted: { cA: 3, cB: 5 },
          },
          { status: 200 },
        ),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={makeClient()}>
        <MantineProvider theme={testTheme}>
          <Notifications />
          <MemoryRouter>
            <FinalizeModal
              opened
              onClose={onClose}
              block={block({
                buckets: [
                  { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'A', inactive: false, track_count: 3 },
                  { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'B', inactive: false, track_count: 5 },
                ],
              })}
              styleId="s1"
            />
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() =>
      expect(screen.getByText(/Finalized Block 1.*promoted 8 tracks across 2 categories/i)).toBeInTheDocument(),
    );
    expect(onClose).toHaveBeenCalled();
  });

  it('shows red toast and closes modal on 422 invalid_state', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'block is not editable' },
          { status: 422 },
        ),
      ),
    );
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={makeClient()}>
        <MantineProvider theme={testTheme}>
          <Notifications />
          <MemoryRouter>
            <FinalizeModal opened onClose={onClose} block={block()} styleId="s1" />
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() => expect(screen.getByText(/already finalized/i)).toBeInTheDocument());
    expect(onClose).toHaveBeenCalled();
  });

  it('flips to blocker variant on 409 with inactive_buckets payload', async () => {
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            error_code: 'inactive_buckets_have_tracks',
            message: '1 inactive staging holds tracks',
            inactive_buckets: [{ id: 'bkX', category_id: 'cX', track_count: 4 }],
          },
          { status: 409 },
        ),
      ),
    );
    const user = userEvent.setup();
    r(block());
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    await waitFor(() => expect(screen.getByText('Cannot finalize yet')).toBeInTheDocument());
    expect(screen.getByText('4 tracks')).toBeInTheDocument();
  });
});

describe('FinalizeModal — blocker variant (preempt)', () => {
  it('renders blocker variant when local block has inactive STAGING with tracks', () => {
    r(
      block({
        buckets: [
          { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'Deleted Cat', inactive: true, track_count: 9 },
        ],
      }),
    );
    expect(screen.getByText('Cannot finalize yet')).toBeInTheDocument();
    expect(screen.getByText('Deleted Cat')).toBeInTheDocument();
    expect(screen.getByText('9 tracks')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Finalize' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/triage/s1/b1/buckets/sa',
    );
  });
});

describe('FinalizeModal — 503 cold-start recovery', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
  afterEach(() => vi.useRealTimers());

  it('switches to recovering phase on 503; success on poll flip', async () => {
    let postCount = 0;
    let getCount = 0;
    server.use(
      http.post('https://api.test/triage/blocks/b1/finalize', () => {
        postCount++;
        return HttpResponse.json({ message: 'Service Unavailable' }, { status: 503 });
      }),
      http.get('https://api.test/triage/blocks/b1', () => {
        getCount++;
        if (getCount === 1) {
          return HttpResponse.json({
            ...block(),
            status: 'IN_PROGRESS',
          });
        }
        return HttpResponse.json({
          ...block(),
          status: 'FINALIZED',
          finalized_at: '2026-04-29T00:00:00Z',
        });
      }),
    );
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const onClose = vi.fn();
    render(
      <QueryClientProvider client={makeClient()}>
        <MantineProvider theme={testTheme}>
          <Notifications />
          <MemoryRouter>
            <FinalizeModal opened onClose={onClose} block={block()} styleId="s1" />
          </MemoryRouter>
        </MantineProvider>
      </QueryClientProvider>,
    );
    await user.click(screen.getByRole('button', { name: 'Finalize' }));
    // tick 1 (t=0): IN_PROGRESS — keep recovering
    await vi.advanceTimersByTimeAsync(0);
    expect(screen.getByText(/cold start, hang on/i)).toBeInTheDocument();
    // tick 2 (t=15s): FINALIZED — success
    await vi.advanceTimersByTimeAsync(15_000);
    await waitFor(() =>
      expect(screen.getByText(/Finalize succeeded after retry/i)).toBeInTheDocument(),
    );
    expect(onClose).toHaveBeenCalled();
    expect(postCount).toBe(1);
  });
});
```

NOTE: the test counts on `apiClient` base URL `https://api.test`. If different, update.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeModal.test.tsx
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement `FinalizeModal`**

```tsx
// frontend/src/features/triage/components/FinalizeModal.tsx
import { useState } from 'react';
import {
  Anchor,
  Button,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
} from '@mantine/core';
import { Link } from 'react-router';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError } from '../../../api/error';
import { api } from '../../../api/client';
import {
  type TriageBlock,
  triageBlockKey,
} from '../hooks/useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from '../hooks/useTriageBlocksByStyle';
import {
  useFinalizeTriageBlock,
  type FinalizeErrorBody,
  type InactiveBucketRow,
} from '../hooks/useFinalizeTriageBlock';
import { schedulePendingFinalizeRecovery } from '../lib/pendingFinalizeRecovery';
import { FinalizeSummaryRow } from './FinalizeSummaryRow';
import { FinalizeBlockerRow } from './FinalizeBlockerRow';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export interface FinalizeModalProps {
  opened: boolean;
  onClose: () => void;
  block: TriageBlock;
  styleId: string;
}

type Phase = 'idle' | 'pending' | 'recovering';

export function FinalizeModal({ opened, onClose, block, styleId }: FinalizeModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const finalize = useFinalizeTriageBlock(block.id, styleId);

  const [phase, setPhase] = useState<Phase>('idle');
  const [serverInactive, setServerInactive] = useState<InactiveBucketRow[] | null>(null);

  const localInactive: InactiveBucketRow[] = block.buckets
    .filter((b) => b.bucket_type === 'STAGING' && b.inactive && b.track_count > 0)
    .map((b) => ({
      id: b.id,
      category_id: b.category_id ?? '',
      track_count: b.track_count,
    }));
  const inactiveBuckets = serverInactive ?? localInactive;
  const blocked = inactiveBuckets.length > 0;

  const stagingActive = block.buckets.filter(
    (b) => b.bucket_type === 'STAGING' && !b.inactive,
  );
  const totalToPromote = stagingActive.reduce((acc, b) => acc + b.track_count, 0);

  const closeIfIdle = () => {
    if (phase === 'pending' || phase === 'recovering') return;
    setPhase('idle');
    setServerInactive(null);
    onClose();
  };

  const scheduleRecovery = () => {
    setPhase('recovering');
    schedulePendingFinalizeRecovery({
      blockId: block.id,
      refetch: () =>
        qc.fetchQuery({
          queryKey: triageBlockKey(block.id),
          queryFn: () => api<TriageBlock>(`/triage/blocks/${block.id}`),
        }),
      onSuccess: (refreshed) => {
        const promotedCount = refreshed.buckets
          .filter((b) => b.bucket_type === 'STAGING' && !b.inactive)
          .reduce((a, c) => a + c.track_count, 0);
        const promotedM = refreshed.buckets.filter(
          (b) => b.bucket_type === 'STAGING' && !b.inactive,
        ).length;
        notifications.show({
          color: 'green',
          message: t('triage.finalize.toast.success_recovered', {
            count: promotedCount,
            blockName: block.name,
            categoryCount: promotedM,
          }),
        });
        qc.invalidateQueries({ queryKey: triageBlockKey(block.id) });
        for (const s of STATUSES) {
          qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
        }
        setPhase('idle');
        onClose();
      },
      onFailure: () => {
        notifications.show({
          color: 'red',
          message: t('triage.finalize.toast.cold_start_terminal'),
        });
        setPhase('idle');
      },
    });
  };

  const handleSubmit = () => {
    setPhase('pending');
    finalize.mutate(undefined, {
      onSuccess: (resp) => {
        const promoted = resp.promoted ?? {};
        const n = Object.values(promoted).reduce((a, c) => a + c, 0);
        const m = Object.keys(promoted).length;
        notifications.show({
          color: 'green',
          message: t('triage.finalize.toast.success', {
            count: n,
            blockName: block.name,
            categoryCount: m,
          }),
        });
        setPhase('idle');
        onClose();
      },
      onError: (err) => {
        handleFinalizeError({
          err,
          t,
          qc,
          blockId: block.id,
          styleId,
          setServerInactive,
          setPhase,
          scheduleRecovery,
        });
      },
    });
  };

  const title = blocked
    ? t('triage.finalize.blocker.title')
    : t('triage.finalize.confirm.title', { blockName: block.name });

  return (
    <Modal opened={opened} onClose={closeIfIdle} size="lg" title={title}>
      {blocked ? (
        <BlockerVariant
          inactiveBuckets={inactiveBuckets}
          block={block}
          styleId={styleId}
          onClose={closeIfIdle}
        />
      ) : (
        <ConfirmVariant
          stagingActive={stagingActive}
          totalToPromote={totalToPromote}
          phase={phase}
          onSubmit={handleSubmit}
          onCancel={closeIfIdle}
        />
      )}
    </Modal>
  );
}

interface ConfirmVariantProps {
  stagingActive: TriageBlock['buckets'];
  totalToPromote: number;
  phase: Phase;
  onSubmit: () => void;
  onCancel: () => void;
}

function ConfirmVariant({
  stagingActive,
  totalToPromote,
  phase,
  onSubmit,
  onCancel,
}: ConfirmVariantProps) {
  const { t } = useTranslation();
  const isEmpty = stagingActive.length === 0;
  return (
    <Stack gap="md">
      <Text>
        {isEmpty
          ? t('triage.finalize.confirm.empty_summary')
          : t('triage.finalize.confirm.body', {
              count: totalToPromote,
              categoryCount: stagingActive.length,
            })}
      </Text>
      {!isEmpty && (
        <Stack gap="xs">
          {stagingActive.map((b) => (
            <FinalizeSummaryRow key={b.id} bucket={b} />
          ))}
        </Stack>
      )}
      {phase === 'recovering' && (
        <Group gap="xs">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t('triage.finalize.confirm.recovering')}
          </Text>
        </Group>
      )}
      <Group justify="flex-end" gap="sm">
        <Button variant="subtle" onClick={onCancel} disabled={phase !== 'idle'}>
          {t('triage.finalize.confirm.cancel')}
        </Button>
        <Button onClick={onSubmit} loading={phase === 'pending'} disabled={phase !== 'idle'}>
          {t('triage.finalize.confirm.submit')}
        </Button>
      </Group>
    </Stack>
  );
}

interface BlockerVariantProps {
  inactiveBuckets: InactiveBucketRow[];
  block: TriageBlock;
  styleId: string;
  onClose: () => void;
}

function BlockerVariant({
  inactiveBuckets,
  block,
  styleId,
  onClose,
}: BlockerVariantProps) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Text>{t('triage.finalize.blocker.body', { count: inactiveBuckets.length })}</Text>
      <Stack gap="xs">
        {inactiveBuckets.map((ib) => {
          const localBucket = block.buckets.find((b) => b.id === ib.id);
          const name =
            localBucket?.category_name ?? t('triage.finalize.blocker.unknown_category');
          return (
            <FinalizeBlockerRow
              key={ib.id}
              categoryName={name}
              trackCount={ib.track_count}
              href={`/triage/${styleId}/${block.id}/buckets/${ib.id}`}
              onNavigate={onClose}
            />
          );
        })}
      </Stack>
      <Group justify="flex-end" gap="sm">
        <Button variant="subtle" onClick={onClose}>
          {t('triage.finalize.blocker.dismiss')}
        </Button>
        <Button disabled>{t('triage.finalize.confirm.submit')}</Button>
      </Group>
    </Stack>
  );
}

interface ErrorCtx {
  err: ApiError | unknown;
  t: TFunction;
  qc: QueryClient;
  blockId: string;
  styleId: string;
  setServerInactive: (rows: InactiveBucketRow[] | null) => void;
  setPhase: (p: Phase) => void;
  scheduleRecovery: () => void;
}

function handleFinalizeError(ctx: ErrorCtx): void {
  const { err, t, qc, blockId, styleId } = ctx;
  if (!(err instanceof ApiError)) {
    notifications.show({ color: 'red', message: t('errors.network') });
    ctx.setPhase('idle');
    return;
  }
  if (err.status === 503) {
    ctx.scheduleRecovery();
    return;
  }
  if (err.code === 'inactive_buckets_have_tracks') {
    const body = err.raw as FinalizeErrorBody | undefined;
    const rows = body?.inactive_buckets ?? [];
    ctx.setServerInactive(rows);
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    notifications.show({
      color: 'orange',
      message: t('triage.finalize.toast.blocked_race', { count: rows.length }),
    });
    ctx.setPhase('idle');
    return;
  }
  if (err.code === 'triage_block_not_found') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.stale_block') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    for (const s of STATUSES) qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
    ctx.setPhase('idle');
    return;
  }
  if (err.code === 'invalid_state') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.already_finalized') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    ctx.setPhase('idle');
    return;
  }
  notifications.show({ color: 'red', message: t('triage.finalize.toast.error') });
  ctx.setPhase('idle');
}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/components/__tests__/FinalizeModal.test.tsx
```

Expected: 7 passing.

- [ ] **Step 5: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): add FinalizeModal with confirm + blocker variants`.

---

## Task 7: `TriageBlockHeader` Finalize CTA + remove dead `finalize_coming_soon` key

**Files:**
- Modify: `frontend/src/features/triage/components/TriageBlockHeader.tsx`
- Modify: `frontend/src/i18n/en.json` (remove `triage.detail.finalize_coming_soon`)
- Update: existing tests under `frontend/src/features/triage/components/__tests__/TriageBlockHeader.test.tsx` (if present — check first)

- [ ] **Step 1: Locate existing test file (if any)**

```bash
ls frontend/src/features/triage/components/__tests__/ | grep -i header
```

If a `TriageBlockHeader.test.tsx` exists, read it to understand current contract before editing. The plan assumes existing tests are minimal and will be augmented inline; if not present, write a fresh test.

- [ ] **Step 2: Write or extend the failing test**

```tsx
// frontend/src/features/triage/components/__tests__/TriageBlockHeader.test.tsx
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { TriageBlockHeader } from '../TriageBlockHeader';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function block(overrides: Partial<TriageBlock> = {}): TriageBlock {
  return {
    id: 'b1', style_id: 's1', style_name: 'House', name: 'Block 1',
    date_from: '2026-04-21', date_to: '2026-04-28',
    status: 'IN_PROGRESS', created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z', finalized_at: null, buckets: [],
    ...overrides,
  };
}

describe('TriageBlockHeader Finalize CTA', () => {
  it('renders enabled Finalize button when status=IN_PROGRESS and calls onFinalize', async () => {
    const onFinalize = vi.fn();
    const user = userEvent.setup();
    render(
      <MantineProvider>
        <TriageBlockHeader block={block()} onDelete={() => {}} onFinalize={onFinalize} />
      </MantineProvider>,
    );
    const btn = screen.getByRole('button', { name: 'Finalize' });
    expect(btn).toBeEnabled();
    await user.click(btn);
    expect(onFinalize).toHaveBeenCalledTimes(1);
  });

  it('does not render Finalize when status=FINALIZED', () => {
    render(
      <MantineProvider>
        <TriageBlockHeader
          block={block({ status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' })}
          onDelete={() => {}}
          onFinalize={() => {}}
        />
      </MantineProvider>,
    );
    expect(screen.queryByRole('button', { name: 'Finalize' })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pnpm test src/features/triage/components/__tests__/TriageBlockHeader.test.tsx
```

Expected: FAIL — `onFinalize` prop missing or button is disabled (placeholder).

- [ ] **Step 4: Update `TriageBlockHeader`**

Edit `frontend/src/features/triage/components/TriageBlockHeader.tsx`:
- Add `onFinalize: () => void` to props.
- Replace the `Tooltip + disabled Button` block.
- Remove `Tooltip` import if no longer used.

Final shape:

```tsx
// frontend/src/features/triage/components/TriageBlockHeader.tsx
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Menu,
  Stack,
  Text,
  Title,
} from '@mantine/core';
import { useTranslation } from 'react-i18next';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { IconDots } from '../../../components/icons';
import type { TriageBlock } from '../hooks/useTriageBlock';

dayjs.extend(relativeTime);

export interface TriageBlockHeaderProps {
  block: TriageBlock;
  onDelete: () => void;
  onFinalize: () => void;
}

export function TriageBlockHeader({ block, onDelete, onFinalize }: TriageBlockHeaderProps) {
  const { t } = useTranslation();
  const isFinalized = block.status === 'FINALIZED';

  return (
    <Stack gap="sm">
      <Group justify="space-between" wrap="nowrap" align="flex-start">
        <Stack gap={2}>
          <Title order={2}>{block.name}</Title>
          <Group gap="xs" wrap="wrap">
            <Text c="dimmed" size="sm">
              {t('triage.detail.header.date_range', {
                from: block.date_from,
                to: block.date_to,
              })}
            </Text>
            <Badge variant={isFinalized ? 'light' : 'filled'}>{block.status}</Badge>
            <Text c="dimmed" size="sm">
              {t('triage.detail.header.created', { relative: dayjs(block.created_at).fromNow() })}
            </Text>
            {isFinalized && block.finalized_at && (
              <Text c="dimmed" size="sm">
                {t('triage.detail.header.finalized', {
                  relative: dayjs(block.finalized_at).fromNow(),
                })}
              </Text>
            )}
          </Group>
        </Stack>
        {!isFinalized && (
          <Group gap="xs">
            <Button onClick={onFinalize}>{t('triage.detail.finalize_cta')}</Button>
            <Menu position="bottom-end" withinPortal>
              <Menu.Target>
                <ActionIcon variant="subtle" aria-label={t('triage.detail.kebab.delete')}>
                  <IconDots size={16} />
                </ActionIcon>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item color="red" onClick={onDelete}>
                  {t('triage.detail.kebab.delete')}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        )}
      </Group>
    </Stack>
  );
}
```

- [ ] **Step 5: Remove `triage.detail.finalize_coming_soon` from `en.json`**

Open `frontend/src/i18n/en.json` and delete the `"finalize_coming_soon": "Coming in F4",` line inside `triage.detail`.

- [ ] **Step 6: Run header + module tests**

```bash
pnpm test src/features/triage/components/__tests__/TriageBlockHeader.test.tsx
pnpm test
```

Expected: header tests pass; full suite still green.

- [ ] **Step 7: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): activate Finalize CTA in TriageBlockHeader`.

---

## Task 8: `TriageDetailPage` mounts `FinalizeModal`

**Files:**
- Modify: `frontend/src/features/triage/routes/TriageDetailPage.tsx`
- Modify: `frontend/src/features/triage/__tests__/TriageDetailPage.integration.test.tsx` (extend; existing file)

- [ ] **Step 1: Read the existing integration test to understand its shape**

```bash
sed -n '1,80p' frontend/src/features/triage/__tests__/TriageDetailPage.integration.test.tsx
```

Identify a suitable place to add a Finalize-flow test alongside existing detail/delete tests.

- [ ] **Step 2: Write the failing test**

Append to `TriageDetailPage.integration.test.tsx`:

```tsx
it('opens FinalizeModal when Finalize button is clicked', async () => {
  // Reuse the existing helper that mounts TriageDetailPage with MSW handlers.
  // Replace the placeholder helper name with whatever the file already uses.
  const user = userEvent.setup();
  // ...mount TriageDetailPage at /triage/s1/b1 with a IN_PROGRESS block fixture...
  await screen.findByRole('button', { name: 'Finalize' });
  await user.click(screen.getByRole('button', { name: 'Finalize' }));
  // Modal title checks confirm variant rendered:
  await waitFor(() => expect(screen.getByText(/Finalize Block 1\?/i)).toBeInTheDocument());
});
```

If the file's existing helpers do not already cover the IN_PROGRESS block fixture, add a small fresh `describe(...)` block at the bottom that uses the same provider tree as `TransferFlow.integration.test.tsx` (see `frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx:71-90`).

- [ ] **Step 3: Run test to verify it fails**

```bash
pnpm test src/features/triage/__tests__/TriageDetailPage.integration.test.tsx
```

Expected: FAIL — Finalize button is disabled or modal does not open.

- [ ] **Step 4: Update `TriageDetailPage` to mount the modal**

Edit `frontend/src/features/triage/routes/TriageDetailPage.tsx`:

```tsx
import { useState } from 'react';
// ...existing imports...
import { FinalizeModal } from '../components/FinalizeModal';

// Inside TriageDetailInner:
const [finalizeOpen, setFinalizeOpen] = useState(false);

// In return JSX, replace existing TriageBlockHeader usage:
<TriageBlockHeader
  block={data}
  onDelete={handleDelete}
  onFinalize={() => setFinalizeOpen(true)}
/>

// Below BucketGrid, add:
{finalizeOpen && (
  <FinalizeModal
    opened
    onClose={() => setFinalizeOpen(false)}
    block={data}
    styleId={styleId}
  />
)}
```

The full updated `TriageDetailInner` looks like:

```tsx
function TriageDetailInner({ styleId, blockId }: InnerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useTriageBlock(blockId);
  const del = useDeleteTriageBlock(styleId);
  const [finalizeOpen, setFinalizeOpen] = useState(false);

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    // ...existing error rendering unchanged...
  }
  if (!data) return null;

  const handleDelete = () => {
    // ...existing delete flow unchanged...
  };

  return (
    <Stack gap="lg">
      <Anchor component={Link} to={`/triage/${styleId}`} c="var(--color-fg)" td="none">
        {t('triage.detail.back_to_list')}
      </Anchor>
      <TriageBlockHeader
        block={data}
        onDelete={handleDelete}
        onFinalize={() => setFinalizeOpen(true)}
      />
      <BucketGrid buckets={data.buckets} styleId={styleId} blockId={blockId} />
      {finalizeOpen && (
        <FinalizeModal
          opened
          onClose={() => setFinalizeOpen(false)}
          block={data}
          styleId={styleId}
        />
      )}
    </Stack>
  );
}
```

Keep all existing imports intact; add `useState` and `FinalizeModal`.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pnpm test src/features/triage/__tests__/TriageDetailPage.integration.test.tsx
pnpm test
```

Expected: full suite green.

- [ ] **Step 6: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): mount FinalizeModal on TriageDetailPage`.

---

## Task 9: `TransferModal` prop refactor + bulk mode + chunk loop

**Why now:** Bulk transfer in F4 reuses `TransferModal`. Refactoring the existing single-track surface preserves F3b semantics while opening up the bulk path.

**Files:**
- Modify: `frontend/src/features/triage/components/TransferModal.tsx`
- Modify: `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx` (existing)
- Modify: `frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx` (existing — verify single-track callsite still works)
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx` (only the F3b single-track callsite — pass `trackIds={[transferTrackId]}`)

**Approach:** Two passes:
- (a) Rename `trackId: string` → `trackIds: string[]`. Update F3b callsite. Run tests; previously-green tests stay green.
- (b) Add `mode?: 'single' | 'bulk'` + bulk chunk loop + bulk-progress UI + bulk-success/partial toast wiring. Add new tests.

Splitting into two passes reduces blast radius and gives a clean intermediate green run.

- [ ] **Step 1: Pass A — write the F3b callsite update**

Edit `frontend/src/features/triage/routes/BucketDetailPage.tsx`:
- Line 197 area: `trackId={transferTrackId}` → `trackIds={[transferTrackId]}`.

Edit `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx`:
- Wherever existing tests pass `trackId="t-1"` (or similar), replace with `trackIds={['t-1']}`. Don't change assertions.

- [ ] **Step 2: Pass A — update `TransferModal` signature and `handlePickBucket`**

Edit `frontend/src/features/triage/components/TransferModal.tsx`:
- Rename prop in `TransferModalProps`: `trackId: string` → `trackIds: string[]`.
- Where `handlePickBucket` calls `transfer.mutate({ ..., trackIds: [trackId], ... })`, change to `trackIds`.
- Toast count: `count: trackIds.length` (was `count: 1`).

Single-track path (no `mode` check yet — added in Pass B).

- [ ] **Step 3: Pass A — run tests**

```bash
pnpm test
```

Expected: all green (no behavioural change).

- [ ] **Step 4: Pass B — write the failing bulk-mode tests**

Append to `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx`:

```tsx
describe('TransferModal — bulk mode', () => {
  beforeEach(() => server.resetHandlers());
  afterEach(() => { notifications.clean(); server.resetHandlers(); });

  it('mode=bulk, 100 trackIds → 1 chunk, success toast', async () => {
    let postCount = 0;
    server.use(
      http.post('https://api.test/triage/blocks/src1/transfer', async ({ request }) => {
        postCount++;
        const body = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json({ transferred: body.track_ids.length }, { status: 200 });
      }),
    );
    // mount modal with trackIds = 100 items, mode='bulk', step pre-set to 'bucket' via test helper or normal flow
    // ...pick a non-inactive target bucket...
    // assert: postCount=1, green toast 'Transferred 100 tracks to ...'
  });

  it('mode=bulk, 1500 trackIds → 2 chunks fired sequentially', async () => {
    // mock 2 successful POSTs; assert order via incremental counter
    // assert: green toast 'Transferred 1500 tracks ...'
  });

  it('mode=bulk, mid-chunk error → orange partial toast + modal stays on step 2', async () => {
    // mock first POST 200, second POST 422 invalid_state
    // assert: orange toast Transferred 1000 of 3000... + red toast target_finalized
    // assert: modal still mounted; bucket grid not disabled (bulkPhase null)
  });
});
```

The test fixtures (`SRC_BLOCK`, `TGT_BLOCK`, `TRACK`) already exist in the file or its parent — reuse them. If not, copy from `TransferFlow.integration.test.tsx:16-63`.

- [ ] **Step 5: Pass B — run tests to verify they fail**

```bash
pnpm test src/features/triage/components/__tests__/TransferModal.test.tsx
```

Expected: 3 new failures — bulk mode unimplemented.

- [ ] **Step 6: Pass B — implement bulk mode**

Edit `frontend/src/features/triage/components/TransferModal.tsx`:
- Add `mode?: 'single' | 'bulk'` to `TransferModalProps` (default `'single'`).
- Add `cancelledRef = useRef(false)`; reset on close.
- Add `bulkPhase` state: `useState<{ k: number; m: number } | null>(null)`.
- In `handlePickBucket`: branch on `mode === 'bulk'`.
- Add `runBulkTransfer` async helper that loops `mutateAsync` with chunk slices; updates `bulkPhase`; surfaces partial/success toasts.
- In `Step2` props: thread `bulkPhase` and render the progress text when set; `disabled` includes `bulkPhase !== null`.

Updated key parts:

```tsx
const BULK_CHUNK_SIZE = 1000;

export interface TransferModalProps {
  opened: boolean;
  onClose: () => void;
  srcBlock: TriageBlock;
  trackIds: string[];
  styleId: string;
  mode?: 'single' | 'bulk';
}

export function TransferModal({
  opened,
  onClose,
  srcBlock,
  trackIds,
  styleId,
  mode = 'single',
}: TransferModalProps) {
  // ...existing state...
  const [bulkPhase, setBulkPhase] = useState<{ k: number; m: number } | null>(null);
  const cancelledRef = useRef(false);

  // ...existing useEffect resetting on close — also reset bulkPhase + cancelledRef...

  const handleClose = () => {
    cancelledRef.current = true;
    setBulkPhase(null);
    setStep('block');
    setTargetBlockId(null);
    onClose();
  };

  const runBulkTransfer = async (
    targetBlockId: string,
    bucket: TriageBucket,
  ) => {
    cancelledRef.current = false;
    const total = trackIds.length;
    const chunks: string[][] = [];
    for (let i = 0; i < total; i += BULK_CHUNK_SIZE) {
      chunks.push(trackIds.slice(i, i + BULK_CHUNK_SIZE));
    }
    let transferred = 0;
    for (let i = 0; i < chunks.length; i++) {
      if (cancelledRef.current) return;
      setBulkPhase({ k: i + 1, m: chunks.length });
      try {
        const resp = await transfer.mutateAsync({
          targetBlockId,
          targetBucketId: bucket.id,
          trackIds: chunks[i],
          styleId,
        });
        transferred += resp.transferred;
      } catch (err) {
        notifications.show({
          color: 'orange',
          message: t('triage.transfer.bulk.toast.partial', {
            count: transferred,
            total,
            blockName: targetBlockQuery.data?.name ?? '',
            bucketLabel: bucketLabel(bucket, t),
          }),
        });
        handleTransferError({
          err, t, qc, styleId, srcBlockId: srcBlock.id, targetBlockId,
          setStep, close: handleClose,
        });
        setBulkPhase(null);
        return;
      }
    }
    setBulkPhase(null);
    notifications.show({
      color: 'green',
      message: t('triage.transfer.bulk.toast.success', {
        count: transferred,
        blockName: targetBlockQuery.data?.name ?? '',
        bucketLabel: bucketLabel(bucket, t),
      }),
    });
    handleClose();
  };

  const handlePickBucket = (bucket: TriageBucket) => {
    if (!targetBlockId) return;
    if (mode === 'single') {
      transfer.mutate(
        { targetBlockId, targetBucketId: bucket.id, trackIds, styleId },
        {
          onSuccess: () => {
            notifications.show({
              color: 'green',
              message: t('triage.transfer.toast.transferred', {
                count: trackIds.length,
                block_name: targetBlockQuery.data?.name ?? '',
                bucket_label: bucketLabel(bucket, t),
              }),
            });
            handleClose();
          },
          onError: (err) =>
            handleTransferError({
              err, t, qc, styleId, srcBlockId: srcBlock.id, targetBlockId,
              setStep, close: handleClose,
            }),
        },
      );
      return;
    }
    void runBulkTransfer(targetBlockId, bucket);
  };
```

Wire `bulkPhase` into `Step2` so the progress text renders and `BucketGrid` `disabled` includes it:

```tsx
function Step2({ loading, targetBlock, transferPending, bulkPhase, onBack, onPick }: Step2Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Anchor component="button" type="button" onClick={onBack}>
          {t('triage.transfer.modal.back')}
        </Anchor>
      </Group>
      {loading && (<Center py="xl"><Loader /></Center>)}
      {bulkPhase && (
        <Group gap="xs">
          <Loader size="sm" />
          <Text size="sm">
            {t('triage.transfer.bulk.modal.batch_progress', {
              k: bulkPhase.k, m: bulkPhase.m,
            })}
          </Text>
        </Group>
      )}
      {targetBlock && (
        <BucketGrid
          buckets={targetBlock.buckets}
          styleId={targetBlock.style_id}
          blockId={targetBlock.id}
          mode="select"
          cols={{ base: 1, xs: 2 }}
          onSelect={onPick}
          disabled={transferPending || bulkPhase !== null}
        />
      )}
    </Stack>
  );
}
```

Add `bulkPhase: { k: number; m: number } | null` to `Step2Props` and thread from parent:

```tsx
{step === 'bucket' && (
  <Step2
    loading={targetBlockQuery.isLoading}
    targetBlock={targetBlockQuery.data}
    transferPending={transfer.isPending}
    bulkPhase={bulkPhase}
    onBack={() => setStep('block')}
    onPick={handlePickBucket}
  />
)}
```

The `useEffect` that resets state on `opened=false` should also reset `bulkPhase` and set `cancelledRef.current = false` on each open. Update accordingly.

- [ ] **Step 7: Pass B — run tests to verify they pass**

```bash
pnpm test src/features/triage/components/__tests__/TransferModal.test.tsx
pnpm test
```

Expected: full suite green including the 3 new bulk tests.

- [ ] **Step 8: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): TransferModal bulk mode + chunk loop`.

---

## Task 10: `BucketDetailPage` bulk transfer header CTA

**Files:**
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx`
- Modify: `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx` (existing)

- [ ] **Step 1: Write the failing test (gating + drain + open)**

Append to `BucketDetailPage.integration.test.tsx`:

```tsx
describe('BucketDetailPage — bulk transfer CTA', () => {
  it('hides the button on STAGING buckets of FINALIZED block', async () => {
    // mount with FINALIZED block + STAGING bucket fixture
    // assert: queryByRole('button', { name: /transfer all/i }) is null
  });

  it('hides the button on tech bucket of IN_PROGRESS block', async () => {
    // mount with IN_PROGRESS block + NEW bucket fixture
    // assert: queryByRole('button', { name: /transfer all/i }) is null
  });

  it('hides the button when bucket has 0 tracks', async () => {
    // mount with FINALIZED + NEW bucket + track_count: 0
    // assert: button absent
  });

  it('drains pages then opens TransferModal pre-filled with trackIds', async () => {
    // FINALIZED block + NEW bucket + 75 tracks (2 pages of 50)
    // mock GET /triage/blocks/{id}/buckets/{bucketId}/tracks?limit=50&offset=0 → 50 items
    // mock GET ...&offset=50 → 25 items
    // click 'Transfer all to another block…'
    // assert: button shows loading, eventually modal opens (title 'Transfer to which block?')
  });
});
```

Reuse the existing helper / fixtures in the file. If the file lacks a FINALIZED-block fixture, derive one from the F3a `BucketDetailPage.integration.test.tsx` IN_PROGRESS fixture by setting `status: 'FINALIZED'` and `finalized_at`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
```

Expected: 4 failures.

- [ ] **Step 3: Implement the bulk CTA in `BucketDetailPage`**

Edit `frontend/src/features/triage/routes/BucketDetailPage.tsx`:

Add imports:

```tsx
import { useEffect, useState } from 'react';
import { Button } from '@mantine/core';
import { IconArrowsExchange } from '../../../components/icons';
import { useBucketTracks } from '../hooks/useBucketTracks';
```

Inside `BucketDetailInner` after `bucket` is resolved:

```tsx
const showBulkTransfer =
  block.status === 'FINALIZED' &&
  bucket.bucket_type !== 'STAGING' &&
  bucket.track_count > 0;

const tracksQuery = useBucketTracks(blockId, bucketId, '');
const [bulkTransferOpen, setBulkTransferOpen] = useState(false);
const [bulkTrackIds, setBulkTrackIds] = useState<string[] | null>(null);
const [collecting, setCollecting] = useState(false);

const handleOpenBulk = async () => {
  if (collecting) return;
  setCollecting(true);
  try {
    while (tracksQuery.hasNextPage && !tracksQuery.isFetchingNextPage) {
      await tracksQuery.fetchNextPage();
    }
    const allIds = (tracksQuery.data?.pages ?? []).flatMap((p) =>
      p.items.map((t) => t.track_id),
    );
    setBulkTrackIds(allIds);
    setBulkTransferOpen(true);
  } catch {
    notifications.show({ color: 'red', message: t('errors.network') });
  } finally {
    setCollecting(false);
  }
};
```

In the JSX, locate the existing header block (the `Stack gap="xs"` containing `Title` + `BucketBadge`). Wrap the whole inner `Group gap="md" align="center"` so the right side hosts the new button:

```tsx
<Stack gap="xs">
  <Group justify="space-between" wrap="nowrap" align="center">
    <Group gap="md" align="center">
      <Title order={2}>{bucketLabel(bucket, t)}</Title>
      <BucketBadge bucket={bucket} size="md" />
    </Group>
    {showBulkTransfer && (
      <Button
        variant="light"
        leftSection={<IconArrowsExchange size={14} />}
        onClick={handleOpenBulk}
        loading={collecting}
        disabled={collecting}
      >
        {t('triage.transfer.bulk.cta')}
      </Button>
    )}
  </Group>
  <Text c="dimmed" size="sm">
    {t('triage.bucket.header.subtitle', {
      count: bucket.track_count,
      block_name: block.name,
      from: block.date_from,
      to: block.date_to,
    })}
  </Text>
</Stack>
```

Below the existing `TransferModal` mount (single-track), add the bulk modal mount:

```tsx
{bulkTransferOpen && bulkTrackIds && (
  <TransferModal
    opened
    onClose={() => {
      setBulkTransferOpen(false);
      setBulkTrackIds(null);
    }}
    srcBlock={block}
    trackIds={bulkTrackIds}
    styleId={styleId}
    mode="bulk"
  />
)}
```

Verify `IconArrowsExchange` is exported from `frontend/src/components/icons.ts` (added in F3b — confirm with `grep IconArrowsExchange frontend/src/components/icons.ts`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
pnpm test
```

Expected: full suite green.

- [ ] **Step 5: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `feat(triage): bulk transfer CTA on finalized tech buckets`.

---

## Task 11: `index.ts` re-exports

**Files:**
- Modify: `frontend/src/features/triage/index.ts`

- [ ] **Step 1: Add re-exports**

Edit `frontend/src/features/triage/index.ts` to append:

```ts
export { FinalizeModal } from './components/FinalizeModal';
export { useFinalizeTriageBlock } from './hooks/useFinalizeTriageBlock';
```

Final file:

```ts
export { TriageIndexRedirect } from './routes/TriageIndexRedirect';
export { TriageListPage } from './routes/TriageListPage';
export { TriageDetailPage } from './routes/TriageDetailPage';
export { BucketDetailPage } from './routes/BucketDetailPage';
export { TransferModal } from './components/TransferModal';
export { useTransferTracks } from './hooks/useTransferTracks';
export { FinalizeModal } from './components/FinalizeModal';
export { useFinalizeTriageBlock } from './hooks/useFinalizeTriageBlock';
```

- [ ] **Step 2: Typecheck + run tests**

```bash
pnpm typecheck
pnpm test
```

Expected: green.

- [ ] **Step 3: Commit**

Sample subject: `chore(triage): re-export FinalizeModal + useFinalizeTriageBlock`.

---

## Task 12: `FinalizeFlow.integration.test.tsx`

**Files:**
- Create: `frontend/src/features/triage/__tests__/FinalizeFlow.integration.test.tsx`

End-to-end coverage of the spec's §11.2 scenarios that aren't already covered by per-component tests.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/features/triage/__tests__/FinalizeFlow.integration.test.tsx
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { testTheme } from '../../../test/theme';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { TriageDetailPage } from '../routes/TriageDetailPage';
import { BucketDetailPage } from '../routes/BucketDetailPage';

const IN_PROGRESS_BLOCK = {
  id: 'b1', style_id: 's1', style_name: 'House', name: 'Block 1',
  date_from: '2026-04-21', date_to: '2026-04-28',
  status: 'IN_PROGRESS', created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z', finalized_at: null,
  buckets: [
    { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'A', inactive: false, track_count: 3 },
    { id: 'sb', bucket_type: 'STAGING', category_id: 'cB', category_name: 'B', inactive: false, track_count: 5 },
    { id: 'NEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
  ],
};

const FINALIZED_BLOCK = {
  ...IN_PROGRESS_BLOCK,
  id: 'fb1',
  status: 'FINALIZED',
  finalized_at: '2026-04-29T00:00:00Z',
  buckets: [
    { id: 'NEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 75 },
  ],
};

const TGT_BLOCK = {
  ...IN_PROGRESS_BLOCK,
  id: 'tgt1',
  name: 'Target Block',
  buckets: [
    { id: 'tgtNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
  ],
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function mountTriageDetail() {
  tokenStore.set?.({ accessToken: 'test', expiresAt: Date.now() + 1e7 } as never);
  return render(
    <QueryClientProvider client={makeClient()}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={['/triage/s1/b1']}>
            <Routes>
              <Route path="/triage/:styleId/:id" element={<TriageDetailPage />} />
            </Routes>
          </MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

function mountBucketDetail(blockId: string, bucketId: string) {
  tokenStore.set?.({ accessToken: 'test', expiresAt: Date.now() + 1e7 } as never);
  return render(
    <QueryClientProvider client={makeClient()}>
      <MantineProvider theme={testTheme}>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={[`/triage/s1/${blockId}/buckets/${bucketId}`]}>
            <Routes>
              <Route
                path="/triage/:styleId/:id/buckets/:bucketId"
                element={<BucketDetailPage />}
              />
            </Routes>
          </MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => server.resetHandlers());
afterEach(() => { notifications.clean(); server.resetHandlers(); });

describe('FinalizeFlow — happy path with STAGING', () => {
  it('finalizes a block with 2 STAGING buckets and shows aggregate toast', async () => {
    server.use(
      http.get('https://api.test/triage/blocks/b1', () =>
        HttpResponse.json(IN_PROGRESS_BLOCK),
      ),
      http.post('https://api.test/triage/blocks/b1/finalize', () =>
        HttpResponse.json(
          {
            block: { ...IN_PROGRESS_BLOCK, status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' },
            promoted: { cA: 3, cB: 5 },
          },
          { status: 200 },
        ),
      ),
    );
    const user = userEvent.setup();
    mountTriageDetail();
    await user.click(await screen.findByRole('button', { name: 'Finalize' }));
    expect(await screen.findByText(/Finalize Block 1\?/i)).toBeInTheDocument();
    await user.click(screen.getAllByRole('button', { name: 'Finalize' })[1]);
    await waitFor(() =>
      expect(
        screen.getByText(/Finalized Block 1.*promoted 8 tracks across 2 categories/i),
      ).toBeInTheDocument(),
    );
  });
});

describe('FinalizeFlow — blocker preempt', () => {
  it('renders blocker variant when block has inactive STAGING with tracks', async () => {
    const blocked = {
      ...IN_PROGRESS_BLOCK,
      buckets: [
        { id: 'sa', bucket_type: 'STAGING', category_id: 'cA', category_name: 'Deleted Cat', inactive: true, track_count: 4 },
      ],
    };
    server.use(http.get('https://api.test/triage/blocks/b1', () => HttpResponse.json(blocked)));
    const user = userEvent.setup();
    mountTriageDetail();
    await user.click(await screen.findByRole('button', { name: 'Finalize' }));
    expect(await screen.findByText('Cannot finalize yet')).toBeInTheDocument();
    expect(screen.getByText('Deleted Cat')).toBeInTheDocument();
    expect(screen.getByText('4 tracks')).toBeInTheDocument();
  });
});

describe('FinalizeFlow — bulk transfer from FINALIZED tech bucket', () => {
  it('drains 2 pages, then bulk-transfers 75 tracks across 1 chunk', async () => {
    const allTracks = Array.from({ length: 75 }, (_, i) => ({
      track_id: `t${i + 1}`,
      title: `Track ${i + 1}`,
      mix_name: null, isrc: null, bpm: 128, length_ms: 240000,
      publish_date: null, spotify_release_date: null, spotify_id: null,
      release_type: null, is_ai_suspected: false, artists: ['Artist'],
      label_name: null, added_at: '2026-04-21T00:00:00Z',
    }));
    server.use(
      http.get('https://api.test/triage/blocks/fb1', () => HttpResponse.json(FINALIZED_BLOCK)),
      http.get('https://api.test/triage/blocks/fb1/buckets/NEW/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        const limit = Number(url.searchParams.get('limit') ?? '50');
        const items = allTracks.slice(offset, offset + limit);
        return HttpResponse.json({ items, total: 75, limit, offset });
      }),
      http.get('https://api.test/styles/s1/triage/blocks', () =>
        HttpResponse.json({ items: [TGT_BLOCK, FINALIZED_BLOCK], total: 2, limit: 50, offset: 0 }),
      ),
      http.get('https://api.test/triage/blocks/tgt1', () => HttpResponse.json(TGT_BLOCK)),
      http.post('https://api.test/triage/blocks/fb1/transfer', async ({ request }) => {
        const body = (await request.json()) as { track_ids: string[] };
        return HttpResponse.json({ transferred: body.track_ids.length }, { status: 200 });
      }),
    );
    const user = userEvent.setup();
    mountBucketDetail('fb1', 'NEW');
    const button = await screen.findByRole('button', { name: /Transfer all to another block/i });
    await user.click(button);
    // Modal opens at step 1
    expect(await screen.findByText('Transfer to which block?')).toBeInTheDocument();
    await user.click(screen.getByText('Target Block'));
    // Step 2: pick NEW bucket
    await user.click(await screen.findByLabelText(/move to.*NEW/i));
    await waitFor(() =>
      expect(screen.getByText(/Transferred 75 tracks to Target Block/i)).toBeInTheDocument(),
    );
  });
});

describe('FinalizeFlow — gating', () => {
  it('Finalize button absent on FINALIZED block', async () => {
    server.use(http.get('https://api.test/triage/blocks/fb1', () => HttpResponse.json(FINALIZED_BLOCK)));
    mountTriageDetail = () => /* swap path */ render(/* path /triage/s1/fb1 */ /* ... */);
    // assert no 'Finalize' button rendered
  });

  it('Bulk Transfer button absent on STAGING bucket of FINALIZED block', async () => {
    const stagingBucket = {
      ...FINALIZED_BLOCK,
      buckets: [{ id: 'st1', bucket_type: 'STAGING', category_id: 'c1', category_name: 'X', inactive: false, track_count: 4 }],
    };
    server.use(http.get('https://api.test/triage/blocks/fb1', () => HttpResponse.json(stagingBucket)));
    mountBucketDetail('fb1', 'st1');
    await screen.findByText('X (staging)');
    expect(screen.queryByRole('button', { name: /Transfer all to another block/i })).not.toBeInTheDocument();
  });
});
```

Some test bodies above are sketches. Fill them in by following the helpers used in `TransferFlow.integration.test.tsx` (especially the mount tree at lines 71-90) — copy that shape.

If `tokenStore.set?.()` differs from the existing test API, mirror what `TransferFlow.integration.test.tsx` does.

- [ ] **Step 2: Run tests to verify they fail (where new) and pass (where existing modules already work)**

```bash
pnpm test src/features/triage/__tests__/FinalizeFlow.integration.test.tsx
```

Iterate on test details until all pass. Each "describe" block tests one slice of the spec's §11.2 scenarios.

- [ ] **Step 3: Run the full suite**

```bash
pnpm test
```

Expected: every prior test green, plus new integration tests.

- [ ] **Step 4: Typecheck + commit**

```bash
pnpm typecheck
```

Sample subject: `test(triage): integration tests for finalize + bulk transfer`.

---

## Task 13: Bundle + smoke + roadmap update

**Files:**
- Modify: `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`

- [ ] **Step 1: Confirm full test suite green**

```bash
cd frontend && pnpm test && pnpm typecheck && pnpm build
```

Expected:
- `pnpm test`: green, ~274 tests (244 baseline + ~30 new).
- `pnpm typecheck`: clean.
- `pnpm build`: ≤ 920 KB minified.

If bundle exceeds the cap, look for unintentional duplicate imports first; bumping the cap requires user sign-off.

- [ ] **Step 2: Manual smoke against deployed prod API**

Follow §11.4 of the spec:

```bash
cd frontend && pnpm dev
```

In the browser at `http://127.0.0.1:5173`:
1. Sign in → triage → open an IN_PROGRESS block.
2. Click `Finalize` → confirm modal lists STAGING buckets + counts. Cancel → close.
3. Click `Finalize` → submit → green toast → page re-renders FINALIZED.
4. Open a finalized block's NEW bucket → click `Transfer all to another block…` → pick another IN_PROGRESS block → pick its NEW bucket → green toast.
5. Re-open the source FINALIZED block's NEW bucket → confirm tracks STILL there.
6. Open the target IN_PROGRESS block's NEW bucket → confirm tracks present.
7. Trigger blocker: in an IN_PROGRESS block with ≥1 STAGING, soft-delete the linked category via F1. Re-open Finalize → blocker variant lists the bucket. Open link → BucketDetailPage. Move tracks elsewhere → return → Finalize succeeds.
8. Edge: FINALIZED block STAGING bucket detail → confirm `Transfer all` button is absent.

Document any anomaly. If a regression appears, halt and address before merge.

- [ ] **Step 3: Update the roadmap**

Edit `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`:

- In the ticket queue table, change the `**F4**` row's status to `~~**F4**~~ ✅ **Shipped 2026-05-03**` (use the actual ship date).
- In the Tech debt table, append `TD-12` row:
  ```
  | TD-12 | Spec-D narrative drift on finalize error code. Spec-D §5.9 says `block_not_editable`; backend emits `invalid_state` (`triage_repository.py:529` + `curation/__init__.py:67`). F4 codes against actual contract. Same drift class as TD-9 / TD-10. | Future contributors reading spec-D may write the wrong frontend mapping. | Update spec-D §5.9 narrative or rename `InvalidStateError.error_code` for the finalize path. Doc-only or 1-line code change. |
  ```
- Add a `## Lessons learned (post-F4, 2026-05-03)` section at the end with notes captured during the cycle (cold-start scheduler reuse pattern, bulk-from-FINALIZED snapshot semantics insight, paginated track-id drain, `ApiError.raw` body access).

- [ ] **Step 4: Commit roadmap update separately**

Sample subject: `docs(roadmap): mark F4 shipped, add TD-12 and lessons`.

- [ ] **Step 5: Merge to `main`**

From the worktree:

```bash
git log --oneline main..HEAD     # review the F4 commits
cd /Users/roman/Projects/clouder-projects/clouder-core
git checkout main
git pull origin main
git merge --no-ff <worktree-branch-name>     # produces a merge commit
```

CI runs on push.

```bash
git push origin main
```

Verify the deploy workflow on GitHub Actions before closing the ticket.

---

## Self-Review Findings

Cross-check against spec sections:

- §2 In scope items ↔ Tasks: scheduler (T1), hook (T2), modal + leaf rows (T4-T6), header CTA (T7), modal mount (T8), TransferModal extension (T9), bucket-page CTA (T10), i18n (T3), tests (T1-T6 unit + T12 integration), roadmap (T13). All items mapped.
- §2 Out-of-scope items: not implemented anywhere; no orphan code.
- §3 Architectural decisions D1-D20: each ties to at least one task. D2 (bulk only on tech) → T10 gating. D5 (recovery scheduler) → T1+T6. D8 (cache sweep keys) → T2. D9 (snapshot semantics) → T9 bulk loop. D11 (error mapping) → T6 + T9. D13 (prop refactor) → T9 Pass A. D16 (empty staging) → T6 ConfirmVariant + T6 test.
- §4.x UI surface: every code block in the spec has a corresponding implementation step.
- §6.x data flow: hook + scheduler + chunk loop are all implemented as written.
- §10 i18n keys: T3 adds the full set.
- §11 testing: §11.1 unit covered by T1, T2, T4, T5, T6, T9. §11.2 integration covered by T8 + T12.

Type / signature consistency:
- `FinalizeResponse`, `InactiveBucketRow`, `FinalizeErrorBody` defined in T2's hook file and re-imported by T6's modal. Matched.
- `schedulePendingFinalizeRecovery` signature stable across T1 and T6.
- `TransferModalProps.trackIds: string[]` consistent in T9 Pass A and T9 Pass B.
- `BULK_CHUNK_SIZE = 1000` referenced consistently.
- `STATUSES` array defined identically in T2, T6 (both files declare the constant locally to avoid cross-feature import; OK by spec).

No placeholders / TBDs in code blocks; integration test bodies in T12 contain narrative sketches that the implementer fills in by following `TransferFlow.integration.test.tsx` patterns explicitly cited (file + line numbers).

No dead references: every type, function, and i18n key used in a later task is defined in an earlier task.

---

## Plan Complete

Plan saved to `docs/superpowers/plans/2026-05-03-F4-triage-finalize-frontend.md`.

Two execution options:

1. **Subagent-Driven (recommended)** — controller dispatches a fresh subagent per task, reviews between tasks. Each subagent has full context for one task only; the controller stitches the work together.
2. **Inline Execution** — execute tasks in this session via `superpowers:executing-plans` with checkpoints for review.

Which approach?

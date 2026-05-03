# F3a Triage Detail + Bucket Browse + Move Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the F2 `TriageDetailStub` with a real `TriageDetailPage` (block summary + bucket grid) and a nested `BucketDetailPage` (paginated track list with search + per-row optimistic Move with Undo). Soft-delete the block from header kebab. F3a covers the in-block reclassification flow only — cross-block transfer is F3b, finalize is F4.

**Architecture:** Two-route master/detail under `/triage/:styleId/:id` and `/triage/:styleId/:id/buckets/:bucketId`. New components live under `frontend/src/features/triage/{routes,components,hooks,lib}/`. React-query 5: `useQuery` for block detail, `useInfiniteQuery` for bucket tracks (limit=50, load-more), `useMutation` for `move` with `onMutate` snapshot + optimistic cache writes + rollback in `onError`. Undo button on the success notification calls `apiClient.post` directly (bypasses the hook to avoid a second `onMutate` cycle and refetch flicker), restoring the original snapshot synchronously. Shared formatters (`formatLength`, `formatAdded`) extracted from F1's `TrackRow.tsx` into `frontend/src/lib/formatters.ts` and a new `formatReleaseDate` added.

**Tech Stack:** React 19, TypeScript, Mantine 9 (`core` + `notifications` + `modals` + `hooks`), `@tanstack/react-query` 5, `react-router` 7, Vitest + Testing Library + MSW. Zero new npm dependencies.

**Spec:** [`../specs/2026-05-03-F3a-triage-detail-frontend-design.md`](../specs/2026-05-03-F3a-triage-detail-frontend-design.md). Read it before starting — every UX decision is referenced from there.

**Delivery model:** Direct merge to `main` from `feat/triage-detail-move` branch (no PR review). Commit messages via `caveman:caveman-commit` skill (CLAUDE.md mandate).

**Working directory:** `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3_task`. All commands run from there unless explicitly cd'd into `frontend/`.

---

## Task 0: Prep — branch rename + dep verification + baseline tests green

**Files:** none modified; verification only.

- [ ] **Step 1: Rename current worktree branch to the policy-compliant name**

The worktree was created on branch `worktree-f3_task` which violates the CLAUDE.md "no agent/user prefixes" rule. Rename to `feat/triage-detail-move`:

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3_task
git branch -m feat/triage-detail-move
git status
```

Expected: `On branch feat/triage-detail-move`.

- [ ] **Step 2: Verify required deps already in `frontend/package.json`**

```bash
grep -E "(@mantine/core|@mantine/hooks|@mantine/modals|@mantine/notifications|@tabler/icons-react|@tanstack/react-query|react-router)" frontend/package.json
```

Expected output includes all 7 lines. F3a should add **zero** new deps.

- [ ] **Step 3: Run baseline tests**

```bash
cd frontend
pnpm test
```

Expected: ~130 tests passing (F1 + F2 baseline).

- [ ] **Step 4: Run typecheck + build**

```bash
cd frontend
pnpm typecheck
pnpm build
```

Expected: typecheck clean; build emits under 700 KB minified bundle.

- [ ] **Step 5: No commit** — Task 0 has no file changes.

---

## Task 1: Extract shared `formatters.ts`; rewire F1's `TrackRow`

**Files:**

- Create: `frontend/src/lib/formatters.ts`
- Create: `frontend/src/lib/__tests__/formatters.test.ts`
- Modify: `frontend/src/features/categories/components/TrackRow.tsx` — replace inline `formatLength`/`formatAdded` declarations with imports from `@/lib/formatters`.

- [ ] **Step 1: Locate every existing in-line declaration that we're consolidating**

```bash
grep -rn "function formatLength\|function formatAdded" frontend/src
```

Expected: matches in `frontend/src/features/categories/components/TrackRow.tsx`. No other call sites today.

- [ ] **Step 2: Create the shared lib directory + formatters file**

```bash
mkdir -p frontend/src/lib/__tests__
```

Create `frontend/src/lib/formatters.ts`:

```ts
export function formatLength(ms: number | null): string {
  if (ms === null || ms === undefined) return '—';
  const total = Math.round(ms / 1000);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function formatAdded(iso: string): string {
  const date = new Date(iso);
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
  }).format(date);
}

export function formatReleaseDate(iso: string | null): string {
  if (!iso) return '—';
  return iso;
}
```

- [ ] **Step 3: Write the failing tests**

Create `frontend/src/lib/__tests__/formatters.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { formatLength, formatAdded, formatReleaseDate } from '../formatters';

describe('formatLength', () => {
  it('returns m:ss for whole seconds', () => {
    expect(formatLength(135_000)).toBe('2:15');
  });
  it('rounds the seconds half-up', () => {
    expect(formatLength(59_999)).toBe('1:00');
  });
  it('returns 0:00 for zero', () => {
    expect(formatLength(0)).toBe('—');
  });
  it('returns em-dash for null', () => {
    expect(formatLength(null)).toBe('—');
  });
  it('zero ms strictly == 0 still prints em-dash (legacy F1 behavior)', () => {
    expect(formatLength(0)).toBe('—');
  });
});

describe('formatAdded', () => {
  it('returns a formatted date string', () => {
    const out = formatAdded('2026-04-15T12:00:00Z');
    expect(out).toMatch(/2026/);
    expect(out).toMatch(/Apr/i);
  });
});

describe('formatReleaseDate', () => {
  it('returns the iso string verbatim', () => {
    expect(formatReleaseDate('2026-04-15')).toBe('2026-04-15');
  });
  it('returns em-dash for null', () => {
    expect(formatReleaseDate(null)).toBe('—');
  });
});
```

- [ ] **Step 4: Run the new tests — they should pass**

```bash
cd frontend
pnpm test src/lib/__tests__/formatters.test.ts
```

Expected: 7 tests pass.

- [ ] **Step 5: Update F1's `TrackRow.tsx` to import from shared**

Open `frontend/src/features/categories/components/TrackRow.tsx`. Replace the top of the file:

```ts
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '@tabler/icons-react';
import { useTranslation } from 'react-i18next';
import { formatAdded, formatLength } from '../../../lib/formatters';
import type { CategoryTrack } from '../hooks/useCategoryTracks';

function joinArtists(artists: CategoryTrack['artists']): string {
  return artists.map((a) => a.name).join(', ');
}
```

(Delete the inline `function formatLength` and `function formatAdded` declarations.)

- [ ] **Step 6: Run F1 tests to verify nothing broke**

```bash
cd frontend
pnpm test src/features/categories
```

Expected: all F1 tests pass (no behavioural change).

- [ ] **Step 7: Commit**

Stage:

```bash
git add frontend/src/lib/formatters.ts \
        frontend/src/lib/__tests__/formatters.test.ts \
        frontend/src/features/categories/components/TrackRow.tsx
```

Generate message via the `caveman:caveman-commit` skill, then:

```bash
git commit -m "<skill output>"
```

Suggested subject: `refactor(frontend): extract track formatters to shared lib`.

---

## Task 2: Add `IconSearch` to icons re-export

**Files:**

- Modify: `frontend/src/components/icons.ts`

- [ ] **Step 1: Verify `IconSearch` is not already re-exported**

```bash
grep "IconSearch" frontend/src/components/icons.ts
```

Expected: no output.

- [ ] **Step 2: Add the icon to the re-export block**

Open `frontend/src/components/icons.ts`. The export block currently ends with `IconPlus,`. Add `IconSearch,` and `IconX,` (the search input also needs a clear-X icon):

```ts
export {
  IconHome,
  IconCategory,
  IconLayoutColumns,
  IconAdjustments,
  IconUser,
  IconPlayerPlay,
  IconPlayerPause,
  IconPlayerSkipForward,
  IconPlayerSkipBack,
  IconChevronUp,
  IconChevronDown,
  IconDots,
  IconCopy,
  IconLogout,
  IconLoader,
  IconAlertTriangle,
  IconArrowLeft,
  IconDotsVertical,
  IconTrash,
  IconPlus,
  IconSearch,
  IconX,
} from '@tabler/icons-react';
```

- [ ] **Step 3: Verify typecheck + tests**

```bash
cd frontend
pnpm typecheck
pnpm test src/components
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/icons.ts
```

Suggested subject: `chore(frontend): add IconSearch and IconX re-exports`.

---

## Task 3: `bucketLabels.ts` helpers

**Files:**

- Create: `frontend/src/features/triage/lib/bucketLabels.ts`
- Create: `frontend/src/features/triage/lib/__tests__/bucketLabels.test.ts`

- [ ] **Step 1: Define the bucket type contract used everywhere**

Create `frontend/src/features/triage/lib/bucketLabels.ts`:

```ts
import type { TFunction } from 'i18next';

export type TechnicalBucketType = 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED';
export type BucketType = TechnicalBucketType | 'STAGING';

export interface TriageBucket {
  id: string;
  bucket_type: BucketType;
  category_id: string | null;
  category_name: string | null;
  inactive: boolean;
  track_count: number;
}

const TECHNICAL_TYPES: ReadonlySet<BucketType> = new Set([
  'NEW',
  'OLD',
  'NOT',
  'DISCARD',
  'UNCLASSIFIED',
]);

export function isTechnical(bucket: Pick<TriageBucket, 'bucket_type'>): boolean {
  return TECHNICAL_TYPES.has(bucket.bucket_type);
}

export function bucketLabel(bucket: TriageBucket, t: TFunction): string {
  if (bucket.bucket_type !== 'STAGING') return bucket.bucket_type;
  const name = bucket.category_name ?? '';
  return bucket.inactive
    ? t('triage.bucket_type.STAGING_inactive_label', { name })
    : t('triage.bucket_type.STAGING_label', { name });
}

export function moveDestinationsFor(
  buckets: TriageBucket[],
  currentBucketId: string,
): TriageBucket[] {
  return buckets.filter((b) => {
    if (b.id === currentBucketId) return false;
    if (b.bucket_type === 'STAGING' && b.inactive) return false;
    return true;
  });
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/lib/__tests__/bucketLabels.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import {
  bucketLabel,
  isTechnical,
  moveDestinationsFor,
  type TriageBucket,
} from '../bucketLabels';

const t = ((key: string, vars?: Record<string, string>) => {
  if (key === 'triage.bucket_type.STAGING_label') return `${vars?.name} (staging)`;
  if (key === 'triage.bucket_type.STAGING_inactive_label')
    return `${vars?.name} (staging, inactive)`;
  return key;
}) as Parameters<typeof bucketLabel>[1];

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 5,
};

const staging: TriageBucket = {
  id: 'b2',
  bucket_type: 'STAGING',
  category_id: 'c1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 3,
};

const stagingInactive: TriageBucket = {
  ...staging,
  id: 'b3',
  category_name: 'Old Genre',
  inactive: true,
};

describe('bucketLabel', () => {
  it('returns the bucket_type literal for technical buckets', () => {
    expect(bucketLabel(tech, t)).toBe('NEW');
  });
  it('returns "<name> (staging)" for active STAGING', () => {
    expect(bucketLabel(staging, t)).toBe('Tech House (staging)');
  });
  it('returns "<name> (staging, inactive)" for inactive STAGING', () => {
    expect(bucketLabel(stagingInactive, t)).toBe('Old Genre (staging, inactive)');
  });
});

describe('isTechnical', () => {
  it('true for NEW/OLD/NOT/DISCARD/UNCLASSIFIED', () => {
    for (const t of ['NEW', 'OLD', 'NOT', 'DISCARD', 'UNCLASSIFIED'] as const) {
      expect(isTechnical({ bucket_type: t })).toBe(true);
    }
  });
  it('false for STAGING', () => {
    expect(isTechnical({ bucket_type: 'STAGING' })).toBe(false);
  });
});

describe('moveDestinationsFor', () => {
  it('excludes the current bucket', () => {
    const result = moveDestinationsFor([tech, staging, stagingInactive], 'b1');
    expect(result.map((b) => b.id)).toEqual(['b2']);
  });
  it('excludes inactive STAGING', () => {
    const result = moveDestinationsFor([tech, staging, stagingInactive], 'b2');
    expect(result.map((b) => b.id)).toEqual(['b1']);
  });
  it('preserves API order', () => {
    const result = moveDestinationsFor([staging, tech, stagingInactive], 'b3');
    expect(result.map((b) => b.id)).toEqual(['b2', 'b1']);
  });
});
```

- [ ] **Step 3: Run tests**

```bash
cd frontend
pnpm test src/features/triage/lib/__tests__/bucketLabels.test.ts
```

Expected: 9 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/lib/bucketLabels.ts \
        frontend/src/features/triage/lib/__tests__/bucketLabels.test.ts
```

Suggested subject: `feat(frontend): add triage bucketLabels helpers`.

---

## Task 4: i18n keys

**Files:**

- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1: Locate the existing `triage` namespace**

```bash
grep -n '"triage":' frontend/src/i18n/en.json
```

Note the line number. The F2 spec already nested several keys under `triage` (page_title, create_cta, tabs, etc.).

- [ ] **Step 2: Add F3a keys inside the existing `triage` object**

Open `frontend/src/i18n/en.json`. Inside the existing `"triage": { ... }` block (after the existing `delete_modal` / `toast` / `errors` / `empty_state` siblings), add the following four new keys at the end of the `triage` object (before its closing `}`):

```json
"detail": {
  "back_to_list": "← Back to triage",
  "finalize_cta": "Finalize",
  "finalize_coming_soon": "Coming in F4",
  "kebab": {
    "delete": "Delete block"
  },
  "header": {
    "date_range": "{{from}} → {{to}}",
    "created": "created {{relative}}",
    "finalized": "finalized {{relative}}"
  },
  "bucket_count_one": "{{count}} bucket",
  "bucket_count_other": "{{count}} buckets"
},
"bucket": {
  "back_to_block": "← Back to {{name}}",
  "header": {
    "subtitle": "{{count}} tracks · {{block_name}} · {{from}} → {{to}}"
  },
  "search_placeholder": "Search tracks…",
  "load_more": "Load more",
  "loading": "Loading tracks…",
  "track_count_one": "{{count}} track",
  "track_count_other": "{{count}} tracks",
  "empty": {
    "no_tracks_title": "No tracks in this bucket",
    "no_tracks_body_default": "Move tracks here from another bucket.",
    "no_tracks_body_unclassified": "Tracks land here when their Spotify release date is missing. Re-run enrichment or move manually.",
    "search_miss_title": "Nothing matches your search",
    "search_miss_body": "Try a different term.",
    "search_miss_clear": "Clear search"
  }
},
"bucket_type": {
  "STAGING_label": "{{name}} (staging)",
  "STAGING_inactive_label": "{{name}} (staging, inactive)",
  "inactive_suffix": "(inactive)"
},
"move": {
  "menu": {
    "trigger_aria": "Move track",
    "label": "Move to",
    "destination_aria": "Move to {{label}}"
  },
  "toast": {
    "moved_one": "Moved 1 track to {{to}}.",
    "moved_other": "Moved {{count}} tracks to {{to}}.",
    "undo_action": "Undo",
    "undone": "Undone.",
    "undo_failed": "Undo failed.",
    "error": "Move failed.",
    "stale_state": "This bucket has changed. Refreshing.",
    "invalid_target": "That destination is no longer valid."
  }
},
"tracks_table": {
  "title_header": "Title",
  "artists_header": "Artists",
  "bpm_header": "BPM",
  "length_header": "Length",
  "released_header": "Released",
  "ai_suspected_aria": "AI-suspected track",
  "actions_header": "Actions"
},
"errors": {
  "block_not_found_title": "Block not found",
  "block_not_found_body": "It may have been deleted.",
  "bucket_not_found_title": "Bucket not found",
  "service_unavailable": "Service unavailable. Please retry."
}
```

If `triage.errors` already exists from F2, MERGE the new keys into the existing object instead of duplicating the parent. Same for any other collision — check before adding.

- [ ] **Step 3: Validate JSON**

```bash
cd frontend
node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8')); console.log('valid')"
```

Expected: `valid`.

- [ ] **Step 4: Run i18n + existing tests to ensure nothing broke**

```bash
cd frontend
pnpm typecheck
pnpm test src/features/triage
```

Expected: passing.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/en.json
```

Suggested subject: `feat(frontend): add F3a i18n keys for triage detail`.

---

## Task 5: `useTriageBlock` hook

**Files:**

- Create: `frontend/src/features/triage/hooks/useTriageBlock.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useTriageBlock.test.tsx`

- [ ] **Step 1: Write the hook**

Create `frontend/src/features/triage/hooks/useTriageBlock.ts`:

```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { TriageBucket } from '../lib/bucketLabels';
import type { TriageStatus } from './useTriageBlocksByStyle';

export interface TriageBlock {
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
  buckets: TriageBucket[];
  correlation_id?: string;
}

export const triageBlockKey = (id: string) => ['triage', 'blockDetail', id] as const;

export function useTriageBlock(id: string): UseQueryResult<TriageBlock> {
  return useQuery({
    queryKey: triageBlockKey(id),
    queryFn: () => api<TriageBlock>(`/triage/blocks/${id}`),
    enabled: !!id,
    staleTime: 30_000,
  });
}
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/features/triage/hooks/__tests__/useTriageBlock.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTriageBlock } from '../useTriageBlock';

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const blockFixture = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'House — week 17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
    { id: 'bk2', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 2 },
  ],
};

describe('useTriageBlock', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches a block by id', async () => {
    server.use(http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(blockFixture)));
    const { result } = renderHook(() => useTriageBlock('b1'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.name).toBe('House — week 17');
    expect(result.current.data?.buckets).toHaveLength(2);
  });

  it('throws on 404', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/missing', () =>
        HttpResponse.json({ error_code: 'triage_block_not_found', message: 'no' }, { status: 404 }),
      ),
    );
    const { result } = renderHook(() => useTriageBlock('missing'), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useTriageBlock.test.tsx
```

Expected: 2 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/hooks/useTriageBlock.ts \
        frontend/src/features/triage/hooks/__tests__/useTriageBlock.test.tsx
```

Suggested subject: `feat(frontend): add useTriageBlock hook`.

---

## Task 6: `useBucketTracks` hook (infinite query + search)

**Files:**

- Create: `frontend/src/features/triage/hooks/useBucketTracks.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useBucketTracks.test.tsx`

- [ ] **Step 1: Write the hook**

Create `frontend/src/features/triage/hooks/useBucketTracks.ts`:

```ts
import {
  useInfiniteQuery,
  type InfiniteData,
  type UseInfiniteQueryResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface BucketTrack {
  track_id: string;
  title: string;
  mix_name: string | null;
  isrc: string | null;
  bpm: number | null;
  length_ms: number | null;
  publish_date: string | null;
  spotify_release_date: string | null;
  spotify_id: string | null;
  release_type: string | null;
  is_ai_suspected: boolean;
  artists: string[];
  added_at: string;
}

export interface PaginatedBucketTracks {
  items: BucketTrack[];
  total: number;
  limit: number;
  offset: number;
  correlation_id?: string;
}

const PAGE_SIZE = 50;

export const bucketTracksKey = (
  blockId: string,
  bucketId: string,
  search: string,
) => ['triage', 'bucketTracks', blockId, bucketId, search] as const;

export function useBucketTracks(
  blockId: string,
  bucketId: string,
  search: string,
): UseInfiniteQueryResult<InfiniteData<PaginatedBucketTracks>> {
  return useInfiniteQuery({
    queryKey: bucketTracksKey(blockId, bucketId, search),
    queryFn: ({ pageParam = 0 }) => {
      const params = new URLSearchParams({
        limit: String(PAGE_SIZE),
        offset: String(pageParam),
      });
      if (search) params.set('search', search);
      return api<PaginatedBucketTracks>(
        `/triage/blocks/${blockId}/buckets/${bucketId}/tracks?${params.toString()}`,
      );
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const fetched = pages.reduce((sum, p) => sum + p.items.length, 0);
      return fetched < lastPage.total ? fetched : undefined;
    },
    enabled: !!blockId && !!bucketId,
    gcTime: 5 * 60_000,
  });
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/hooks/__tests__/useBucketTracks.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useBucketTracks, bucketTracksKey } from '../useBucketTracks';

function wrap() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function trackFixture(id: string) {
  return {
    track_id: id,
    title: `Track ${id}`,
    mix_name: null,
    isrc: null,
    bpm: 124,
    length_ms: 360_000,
    publish_date: '2026-04-21',
    spotify_release_date: '2026-04-15',
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    artists: ['Artist'],
    added_at: '2026-04-21T08:00:00Z',
  };
}

describe('useBucketTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('fetches the first page', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [trackFixture('t1')], total: 1, limit: 50, offset: 0 }),
      ),
    );
    const { result } = renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.pages[0].items[0].title).toBe('Track t1');
  });

  it('omits the search param when search is empty', async () => {
    let receivedUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        receivedUrl = request.url;
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(receivedUrl).toContain('limit=50'));
    expect(receivedUrl).not.toContain('search=');
  });

  it('includes the search param when search is non-empty', async () => {
    let receivedUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        receivedUrl = request.url;
        return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
      }),
    );
    renderHook(() => useBucketTracks('b1', 'bk1', 'foo'), { wrapper: wrap() });
    await waitFor(() => expect(receivedUrl).toContain('search=foo'));
  });

  it('paginates via getNextPageParam', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) {
          return HttpResponse.json({ items: [trackFixture('t1')], total: 2, limit: 1, offset: 0 });
        }
        return HttpResponse.json({ items: [trackFixture('t2')], total: 2, limit: 1, offset: 1 });
      }),
    );
    const { result } = renderHook(() => useBucketTracks('b1', 'bk1', ''), { wrapper: wrap() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);
    await act(async () => {
      await result.current.fetchNextPage();
    });
    expect(result.current.data?.pages.flatMap((p) => p.items)).toHaveLength(2);
  });

  it('produces a stable cache key per search term', () => {
    expect(bucketTracksKey('b1', 'bk1', '')).toEqual(['triage', 'bucketTracks', 'b1', 'bk1', '']);
    expect(bucketTracksKey('b1', 'bk1', 'foo')).toEqual([
      'triage',
      'bucketTracks',
      'b1',
      'bk1',
      'foo',
    ]);
  });
});
```

- [ ] **Step 3: Run the tests**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useBucketTracks.test.tsx
```

Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/hooks/useBucketTracks.ts \
        frontend/src/features/triage/hooks/__tests__/useBucketTracks.test.tsx
```

Suggested subject: `feat(frontend): add useBucketTracks infinite query`.

---

## Task 7: `useMoveTracks` hook (optimistic + rollback + Undo)

**Files:**

- Create: `frontend/src/features/triage/hooks/useMoveTracks.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useMoveTracks.test.tsx`

- [ ] **Step 1: Write the hook with snapshot, optimistic write, rollback, and an exported `undoMoveDirect` helper**

Create `frontend/src/features/triage/hooks/useMoveTracks.ts`:

```ts
import {
  useMutation,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import {
  bucketTracksKey,
  type PaginatedBucketTracks,
} from './useBucketTracks';
import { triageBlockKey, type TriageBlock } from './useTriageBlock';
import { triageBlocksByStyleKey, type TriageStatus } from './useTriageBlocksByStyle';

export interface MoveInput {
  fromBucketId: string;
  toBucketId: string;
  trackIds: string[];
}

export interface MoveResponse {
  moved: number;
  correlation_id?: string;
}

export interface MoveSnapshot {
  source: [readonly unknown[], unknown][];
  block: TriageBlock | undefined;
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function takeSnapshot(
  qc: QueryClient,
  blockId: string,
  fromBucketId: string,
): MoveSnapshot {
  const source = qc.getQueriesData({
    queryKey: ['triage', 'bucketTracks', blockId, fromBucketId],
  }) as [readonly unknown[], unknown][];
  const block = qc.getQueryData<TriageBlock>(triageBlockKey(blockId));
  return { source, block };
}

export function applyOptimisticMove(
  qc: QueryClient,
  blockId: string,
  input: MoveInput,
): void {
  qc.setQueriesData(
    { queryKey: ['triage', 'bucketTracks', blockId, input.fromBucketId] },
    (old: { pages: PaginatedBucketTracks[]; pageParams: unknown[] } | undefined) => {
      if (!old) return old;
      return {
        ...old,
        pages: old.pages.map((p) => ({
          ...p,
          items: p.items.filter((t) => !input.trackIds.includes(t.track_id)),
          total: Math.max(0, p.total - input.trackIds.length),
        })),
      };
    },
  );
  qc.setQueryData<TriageBlock | undefined>(triageBlockKey(blockId), (old) => {
    if (!old) return old;
    return {
      ...old,
      buckets: old.buckets.map((b) => {
        if (b.id === input.fromBucketId) {
          return { ...b, track_count: Math.max(0, b.track_count - input.trackIds.length) };
        }
        if (b.id === input.toBucketId) {
          return { ...b, track_count: b.track_count + input.trackIds.length };
        }
        return b;
      }),
    };
  });
}

export function restoreSnapshot(
  qc: QueryClient,
  blockId: string,
  snap: MoveSnapshot,
): void {
  for (const [key, val] of snap.source) {
    qc.setQueryData(key, val);
  }
  if (snap.block !== undefined) {
    qc.setQueryData(triageBlockKey(blockId), snap.block);
  }
}

/**
 * Direct apiClient call for the Undo button.
 *
 * Why bypass `useMoveTracks.mutate`? Going through the hook would trigger a
 * second `onMutate` cycle (cancel queries, snapshot, optimistic write) and on
 * `onSuccess` invalidate the now-source bucket — causing a refetch flicker
 * during the brief window where the cache still reflects the post-move state
 * before the network round-trips. Restoring the original snapshot synchronously
 * before firing the inverse HTTP call avoids the flicker entirely.
 */
export async function undoMoveDirect(
  qc: QueryClient,
  blockId: string,
  styleId: string,
  originalInput: MoveInput,
  snapshot: MoveSnapshot,
): Promise<void> {
  // 1. Restore caches to pre-move state synchronously.
  restoreSnapshot(qc, blockId, snapshot);

  // 2. Fire inverse HTTP call.
  try {
    await api<MoveResponse>(`/triage/blocks/${blockId}/move`, {
      method: 'POST',
      body: JSON.stringify({
        from_bucket_id: originalInput.toBucketId,
        to_bucket_id: originalInput.fromBucketId,
        track_ids: originalInput.trackIds,
      }),
    });
  } catch (err) {
    // Inverse failed — re-apply the optimistic write so the UI matches reality.
    applyOptimisticMove(qc, blockId, originalInput);
    throw err;
  }

  // 3. Invalidate the byStyle list (counters on F2 list page).
  for (const s of STATUSES) {
    qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
  }
}

export function useMoveTracks(
  blockId: string,
  styleId: string,
): UseMutationResult<MoveResponse, ApiError, MoveInput, MoveSnapshot> {
  const qc = useQueryClient();
  return useMutation<MoveResponse, ApiError, MoveInput, MoveSnapshot>({
    mutationKey: ['triage', 'move', blockId],
    mutationFn: (input) =>
      api<MoveResponse>(`/triage/blocks/${blockId}/move`, {
        method: 'POST',
        body: JSON.stringify({
          from_bucket_id: input.fromBucketId,
          to_bucket_id: input.toBucketId,
          track_ids: input.trackIds,
        }),
      }),
    onMutate: async (input) => {
      await qc.cancelQueries({
        queryKey: ['triage', 'bucketTracks', blockId, input.fromBucketId],
      });
      await qc.cancelQueries({ queryKey: triageBlockKey(blockId) });
      const snap = takeSnapshot(qc, blockId, input.fromBucketId);
      applyOptimisticMove(qc, blockId, input);
      return snap;
    },
    onError: (_err, _input, context) => {
      if (context) restoreSnapshot(qc, blockId, context);
    },
    onSuccess: (_data, input) => {
      qc.invalidateQueries({
        queryKey: ['triage', 'bucketTracks', blockId, input.toBucketId],
      });
      qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
      }
    },
  });
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/hooks/__tests__/useMoveTracks.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useMoveTracks, undoMoveDirect, takeSnapshot } from '../useMoveTracks';
import { triageBlockKey } from '../useTriageBlock';
import { bucketTracksKey } from '../useBucketTracks';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

function block(buckets: { id: string; track_count: number }[]) {
  return {
    id: 'b1',
    style_id: 's1',
    style_name: 'House',
    name: 'W17',
    date_from: '2026-04-21',
    date_to: '2026-04-28',
    status: 'IN_PROGRESS' as const,
    created_at: '2026-04-21T00:00:00Z',
    updated_at: '2026-04-21T00:00:00Z',
    finalized_at: null,
    buckets: buckets.map((b) => ({
      id: b.id,
      bucket_type: 'NEW' as const,
      category_id: null,
      category_name: null,
      inactive: false,
      track_count: b.track_count,
    })),
  };
}

function tracksPage(ids: string[], total: number) {
  return {
    pageParams: [0],
    pages: [
      {
        items: ids.map((id) => ({
          track_id: id,
          title: `t${id}`,
          mix_name: null,
          isrc: null,
          bpm: null,
          length_ms: null,
          publish_date: null,
          spotify_release_date: null,
          spotify_id: null,
          release_type: null,
          is_ai_suspected: false,
          artists: [],
          added_at: '2026-04-21T00:00:00Z',
        })),
        total,
        limit: 50,
        offset: 0,
      },
    ],
  };
}

describe('useMoveTracks — optimistic write', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('removes the track from source list and adjusts counters on success', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ moved: 1 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        fromBucketId: 'src',
        toBucketId: 'dst',
        trackIds: ['t1'],
      });
    });

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0].items.map((t) => t.track_id)).toEqual(['t2']);
    expect(after?.pages[0].total).toBe(1);
  });

  it('rolls back on 409 inactive_bucket', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'inactive_bucket', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({ fromBucketId: 'src', toBucketId: 'dst', trackIds: ['t1'] })
        .catch(() => {});
    });

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0].items.map((t) => t.track_id)).toEqual(['t1', 't2']);
    expect(after?.pages[0].total).toBe(2);
  });

  it('rolls back on 404 stale-state', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'no' },
          { status: 404 },
        ),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const { result } = renderHook(() => useMoveTracks('b1', 's1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({ fromBucketId: 'src', toBucketId: 'dst', trackIds: ['t1'] })
        .catch(() => {});
    });

    const blockAfter = qc.getQueryData<ReturnType<typeof block>>(triageBlockKey('b1'));
    expect(blockAfter?.buckets.find((b) => b.id === 'src')?.track_count).toBe(2);
    expect(blockAfter?.buckets.find((b) => b.id === 'dst')?.track_count).toBe(0);
  });
});

describe('undoMoveDirect', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('restores snapshot and fires inverse call', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ moved: 1 });
      }),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const snap = takeSnapshot(qc, 'b1', 'src');
    // Simulate: optimistic move already applied
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t2'], 1));

    await undoMoveDirect(qc, 'b1', 's1', {
      fromBucketId: 'src',
      toBucketId: 'dst',
      trackIds: ['t1'],
    }, snap);

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0].items.map((t) => t.track_id)).toEqual(['t1', 't2']);
    expect(bodySeen).toMatchObject({
      from_bucket_id: 'dst',
      to_bucket_id: 'src',
      track_ids: ['t1'],
    });
  });

  it('re-applies optimistic write if inverse call fails', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ error_code: 'unknown', message: 'no' }, { status: 500 }),
      ),
    );
    const qc = makeClient();
    qc.setQueryData(triageBlockKey('b1'), block([
      { id: 'src', track_count: 2 },
      { id: 'dst', track_count: 0 },
    ]));
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t1', 't2'], 2));

    const snap = takeSnapshot(qc, 'b1', 'src');
    qc.setQueryData(bucketTracksKey('b1', 'src', ''), tracksPage(['t2'], 1));

    await expect(
      undoMoveDirect(qc, 'b1', 's1', {
        fromBucketId: 'src',
        toBucketId: 'dst',
        trackIds: ['t1'],
      }, snap),
    ).rejects.toBeTruthy();

    const after = qc.getQueryData<ReturnType<typeof tracksPage>>(bucketTracksKey('b1', 'src', ''));
    expect(after?.pages[0].items.map((t) => t.track_id)).toEqual(['t2']);
  });
});
```

- [ ] **Step 3: Run the tests**

```bash
cd frontend
pnpm test src/features/triage/hooks/__tests__/useMoveTracks.test.tsx
```

Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/hooks/useMoveTracks.ts \
        frontend/src/features/triage/hooks/__tests__/useMoveTracks.test.tsx
```

Suggested subject: `feat(frontend): add useMoveTracks with optimistic + undo`.

---

## Task 8: `BucketBadge` component

**Files:**

- Create: `frontend/src/features/triage/components/BucketBadge.tsx`
- Create: `frontend/src/features/triage/components/__tests__/BucketBadge.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/BucketBadge.tsx`:

```tsx
import { Badge } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketBadgeProps {
  bucket: TriageBucket;
  size?: 'xs' | 'sm' | 'md' | 'lg';
}

export function BucketBadge({ bucket, size = 'sm' }: BucketBadgeProps) {
  const { t } = useTranslation();
  const variant = bucket.bucket_type === 'STAGING' ? 'outline' : 'light';
  const color = bucket.inactive ? 'gray' : undefined;
  return (
    <Badge size={size} variant={variant} color={color}>
      {bucketLabel(bucket, t)}
    </Badge>
  );
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/BucketBadge.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { BucketBadge } from '../BucketBadge';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 5,
};

const staging: TriageBucket = {
  id: 'b2',
  bucket_type: 'STAGING',
  category_id: 'c1',
  category_name: 'Tech House',
  inactive: false,
  track_count: 3,
};

describe('BucketBadge', () => {
  it('renders technical bucket type literal', () => {
    r(<BucketBadge bucket={tech} />);
    expect(screen.getByText('NEW')).toBeInTheDocument();
  });
  it('renders STAGING with category name', () => {
    r(<BucketBadge bucket={staging} />);
    expect(screen.getByText(/Tech House.*staging/)).toBeInTheDocument();
  });
  it('renders inactive STAGING with inactive label', () => {
    r(<BucketBadge bucket={{ ...staging, inactive: true }} />);
    expect(screen.getByText(/Tech House.*staging.*inactive/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/BucketBadge.test.tsx
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/BucketBadge.tsx \
        frontend/src/features/triage/components/__tests__/BucketBadge.test.tsx
```

Suggested subject: `feat(frontend): add BucketBadge component`.

---

## Task 9: `BucketCard` component

**Files:**

- Create: `frontend/src/features/triage/components/BucketCard.tsx`
- Create: `frontend/src/features/triage/components/__tests__/BucketCard.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/BucketCard.tsx`:

```tsx
import { Card, Group, Stack, Text } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketBadge } from './BucketBadge';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export interface BucketCardProps {
  bucket: TriageBucket;
  styleId: string;
  blockId: string;
}

export function BucketCard({ bucket, styleId, blockId }: BucketCardProps) {
  const { t } = useTranslation();
  const dimmed = bucket.bucket_type === 'STAGING' && bucket.inactive;
  return (
    <Card
      component={Link}
      to={`/triage/${styleId}/${blockId}/buckets/${bucket.id}`}
      withBorder
      padding="md"
      style={{ opacity: dimmed ? 0.5 : 1, textDecoration: 'none', color: 'inherit' }}
      aria-label={t('triage.move.menu.destination_aria', { label: bucketLabel(bucket, t) })}
    >
      <Stack gap="xs">
        <Group justify="space-between" wrap="nowrap">
          <BucketBadge bucket={bucket} />
          <Text size="lg" fw={600} className="font-mono">
            {bucket.track_count}
          </Text>
        </Group>
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/BucketCard.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { BucketCard } from '../BucketCard';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

const tech: TriageBucket = {
  id: 'b1',
  bucket_type: 'NEW',
  category_id: null,
  category_name: null,
  inactive: false,
  track_count: 12,
};

describe('BucketCard', () => {
  it('renders bucket badge and count', () => {
    r(<BucketCard bucket={tech} styleId="s1" blockId="bl1" />);
    expect(screen.getByText('NEW')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
  });
  it('links to /triage/:styleId/:blockId/buckets/:bucketId', () => {
    r(<BucketCard bucket={tech} styleId="s1" blockId="bl1" />);
    const link = screen.getByRole('link');
    expect(link).toHaveAttribute('href', '/triage/s1/bl1/buckets/b1');
  });
  it('dims inactive STAGING via opacity', () => {
    const inactive: TriageBucket = {
      id: 'b2',
      bucket_type: 'STAGING',
      category_id: 'c1',
      category_name: 'Old',
      inactive: true,
      track_count: 3,
    };
    r(<BucketCard bucket={inactive} styleId="s1" blockId="bl1" />);
    const link = screen.getByRole('link');
    expect(link).toHaveStyle('opacity: 0.5');
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/BucketCard.test.tsx
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/BucketCard.tsx \
        frontend/src/features/triage/components/__tests__/BucketCard.test.tsx
```

Suggested subject: `feat(frontend): add BucketCard component`.

---

## Task 10: `BucketGrid` component

**Files:**

- Create: `frontend/src/features/triage/components/BucketGrid.tsx`
- Create: `frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/BucketGrid.tsx`:

```tsx
import { SimpleGrid } from '@mantine/core';
import { BucketCard } from './BucketCard';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketGridProps {
  buckets: TriageBucket[];
  styleId: string;
  blockId: string;
}

export function BucketGrid({ buckets, styleId, blockId }: BucketGridProps) {
  return (
    <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }} spacing="md">
      {buckets.map((b) => (
        <BucketCard key={b.id} bucket={b} styleId={styleId} blockId={blockId} />
      ))}
    </SimpleGrid>
  );
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx`:

```tsx
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../../../i18n';
import { BucketGrid } from '../BucketGrid';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>{ui}</MantineProvider>
    </MemoryRouter>,
  );
}

const buckets: TriageBucket[] = [
  { id: 'b1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
  { id: 'b2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'b3', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 3 },
];

describe('BucketGrid', () => {
  it('renders all buckets in given order', () => {
    r(<BucketGrid buckets={buckets} styleId="s1" blockId="bl1" />);
    const links = screen.getAllByRole('link');
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b1');
    expect(links[1]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b2');
    expect(links[2]).toHaveAttribute('href', '/triage/s1/bl1/buckets/b3');
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/BucketGrid.test.tsx
```

Expected: 1 test pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/BucketGrid.tsx \
        frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx
```

Suggested subject: `feat(frontend): add BucketGrid component`.

---

## Task 11: `MoveToMenu` component

**Files:**

- Create: `frontend/src/features/triage/components/MoveToMenu.tsx`
- Create: `frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/MoveToMenu.tsx`:

```tsx
import { ActionIcon, Menu } from '@mantine/core';
import { IconDotsVertical } from '../../../components/icons';
import { useTranslation } from 'react-i18next';
import { bucketLabel, moveDestinationsFor, type TriageBucket } from '../lib/bucketLabels';
import { BucketBadge } from './BucketBadge';

export interface MoveToMenuProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  disabled?: boolean;
}

export function MoveToMenu({ buckets, currentBucketId, onMove, disabled }: MoveToMenuProps) {
  const { t } = useTranslation();
  const destinations = moveDestinationsFor(buckets, currentBucketId);

  if (destinations.length === 0 || disabled) {
    return (
      <ActionIcon variant="subtle" disabled aria-label={t('triage.move.menu.trigger_aria')}>
        <IconDotsVertical size={16} />
      </ActionIcon>
    );
  }

  return (
    <Menu position="bottom-end" withinPortal>
      <Menu.Target>
        <ActionIcon variant="subtle" aria-label={t('triage.move.menu.trigger_aria')}>
          <IconDotsVertical size={16} />
        </ActionIcon>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Label>{t('triage.move.menu.label')}</Menu.Label>
        {destinations.map((d) => (
          <Menu.Item
            key={d.id}
            leftSection={<BucketBadge bucket={d} size="xs" />}
            onClick={() => onMove(d)}
            aria-label={t('triage.move.menu.destination_aria', { label: bucketLabel(d, t) })}
          >
            {bucketLabel(d, t)}
          </Menu.Item>
        ))}
      </Menu.Dropdown>
    </Menu>
  );
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { MoveToMenu } from '../MoveToMenu';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const buckets: TriageBucket[] = [
  { id: 'src', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
  { id: 'staging', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 0 },
  { id: 'staging-inactive', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Old', inactive: true, track_count: 0 },
];

describe('MoveToMenu', () => {
  it('lists active destinations excluding current and inactive STAGING', async () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} />);
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    expect(await screen.findByRole('menuitem', { name: /Move to OLD/ })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: /Move to Tech \(staging\)/ })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /Move to NEW/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('menuitem', { name: /Old \(staging, inactive\)/ }),
    ).not.toBeInTheDocument();
  });

  it('calls onMove with the destination bucket', async () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} />);
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    expect(onMove).toHaveBeenCalledWith(expect.objectContaining({ id: 'dst' }));
  });

  it('renders disabled trigger when destinations empty', () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={[buckets[0]]} currentBucketId="src" onMove={onMove} />);
    expect(screen.getByRole('button', { name: /Move track/ })).toBeDisabled();
  });

  it('renders disabled trigger when disabled prop set', () => {
    const onMove = vi.fn();
    r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} disabled />);
    expect(screen.getByRole('button', { name: /Move track/ })).toBeDisabled();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/MoveToMenu.test.tsx
```

Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/MoveToMenu.tsx \
        frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx
```

Suggested subject: `feat(frontend): add MoveToMenu component`.

---

## Task 12: `BucketTrackRow` component

**Files:**

- Create: `frontend/src/features/triage/components/BucketTrackRow.tsx`
- Create: `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/BucketTrackRow.tsx`:

```tsx
import { Card, Group, Stack, Table, Text } from '@mantine/core';
import { IconAlertTriangle } from '../../../components/icons';
import { useTranslation } from 'react-i18next';
import { formatLength, formatReleaseDate } from '../../../lib/formatters';
import type { BucketTrack } from '../hooks/useBucketTracks';
import type { TriageBucket } from '../lib/bucketLabels';
import { MoveToMenu } from './MoveToMenu';

export interface BucketTrackRowProps {
  track: BucketTrack;
  variant: 'desktop' | 'mobile';
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  showMoveMenu: boolean;
}

export function BucketTrackRow({
  track,
  variant,
  buckets,
  currentBucketId,
  onMove,
  showMoveMenu,
}: BucketTrackRowProps) {
  const { t } = useTranslation();
  const aiBadge = track.is_ai_suspected ? (
    <IconAlertTriangle
      size={14}
      aria-label={t('triage.tracks_table.ai_suspected_aria')}
      color="var(--color-warning)"
    />
  ) : null;
  const moveMenu = showMoveMenu ? (
    <MoveToMenu buckets={buckets} currentBucketId={currentBucketId} onMove={onMove} />
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
        <Table.Td>{track.artists.join(', ')}</Table.Td>
        <Table.Td className="font-mono">{track.bpm ?? '—'}</Table.Td>
        <Table.Td className="font-mono">{formatLength(track.length_ms)}</Table.Td>
        <Table.Td className="font-mono">{formatReleaseDate(track.spotify_release_date)}</Table.Td>
        <Table.Td>{moveMenu}</Table.Td>
      </Table.Tr>
    );
  }

  return (
    <Card withBorder padding="sm">
      <Stack gap={4}>
        <Group justify="space-between" wrap="nowrap" align="flex-start">
          <Group gap="xs">
            {aiBadge}
            <Text fw={500}>{track.title}</Text>
          </Group>
          {moveMenu}
        </Group>
        {track.mix_name && (
          <Text size="xs" c="dimmed">
            {track.mix_name}
          </Text>
        )}
        <Text size="sm">{track.artists.join(', ')}</Text>
        <Group gap="md" mt={4}>
          <Text size="xs" c="dimmed" className="font-mono">
            {track.bpm ?? '—'} BPM
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatLength(track.length_ms)}
          </Text>
          <Text size="xs" c="dimmed" className="font-mono">
            {formatReleaseDate(track.spotify_release_date)}
          </Text>
        </Group>
        {track.publish_date && (
          <Text size="xs" c="dimmed">
            Beatport: {track.publish_date}
          </Text>
        )}
      </Stack>
    </Card>
  );
}
```

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider, Table } from '@mantine/core';
import '../../../../i18n';
import { BucketTrackRow } from '../BucketTrackRow';
import type { BucketTrack } from '../../hooks/useBucketTracks';
import type { TriageBucket } from '../../lib/bucketLabels';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const track: BucketTrack = {
  track_id: 't1',
  title: 'Test Track',
  mix_name: 'Original Mix',
  isrc: null,
  bpm: 124,
  length_ms: 360_000,
  publish_date: '2026-04-21',
  spotify_release_date: '2026-04-15',
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  artists: ['Artist A', 'Artist B'],
  added_at: '2026-04-21T08:00:00Z',
};

const buckets: TriageBucket[] = [
  { id: 'src', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
];

describe('BucketTrackRow desktop', () => {
  it('renders title, mix_name, artists.join, bpm, length, release date', () => {
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
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText('Original Mix')).toBeInTheDocument();
    expect(screen.getByText('Artist A, Artist B')).toBeInTheDocument();
    expect(screen.getByText('124')).toBeInTheDocument();
    expect(screen.getByText('6:00')).toBeInTheDocument();
    expect(screen.getByText('2026-04-15')).toBeInTheDocument();
  });

  it('shows AI warning when is_ai_suspected', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={{ ...track, is_ai_suspected: true }}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.getByLabelText(/AI-suspected track/i)).toBeInTheDocument();
  });

  it('hides MoveToMenu when showMoveMenu=false (FINALIZED)', () => {
    r(
      <Table>
        <Table.Tbody>
          <BucketTrackRow
            track={track}
            variant="desktop"
            buckets={buckets}
            currentBucketId="src"
            onMove={vi.fn()}
            showMoveMenu={false}
          />
        </Table.Tbody>
      </Table>,
    );
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });
});

describe('BucketTrackRow mobile', () => {
  it('renders fields including Beatport publish_date secondary', () => {
    r(
      <BucketTrackRow
        track={track}
        variant="mobile"
        buckets={buckets}
        currentBucketId="src"
        onMove={vi.fn()}
        showMoveMenu
      />,
    );
    expect(screen.getByText('Test Track')).toBeInTheDocument();
    expect(screen.getByText(/Beatport: 2026-04-21/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/BucketTrackRow.test.tsx
```

Expected: 4 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/BucketTrackRow.tsx \
        frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx
```

Suggested subject: `feat(frontend): add BucketTrackRow component`.

---

## Task 13: `BucketTracksList` component (search + load-more + Table/Stack)

**Files:**

- Create: `frontend/src/features/triage/components/BucketTracksList.tsx`
- Create: `frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/BucketTracksList.tsx`:

```tsx
import { useState } from 'react';
import { Button, Group, Stack, Table, TextInput } from '@mantine/core';
import { useDebouncedValue, useMediaQuery } from '@mantine/hooks';
import { useTranslation } from 'react-i18next';
import { IconSearch, IconX } from '../../../components/icons';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useBucketTracks } from '../hooks/useBucketTracks';
import { BucketTrackRow } from './BucketTrackRow';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketTracksListProps {
  blockId: string;
  bucket: TriageBucket;
  buckets: TriageBucket[];
  showMoveMenu: boolean;
  onMove: (trackId: string, toBucket: TriageBucket) => void;
}

export function BucketTracksList({
  blockId,
  bucket,
  buckets,
  showMoveMenu,
  onMove,
}: BucketTracksListProps) {
  const { t } = useTranslation();
  const isMobile = useMediaQuery('(max-width: 64em)');
  const [rawSearch, setRawSearch] = useState('');
  const [debounced] = useDebouncedValue(rawSearch.trim(), 300);
  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } = useBucketTracks(
    blockId,
    bucket.id,
    debounced,
  );

  const items = data?.pages.flatMap((p) => p.items) ?? [];
  const total = data?.pages[0]?.total ?? 0;
  const remaining = Math.max(0, total - items.length);

  const searchInput = (
    <TextInput
      placeholder={t('triage.bucket.search_placeholder')}
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
    if (debounced) {
      return (
        <Stack gap="md">
          {searchInput}
          <EmptyState
            title={t('triage.bucket.empty.search_miss_title')}
            body={
              <Button variant="default" onClick={() => setRawSearch('')}>
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
      showMoveMenu={showMoveMenu}
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

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import '../../../../i18n';
import { BucketTracksList } from '../BucketTracksList';
import type { TriageBucket } from '../../lib/bucketLabels';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const buckets: TriageBucket[] = [
  { id: 'bk', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
  { id: 'dst', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
];

function mkTracks(ids: string[], total: number) {
  return {
    items: ids.map((id) => ({
      track_id: id,
      title: `Track ${id}`,
      mix_name: null,
      isrc: null,
      bpm: 124,
      length_ms: 360_000,
      publish_date: null,
      spotify_release_date: null,
      spotify_id: null,
      release_type: null,
      is_ai_suspected: false,
      artists: [],
      added_at: '2026-04-21T08:00:00Z',
    })),
    total,
    limit: 50,
    offset: 0,
  };
}

describe('BucketTracksList', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('renders empty state with default body for non-UNCLASSIFIED bucket', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks([], 0)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    expect(await screen.findByText(/No tracks in this bucket/)).toBeInTheDocument();
    expect(screen.getByText(/Move tracks here from another bucket/)).toBeInTheDocument();
  });

  it('renders UNCLASSIFIED-specific empty body', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks([], 0)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={{ ...buckets[0], bucket_type: 'UNCLASSIFIED' }}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    expect(await screen.findByText(/Spotify release date is missing/)).toBeInTheDocument();
  });

  it('debounces search and includes search param', async () => {
    let lastUrl = '';
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', ({ request }) => {
        lastUrl = request.url;
        return HttpResponse.json(mkTracks([], 0));
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText(/No tracks in this bucket/);
    await userEvent.type(screen.getByPlaceholderText(/Search tracks/), 'foo');
    await waitFor(() => expect(lastUrl).toContain('search=foo'), { timeout: 1500 });
  });

  it('renders rows + load-more', async () => {
    let calls = 0;
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', ({ request }) => {
        calls += 1;
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) return HttpResponse.json({ ...mkTracks(['t1'], 2), limit: 1 });
        return HttpResponse.json({ ...mkTracks(['t2'], 2), limit: 1, offset: 1 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]}
        buckets={buckets}
        showMoveMenu
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText('Track t1');
    expect(screen.queryByText('Track t2')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Load more/ }));
    await screen.findByText('Track t2');
    expect(calls).toBe(2);
  });

  it('hides MoveToMenu rows when showMoveMenu=false', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1/buckets/bk/tracks', () =>
        HttpResponse.json(mkTracks(['t1'], 1)),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
    render(
      <BucketTracksList
        blockId="b1"
        bucket={buckets[0]}
        buckets={buckets}
        showMoveMenu={false}
        onMove={vi.fn()}
      />,
      { wrapper: wrap(qc) },
    );
    await screen.findByText('Track t1');
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/BucketTracksList.test.tsx
```

Expected: 5 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/BucketTracksList.tsx \
        frontend/src/features/triage/components/__tests__/BucketTracksList.test.tsx
```

Suggested subject: `feat(frontend): add BucketTracksList component`.

---

## Task 14: `TriageBlockHeader` component

**Files:**

- Create: `frontend/src/features/triage/components/TriageBlockHeader.tsx`
- Create: `frontend/src/features/triage/components/__tests__/TriageBlockHeader.test.tsx`

- [ ] **Step 1: Write the component**

Create `frontend/src/features/triage/components/TriageBlockHeader.tsx`:

```tsx
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Menu,
  Stack,
  Text,
  Title,
  Tooltip,
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
}

export function TriageBlockHeader({ block, onDelete }: TriageBlockHeaderProps) {
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
            <Tooltip label={t('triage.detail.finalize_coming_soon')}>
              <Button disabled>{t('triage.detail.finalize_cta')}</Button>
            </Tooltip>
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

- [ ] **Step 2: Write the failing tests**

Create `frontend/src/features/triage/components/__tests__/TriageBlockHeader.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { TriageBlockHeader } from '../TriageBlockHeader';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const inProgress: TriageBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [],
};

describe('TriageBlockHeader IN_PROGRESS', () => {
  it('renders title, dates, status badge, Finalize button (disabled), kebab', () => {
    r(<TriageBlockHeader block={inProgress} onDelete={() => {}} />);
    expect(screen.getByText('W17')).toBeInTheDocument();
    expect(screen.getByText('IN_PROGRESS')).toBeInTheDocument();
    expect(screen.getByText(/2026-04-21.*2026-04-28/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Finalize/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: /Delete block/ })).toBeInTheDocument();
  });

  it('opens kebab menu and calls onDelete', async () => {
    const onDelete = vi.fn();
    r(<TriageBlockHeader block={inProgress} onDelete={onDelete} />);
    await userEvent.click(screen.getByRole('button', { name: /Delete block/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete block/ }));
    expect(onDelete).toHaveBeenCalled();
  });
});

describe('TriageBlockHeader FINALIZED', () => {
  const finalized: TriageBlock = {
    ...inProgress,
    status: 'FINALIZED',
    finalized_at: '2026-04-22T10:00:00Z',
  };

  it('shows FINALIZED badge + finalized_at, hides Finalize and kebab', () => {
    r(<TriageBlockHeader block={finalized} onDelete={() => {}} />);
    expect(screen.getByText('FINALIZED')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Finalize/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
    expect(screen.getByText(/finalized/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test**

```bash
cd frontend
pnpm test src/features/triage/components/__tests__/TriageBlockHeader.test.tsx
```

Expected: 3 tests pass.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/triage/components/TriageBlockHeader.tsx \
        frontend/src/features/triage/components/__tests__/TriageBlockHeader.test.tsx
```

Suggested subject: `feat(frontend): add TriageBlockHeader component`.

---

## Task 15: `TriageDetailPage` route

**Files:**

- Create: `frontend/src/features/triage/routes/TriageDetailPage.tsx`

(Integration test for this page lands in Task 18.)

- [ ] **Step 1: Write the page**

Create `frontend/src/features/triage/routes/TriageDetailPage.tsx`:

```tsx
import { Anchor, Stack } from '@mantine/core';
import { Link, Navigate, useNavigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { modals } from '@mantine/modals';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useTriageBlock } from '../hooks/useTriageBlock';
import { useDeleteTriageBlock } from '../hooks/useDeleteTriageBlock';
import { TriageBlockHeader } from '../components/TriageBlockHeader';
import { BucketGrid } from '../components/BucketGrid';

export function TriageDetailPage() {
  const { styleId, id } = useParams<{ styleId: string; id: string }>();
  if (!styleId || !id) return <Navigate to="/triage" replace />;
  return <TriageDetailInner styleId={styleId} blockId={id} />;
}

interface InnerProps {
  styleId: string;
  blockId: string;
}

function TriageDetailInner({ styleId, blockId }: InnerProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { data, isLoading, isError, error } = useTriageBlock(blockId);
  const del = useDeleteTriageBlock(styleId);

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    const code = error instanceof ApiError ? error.code : 'unknown';
    if (code === 'triage_block_not_found' || (error instanceof ApiError && error.status === 404)) {
      return (
        <EmptyState
          title={t('triage.errors.block_not_found_title')}
          body={
            <Anchor component={Link} to={`/triage/${styleId}`}>
              {t('triage.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return (
      <EmptyState
        title={t('triage.errors.service_unavailable')}
        body={
          <Anchor component={Link} to={`/triage/${styleId}`}>
            {t('triage.detail.back_to_list')}
          </Anchor>
        }
      />
    );
  }
  if (!data) return null;

  const handleDelete = () => {
    modals.openConfirmModal({
      title: t('triage.delete_modal.title'),
      children: t('triage.delete_modal.body', { name: data.name }),
      labels: {
        confirm: t('triage.delete_modal.confirm'),
        cancel: t('triage.delete_modal.cancel'),
      },
      confirmProps: { color: 'red' },
      onConfirm: () => {
        del.mutate(blockId, {
          onSuccess: () => {
            notifications.show({ message: t('triage.toast.deleted'), color: 'green' });
            navigate(`/triage/${styleId}`);
          },
          onError: (err) => {
            const msg =
              err instanceof ApiError && err.status === 404
                ? t('triage.toast.delete_not_found')
                : t('triage.toast.generic_error');
            notifications.show({ message: msg, color: 'red' });
          },
        });
      },
    });
  };

  return (
    <Stack gap="lg">
      <Anchor component={Link} to={`/triage/${styleId}`} c="var(--color-fg)" td="none">
        {t('triage.detail.back_to_list')}
      </Anchor>
      <TriageBlockHeader block={data} onDelete={handleDelete} />
      <BucketGrid buckets={data.buckets} styleId={styleId} blockId={blockId} />
    </Stack>
  );
}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/routes/TriageDetailPage.tsx
```

Suggested subject: `feat(frontend): add TriageDetailPage route`.

---

## Task 16: `BucketDetailPage` route (with Undo via direct apiClient)

**Files:**

- Create: `frontend/src/features/triage/routes/BucketDetailPage.tsx`

(Integration test for this page lands in Task 19.)

- [ ] **Step 1: Write the page**

Create `frontend/src/features/triage/routes/BucketDetailPage.tsx`:

```tsx
import { useRef } from 'react';
import { Anchor, Group, Stack, Text, Title } from '@mantine/core';
import { Link, Navigate, useParams } from 'react-router';
import { useTranslation } from 'react-i18next';
import { useQueryClient } from '@tanstack/react-query';
import { notifications } from '@mantine/notifications';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { FullScreenLoader } from '../../../components/FullScreenLoader';
import { useTriageBlock } from '../hooks/useTriageBlock';
import {
  takeSnapshot,
  undoMoveDirect,
  useMoveTracks,
  type MoveInput,
  type MoveSnapshot,
} from '../hooks/useMoveTracks';
import { BucketTracksList } from '../components/BucketTracksList';
import { BucketBadge } from '../components/BucketBadge';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export function BucketDetailPage() {
  const { styleId, id, bucketId } = useParams<{
    styleId: string;
    id: string;
    bucketId: string;
  }>();
  if (!styleId || !id || !bucketId) return <Navigate to="/triage" replace />;
  return <BucketDetailInner styleId={styleId} blockId={id} bucketId={bucketId} />;
}

interface InnerProps {
  styleId: string;
  blockId: string;
  bucketId: string;
}

function BucketDetailInner({ styleId, blockId, bucketId }: InnerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: block, isLoading, isError, error } = useTriageBlock(blockId);
  const move = useMoveTracks(blockId, styleId);
  const undoInflight = useRef(false);

  if (isLoading) return <FullScreenLoader />;
  if (isError) {
    const code = error instanceof ApiError ? error.code : 'unknown';
    if (code === 'triage_block_not_found' || (error instanceof ApiError && error.status === 404)) {
      return (
        <EmptyState
          title={t('triage.errors.block_not_found_title')}
          body={
            <Anchor component={Link} to={`/triage/${styleId}`}>
              {t('triage.detail.back_to_list')}
            </Anchor>
          }
        />
      );
    }
    return (
      <EmptyState
        title={t('triage.errors.service_unavailable')}
        body={
          <Anchor component={Link} to={`/triage/${styleId}`}>
            {t('triage.detail.back_to_list')}
          </Anchor>
        }
      />
    );
  }
  if (!block) return null;

  const bucket = block.buckets.find((b) => b.id === bucketId);
  if (!bucket) {
    return (
      <EmptyState
        title={t('triage.errors.bucket_not_found_title')}
        body={
          <Anchor component={Link} to={`/triage/${styleId}/${blockId}`}>
            {t('triage.bucket.back_to_block', { name: block.name })}
          </Anchor>
        }
      />
    );
  }

  const showMoveMenu = block.status === 'IN_PROGRESS';

  const handleMove = (trackId: string, toBucket: TriageBucket) => {
    const input: MoveInput = {
      fromBucketId: bucket.id,
      toBucketId: toBucket.id,
      trackIds: [trackId],
    };
    const snapshot: MoveSnapshot = takeSnapshot(qc, blockId, bucket.id);
    move.mutate(input, {
      onSuccess: () => {
        const toastId = `triage-move-${Date.now()}-${trackId}`;
        notifications.show({
          id: toastId,
          color: 'green',
          autoClose: 5000,
          message: (
            <Group justify="space-between" gap="md">
              <Text size="sm">
                {t('triage.move.toast.moved', {
                  count: 1,
                  to: bucketLabel(toBucket, t),
                })}
              </Text>
              <Anchor
                component="button"
                onClick={async () => {
                  if (undoInflight.current) return;
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
        if (code === 'inactive_bucket' || code === 'invalid_state') {
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
  };

  return (
    <Stack gap="lg">
      <Anchor
        component={Link}
        to={`/triage/${styleId}/${blockId}`}
        c="var(--color-fg)"
        td="none"
      >
        {t('triage.bucket.back_to_block', { name: block.name })}
      </Anchor>
      <Stack gap="xs">
        <Group gap="md" align="center">
          <Title order={2}>{bucketLabel(bucket, t)}</Title>
          <BucketBadge bucket={bucket} size="md" />
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
      <BucketTracksList
        blockId={blockId}
        bucket={bucket}
        buckets={block.buckets}
        showMoveMenu={showMoveMenu}
        onMove={handleMove}
      />
    </Stack>
  );
}
```

- [ ] **Step 2: Verify typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/routes/BucketDetailPage.tsx
```

Suggested subject: `feat(frontend): add BucketDetailPage route with undo`.

---

## Task 17: Wire routes — replace stub, register nested route, delete `TriageDetailStub`

**Files:**

- Modify: `frontend/src/routes/router.tsx`
- Delete: `frontend/src/features/triage/routes/TriageDetailStub.tsx`
- Modify: `frontend/src/features/triage/index.ts` — add re-exports for the two new pages.

- [ ] **Step 1: Update `router.tsx`**

Open `frontend/src/routes/router.tsx`. Replace the lines that import + register `TriageDetailStub`:

Before:

```tsx
import { TriageDetailStub } from '../features/triage/routes/TriageDetailStub';
// ...
{
  path: 'triage',
  children: [
    { index: true, element: <TriageIndexRedirect /> },
    { path: ':styleId', element: <TriageListPage /> },
    { path: ':styleId/:id', element: <TriageDetailStub /> },
  ],
},
```

After:

```tsx
import { TriageDetailPage } from '../features/triage/routes/TriageDetailPage';
import { BucketDetailPage } from '../features/triage/routes/BucketDetailPage';
// ...
{
  path: 'triage',
  children: [
    { index: true, element: <TriageIndexRedirect /> },
    { path: ':styleId', element: <TriageListPage /> },
    { path: ':styleId/:id', element: <TriageDetailPage /> },
    { path: ':styleId/:id/buckets/:bucketId', element: <BucketDetailPage /> },
  ],
},
```

- [ ] **Step 2: Delete `TriageDetailStub.tsx`**

```bash
git rm frontend/src/features/triage/routes/TriageDetailStub.tsx
```

- [ ] **Step 3: Update `features/triage/index.ts`**

Open `frontend/src/features/triage/index.ts` and replace the file with:

```ts
export { TriageIndexRedirect } from './routes/TriageIndexRedirect';
export { TriageListPage } from './routes/TriageListPage';
export { TriageDetailPage } from './routes/TriageDetailPage';
export { BucketDetailPage } from './routes/BucketDetailPage';
```

(Adjust if the file's existing structure adds extra named exports; keep them and add the two new lines.)

- [ ] **Step 4: Verify typecheck + tests**

```bash
cd frontend
pnpm typecheck
pnpm test
```

Expected: typecheck clean, all existing tests pass (no integration tests yet for the new pages).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/router.tsx \
        frontend/src/features/triage/index.ts
git rm frontend/src/features/triage/routes/TriageDetailStub.tsx 2>/dev/null
```

Suggested subject: `feat(frontend): wire triage detail routes, drop stub`.

---

## Task 18: Integration test — `TriageDetailPage`

**Files:**

- Create: `frontend/src/features/triage/__tests__/TriageDetailPage.integration.test.tsx`

- [ ] **Step 1: Write the integration test**

Create `frontend/src/features/triage/__tests__/TriageDetailPage.integration.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import {
  createMemoryRouter,
  RouterProvider,
} from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { TriageDetailPage } from '../routes/TriageDetailPage';

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/triage/:styleId/:id', element: <TriageDetailPage /> },
      { path: '/triage/:styleId', element: <div data-testid="list-page" /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 5 },
    { id: 'bk2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk3', bucket_type: 'NOT', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk4', bucket_type: 'DISCARD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk5', bucket_type: 'UNCLASSIFIED', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk6', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 2 },
    { id: 'bk7', bucket_type: 'STAGING', category_id: 'c2', category_name: 'Old', inactive: true, track_count: 1 },
  ],
};

describe('TriageDetailPage integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
  });
  afterEach(() => notifications.clean());

  it('renders header + bucket grid (5 tech + 2 STAGING)', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1');
    expect(await screen.findByText('W17')).toBeInTheDocument();
    const links = await screen.findAllByRole('link');
    // 1 back link + 7 bucket cards
    expect(links.filter((l) => l.getAttribute('href')?.includes('/buckets/'))).toHaveLength(7);
  });

  it('soft-deletes from kebab + navigates back + green toast', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.delete('http://localhost/triage/blocks/b1', () => new HttpResponse(null, { status: 204 })),
    );
    renderAt('/triage/s1/b1');
    await screen.findByText('W17');
    await userEvent.click(screen.getByRole('button', { name: /Delete block/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Delete block/ }));
    // Confirm modal
    await userEvent.click(await screen.findByRole('button', { name: /^Delete$/ }));
    await waitFor(() => expect(screen.getByTestId('list-page')).toBeInTheDocument());
    expect(await screen.findByText(/Triage block deleted/)).toBeInTheDocument();
  });

  it('FINALIZED variant hides Finalize button + kebab', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          ...inProgressBlock,
          status: 'FINALIZED',
          finalized_at: '2026-04-22T10:00:00Z',
        }),
      ),
    );
    renderAt('/triage/s1/b1');
    await screen.findByText('FINALIZED');
    expect(screen.queryByRole('button', { name: /Finalize/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete block/ })).not.toBeInTheDocument();
  });

  it('404 shows block-not-found + back link', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/missing', () =>
        HttpResponse.json(
          { error_code: 'triage_block_not_found', message: 'no' },
          { status: 404 },
        ),
      ),
    );
    renderAt('/triage/s1/missing');
    expect(await screen.findByText(/Block not found/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Back to triage/ })).toHaveAttribute(
      'href',
      '/triage/s1',
    );
  });

  it('inactive STAGING is dimmed (opacity 0.5) but still clickable', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1');
    const links = await screen.findAllByRole('link');
    const stagingInactiveLink = links.find((l) =>
      l.getAttribute('href')?.endsWith('/buckets/bk7'),
    )!;
    expect(stagingInactiveLink).toHaveStyle('opacity: 0.5');
  });
});
```

- [ ] **Step 2: Run the test**

```bash
cd frontend
pnpm test src/features/triage/__tests__/TriageDetailPage.integration.test.tsx
```

Expected: 5 tests pass.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/__tests__/TriageDetailPage.integration.test.tsx
```

Suggested subject: `test(frontend): add TriageDetailPage integration test`.

---

## Task 19: Integration test — `BucketDetailPage` (move + Undo + search + finalized)

**Files:**

- Create: `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`

- [ ] **Step 1: Write the integration test**

Create `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { ModalsProvider } from '@mantine/modals';
import { Notifications, notifications } from '@mantine/notifications';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { BucketDetailPage } from '../routes/BucketDetailPage';

function renderAt(path: string) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(
    [
      { path: '/triage/:styleId/:id/buckets/:bucketId', element: <BucketDetailPage /> },
      { path: '/triage/:styleId/:id', element: <div data-testid="block-page" /> },
      { path: '/triage/:styleId', element: <div data-testid="list-page" /> },
    ],
    { initialEntries: [path] },
  );
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications position="top-right" />
          <RouterProvider router={router} />
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const inProgressBlock = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T08:00:00Z',
  updated_at: '2026-04-21T08:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'bk1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 2 },
    { id: 'bk2', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'bk3', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: false, track_count: 0 },
  ],
};

function track(id: string) {
  return {
    track_id: id,
    title: `Track ${id}`,
    mix_name: null,
    isrc: null,
    bpm: 124,
    length_ms: 360_000,
    publish_date: null,
    spotify_release_date: null,
    spotify_id: null,
    release_type: null,
    is_ai_suspected: false,
    artists: [],
    added_at: '2026-04-21T08:00:00Z',
  };
}

describe('BucketDetailPage integration', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    notifications.clean();
  });
  afterEach(() => notifications.clean());

  it('renders track list and load-more', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const offset = Number(url.searchParams.get('offset') ?? '0');
        if (offset === 0) {
          return HttpResponse.json({ items: [track('t1')], total: 2, limit: 1, offset: 0 });
        }
        return HttpResponse.json({ items: [track('t2')], total: 2, limit: 1, offset: 1 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    expect(screen.queryByText('Track t2')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Load more/ }));
    await screen.findByText('Track t2');
  });

  it('move happy path: row disappears + green toast with Undo', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1'), track('t2')], total: 2, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk2/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json({ moved: 1 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const triggers = await screen.findAllByRole('button', { name: /Move track/ });
    await userEvent.click(triggers[0]);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    // Optimistic — t1 should disappear from the list
    await waitFor(() => expect(screen.queryByText('Track t1')).not.toBeInTheDocument());
    // Toast
    expect(await screen.findByText(/Moved 1 track/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Undo/ })).toBeInTheDocument();
  });

  it('Undo within 5s puts the track back', async () => {
    let postCount = 0;
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1'), track('t2')], total: 2, limit: 50, offset: 0 }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk2/tracks', () =>
        HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () => {
        postCount += 1;
        return HttpResponse.json({ moved: 1 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const triggers = await screen.findAllByRole('button', { name: /Move track/ });
    await userEvent.click(triggers[0]);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    const undoBtn = await screen.findByRole('button', { name: /Undo/ });
    await userEvent.click(undoBtn);
    await waitFor(() => expect(screen.getByText('Track t1')).toBeInTheDocument());
    await waitFor(() => expect(postCount).toBe(2));
    expect(await screen.findByText(/Undone/)).toBeInTheDocument();
  });

  it('move 409 inactive_bucket: rollback + red toast', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 }),
      ),
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'inactive_bucket', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    const trigger = await screen.findByRole('button', { name: /Move track/ });
    await userEvent.click(trigger);
    await userEvent.click(await screen.findByRole('menuitem', { name: /Move to OLD/ }));
    expect(await screen.findByText(/destination is no longer valid/i)).toBeInTheDocument();
    // Track restored
    expect(screen.getByText('Track t1')).toBeInTheDocument();
  });

  it('FINALIZED block: no MoveMenu', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () =>
        HttpResponse.json({
          ...inProgressBlock,
          status: 'FINALIZED',
          finalized_at: '2026-04-22T00:00:00Z',
        }),
      ),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', () =>
        HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 }),
      ),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    expect(screen.queryByRole('button', { name: /Move track/ })).not.toBeInTheDocument();
  });

  it('search miss empty state with clear-search action', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
      http.get('http://localhost/triage/blocks/b1/buckets/bk1/tracks', ({ request }) => {
        const url = new URL(request.url);
        const search = url.searchParams.get('search');
        if (search === 'xyz') {
          return HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 });
        }
        return HttpResponse.json({ items: [track('t1')], total: 1, limit: 50, offset: 0 });
      }),
    );
    renderAt('/triage/s1/b1/buckets/bk1');
    await screen.findByText('Track t1');
    await userEvent.type(screen.getByPlaceholderText(/Search tracks/), 'xyz');
    expect(await screen.findByText(/Nothing matches your search/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Clear search/ }));
    expect(await screen.findByText('Track t1')).toBeInTheDocument();
  });

  it('bucket-not-found in URL renders empty state', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(inProgressBlock)),
    );
    renderAt('/triage/s1/b1/buckets/no-such-id');
    expect(await screen.findByText(/Bucket not found/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test**

```bash
cd frontend
pnpm test src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
```

Expected: 7 tests pass. If any fail, the most likely culprits are (1) missing jsdom shims (verify `setup.ts` has all 5 — see CLAUDE.md), (2) `notifications.clean()` race (already in `beforeEach`/`afterEach`), or (3) Mantine `Menu` portal not opening in test (verify the `withinPortal` prop and that `@mantine/core` `MantineProvider` is wrapping).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx
```

Suggested subject: `test(frontend): add BucketDetailPage integration test`.

---

## Task 20: Smoke test against deployed prod API

**Files:** none modified — manual verification only.

- [ ] **Step 1: Verify `frontend/.env.local` exists and points at the deployed API**

```bash
cat frontend/.env.local
```

Expected: `VITE_API_BASE_URL=https://<api-gw>.execute-api.<region>.amazonaws.com`. If missing:

```bash
cd infra
terraform output -raw api_endpoint > /tmp/api
echo "VITE_API_BASE_URL=$(cat /tmp/api | tr -d '/')" > ../frontend/.env.local
cd ..
```

- [ ] **Step 2: Start the dev server**

```bash
cd frontend
pnpm dev
```

Expected: Vite logs `Local: http://127.0.0.1:5173`.

- [ ] **Step 3: Sign in, open an existing block**

In the browser:

1. Navigate to `http://127.0.0.1:5173/login` → sign in with Spotify.
2. Click `Triage` in the sidebar. Pick a style with at least one IN_PROGRESS block from F2.
3. Click the row → land on `/triage/<styleId>/<blockId>`. Header + bucket grid render. Inactive STAGING (if any) dimmed.

- [ ] **Step 4: Open a bucket and verify the track list**

1. Click a bucket card → `BucketDetailPage` mounts. Tracks render with bpm / length / release-date columns.
2. Type into the search box → after ~300ms the list filters.
3. Clear search → list restores.

- [ ] **Step 5: Move a track + Undo**

1. On the NEW bucket: click the per-row `···` → click a STAGING destination.
2. Verify the row disappears immediately, source counter -1, target counter +1, green toast appears.
3. Click `Undo` within 5s → row returns to source bucket, target counter back to original.

- [ ] **Step 6: Soft-delete a (test) block from header kebab**

Pick a disposable block (or create one via the F2 list page first). Click the header kebab → `Delete block` → confirm. Expected: navigates back to `/triage/<styleId>` with green toast `Triage block deleted.`. The row no longer appears in any tab.

- [ ] **Step 7: Stop the dev server (Ctrl-C) and document any anomalies**

If smoke surfaces any blocker, halt the plan, file a follow-up note, and address before merging.

- [ ] **Step 8: No commit** — Task 20 has no file changes.

---

## Task 21: Build, typecheck, full test sweep

**Files:** none modified — verification only.

- [ ] **Step 1: Typecheck**

```bash
cd frontend
pnpm typecheck
```

Expected: clean.

- [ ] **Step 2: Full test run**

```bash
cd frontend
pnpm test
```

Expected: ~160 tests pass (130 baseline + ~30 new).

- [ ] **Step 3: Production build**

```bash
cd frontend
pnpm build
```

Expected: under 700 KB minified bundle (no new deps); no warnings about missing icons or stale i18n keys.

- [ ] **Step 4: No commit** — Task 21 has no file changes.

---

## Task 22: Merge to main

**Files:** none modified.

- [ ] **Step 1: Verify branch state is clean**

```bash
git status
git log --oneline main..feat/triage-detail-move
```

Expected: working tree clean; commit list shows the F3a sequence (Task 1 → 19 commits).

- [ ] **Step 2: Switch to main in the canonical repo (NOT the worktree)**

The worktree has `feat/triage-detail-move` checked out. `main` lives in the canonical repo dir:

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git pull --ff-only origin main
git merge feat/triage-detail-move --no-ff -m "Merge branch 'feat/triage-detail-move'"
git push origin main
```

Expected: merge commit lands on `main`, push succeeds (TD-6 branch protection still not configured).

- [ ] **Step 3: Update the roadmap**

Open `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`. In the F3 row of the Ticket queue table:

```md
| **F3** | Triage detail (buckets + reordering) | P-16..P-19 | `GET /triage/blocks/{id}`, `POST /move`, `POST /transfer` | `02 Pages catalog` Pass 1 | spec-D | L (4-6 days) |
```

becomes:

```md
| ~~**F3a**~~ ✅ **Shipped 2026-05-03** | Triage detail (block + bucket browse + single-track move) | P-16, P-17 | `GET /triage/blocks/{id}`, `GET .../buckets/{bucket_id}/tracks`, `POST /move` | `02 Pages catalog` Pass 1 | spec-D | M — actual ~1 day session |
| **F3b** | Triage transfer (cross-block) | P-19 | `POST /triage/blocks/{src_id}/transfer` | Pass 1 | spec-D | M |
```

Add a `## Lessons learned (post-F3a, 2026-05-03)` section at the end of the roadmap to capture any new gotchas surfaced during F3a (especially around optimistic mutations + Undo via direct apiClient).

- [ ] **Step 4: Commit the roadmap update**

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
```

Generate via `caveman:caveman-commit`. Suggested subject: `docs: mark F3a shipped, split F3b out`.

```bash
git commit -m "<skill output>"
git push origin main
```

- [ ] **Step 5: Cleanup the worktree branch (optional, after a day or two of soak)**

When you're confident the merge is healthy:

```bash
cd /Users/roman/Projects/clouder-projects/clouder-core
git worktree remove .claude/worktrees/f3_task
git branch -d feat/triage-detail-move
```

---

## Done

After Task 22 lands, F3a is shipped:

- `/triage/:styleId/:id` renders block detail + bucket grid.
- `/triage/:styleId/:id/buckets/:bucketId` renders track list with search + load-more + per-row optimistic Move with Undo.
- FINALIZED blocks render read-only.
- Soft-delete works from header kebab.
- Inactive STAGING dimmed and excluded from move targets.
- ~30 new tests; F1 + F2 baseline still green; bundle still under 700 KB.

Next up: **F3b** (cross-block transfer — target-block + target-bucket picker, `POST /triage/blocks/{src_id}/transfer`). The brainstorming session for F3b can re-enter via `superpowers:brainstorming` with this F3a spec + roadmap as input.

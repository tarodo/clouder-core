# F3b — Triage Cross-Block Transfer Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement cross-block transfer in the triage frontend: add a `Transfer to other block…` item to the row-level kebab menu, open a two-step modal (pick sibling block → pick non-inactive bucket), POST to `/triage/blocks/{src_id}/transfer`, fire-and-toast on success.

**Architecture:** Extend three existing F3a components (`MoveToMenu`, `BucketGrid`, `BucketCard`) with new optional props rather than fork them. Add new `TransferModal` + `TransferBlockOption` components, new `useTransferTracks` hook with no `onMutate` (snapshot semantics — source is not mutated by the backend, so no optimistic write or Undo). Reuse `useTriageBlocksByStyle` (F2) for sibling discovery and `useTriageBlock` (F3a) for target bucket grid. Modal state lives locally inside `TransferModal` (`step` + `targetBlockId` via `useState`).

**Tech Stack:** React 19, TypeScript, Mantine 9 (`Modal`, `Menu.Divider`, `UnstyledButton`, `Loader`, `Anchor`), TanStack Query 5, react-router 7, react-i18next, Vitest + Testing Library + MSW, `@tabler/icons-react`.

**Spec:** `docs/superpowers/specs/2026-05-03-F3b-triage-transfer-frontend-design.md` (commit `d147ea5`).

---

## Conventions

- All paths are absolute from worktree root `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task`.
- All commands run from worktree root unless noted.
- All commits via `caveman:caveman-commit` skill (project policy in `CLAUDE.md`); use heredoc form for multi-line bodies.
- Frontend test runner: `pnpm --dir frontend test` (single run); `pnpm --dir frontend test --watch` if iterating.
- TypeScript check: `pnpm --dir frontend typecheck`.
- Build sanity: `pnpm --dir frontend build`.
- Branch: `feat/triage-transfer` (rename current `worktree-f3b_task` to `feat/triage-transfer` before first commit; see Task 0).

## File Structure

**New files:**
- `frontend/src/features/triage/hooks/useTransferTracks.ts`
- `frontend/src/features/triage/hooks/__tests__/useTransferTracks.test.tsx`
- `frontend/src/features/triage/components/TransferBlockOption.tsx`
- `frontend/src/features/triage/components/__tests__/TransferBlockOption.test.tsx`
- `frontend/src/features/triage/components/TransferModal.tsx`
- `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx`
- `frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx`

**Modified files:**
- `frontend/src/components/icons.ts` — add `IconArrowsExchange` re-export.
- `frontend/src/i18n/en.json` — add `triage.transfer.*` namespace (after `triage.tracks_table`).
- `frontend/src/features/triage/components/MoveToMenu.tsx` — new optional props `onTransfer` + `showTransfer`.
- `frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx` — add transfer-item tests.
- `frontend/src/features/triage/components/BucketGrid.tsx` — new optional props `mode`, `onSelect`, `disabled`, `cols`.
- `frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx` — add `mode='select'` + regression tests.
- `frontend/src/features/triage/components/BucketCard.tsx` — branch on `mode`.
- `frontend/src/features/triage/components/__tests__/BucketCard.test.tsx` — add `mode='select'` test.
- `frontend/src/features/triage/components/BucketTracksList.tsx` — thread optional `onTransfer` prop down.
- `frontend/src/features/triage/components/BucketTrackRow.tsx` — thread `onTransfer` to `MoveToMenu`.
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — local state `transferTrackId`, mount `TransferModal` conditionally.
- `frontend/src/features/triage/index.ts` — re-export `TransferModal`, `useTransferTracks`.

**Untouched (read-only references):**
- `frontend/src/features/triage/hooks/useTriageBlock.ts` (already has `enabled: !!id` — line 27)
- `frontend/src/features/triage/hooks/useTriageBlocksByStyle.ts` (used as-is for siblings)
- `frontend/src/features/triage/lib/bucketLabels.ts` (used as-is)
- `frontend/src/api/error.ts` (`ApiError.code` is the field we branch on)

---

## Task 0: Branch rename + smoke baseline

**Files:** none (git operation only)

**Why:** Per `CLAUDE.md` Branch Naming, `worktree-f3b_task` does not match `feat/<topic>`. Roadmap and spec D17 both name `feat/triage-transfer`. Establish the right branch before commits accumulate.

- [ ] **Step 1: Verify current branch name.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task branch --show-current
```

Expected: `worktree-f3b_task`.

- [ ] **Step 2: Rename branch.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task branch -m worktree-f3b_task feat/triage-transfer
```

- [ ] **Step 3: Confirm new branch name.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task branch --show-current
```

Expected: `feat/triage-transfer`.

- [ ] **Step 4: Baseline test run.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test
```

Expected: green; record the test count (should be ~205 from F3a baseline). This number is the reference for `+25` after F3b ships.

- [ ] **Step 5: Baseline typecheck + build.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend build
```

Expected: both green; record bundle size for ratchet check at end.

No commit — branch rename is metadata-only.

---

## Task 1: i18n keys + icon re-export (foundation)

**Files:**
- Modify: `frontend/src/i18n/en.json` (add `triage.transfer.*` keys after line 237 `tracks_table` block)
- Modify: `frontend/src/components/icons.ts` (add `IconArrowsExchange` to the re-export list)

- [ ] **Step 1: Add `triage.transfer.*` namespace to `en.json`.**

In `frontend/src/i18n/en.json`, locate the `tracks_table` object that ends at line 237 (the closing `}` after `"actions_header": "Actions"`). Replace that closing `},` with the block below — it inserts the new `transfer` namespace then closes `tracks_table` and `triage` correctly:

```json
    "tracks_table": {
      "title_header": "Title",
      "artists_header": "Artists",
      "bpm_header": "BPM",
      "length_header": "Length",
      "released_header": "Released",
      "ai_suspected_aria": "AI-suspected track",
      "actions_header": "Actions"
    },
    "transfer": {
      "menu_item": "Transfer to other block…",
      "modal": {
        "title_pick_block": "Transfer to which block?",
        "title_pick_bucket": "Pick a bucket in {{block_name}}",
        "back": "← Back",
        "load_more": "Load more",
        "track_count_one": "{{count}} track",
        "track_count_other": "{{count}} tracks"
      },
      "empty": {
        "no_siblings_title": "No other in-progress blocks",
        "no_siblings_body": "Create a new triage block to transfer tracks.",
        "no_siblings_cta": "Go to triage"
      },
      "toast": {
        "transferred_one": "Transferred 1 track to {{block_name}} / {{bucket_label}}.",
        "transferred_other": "Transferred {{count}} tracks to {{block_name}} / {{bucket_label}}.",
        "stale_source": "Source block changed. Refreshing.",
        "stale_target": "Target block is gone. Pick another.",
        "target_finalized": "Target block was finalized. Pick another.",
        "target_inactive": "That bucket is no longer valid.",
        "style_mismatch": "Style mismatch. Refreshing.",
        "error": "Transfer failed."
      }
    }
  }
}
```

- [ ] **Step 2: Add `IconArrowsExchange` to icons re-export.**

Read `frontend/src/components/icons.ts` first to see the current import list. The file re-exports a curated set from `@tabler/icons-react`. Locate the import list and add `IconArrowsExchange` alphabetically (it sorts after `IconArrowLeft` if present, else next to other `IconArrow*` icons). Then add it to the export list in the same file (the file's pattern already separates imports and exports — preserve that).

If the existing file is just `export { ... } from '@tabler/icons-react';`, add `IconArrowsExchange` to the brace list. Either way, the new symbol must be importable as:

```ts
import { IconArrowsExchange } from '../../../components/icons';
```

- [ ] **Step 3: Verify JSON is valid + icon imports clean.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green. If `en.json` is malformed JSON, vitest setup would fail; if `icons.ts` mistypes the icon, typecheck flags it.

- [ ] **Step 4: Run a smoke test that touches i18n.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/MoveToMenu.test.tsx
```

Expected: green (existing F3a tests should not regress; we only added keys).

- [ ] **Step 5: Commit.**

Generate the commit message via `caveman:caveman-commit` (input: "i18n triage.transfer keys + IconArrowsExchange re-export"). Use heredoc form per `CLAUDE.md`:

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/i18n/en.json frontend/src/components/icons.ts
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
chore(i18n): add triage.transfer keys and IconArrowsExchange icon

Foundation for F3b transfer modal — keys for menu item, two-step modal,
empty state, and the seven error/success toast variants. Icon re-export
exposes the swap glyph used in the new MoveToMenu item.
EOF
)"
```

Verify with:

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task log -1 --pretty=%B
```

Expected: full subject + body.

---

## Task 2: `useTransferTracks` hook + unit tests

**Files:**
- Create: `frontend/src/features/triage/hooks/useTransferTracks.ts`
- Create: `frontend/src/features/triage/hooks/__tests__/useTransferTracks.test.tsx`

- [ ] **Step 1: Write the failing test.**

Create `frontend/src/features/triage/hooks/__tests__/useTransferTracks.test.tsx` with this content (mirrors `useMoveTracks.test.tsx` patterns; uses MSW `server` from test setup; sets a token so `api` doesn't 401):

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useTransferTracks } from '../useTransferTracks';
import { triageBlockKey } from '../useTriageBlock';
import { triageBlocksByStyleKey } from '../useTriageBlocksByStyle';

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

describe('useTransferTracks', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs target_bucket_id + track_ids to /transfer and returns transferred count', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    expect(bodySeen).toEqual({ target_bucket_id: 'bk1', track_ids: ['t1'] });
    expect(result.current.data).toEqual({ transferred: 1 });
  });

  it('invalidates target bucketTracks, target blockDetail, and byStyle on success', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json({ transferred: 1 }),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    const calls = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(calls).toContainEqual(['triage', 'bucketTracks', 'tgt1', 'bk1']);
    expect(calls).toContainEqual(triageBlockKey('tgt1'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', 'IN_PROGRESS'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', 'FINALIZED'));
    expect(calls).toContainEqual(triageBlocksByStyleKey('st1', undefined));
  });

  it('does not invalidate source caches on success (snapshot semantics)', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json({ transferred: 1 }),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current.mutateAsync({
        targetBlockId: 'tgt1',
        targetBucketId: 'bk1',
        trackIds: ['t1'],
        styleId: 'st1',
      });
    });

    const calls = invalidate.mock.calls.map((c) => c[0]?.queryKey);
    expect(calls).not.toContainEqual(triageBlockKey('src1'));
    expect(calls.find((k) => Array.isArray(k) && k[0] === 'triage' && k[1] === 'bucketTracks' && k[2] === 'src1')).toBeUndefined();
  });

  it('rejects with ApiError on 409 and does not invalidate target caches', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );
    const qc = makeClient();
    const invalidate = vi.spyOn(qc, 'invalidateQueries');
    const { result } = renderHook(() => useTransferTracks('src1'), { wrapper: wrap(qc) });

    await act(async () => {
      await result.current
        .mutateAsync({
          targetBlockId: 'tgt1',
          targetBucketId: 'bk1',
          trackIds: ['t1'],
          styleId: 'st1',
        })
        .catch(() => {});
    });

    expect(result.current.isError).toBe(true);
    expect(invalidate).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/hooks/__tests__/useTransferTracks.test.tsx
```

Expected: FAIL — `Cannot find module '../useTransferTracks'`.

- [ ] **Step 3: Implement the hook.**

Create `frontend/src/features/triage/hooks/useTransferTracks.ts`:

```ts
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { triageBlockKey } from './useTriageBlock';
import {
  triageBlocksByStyleKey,
  type TriageStatus,
} from './useTriageBlocksByStyle';

export interface TransferInput {
  targetBlockId: string;
  targetBucketId: string;
  trackIds: string[];
  styleId: string;
}

export interface TransferResponse {
  transferred: number;
  correlation_id?: string;
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export function useTransferTracks(
  srcBlockId: string,
): UseMutationResult<TransferResponse, ApiError, TransferInput> {
  const qc = useQueryClient();
  return useMutation<TransferResponse, ApiError, TransferInput>({
    mutationKey: ['triage', 'transfer', srcBlockId],
    mutationFn: (input) =>
      api<TransferResponse>(`/triage/blocks/${srcBlockId}/transfer`, {
        method: 'POST',
        body: JSON.stringify({
          target_bucket_id: input.targetBucketId,
          track_ids: input.trackIds,
        }),
      }),
    onSuccess: (_data, input) => {
      qc.invalidateQueries({
        queryKey: ['triage', 'bucketTracks', input.targetBlockId, input.targetBucketId],
      });
      qc.invalidateQueries({ queryKey: triageBlockKey(input.targetBlockId) });
      for (const s of STATUSES) {
        qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(input.styleId, s) });
      }
    },
  });
}
```

- [ ] **Step 4: Run test to verify it passes.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/hooks/__tests__/useTransferTracks.test.tsx
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Run typecheck.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/hooks/useTransferTracks.ts frontend/src/features/triage/hooks/__tests__/useTransferTracks.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): add useTransferTracks hook

POST /triage/blocks/{src_id}/transfer mutation. Invalidates target
bucketTracks + target blockDetail + byStyle on success. No onMutate —
backend snapshot semantics: source not mutated, no optimistic write.
Source caches deliberately untouched on success.
EOF
)"
```

---

## Task 3: `TransferBlockOption` component + unit tests

**Files:**
- Create: `frontend/src/features/triage/components/TransferBlockOption.tsx`
- Create: `frontend/src/features/triage/components/__tests__/TransferBlockOption.test.tsx`

- [ ] **Step 1: Write the failing test.**

Create `frontend/src/features/triage/components/__tests__/TransferBlockOption.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import '../../../../i18n';
import { TransferBlockOption } from '../TransferBlockOption';
import type { TriageBlockSummary } from '../../hooks/useTriageBlocksByStyle';

function r(ui: React.ReactNode) {
  return render(<MantineProvider>{ui}</MantineProvider>);
}

const block: TriageBlockSummary = {
  id: 'b1',
  style_id: 's1',
  style_name: 'House',
  name: 'W17',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  track_count: 5,
};

describe('TransferBlockOption', () => {
  it('renders block name, date range, and track count (plural)', () => {
    r(<TransferBlockOption block={block} onSelect={vi.fn()} />);
    expect(screen.getByText('W17')).toBeInTheDocument();
    expect(screen.getByText(/2026-04-21 → 2026-04-28/)).toBeInTheDocument();
    expect(screen.getByText(/5 tracks/)).toBeInTheDocument();
  });

  it('renders singular track count when count is 1', () => {
    r(<TransferBlockOption block={{ ...block, track_count: 1 }} onSelect={vi.fn()} />);
    expect(screen.getByText(/1 track(?!s)/)).toBeInTheDocument();
  });

  it('calls onSelect when clicked', async () => {
    const onSelect = vi.fn();
    r(<TransferBlockOption block={block} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('calls onSelect on keyboard activation (Enter)', async () => {
    const onSelect = vi.fn();
    r(<TransferBlockOption block={block} onSelect={onSelect} />);
    const btn = screen.getByRole('button');
    btn.focus();
    await userEvent.keyboard('{Enter}');
    expect(onSelect).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/TransferBlockOption.test.tsx
```

Expected: FAIL — `Cannot find module '../TransferBlockOption'`.

- [ ] **Step 3: Implement the component.**

Create `frontend/src/features/triage/components/TransferBlockOption.tsx`:

```tsx
import { Stack, Text, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import type { TriageBlockSummary } from '../hooks/useTriageBlocksByStyle';

export interface TransferBlockOptionProps {
  block: TriageBlockSummary;
  onSelect: () => void;
}

export function TransferBlockOption({ block, onSelect }: TransferBlockOptionProps) {
  const { t } = useTranslation();
  return (
    <UnstyledButton
      onClick={onSelect}
      style={{
        display: 'block',
        width: '100%',
        padding: 'var(--mantine-spacing-md)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--mantine-radius-md)',
      }}
    >
      <Stack gap={2}>
        <Text fw={600}>{block.name}</Text>
        <Text size="sm" c="dimmed">
          {block.date_from} → {block.date_to} ·{' '}
          {t('triage.transfer.modal.track_count', { count: block.track_count })}
        </Text>
      </Stack>
    </UnstyledButton>
  );
}
```

- [ ] **Step 4: Run test to verify it passes.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/TransferBlockOption.test.tsx
```

Expected: PASS — all 4 tests green.

- [ ] **Step 5: Run typecheck.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/components/TransferBlockOption.tsx frontend/src/features/triage/components/__tests__/TransferBlockOption.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): add TransferBlockOption component

Step-1 row in the transfer modal: name + date range + track count
(plural-aware). UnstyledButton — full row clickable, keyboard accessible.
Slim ~30-line component instead of repurposing TriageBlockRow which
carries Link wrapper and kebab menu.
EOF
)"
```

---

## Task 4: `BucketGrid` + `BucketCard` `mode='select'` extension

**Files:**
- Modify: `frontend/src/features/triage/components/BucketGrid.tsx`
- Modify: `frontend/src/features/triage/components/BucketCard.tsx`
- Modify: `frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx`
- Modify: `frontend/src/features/triage/components/__tests__/BucketCard.test.tsx`

- [ ] **Step 1: Write failing tests in `BucketGrid.test.tsx`.**

Read the existing file first. Append (or merge) these new tests inside the existing `describe('BucketGrid', ...)`:

```tsx
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

// ... existing imports stay; add userEvent + vi above if missing

it('default mode is navigate (cards wrapped in Link)', () => {
  r(<BucketGrid buckets={buckets} styleId="s1" blockId="bl1" />);
  // Each card is an <a> link
  expect(screen.getAllByRole('link')).toHaveLength(buckets.length);
});

it('mode="select" wraps cards in buttons and calls onSelect', async () => {
  const onSelect = vi.fn();
  r(
    <BucketGrid
      buckets={buckets}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
    />,
  );
  const btns = screen.getAllByRole('button');
  expect(btns).toHaveLength(buckets.length);
  expect(screen.queryByRole('link')).toBeNull();

  await userEvent.click(btns[0]!);
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ id: 'b1' }));
});

it('mode="select" disables inactive STAGING buckets', async () => {
  const onSelect = vi.fn();
  const withInactive = [
    ...buckets,
    {
      id: 'b4',
      bucket_type: 'STAGING' as const,
      category_id: 'c2',
      category_name: 'Old',
      inactive: true,
      track_count: 0,
    },
  ];
  r(
    <BucketGrid
      buckets={withInactive}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
    />,
  );
  const btns = screen.getAllByRole('button');
  const inactiveBtn = btns[btns.length - 1]!;
  expect(inactiveBtn).toBeDisabled();
  await userEvent.click(inactiveBtn);
  expect(onSelect).not.toHaveBeenCalled();
});

it('mode="select" with disabled prop disables every card', async () => {
  const onSelect = vi.fn();
  r(
    <BucketGrid
      buckets={buckets}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
      disabled
    />,
  );
  for (const btn of screen.getAllByRole('button')) {
    expect(btn).toBeDisabled();
  }
});

it('respects custom cols prop', () => {
  // Render with cols={{ base: 1, xs: 2 }} and verify the SimpleGrid receives it.
  // Mantine renders cols via CSS variables; assert no crash + correct number of cards.
  const { container } = r(
    <BucketGrid
      buckets={buckets}
      styleId="s1"
      blockId="bl1"
      cols={{ base: 1, xs: 2 }}
    />,
  );
  expect(container.querySelectorAll('[class*="SimpleGrid"]').length).toBeGreaterThan(0);
  expect(screen.getAllByRole('link')).toHaveLength(buckets.length);
});
```

- [ ] **Step 2: Write failing tests in `BucketCard.test.tsx`.**

Read the existing file. Add these tests inside the existing `describe`:

```tsx
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

it('mode="select" renders a button and calls onSelect', async () => {
  const onSelect = vi.fn();
  const bucket = {
    id: 'b1',
    bucket_type: 'NEW' as const,
    category_id: null,
    category_name: null,
    inactive: false,
    track_count: 5,
  };
  r(
    <BucketCard
      bucket={bucket}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
    />,
  );
  const btn = screen.getByRole('button');
  await userEvent.click(btn);
  expect(onSelect).toHaveBeenCalledWith(bucket);
});

it('mode="select" + inactive STAGING is disabled and does not fire onSelect', async () => {
  const onSelect = vi.fn();
  const bucket = {
    id: 'b1',
    bucket_type: 'STAGING' as const,
    category_id: 'c1',
    category_name: 'Tech',
    inactive: true,
    track_count: 0,
  };
  r(
    <BucketCard
      bucket={bucket}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
    />,
  );
  const btn = screen.getByRole('button');
  expect(btn).toBeDisabled();
  await userEvent.click(btn);
  expect(onSelect).not.toHaveBeenCalled();
});

it('mode="select" + disabled prop disables card regardless of bucket state', async () => {
  const onSelect = vi.fn();
  const bucket = {
    id: 'b1',
    bucket_type: 'NEW' as const,
    category_id: null,
    category_name: null,
    inactive: false,
    track_count: 5,
  };
  r(
    <BucketCard
      bucket={bucket}
      styleId="s1"
      blockId="bl1"
      mode="select"
      onSelect={onSelect}
      disabled
    />,
  );
  expect(screen.getByRole('button')).toBeDisabled();
});
```

If the existing `BucketCard.test.tsx` does not import `MemoryRouter` (it only renders Cards, no Link in select mode), the imports stay the same — but for the *navigate* tests already in that file the MemoryRouter wrapper is needed. Check the file's existing wrapper helper `r()` and reuse.

- [ ] **Step 3: Run tests to verify they fail.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/BucketGrid.test.tsx src/features/triage/components/__tests__/BucketCard.test.tsx
```

Expected: FAIL — new props don't exist on `BucketGridProps` / `BucketCardProps`; `mode`, `onSelect`, `disabled`, `cols` typed as unknown.

- [ ] **Step 4: Extend `BucketCard` with `mode` branch.**

Replace `frontend/src/features/triage/components/BucketCard.tsx` with:

```tsx
import { Card, Group, Stack, Text, UnstyledButton } from '@mantine/core';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import { BucketBadge } from './BucketBadge';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';

export type BucketCardMode = 'navigate' | 'select';

export interface BucketCardProps {
  bucket: TriageBucket;
  styleId: string;
  blockId: string;
  mode?: BucketCardMode;
  onSelect?: (bucket: TriageBucket) => void;
  disabled?: boolean;
}

export function BucketCard({
  bucket,
  styleId,
  blockId,
  mode = 'navigate',
  onSelect,
  disabled,
}: BucketCardProps) {
  const { t } = useTranslation();
  const dimmed = bucket.bucket_type === 'STAGING' && bucket.inactive;
  const ariaLabel = t('triage.move.menu.destination_aria', { label: bucketLabel(bucket, t) });

  const inner = (
    <Stack gap="xs">
      <Group justify="space-between" wrap="nowrap">
        <BucketBadge bucket={bucket} />
        <Text size="lg" fw={600} className="font-mono">
          {bucket.track_count}
        </Text>
      </Group>
    </Stack>
  );

  if (mode === 'select') {
    const isDisabled = disabled || dimmed;
    return (
      <UnstyledButton
        onClick={() => onSelect?.(bucket)}
        disabled={isDisabled}
        aria-label={ariaLabel}
        style={{ width: '100%', opacity: dimmed ? 0.5 : 1 }}
      >
        <Card withBorder padding="md">
          {inner}
        </Card>
      </UnstyledButton>
    );
  }

  return (
    <Card
      component={Link}
      to={`/triage/${styleId}/${blockId}/buckets/${bucket.id}`}
      withBorder
      padding="md"
      style={{ opacity: dimmed ? 0.5 : 1, textDecoration: 'none', color: 'inherit' }}
      aria-label={ariaLabel}
    >
      {inner}
    </Card>
  );
}
```

- [ ] **Step 5: Extend `BucketGrid` to forward props.**

Replace `frontend/src/features/triage/components/BucketGrid.tsx` with:

```tsx
import { SimpleGrid, type SimpleGridProps } from '@mantine/core';
import { BucketCard, type BucketCardMode } from './BucketCard';
import type { TriageBucket } from '../lib/bucketLabels';

export interface BucketGridProps {
  buckets: TriageBucket[];
  styleId: string;
  blockId: string;
  mode?: BucketCardMode;
  onSelect?: (bucket: TriageBucket) => void;
  disabled?: boolean;
  cols?: SimpleGridProps['cols'];
}

export function BucketGrid({
  buckets,
  styleId,
  blockId,
  mode = 'navigate',
  onSelect,
  disabled,
  cols = { base: 1, xs: 2, md: 3 },
}: BucketGridProps) {
  return (
    <SimpleGrid cols={cols} spacing="md">
      {buckets.map((b) => (
        <BucketCard
          key={b.id}
          bucket={b}
          styleId={styleId}
          blockId={blockId}
          mode={mode}
          onSelect={onSelect}
          disabled={disabled}
        />
      ))}
    </SimpleGrid>
  );
}
```

- [ ] **Step 6: Run tests to verify they pass.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/BucketGrid.test.tsx src/features/triage/components/__tests__/BucketCard.test.tsx
```

Expected: all green (existing F3a tests + new ones).

- [ ] **Step 7: Run full triage component suite as regression check.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components
```

Expected: all green (no F3a regressions on `BucketTracksList`, `TriageBlockHeader`, etc., which all consume `BucketCard` indirectly).

- [ ] **Step 8: Run typecheck.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green.

- [ ] **Step 9: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/components/BucketGrid.tsx frontend/src/features/triage/components/BucketCard.tsx frontend/src/features/triage/components/__tests__/BucketGrid.test.tsx frontend/src/features/triage/components/__tests__/BucketCard.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): add mode='select' to BucketGrid and BucketCard

Select mode wraps each card in UnstyledButton + onSelect callback —
needed by F3b transfer modal step 2. Inactive STAGING buckets and the
disabled prop both render the card disabled. Default mode stays
'navigate' (Link wrapper) so existing F3a callers are unaffected.
EOF
)"
```

---

## Task 5: `MoveToMenu` `onTransfer` + `showTransfer` props

**Files:**
- Modify: `frontend/src/features/triage/components/MoveToMenu.tsx`
- Modify: `frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx`

- [ ] **Step 1: Add failing tests.**

Append these tests inside the existing `describe('MoveToMenu', ...)` block in `frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx`:

```tsx
it('shows Transfer item after divider when showTransfer + onTransfer provided', async () => {
  const onMove = vi.fn();
  const onTransfer = vi.fn();
  r(
    <MoveToMenu
      buckets={buckets}
      currentBucketId="src"
      onMove={onMove}
      showTransfer
      onTransfer={onTransfer}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
  expect(
    await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
  ).toBeInTheDocument();
});

it('hides Transfer item when showTransfer is false', async () => {
  const onMove = vi.fn();
  const onTransfer = vi.fn();
  r(
    <MoveToMenu
      buckets={buckets}
      currentBucketId="src"
      onMove={onMove}
      showTransfer={false}
      onTransfer={onTransfer}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
  await screen.findByRole('menuitem', { name: /Move to OLD/ });
  expect(
    screen.queryByRole('menuitem', { name: /Transfer to other block/ }),
  ).not.toBeInTheDocument();
});

it('hides Transfer item when onTransfer is omitted', async () => {
  const onMove = vi.fn();
  r(<MoveToMenu buckets={buckets} currentBucketId="src" onMove={onMove} showTransfer />);
  await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
  await screen.findByRole('menuitem', { name: /Move to OLD/ });
  expect(
    screen.queryByRole('menuitem', { name: /Transfer to other block/ }),
  ).not.toBeInTheDocument();
});

it('clicking Transfer fires onTransfer callback', async () => {
  const onMove = vi.fn();
  const onTransfer = vi.fn();
  r(
    <MoveToMenu
      buckets={buckets}
      currentBucketId="src"
      onMove={onMove}
      showTransfer
      onTransfer={onTransfer}
    />,
  );
  await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
  await userEvent.click(
    await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
  );
  expect(onTransfer).toHaveBeenCalledTimes(1);
});

it('with empty destinations + showTransfer, trigger is enabled and Transfer is the only item', async () => {
  const onMove = vi.fn();
  const onTransfer = vi.fn();
  const onlyCurrent: TriageBucket[] = [buckets[0]!];
  r(
    <MoveToMenu
      buckets={onlyCurrent}
      currentBucketId="src"
      onMove={onMove}
      showTransfer
      onTransfer={onTransfer}
    />,
  );
  const trigger = screen.getByRole('button', { name: /Move track/ });
  expect(trigger).not.toBeDisabled();
  await userEvent.click(trigger);
  const items = await screen.findAllByRole('menuitem');
  expect(items).toHaveLength(1);
  expect(items[0]).toHaveAccessibleName(/Transfer to other block/);
});
```

- [ ] **Step 2: Run tests to verify they fail.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/MoveToMenu.test.tsx
```

Expected: FAIL — new props don't exist; existing F3a "renders disabled trigger when destinations empty" test will still pass.

- [ ] **Step 3: Update `MoveToMenu.tsx` to add the new props and the Transfer item.**

Replace `frontend/src/features/triage/components/MoveToMenu.tsx` with:

```tsx
import { ActionIcon, Menu } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconArrowsExchange, IconDotsVertical } from '../../../components/icons';
import { bucketLabel, moveDestinationsFor, type TriageBucket } from '../lib/bucketLabels';
import { BucketBadge } from './BucketBadge';

export interface MoveToMenuProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  onTransfer?: () => void;
  showTransfer?: boolean;
  disabled?: boolean;
}

export function MoveToMenu({
  buckets,
  currentBucketId,
  onMove,
  onTransfer,
  showTransfer,
  disabled,
}: MoveToMenuProps) {
  const { t } = useTranslation();
  const destinations = moveDestinationsFor(buckets, currentBucketId);
  const transferAvailable = !!showTransfer && !!onTransfer;

  // Trigger is disabled only when there are no items at all.
  const noItems = destinations.length === 0 && !transferAvailable;

  if (noItems || disabled) {
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
        {destinations.length > 0 && (
          <>
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
          </>
        )}
        {transferAvailable && destinations.length > 0 && <Menu.Divider />}
        {transferAvailable && (
          <Menu.Item leftSection={<IconArrowsExchange size={14} />} onClick={onTransfer}>
            {t('triage.transfer.menu_item')}
          </Menu.Item>
        )}
      </Menu.Dropdown>
    </Menu>
  );
}
```

- [ ] **Step 4: Run tests.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/MoveToMenu.test.tsx
```

Expected: PASS — both old (4 tests) and new (5 tests).

- [ ] **Step 5: Run typecheck + full triage component suite.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/components/MoveToMenu.tsx frontend/src/features/triage/components/__tests__/MoveToMenu.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): add Transfer item to MoveToMenu

New optional props onTransfer + showTransfer expose a 'Transfer to other
block…' Menu.Item after a Menu.Divider. Trigger stays enabled when
destinations are empty if transfer is available — gives the user a way
in even from a one-bucket-no-siblings edge case.
EOF
)"
```

---

## Task 6: `TransferModal` component + unit tests

**Files:**
- Create: `frontend/src/features/triage/components/TransferModal.tsx`
- Create: `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx`

This is the largest component test — exercises both modal steps via mocked react-query state and MSW handlers.

- [ ] **Step 1: Write failing tests.**

Create `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import '../../../../i18n';
import { TransferModal } from '../TransferModal';
import type { TriageBlock } from '../../hooks/useTriageBlock';

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(ui: React.ReactNode, qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter>{ui}</MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

const srcBlock: TriageBlock = {
  id: 'src1',
  style_id: 's1',
  style_name: 'House',
  name: 'Src Block',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'srcb1', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 3 },
  ],
};

const targetBlock: TriageBlock = {
  id: 'tgt1',
  style_id: 's1',
  style_name: 'House',
  name: 'Tgt Block',
  date_from: '2026-04-28',
  date_to: '2026-05-05',
  status: 'IN_PROGRESS',
  created_at: '2026-04-28T00:00:00Z',
  updated_at: '2026-04-28T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'tgtNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'tgtOLD', bucket_type: 'OLD', category_id: null, category_name: null, inactive: false, track_count: 1 },
    { id: 'tgtSTAGING', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: true, track_count: 0 },
  ],
};

const siblings = {
  items: [
    {
      id: 'tgt1', style_id: 's1', style_name: 'House', name: 'Tgt Block',
      date_from: '2026-04-28', date_to: '2026-05-05',
      status: 'IN_PROGRESS' as const,
      created_at: '2026-04-28T00:00:00Z', updated_at: '2026-04-28T00:00:00Z',
      finalized_at: null, track_count: 1,
    },
    {
      id: 'src1', style_id: 's1', style_name: 'House', name: 'Src Block',
      date_from: '2026-04-21', date_to: '2026-04-28',
      status: 'IN_PROGRESS' as const,
      created_at: '2026-04-21T00:00:00Z', updated_at: '2026-04-21T00:00:00Z',
      finalized_at: null, track_count: 3,
    },
  ],
  total: 2,
  limit: 50,
  offset: 0,
};

beforeEach(() => {
  tokenStore.set('TOK');
  notifications.clean();
});

describe('TransferModal', () => {
  it('step 1 lists siblings excluding current block, sorted by created_at DESC (server order)', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    expect(await screen.findByText('Tgt Block')).toBeInTheDocument();
    expect(screen.queryByText('Src Block')).toBeNull();
  });

  it('shows EmptyState when only the current block is in IN_PROGRESS', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [siblings.items[1]!], // src only
          total: 1,
          limit: 50,
          offset: 0,
        }),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    expect(
      await screen.findByText(/No other in-progress blocks/),
    ).toBeInTheDocument();
  });

  it('step 2: clicking a target block loads bucket grid; Back returns to step 1', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));

    // Step 2: bucket grid renders
    await waitFor(() => {
      expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
    });
    expect(screen.getAllByRole('button').filter((b) => b.textContent?.match(/NEW|OLD|Tech/))).toHaveLength(3);

    await userEvent.click(screen.getByRole('button', { name: /Back/ }));
    expect(await screen.findByText('Tgt Block')).toBeInTheDocument();
  });

  it('step 2: clicking active NEW bucket POSTs transfer with right payload, fires green toast, closes modal', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const newBucketBtn = screen.getAllByRole('button').find((b) => b.textContent === 'NEW0');
    // BucketCard renders BucketBadge label + count; "NEW" + "0" concatenate in textContent.
    expect(newBucketBtn).toBeDefined();
    await userEvent.click(newBucketBtn!);

    await waitFor(() => expect(bodySeen).toEqual({ target_bucket_id: 'tgtNEW', track_ids: ['tk1'] }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(await screen.findByText(/Transferred 1 track to Tgt Block/)).toBeInTheDocument();
  });

  it('step 2: inactive STAGING bucket is disabled and does not POST', async () => {
    let posted = false;
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () => {
        posted = true;
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const stagingBtn = screen.getAllByRole('button').find((b) => /Tech \(staging, inactive\)/.test(b.textContent ?? ''));
    expect(stagingBtn).toBeDefined();
    expect(stagingBtn).toBeDisabled();
    await userEvent.click(stagingBtn!);
    expect(posted).toBe(false);
  });

  it('409 invalid_state: red toast target_finalized + modal closes', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => b.textContent === 'NEW0');
    await userEvent.click(newBtn!);

    expect(
      await screen.findByText(/Target block was finalized/),
    ).toBeInTheDocument();
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('409 target_bucket_inactive: red toast target_inactive + STAYS on step 2', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );
    const onClose = vi.fn();

    r(
      <TransferModal
        opened
        onClose={onClose}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => b.textContent === 'NEW0');
    await userEvent.click(newBtn!);

    expect(await screen.findByText(/no longer valid/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
  });

  it('404 bucket_not_found: red toast stale_target + returns to step 1', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json(siblings),
      ),
      http.get('http://localhost/triage/blocks/tgt1', () =>
        HttpResponse.json(targetBlock),
      ),
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'bucket_not_found', message: 'gone' },
          { status: 404 },
        ),
      ),
    );

    r(
      <TransferModal
        opened
        onClose={vi.fn()}
        srcBlock={srcBlock}
        trackId="tk1"
        styleId="s1"
      />,
    );

    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => b.textContent === 'NEW0');
    await userEvent.click(newBtn!);

    expect(await screen.findByText(/Target block is gone/)).toBeInTheDocument();
    await waitFor(() => screen.getByText(/Transfer to which block/));
  });
});
```

> **Note:** the assertion `b.textContent === 'NEW0'` is fragile against component whitespace changes; if it fails after implementation, tighten via `findByRole('button', { name: /^NEW/ })` and `track_count: 0` mock data — keep the test selector close to what the spec says (BucketCard renders bucket type + count). Adjust selectors if implementation whitespace differs; the *behavior* assertions are load-bearing.

- [ ] **Step 2: Run tests to verify they fail.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/TransferModal.test.tsx
```

Expected: FAIL — module `../TransferModal` does not exist.

- [ ] **Step 3: Implement `TransferModal`.**

Create `frontend/src/features/triage/components/TransferModal.tsx`:

```tsx
import { useState, useEffect } from 'react';
import {
  Anchor,
  Button,
  Center,
  Group,
  Loader,
  Modal,
  Stack,
} from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useQueryClient, type QueryClient } from '@tanstack/react-query';
import { Link } from 'react-router';
import { useTranslation } from 'react-i18next';
import type { TFunction } from 'i18next';
import { ApiError } from '../../../api/error';
import { EmptyState } from '../../../components/EmptyState';
import { useTriageBlock, triageBlockKey, type TriageBlock } from '../hooks/useTriageBlock';
import {
  useTriageBlocksByStyle,
  triageBlocksByStyleKey,
  type TriageStatus,
} from '../hooks/useTriageBlocksByStyle';
import { useTransferTracks } from '../hooks/useTransferTracks';
import { bucketLabel, type TriageBucket } from '../lib/bucketLabels';
import { BucketGrid } from './BucketGrid';
import { TransferBlockOption } from './TransferBlockOption';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

export interface TransferModalProps {
  opened: boolean;
  onClose: () => void;
  srcBlock: TriageBlock;
  trackId: string;
  styleId: string;
}

export function TransferModal({
  opened,
  onClose,
  srcBlock,
  trackId,
  styleId,
}: TransferModalProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [step, setStep] = useState<'block' | 'bucket'>('block');
  const [targetBlockId, setTargetBlockId] = useState<string | null>(null);

  const siblingsQuery = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const targetBlockQuery = useTriageBlock(targetBlockId ?? '');
  const transfer = useTransferTracks(srcBlock.id);

  // Reset internal state on close.
  useEffect(() => {
    if (!opened) {
      setStep('block');
      setTargetBlockId(null);
    }
  }, [opened]);

  const siblings = (siblingsQuery.data?.pages ?? [])
    .flatMap((p) => p.items)
    .filter((b) => b.id !== srcBlock.id);

  const handleClose = () => {
    setStep('block');
    setTargetBlockId(null);
    onClose();
  };

  const handlePickBlock = (id: string) => {
    setTargetBlockId(id);
    setStep('bucket');
  };

  const handlePickBucket = (bucket: TriageBucket) => {
    if (!targetBlockId) return;
    transfer.mutate(
      { targetBlockId, targetBucketId: bucket.id, trackIds: [trackId], styleId },
      {
        onSuccess: () => {
          notifications.show({
            color: 'green',
            message: t('triage.transfer.toast.transferred', {
              count: 1,
              block_name: targetBlockQuery.data?.name ?? '',
              bucket_label: bucketLabel(bucket, t),
            }),
          });
          handleClose();
        },
        onError: (err) =>
          handleTransferError({
            err,
            t,
            qc,
            styleId,
            srcBlockId: srcBlock.id,
            targetBlockId,
            setStep,
            close: handleClose,
          }),
      },
    );
  };

  const title =
    step === 'block'
      ? t('triage.transfer.modal.title_pick_block')
      : t('triage.transfer.modal.title_pick_bucket', {
          block_name: targetBlockQuery.data?.name ?? '',
        });

  return (
    <Modal opened={opened} onClose={handleClose} size="lg" title={title}>
      {step === 'block' && (
        <Step1
          loading={siblingsQuery.isLoading}
          siblings={siblings}
          hasNextPage={siblingsQuery.hasNextPage ?? false}
          fetchingNext={siblingsQuery.isFetchingNextPage}
          onPick={handlePickBlock}
          onLoadMore={() => siblingsQuery.fetchNextPage()}
          styleId={styleId}
          onClose={handleClose}
        />
      )}
      {step === 'bucket' && (
        <Step2
          loading={targetBlockQuery.isLoading}
          targetBlock={targetBlockQuery.data}
          transferPending={transfer.isPending}
          onBack={() => setStep('block')}
          onPick={handlePickBucket}
        />
      )}
    </Modal>
  );
}

interface Step1Props {
  loading: boolean;
  siblings: ReturnType<typeof useTriageBlocksByStyle>['data'] extends infer D
    ? D extends { pages: { items: infer I }[] }
      ? I extends Array<infer X>
        ? X[]
        : never
      : never
    : never;
  hasNextPage: boolean;
  fetchingNext: boolean;
  onPick: (id: string) => void;
  onLoadMore: () => void;
  styleId: string;
  onClose: () => void;
}

function Step1({
  loading,
  siblings,
  hasNextPage,
  fetchingNext,
  onPick,
  onLoadMore,
  styleId,
  onClose,
}: Step1Props) {
  const { t } = useTranslation();
  if (loading) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }
  if (siblings.length === 0) {
    return (
      <EmptyState
        title={t('triage.transfer.empty.no_siblings_title')}
        body={
          <Stack gap="sm">
            <span>{t('triage.transfer.empty.no_siblings_body')}</span>
            <Anchor component={Link} to={`/triage/${styleId}`} onClick={onClose}>
              {t('triage.transfer.empty.no_siblings_cta')}
            </Anchor>
          </Stack>
        }
      />
    );
  }
  return (
    <Stack gap="sm">
      {siblings.map((b) => (
        <TransferBlockOption key={b.id} block={b} onSelect={() => onPick(b.id)} />
      ))}
      {hasNextPage && (
        <Button variant="subtle" loading={fetchingNext} onClick={onLoadMore}>
          {t('triage.transfer.modal.load_more')}
        </Button>
      )}
    </Stack>
  );
}

interface Step2Props {
  loading: boolean;
  targetBlock: TriageBlock | undefined;
  transferPending: boolean;
  onBack: () => void;
  onPick: (bucket: TriageBucket) => void;
}

function Step2({ loading, targetBlock, transferPending, onBack, onPick }: Step2Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Group gap="xs">
        <Anchor component="button" type="button" onClick={onBack}>
          {t('triage.transfer.modal.back')}
        </Anchor>
      </Group>
      {loading && (
        <Center py="xl">
          <Loader />
        </Center>
      )}
      {targetBlock && (
        <BucketGrid
          buckets={targetBlock.buckets}
          styleId={targetBlock.style_id}
          blockId={targetBlock.id}
          mode="select"
          cols={{ base: 1, xs: 2 }}
          onSelect={onPick}
          disabled={transferPending}
        />
      )}
    </Stack>
  );
}

interface ErrorCtx {
  err: ApiError | unknown;
  t: TFunction;
  qc: QueryClient;
  styleId: string;
  srcBlockId: string;
  targetBlockId: string | null;
  setStep: (s: 'block' | 'bucket') => void;
  close: () => void;
}

function handleTransferError(ctx: ErrorCtx): void {
  const code = ctx.err instanceof ApiError ? ctx.err.code : 'unknown';
  let toastKey: string;
  let next: 'close' | 'step1' | 'stay';

  switch (code) {
    case 'triage_block_not_found':
    case 'tracks_not_in_source':
      toastKey = 'triage.transfer.toast.stale_source';
      ctx.qc.invalidateQueries({ queryKey: ['triage', 'bucketTracks', ctx.srcBlockId] });
      next = 'close';
      break;
    case 'bucket_not_found':
      toastKey = 'triage.transfer.toast.stale_target';
      for (const s of STATUSES) ctx.qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(ctx.styleId, s) });
      next = 'step1';
      break;
    case 'invalid_state':
      toastKey = 'triage.transfer.toast.target_finalized';
      for (const s of STATUSES) ctx.qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(ctx.styleId, s) });
      next = 'close';
      break;
    case 'target_bucket_inactive':
      toastKey = 'triage.transfer.toast.target_inactive';
      if (ctx.targetBlockId) ctx.qc.invalidateQueries({ queryKey: triageBlockKey(ctx.targetBlockId) });
      next = 'stay';
      break;
    case 'target_block_style_mismatch':
      toastKey = 'triage.transfer.toast.style_mismatch';
      next = 'close';
      break;
    default:
      toastKey = 'errors.network';
      next = 'stay';
  }

  notifications.show({ color: 'red', message: ctx.t(toastKey) });
  if (next === 'close') ctx.close();
  else if (next === 'step1') ctx.setStep('block');
}
```

> **Note on `Step1Props.siblings` type:** the helper-style derivation above is a verbose way to write the right element type. If TypeScript chokes, replace with a direct import: `siblings: TriageBlockSummary[]` after importing `TriageBlockSummary` from `../hooks/useTriageBlocksByStyle`. Pick whichever the implementer finds cleaner — both are equivalent.

- [ ] **Step 4: Run tests.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/TransferModal.test.tsx
```

Expected: PASS — all 7 tests green.

If a test fails on a fragile selector (e.g. `b.textContent === 'NEW0'`), tighten the assertion to use `findByRole('button', { name: /^NEW/ })` or query by `aria-label` (`bucketLabel`-formatted). Keep the *behavioral* assertion intact.

- [ ] **Step 5: Run typecheck + full triage suite as regression check.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage
```

Expected: green.

- [ ] **Step 6: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/components/TransferModal.tsx frontend/src/features/triage/components/__tests__/TransferModal.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): add TransferModal component

Two-step modal for cross-block transfer. Step 1 lists IN_PROGRESS
sibling blocks (current excluded) via useTriageBlocksByStyle. Step 2
loads the target block's buckets via useTriageBlock and renders them in
BucketGrid mode='select' with cols={{ base: 1, xs: 2 }}. Error mapping
covers all spec-D codes: stale_source / stale_target / target_finalized
/ target_inactive / style_mismatch / network. Modal stays on step 2 only
for recoverable errors (target_bucket_inactive, 503).
EOF
)"
```

---

## Task 7: Wire `BucketTracksList` + `BucketTrackRow` + `BucketDetailPage`

**Files:**
- Modify: `frontend/src/features/triage/components/BucketTrackRow.tsx`
- Modify: `frontend/src/features/triage/components/BucketTracksList.tsx`
- Modify: `frontend/src/features/triage/routes/BucketDetailPage.tsx`

This task threads `onTransfer` from the page down to `MoveToMenu` and mounts `TransferModal`.

- [ ] **Step 1: Extend `BucketTrackRow` to accept and forward `onTransfer`.**

Replace the props interface and the `MoveToMenu` invocation in `frontend/src/features/triage/components/BucketTrackRow.tsx`. Specifically:

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
}
```

And update the `MoveToMenu` line (around line 35):

```tsx
const moveMenu = showMoveMenu ? (
  <MoveToMenu
    buckets={buckets}
    currentBucketId={currentBucketId}
    onMove={onMove}
    onTransfer={onTransfer}
    showTransfer={blockStatus === 'IN_PROGRESS' && !!onTransfer}
  />
) : null;
```

Add `blockStatus` and `onTransfer` to the destructured props at the top of the component:

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
}: BucketTrackRowProps) {
  // ... existing body
}
```

> **Why a separate `blockStatus` prop?** `showMoveMenu` is already gated on `block.status === 'IN_PROGRESS'` upstream; in practice `showMoveMenu === true` implies `blockStatus === 'IN_PROGRESS'`. We pass `blockStatus` explicitly anyway so the prop wiring is unambiguous and resilient to future reuse where someone might set `showMoveMenu=true` for a different reason.

- [ ] **Step 2: Update existing `BucketTrackRow.test.tsx` to remain green.**

Read `frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx`. The new prop is optional (`onTransfer?`), so existing tests don't need to change — only verify they still compile (TypeScript will not complain because `onTransfer` is optional). Run:

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/BucketTrackRow.test.tsx
```

Expected: green. Add a single new test to assert that when `blockStatus='IN_PROGRESS'` and `onTransfer` is provided, the menu shows the Transfer item:

```tsx
it('passes onTransfer through to MoveToMenu when blockStatus=IN_PROGRESS', async () => {
  const onTransfer = vi.fn();
  // r() is the existing wrapper from this file
  r(
    <table><tbody>
    <BucketTrackRow
      track={{
        track_id: 'tk1', title: 't', mix_name: null, isrc: null, bpm: null,
        length_ms: null, publish_date: null, spotify_release_date: null,
        spotify_id: null, release_type: null, is_ai_suspected: false,
        artists: ['a'], added_at: '2026-04-21T00:00:00Z',
      }}
      variant="desktop"
      buckets={[
        { id: 'cur', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
      ]}
      currentBucketId="cur"
      onMove={vi.fn()}
      onTransfer={onTransfer}
      showMoveMenu
      blockStatus="IN_PROGRESS"
    />
    </tbody></table>,
  );
  await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
  await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
  expect(onTransfer).toHaveBeenCalledTimes(1);
});
```

(If the existing test file's `r()` helper already wraps in a `MantineProvider`, no extra setup needed; the `<table><tbody>` shell is needed because `BucketTrackRow` desktop variant emits a `<tr>`.)

- [ ] **Step 3: Extend `BucketTracksList` to thread `onTransfer` down.**

In `frontend/src/features/triage/components/BucketTracksList.tsx`:

Add to the props interface:

```tsx
export interface BucketTracksListProps {
  blockId: string;
  bucket: TriageBucket;
  buckets: TriageBucket[];
  showMoveMenu: boolean;
  onMove: (trackId: string, toBucket: TriageBucket) => void;
  onTransfer?: (trackId: string) => void;
  blockStatus?: 'IN_PROGRESS' | 'FINALIZED';
}
```

Destructure them:

```tsx
export function BucketTracksList({
  blockId,
  bucket,
  buckets,
  showMoveMenu,
  onMove,
  onTransfer,
  blockStatus,
}: BucketTracksListProps) {
  // ... existing body
}
```

In the `rows = items.map(...)` block (around line 101), add the new props:

```tsx
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
  />
));
```

- [ ] **Step 4: Update existing `BucketTracksList.test.tsx` to compile.**

`onTransfer` and `blockStatus` are optional, so existing tests still pass. Run:

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/components/__tests__/BucketTracksList.test.tsx
```

Expected: green.

- [ ] **Step 5: Wire `BucketDetailPage` to mount `TransferModal`.**

Edit `frontend/src/features/triage/routes/BucketDetailPage.tsx`. Add imports near the top:

```tsx
import { useState } from 'react';
import { TransferModal } from '../components/TransferModal';
```

(`useState` is already imported in F3a — verify existing imports first; if `useState` is already present, do not duplicate.)

Inside `BucketDetailInner`, alongside the existing `undoInflight` ref, add:

```tsx
const [transferTrackId, setTransferTrackId] = useState<string | null>(null);
```

Pass `onTransfer` and `blockStatus` into `BucketTracksList`:

```tsx
<BucketTracksList
  blockId={blockId}
  bucket={bucket}
  buckets={block.buckets}
  showMoveMenu={showMoveMenu}
  onMove={handleMove}
  onTransfer={(trackId) => setTransferTrackId(trackId)}
  blockStatus={block.status}
/>
```

After the closing `</Stack>` of the page (the outermost Stack), conditionally mount the modal — but since the Modal manages its own visibility, we mount it always once `transferTrackId !== null`:

```tsx
{transferTrackId && (
  <TransferModal
    opened
    onClose={() => setTransferTrackId(null)}
    srcBlock={block}
    trackId={transferTrackId}
    styleId={styleId}
  />
)}
```

The whole return then looks like:

```tsx
return (
  <Stack gap="lg">
    {/* ... existing back link, header, BucketTracksList */}
    <BucketTracksList
      blockId={blockId}
      bucket={bucket}
      buckets={block.buckets}
      showMoveMenu={showMoveMenu}
      onMove={handleMove}
      onTransfer={(trackId) => setTransferTrackId(trackId)}
      blockStatus={block.status}
    />
    {transferTrackId && (
      <TransferModal
        opened
        onClose={() => setTransferTrackId(null)}
        srcBlock={block}
        trackId={transferTrackId}
        styleId={styleId}
      />
    )}
  </Stack>
);
```

- [ ] **Step 6: Run typecheck + the full triage feature suite.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage
```

Expected: green. The existing F3a integration test `BucketDetailPage.integration.test.tsx` should continue to pass since it never opens the transfer modal (the modal mounts only when `transferTrackId !== null`).

- [ ] **Step 7: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/components/BucketTrackRow.tsx frontend/src/features/triage/components/BucketTracksList.tsx frontend/src/features/triage/routes/BucketDetailPage.tsx frontend/src/features/triage/components/__tests__/BucketTrackRow.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
feat(triage): wire transfer modal into BucketDetailPage

BucketTrackRow + BucketTracksList thread an optional onTransfer
callback into MoveToMenu. BucketDetailPage holds the transferTrackId
state and conditionally mounts TransferModal. blockStatus prop
explicitly threaded so the menu's showTransfer gate is unambiguous,
even though showMoveMenu already implies IN_PROGRESS today.
EOF
)"
```

---

## Task 8: Re-exports in `index.ts`

**Files:**
- Modify: `frontend/src/features/triage/index.ts`

- [ ] **Step 1: Add re-exports.**

Replace `frontend/src/features/triage/index.ts` with:

```ts
export { TriageIndexRedirect } from './routes/TriageIndexRedirect';
export { TriageListPage } from './routes/TriageListPage';
export { TriageDetailPage } from './routes/TriageDetailPage';
export { BucketDetailPage } from './routes/BucketDetailPage';
export { TransferModal } from './components/TransferModal';
export { useTransferTracks } from './hooks/useTransferTracks';
```

- [ ] **Step 2: Run typecheck.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green.

- [ ] **Step 3: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/index.ts
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
chore(triage): re-export TransferModal and useTransferTracks

Feature index now exposes the new transfer surface alongside the
existing routes — keeps the public surface of the feature in one place.
EOF
)"
```

---

## Task 9: Integration test `TransferFlow.integration.test.tsx`

**Files:**
- Create: `frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx`

This exercises the full path: render `BucketDetailPage` → kebab → Transfer → modal → bucket pick → toast. Uses MSW for all API calls.

- [ ] **Step 1: Read the F3a integration test for shape reference.**

The existing F3a integration test `frontend/src/features/triage/__tests__/BucketDetailPage.integration.test.tsx` is the closest pattern — it sets up a `MemoryRouter`, mocks the block + bucket-tracks endpoints, and exercises `MoveToMenu`. Mirror it.

- [ ] **Step 2: Write the failing integration test.**

Create `frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { Notifications, notifications } from '@mantine/notifications';
import { ModalsProvider } from '@mantine/modals';
import { MemoryRouter, Routes, Route } from 'react-router';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../test/setup';
import { tokenStore } from '../../../auth/tokenStore';
import '../../../i18n';
import { BucketDetailPage } from '../routes/BucketDetailPage';

const SRC_BLOCK = {
  id: 'src1',
  style_id: 's1',
  style_name: 'House',
  name: 'Src Block',
  date_from: '2026-04-21',
  date_to: '2026-04-28',
  status: 'IN_PROGRESS',
  created_at: '2026-04-21T00:00:00Z',
  updated_at: '2026-04-21T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'srcNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 1 },
  ],
};

const TGT_BLOCK = {
  id: 'tgt1',
  style_id: 's1',
  style_name: 'House',
  name: 'Tgt Block',
  date_from: '2026-04-28',
  date_to: '2026-05-05',
  status: 'IN_PROGRESS',
  created_at: '2026-04-28T00:00:00Z',
  updated_at: '2026-04-28T00:00:00Z',
  finalized_at: null,
  buckets: [
    { id: 'tgtNEW', bucket_type: 'NEW', category_id: null, category_name: null, inactive: false, track_count: 0 },
    { id: 'tgtSTAGING', bucket_type: 'STAGING', category_id: 'c1', category_name: 'Tech', inactive: true, track_count: 0 },
  ],
};

const TRACK = {
  track_id: 'tk1',
  title: 'Some Title',
  mix_name: null,
  isrc: null,
  bpm: 128,
  length_ms: 240000,
  publish_date: null,
  spotify_release_date: '2026-04-15',
  spotify_id: null,
  release_type: null,
  is_ai_suspected: false,
  artists: ['Artist'],
  added_at: '2026-04-21T00:00:00Z',
};

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}

function r(qc = makeClient()) {
  return render(
    <QueryClientProvider client={qc}>
      <MantineProvider>
        <ModalsProvider>
          <Notifications />
          <MemoryRouter initialEntries={['/triage/s1/src1/buckets/srcNEW']}>
            <Routes>
              <Route
                path="/triage/:styleId/:id/buckets/:bucketId"
                element={<BucketDetailPage />}
              />
              <Route path="/triage/:styleId" element={<div>triage list</div>} />
            </Routes>
          </MemoryRouter>
        </ModalsProvider>
      </MantineProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  tokenStore.set('TOK');
  notifications.clean();
  // Default handlers — individual tests override as needed.
  server.use(
    http.get('http://localhost/triage/blocks/src1', () => HttpResponse.json(SRC_BLOCK)),
    http.get('http://localhost/triage/blocks/tgt1', () => HttpResponse.json(TGT_BLOCK)),
    http.get('http://localhost/triage/blocks/src1/buckets/srcNEW/tracks', () =>
      HttpResponse.json({ items: [TRACK], total: 1, limit: 50, offset: 0 }),
    ),
    http.get('http://localhost/styles/s1/triage/blocks', () =>
      HttpResponse.json({
        items: [
          { ...TGT_BLOCK, track_count: 0 },
          { ...SRC_BLOCK, track_count: 1 },
        ].map((b) => ({
          id: b.id, style_id: b.style_id, style_name: b.style_name,
          name: b.name, date_from: b.date_from, date_to: b.date_to,
          status: b.status, created_at: b.created_at, updated_at: b.updated_at,
          finalized_at: b.finalized_at, track_count: b.track_count ?? 0,
        })),
        total: 2,
        limit: 50,
        offset: 0,
      }),
    ),
  );
});

describe('Transfer flow integration', () => {
  it('happy path: row kebab → Transfer → block → bucket → toast', async () => {
    let bodySeen: unknown = null;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', async ({ request }) => {
        bodySeen = await request.json();
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r();

    // Wait for the row to render.
    await screen.findByText('Some Title');

    // Open kebab menu.
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));

    // Click "Transfer to other block…".
    await userEvent.click(
      await screen.findByRole('menuitem', { name: /Transfer to other block/ }),
    );

    // Step 1 — pick Tgt Block.
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));

    // Step 2 — pick NEW bucket.
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => /^NEW/.test(b.textContent ?? ''));
    expect(newBtn).toBeDefined();
    await userEvent.click(newBtn!);

    await waitFor(() => expect(bodySeen).toEqual({ target_bucket_id: 'tgtNEW', track_ids: ['tk1'] }));
    expect(await screen.findByText(/Transferred 1 track to Tgt Block/)).toBeInTheDocument();
  });

  it('empty siblings: shows EmptyState with CTA', async () => {
    server.use(
      http.get('http://localhost/styles/s1/triage/blocks', () =>
        HttpResponse.json({
          items: [{
            id: 'src1', style_id: 's1', style_name: 'House', name: 'Src Block',
            date_from: '2026-04-21', date_to: '2026-04-28',
            status: 'IN_PROGRESS', created_at: '2026-04-21T00:00:00Z',
            updated_at: '2026-04-21T00:00:00Z', finalized_at: null, track_count: 1,
          }],
          total: 1, limit: 50, offset: 0,
        }),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));

    expect(await screen.findByText(/No other in-progress blocks/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Go to triage/ })).toBeInTheDocument();
  });

  it('inactive STAGING bucket disabled in step 2', async () => {
    let posted = false;
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () => {
        posted = true;
        return HttpResponse.json({ transferred: 1 });
      }),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));

    const stagingBtn = screen.getAllByRole('button').find((b) => /Tech \(staging, inactive\)/.test(b.textContent ?? ''));
    expect(stagingBtn).toBeDefined();
    expect(stagingBtn).toBeDisabled();
    await userEvent.click(stagingBtn!);
    expect(posted).toBe(false);
  });

  it('409 invalid_state: red toast, modal closes', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'invalid_state', message: 'finalized' },
          { status: 409 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => /^NEW/.test(b.textContent ?? ''));
    await userEvent.click(newBtn!);

    expect(await screen.findByText(/Target block was finalized/)).toBeInTheDocument();
    // Modal closed → "Pick a bucket" gone.
    await waitFor(() => expect(screen.queryByText(/Pick a bucket in/)).toBeNull());
  });

  it('409 target_bucket_inactive: red toast, modal stays on step 2', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/src1/transfer', () =>
        HttpResponse.json(
          { error_code: 'target_bucket_inactive', message: 'no' },
          { status: 409 },
        ),
      ),
    );

    r();
    await screen.findByText('Some Title');
    await userEvent.click(screen.getByRole('button', { name: /Move track/ }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Transfer to other block/ }));
    await userEvent.click(await screen.findByRole('button', { name: /Tgt Block/ }));
    await waitFor(() => screen.getByText(/Pick a bucket in/));
    const newBtn = screen.getAllByRole('button').find((b) => /^NEW/.test(b.textContent ?? ''));
    await userEvent.click(newBtn!);

    expect(await screen.findByText(/no longer valid/)).toBeInTheDocument();
    expect(screen.getByText(/Pick a bucket in/)).toBeInTheDocument();
  });

  it('FINALIZED src block: Transfer item not exposed', async () => {
    server.use(
      http.get('http://localhost/triage/blocks/src1', () =>
        HttpResponse.json({ ...SRC_BLOCK, status: 'FINALIZED', finalized_at: '2026-04-29T00:00:00Z' }),
      ),
    );

    r();
    await screen.findByText('Some Title');
    // F3a hides the entire kebab when FINALIZED, so the trigger may simply not exist.
    expect(screen.queryByRole('button', { name: /Move track/ })).toBeNull();
    expect(screen.queryByText(/Transfer to other block/)).toBeNull();
  });
});
```

> **Note on selectors:** the integration test relies on the same `^NEW` text match as the component test. If the `BucketCard` rendering of the bucket label uses different whitespace (e.g. a flex layout that separates the type from the count), prefer matching on `aria-label` (`bucketLabel`-formatted, e.g. `aria-label="Move to NEW"`). Tighten as needed during execution; keep the behavioral assertion intact.

- [ ] **Step 3: Run the integration test.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test src/features/triage/__tests__/TransferFlow.integration.test.tsx
```

Expected: green — all 6 tests pass.

- [ ] **Step 4: Commit.**

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add frontend/src/features/triage/__tests__/TransferFlow.integration.test.tsx
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
test(triage): add F3b transfer flow integration test

Exercises kebab → Transfer → modal step 1 → block pick → step 2 → bucket
pick → toast. Covers happy path, empty siblings, inactive bucket
disabled, 409 invalid_state (modal closes), 409 target_bucket_inactive
(modal stays), and FINALIZED src block (entry hidden).
EOF
)"
```

---

## Task 10: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full test suite.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend test
```

Expected: green. Test count should be ≥ 230 (F3a baseline ~205 + ~25 new). Record actual count.

- [ ] **Step 2: Typecheck.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend typecheck
```

Expected: green.

- [ ] **Step 3: Build sanity.**

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend build
```

Expected: green. Bundle size should stay under 700 KB minified — record the new figure and compare against the Task 0 baseline. Acceptable delta: a few KB (icon + small components + small modal). If bundle jumps > 30 KB, investigate (something pulled in unintentionally — likely an unused Mantine subpackage or icon-set).

- [ ] **Step 4: Manual smoke against deployed prod API (per spec §11.4).**

Requires `frontend/.env.local` with `VITE_API_BASE_URL=$(cd infra && terraform output -raw api_endpoint)`. Run:

```bash
pnpm --dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task/frontend dev
```

In a browser:

1. Sign in.
2. Navigate to a style with ≥ 2 IN_PROGRESS triage blocks. If only one, create a second via F2 `+ New triage block`.
3. Open one block → open a bucket with ≥ 1 track → kebab on a track → `Transfer to other block…`.
4. Step 1: confirm only the OTHER block appears (current excluded). Click it.
5. Step 2: confirm bucket grid renders. Click the NEW bucket of the target.
6. Confirm green toast `Transferred 1 track to {block} / NEW`.
7. Open target block → confirm track now appears in NEW bucket.
8. Open source block → confirm track is STILL in the source bucket (snapshot semantics).
9. Edge: open a triage block in a style with no other IN_PROGRESS blocks → confirm modal shows EmptyState + CTA.
10. Edge: target block has an inactive STAGING bucket → confirm dimmed + click no-op.
11. Edge: open a FINALIZED block → confirm `Move track` kebab is hidden entirely.

Record any drift between code and prod behavior in the F3b "lessons learned" roadmap section after merge.

- [ ] **Step 5: Roadmap update commit.**

Edit `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md`:

- Mark F3b row as shipped: change `| **F3b** | Triage transfer (cross-block) ...` to `| ~~**F3b**~~ ✅ **Shipped 2026-05-DD** | Triage transfer (cross-block) ...` with the actual ship date.
- Add a `## Lessons learned (post-F3b, 2026-05-DD)` section at the end (mirror F3a's section) — include any non-obvious findings from the smoke run, plus the drift notes for `TD-9` (OpenAPI description) and `TD-10` (F3a Move error code mismatch — fix in a separate PR).
- Add `TD-9` and `TD-10` rows to the tech-debt table.

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task add docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md
git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/f3b_task commit -m "$(cat <<'EOF'
docs(roadmap): mark F3b shipped, add TD-9 and TD-10

F3b cross-block transfer landed. TD-9 covers the misleading OpenAPI
description on the transfer endpoint (claims source mutation, actually
INSERT-only). TD-10 covers F3a's wrong error_code mapping for
inactive-bucket move 409s — toast falls back to generic in prod.
EOF
)"
```

- [ ] **Step 6: Optional — merge to main.**

Per spec §12 step 5:

```bash
git -C /Users/roman/Projects/clouder-projects/clouder-core checkout main
git -C /Users/roman/Projects/clouder-projects/clouder-core merge feat/triage-transfer --no-ff
# Inspect git log -3 to confirm; only push when smoke is fully green.
```

Push only after manual smoke (Step 4) confirms prod works end-to-end.

---

## Self-Review Checklist (executed against the plan + spec)

**Spec coverage:**
- §2 In scope items → Tasks 1–9 (i18n, hook, modal, components, wiring, integration test).
- §3 Architectural decisions D1–D20 → embedded in tasks 4–7.
- §4 UI Surface → Tasks 4 (BucketGrid mode), 5 (MoveToMenu transfer item), 6 (TransferModal + Step1 + Step2).
- §5 Component catalog → all listed components are created or extended in Tasks 3–7.
- §6 Data Flow → Task 2 (hook with right invalidations), Task 6 (`handleTransferError` reproducing §6.3).
- §7 Validation → Task 6 (filtering siblings; filtering inactive in BucketGrid `mode='select'`).
- §8 Error/empty/loading → Task 6 unit tests + Task 9 integration tests cover all branches.
- §9 Code layout → Tasks 1–8 cover every new and modified file.
- §10 i18n keys → Task 1.
- §11 Testing → Tasks 2–6 (unit + component), Task 9 (integration), Task 10 (manual smoke).
- §12 Delivery → Task 0 (branch rename), per-task commits, Task 10 (final checks + roadmap update).
- §14 Acceptance criteria → cross-checked against Tasks 6 (component-level) and 9 (integration-level).

**Type consistency check:**
- `TransferInput` shape `{targetBlockId, targetBucketId, trackIds, styleId}` — defined in Task 2, used identically in Task 6 (`handlePickBucket`), passed unchanged in Task 9 integration test.
- `TriageBlock` (with `style_id`, `buckets`) — imported from `useTriageBlock.ts:6` in both Task 6 (TransferModal `srcBlock` prop) and Task 7 (BucketDetailPage state).
- `BucketCardMode = 'navigate' | 'select'` — defined in Task 4, re-exported via `BucketGrid.tsx`, used in Task 6 (`mode="select"`).
- `bucketLabel(bucket, t)` — used identically in Tasks 4, 6, 9.
- All toast keys (`triage.transfer.toast.*`) — defined in Task 1, used in Task 6 implementation, asserted in Task 9 integration test.
- Error codes `triage_block_not_found / target_bucket_not_found / bucket_not_found / tracks_not_in_source / invalid_state / target_bucket_inactive / target_block_style_mismatch` — verified against `src/collector/curation/__init__.py` (lines 46–107) and `src/collector/curation/triage_repository.py:393` during Task 1 of brainstorming.

**Placeholder scan:** no TBD / TODO / "implement later" / "similar to" markers. The two "Note:" callouts in Tasks 6 + 9 about fragile selectors are explicit guidance for the implementer, not placeholders.

**Spec gap:** none — every spec section maps to at least one task and one verification step.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-03-F3b-triage-transfer-frontend-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Good fit for F3b since tasks are small and isolated, and F3a shipped 22 tasks via this exact pattern.

**2. Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints for review.

Which approach?

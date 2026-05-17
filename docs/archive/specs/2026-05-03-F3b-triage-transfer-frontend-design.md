# F3b — Triage Cross-Block Transfer Frontend

**Date:** 2026-05-03
**Status:** brainstorm stage — design approved, awaiting implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F3b** (split from F3 per F3a §1).
**Backend prerequisite:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) §5.8 — `POST /triage/blocks/{src_id}/transfer` already shipped to prod.
**Frontend prerequisites:**
- [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — F2 merged 2026-05-03 (provides `useTriageBlocksByStyle`, `byStyle` cache, `TriageBlockRow`).
- [`2026-05-03-F3a-triage-detail-frontend-design.md`](./2026-05-03-F3a-triage-detail-frontend-design.md) — F3a merged 2026-05-03 (provides `MoveToMenu`, `BucketGrid`, `BucketCard`, `BucketDetailPage`, `useTriageBlock`, `useBucketTracks`).

**Successor blockers:** F4 Finalize (independent), F5 Curate (independent), F8 Home (independent).

## 1. Context and Goal

F3a shipped triage block detail + bucket detail + single-track Move within a block. F3b adds **cross-block transfer**: a user picks a track in `BucketDetailPage` and copies it into another `IN_PROGRESS` triage block of the same style, into a chosen non-inactive bucket. Backend (`POST /triage/blocks/{src_id}/transfer`, spec-D §5.8) is a **snapshot operation** — source bucket is not mutated; the track stays in the source AND lands in the target.

After F3b ships, a logged-in user can:

- Open any track in `BucketDetailPage` of an `IN_PROGRESS` block → kebab `MoveToMenu` → click `Transfer to other block…`.
- See a two-step modal: step 1 lists sibling `IN_PROGRESS` blocks of the same style (excluding the current block); step 2 renders the chosen block's `BucketGrid` for bucket selection.
- Click a non-inactive bucket → fire `POST /transfer` → green toast `Transferred 1 track to {block} / {bucket}` → modal closes.
- Source bucket: unchanged (no row removal, no count adjustment).
- Target caches invalidated: `bucketTracks` for target bucket, `blockDetail` for target block, `byStyle` for the style (target `track_count` summary changes).

Out of scope: multi-track / bulk-select (`FUTURE-F3b-1`), Undo (impossible per snapshot semantics), inline create-new-block from modal, cross-style transfer, optimistic target write.

## 2. Scope

**In scope:**

- Extension of `MoveToMenu` (F3a) with a final `Transfer to other block…` item separated by `Menu.Divider`.
- New components: `TransferModal`, `TransferBlockOption`.
- New hook: `useTransferTracks(srcBlockId)` — `useMutation` on `POST /triage/blocks/{src_id}/transfer`.
- Reuse of `useTriageBlocksByStyle(styleId, 'IN_PROGRESS')` (F2) for siblings discovery, with client-side filter excluding the current block.
- Reuse of `useTriageBlock(targetBlockId)` (F3a) for the target bucket grid.
- Extension of `BucketGrid` + `BucketCard` with a `mode: 'navigate' | 'select'` prop. `navigate` is the existing F3a behavior (Link-wrapped); `select` is a new mode that wraps cards in `UnstyledButton` and calls `onSelect(bucket)` instead of navigating.
- New i18n keys under `triage.transfer.*`.
- Vitest unit + integration tests, mirroring F3a conventions.
- Tech-debt entry: `TD-9` — fix `schema.d.ts` description for the transfer endpoint (currently misleading: claims tracks leave the source — they do not).

**Out of scope:**

- **Multi-track / bulk-select.** Backend supports `track_ids` up to 1000; UI ships single-track only. `FUTURE-F3b-1` covers later promotion alongside `FUTURE-F3a-1` (one combined bulk-bar upgrade for Move + Transfer).
- **Undo for transfer.** Snapshot semantics: source unchanged, target gains a row. Honest Undo would need a `DELETE` endpoint on triage bucket membership (not exposed). Skipped; documented in §3 D4.
- **Optimistic target write.** Source unchanged → no visual race on the page the user is on. Optimistic target write is near-useless (target cache is typically cold; new `added_at` unknown so order can flicker).
- **Open-target-bucket link in success toast.** `FUTURE-F3b-2`. User navigates manually via triage list.
- **Inline create-new-block from `TransferModal` empty state.** EmptyState links to `/triage/{styleId}` (triage list) where the existing F2 create flow lives. Embedding create-block in transfer modal would tangle two features for marginal UX gain.
- **New backend endpoint** like `GET /triage/blocks/{src_id}/transfer-targets`. We use the existing `useTriageBlocksByStyle(styleId, 'IN_PROGRESS')` cache.
- **Bulk-from-bucket "Transfer all" affordance.** Same scope rationale as `FUTURE-F3b-1`.
- **Mobile-specific picker variant** (e.g. Drawer instead of Modal). Mantine `Modal` works on both desktop and mobile by default.
- **Source bucket inference UI.** Backend infers source bucket from `(src_block_id, track_id)` automatically — no client-side selection needed.

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Entry point: extend `MoveToMenu`.** Add a single `Menu.Item` `Transfer to other block…` at the end, separated by `Menu.Divider`. New `MoveToMenu` props: `onTransfer?: () => void`, `showTransfer?: boolean`. The pre-existing destination list (intra-block move) stays first. | Brainstorming Q1-A. One mental model per row: "send this track somewhere." Two separate buttons (Q1-B) doubles row affordance for marginal gain. Bucket-level multi-select trigger (Q1-C) requires bulk infra not in scope. Project memory: tap-on-button, not DnD — extending the existing menu is the cheapest tap-shaped affordance. |
| D2 | **Two-step `TransferModal`.** Step 1: list of sibling `IN_PROGRESS` blocks (same style, excluding current), sorted `created_at DESC`. Step 2: `BucketGrid` of the chosen block. Internal state: `useState<'block' \| 'bucket'>('block')` + `useState<string \| null>(null)` for `targetBlockId`. `Back` link on step 2 returns to step 1 without reloading. | Brainstorming Q2-A. Plain list (Q2-B) collapses ~20–40 bucket rows when siblings × buckets multiplies — noisy. Cascading Selects (Q2-C) break visual parity with the rest of triage UI. Tree/accordion (Q2-D) feels heavy for ≤ a handful of siblings. Two steps separate "where" from "which container" decisions cleanly. No `Stepper` component — overkill for 2 steps. |
| D3 | **Single-track scope.** `track_ids: [trackId]` payload. Per-row entry only — no checkbox column, no sticky bar. | Brainstorming Q3-A. Bulk = `FUTURE-F3b-1`, paired with `FUTURE-F3a-1` for one combined upgrade. F3b stays atomic and small. |
| D4 | **Fire-and-toast UX, no optimistic, no Undo.** On bucket click in step 2: fire `POST /transfer`. While pending: bucket cards `disabled`, header loader. On 200: green toast `triage.transfer.toast.transferred`, modal close, target caches invalidated (D9). On error: red toast per error code (D10), modal stays open or closes per case. | Brainstorming Q4-A. Source not mutated → no visual race on current page → no optimistic write needed. Honest Undo would require a delete endpoint we don't have; faking it via a "remove from target" move would create snapshot-semantics confusion. Modal-pick is itself the confirm step. |
| D5 | **Sibling discovery: reuse `useTriageBlocksByStyle(styleId, 'IN_PROGRESS')`.** Client-side filter `block.id !== currentBlockId`. Modal mounts → hook activates; if user navigated from triage list, the cache is warm. `staleTime: 30s` (F2 default) prevents bouncing. | Brainstorming Q5-A. No new endpoint needed; pattern reuse is free. |
| D6 | **Edge: > 50 sibling blocks.** Modal renders a `Load more` button while `hasNextPage`. Clicking calls `fetchNextPage` (already on the infinite-query result). Realistically the user will never have 50 simultaneous IN_PROGRESS blocks in one style, but the edge is closed cheaply. | Defensive completeness; cost is one button + one click handler. |
| D7 | **Step-1 row component: new `TransferBlockOption`.** Renders block name (semibold), date range `{date_from} → {date_to}`, total track count `{n} track(s)`. No status badge (modal already filters to IN_PROGRESS). Full row is an `UnstyledButton` with hover bg + focus ring + 12 px padding. Sort: `created_at DESC` (matches triage list). | Brainstorming Q6 (refined). Reusing F2's `TriageBlockRow` was tempting but rejected: it's wrapped in `<Link>` for navigation and includes a kebab menu — neither applies in modal context. Slim 30-line component is cleaner than a discriminated-mode `TriageBlockRow`. |
| D8 | **Step 2: reuse `BucketGrid` + `BucketCard` with new `mode: 'navigate' \| 'select'` prop (default `navigate`).** In `select` mode: cards wrapped in `UnstyledButton` instead of `<Link>`; `onSelect(bucket)` callback invoked on click. Inactive STAGING: dimmed (existing F3a behavior, opacity 0.5) + `disabled` button (no `onSelect` invoked). Current source bucket is NOT filtered out — backend allows transfer into the same `bucket_type` of a different block (e.g. NEW → NEW of another block is valid). | Brainstorming Q7-A. Visual parity: user sees the same grid in `TriageDetailPage` and inside the modal. `mode` flag is the YAGNI-compliant minimum to avoid duplicating `BucketGrid`. |
| D9 | **`useTransferTracks(srcBlockId)`** = `useMutation`, `mutationKey: ['triage','transfer', srcBlockId]`. No `onMutate` (D4). `onSuccess`: invalidate `['triage','bucketTracks', input.targetBlockId, input.targetBucketId]` + `triageBlockKey(input.targetBlockId)` + `triageBlocksByStyleKey(styleId, *)` for all three `STATUSES` (target `track_count` summary changed). Source caches NOT invalidated (snapshot — source unchanged). | Surgical invalidation; `byStyle` covers list views that show summary counts. |
| D10 | **Error mapping.** From spec-D §5.8 and `triage_repository.py:393` + `curation/__init__.py` (authoritative `error_code` strings): <br>• `404 triage_block_not_found` (src) → red toast `triage.transfer.toast.stale_source` + modal close + invalidate `bucketTracks` (src). <br>• `404 target_bucket_not_found` → red toast `triage.transfer.toast.stale_target` + return to step 1 + invalidate `byStyle`. <br>• `404 tracks_not_in_source` → red toast `triage.transfer.toast.stale_source` + modal close + invalidate `bucketTracks` (src). <br>• `409 invalid_state` (target block not IN_PROGRESS) → red toast `triage.transfer.toast.target_finalized` + modal close + invalidate `byStyle`. <br>• `409 target_bucket_inactive` → red toast `triage.transfer.toast.target_inactive` + STAY on step 2 + invalidate target `triageBlockKey` (the dimmed bucket reflects fresh state). <br>• `409 target_block_style_mismatch` → red toast `triage.transfer.toast.style_mismatch` + modal close (defensive — UI filters by style upstream, should not happen). <br>• `503` terminal → red toast `errors.network` + STAY on step 2 (user can retry). <br><br>**Note on F3a drift:** F3a's `BucketDetailPage` (`routes/BucketDetailPage.tsx:143`) maps `inactive_bucket` instead of the actual `target_bucket_inactive` — latent bug, the toast never fires in prod. Tracked as `TD-10` (separate fix, do NOT touch F3a Move semantics in F3b PR). | All paths invalidate the relevant cache so UI re-converges with server truth. Modal stays on step 2 only for recoverable cases (`target_bucket_inactive`, `503`); other errors are terminal-from-UI. |
| D11 | **FINALIZED src block: `Transfer to…` not exposed.** F3a §3 D10 already hides the entire `MoveToMenu` for FINALIZED blocks (`showMoveMenu` prop). No separate gating needed. The new `showTransfer` prop on `MoveToMenu` defaults to `block.status === 'IN_PROGRESS'`. | Read-only invariant from F3a. |
| D12 | **Empty siblings: EmptyState with CTA to triage list.** When the filtered siblings list is empty, step 1 shows `EmptyState` with title `triage.transfer.empty.no_siblings_title`, body `triage.transfer.empty.no_siblings_body`, and an `<Anchor component={Link} to={`/triage/${styleId}`}>` CTA `triage.transfer.empty.no_siblings_cta`. | Natural fallback. Inline create-new-block from modal is `FUTURE-F3b-3`. |
| D13 | **Cold-start UX.** Reads (`useTriageBlocksByStyle`, `useTriageBlock(target)`) rely on existing `apiClient` cold-start retry. Transfer mutation on terminal 503 → red toast, no auto-recover (mirror F3a D15). | Idempotency-key concern is N/A on read; transfer on 503 is rare and manual retry is one click on the same bucket card. |
| D14 | **No `Stepper` component.** Local `useState<'block' \| 'bucket'>` plus `useState<string \| null>` for `targetBlockId`. Modal title and body branch on the step. `Back` is a plain `Anchor`. Reset on close. | YAGNI. Mantine `Stepper` is for multi-step forms with progress dots; we have two view-states, not a flow. |
| D15 | **`TransferModal` mounts only when triggered.** `BucketDetailPage` holds `[transferTrackId, setTransferTrackId] = useState<string \| null>(null)`. `null` = closed; non-null = open with the chosen track id. `MoveToMenu.onTransfer = () => setTransferTrackId(track.id)`. `TransferModal.onClose = () => setTransferTrackId(null)`. | Simpler than a global modal context; matches F2 `CreateTriageBlockDialog` mounting pattern. |
| D16 | **No `BucketGrid` test regression.** Existing F3a tests for `BucketGrid` use `mode='navigate'` implicitly (default). New `mode='select'` tests live in `TransferModal.test.tsx` — `BucketGrid.test.tsx` gains one new test asserting that default mode = navigate (regression guard). | Backwards compatibility: F3a callers do not pass `mode`. |
| D17 | **PR shape.** Single PR `feat/triage-transfer` from `main` (worktree `f3b_task` already exists). Sequential caveman-commits per natural boundary, merge `--no-ff`. Mirror F3a D22. | Solo dev workflow consistent with F1 + F2 + F3a. |
| D18 | **Bundle additions: zero new deps.** Mantine `Modal` already shipped (used by `CreateTriageBlockDialog` in F2). `IconArrowsExchange` from `@tabler/icons-react` is already in the dep tree; one new re-export in `frontend/src/components/icons.ts`. | Bundle stays under 700 KB minified target. |
| D19 | **Source bucket inference is implicit.** Backend `transfer_tracks` selects the source bucket internally by joining on `triage_bucket_tracks.track_id` within the src block (`triage_repository.py:461`). The client only sends `target_bucket_id` + `track_ids` — never `from_bucket_id`. The trigger row on the frontend already lives in a known bucket, but we don't pass that information. | Matches spec-D §5.8 payload shape `TransferTracksIn = { target_bucket_id, track_ids }`. |
| D20 | **OpenAPI description drift.** `frontend/src/api/schema.d.ts:2492` describes the endpoint as "Tracks leave the source block entirely" — this is INCORRECT; spec-D §5.8 ("Source is not mutated") and `triage_repository.py:393` (INSERT-only, no DELETE) are authoritative. Roadmap gets a new `TD-9` to fix the OpenAPI description. F3b ships against actual semantics: source unchanged. | Documenting the contradiction so future contributors and code-reviewers don't re-introduce the bug based on the misleading docstring. |

## 4. UI Surface

### 4.1 Modified `MoveToMenu`

```tsx
interface MoveToMenuProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  onMove: (toBucket: TriageBucket) => void;
  onTransfer?: () => void;          // NEW
  showTransfer?: boolean;           // NEW — true when block.status === 'IN_PROGRESS'
  disabled?: boolean;
}

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
    {showTransfer && onTransfer && (
      <>
        <Menu.Divider />
        <Menu.Item leftSection={<IconArrowsExchange size={14} />} onClick={onTransfer}>
          {t('triage.transfer.menu_item')}
        </Menu.Item>
      </>
    )}
  </Menu.Dropdown>
</Menu>
```

If `destinations.length === 0 && !showTransfer` → trigger renders disabled (existing F3a behavior). If `destinations.length === 0 && showTransfer` → trigger renders enabled, dropdown shows only the transfer item (no `Menu.Label` `Move to` since there are no move destinations — branch the label render).

### 4.2 `TransferModal`

```tsx
interface TransferModalProps {
  opened: boolean;
  onClose: () => void;
  srcBlock: TriageBlock;
  trackId: string;
  styleId: string;
}

function TransferModal({ opened, onClose, srcBlock, trackId, styleId }: TransferModalProps) {
  const { t } = useTranslation();
  const [step, setStep] = useState<'block' | 'bucket'>('block');
  const [targetBlockId, setTargetBlockId] = useState<string | null>(null);

  const siblingsQuery = useTriageBlocksByStyle(styleId, 'IN_PROGRESS');
  const siblings = (siblingsQuery.data?.pages ?? [])
    .flatMap((p) => p.items)
    .filter((b) => b.id !== srcBlock.id);

  const targetBlockQuery = useTriageBlock(targetBlockId ?? '');
  const transfer = useTransferTracks(srcBlock.id);

  const reset = () => { setStep('block'); setTargetBlockId(null); };
  const handleClose = () => { reset(); onClose(); };

  const handlePickBlock = (id: string) => { setTargetBlockId(id); setStep('bucket'); };
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
        onError: (err) => handleTransferError(err, /* see D10 */),
      },
    );
  };

  return (
    <Modal opened={opened} onClose={handleClose} size="lg"
      title={step === 'block'
        ? t('triage.transfer.modal.title_pick_block')
        : t('triage.transfer.modal.title_pick_bucket', { block_name: targetBlockQuery.data?.name ?? '' })
      }>
      {step === 'block' && /* see §4.3 */}
      {step === 'bucket' && /* see §4.4 */}
    </Modal>
  );
}
```

`handleTransferError` is a small helper that branches on `ApiError.code` per D10 and dispatches the right toast + invalidation + modal-state transition (close vs stay-on-step-2 vs return-to-step-1).

### 4.3 Step 1 — block picker

```tsx
{siblingsQuery.isLoading && <Center><Loader /></Center>}

{!siblingsQuery.isLoading && siblings.length === 0 && (
  <EmptyState
    title={t('triage.transfer.empty.no_siblings_title')}
    body={t('triage.transfer.empty.no_siblings_body')}
    action={
      <Anchor component={Link} to={`/triage/${styleId}`} onClick={handleClose}>
        {t('triage.transfer.empty.no_siblings_cta')}
      </Anchor>
    }
  />
)}

{!siblingsQuery.isLoading && siblings.length > 0 && (
  <Stack gap="sm">
    {siblings.map((b) => (
      <TransferBlockOption key={b.id} block={b} onSelect={() => handlePickBlock(b.id)} />
    ))}
    {siblingsQuery.hasNextPage && (
      <Button variant="subtle" loading={siblingsQuery.isFetchingNextPage}
        onClick={() => siblingsQuery.fetchNextPage()}>
        {t('triage.transfer.modal.load_more')}
      </Button>
    )}
  </Stack>
)}
```

### 4.4 Step 2 — bucket picker

```tsx
<Stack gap="md">
  <Group gap="xs">
    <Anchor component="button" onClick={() => setStep('block')}>
      {t('triage.transfer.modal.back')}
    </Anchor>
  </Group>

  {targetBlockQuery.isLoading && <Center><Loader /></Center>}

  {targetBlockQuery.isError && /* D10: target 404 — handled by error effect, return to step 1 */}

  {targetBlockQuery.data && (
    <BucketGrid
      buckets={targetBlockQuery.data.buckets}
      cols={{ base: 1, xs: 2 }}
      mode="select"
      onSelect={handlePickBucket}
      disabled={transfer.isPending}
    />
  )}
</Stack>
```

`BucketGrid` (existing F3a component) receives the new `mode` + `onSelect` + `disabled` props. The `disabled` flag (passed during `transfer.isPending`) renders all cards as `disabled` (no click) and shows an inline `<Loader size="sm"/>` next to the modal title or as an overlay — implementation detail, not load-bearing.

### 4.5 `TransferBlockOption`

```tsx
interface TransferBlockOptionProps {
  block: TriageBlockSummary;
  onSelect: () => void;
}

function TransferBlockOption({ block, onSelect }: TransferBlockOptionProps) {
  const { t } = useTranslation();
  return (
    <UnstyledButton
      onClick={onSelect}
      style={{
        display: 'block',
        width: '100%',
        padding: 'var(--mantine-spacing-md)',
        border: '1px solid var(--color-border)',
        borderRadius: 'var(--radius-md)',
      }}
      // hover/focus styles via CSS module or Mantine theme
    >
      <Stack gap={2}>
        <Text fw={600}>{block.name}</Text>
        <Text size="sm" c="dimmed">
          {block.date_from} → {block.date_to} · {t('triage.transfer.modal.track_count', { count: block.track_count })}
        </Text>
      </Stack>
    </UnstyledButton>
  );
}
```

### 4.6 State summary for `BucketDetailPage`

```tsx
const [transferTrackId, setTransferTrackId] = useState<string | null>(null);

// In handler passed to BucketTracksList → BucketTrackRow → MoveToMenu:
const handleTransfer = (trackId: string) => setTransferTrackId(trackId);

// After block + bucket loaded:
return (
  <Stack gap="lg">
    {/* existing UI */}
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

## 5. Component Catalog

| Component | Anatomy | Mantine base | Owner |
|---|---|---|---|
| `TransferModal` | Modal with two-step internal state; step 1 = block picker; step 2 = bucket grid + Back | `Modal`, `Stack`, `Anchor`, `Loader` | F3b (NEW) |
| `TransferBlockOption` | Button-row showing block name + date + count | `UnstyledButton`, `Stack`, `Text` | F3b (NEW) |
| `MoveToMenu` (modified) | Existing F3a menu + `Menu.Divider` + transfer item | `Menu` | F3a → F3b extends |
| `BucketGrid` (modified) | Existing F3a grid + `mode` prop | `SimpleGrid` | F3a → F3b extends |
| `BucketCard` (modified) | Existing F3a card + `mode='select'` branch (UnstyledButton wrapper, disabled when inactive or `disabled` prop) | `Card` | F3a → F3b extends |
| `BucketTrackRow` (modified) | New optional `onTransfer?: () => void` prop, propagated to `MoveToMenu` | `Table.Tr` / `Card` | F3a → F3b extends |
| `BucketTracksList` (modified) | New optional `onTransfer?: (trackId: string) => void` prop, threaded to each `BucketTrackRow` | `Table` / `Stack` | F3a → F3b extends |
| `EmptyState` | Existing — reuse for empty siblings | — | reused |

## 6. Data Flow

### 6.1 React-query keys

No new keys. Reuse:

```ts
['triage', 'byStyle', styleId, status]            // F2 — siblings discovery
['triage', 'blockDetail', blockId]                // F3a — target bucket grid
['triage', 'bucketTracks', blockId, bucketId, search]  // F3a — invalidated on success
```

### 6.2 Hook `useTransferTracks`

```ts
import {
  useMutation,
  useQueryClient,
  type UseMutationResult,
} from '@tanstack/react-query';
import { api } from '../../../api/client';
import { ApiError } from '../../../api/error';
import { triageBlockKey } from './useTriageBlock';
import { triageBlocksByStyleKey, type TriageStatus } from './useTriageBlocksByStyle';

export interface TransferInput {
  targetBlockId: string;
  targetBucketId: string;
  trackIds: string[];           // single-element in F3b
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

No `onMutate` (D4). No source invalidation (snapshot — source unchanged).

### 6.3 Error handling effect

```ts
function handleTransferError(
  err: ApiError | unknown,
  ctx: { qc: QueryClient; styleId: string; srcBlockId: string; targetBlockId: string | null;
         setStep: (s: 'block' | 'bucket') => void; close: () => void; t: TFunction },
): void {
  const code = err instanceof ApiError ? err.code : 'unknown';
  let toastKey = 'triage.transfer.toast.error';
  let next: 'close' | 'step1' | 'stay' = 'close';

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
      // network/503/unknown
      toastKey = 'errors.network';
      next = 'stay';
  }

  notifications.show({ color: 'red', message: ctx.t(toastKey) });
  if (next === 'close') ctx.close();
  else if (next === 'step1') ctx.setStep('block');
  // 'stay' → no-op
}
```

### 6.4 Mounting mechanics

`TransferModal` is conditionally rendered by `BucketDetailPage`. Internal state (`step`, `targetBlockId`) lives in the modal and resets on close (D14). The `siblings` and `targetBlock` queries follow standard react-query lifecycle — they activate on mount and stay cached after close (`gcTime` defaults; `staleTime: 30s` for `useTriageBlock`, default for `useTriageBlocksByStyle`).

## 7. Validation

No forms. Client-side validation only:

- **Sibling filtering** (D5): `block.id !== srcBlockId` enforced before render.
- **Bucket filtering** (D8): `inactive` STAGING rendered as `disabled`; backend defends with 409 anyway.
- **Empty target block id** (defensive): `useTriageBlock(targetBlockId ?? '')` — pass `''` while step is `'block'`; F3a hook has `enabled: !!id` (verified at `useTriageBlock.ts:27`), so the query stays idle until `targetBlockId` is set.

No Zod schemas needed.

## 8. Error / Empty / Loading UX Mapping

| State | Surface | UX |
|---|---|---|
| Modal open, siblings loading | step 1 | Centered `Loader`. |
| Modal open, siblings empty | step 1 | `EmptyState` with CTA `Anchor` to `/triage/{styleId}`. Closes modal on click. |
| Modal open, siblings 503 | step 1 | `apiClient` retry; on terminal failure, EmptyState `errors.service_unavailable` + Retry button (calls `siblingsQuery.refetch()`). |
| Step 1, block picker happy | step 1 | List rendered; click → step 2. |
| Step 2, target block loading | step 2 | Centered `Loader` (target block summary in `byStyle` is summary-only; `useTriageBlock` fetches buckets — first hit may be a network call). |
| Step 2, target block 404 (race) | step 2 | Auto-handled by error effect: red toast `stale_target`, `setStep('block')`, invalidate `byStyle`. |
| Step 2, transfer pending | step 2 | Bucket cards `disabled` (`disabled={transfer.isPending}` on `BucketGrid`); inline `Loader` near title. |
| Transfer 200 OK | toast | Green `triage.transfer.toast.transferred` (count + block + bucket). Modal closes. Target caches invalidated (D9). |
| Transfer 404 src (`triage_block_not_found` / `tracks_not_in_source`) | toast | Red `stale_source`. Modal closes. Source `bucketTracks` invalidated. |
| Transfer 404 target (`bucket_not_found`) | toast | Red `stale_target`. Return to step 1. `byStyle` invalidated. |
| Transfer 409 `invalid_state` (target finalized) | toast | Red `target_finalized`. Modal closes. `byStyle` invalidated. |
| Transfer 409 `target_bucket_inactive` | toast | Red `target_inactive`. Stay on step 2. Target `triageBlockKey` invalidated → grid re-renders with bucket dimmed. |
| Transfer 409 `target_block_style_mismatch` | toast | Red `style_mismatch`. Modal closes. (Defensive — UI prefilters by style.) |
| Transfer 503 terminal | toast | Red `errors.network`. Stay on step 2 (user can retry by clicking another bucket card or the same one). |
| FINALIZED src block | menu | `Transfer to…` item not rendered (F3a `MoveToMenu` already hidden via `showMoveMenu={false}`). |

## 9. Code Layout

### 9.1 New files

```
frontend/src/features/triage/
├── components/
│   ├── TransferModal.tsx                      # NEW
│   ├── TransferBlockOption.tsx                # NEW
│   └── __tests__/
│       ├── TransferModal.test.tsx             # NEW
│       └── TransferBlockOption.test.tsx       # NEW
├── hooks/
│   ├── useTransferTracks.ts                   # NEW
│   └── __tests__/
│       └── useTransferTracks.test.tsx         # NEW
└── __tests__/
    └── TransferFlow.integration.test.tsx      # NEW
```

### 9.2 Modified files

- `frontend/src/features/triage/components/MoveToMenu.tsx` — add `onTransfer?` + `showTransfer?` props; render `Menu.Divider` + transfer `Menu.Item` when both truthy. Default both falsy → existing F3a behavior unchanged.
- `frontend/src/features/triage/components/BucketGrid.tsx` — add `mode?: 'navigate' | 'select'` (default `'navigate'`), `onSelect?: (bucket: TriageBucket) => void`, `disabled?: boolean`, optional `cols?: SimpleGridProps['cols']` if not already present. Forward to `BucketCard`.
- `frontend/src/features/triage/components/BucketCard.tsx` — branch on `mode`:
  - `navigate` (existing): `<Card component={Link} to={...}>`.
  - `select`: `<Card component={UnstyledButton} onClick={() => onSelect(bucket)} disabled={disabled || bucket.inactive}>`.
- `frontend/src/features/triage/components/BucketTracksList.tsx` — add `onTransfer?: (trackId: string) => void` prop; forward to each `BucketTrackRow`.
- `frontend/src/features/triage/components/BucketTrackRow.tsx` — add `onTransfer?: () => void` prop; pass to `MoveToMenu` along with `showTransfer={block.status === 'IN_PROGRESS'}`.
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — add `useState<string | null>` for `transferTrackId`; pass `handleTransfer` down to `BucketTracksList`; conditionally render `<TransferModal>`.
- `frontend/src/features/triage/index.ts` — re-export `TransferModal`, `useTransferTracks`.
- `frontend/src/components/icons.ts` — add `IconArrowsExchange` re-export.
- `frontend/src/i18n/en.json` — add `triage.transfer.*` namespace (§10).

### 9.3 No backend changes

Endpoint exists (spec-D §5.8). `schema.d.ts` already has `TransferTracksIn` + path. No `pnpm api:types` run needed.

### 9.4 Tech debt entries

- **`TD-9`: OpenAPI description for `/triage/blocks/{src_id}/transfer` is wrong.** Description claims tracks leave the source — they do not. Fix by updating either the FastAPI route docstring or `scripts/generate_openapi.py:ROUTES` (whichever sources that string), regenerating `docs/openapi.yaml`, and re-running `pnpm api:types` to refresh `schema.d.ts`. Add to the roadmap.
- **`TD-10`: F3a `BucketDetailPage` Move error mapping uses wrong code.** `routes/BucketDetailPage.tsx:143` checks `code === 'inactive_bucket'`, but backend `InactiveBucketError.error_code = 'target_bucket_inactive'` (`curation/__init__.py:74`). The "invalid target" toast never fires in prod for inactive-bucket move 409s — falls back to generic `triage.move.toast.error`. Fix in a separate PR (do NOT bundle with F3b to keep blast radius minimal). Tests in F3a's `useMoveTracks.test.tsx:106` and `BucketDetailPage.integration.test.tsx:153` use the wrong mocked code, masking the bug.

## 10. i18n Keys

```json
{
  "triage": {
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

Pluralization via i18next ICU (`_one` / `_other`). RU bundle = iter-2b.

## 11. Testing

### 11.1 Unit (Vitest + Testing Library)

`features/triage/components/__tests__/MoveToMenu.test.tsx` (extend existing):
- `showTransfer={true} + onTransfer` → transfer item visible after divider; click triggers `onTransfer`.
- `showTransfer={false}` → no transfer item, no divider.
- `showTransfer={true}` + empty `destinations` → menu opens, shows only transfer item (no `Move to` label or empty label).

`features/triage/components/__tests__/BucketGrid.test.tsx` (extend):
- New regression test: default `mode` is `'navigate'` (cards wrapped in `Link`).
- `mode='select'` + `onSelect` → cards render as buttons; click on active bucket invokes `onSelect(bucket)`.
- `mode='select'` + inactive bucket → button `disabled`, click no-op.
- `disabled={true}` (transfer pending) → all buttons `disabled`.

`features/triage/components/__tests__/TransferBlockOption.test.tsx`:
- Renders block name (semibold), date range, track count (correct singular/plural).
- Click triggers `onSelect`.
- Keyboard activation (Enter / Space) triggers `onSelect`.

`features/triage/components/__tests__/TransferModal.test.tsx`:
- Initial render → step 1, siblings list (current block excluded, sort `created_at DESC`).
- Empty siblings → EmptyState with CTA Anchor.
- Click block → step 2 with `BucketGrid` (mocked `useTriageBlock` for target).
- Step 2 `Back` link → step 1, no reload of siblings (cache hit).
- Click bucket → `useTransferTracks.mutate` called with `{targetBlockId, targetBucketId, trackIds, styleId}`.
- Modal close (close button or onClose) → resets `step` and `targetBlockId`.
- Load-more button visible when `hasNextPage`; click → `fetchNextPage` triggered.

`features/triage/hooks/__tests__/useTransferTracks.test.tsx`:
- Happy 200 → `transferred: N` returned; correct invalidations fired (`bucketTracks` target, `blockDetail` target, `byStyle` for all 3 statuses).
- 404 / 409 / 503 → mutation rejects with `ApiError`; no source invalidation.

### 11.2 Integration (Vitest + MSW) — `TransferFlow.integration.test.tsx`

Mounted under `BucketDetailPage` with `MemoryRouter`.

1. **Happy path.** Mock siblings (2 IN_PROGRESS in same style + current). Open kebab → click `Transfer to other block…` → modal opens on step 1, current block excluded, 2 rows. Click first → step 2 with bucket grid (mocked `useTriageBlock` for target). Click NEW bucket → POST `/transfer` with right payload → green toast → modal closes. Source `bucketTracks` cache untouched (track count unchanged on source page). Target invalidations fired (verify by re-render counter or `qc.getQueryState`).
2. **Empty siblings.** Mock siblings = only current block. Open modal → EmptyState with CTA Anchor visible. Click CTA → modal disappears from DOM (assertion covers both `handleClose` and the `<Link>` navigation that unmounts the page).
3. **Back navigation preserves state.** Step 1 → click block → step 2 → click `Back` → step 1, siblings list rendered without re-fetch (assert via MSW handler call counter).
4. **Inactive STAGING bucket disabled.** Mock target block with one inactive STAGING. Step 2 → inactive card visually dimmed (assert opacity class) and `aria-disabled` / `disabled` attr; click → no `transfer.mutate` call.
5. **409 `invalid_state` (target finalized).** Mock 409 with `error_code: 'invalid_state'` on POST → red toast `target_finalized` + modal closes + `byStyle` invalidated (verify next siblings query refetches when modal re-opens).
6. **409 `target_bucket_inactive`.** Mock 409 with `error_code: 'target_bucket_inactive'` → red toast `target_inactive` + modal stays on step 2 + target `triageBlockKey` invalidated. Subsequent click on a different (active) bucket succeeds.
7. **404 `tracks_not_in_source`.** Mock 404 with `error_code: 'tracks_not_in_source'` → red toast `stale_source` + modal closes + source `bucketTracks` invalidated.
8. **404 `bucket_not_found` (target race).** Mock 404 on POST → red toast `stale_target` + return to step 1 + `byStyle` invalidated.
9. **FINALIZED src block.** Mock src block.status=FINALIZED → kebab/menu absent on rows (existing F3a behavior); transfer item never reachable. Sanity assertion: `Transfer to other block…` not present in DOM.
10. **Load-more siblings.** Mock 60 IN_PROGRESS blocks (page=50). Step 1 → 50 rows + `Load more`. Click → 10 more rows fetched and rendered.
11. **503 terminal on transfer.** Mock 503 (after retry) → red toast `errors.network` + modal stays on step 2. Click bucket again → second POST attempt.

### 11.3 Test infra (mirror F3a)

- `notifications.clean()` in `beforeEach` and `afterEach` (F2 lesson 20).
- `gcTime: Infinity` on test QueryClient (F2 lesson 6).
- `notifyManager.setScheduler(queueMicrotask)` already in `setup.ts` (A2).
- `NODE_OPTIONS=--no-experimental-webstorage` in test scripts (F1).
- Mantine `Modal` `transitionProps={{ duration: 0 }}` in test theme (verify; if missing, add — same workaround as F2 `Menu`).
- All five jsdom shims in `setup.ts` already in place (F2 lesson 16).
- MSW handlers for `GET /styles/{styleId}/triage/blocks?status=IN_PROGRESS`, `GET /triage/blocks/{id}`, `POST /triage/blocks/{src_id}/transfer`.

### 11.4 Smoke (manual pre-merge)

1. Sign in → triage → pick a style with ≥ 2 IN_PROGRESS blocks. If none, create a second block via F2 `CreateTriageBlockDialog`.
2. Open one block → open a bucket with tracks → kebab on a track → `Transfer to other block…`.
3. Modal: step 1 shows the other block. Click → step 2 grid renders.
4. Click NEW bucket of target → green toast.
5. Open target block → confirm the track now appears in NEW. Open source block → confirm the track is STILL in the source bucket (snapshot semantics).
6. Edge: open a block whose style has only that block IN_PROGRESS → `Transfer…` opens modal with empty state.
7. Edge: in a block with an inactive STAGING in target → that bucket renders dimmed and click is no-op.
8. FINALIZED block → confirm `Transfer…` item is unreachable (entire `MoveToMenu` is hidden).

### 11.5 Coverage target

~25 new tests. Existing F1 + F2 + F3a baseline ~205 tests → after F3b ~230. `pnpm test` green, `pnpm typecheck` green, `pnpm build` < 700 KB.

## 12. Delivery

1. Branch `feat/triage-transfer` from `main` (worktree `f3b_task` already exists).
2. Sequential commits per natural boundary, all messages from `caveman:caveman-commit`:
   - `useTransferTracks` hook + tests
   - `TransferBlockOption` component + tests
   - `BucketGrid` / `BucketCard` `mode='select'` extension + regression tests
   - `MoveToMenu` `onTransfer` / `showTransfer` props + tests
   - `TransferModal` component + tests
   - `BucketTracksList` / `BucketTrackRow` / `BucketDetailPage` wiring
   - i18n keys
   - integration tests (`TransferFlow.integration.test.tsx`)
   - icon re-export, `index.ts` re-exports
3. `pnpm test` green, `pnpm typecheck` green, `pnpm build` green.
4. `pnpm dev` manual smoke against deployed prod API (§11.4).
5. `git checkout main && git merge feat/triage-transfer --no-ff && git push origin main`.
6. Roadmap update: mark F3b shipped, append F3b lessons section, add `TD-9` entry.

CI runs on push to `main`.

## 13. Open Items, Edge Cases, Future Flags

### 13.1 Edge cases worth a comment

- **Concurrent transfers from the same row.** User opens transfer modal, picks bucket, mutation in flight, picks ANOTHER bucket. Solution: `BucketGrid disabled={transfer.isPending}` blocks all clicks on step 2 until mutation resolves. Test 11 in §11.2 partially covers via 503 retry.
- **Modal opened, user navigates away in another tab.** Modal stays mounted in current tab (it's local React state). Underlying queries may fetch fresh data via tab-focus refetch. Acceptable.
- **Target block soft-deleted between step 1 and step 2 click.** `useTriageBlock(targetBlockId)` in step 2 returns 404 → handled by error effect in modal: red toast `stale_target` + `setStep('block')` + `byStyle` invalidate. Step 1 list refreshes.
- **Source block soft-deleted while modal open.** User navigates from `BucketDetailPage` already gates on src block presence; modal can't reach this state without the parent route boundary firing. Defensive: 404 on POST handled per D10.
- **Style change of target block.** Backend prevents (`style_mismatch` 409). Defensive in UI but should not happen — siblings list filters by `styleId`. Toast covers it.
- **Track soft-deleted between row click and bucket click.** Backend returns `tracks_not_in_source` 404 → red toast + modal closes + invalidate src.
- **Transferring into the source's same bucket-type of another block** (e.g. NEW → NEW). Allowed by backend, allowed by D8. `BucketGrid` does NOT filter by bucket type — every active bucket is a valid target.
- **Re-opening modal after success.** Internal state was reset on close (D14). Step starts at `'block'`, `targetBlockId` is `null`. Sibling cache may have been invalidated and refetched; that's fine.
- **`useTriageBlock` returns stale cache on step 2.** With `staleTime: 30s` (F3a) the target buckets may be slightly out of date. Inactive states reflect server truth on next refetch. Acceptable; 409 path covers the race.
- **Translation pluralization.** `transferred_one` / `transferred_other` keys exist; F3b sends `count: 1` always, but the future-bulk upgrade just changes the call site, not the keys.
- **Modal close mid-mutation.** User clicks the X button while transfer is pending. Mutation continues in background; on success/error, toast still fires. Modal already closed → no UI thrash. `onSuccess` invalidations fire normally. Acceptable; documented but not specially-handled.
- **Empty siblings → EmptyState CTA click.** CTA navigates to `/triage/{styleId}` (Anchor with `component={Link}`). We close the modal first via `onClick={handleClose}` to avoid stuck-modal-on-back. Ordering: `handleClose` runs first, then router navigation.

### 13.2 Future flags (post iter-2a)

- **`FUTURE-F3b-1`** — bulk-select + cross-block transfer. Combine with `FUTURE-F3a-1` for one bulk-bar upgrade across move + transfer.
- **`FUTURE-F3b-2`** — `Open target` link in success toast that navigates to `/triage/{styleId}/{targetBlockId}/buckets/{targetBucketId}`.
- **`FUTURE-F3b-3`** — inline create-new-block from the empty-siblings state (saves a navigation hop when the user has only one block).
- **`FUTURE-F3b-4`** — keyboard navigation through the bucket grid in step 2 (arrow keys + Enter). Out-of-scope for F3b; Curate (F5) is the keyboard surface.
- **`FUTURE-F3b-5`** — search box for siblings list when block count grows beyond ~10. Realistic only after long-running usage; not necessary today.

### 13.3 Cross-ticket dependencies

- **F4 Finalize** is independent. Finalize-blocked-by-inactive-buckets path may push users toward Transfer ("move tracks out then finalize") — but the `Transfer to…` affordance is always available regardless of F4 state.
- **F5 Curate** is independent. Curate operates on a single block (move via destination buttons); Transfer is a per-row escape hatch only.
- **F8 Home** does not consume Transfer specifically; it composes `byStyle` summaries which Transfer's `onSuccess` invalidates.

## 14. Acceptance Criteria

- `MoveToMenu` shows `Transfer to other block…` item (with leading divider) when `block.status === 'IN_PROGRESS'`.
- Click `Transfer to other block…` → `TransferModal` opens at step 1.
- Step 1 lists sibling `IN_PROGRESS` blocks of the same style (excluding current), sorted `created_at DESC`. Current block excluded. Each row shows name + date range + track count (singular/plural). Current bucket NOT filtered out from step 2 (cross-block same-type transfer allowed).
- Empty siblings → EmptyState with CTA link to `/triage/{styleId}` (closes modal on click).
- `Load more` button appears when `hasNextPage`; click loads next page.
- Click sibling block row → step 2, `BucketGrid` of target block renders (with `useTriageBlock(targetBlockId)`).
- Step 2 `Back` link → step 1; siblings preserved.
- Active bucket card click → POST `/transfer` with `{target_bucket_id, track_ids: [trackId]}` → on 200, green toast `Transferred 1 track to {block} / {bucket}` + modal close + invalidate target `bucketTracks`, target `blockDetail`, all `byStyle` for the style.
- Source bucket cache and source `blockDetail` are NOT invalidated (snapshot — source unchanged).
- Inactive STAGING bucket in step 2: dimmed + disabled; click is no-op.
- All error branches per §6.3 / §8 land the right toast + state transition + cache invalidation.
- FINALIZED src block: `Transfer to…` item is unreachable (existing F3a `MoveToMenu` invariant).
- 0 new dependencies. Bundle stays under 700 KB minified.
- `pnpm test`, `pnpm typecheck`, `pnpm build` all green. ~25 new tests, total ≥ 230.
- Manual smoke (§11.4) green against deployed prod API.

## 15. References

- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket F3b.
- Backend prereq: [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) §5.8 (transfer endpoint, error codes) + §6 (`transfer_tracks` repository signature).
- F2 prereq: [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — `useTriageBlocksByStyle`, `byStyle` cache, `TriageBlockSummary` shape.
- F3a prereq: [`2026-05-03-F3a-triage-detail-frontend-design.md`](./2026-05-03-F3a-triage-detail-frontend-design.md) — `MoveToMenu`, `BucketGrid`, `BucketCard`, `BucketDetailPage`, `useTriageBlock`, `useBucketTracks`, error-mapping pattern.
- Frontend bootstrap: [`2026-04-30-frontend-bootstrap-design.md`](./2026-04-30-frontend-bootstrap-design.md).
- Pages catalog Pass 1: `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` — P-19 Transfer (visual reference).
- Component spec sheet: `docs/design_handoff/04 Component spec sheet.html`.
- API contract: `docs/openapi.yaml` path `/triage/blocks/{src_id}/transfer`. Request shape `TransferTracksIn = { target_bucket_id, track_ids[] }` (≤ 1000). Response `{ transferred: int, correlation_id }`. **Note:** description text is misleading (claims source mutation); spec-D and `triage_repository.py:393` are authoritative — source is NOT mutated. Tracked as `TD-9`.
- Project memory: `tap-on-button, not DnD` (motivates D1 + D4 — single tap → modal, no drag).
- Tokens: `docs/design_handoff/tokens.css`, `frontend/src/tokens.css`, `frontend/src/theme.ts`.

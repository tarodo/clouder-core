# F4 — Triage Finalize Frontend

**Date:** 2026-05-03
**Status:** brainstorm stage — design awaiting user approval before implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F4**.
**Backend prerequisite:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) §5.9 — `POST /triage/blocks/{id}/finalize` shipped to prod (verified live via the spec-D backend hotfix landed 2026-05-03 alongside F3a).
**Frontend prerequisites:**

- [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — F2 merged 2026-05-03 (provides `useTriageBlocksByStyle`, `byStyle` cache, `pendingCreateRecovery` scheduler).
- [`2026-05-03-F3a-triage-detail-frontend-design.md`](./2026-05-03-F3a-triage-detail-frontend-design.md) — F3a merged 2026-05-03 (provides `MoveToMenu`, `BucketGrid`, `BucketCard`, `BucketDetailPage`, `useTriageBlock`).
- [`2026-05-03-F3b-triage-transfer-frontend-design.md`](./2026-05-03-F3b-triage-transfer-frontend-design.md) — F3b merged 2026-05-03 (provides `TransferModal`, `useTransferTracks`, single-track transfer flow).

**Successor blockers:** F5 Curate (independent), F8 Home (consumes `byStyle` summary counts which finalize updates).

## 1. Context and Goal

After F3a + F3b a user can browse triage blocks, move tracks intra-block, transfer single tracks cross-block. F4 closes the triage loop by adding **finalize**: promote every STAGING bucket's tracks into the linked `clouder_categories.category_tracks` rows in one atomic Aurora transaction (spec-D §5.9), flipping the block to `FINALIZED`.

A finalized block is read-only EXCEPT for one explicit escape hatch: the **technical buckets** (`NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED`) of a finalized block remain transferable into another `IN_PROGRESS` block of the same style. The user motivation: technical buckets are a historical sorting record but stay valuable as a source — e.g. carrying forward a `NOT` bucket from a finalized week into the next week's `NOT` bucket without re-curating. STAGING buckets in a finalized block stay strictly read-only because their content is already promoted into the corresponding category and re-transferring would be misleading.

After F4 ships, a logged-in user can:

- Open `TriageDetailPage` of an `IN_PROGRESS` block → click `Finalize` → see a pre-flight modal listing every active STAGING bucket with its category name + track count and an aggregate total → confirm → block flips to `FINALIZED`, green toast `Finalized {block.name} · promoted N tracks across M categories.`
- If any inactive STAGING bucket holds tracks → modal renders a **blocker view** instead of confirm: per-bucket row `{deleted_category_name} · {n} tracks` with `Open` link to that `BucketDetailPage`. `Finalize` button stays disabled until the user resolves them. Backend 409 fallback closes a race where a category is soft-deleted between modal open and Finalize click.
- On a `FINALIZED` block, open a non-empty technical bucket → `BucketDetailPage` header shows a `Transfer all to another block…` button → opens the existing `TransferModal` (extended) pre-filled with all bucket tracks → pick target IN_PROGRESS block + bucket → bulk transfer with auto-chunking at 1000 tracks per request → green toast on full success / amber toast on partial success with retry hint.
- If the originating Lambda 503s on cold-start during finalize → automatic recovery scheduler polls `GET /triage/blocks/{id}` 0/15/30s after the failure; if `block.status === 'FINALIZED'` materialises → success path; otherwise terminal-fail toast.

Out of scope: per-track Transfer-out from FINALIZED block (D2), re-open / unfinalize (backend forbidden, spec-D D1), bulk-from-IN_PROGRESS (kept atomic — F3b is per-track, F4 bulk lives only on FINALIZED tech buckets), batch-rollback on partial failure (snapshot semantics make it unnecessary — see D9), `/triage/{styleId}/{id}/blocked` route (D6).

## 2. Scope

**In scope:**

- New components: `FinalizeModal` (pre-flight summary + blocker variants), `FinalizeBlockerRow`, `FinalizeSummaryRow`.
- New hook: `useFinalizeTriageBlock(blockId, styleId)` — `useMutation` on `POST /triage/blocks/{id}/finalize` + cache sweep.
- New scheduler: `pendingFinalizeRecovery.ts` (mirrors `pendingCreateRecovery` shape) — polls `GET /triage/blocks/{id}` and resolves on `block.status === 'FINALIZED'`.
- Wiring `Finalize` CTA in `TriageBlockHeader` (replacing the current `disabled` placeholder + `coming_soon` tooltip at `TriageBlockHeader.tsx:54-58`).
- Extension of `TransferModal` (F3b) to accept `trackIds: string[]` instead of `trackId: string` — single-track callsites pass `[trackId]`. New optional `mode: 'single' | 'bulk'` controls bulk-specific UI (progress text + chunk loop).
- Bulk transfer chunk loop inside `TransferModal` step 2 — sequential firings of `useTransferTracks` with `track_ids` slices of ≤1000, partial-success aware.
- Wiring `Transfer all to another block…` header CTA in `BucketDetailPage` (FINALIZED block + non-STAGING bucket + non-empty).
- New i18n keys under `triage.finalize.*` and `triage.transfer.bulk.*`.
- Vitest unit + integration tests, mirroring F3a/F3b conventions.
- Tech-debt entry: `TD-12` — spec-D narrative says `block_not_editable` but backend emits `invalid_state` (`triage_repository.py:529` + `curation/__init__.py:67`). Same drift class as F3b TD-9. F4 codes against the actual `error_code`.

**Out of scope:**

- **Per-track Transfer from FINALIZED block.** Q1 outcome: bulk-only on tech buckets. Per-track stays IN_PROGRESS-only (existing F3b gate `MoveToMenu.showTransfer = blockStatus === 'IN_PROGRESS'`). Documented in §3 D2.
- **Transfer from FINALIZED STAGING bucket.** STAGING content is already promoted to the linked category; re-transferring would be misleading. The header CTA is hidden when `bucket.bucket_type === 'STAGING'` regardless of block status.
- **Re-open / unfinalize a FINALIZED block.** Spec-D D1 forbids it; no backend endpoint.
- **Bulk-from-IN_PROGRESS.** F3b is per-track and stays per-track. Bulk lives only on FINALIZED tech buckets. Future iteration: `FUTURE-F4-2` covers a unified bulk surface across both states.
- **Inline batch-rollback.** Source bucket is snapshot (spec-D §5.8 + `triage_repository.py:393`), so partial-failure rollback is unnecessary — the original tracks never left the source bucket and backend INSERT is idempotent (`ON CONFLICT DO NOTHING`, `triage_repository.py:493`). Retry covers the gap. Documented in §3 D9.
- **`/triage/{styleId}/{id}/blocked` standalone route.** Pass-1 design has a `P-21 Blocked` artboard but the inline blocker variant inside `FinalizeModal` covers the same UX in fewer hops.
- **Per-category breakdown in success toast.** `promoted: {<category_id>: <count>}` payload is reduced to aggregate `N tracks across M categories` for the toast. The detailed list is implicit in category track counts (F1 surface).
- **`Open target` link in success toast.** Same `FUTURE-F3b-2` carryover. User navigates manually.
- **Auto-chunk progress as Mantine `Progress` bar.** `Loader` + `"Transferring batch K of M…"` text is sufficient (Q11-A). `FUTURE-F4-3` covers richer progress when bucket sizes warrant it.
- **Sticky finalize CTA on mobile.** Single CTA in header is fine; F8 (Home) introduces sticky bars across the app — finalize joins that effort.
- **Partial-finalize / chunked-finalize from the client.** Backend handles 500-chunk `add_tracks_bulk` internally inside the single TX; client makes one POST. Chunking is server-side only (spec-D §7.3 `finalize_block`).
- **`promoted` payload validation.** We trust the backend shape and treat missing keys defensively (`Object.keys(promoted ?? {}).length`). No Zod schema for the response.

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Finalize CTA replaces the disabled placeholder in `TriageBlockHeader.tsx:54-58`.** Active when `block.status === 'IN_PROGRESS'`. Removes the `Tooltip + disabled Button` pair; renders an enabled `Button` that opens `FinalizeModal`. | The placeholder was already the right surface; F4 just lights it up. No new layout work. |
| D2 | **Bulk transfer from FINALIZED is exposed only on tech buckets.** `BucketDetailPage` header renders `Transfer all to other block…` when all of the following hold: `block.status === 'FINALIZED'`, `bucket.bucket_type !== 'STAGING'`, `bucket.track_count > 0`. STAGING buckets in FINALIZED stay strictly read-only. Per-track menu remains hidden on FINALIZED (existing F3a invariant). | Q1-D outcome. STAGING in FINALIZED is already promoted into the matching category — transferring it elsewhere would be a snapshot of an already-permanent record, confusing UX. Tech buckets are historical sorting state and remain useful as a source. |
| D3 | **`FinalizeModal` has two body variants.** **Confirm variant** (default): for each active STAGING bucket render `{category_name} → +{track_count}` rows; aggregate footer `Total: {N} tracks across {M} categories`; primary `Finalize` button (disabled when `mutation.isPending` or recovery scheduler pending). **Blocker variant**: triggered when `block.buckets.some(b => b.bucket_type === 'STAGING' && b.inactive && b.track_count > 0)`; renders `triage.finalize.blocker.title` + per-bucket `FinalizeBlockerRow` (`{deleted_category_name} · {track_count} tracks` + `Open` link to `/triage/{styleId}/{id}/buckets/{bucket.id}`); `Finalize` button **disabled** with explanatory copy. Both variants share one `<Modal>` shell. | Q2-A + Q3-A. Pre-flight summary respects irreversibility; blocker is the same concept inverted. One modal = less code, less navigation. |
| D4 | **`useFinalizeTriageBlock(blockId, styleId)` = `useMutation`** with `mutationKey: ['triage', 'finalize', blockId]`. No `onMutate` (irreversible op, optimistic write would lie about cache state). On success: per-D8 cache sweep + scheduler short-circuit. On error: per-D11 mapping. | Standard mutation shape; sweep is the only non-trivial bit. |
| D5 | **Cold-start (503) auto-recovery via `pendingFinalizeRecovery`.** New file `frontend/src/features/triage/lib/pendingFinalizeRecovery.ts` mirrors `pendingCreateRecovery` shape: pure scheduler, no React, no QueryClient. Args: `{ blockId, refetch: () => Promise<TriageBlock>, onSuccess: (block) => void, onFailure: () => void, delays?: number[] }`. Default delays `[0, 15_000, 15_000]`. Match condition: `block.status === 'FINALIZED'`. On terminal failure (3 ticks, no flip) → `onFailure`. The hook (`useFinalizeTriageBlock`) builds the closure on 503; the modal branches on success vs failure for toast + close behaviour. | Q4-A. Mirrors F2 lesson 23 pattern. Promotion to a shared `frontend/src/lib/coldStartRecovery.ts` deferred until a third consumer arrives (F2 lesson 23 explicitly defers shared promote until N=3). |
| D6 | **Inline blocker view, no `/blocked` route.** P-21 design artboard is a standalone "Blocked" page; we collapse it into the modal's blocker variant. `Open` links navigate to `BucketDetailPage` and close the modal first. | YAGNI — fewer routes, fewer mounts, same UX. |
| D7 | **`FinalizeModal` mounts only when triggered.** `TriageDetailPage` holds `[finalizeOpen, setFinalizeOpen] = useState(false)`. `false` = closed; `true` = open. `TriageBlockHeader.onFinalize = () => setFinalizeOpen(true)`. `FinalizeModal.onClose = () => setFinalizeOpen(false)`. | Mirrors F2 `CreateTriageBlockDialog` and F3b `TransferModal` mount semantics. Avoids global modal context. |
| D8 | **Cache sweep on finalize success.** Invalidate: `triageBlockKey(blockId)`, `triageBlocksByStyleKey(styleId, *)` for all 3 statuses (block migrates IN_PROGRESS → FINALIZED tab), `categoriesByStyleKey(styleId)` (track_count summary increased), and per `category_id` in `Object.keys(promoted)`: `categoryDetailKey(category_id)` + a `predicate` invalidation matching `['categories', 'tracks', category_id]` (covers all `search` variants of `categoryTracksKey`). | Q8-A. Predicate invalidation is required because `categoryTracksKey(id, search)` includes a search param — invalidating only `categoryTracksKey(id, '')` misses cached search results. |
| D9 | **Bulk transfer = snapshot semantics, no rollback.** Backend `POST /transfer` is INSERT-only (`triage_repository.py:393`); source bucket is never mutated. Sequential 1000-batches: if batch K+1 fails, batches 1..K already landed in target, source still intact (it never changed). Retry is idempotent (`ON CONFLICT DO NOTHING`, `triage_repository.py:493`) — repeating the same `track_ids` skips already-transferred rows server-side. Toast on partial success: `Transferred N of M. Source unchanged — click Transfer all again to retry.` Toast on full success: `Transferred M tracks to {block} / {bucket}.` | Q9-B + Q10-A. The user's "вернуть на место" concern is moot because source is the place — snapshot semantics guarantee it. Documented for future readers because the intuition "transfer = move" is wrong here. |
| D10 | **Bulk chunk size = 1000.** Hardcoded constant `BULK_CHUNK_SIZE = 1000` in `TransferModal.tsx`. Matches backend `track_ids` cap (spec-D §5.8). UI limit verification: `if (trackIds.length > 0)` always; backend enforces upper cap separately. No artificial "bucket too large" disabling — auto-chunk handles arbitrary sizes. | Q9 chosen path (B with rollback intent → A semantics after Q10 disambiguation). The cap concern is technical (HTTP payload size); auto-chunk solves it transparently. |
| D11 | **Error mapping.** From spec-D §5.9 and `triage_repository.py:528` + `curation/__init__.py:67/78` (authoritative `error_code` strings):<br>**Finalize errors:**<br>• `404 triage_block_not_found` → red toast `triage.finalize.toast.stale_block` + close modal + invalidate `triageBlockKey` + `triageBlocksByStyleKey`.<br>• `422 invalid_state` (block already FINALIZED or soft-deleted) → red toast `triage.finalize.toast.already_finalized` + close modal + invalidate `triageBlockKey` (likely race; UI hides the button when status changes).<br>• `409 inactive_buckets_have_tracks` (race: category soft-deleted between modal open and submit) → keep modal open + switch to **blocker variant** using the response body's `inactive_buckets[]` payload + invalidate `triageBlockKey`. (Initial blocker rendering uses local block.buckets state; runtime fallback uses the server payload.)<br>• `503` terminal → handled by `pendingFinalizeRecovery` scheduler (D5).<br><br>**Bulk transfer errors per batch:** reuse F3b error mapping verbatim — error per chunk handled the same as a single transfer. On any non-network error mid-loop, **break the loop**: stop firing remaining batches, surface the partial-success toast (`triage.transfer.bulk.toast.partial`) + the underlying error toast, leave modal open on step 2 so the user can retry. | One mapping table per surface. The spec-D narrative `block_not_editable` does not exist as an `error_code` — `invalid_state` is what backend emits. Tracked as `TD-12`. |
| D12 | **Spec-D narrative drift.** Spec-D §5.9 says 422 `block_not_editable`; backend emits `invalid_state` (`InvalidStateError.error_code = 'invalid_state'`). F3b already noted this drift (lesson 36, 37). F4 codes against `invalid_state` and adds `TD-12` to the roadmap to update spec-D's narrative. No code change in backend required — the `error_code` constant is the contract. | Same drift class as F3b TD-9 (OpenAPI description) and TD-10 (Move error code). The pattern is real and worth a roadmap entry. |
| D13 | **`TransferModal` prop refactor.** Rename `trackId: string` → `trackIds: string[]`. F3b's single-track callsite (`BucketDetailPage.tsx:197`) updates to pass `[transferTrackId]`. New optional prop `mode: 'single' \| 'bulk'` (default `'single'`) controls UI affordances: in `'bulk'` mode, step 2 shows `Transferring batch {k} of {m}…` text during the chunk loop; toast wording uses bulk-aware keys. | Q6-A. One component covers both flows; less duplication than a separate `BulkTransferModal`. |
| D14 | **Bulk chunk loop sequencing.** Inside `handlePickBucket` of `TransferModal` (when `mode === 'bulk'`): build chunks via `chunk(trackIds, BULK_CHUNK_SIZE)`; iterate `for (let i = 0; i < chunks.length; i++)`; `await transfer.mutateAsync({ trackIds: chunks[i], targetBlockId, targetBucketId, styleId })`; track `transferredSoFar += response.transferred`; on error `break` and surface the partial-success path. State: `[bulkPhase, setBulkPhase] = useState<{ k: number; m: number } \| null>(null)` to drive the UI. Reset on close. | Q11-A. Sequential is simpler than parallel and the cap (1000/req) makes parallel fan-out a future optimization. |
| D15 | **Header CTA disabled state during bulk transfer.** While `bulkPhase !== null` the bucket detail page header keeps the button rendered but `disabled` (so the user doesn't double-trigger by reopening from another route). Modal owns the active state; closing the modal mid-loop does NOT cancel in-flight chunks (one already-firing fetch finishes; subsequent chunks are skipped by the early-return on `cancelled` ref). | Defensive against double-trigger; cancellation is best-effort. |
| D16 | **Empty `promoted` (no STAGING buckets at all).** Possible: a triage block where the user authored zero categories. Finalize is still allowed by backend (spec-D §5.9 — promotes "every track in each STAGING bucket"; zero buckets = zero promotions, block flips to FINALIZED). Modal `Confirm` variant shows `triage.finalize.confirm.empty_summary` copy ("Block has no staging buckets. Finalizing will mark it FINALIZED with no category promotions.") + enabled `Finalize` button. Toast on success: `Finalized {block.name} · no tracks promoted.` | Edge case worth covering explicitly to avoid confusing empty-summary modal renders. |
| D17 | **`Cancel` button = `onClose`.** Modal close by X / Escape / `Cancel` button all call `handleClose` which resets local state. No confirmation-on-cancel — cancelling a pre-flight is harmless. | Standard Mantine modal behaviour. |
| D18 | **Finalize toast composes `N` and `M` from `promoted` payload.** `N = sum(Object.values(promoted))`, `M = Object.keys(promoted).length`. Pluralized via i18next ICU `triage.finalize.toast.success_one` / `_other`. | Q7-A simple aggregate; per-category breakdown is implicit in category track counts (F1). |
| D19 | **PR shape.** Single PR `feat/triage-finalize` from `main` (worktree `f4_task` already in place). Sequential caveman-commits per natural boundary, merge `--no-ff`. Mirror F3a/F3b discipline. | Solo dev workflow consistent with F1+F2+F3a+F3b. |
| D20 | **Bundle additions: zero new deps.** Mantine `Modal` already shipped. No new icons (reuse existing `IconArrowsExchange` from F3b for bulk-transfer button; reuse `IconCheck` or no icon on Finalize button — Mantine Button accepts text-only). | Bundle stays under 700 KB minified target (post-F3b is ~896 KB; F4 adds ~12-18 KB est. — confirm in plan). |

## 4. UI Surface

### 4.1 `TriageBlockHeader` finalize CTA (replaces placeholder)

Before:

```tsx
{!isFinalized && (
  <Group gap="xs">
    <Tooltip label={t('triage.detail.finalize_coming_soon')}>
      <Button disabled>{t('triage.detail.finalize_cta')}</Button>
    </Tooltip>
    <Menu position="bottom-end" withinPortal>
      {/* delete kebab */}
    </Menu>
  </Group>
)}
```

After:

```tsx
{!isFinalized && (
  <Group gap="xs">
    <Button onClick={onFinalize}>{t('triage.detail.finalize_cta')}</Button>
    <Menu position="bottom-end" withinPortal>
      {/* delete kebab — unchanged */}
    </Menu>
  </Group>
)}
```

New prop: `onFinalize: () => void`. The `triage.detail.finalize_coming_soon` i18n key becomes unused — remove it. The `finalize_cta` key already exists; reuse.

### 4.2 `TriageDetailPage` wiring

```tsx
const [finalizeOpen, setFinalizeOpen] = useState(false);

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
```

### 4.3 `FinalizeModal` — confirm variant

```tsx
interface FinalizeModalProps {
  opened: boolean;
  onClose: () => void;
  block: TriageBlock;
  styleId: string;
}

function FinalizeModal({ opened, onClose, block, styleId }: FinalizeModalProps) {
  const { t } = useTranslation();
  const finalize = useFinalizeTriageBlock(block.id, styleId);
  const [phase, setPhase] = useState<'idle' | 'pending' | 'recovering'>('idle');

  // Local copy of inactive-with-tracks list, refreshed by 409 fallback if needed.
  const [serverInactiveBuckets, setServerInactiveBuckets] =
    useState<InactiveBucketRow[] | null>(null);

  const localInactive = block.buckets.filter(
    (b) => b.bucket_type === 'STAGING' && b.inactive && b.track_count > 0,
  );
  const inactiveBuckets = serverInactiveBuckets ?? localInactive;
  const blocked = inactiveBuckets.length > 0;

  const stagingActive = block.buckets.filter(
    (b) => b.bucket_type === 'STAGING' && !b.inactive,
  );
  const totalToPromote = stagingActive.reduce((acc, b) => acc + b.track_count, 0);

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
        onClose();
      },
      onError: (err) => handleFinalizeError({
        err, t, qc, blockId: block.id, styleId,
        setServerInactiveBuckets, setPhase,
        scheduleRecovery: () => {
          setPhase('recovering');
          schedulePendingFinalizeRecovery({
            blockId: block.id,
            refetch: () => qc.fetchQuery({
              queryKey: triageBlockKey(block.id),
              queryFn: () => api<TriageBlock>(`/triage/blocks/${block.id}`),
            }),
            onSuccess: (refreshed) => {
              const m = refreshed.buckets.filter(b => b.bucket_type === 'STAGING' && !b.inactive).length;
              const n = refreshed.buckets
                .filter(b => b.bucket_type === 'STAGING' && !b.inactive)
                .reduce((a, c) => a + c.track_count, 0);
              notifications.show({
                color: 'green',
                message: t('triage.finalize.toast.success_recovered', {
                  count: n, blockName: block.name, categoryCount: m,
                }),
              });
              qc.invalidateQueries({ queryKey: triageBlockKey(block.id) });
              for (const s of STATUSES) {
                qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
              }
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
        },
      }),
    });
  };

  return (
    <Modal
      opened={opened}
      onClose={phase === 'pending' || phase === 'recovering' ? () => {} : onClose}
      size="lg"
      title={blocked
        ? t('triage.finalize.blocker.title')
        : t('triage.finalize.confirm.title', { blockName: block.name })
      }
    >
      {blocked
        ? <BlockerVariant inactiveBuckets={inactiveBuckets} block={block} styleId={styleId} onClose={onClose} />
        : <ConfirmVariant
            stagingActive={stagingActive}
            totalToPromote={totalToPromote}
            phase={phase}
            onSubmit={handleSubmit}
            onCancel={onClose}
          />
      }
    </Modal>
  );
}
```

`InactiveBucketRow` shape matches the backend's `inactive_buckets[]` payload from spec-D §5.9: `{ id: string; category_id: string; track_count: number }`. Frontend augments rendering with `category_name` from `block.buckets` lookup (`block.buckets.find(b => b.id === ib.id)?.category_name`).

### 4.4 `ConfirmVariant`

```tsx
interface ConfirmVariantProps {
  stagingActive: TriageBucket[];
  totalToPromote: number;
  phase: 'idle' | 'pending' | 'recovering';
  onSubmit: () => void;
  onCancel: () => void;
}

function ConfirmVariant({ stagingActive, totalToPromote, phase, onSubmit, onCancel }: ConfirmVariantProps) {
  const { t } = useTranslation();
  const isEmpty = stagingActive.length === 0;
  return (
    <Stack gap="md">
      <Text>{isEmpty
        ? t('triage.finalize.confirm.empty_summary')
        : t('triage.finalize.confirm.body', {
            count: totalToPromote,
            categoryCount: stagingActive.length,
          })
      }</Text>
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
          <Text size="sm" c="dimmed">{t('triage.finalize.confirm.recovering')}</Text>
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
```

### 4.5 `FinalizeSummaryRow`

```tsx
interface FinalizeSummaryRowProps {
  bucket: TriageBucket;  // STAGING, active
}

function FinalizeSummaryRow({ bucket }: FinalizeSummaryRowProps) {
  const { t } = useTranslation();
  return (
    <Group justify="space-between" wrap="nowrap"
      style={{ padding: 'var(--mantine-spacing-xs) 0', borderBottom: '1px solid var(--color-border)' }}>
      <Text>{bucket.category_name ?? '—'}</Text>
      <Text className="font-mono" c="dimmed">
        +{t('triage.finalize.confirm.row_count', { count: bucket.track_count })}
      </Text>
    </Group>
  );
}
```

### 4.6 `BlockerVariant`

```tsx
interface BlockerVariantProps {
  inactiveBuckets: InactiveBucketRow[];
  block: TriageBlock;
  styleId: string;
  onClose: () => void;
}

function BlockerVariant({ inactiveBuckets, block, styleId, onClose }: BlockerVariantProps) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Text>{t('triage.finalize.blocker.body', { count: inactiveBuckets.length })}</Text>
      <Stack gap="xs">
        {inactiveBuckets.map((ib) => {
          const localBucket = block.buckets.find((b) => b.id === ib.id);
          const name = localBucket?.category_name ?? t('triage.finalize.blocker.unknown_category');
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
        <Button disabled>
          {t('triage.finalize.confirm.submit')}
        </Button>
      </Group>
    </Stack>
  );
}
```

### 4.7 `FinalizeBlockerRow`

```tsx
interface FinalizeBlockerRowProps {
  categoryName: string;
  trackCount: number;
  href: string;
  onNavigate: () => void;
}

function FinalizeBlockerRow({ categoryName, trackCount, href, onNavigate }: FinalizeBlockerRowProps) {
  const { t } = useTranslation();
  return (
    <Group justify="space-between" wrap="nowrap"
      style={{ padding: 'var(--mantine-spacing-sm)', border: '1px solid var(--color-border)', borderRadius: 'var(--radius-md)' }}>
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

### 4.8 `BucketDetailPage` bulk-transfer header CTA

```tsx
const showBulkTransfer =
  block.status === 'FINALIZED' &&
  bucket.bucket_type !== 'STAGING' &&
  bucket.track_count > 0;

const [bulkTransferOpen, setBulkTransferOpen] = useState(false);
const [bulkTrackIds, setBulkTrackIds] = useState<string[] | null>(null);
const [collecting, setCollecting] = useState(false);

const tracksQuery = useBucketTracks(blockId, bucketId, '');
// Pagination is real (page size 50) — exhaust before opening the modal.

const handleOpenBulk = async () => {
  setCollecting(true);
  try {
    let q = tracksQuery;
    while (q.hasNextPage && !q.isFetchingNextPage) {
      await q.fetchNextPage();
      q = tracksQuery;
    }
    const allIds = (tracksQuery.data?.pages ?? []).flatMap((p) => p.items.map((t) => t.track_id));
    setBulkTrackIds(allIds);
    setBulkTransferOpen(true);
  } catch {
    notifications.show({ color: 'red', message: t('errors.network') });
  } finally {
    setCollecting(false);
  }
};

// In the header Group:
<Group gap="md" align="center" justify="space-between">
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

{/* Below the existing TransferModal mount: */}
{bulkTransferOpen && bulkTrackIds && (
  <TransferModal
    opened
    onClose={() => { setBulkTransferOpen(false); setBulkTrackIds(null); }}
    srcBlock={block}
    trackIds={bulkTrackIds}
    styleId={styleId}
    mode="bulk"
  />
)}
```

**Pagination handling:** `useBucketTracks` is `useInfiniteQuery` with `PAGE_SIZE = 50` (`useBucketTracks.ts:33`). Bulk transfer must enumerate every track ID, so the button click drains `fetchNextPage` until `hasNextPage === false`, then opens the modal with the full ID list. For a 2000-track bucket that's 40 sequential round-trips (~4 s on a warm cluster). Acceptable; the button shows a `loading` spinner during the drain. `track_count` displayed on the bucket header gives the user an honest expectation of duration.

Why not parallel fetch: `useInfiniteQuery` doesn't expose a parallel-page primitive, and Aurora Data API has a per-Lambda concurrency cap; sequential is safer + matches existing infrastructure. Faster bulk loading is `FUTURE-F4-7` (custom non-react-query fetch with `Promise.all` chunked at N parallel pages, or a backend `?bulk=true` param returning all rows in one call).

### 4.9 `TransferModal` extension

Prop changes:

```ts
interface TransferModalProps {
  opened: boolean;
  onClose: () => void;
  srcBlock: TriageBlock;
  trackIds: string[];                     // CHANGED: was `trackId: string`
  styleId: string;
  mode?: 'single' | 'bulk';               // NEW (default 'single')
}
```

F3b callsite update (`BucketDetailPage.tsx:197`):

```tsx
<TransferModal
  opened
  onClose={() => setTransferTrackId(null)}
  srcBlock={block}
  trackIds={[transferTrackId]}            // wrap in array
  styleId={styleId}
  // mode omitted → defaults to 'single'
/>
```

`handlePickBucket` updated to branch:

```tsx
const handlePickBucket = (bucket: TriageBucket) => {
  if (!targetBlockId) return;
  if (mode === 'single') {
    transfer.mutate(
      { targetBlockId, targetBucketId: bucket.id, trackIds, styleId },
      { onSuccess: ..., onError: ... },
    );
    return;
  }
  // mode === 'bulk' → chunk loop
  runBulkTransfer({ targetBlockId, targetBucketId: bucket.id, trackIds, styleId, bucketLabelText: bucketLabel(bucket, t) });
};
```

`runBulkTransfer` is an async helper that:

1. Sets `setBulkPhase({ k: 1, m: chunks.length })`.
2. Iterates chunks via `mutateAsync`; updates `setBulkPhase({ k: i+1, m })` at the start of each.
3. On any error mid-loop: surfaces partial-success toast (`triage.transfer.bulk.toast.partial` with `transferred` count + `total` count) + the underlying error toast, sets `setBulkPhase(null)`, leaves modal open on step 2.
4. On full success: green toast `triage.transfer.bulk.toast.success` + `handleClose()`.

A `cancelled` ref short-circuits the loop if the modal is closed mid-flight (D15 best-effort cancellation).

### 4.10 Step 2 progress UI in bulk mode

```tsx
{mode === 'bulk' && bulkPhase && (
  <Group gap="xs">
    <Loader size="sm" />
    <Text size="sm">
      {t('triage.transfer.bulk.modal.batch_progress', { k: bulkPhase.k, m: bulkPhase.m })}
    </Text>
  </Group>
)}
```

`BucketGrid` `disabled` prop wires to `disabled={transfer.isPending || bulkPhase !== null}`.

## 5. Component Catalog

| Component | Anatomy | Mantine base | Owner |
|---|---|---|---|
| `FinalizeModal` | Modal that branches on blocker vs confirm variant; owns mutation + recovery state | `Modal`, `Stack`, `Group` | F4 (NEW) |
| `ConfirmVariant` | Header + summary list + total + Cancel/Finalize buttons | `Stack`, `Text`, `Button`, `Loader` | F4 (NEW, internal) |
| `BlockerVariant` | Header + inactive list + Dismiss/disabled-Finalize | `Stack`, `Text`, `Button` | F4 (NEW, internal) |
| `FinalizeSummaryRow` | One row: `category_name → +N` | `Group`, `Text` | F4 (NEW) |
| `FinalizeBlockerRow` | One row: `category_name · N tracks` + Open link | `Group`, `Stack`, `Text`, `Anchor` | F4 (NEW) |
| `TriageBlockHeader` (modified) | Adds `onFinalize` prop, replaces disabled placeholder Button with active Button | `Button` | F1 → F4 extends |
| `TransferModal` (modified) | Renamed prop + new `mode` + bulk chunk loop + progress UI | `Modal` | F3b → F4 extends |
| `BucketDetailPage` (modified) | Adds `Transfer all` header CTA + new modal mount + bulk track-id resolution | `Button`, `Group` | F3a → F4 extends |
| `EmptyState` | Reused (none needed for finalize) | — | reused |

## 6. Data Flow

### 6.1 React-query keys (no new keys)

Reuse:

```ts
// existing
['triage', 'blockDetail', blockId]                                // F3a
['triage', 'byStyle', styleId, status]                            // F2 (status: 'IN_PROGRESS' | 'FINALIZED' | undefined)
['triage', 'bucketTracks', blockId, bucketId, search]             // F3a
['categories', 'byStyle', styleId]                                // F1
['categories', 'detail', categoryId]                              // F1
['categories', 'tracks', categoryId, search]                      // F1
```

### 6.2 Hook `useFinalizeTriageBlock`

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
import {
  categoriesByStyleKey,
} from '../../categories/hooks/useCategoriesByStyle';
import {
  categoryDetailKey,
} from '../../categories/hooks/useCategoryDetail';

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

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

export function useFinalizeTriageBlock(
  blockId: string,
  styleId: string,
): UseMutationResult<FinalizeResponse, ApiError, void> {
  const qc = useQueryClient();
  return useMutation<FinalizeResponse, ApiError, void>({
    mutationKey: ['triage', 'finalize', blockId],
    mutationFn: () =>
      api<FinalizeResponse>(`/triage/blocks/${blockId}/finalize`, {
        method: 'POST',
      }),
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

### 6.3 Scheduler `pendingFinalizeRecovery`

```ts
import type { TriageBlock } from '../hooks/useTriageBlock';

interface ScheduleArgs {
  blockId: string;
  refetch: () => Promise<TriageBlock>;
  onSuccess: (block: TriageBlock) => void;
  onFailure: () => void;
  delays?: number[];
}

const DEFAULT_DELAYS = [0, 15_000, 15_000];

export function schedulePendingFinalizeRecovery({
  blockId: _blockId,
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

### 6.4 Error mapping helper

```ts
interface FinalizeErrorCtx {
  err: ApiError | unknown;
  t: TFunction;
  qc: QueryClient;
  blockId: string;
  styleId: string;
  setServerInactiveBuckets: (rows: InactiveBucketRow[] | null) => void;
  setPhase: (p: 'idle' | 'pending' | 'recovering') => void;
  scheduleRecovery: () => void;
}

const STATUSES: (TriageStatus | undefined)[] = ['IN_PROGRESS', 'FINALIZED', undefined];

function handleFinalizeError(ctx: FinalizeErrorCtx): void {
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

  const code = err.code;

  if (code === 'inactive_buckets_have_tracks') {
    const body = err.raw as FinalizeErrorBody | undefined;
    const rows = body?.inactive_buckets ?? [];
    ctx.setServerInactiveBuckets(rows);
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    notifications.show({
      color: 'orange',
      message: t('triage.finalize.toast.blocked_race', { count: rows.length }),
    });
    ctx.setPhase('idle');
    return;
  }

  if (code === 'triage_block_not_found') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.stale_block') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    for (const s of STATUSES) qc.invalidateQueries({ queryKey: triageBlocksByStyleKey(styleId, s) });
    ctx.setPhase('idle');
    return;
  }

  if (code === 'invalid_state') {
    notifications.show({ color: 'red', message: t('triage.finalize.toast.already_finalized') });
    qc.invalidateQueries({ queryKey: triageBlockKey(blockId) });
    ctx.setPhase('idle');
    return;
  }

  notifications.show({ color: 'red', message: t('triage.finalize.toast.error') });
  ctx.setPhase('idle');
}
```

`ApiError.raw` (existing field at `frontend/src/api/error.ts:7`) already exposes the parsed JSON body of the error response. Cast to `FinalizeErrorBody` to read `inactive_buckets[]`. No infrastructure extension needed.

### 6.5 Bulk transfer chunk loop

```ts
interface RunBulkArgs {
  targetBlockId: string;
  targetBucketId: string;
  trackIds: string[];
  styleId: string;
  bucketLabelText: string;
}

const BULK_CHUNK_SIZE = 1000;

const runBulkTransfer = async (args: RunBulkArgs) => {
  const { targetBlockId, targetBucketId, trackIds, styleId, bucketLabelText } = args;
  const chunks: string[][] = [];
  for (let i = 0; i < trackIds.length; i += BULK_CHUNK_SIZE) {
    chunks.push(trackIds.slice(i, i + BULK_CHUNK_SIZE));
  }
  const total = trackIds.length;
  let transferred = 0;

  for (let i = 0; i < chunks.length; i++) {
    if (cancelledRef.current) break;
    setBulkPhase({ k: i + 1, m: chunks.length });
    try {
      const resp = await transfer.mutateAsync({
        targetBlockId, targetBucketId, trackIds: chunks[i], styleId,
      });
      transferred += resp.transferred;
    } catch (err) {
      // Partial success: stop firing remaining chunks, surface partial toast,
      // leave modal on step 2 for retry.
      notifications.show({
        color: 'orange',
        message: t('triage.transfer.bulk.toast.partial', {
          count: transferred,
          total,
          blockName: targetBlockQuery.data?.name ?? '',
          bucketLabel: bucketLabelText,
        }),
      });
      handleTransferError({ err, /* same as F3b */ });
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
      bucketLabel: bucketLabelText,
    }),
  });
  handleClose();
};
```

### 6.6 Mounting mechanics

`FinalizeModal` mounts when `finalizeOpen === true` (D7). State (`phase`, `serverInactiveBuckets`) lives inside the modal and resets on close. Closing during pending or recovering is **suppressed** (`onClose` no-op via the `phase` check) — finalize is irreversible; the user should let the recovery scheduler resolve. The X / Escape are also suppressed in those phases.

`TransferModal` in bulk mode mounts when `bulkTransferOpen === true` on `BucketDetailPage`. Internal state (`step`, `targetBlockId`, `bulkPhase`) resets on close.

## 7. Validation

No forms. Client-side gates only:

- **Finalize CTA visible only when** `block.status === 'IN_PROGRESS'` (D1). Header re-renders post-success showing FINALIZED badge + finalized_at.
- **Bulk Transfer button visible only when** `block.status === 'FINALIZED' && bucket.bucket_type !== 'STAGING' && bucket.track_count > 0` (D2).
- **Blocker preempt** uses `block.buckets` (local) before submit; backend 409 fallback covers the race (D3, D11).
- **Empty staging summary** is rendered when `stagingActive.length === 0` — backend allows finalize anyway (D16).
- **No Zod schemas needed** (no inputs).

## 8. Error / Empty / Loading UX Mapping

| State | Surface | UX |
|---|---|---|
| Modal opens, no inactive STAGING with tracks, no STAGING at all | confirm | `triage.finalize.confirm.empty_summary` body + enabled `Finalize`. |
| Modal opens, no inactive, ≥1 STAGING active | confirm | Body with total + per-bucket rows + enabled `Finalize`. |
| Modal opens, ≥1 inactive STAGING with tracks | blocker | List rows + Open links; disabled `Finalize`. |
| Submit, pending | confirm | `Finalize` button shows `loading`; Cancel disabled; Modal close suppressed. |
| Submit, 200 OK | toast | Green `triage.finalize.toast.success` (count + blockName + categoryCount). Modal closes. Cache sweep fires (D8). |
| Submit, 503 | confirm | Phase = `recovering`; `Loader + recovering text` shown next to footer. Modal close suppressed during recovery. |
| Submit, 503 → recovery success (status=FINALIZED) | toast | Green `triage.finalize.toast.success_recovered` + cache sweep + modal closes. |
| Submit, 503 → recovery 3-tick fail | toast | Red `triage.finalize.toast.cold_start_terminal` + phase resets to `idle`; user can retry the button. |
| Submit, 422 `invalid_state` (race: already FINALIZED) | toast | Red `triage.finalize.toast.already_finalized` + invalidate `triageBlockKey` + modal closes. Page re-renders FINALIZED. |
| Submit, 404 `triage_block_not_found` | toast | Red `triage.finalize.toast.stale_block` + invalidate `triageBlockKey` + `triageBlocksByStyleKey` + modal closes. |
| Submit, 409 `inactive_buckets_have_tracks` | blocker | Modal switches to blocker variant using server payload; orange info toast `triage.finalize.toast.blocked_race`. |
| Bulk transfer, all chunks OK | toast | Green `triage.transfer.bulk.toast.success` + modal closes. |
| Bulk transfer, mid-loop fail | toast | Orange `triage.transfer.bulk.toast.partial` + the underlying error toast (per F3b mapping); modal stays on step 2. |
| Bulk transfer, batch progress | step 2 | `Loader` + `Transferring batch K of M…`. `BucketGrid disabled`. |
| Bulk transfer button click, draining pages | header | Button shows `loading` spinner; modal not yet open. On drain failure → red `errors.network` toast; button resets. |
| Bulk transfer button on STAGING (any status) | header | Button not rendered. |
| Bulk transfer button on tech bucket of IN_PROGRESS | header | Button not rendered (per-track menu handles single-track in IN_PROGRESS via F3b). |
| Per-track Transfer item in `MoveToMenu` on FINALIZED | menu | Not reachable (F3a hides entire menu via `showMoveMenu = block.status === 'IN_PROGRESS'`). Existing invariant. |

## 9. Code Layout

### 9.1 New files

```
frontend/src/features/triage/
├── components/
│   ├── FinalizeModal.tsx                     # NEW
│   ├── FinalizeSummaryRow.tsx                # NEW
│   ├── FinalizeBlockerRow.tsx                # NEW
│   └── __tests__/
│       ├── FinalizeModal.test.tsx            # NEW
│       ├── FinalizeSummaryRow.test.tsx       # NEW
│       └── FinalizeBlockerRow.test.tsx       # NEW
├── hooks/
│   ├── useFinalizeTriageBlock.ts             # NEW
│   └── __tests__/
│       └── useFinalizeTriageBlock.test.tsx   # NEW
├── lib/
│   ├── pendingFinalizeRecovery.ts            # NEW
│   └── __tests__/
│       └── pendingFinalizeRecovery.test.ts   # NEW
└── __tests__/
    └── FinalizeFlow.integration.test.tsx     # NEW (covers TriageDetailPage + FinalizeModal)
```

### 9.2 Modified files

- `frontend/src/features/triage/components/TriageBlockHeader.tsx` — add `onFinalize: () => void` prop; replace `Tooltip + disabled Button` with active `Button onClick={onFinalize}`. Remove the dead `triage.detail.finalize_coming_soon` i18n key reference.
- `frontend/src/features/triage/routes/TriageDetailPage.tsx` — add `useState<boolean>` for `finalizeOpen`; thread `onFinalize`; conditionally render `<FinalizeModal>`.
- `frontend/src/features/triage/components/TransferModal.tsx` — rename `trackId: string` → `trackIds: string[]`; add `mode?: 'single' | 'bulk'` prop; add `runBulkTransfer` helper + `bulkPhase` state; branch UI in step 2 on mode.
- `frontend/src/features/triage/components/__tests__/TransferModal.test.tsx` — update existing single-track tests to pass `trackIds={['t-1']}` and update success-toast assertion to call site (the F3b `transferred_one` key uses `count: 1` already; should be unchanged).
- `frontend/src/features/triage/routes/BucketDetailPage.tsx` — add `useBucketTracks` resolver to gather all track IDs for the bucket (already partially loaded — extend if pagination is real); add `useState<boolean>` for `bulkTransferOpen`; render `Transfer all` button per D2 conditions; mount `<TransferModal mode="bulk" trackIds={tracksInBucket} />`.
- `frontend/src/features/triage/index.ts` — re-export `FinalizeModal`, `useFinalizeTriageBlock`.
- `frontend/src/i18n/en.json` — add `triage.finalize.*` and `triage.transfer.bulk.*` namespaces (§10). Remove unused `triage.detail.finalize_coming_soon`.
- `frontend/src/api/error.ts` — **no change needed.** `ApiError.raw: unknown` already carries the parsed JSON body (verified at `error.ts:7` and `from()` populates it). Handler casts `err.raw as FinalizeErrorBody` to read `inactive_buckets[]`.

### 9.3 No backend changes

`POST /triage/blocks/{id}/finalize` already deployed. `schema.d.ts` already has the path + `FinalizeTriageBlockOut`. Verify `inactive_buckets[]` shape in schema (spec-D §5.9 lists it; if missing in OpenAPI body, treat as TD entry — read body via `ApiError.body`).

### 9.4 Tech debt entries

- **`TD-12`: spec-D narrative drift on finalize error code.** Spec-D §5.9 says 422 `block_not_editable`; backend emits `invalid_state` (`triage_repository.py:529` + `curation/__init__.py:67`). Fix: update spec-D narrative or rename `InvalidStateError.error_code` for the finalize path. F4 codes against `invalid_state` (the actual contract). Add to roadmap; same drift pattern as `TD-9` (OpenAPI description) and `TD-10` (Move error code).
- (No additional TD entry — `ApiError.raw` already exposes the parsed body.)

## 10. i18n Keys

```json
{
  "triage": {
    "detail": {
      "finalize_cta": "Finalize"
    },
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
    },
    "transfer": {
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
    }
  }
}
```

Pluralization via i18next ICU (`_one` / `_other`). RU bundle = iter-2b.

`triage.detail.finalize_coming_soon` is removed from `en.json`.

## 11. Testing

### 11.1 Unit (Vitest + Testing Library)

`features/triage/lib/__tests__/pendingFinalizeRecovery.test.ts`:
- 3 ticks scheduled with cumulative delays `[0, 15s, 30s]` from default.
- Tick 1 returns `IN_PROGRESS` → no `onSuccess`; tick 2 returns `FINALIZED` → `onSuccess` fires once, scheduler `resolved`.
- All 3 ticks return `IN_PROGRESS` → `onFailure` fires on tick 3 only.
- Refetch throws on tick 2 → silent; throws on tick 3 → `onFailure` fires.
- Custom `delays` override default.

`features/triage/hooks/__tests__/useFinalizeTriageBlock.test.tsx`:
- Happy 200 → invalidates `triageBlockKey`, `triageBlocksByStyleKey` (3 statuses), `categoriesByStyleKey`, per-category `categoryDetailKey` and `categoryTracks` predicate match. Spy on `qc.invalidateQueries`.
- 503 → mutation rejects with ApiError; no invalidations fire (onSuccess not called).
- 409 with `inactive_buckets` body → mutation rejects; `error.body.inactive_buckets` accessible.

`features/triage/components/__tests__/FinalizeModal.test.tsx`:
- Confirm variant: no inactive STAGING with tracks → renders summary rows + total + enabled `Finalize`.
- Empty staging: zero STAGING active → renders empty_summary copy + enabled `Finalize`.
- Blocker variant: ≥1 inactive STAGING with tracks → renders blocker rows with category names and Open links (with correct `to` URLs); `Finalize` disabled.
- Submit click → calls mutate; sets phase=pending; Cancel + close suppressed during pending.
- 200 success → shows green toast (mocked notifications); calls onClose.
- 503 mocked → enters recovering phase; shows "Cold start, hang on…" copy; modal close suppressed.
- 422 `invalid_state` → red toast; closes modal.
- 409 `inactive_buckets_have_tracks` → switches to blocker variant with server payload; orange info toast.

`features/triage/components/__tests__/FinalizeSummaryRow.test.tsx`:
- Renders `category_name` and `+{track_count}` (singular/plural).
- Missing `category_name` → renders dash placeholder.

`features/triage/components/__tests__/FinalizeBlockerRow.test.tsx`:
- Renders `categoryName` + `trackCount` row.
- Open link has correct `href`; click triggers `onNavigate`.

`features/triage/components/__tests__/TransferModal.test.tsx` (extended):
- Existing single-track tests: prop refactor `trackIds={['t-1']}`; assertions unchanged for happy / error paths.
- New bulk-mode tests:
  - `mode='bulk'`, 100 trackIds, 1000 cap → 1 chunk, single mutateAsync, success toast.
  - `mode='bulk'`, 1500 trackIds → 2 chunks; second chunk fires only after first resolves; success toast aggregates `transferred=1500`.
  - `mode='bulk'`, mid-chunk error (chunk 2 of 3 rejects with 409) → orange partial toast (`transferred=1000 of 3000`) + red underlying toast; modal stays on step 2; `bulkPhase` resets to null.
  - `mode='bulk'`, all chunks 200 → green bulk success toast + modal close.
  - Modal close mid-bulk → `cancelled` ref short-circuits next chunk; in-flight chunk completes silently.

### 11.2 Integration (Vitest + MSW) — `FinalizeFlow.integration.test.tsx`

Mounted under `TriageDetailPage` with `MemoryRouter`.

1. **Happy path no STAGING.** Block with only NEW/OLD/UNCLASSIFIED buckets. Click `Finalize` → modal opens with empty_summary copy + enabled button. Submit → mocked POST 200 with `promoted: {}` → green toast `Finalized {name} · promoted 0 tracks across 0 categories.` → modal closes → header shows FINALIZED badge.
2. **Happy path with STAGING.** Block with 2 STAGING (3 tracks each). Modal shows 2 summary rows + total `6`. Submit → POST 200 `promoted: {cat1: 3, cat2: 3}` → green toast `…promoted 6 tracks across 2 categories.` → modal closes → cache invalidations fire (verify via spy: `triageBlockKey`, `triageBlocksByStyleKey × 3`, `categoriesByStyleKey`, `categoryDetailKey × 2`, `categoryTracks` predicate × 2).
3. **Blocker preempt.** Block with 1 inactive STAGING with 5 tracks. Click `Finalize` → modal opens directly to blocker variant, lists the deleted category name (from local `block.buckets` lookup) + `5 tracks` + Open link to `/triage/{styleId}/{id}/buckets/{bucketId}`. `Finalize` disabled. Click Open → modal closes + navigation fires.
4. **Blocker race.** Block with 0 inactive locally. Click `Finalize` → confirm variant. Submit → mocked 409 with `inactive_buckets: [{id, category_id, track_count:7}]` → modal switches to blocker variant; orange info toast; phase reset.
5. **422 already finalized.** Submit → mocked 422 `invalid_state` → red toast `already_finalized` + invalidate `triageBlockKey` + modal closes.
6. **404 stale block.** Submit → mocked 404 `triage_block_not_found` → red toast `stale_block` + invalidates fire + modal closes.
7. **503 cold-start success on tick 2.** Submit → 503 → phase=recovering; "Cold start, hang on…" copy visible. Mock `GET /triage/blocks/{id}` to return `IN_PROGRESS` on tick 1 (t=0) and `FINALIZED` on tick 2 (t=15s). Use `vi.useFakeTimers()` + advance timers; expect green `success_recovered` toast + cache invalidations + modal closes.
8. **503 cold-start terminal.** Same setup but `GET` returns IN_PROGRESS on all 3 ticks. Advance to t=30s. Expect red `cold_start_terminal` toast + phase resets to idle (modal stays open, user can retry).
9. **Bulk transfer happy path.** Mount `BucketDetailPage` for a FINALIZED block's NEW bucket with 2500 mocked tracks. Click `Transfer all` → modal opens (single-block sibling). Pick block → step 2. Pick NEW bucket → 3 sequential POSTs (sizes 1000/1000/500); intermediate `batch_progress` text visible after each chunk start. All 200 → green `bulk.toast.success` (count=2500) + modal closes.
10. **Bulk transfer partial.** Same setup, mock 2nd POST as 422 `invalid_state` → orange partial toast (`transferred=1000 of 2500`) + red underlying toast `target_finalized` + modal stays on step 2.
11. **Bulk transfer button gating.** STAGING bucket of FINALIZED → button absent. Tech bucket of IN_PROGRESS → button absent. Tech bucket of FINALIZED with 0 tracks → button absent. Tech bucket of FINALIZED with ≥1 track → button present.
12. **Finalize button visibility.** IN_PROGRESS → button visible & enabled. FINALIZED → button absent (header conditional).

### 11.3 Test infra (mirror F3a/F3b)

- `notifications.clean()` in `beforeEach` and `afterEach`.
- `gcTime: Infinity` on test QueryClient.
- `notifyManager.setScheduler(queueMicrotask)` already in `setup.ts`.
- `NODE_OPTIONS=--no-experimental-webstorage` in test scripts.
- Mantine `Modal` `transitionProps={{ duration: 0 }}` from `frontend/src/test/theme.ts` (F3b lesson 40 + 43).
- All five jsdom shims in `setup.ts` already in place.
- MSW handlers for `POST /triage/blocks/{id}/finalize`, `GET /triage/blocks/{id}` (recovery polling), `POST /triage/blocks/{id}/transfer` (bulk loop).
- Fake timers for 503 cold-start tests (advance via `vi.advanceTimersByTime(15_000)`).

### 11.4 Smoke (manual pre-merge)

1. Sign in → triage → pick a style → open an IN_PROGRESS block.
2. Click `Finalize` → confirm modal lists STAGING buckets + counts. Cancel → modal closes, no state change.
3. Click `Finalize` → submit → green toast → page re-renders FINALIZED badge + finalized_at.
4. Open a finalized block whose original NEW bucket has tracks → bucket detail → click `Transfer all to another block…` → pick another IN_PROGRESS block → pick its NEW bucket → green toast.
5. Re-open the source FINALIZED block's NEW bucket → confirm tracks STILL there (snapshot semantics).
6. Open the target IN_PROGRESS block's NEW bucket → confirm the tracks are present.
7. Trigger blocker: in an IN_PROGRESS block with ≥1 STAGING, soft-delete the linked category (via F1 `Delete` flow). Re-open Finalize → blocker variant lists the bucket. Open link → navigates to BucketDetailPage. Move tracks elsewhere → return → Finalize succeeds.
8. Edge: FINALIZED block STAGING bucket detail page → confirm `Transfer all` button is absent.

### 11.5 Coverage target

~30 new tests. Existing F1+F2+F3a+F3b baseline ~244 tests → after F4 ~274. `pnpm test` green, `pnpm typecheck` green, `pnpm build` < 920 KB (target +20 KB max over F3b 896 KB).

## 12. Delivery

1. Branch `feat/triage-finalize` from `main` (worktree `f4_task` already in place).
2. Sequential commits per natural boundary, all messages from `caveman:caveman-commit`:
   - `pendingFinalizeRecovery` scheduler + tests
   - `useFinalizeTriageBlock` hook + tests (with cache sweep)
   - `FinalizeSummaryRow` + `FinalizeBlockerRow` leaf components + tests
   - `FinalizeModal` (confirm + blocker variants + recovery integration) + tests
   - `TriageBlockHeader` Finalize CTA wiring
   - `TriageDetailPage` modal mount
   - `TransferModal` prop refactor (`trackId` → `trackIds`) + bulk-mode + chunk loop + tests
   - `BucketDetailPage` bulk transfer header CTA + modal mount
   - i18n keys + remove unused `finalize_coming_soon`
   - `ApiError.body` extension if needed (separate small commit if non-trivial)
   - integration tests (`FinalizeFlow.integration.test.tsx`)
3. `pnpm test` green, `pnpm typecheck` green, `pnpm build` green.
4. `pnpm dev` manual smoke against deployed prod API (§11.4).
5. `git checkout main && git merge feat/triage-finalize --no-ff && git push origin main`.
6. Roadmap update: mark F4 shipped, append F4 lessons section, add `TD-12` (and `TD-13` if needed) entry.

CI runs on push to `main`.

## 13. Open Items, Edge Cases, Future Flags

### 13.1 Edge cases worth a comment

- **Concurrent finalize attempts.** User opens modal in two tabs and clicks Finalize in both. First wins (200), second gets 422 `invalid_state` → red toast `already_finalized`. Tab 2's modal closes; the page re-renders FINALIZED. No corruption.
- **Category soft-deleted between modal-open and Submit.** Local block.buckets state is stale; backend 409 fires; the handler swaps in the server `inactive_buckets[]` payload. Modal flips to blocker variant in place.
- **STAGING bucket has 0 tracks.** Counted as a row in summary with `+0` — backend promotes 0 tracks for it. Could be hidden, but explicit "0" is informative when mixed with non-zero rows. Acceptable.
- **`promoted` payload contains category_id absent from local categories cache.** Possible if categories cache is stale. Cache sweep invalidates everything anyway; next render reflects authoritative server state.
- **User navigates away during finalize pending.** Modal unmounts; mutation continues (TanStack Query keeps mutation alive while in-flight). On success, the cache sweep updates background data; the next visit shows FINALIZED. Toast may not fire because notifications context changes — acceptable; the visible page state is the source of truth.
- **User navigates away during bulk transfer.** Same as above. `cancelled` ref is set on close → loop short-circuits before next chunk. The in-flight chunk completes silently. Acceptable; user can retry on the next visit.
- **`promoted` is undefined / missing field.** Defensive: `data.promoted ?? {}`. Toast shows `count=0, categoryCount=0` — degenerate but non-crashing.
- **Refetch during recovery returns 401.** The poll loop catches the throw on the final tick and calls `onFailure`. Auth refresh would have redirected on the original POST anyway — this path is best-effort.
- **(Verified) `ApiError.raw` already exposes the parsed body** (`frontend/src/api/error.ts:7`). The handler casts `err.raw as FinalizeErrorBody` for `inactive_buckets[]`. No extra infrastructure work.

### 13.2 Future flags (post iter-2a)

- **`FUTURE-F4-1`** — bulk transfer `Open target` link in success toast (mirror `FUTURE-F3b-2`).
- **`FUTURE-F4-2`** — unified bulk surface across IN_PROGRESS + FINALIZED. Promote the F3b per-track row affordance plus F4 bulk header into one shared "transfer this set" UX.
- **`FUTURE-F4-3`** — Mantine `Progress` bar for bulk transfer (replace text-only progress). Real-time chunks-completed indicator + cancel button.
- **`FUTURE-F4-4`** — promote `pendingCreateRecovery` + `pendingFinalizeRecovery` to a shared `frontend/src/lib/coldStartRecovery.ts` with multiple match strategies (`tuple`, `statusFlip`, custom predicate). Land when a third consumer arrives.
- **`FUTURE-F4-5`** — `Re-open` (unfinalize) endpoint + UI. Spec-D D1 forbids it today; if business needs change, both backend and frontend surface need to be designed.
- **`FUTURE-F4-6`** — async-finalize via Step Functions for staging buckets above ~5000 tracks (spec-D `FUTURE-D3`). Frontend coupling: a `pollable_run_id` style affordance instead of synchronous wait.
- **`FUTURE-F4-7`** — faster bulk-transfer track-id enumeration. Either a backend `GET /triage/blocks/{id}/buckets/{bucketId}/tracks?bulk=true` returning all rows in one call, or a parallel-pages primitive on top of `useInfiniteQuery`. Today's sequential drain is ~4 s for 2000 tracks; acceptable but improvable.

### 13.3 Cross-ticket dependencies

- **F5 Curate** is independent. Curate operates on a single IN_PROGRESS block; Finalize is the exit door. No shared state.
- **F8 Home** consumes `byStyle` summary counts which Finalize invalidates. The Home dashboard's `FINALIZED tab counter` for a style ticks up immediately after F4 success.
- **F1 Categories** consumes `categoriesByStyle`/`categoryDetail`/`categoryTracks` keys. Finalize sweep keeps F1 in sync without F1 code changes.

## 14. Acceptance Criteria

- `TriageBlockHeader` renders an enabled `Finalize` button when `block.status === 'IN_PROGRESS'`; absent (with FINALIZED badge instead) when FINALIZED. Disabled placeholder + `coming_soon` tooltip removed.
- Click `Finalize` → `FinalizeModal` opens.
- Confirm variant lists every active STAGING bucket as `{category_name} → +{count}` row + aggregate `Total: N tracks across M categories`. `Finalize` button enabled.
- Empty-staging confirm variant shows the explicit copy + enabled `Finalize`.
- Blocker variant lists every inactive STAGING with tracks; each row carries `Open` link to that BucketDetailPage. `Finalize` button disabled.
- Submit (200) → green toast `Finalized {name} · promoted N tracks across M categories.` + page re-renders FINALIZED + cache sweep fires (D8 keys).
- Submit (503) → recovery scheduler polls 0/15/30s for `block.status === 'FINALIZED'`. On flip → green `success_recovered` toast + close. On terminal fail → red `cold_start_terminal` toast; modal stays open (idle); user can retry.
- Submit (422 `invalid_state`) → red `already_finalized` toast + invalidate triage detail + close.
- Submit (404 `triage_block_not_found`) → red `stale_block` toast + invalidates + close.
- Submit (409 `inactive_buckets_have_tracks`) → modal switches to blocker variant using `error.body.inactive_buckets[]`; orange info toast.
- Bulk Transfer button on `BucketDetailPage` is visible exactly when `block.status === 'FINALIZED' && bucket.bucket_type !== 'STAGING' && bucket.track_count > 0`. Not visible otherwise.
- Click `Transfer all to another block…` → `TransferModal` opens with `mode='bulk'`, `trackIds = [all tracks of the bucket]`.
- Step 2 bulk loop: sequential 1000-batches, `Transferring batch K of M…` text visible during fire, `BucketGrid disabled` until phase resolves.
- Bulk all-success → green `bulk.toast.success` (aggregate count) + modal closes.
- Bulk partial-fail (mid-loop) → orange `bulk.toast.partial` + red underlying toast; modal stays on step 2; user can retry; backend `ON CONFLICT DO NOTHING` prevents duplicates.
- Per-track Transfer affordance unchanged (F3b): only on IN_PROGRESS blocks, single-track only. F3b callsite migrated to `trackIds={[trackId]}`.
- 0 new dependencies. Bundle stays under 920 KB minified.
- `pnpm test`, `pnpm typecheck`, `pnpm build` all green. ~30 new tests, total ≥ 274.
- Manual smoke (§11.4) green against deployed prod API.

## 15. References

- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket F4.
- Backend prereq: [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) §5.9 (finalize endpoint), §5.8 (transfer endpoint, snapshot semantics), §6 (`finalize_block` repository signature), §7.7 (logging events).
- F2 prereq: [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — `useTriageBlocksByStyle`, `byStyle` cache, `pendingCreateRecovery` pattern (lesson 23).
- F3a prereq: [`2026-05-03-F3a-triage-detail-frontend-design.md`](./2026-05-03-F3a-triage-detail-frontend-design.md) — `MoveToMenu`, `BucketGrid`, `BucketCard`, `BucketDetailPage`, `useTriageBlock`, `useBucketTracks`, error-mapping pattern.
- F3b prereq: [`2026-05-03-F3b-triage-transfer-frontend-design.md`](./2026-05-03-F3b-triage-transfer-frontend-design.md) — `TransferModal`, `useTransferTracks`, `TransferBlockOption`, `BucketGrid mode='select'`.
- Pages catalog Pass 1: `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` — `P-20 Finalize` + `P-21 Blocked` (visual references).
- Pages catalog Pass 2: `docs/design_handoff/03 Pages catalog · Pass 2 (Curate-Patterns).html` — `S-04` style guide reference.
- API contract: `docs/openapi.yaml` path `/triage/blocks/{id}/finalize`. Response `{ block: TriageBlock, promoted: {<category_id>: <count>}, correlation_id }`. Error 409 body carries `inactive_buckets: [{id, category_id, track_count}]`. **Note:** spec-D narrative §5.9 says 422 `block_not_editable` but backend emits `invalid_state`. Tracked as `TD-12`.
- Project memory:
  - "tap-on-button, not DnD" (motivates D2 — bulk surface is a tap on a clearly-labelled button, not a drag gesture).
  - "Designer briefs need explicit edge cases" (motivates explicit blocker variant + empty-staging variant + cold-start recovery copy).
- Tokens: `docs/design_handoff/tokens.css`, `frontend/src/tokens.css`, `frontend/src/theme.ts`.

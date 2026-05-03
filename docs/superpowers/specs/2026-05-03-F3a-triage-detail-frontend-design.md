# F3a — Triage Detail + Bucket Browse + Move Frontend

**Date:** 2026-05-03
**Status:** brainstorm stage — design approved, awaiting implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F3** (split into F3a + F3b per brainstorming Q1).
**Backend prerequisite:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — already shipped to prod.
**Frontend prerequisites:**
- [`2026-05-01-F1-categories-frontend-design.md`](./2026-05-01-F1-categories-frontend-design.md) — F1 merged 2026-05-02.
- [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — F2 merged 2026-05-03.

**Successor blockers:** F3b Transfer (consumes the bucket detail view + move infra here), F4 Finalize (consumes the block detail header), F5 Curate (consumes block detail + the same hooks).

## 1. Context and Goal

F2 shipped triage `/triage/:styleId` (list / create / soft-delete) and a placeholder `TriageDetailStub` at `/triage/:styleId/:id`. F3a fills in the **block detail page**, **bucket detail page**, and **single-track move** within a block. Cross-block transfer (F3b) and finalize (F4) are out of scope for this spec.

After F3a ships, a logged-in user can:

- Open a triage block from the list → land on `TriageDetailPage` showing block summary (name, date range, status) and a grid of buckets: 5 technical (NEW / OLD / NOT / DISCARD / UNCLASSIFIED) + N STAGING (one per alive category) returned in the API order (technical fixed sort then STAGING by category position).
- Click a bucket → land on `BucketDetailPage` rendering a paginated track list with optional inline search.
- Reclassify a track via per-row Mantine `Menu` "Move to ▾" → optimistic update (row disappears immediately, source/target counters adjust) + Undo toast (5 s) → click Undo → reverse `move` call.
- Soft-delete the whole block via header kebab → `modals.openConfirmModal` → reuse `useDeleteTriageBlock` from F2 → navigate back to `/triage/:styleId`.
- Open a FINALIZED block → read-only view: bucket grid + track lists render, "Move to ▾" menu hidden, header shows `FINALIZED` badge + `finalized_at`.

Out of scope for F3a: cross-block transfer (F3b), finalize action (F4), bulk-select / multi-track move (potential F3 follow-up), Curate destination buttons (F5), Web Playback SDK (F6), block rename (backend not exposed), category management from triage (F1 territory).

## 2. Scope

**In scope:**

- Two new routes (one replaces the F2 stub, one new nested):
  - `/triage/:styleId/:id` → `TriageDetailPage` (replaces `TriageDetailStub`).
  - `/triage/:styleId/:id/buckets/:bucketId` → `BucketDetailPage`.
- New components under `features/triage/components/`: `TriageBlockHeader`, `BucketGrid`, `BucketCard`, `BucketBadge`, `BucketTracksList`, `BucketTrackRow`, `MoveToMenu`.
- New hooks: `useTriageBlock(blockId)`, `useBucketTracks(blockId, bucketId, search)` (`useInfiniteQuery`), `useMoveTracks(blockId)`.
- Optimistic move with rollback on error + Mantine notification "Undo" action (5 s timer) that calls `move` with `from`/`to` swapped.
- Per-row "Move to ▾" Mantine `Menu` — destinations = all non-current buckets except inactive STAGING.
- Soft-delete reused from F2 (`useDeleteTriageBlock`) wired into header kebab; navigation back to `/triage/:styleId` on success.
- Shared extract: `formatLength`, `formatAdded` from `features/categories/components/TrackRow.tsx` → `frontend/src/lib/formatters.ts`. F1 imports updated.
- i18n EN-only keys under `triage.detail.*`, `triage.bucket.*`, `triage.move.*`, `triage.bucket_type.*`. Domain terms (`NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED`, `STAGING`, `BPM`, `FINALIZED`) stay literal.
- Empty / loading / error states (§8).
- Vitest unit + integration tests (MSW); mirror F2 conventions (NODE_OPTIONS shim, jsdom shims, `notifications.clean()` between tests).

**Out of scope:**

- **F3b: cross-block transfer.** `POST /triage/blocks/{src_id}/transfer` consumed in a follow-up PR. Adds target-block picker + `style_mismatch` error case + cross-block cache invalidation.
- **F4: finalize.** `POST /triage/blocks/{id}/finalize` is rendered as a disabled placeholder button in the header with a `Tooltip` "Coming in F4". No mutation, no submenu.
- **Bulk-select / multi-track move.** Backend supports up to 1000 ids per `POST /move`, but UI exposes only single-track selection in F3a. `FUTURE-F3a-1`.
- **Re-classification (re-run R4) of an existing block.** Backend D14 forbids; not a UI feature.
- **Bucket rename / inactive bucket recovery / category-from-triage create.** F1 territory.
- **Web Playback SDK / preview / now-playing.** F6.
- **Mobile-specific picker variants (Drawer for "Move to ▾").** Default: Mantine `Menu` on both desktop and mobile.
- **Pagination beyond load-more.** No page numbers, no virtualisation.
- **UNCLASSIFIED help-tooltip.** `FUTURE-F3a-2`.
- **Spotify metadata enrichment / backfill triggers from UI.** Operational (`scripts/backfill_spotify_release_date.py`).
- **Block rename.** Backend not exposed (mirror F2 `FUTURE-F2-3`).

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Two-route master/detail layout.** `/triage/:styleId/:id` = block detail (header + bucket grid). Click bucket → push route `/triage/:styleId/:id/buckets/:bucketId` = bucket detail (track list). Mobile = same routing, just stacked layout. | Brainstorming Q2-A. Mirrors F1 `/categories/:styleId/:id` and F2 routing depth. Deep-link to bucket works. Master/detail two-pane (Q2-B) was rejected: more code, two layouts to test, mobile reverts to A anyway, real bulk-sort flow lives in F5 Curate. |
| D2 | **Per-row Mantine `Menu` "Move to ▾" — single-track move only.** No checkboxes, no sticky bulk-action bar. | Brainstorming Q3-A. F3 = review surface; bulk-sort lives in F5 Curate (destination buttons per design). Adding bulk-select would add ~2-3 days for a feature without confirmed demand. `FUTURE-F3a-1` covers later promotion. |
| D3 | **Optimistic move with Undo toast — no confirm modal.** On click: row disappears from source list, source `track_count` decremented, target `track_count` incremented, Mantine `notifications.show` with 5 s timeout and an "Undo" action. Click Undo → call `move` with `from_bucket_id`/`to_bucket_id` swapped + same `track_ids`. On Undo success: re-insert into source query cache (top of list — see D13), re-decrement target. On move-call error: rollback (re-insert source, restore counts) + red error toast. | Brainstorming Q4. Backend `move` is idempotent (D9 in spec-D — already-in-target tracks are silent no-op), so reverse-call works without backend support. Confirm modal (P-18 design) was rejected: legacy DnD+confirm pattern not aligned with project memory ("tap-on-button, not DnD") and adds friction to a frequent action. |
| D4 | **Bucket grid order = API order.** Spec-D §5.1 returns buckets sorted: technical fixed `NEW, OLD, NOT, UNCLASSIFIED, DISCARD`, then STAGING by `categories.position ASC, created_at DESC, id ASC`. Client preserves this order — no client-side re-sort. | Server is the source of truth. STAGING order matches the order F1 uses on the categories list, so users see consistent ordering across surfaces. |
| D5 | **Inactive STAGING bucket display.** Bucket card renders dimmed (`opacity: 0.5`) with `(inactive)` suffix in i18n label. Card is clickable — user can view tracks inside (read flow not blocked). However, the bucket is filtered out of the `MoveToMenu` destination list (move into inactive returns 409). Move out of an inactive bucket is allowed and exposed normally. | Spec-D D8 + D9: `inactive=true` blocks move-in only. UX surfaces this asymmetry without hiding tracks. Resolves D12-blocked-finalize via "move tracks out then finalize" flow that F4 will document. |
| D6 | **`MoveToMenu` destination list excludes:** the current bucket (no-op), inactive STAGING buckets (409). Submenu is flat (no grouping by tech/STAGING), in API order, with the bucket label rendered the same way as in the grid. | Flat list is faster to scan than grouped (≤ ~10 destinations typical). Visual parity between menu items and bucket cards reduces cognitive load. |
| D7 | **`useInfiniteQuery` + load-more for bucket tracks.** `limit=50`, `getNextPageParam` from `offset + items.length` while `total > offset + items.length`. Identical to F1/F2 pattern. | No virtualisation needed at MVP — typical bucket holds 5-200 tracks; load-more handles tail of UNCLASSIFIED if backfill produces large counts. |
| D8 | **Bucket search box** = controlled `TextInput` debounced 300 ms; `search` becomes part of the query key so each typed term creates a fresh cache. Empty string omits the param. | Spec-D §5.5 `?search=` filters on `clouder_tracks.title ILIKE '%term%'`. Debounce avoids N requests per keystroke. Cache fresh per term so rapid back-and-forth is instant. |
| D9 | **Block detail header actions** = single kebab menu, `Delete block` only. `Finalize` rendered as a disabled `Button` next to kebab with `Tooltip` "Coming in F4". | Soft-delete reuses F2 `useDeleteTriageBlock` + `modals.openConfirmModal` with body copy lifted from F2's `triage.delete_modal`. Disabled finalize button reserves the affordance so F4 is a one-line wiring change, not a layout reshuffle. |
| D10 | **FINALIZED status renders read-only.** Bucket grid + track lists render normally. `MoveToMenu` is hidden entirely (the kebab/`···` icon does not render on rows). Header shows a `Badge` `FINALIZED` + `finalized_at` formatted like F2. The kebab menu hides `Delete block` too — finalized blocks are an audit trail, not deletable from UI. (Backend allows soft-delete on any status; we choose to not expose it post-finalize.) | Spec-D D11: technical buckets become a historical record after finalize. Hiding mutations prevents accidental edits to a closed audit. Soft-delete of finalized blocks can be added later if user testing motivates it (`FUTURE-F3a-3`). |
| D11 | **Soft-deleted block = 404 from `GET /triage/blocks/{id}`** (backend filters by `deleted_at IS NULL`). Route loader detects 404 → throws → `RouteErrorBoundary` shows "Block not found" copy + link back to `/triage/:styleId`. | Mirror F1 detail-page-404 handling. No special "deleted" UX — race window is small; user just sees standard not-found. |
| D12 | **Track row content (desktop table, mobile card).** Fields rendered: `title` (+ `mix_name` muted), `artists.join(', ')`, `bpm`, formatted `length_ms`, `spotify_release_date` (key for explaining classification — show as `Released YYYY-MM-DD` or `—`), `is_ai_suspected` warning icon. Beatport `publish_date` is shown small/secondary in mobile-card variant only (helps explain OLD vs NEW discrepancy when Spotify and Beatport disagree). `release_type` and `spotify_id` are not displayed (informational only). | Spec-D bucket-track payload (§5.5) carries all these fields. Limiting columns keeps the table scannable. Beatport `publish_date` matters less per spec-D D5 (`spotify_release_date` is the classification source). |
| D13 | **Optimistic update strategy for `move`.** On click: (a) `setQueryData` on source `useInfiniteQuery` cache — remove track from the page where it appears, decrement `total` on every page (the `total` field is mirrored on every page response, so iterate); (b) `setQueryData` on the block detail cache to decrement source `track_count` and increment target `track_count` on the buckets array; (c) skip target list mutation — target list is sorted `added_at DESC, track_id ASC` and we don't have the new `added_at` until server responds. On `onSuccess`: invalidate target bucket's tracks query (so it refetches with the freshly added row). On Undo or error rollback: replay (a) and (b) in reverse using the snapshot taken before the optimistic write. Snapshots stored in the mutation's `onMutate` return value (TanStack Query convention). | Source list is what the user is staring at — must update instantly. Target list is "elsewhere" — refetch on success is fine. Rolling back from a snapshot is the standard TanStack pattern (`onMutate` → `onError`). Counters on the block detail need both source/target adjustments since the user often returns to the grid to see progress. |
| D14 | **Undo timing = Mantine `notifications.show({ autoClose: 5000 })` with custom action button.** Action button triggers the inverse mutation. After 5 s the notification auto-dismisses and undo is no longer possible. If user spam-clicks Undo while inverse mutation in flight, debounce via mutation `isPending` flag. If user navigates away mid-toast, the toast persists (notifications are global). Undo notification carries a stable `id` so a subsequent move toast doesn't accidentally invoke the previous undo action. | 5 s is the iOS/Material standard for undo bars. Stable id prevents callback bleed between back-to-back moves. Persist-across-nav matches F2 503 toast behaviour and is a non-issue in practice. |
| D15 | **Cold-start UX.** GET endpoints (`block detail`, `bucket tracks`) rely on the existing `apiClient` cold-start retry. No special scheduler (unlike F2 create's pending-recovery). On terminal 503 from GET → `RouteErrorBoundary` with retry button. On terminal 503 from `POST /move` → red toast + rollback (treat as ordinary error). | Reads have no idempotency-key concern, so apiClient retry suffices. Move-on-503 is rare and a retry is a click on the same row — no auto-retry needed. |
| D16 | **No new shared extracts beyond `formatters`.** `BucketBadge`, `BucketCard`, `BucketTrackRow` stay in `features/triage/components/`. F4 finalize will not need `BucketTrackRow`; F5 Curate will rebuild its own track-card UI per design (P-22 / P-23). When a third consumer arrives, promote per F2 D14 dependency direction. | YAGNI. F2 promoted `StyleSelector` + `useStyles` because two features needed them simultaneously (F1 + F2). F3a triage components have one consumer today. |
| D17 | **`useTriageBlock(blockId)`** = single-record `useQuery`, `staleTime: 30s`. Invalidated on move success (counts changed), block-soft-delete (no longer relevant), and any cross-tab cache invalidation. | `useQuery` is cheap and the response is small (~5–20 buckets, no track lists). 30 s staleTime prevents grid bouncing during rapid back-nav. |
| D18 | **`useBucketTracks(blockId, bucketId, search)`** = `useInfiniteQuery`, `gcTime: 5min`. After a move, the source query is mutated optimistically (D13); after move success, target query is invalidated (D13). | Long gcTime keeps source list warm during typical Undo window. |
| D19 | **Query keys.** Reserve under the existing `'triage'` namespace: `['triage', 'blockDetail', blockId]`, `['triage', 'bucketTracks', blockId, bucketId, searchTerm]`. F2 uses `['triage', 'byStyle', styleId, status]` and `['triage', 'detail', blockId]` (the latter was reserved-but-unused; **F3a renames it to `'blockDetail'`** to be explicit). F2 had no real consumer of the reserved key, so this is a 1-line change to `useTriageBlocksByStyle.ts` if anything references it (none today). | Per-segment cache isolation. Searching does not invalidate the no-search cache. |
| D20 | **Cross-cache invalidation on move success.** `useMoveTracks.onSuccess` invalidates: target `bucketTracks`, the `blockDetail` (counts), and `byStyle` for the block's style (because `track_count` on the list summary may need updating). Source `bucketTracks` is not invalidated — optimistic write already reflects truth. | Surgical invalidation; avoids needless refetch of the source bucket. |
| D21 | **Cross-cache invalidation on block soft-delete.** Reuse F2 `useDeleteTriageBlock` invalidation (already covers `byStyle` for all 3 tabs). Additionally, the F3a header soft-delete navigates back to `/triage/:styleId` on success. | Mirror F2; nav prevents user from staring at a now-deleted block. |
| D22 | **PR shape.** Single PR `feat/triage-detail-move` from `main`, sequential caveman-commits per natural boundary, merge `--no-ff`. Mirror F2 D19. | Solo dev workflow; same delivery shape that worked in F1 + F2. |
| D23 | **Bundle additions: none.** All deps (`@mantine/*`, `@tanstack/react-query`, `dayjs`) are already shipped. `@tabler/icons-react` icons already re-exported via `frontend/src/components/icons.ts`; F3a adds 2-3 new re-exports there. | Zero new deps; bundle stays under 700 KB minified target. |
| D24 | **Disabled-state semantics.** Inactive STAGING bucket card is dimmed but clickable to read tracks. The "Finalize" button placeholder is disabled (`<Button disabled>` + Tooltip "Coming in F4"). In a FINALIZED block, the kebab `Delete block` is hidden. The "Move to ▾" item in `MoveToMenu` for the current bucket is omitted (not disabled — there is nothing useful to convey). | Explicit semantic mapping: dimmed = "you can read but not move-into", disabled = "this control exists but is not active yet", hidden = "irrelevant for this state". |

## 4. UI Surface

### 4.1 Routes

```
/triage/:styleId/:id                          → TriageDetailPage      (P-16)
/triage/:styleId/:id/buckets/:bucketId        → BucketDetailPage      (P-17)
```

`/triage/:styleId/:id` invalid UUID or block not found → `RouteErrorBoundary` (404 page).
Bucket UUID not in the block → 404 from `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` → `RouteErrorBoundary`.

The legacy `TriageDetailStub` component is **deleted**; `routes/router.tsx` swaps to `TriageDetailPage` and registers the new nested `buckets/:bucketId` route.

### 4.2 TriageDetailPage (P-16)

Layout (desktop ≥ 64em):

```
[← Back to triage]                                              ← Link "All blocks for {styleName}"
[TriageBlockHeader]
   ├─ Title (block.name)                                        ← editable in FUTURE-F2-3
   ├─ Subtitle: "{date_from} → {date_to} · STATUS · created {relative}"
   ├─ Right: [Finalize ▾ disabled]  [···  kebab → Delete block]
   └─ FINALIZED variant: badge, no Finalize button, no kebab
[BucketGrid]
   3-column grid on desktop, 2-column ≥ 36em mobile, 1-column < 36em
   Each cell: <BucketCard>
       ├─ <BucketBadge bucketType={…} categoryName={…} inactive={…}/>
       ├─ track_count (mono font)
       └─ aria-label "Open bucket {label}"
       (entire card is a <Link to=`/triage/:styleId/:id/buckets/:bucketId`>)
```

Mobile (< 64em): same components, header stacks (title above subtitle above actions row), bucket grid collapses to 1- or 2-column based on width.

### 4.3 BucketDetailPage (P-17)

Layout:

```
[← Back to {block.name}]                                        ← Link to /triage/:styleId/:id
[Header]
   ├─ <BucketBadge.../> + bucket label (large)
   ├─ Subtitle: "{track_count} tracks · {block.name} · {block.date_from} → {block.date_to}"
   └─ Right: [TextInput "Search tracks…" 300ms debounce]
[BucketTracksList]
   Desktop: <Table> with columns [Title, Artists, BPM, Length, Released, Action]
   Mobile: <Stack gap="sm"> of <Card>s, with action button at bottom right
   Last column / card-corner: <MoveToMenu trackId={…} sourceBucketId={…} block={block}/>
   Hidden when block.status === 'FINALIZED' (D10)
[Load more button]                                              ← shown while total > shown
```

Empty / loading / error states detailed in §8.

### 4.4 MoveToMenu (component)

```
Trigger: <ActionIcon><IconDotsVertical/></ActionIcon>          ← desktop
         OR full-width <Button leftSection="Move to ▾"/>       ← mobile (one per card)
Mantine <Menu position="bottom-end">
  <Menu.Label>Move to</Menu.Label>
  ...for each destination in (block.buckets - currentBucket - inactiveStaging):
     <Menu.Item leftSection={<BucketBadge inline.../>} onClick={…}>
        {bucketLabel(d)}
     </Menu.Item>
```

Click → `useMoveTracks(blockId).mutate({ from, to, track_ids: [trackId] })`.

### 4.5 TriageBlockHeader (component)

```
<Stack gap="sm">
  <Group justify="space-between" wrap="nowrap">
    <Stack gap={2}>
      <Title order={2}>{block.name}</Title>
      <Group gap="xs">
        <Text c="dimmed" size="sm">{date_from} → {date_to}</Text>
        <Badge>{status}</Badge>                                ← STATUS literal (NEW etc not relevant here, "IN_PROGRESS" or "FINALIZED")
        <Text c="dimmed" size="sm">created {relative}</Text>
        {finalized_at ? <Text c="dimmed" size="sm">finalized {relative}</Text> : null}
      </Group>
    </Stack>
    {status === 'IN_PROGRESS' ? (
      <Group gap="xs">
        <Tooltip label={t('triage.detail.finalize_coming_soon')}>
          <Button disabled>{t('triage.detail.finalize_cta')}</Button>
        </Tooltip>
        <Menu>
          <Menu.Target><ActionIcon variant="subtle"><IconDots/></ActionIcon></Menu.Target>
          <Menu.Dropdown>
            <Menu.Item color="red" onClick={onDelete}>{t('triage.detail.kebab.delete')}</Menu.Item>
          </Menu.Dropdown>
        </Menu>
      </Group>
    ) : null}
  </Group>
</Stack>
```

## 5. Component Catalog

| Component | Anatomy | Mantine base | Owner |
|---|---|---|---|
| `TriageDetailPage` | Back link + Header + BucketGrid | `Container`, `Stack`, `Group` | F3a |
| `BucketDetailPage` | Back link + Header + Search + BucketTracksList + LoadMore | `Container`, `Stack`, `Table` | F3a |
| `TriageBlockHeader` | Title + meta + Finalize-disabled + kebab | `Stack`, `Group`, `Title`, `Badge`, `Tooltip`, `Button`, `Menu` | F3a |
| `BucketGrid` | Responsive grid of BucketCard | `SimpleGrid` | F3a |
| `BucketCard` | Link card with badge + count | `Card`, `Anchor` (component={Link}) | F3a |
| `BucketBadge` | Small label "NEW" / "Tech House (staging)" / "(inactive)" suffix | `Badge` or `Text` | F3a |
| `BucketTracksList` | Desktop `Table` / mobile `Stack<Card>` switched by `useMediaQuery('(min-width: 64em)')` | `Table`, `Stack` | F3a |
| `BucketTrackRow` | Single-row anatomy: title + artists + bpm + length + released + ai-warning + MoveToMenu | `Table.Tr` (desktop) / `Card` (mobile) | F3a |
| `MoveToMenu` | Per-row `Menu` with destination items | `ActionIcon` or `Button` + `Menu` | F3a |
| `RouteErrorBoundary` | Existing — reuse for 404 handling | — | reused |
| `EmptyState` | Existing — reuse for empty buckets / search miss | — | reused |
| `FullScreenLoader` | Existing — reuse for block detail loading | — | reused |

`BucketCard` is wrapped in `<Link>` (router); keyboard activation works without extra wiring.

`BucketTrackRow` (D12) is a new component because the bucket-track payload shape (`artists: string[]`, plus extra fields `spotify_release_date`, `spotify_id`, `release_type`, `publish_date`, `isrc`) differs from F1's `CategoryTrack` (`artists: { name }[]`). Sharing a row component would force a discriminated union and obscure the difference — `FUTURE-F3a-4` if a third consumer appears.

## 6. Data Flow

### 6.1 React-query keys

```ts
// Existing (from F1 + F2):
['styles']
['triage', 'byStyle', styleId, status]
['categories', ...]                                     // F1 namespace

// F3a additions:
['triage', 'blockDetail', blockId]                      // useTriageBlock
['triage', 'bucketTracks', blockId, bucketId, search]   // useBucketTracks (search='' → omit param)
```

`'triage', 'detail'` — reserved-but-unused string in F2 §6.1 — is renamed to `'blockDetail'` (D19). No production reference in F2 today; one-line comment update only.

### 6.2 Hooks

| Hook | Endpoint | Notes |
|---|---|---|
| `useTriageBlock(blockId)` | `GET /triage/blocks/{id}` | `useQuery`, `staleTime: 30s`. Throws on 404 → caught by route boundary. |
| `useBucketTracks(blockId, bucketId, search)` | `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks?limit=50&offset=&search=` | `useInfiniteQuery`. `getNextPageParam` from `offset + items.length` while `total > offset + items.length`. `search === ''` omits the param. `gcTime: 5min`. |
| `useMoveTracks(blockId)` | `POST /triage/blocks/{id}/move` | `useMutation`. Optimistic write + Undo (D3, D13, D14). |
| `useDeleteTriageBlock(styleId)` | reused F2 hook | Used by `TriageBlockHeader` kebab. |

### 6.3 Optimistic move (`useMoveTracks`)

```ts
type MoveInput = {
  fromBucketId: string;
  toBucketId: string;
  trackIds: string[];          // F3a always sends single-element array; D2
}

useMutation({
  mutationFn: (input) => apiClient.post(`/triage/blocks/${blockId}/move`, {
    from_bucket_id: input.fromBucketId,
    to_bucket_id:   input.toBucketId,
    track_ids:      input.trackIds,
  }),
  onMutate: async (input) => {
    // 1. Cancel in-flight queries that we're about to mutate.
    await qc.cancelQueries({ queryKey: ['triage','bucketTracks', blockId, input.fromBucketId] });
    await qc.cancelQueries({ queryKey: ['triage','blockDetail', blockId] });

    // 2. Snapshot for rollback.
    const sourceSnapshot = qc.getQueriesData({ queryKey: ['triage','bucketTracks', blockId, input.fromBucketId] });
    const blockSnapshot  = qc.getQueryData(['triage','blockDetail', blockId]);

    // 3. Optimistic source mutation: drop track from each page, decrement total on every page.
    qc.setQueriesData({ queryKey: ['triage','bucketTracks', blockId, input.fromBucketId] }, (old) => {
      if (!old) return old;
      return {
        ...old,
        pages: old.pages.map((p) => ({
          ...p,
          items: p.items.filter((t) => !input.trackIds.includes(t.track_id)),
          total: Math.max(0, p.total - input.trackIds.length),
        })),
      };
    });

    // 4. Optimistic block-detail mutation: adjust bucket counts.
    qc.setQueryData(['triage','blockDetail', blockId], (old) => {
      if (!old) return old;
      return {
        ...old,
        buckets: old.buckets.map((b) => {
          if (b.id === input.fromBucketId) return { ...b, track_count: Math.max(0, b.track_count - input.trackIds.length) };
          if (b.id === input.toBucketId)   return { ...b, track_count: b.track_count + input.trackIds.length };
          return b;
        }),
      };
    });

    return { sourceSnapshot, blockSnapshot };
  },
  onError: (_err, _input, ctx) => {
    // Rollback.
    ctx?.sourceSnapshot.forEach(([key, val]) => qc.setQueryData(key, val));
    if (ctx?.blockSnapshot) qc.setQueryData(['triage','blockDetail', blockId], ctx.blockSnapshot);
    notifications.show({ message: t('triage.move.toast.error'), color: 'red' });
  },
  onSuccess: (_data, input) => {
    // Target list refetch (we don't know the new added_at).
    qc.invalidateQueries({ queryKey: ['triage','bucketTracks', blockId, input.toBucketId] });
    // Block detail double-check (counts already adjusted optimistically; refetch confirms).
    qc.invalidateQueries({ queryKey: ['triage','blockDetail', blockId] });
    // List summary in the F2 list page.
    qc.invalidateQueries({ queryKey: ['triage','byStyle', styleId] });
  },
});
```

### 6.4 Undo flow

```ts
function showMoveSuccessToast(input: MoveInput, label: { from: string; to: string }) {
  const id = `triage-move-${Date.now()}-${input.trackIds[0]}`;
  notifications.show({
    id,
    message: t('triage.move.toast.moved', { count: input.trackIds.length, to: label.to }),
    color: 'green',
    autoClose: 5000,
    withCloseButton: true,
    // Mantine notifications support an action via `withCloseButton: false` + custom render.
    // Our convention: render a small inline UndoButton inside `message`.
    // Pseudocode — actual render uses a React node passed to `message`.
  });
}

// UndoButton internals:
//   onClick:
//     1. notifications.hide(id)                         // stop the auto-close timer
//     2. Restore the original snapshot synchronously     // no flicker; reverses optimistic write
//        ctx.sourceSnapshot.forEach(...) + ctx.blockSnapshot
//     3. Fire inverse HTTP call directly via apiClient.post (NOT through useMoveTracks.mutate
//        — going through the hook would trigger a second onMutate cycle and refetch flicker).
//     4. On HTTP success: notifications.show({ message: t('triage.move.toast.undone'), color: 'green' }).
//     5. On HTTP error:   re-apply the optimistic write (track-was-moved state) +
//                         notifications.show({ message: t('triage.move.toast.undo_failed'), color: 'red' }).
//   - Debounced via local React state (in-flight ref); click while in flight → no-op.
```

The undo handler is built in the same hook (`useMoveTracks`) closure so it can reuse the snapshot machinery for the inverse mutation (which is just another optimistic move with swapped bucket ids).

### 6.5 Route loaders vs query-on-mount

Use **query-on-mount** for both pages — no react-router loader. Same pattern as F1 `CategoryDetailPage`. Loading state from `useTriageBlock` gates rendering; throw on 404 so `RouteErrorBoundary` catches.

`requireAuth` loader on the parent `AppShellLayout` route already gates auth — no per-route auth guard needed.

### 6.6 Navigation

- Click bucket card → `<Link to={`/triage/${styleId}/${blockId}/buckets/${bucketId}`}>`. No state passed; `BucketDetailPage` reads `:bucketId` from params and reads block + bucket from `useTriageBlock` cache (already warm from grid render).
- "← Back to {block.name}" on bucket detail → `<Link to={`/triage/${styleId}/${blockId}`}>`.
- "← Back to triage" on block detail → `<Link to={`/triage/${styleId}`}>`.
- After successful soft-delete → `useNavigate()` to `/triage/${styleId}` + green toast.

Browser back button works naturally (separate routes, history stack honoured).

## 7. Validation

F3a has no forms (no create / rename / etc.). The only client-side validation is:

- **Move destination derivation** (D6): `MoveToMenu` filters out current bucket and inactive STAGING in the component itself. Backend defends additionally (409 on inactive target) but client should never trigger that path.
- **Search input**: trim leading/trailing whitespace before sending; empty → omit param. No length limit (backend caps internally).

No Zod schemas needed.

## 8. Error / Empty / Loading UX Mapping

| State | Surface | UX |
|---|---|---|
| Block detail loading | TriageDetailPage | `FullScreenLoader` until first response. |
| Block detail 404 (`triage_block_not_found`) | TriageDetailPage | Throw → `RouteErrorBoundary` → "Block not found" copy + "Back to triage" link. |
| Block detail 503 terminal | TriageDetailPage | `RouteErrorBoundary` "Service unavailable, try again" + retry button. |
| Block detail unknown 5xx | TriageDetailPage | Same as 503. |
| Bucket grid all counts == 0 | TriageDetailPage | Bucket cards still render (track_count=0). EmptyState shown only if `block.buckets.length === 0` — never in practice (5 tech buckets always created). |
| Bucket tracks loading | BucketDetailPage | `FullScreenLoader` overlay above the empty table during initial load. |
| Bucket tracks 404 (`bucket_not_found`) | BucketDetailPage | `RouteErrorBoundary` "Bucket not found" + back link. |
| Bucket tracks empty (no tracks, no search) | BucketDetailPage | EmptyState `triage.bucket.empty.no_tracks` (per bucket type — UNCLASSIFIED gets a custom hint copy). |
| Bucket tracks empty (search miss) | BucketDetailPage | EmptyState `triage.bucket.empty.search_miss` with "Clear search" action. |
| Move 200 OK | row disappears optimistically (D13) | Green toast `triage.move.toast.moved` with Undo action (5s). |
| Move 404 (`triage_block_not_found` / `bucket_not_found` / `tracks_not_in_source`) | row | Rollback + red toast `triage.move.toast.stale_state` + invalidate `blockDetail` + `bucketTracks(source)`. |
| Move 409 (`invalid_state` / `inactive_bucket`) | row | Rollback + red toast `triage.move.toast.invalid_target` + invalidate `blockDetail`. |
| Move 422 | row | Rollback + red toast `triage.move.toast.error`. Should not happen (client mirrors backend). |
| Move 503 terminal | row | Rollback + red toast `errors.network`. No auto-recovery (D15). |
| Soft-delete success | header kebab | `useNavigate('/triage/' + styleId)` + green toast (reuse F2 `triage.toast.deleted`). |
| Soft-delete 404 | header kebab | Toast `triage.toast.delete_not_found` + navigate back (reuse F2). |
| Undo success | toast | Green `triage.move.toast.undone`. |
| Undo failure | toast | Red `triage.move.toast.undo_failed`. State left as-was (the original move succeeded, undo did not, so the track is in the target — UI already shows that). |

Toasts use `@mantine/notifications` (top-right, configured in A2). All red-toast paths invalidate the relevant queries to converge UI with server truth.

## 9. Code Layout

### 9.1 New files

```
frontend/src/features/triage/
├── routes/
│   ├── TriageDetailPage.tsx                       # NEW (replaces TriageDetailStub)
│   └── BucketDetailPage.tsx                       # NEW
├── components/
│   ├── TriageBlockHeader.tsx                      # NEW
│   ├── BucketGrid.tsx                             # NEW
│   ├── BucketCard.tsx                             # NEW
│   ├── BucketBadge.tsx                            # NEW
│   ├── BucketTracksList.tsx                       # NEW
│   ├── BucketTrackRow.tsx                         # NEW
│   ├── MoveToMenu.tsx                             # NEW
│   └── __tests__/
│       ├── TriageBlockHeader.test.tsx
│       ├── BucketCard.test.tsx
│       ├── BucketGrid.test.tsx
│       ├── BucketTrackRow.test.tsx
│       └── MoveToMenu.test.tsx
├── hooks/
│   ├── useTriageBlock.ts                          # NEW
│   ├── useBucketTracks.ts                         # NEW
│   ├── useMoveTracks.ts                           # NEW
│   └── __tests__/
│       ├── useTriageBlock.test.tsx
│       ├── useBucketTracks.test.tsx
│       └── useMoveTracks.test.tsx
├── lib/
│   └── bucketLabels.ts                            # NEW — bucketLabel(bucket), moveDestinationsFor(block, currentBucketId)
│   └── __tests__/
│       └── bucketLabels.test.ts
└── __tests__/
    ├── TriageDetailPage.integration.test.tsx
    └── BucketDetailPage.integration.test.tsx
```

### 9.2 Refactor — extract shared formatters

```
frontend/src/lib/formatters.ts                     # NEW
frontend/src/lib/__tests__/formatters.test.ts      # NEW
```

`formatters.ts` exports `formatLength(ms)`, `formatAdded(iso)`, and a new `formatReleaseDate(iso | null)`. F1's `features/categories/components/TrackRow.tsx` imports the first two from the new location instead of declaring them inline. The original local declarations are removed (mechanical: 2 lines deleted, 1 import added).

### 9.3 Modified files

- `frontend/src/routes/router.tsx` — add nested route `:styleId/:id/buckets/:bucketId → BucketDetailPage`; replace `TriageDetailStub` import with `TriageDetailPage`. Delete the import of `TriageDetailStub`.
- `frontend/src/features/triage/routes/TriageDetailStub.tsx` — **deleted**.
- `frontend/src/features/triage/index.ts` — re-export `TriageDetailPage` and `BucketDetailPage`.
- `frontend/src/components/icons.ts` — verified existing re-exports cover `IconDots`, `IconDotsVertical`, `IconAlertTriangle`, `IconArrowLeft`. Add `IconSearch` for the bucket-detail search-input `leftSection`.
- `frontend/src/features/categories/components/TrackRow.tsx` — replace inline `formatLength` / `formatAdded` with imports from `@/lib/formatters` (D9.2).
- `frontend/src/i18n/en.json` — add `triage.detail.*`, `triage.bucket.*`, `triage.move.*`, `triage.bucket_type.*` namespaces (§10).

### 9.4 No backend changes

Confirmed: spec-D ships `GET /triage/blocks/{id}`, `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks`, `POST /triage/blocks/{id}/move`. Already in `frontend/src/api/schema.d.ts` (F2 round). `pnpm api:types` not needed.

## 10. i18n Keys

Add under `frontend/src/i18n/en.json` (mirror F2 layout; RU lands in iter-2b):

```json
{
  "triage": {
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
  }
}
```

Bucket type literal labels (`NEW`, `OLD`, `NOT`, `DISCARD`, `UNCLASSIFIED`, `FINALIZED`) stay literal per CLAUDE.md memory — rendered directly from `bucket.bucket_type` without translation. Domain terms (`BPM`, `STAGING`) likewise.

Pluralisation uses i18next ICU (`_one` / `_other`).

## 11. Testing

### 11.1 Unit (Vitest + Testing Library)

`frontend/src/lib/__tests__/formatters.test.ts`:
- `formatLength(0)` → `'0:00'`. `formatLength(null)` → `'—'`. `formatLength(135_000)` → `'2:15'`. `formatLength(59_999)` → `'1:00'` (Math.round).
- `formatAdded` returns ISO-date-formatted localised string (snapshot-style, locale-stable).
- `formatReleaseDate(null)` → `'—'`. `formatReleaseDate('2026-04-15')` → `'2026-04-15'` (strict ISO display).

`features/triage/lib/__tests__/bucketLabels.test.ts`:
- `bucketLabel({type:'NEW'})` → `'NEW'`. `bucketLabel({type:'STAGING', categoryName:'Tech House'})` → `'Tech House (staging)'`. Inactive STAGING → `'Tech House (staging, inactive)'`.
- `moveDestinationsFor(block, currentBucketId)` returns all buckets except current and inactive STAGING, in API order.

`features/triage/components/__tests__/BucketCard.test.tsx`:
- Renders type badge + count + link to `/triage/{styleId}/{blockId}/buckets/{bucketId}`.
- STAGING variant renders category name. Inactive STAGING renders dimmed (opacity 0.5 via class assertion).
- Clicking card triggers navigation (assert via memory-router `Routes`).

`features/triage/components/__tests__/BucketGrid.test.tsx`:
- Renders all buckets in API order (no client re-sort).
- 3-col on desktop, 2-col on tablet, 1-col on narrow (assert via SimpleGrid `cols` prop).

`features/triage/components/__tests__/BucketTrackRow.test.tsx`:
- Desktop variant: renders title, mix_name muted, artists.join, bpm/—, formatLength, spotify_release_date, AI warning icon.
- Mobile variant: same fields plus publish_date as muted secondary.
- IN_PROGRESS block → MoveToMenu visible. FINALIZED → MoveToMenu hidden.

`features/triage/components/__tests__/MoveToMenu.test.tsx`:
- Destination list excludes current bucket + inactive STAGING.
- Click destination → calls `useMoveTracks.mutate` with correct shape.
- Empty destination list (only current + all-inactive) → menu trigger disabled or hidden (decide implementation; test verifies UX is not a "click reveals nothing" trap).

`features/triage/components/__tests__/TriageBlockHeader.test.tsx`:
- IN_PROGRESS variant: renders Title, date range, status badge, Finalize-disabled, kebab.
- FINALIZED variant: shows finalized badge + finalized_at relative time, no Finalize button, no kebab.
- Click kebab → Delete → opens `modals.openConfirmModal` with F2-style copy.
- Tooltip "Coming in F4" present on disabled Finalize button.

`features/triage/hooks/__tests__/useTriageBlock.test.tsx`:
- Happy 200 → returns block shape with buckets array.
- 404 → throws (caught by route boundary in integration; here just assert error state).
- 503 → existing apiClient retry semantics (mock retry, then resolution).

`features/triage/hooks/__tests__/useBucketTracks.test.tsx`:
- First page renders with `total` and `items`. Next page button hidden when `total ≤ shown`.
- Search '' omits the param. Search 'foo' adds `?search=foo` and creates separate cache.
- Debounce: rapid input collapses into one fetch (test with fake timers).

`features/triage/hooks/__tests__/useMoveTracks.test.tsx`:
- Happy: optimistic source removal + count adjust. On success: target invalidated.
- Error 404 → rollback both caches; red toast shown.
- Error 409 → rollback; "invalid target" toast.
- Snapshot/rollback survives concurrent in-flight mutations on different rows.
- Undo: subsequent mutation with swapped from/to fired; second snapshot taken.

### 11.2 Integration (Vitest + MSW)

`features/triage/__tests__/TriageDetailPage.integration.test.tsx`:

1. **Happy render.** Mock GET `/triage/blocks/{id}` → block with 5 tech + 2 STAGING (one inactive). Page renders header, 7 bucket cards, inactive dimmed. `← Back to triage` link present.
2. **Navigate to bucket.** Click NEW card → URL changes to `/triage/{style}/{block}/buckets/{newId}`; `BucketDetailPage` mounts.
3. **Soft-delete from kebab.** Click kebab → Delete → confirm → DELETE call → navigate back to `/triage/{style}` + green toast.
4. **FINALIZED variant.** Mock block with status FINALIZED → no Finalize button, no kebab, finalized_at displayed. Bucket cards still clickable.
5. **404 path.** Mock GET 404 → `RouteErrorBoundary` "Block not found" copy + "Back to triage" link.
6. **503 terminal.** Mock GET 503 (after retry exhausted) → service-unavailable error copy.

`features/triage/__tests__/BucketDetailPage.integration.test.tsx`:

1. **Happy render + load-more.** Mock `bucketTracks` with `total=120, limit=50`. First 50 render. "Load more" appears. Click → next 50 fetch + append.
2. **Search debounce.** Type "foo" → wait 300ms → request with `?search=foo`. Type more → debounce keeps to one request per pause.
3. **Move happy.** Click "Move to ▾" on row 1 → click "Tech House (staging)" → row disappears immediately, source counter -1, target counter +1. Green toast with Undo. Network call resolves → no rollback.
4. **Undo.** Click Undo within 5s → row reappears in source (after target invalidate refetches), counters revert. Green "Undone" toast.
5. **Move error rollback (409 inactive_bucket).** Force-include an inactive STAGING destination via mock (defensive — UI normally filters). Click → mock 409 → rollback (row reappears) + red toast "invalid target".
6. **FINALIZED variant.** Block status FINALIZED → MoveToMenu omitted from rows; no kebab; tracks render read-only.
7. **Empty bucket.** Mock 0 items → EmptyState `no_tracks_title`. UNCLASSIFIED variant → variant-specific body copy.
8. **Search miss.** Mock 0 items + search='xyz' → EmptyState `search_miss_title` with "Clear search" → click clears input + refetches.
9. **Bucket 404.** Mock 404 on GET tracks → `RouteErrorBoundary` "Bucket not found".
10. **Inactive STAGING source.** Bucket itself inactive (clickable per D5) → tracks render normally; MoveToMenu still works (move OUT of inactive is allowed).

### 11.3 Test infra (mirror F2)

- `notifications.clean()` in `beforeEach` and `afterEach` per F2 lesson 20.
- `gcTime: Infinity` on the test QueryClient (F2 lesson 6).
- `notifyManager.setScheduler(queueMicrotask)` already set in `setup.ts` (A2).
- `NODE_OPTIONS=--no-experimental-webstorage` already in test scripts (F2 / F1).
- All five jsdom shims in `setup.ts` already in place (F2 lesson 16).
- Mantine `Menu` `transitionProps={{ duration: 0 }}` in test theme already configured (F2 lesson 5).
- `userEvent` + real timers for the move + Undo test path; fake timers ONLY for the search-debounce test (per F2 lesson 19).

### 11.4 No E2E

Playwright (CC-2 in roadmap) deferred. Manual smoke before merge:

1. Sign in.
2. `Triage` sidebar → land on style → list shows F2 blocks.
3. Click a block row → land on `TriageDetailPage`. Header + bucket grid render.
4. Click NEW bucket → tracks render. Search a known title.
5. Move a track NEW → DISCARD → Undo. Verify counters bounce.
6. Move a track NEW → STAGING. Verify counter on target STAGING bucket increments.
7. Soft-delete from header kebab → land back on `/triage/{style}` + toast.
8. Open a FINALIZED block (create one in DB by manually finalizing via Postman until F4) → MoveMenu absent, kebab absent.

### 11.5 Coverage target

No numeric gate. Every hook ≥ 1 unit test, every page ≥ 1 happy-path integration test, every red-toast path ≥ 1 test (per §8 mapping). Existing F1 + F2 tests (~130 after F2 ship) stay green; F3a adds ~30 tests.

## 12. Delivery

1. Branch `feat/triage-detail-move` from `main` in worktree (already in `f3_task`).
2. Sequential commits per natural boundary, all messages from `caveman:caveman-commit`:
   - `formatters.ts` extract + F1 import update
   - `bucketLabels.ts` helpers + tests
   - hooks scaffold (`useTriageBlock`, `useBucketTracks`, `useMoveTracks`)
   - components scaffold (`BucketBadge`, `BucketCard`, `BucketGrid`, `TriageBlockHeader`, `BucketTrackRow`, `BucketTracksList`, `MoveToMenu`)
   - `TriageDetailPage` route
   - `BucketDetailPage` route
   - router wiring + `TriageDetailStub` deletion
   - i18n keys
   - integration tests
3. `pnpm test` green, `pnpm build` green.
4. `pnpm dev` manual smoke against deployed prod API (§11.4).
5. `git checkout main && git merge feat/triage-detail-move --no-ff && git push origin main`.
6. Roadmap update: append F3a lessons section, mark F3a row shipped (and reference F3b as still pending).

CI runs on push to `main`.

## 13. Open Items, Edge Cases, Future Flags

### 13.1 Edge cases worth a comment

- **Concurrent moves on the same row.** User clicks Move on row A while a previous move (also row A) is in flight. Mutation cancels in-flight via `qc.cancelQueries` (D13 step 1); the second snapshot may not reflect the first's optimistic write if the order races. Acceptable: mutations are serialised by react-query per `mutationKey` if we add one (`mutationKey: ['move', blockId, trackId]`). Implement.
- **Optimistic write while target query is GC'd.** If user opens NEW bucket, moves to Tech House (never visited that bucket detail), the `bucketTracks` cache for Tech House doesn't exist. `setQueryData` on a non-existent key is a no-op; `invalidateQueries` on a non-existent key is also a no-op. Counters update via `blockDetail` cache. Correct behaviour.
- **Move triggers FINALIZED block 409.** User opens an IN_PROGRESS block, another tab finalizes it, user moves a track → `invalid_state` 409 → rollback + invalidate `blockDetail` → re-render now shows FINALIZED variant (MoveMenu disappears). Test 5 in §11.2 covers an analogous case.
- **Bucket deleted between block-fetch and bucket-fetch.** Categories soft-delete in F1 marks the STAGING `inactive=true`; the bucket itself is not deleted. So `bucket_not_found` only happens for an invalid `:bucketId` URL — typical user path can't trigger.
- **Undo after navigation away from BucketDetailPage.** Notifications are global; Undo button works even after user navigates back to TriageDetailPage. Inverse mutation invalidates target (now stale); user sees correct state on bucket re-visit.
- **Search query containing `%` or `_`.** Backend handles ILIKE escaping per spec-D §5.5. Client sends raw user text.
- **Block detail `created` time in the past — locale rendering.** `dayjs.fromNow()` already i18n'd via `dayjs/plugin/relativeTime` (F2 dependency). RU plural forms ship in iter-2b.
- **Bucket-detail subtitle counts.** Use `total` from latest infinite-query first page, not summed across pages (avoids double-counting on undo refresh).
- **First-bucket-of-empty-block visit.** A freshly created block with all 5 tech buckets at count 0 renders 5 cards with 0 each. Bucket detail shows EmptyState. Expected.
- **Race: user clicks Undo at the exact 5s boundary.** If Mantine has dispatched the auto-close animation, the Undo button is unmounted; click does nothing. Acceptable; matches platform conventions.

### 13.2 Future flags (post-iter-2a)

- **`FUTURE-F3a-1`** — bulk-select + sticky-bar move. Add when DJ feedback says single-track-only is too slow. Requires checkbox column, selection state hoist to BucketDetailPage, sticky footer (mobile = drawer).
- **`FUTURE-F3a-2`** — UNCLASSIFIED help-tooltip explaining Spotify-enrichment dependency.
- **`FUTURE-F3a-3`** — soft-delete a FINALIZED block. Backend allows; UI hides today (D10).
- **`FUTURE-F3a-4`** — extract `BucketTrackRow` to a shared component when F5 Curate or another consumer needs it.
- **`FUTURE-F3a-5`** — virtualised bucket-tracks list for very large UNCLASSIFIED buckets (1000+) once backfill produces them.
- **`FUTURE-F3a-6`** — keyboard hotkeys for move (e.g. `1`–`6` like Curate's design). Out of scope: F3 is mouse / tap, Curate is the keyboard surface.

### 13.3 Cross-ticket dependencies

- **F3b Transfer** layers on top of `BucketDetailPage`. `MoveToMenu` will gain a "Transfer to other block…" item that opens a target-block picker modal. F3b can also reuse `useMoveTracks` snapshot pattern for its own optimistic write.
- **F4 Finalize** wires the disabled placeholder button (D9) to a real mutation. Header layout unchanged; one prop + one hook added.
- **F5 Curate** consumes block detail + bucket lists; rebuilds row UI per design. Hooks are shared.
- **F8 Home** may compose triage block summaries; uses existing F2 `useTriageBlocksByStyle`.

## 14. Acceptance Criteria

- All routes (§4.1) resolve. Invalid block id → 404 page. Invalid bucket id → 404 page.
- `TriageDetailStub` is deleted; `TriageDetailPage` renders block summary + bucket grid.
- Bucket grid order matches API order (D4). Inactive STAGING dimmed and clickable but not a move target (D5).
- `BucketDetailPage` renders paginated track list (limit=50, load-more works), search box debounced 300 ms, fields per D12.
- Per-row "Move to ▾" Mantine Menu lists destinations excluding current and inactive STAGING (D6).
- Move is optimistic (D13) — row disappears instantly, counters adjust, success refetches target. Error rollback restores state and shows red toast.
- Undo notification (5 s) reverses the move via swapped-bucket call. Undo failure leaves the move in place + red toast.
- FINALIZED block: read-only — no MoveMenu, no kebab, finalized_at displayed (D10).
- Header kebab → Delete soft-deletes the block (reuse F2 hook), navigates back to `/triage/:styleId` + green toast (D9).
- All §8 error / empty / loading branches covered by tests.
- `formatters.ts` extract: F1 `TrackRow` imports work, F1 tests still green.
- `pnpm test` green (≥ 160 tests = F1+F2 baseline ~130 + F3a ~30).
- `pnpm build` produces under 700 KB minified bundle (no new deps).
- Manual smoke (§11.4) green against deployed prod API.

## 15. References

- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket F3 (split into F3a + F3b).
- Backend prereq: [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — endpoints `GET /triage/blocks/{id}`, `GET .../buckets/{bucket_id}/tracks`, `POST .../move`. UNCLASSIFIED semantics in §6.3.
- F1 prereq: [`2026-05-01-F1-categories-frontend-design.md`](./2026-05-01-F1-categories-frontend-design.md) — `TrackRow` and `formatLength` source for the shared extract.
- F2 prereq: [`2026-05-02-F2-triage-list-create-frontend-design.md`](./2026-05-02-F2-triage-list-create-frontend-design.md) — `useDeleteTriageBlock`, `byStyle` cache, F2 lessons table 15-26.
- Frontend bootstrap: [`2026-04-30-frontend-bootstrap-design.md`](./2026-04-30-frontend-bootstrap-design.md).
- Pages catalog Pass 1: `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` — P-16 (BlockDetail), P-17 (BucketDetail), P-18 (Move confirm — superseded by D3). P-19 Transfer covered in F3b.
- Component spec sheet: `docs/design_handoff/04 Component spec sheet.html`.
- Open questions: `docs/design_handoff/OPEN_QUESTIONS.md` — none specific to F3a.
- Tokens: `docs/design_handoff/tokens.css`, `frontend/src/tokens.css`, `frontend/src/theme.ts`.
- Project memory: `tap-on-button, not DnD` (motivates D2 + D3).
- API contract: `docs/openapi.yaml` paths `/triage/blocks/{id}`, `/triage/blocks/{id}/buckets/{bucket_id}/tracks`, `/triage/blocks/{id}/move`. Move body shape `{from_bucket_id, to_bucket_id, track_ids[]}`, cap 1000.

# Categories: Move and Remove Tracks

**Date:** 2026-05-10
**Status:** Design — pending implementation plan
**Scope:** Frontend-only (no backend changes)

## Goal

Let the user move a single track from one category to another **within the same style**, or remove a track from its current category, directly from the tracks table on the Category Detail page.

## Non-goals

- Bulk / multi-select operations.
- Cross-style moves (UI hides categories of other styles).
- Drag-and-drop reordering.
- New backend endpoints. The existing `POST /categories/{id}/tracks` and `DELETE /categories/{id}/tracks/{track_id}` cover both flows.

## UX

### Affordance

Each track row exposes a kebab (`⋮`) button as the last column on desktop and as a top-right action on the mobile card. Clicking opens a Mantine `Menu` with two items:

1. **«Переместить в…»** — opens a nested submenu listing all categories of the same style (Mantine `Menu` nested or `Popover`-style submenu).
2. **«Удалить из категории»** — destructive item (`color="red"`).

Both actions execute optimistically. No confirmation dialog.

### Submenu rules

- Lists categories from `useCategoriesByStyle(styleId)`.
- The current category appears in the list but is `disabled` and labelled `(текущая)`.
- If the style has only one category, the parent «Переместить в…» item itself is `disabled` with tooltip «Нет других категорий».
- While `useCategoriesByStyle` is loading, the parent item shows a small `Loader` and is `disabled`. (In practice the query is already cached — the parent style page warms it.)

### Toasts and undo

After a successful action, show a Mantine notification (`autoClose: 5000`) with a textual **«Отменить»** action button.

| Action | Toast (success) | Toast (error) |
|---|---|---|
| Move | «Перенесено в «{name}». Отменить» | see Errors |
| Remove | «Удалено из категории. Отменить» | see Errors |
| Undo (either) | «Отменено» | «Не удалось отменить» |

Clicking «Отменить» runs the inverse mutation (see Data flow). If the toast auto-closes, undo is no longer available — the user must perform the inverse action manually.

## Architecture

### Frontend files

**New:**

- `frontend/src/features/categories/components/TrackRowActions.tsx`
  - Props: `{ track: CategoryTrack; currentCategoryId: string; styleId: string }`.
  - Renders an `ActionIcon` (`⋮`) that opens a Mantine `Menu`.
  - Owns the move/remove mutations and toast invocations.
  - Pure presentational w.r.t. data — reads categories via `useCategoriesByStyle(styleId)`.

- `frontend/src/features/categories/hooks/useMoveTrackBetweenCategories.ts`
  - `useMutation` with input `{ trackId: string; fromCategoryId: string; toCategoryId: string }`.
  - `mutationFn`: sequential `POST /categories/{toCategoryId}/tracks` then `DELETE /categories/{fromCategoryId}/tracks/{trackId}` via direct `api()` calls (does not compose existing hooks).
  - Throws a typed error `MovePartialError` when POST succeeded but DELETE failed.
  - Optimistic update on `onMutate`; rollback on `onError`; invalidates both source and target track lists plus `['categories']` on `onSettled`.

- `frontend/src/features/categories/hooks/useRemoveTrackOptimistic.ts`
  - `useMutation` with input `{ categoryId: string; trackId: string }`.
  - `mutationFn`: `DELETE /categories/{categoryId}/tracks/{trackId}` via direct `api()`.
  - Owns optimistic shrink + rollback for the source list.
  - Separate from the shared `useRemoveTrackFromCategory` so the existing curate Force-tap undo path (`useCurateSession.ts`) stays unchanged.

**Modified:**

- `frontend/src/features/categories/components/TrackRow.tsx`
  - Add optional `actions?: React.ReactNode` prop.
  - Desktop variant: render in a new trailing `<Table.Td>` (column count grows by one).
  - Mobile variant: render absolutely positioned in the top-right of the card.
  - When `actions` is undefined the slot collapses (keeps the component reusable).

- `frontend/src/features/categories/components/TracksTab.tsx`
  - Accept `styleId: string` prop.
  - Add an empty `<Table.Th />` to the desktop header for the actions column (keeps table cell count consistent).
  - Pass `<TrackRowActions track={tr} currentCategoryId={categoryId} styleId={styleId} />` into each `TrackRow`.

- `frontend/src/features/categories/routes/CategoryDetailPage.tsx`
  - Pass `styleId` into `<TracksTab>`.

**Untouched:**

- `useRemoveTrackFromCategory` and `useAddTrackToCategory` keep their current shape and `onSuccess`-only behavior. They are still used by the curate Force-tap chain (`useCurateSession.ts`) and by undo-of-remove on this page (the toast Undo simply invokes `useAddTrackToCategory.mutate(...)`). No optimistic logic is grafted onto them.

### No backend changes

The two existing endpoints satisfy this feature:

- `POST /categories/{id}/tracks` — idempotent on `(category_id, track_id)`. Returns 201 if newly added, 200 if `already_present`. Both treated as success.
- `DELETE /categories/{id}/tracks/{track_id}` — returns 204 on success, 404 `track_not_in_category` if missing.

`source_triage_block_id` stays `None` for manual moves (the handler hardcodes it and we do not extend the contract).

## Data flow

### Move

```
async mutationFn({ trackId, fromCategoryId, toCategoryId }):
  await api(POST /categories/{toCategoryId}/tracks, { track_id: trackId })
  try:
    await api(DELETE /categories/{fromCategoryId}/tracks/{trackId})
  except err:
    throw new MovePartialError(err)  // POST already succeeded
```

**Optimistic update on `onMutate`:**

1. `await qc.cancelQueries({ queryKey: ['categories', 'tracks', fromCategoryId] })`.
2. Capture `prev = qc.getQueriesData({ queryKey: ['categories', 'tracks', fromCategoryId] })`.
3. For each cached `(search, sort, order)` variant, `setQueriesData` to filter the moved track out of every page and decrement `total`.
4. Return `{ prev }`.

**`onError(err, _input, ctx)`:**

1. Restore `ctx.prev` via `setQueriesData`.
2. If `err instanceof MovePartialError` — fire toast «Трек в обеих категориях» with a Retry button that triggers a standalone DELETE call. Otherwise toast «Не удалось перенести».

**`onSettled(_data, _err, { fromCategoryId, toCategoryId })`:**

```
qc.invalidateQueries({ queryKey: ['categories', 'tracks', fromCategoryId] })
qc.invalidateQueries({ queryKey: ['categories', 'tracks', toCategoryId] })
qc.invalidateQueries({ queryKey: ['categories'] })  // for track_count
```

### Remove

`useRemoveTrackOptimistic` mirrors the Move logic minus the POST step:

1. `onMutate`: cancelQueries + snapshot + setQueriesData (shrink + decrement total) on `['categories', 'tracks', categoryId]`.
2. `onError`: restore snapshot.
3. `onSettled`: invalidate `['categories', 'tracks', categoryId]` and `['categories']`.

### Undo

- **After Move** — call the same hook with swapped `from`/`to`. Idempotent POST handles re-adding cleanly even if the toast click races with a slow `onSettled` invalidation.
- **After Remove** — call `useAddTrackToCategory.mutate({ categoryId, trackId })`.
- Undo failure shows toast «Не удалось отменить»; the data converges to the post-action state.

## Error handling

| Status / Cause | UX |
|---|---|
| Move POST 4xx/5xx | Optimistic rollback. Toast «Не удалось перенести». |
| Move POST ok + DELETE fail | No rollback (POST already happened). Toast «Трек в обеих категориях. Повторить удаление». Retry button calls DELETE standalone. |
| Remove DELETE 404 | Treat as success (already gone). Toast «Удалено из категории». No undo. |
| Remove DELETE other failure | Rollback, toast «Не удалось удалить». |
| 503 Aurora cold-start | Bubble up as generic failure — no auto-retry (would race with the 5 s undo window). User can retry from the kebab. |
| Unknown category in submenu (race: deleted in another tab) | Backend returns 404; show toast «Категория не найдена. Обновите страницу». |

## i18n

New keys in `frontend/src/locales/<lang>/translation.json` (both EN and RU):

```
categories.tracks_table.row_actions_label
categories.tracks_table.move_to_label
categories.tracks_table.move_to_empty
categories.tracks_table.remove_label
categories.tracks_table.current_marker
categories.toast.track_moved              // "Перенесено в «{{name}}»"
categories.toast.track_moved_partial      // "Трек в обеих категориях"
categories.toast.track_move_failed
categories.toast.track_removed
categories.toast.track_remove_failed
categories.toast.undo
categories.toast.undone
categories.toast.undo_failed
categories.toast.retry
```

## Tests

### Hook tests

- **`useMoveTrackBetweenCategories.test.tsx`** (new):
  - Happy path: POST + DELETE both 200 → mutation resolved; both invalidations queued.
  - POST 404 → mutation rejects with non-partial error; DELETE never called.
  - POST 200 + DELETE 500 → mutation rejects with `MovePartialError`.
  - Optimistic shrink: source cache loses the track on `onMutate`.
  - Rollback: source cache restored on `onError`.
  - `cancelQueries` invoked on the source list before optimistic write.

- **`useRemoveTrackOptimistic.test.tsx`** (new):
  - Happy path: DELETE 204 → mutation resolved.
  - DELETE 404 `track_not_in_category` → mutation resolved (idempotent semantics; the desired post-state is reached).
  - DELETE 500 → mutation rejects; rollback restores cache.
  - Optimistic shrink: source cache loses the track on `onMutate`.
  - `cancelQueries` invoked on the source list before optimistic write.

### Component tests

- **`TrackRowActions.test.tsx`** (new):
  - Renders kebab; click opens menu with both items.
  - Submenu lists categories of the style; current is disabled and marked `(текущая)`.
  - Click on another category triggers move mutation with correct ids.
  - Click on «Удалить» triggers remove mutation.
  - Single-category style: «Переместить в…» is disabled.
  - Wrap mount in `<MantineProvider theme={testTheme}>`; scope queries via `within(await screen.findByRole('menu'))` (per CLAUDE.md portal-singleton gotcha).

- **`TracksTab.test.tsx`** (update):
  - Renders the new actions column on desktop (header + cells).
  - Mobile cards include the action slot.
  - `styleId` is plumbed through.

### Integration test

- **`CategoryDetailPage.test.tsx`** (extend):
  - Move flow: open kebab → submenu → pick destination → optimistic shrink → success toast.
  - Undo: click «Отменить» on the toast → track reappears.
  - Partial-fail (POST 200, DELETE 500): toast «в обеих категориях» with Retry button works.

### Skipped on purpose

- Mantine submenu positioning behavior (Mantine concern).
- Toast animation timing (jsdom does not animate; Mantine notifications are smoke-tested via existing test infra).

## Open questions

None. All decisions resolved during brainstorming:
- Single-track scope only (no bulk).
- Kebab `⋮` affordance with inline submenu.
- Optimistic + Undo toast, no confirmation modal.
- Client-side composition (POST then DELETE) — no new backend endpoint.

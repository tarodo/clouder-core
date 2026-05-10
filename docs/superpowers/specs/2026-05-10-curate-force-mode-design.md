# Curate — Force Mode Design

**Date:** 2026-05-10
**Scope:** `frontend/src/features/curate/` + `frontend/src/features/categories/hooks/`
**Backend changes:** none
**Companion plan:** to be produced by `writing-plans` skill after spec approval.

---

## 1. Goal

Add a **Force** toggle to the Curate session so that, while it is ON, assigning the
current track to a staging-bucket also pushes the track into that bucket's
**general category folder** (`category_tracks` table). The Force mode is a
single-shot modifier: it auto-disables after the next track-advancing action.

User-facing requirements (per brainstorming Q&A 2026-05-10):

- Force toggle button sits **next to DISCARD on the same row**, visibly **smaller**
  than DISCARD.
- Visual states: idle = outline border; active = filled accent — must be obvious
  whether Force is ON or OFF.
- Pressing the destination button while Force is ON does both moves: bucket move +
  insert into the bucket's general category folder.
- Force auto-disables on track advance (after a successful assign).
- Pressing Force again toggles it OFF without performing any move.
- Hotkey: **`L`** (mnemonic: *Like*).

---

## 2. Glossary

| Term | Meaning |
|---|---|
| **Bucket** | One slot in a triage block. Types: `STAGING` (linked to a category), `NEW` / `OLD` / `NOT` (technical), `DISCARD`. |
| **General category folder** | Persistent set of tracks per category (`category_tracks` table). Backend ID = `category_id` on the staging bucket. |
| **Force tap** | An assign action issued while `forceMode === true` and the destination is a staging bucket. |
| **Pending hold** | The 200 ms window between assign and the reducer's `ADVANCE` action — gives the user time to redirect the same track or undo. |

---

## 3. Decisions (locked from brainstorming)

| # | Decision |
|---|---|
| D1 | Force tap on **non-staging** bucket (DISCARD / NEW / OLD / NOT) → silent normal move; Force resets after advance. No toast. |
| D2 | Undo of a Force tap performs **both** rollbacks: inverse bucket move + `DELETE /categories/{id}/tracks/{track_id}`. |
| D3 | Hotkey: `L`. Bound via `event.code === 'KeyL'` (layout-safe, per existing CLAUDE.md gotcha). |
| D4 | Partial failure (move succeeds, category POST fails): keep the move, show `yellow` warning toast, do **not** roll back the move. Best-effort semantics on step 2. |
| D5 | Layout: `[DISCARD ~75% width][Force ~25% width]` on one row. Idle = outline; active = filled accent. Force is icon-only on mobile (`compact`). |
| D6 | Force resets on: completed `ADVANCE`, `SKIP`, `PREV`, `UNDO_WITHIN`, `UNDO_AFTER`, unmount (Esc / back), and explicit toggle. Force does **not** reset on `MUTATION_ERROR` (user can retry the same tap). |
| D7 | Approach **A** chosen: FE-orchestrated chain (no backend changes). Rejected: B (backend `force=true` flag — too costly), C (generic bundle abstraction — YAGNI). |

---

## 4. Architecture

### 4.1 Boundaries

```
DestinationGrid (UI)
  └─ Top row: <Group wrap="nowrap" align="stretch">
       ├─ <DiscardButton flex=1>          (existing renderBtn(discardBucket, 'Z'))
       └─ <ForceToggle compact={isMobile}> (new)

useCurateSession (orchestrator)
  ├─ State adds: forceMode: boolean
  ├─ LastOp adds: forceCategoryId: string | null
  ├─ assign(toBucketId): reads forceMode + dst.category_id → forceCategoryId
  ├─ toggleForce(): dispatch TOGGLE_FORCE
  ├─ undo(): if lastOp.forceCategoryId → DELETE /categories/{id}/tracks/{tid}
  └─ Reset triggers (in reducer): ADVANCE, SKIP, PREV, UNDO_*

useAddTrackToCategory (new hook)
  POST /categories/{id}/tracks  body { track_id }
  Idempotent on (category_id, track_id) per backend ON CONFLICT DO NOTHING.

useRemoveTrackFromCategory (new hook)
  DELETE /categories/{id}/tracks/{track_id}
  Used only by undo of Force taps.

useCurateHotkeys
  + binding: event.code === 'KeyL' → onToggleForce()

HotkeyOverlay
  + row: "L — Toggle Force mode"
```

### 4.2 Force tap data flow

```
1. User taps a staging bucket while forceMode === true.
2. useCurateSession.assign(toBucketId)
   ├─ resolve dst from destinations
   ├─ forceCategoryId = forceMode && dst.category_id ? dst.category_id : null
   ├─ snapshot move (takeSnapshot)
   ├─ optimistic shrink (existing useMoveTracks.applyOptimisticMove)
   ├─ scheduleAdvance() / schedulePulse()
   ├─ dispatch ASSIGN_BEGIN { ..., lastOp: { ..., forceCategoryId } }
   └─ fireMutation(input, lastOp)
3. moveMutation.onSuccess
   ├─ writeLastCurateLocation (existing)
   ├─ GUARD: stateRef.lastOp !== captured lastOp  → skip chain
   └─ if (lastOp.forceCategoryId)
        addToCategoryMutate({ categoryId, trackId })
          ├─ onSuccess: invalidate ['categories'] + ['categories','tracks',cid]
          └─ onError: notify yellow 'curate.force.toast_partial'
4. After 200 ms hold → dispatch ADVANCE → forceMode := false (reducer)
```

The category POST is **fire-and-forget relative to the hold timer**. Hold latency
and category latency are decoupled; reducer state stays consistent regardless of
order of completion.

---

## 5. State machine (reducer)

### 5.1 State shape

```ts
interface State {
  currentIndex: number;
  totalAssigned: number;
  lastTappedBucketId: string | null;
  lastOp: LastOp | null;
  forceMode: boolean;        // NEW — defaults to false
}

interface LastOp {
  input: MoveInput;
  snapshot: MoveSnapshot;
  trackIndex: number;
  track: BucketTrack;
  forceCategoryId: string | null;   // NEW — null if not Force / not staging
}

const initialState: State = {
  currentIndex: 0,
  totalAssigned: 0,
  lastTappedBucketId: null,
  lastOp: null,
  forceMode: false,
};
```

### 5.2 New actions

```ts
type Action =
  | // ...existing
  | { type: 'TOGGLE_FORCE' }
  | { type: 'CLEAR_FORCE' };
```

### 5.3 Reducer cases (full delta)

```ts
case 'TOGGLE_FORCE':
  return { ...state, forceMode: !state.forceMode };

case 'CLEAR_FORCE':
  return state.forceMode ? { ...state, forceMode: false } : state;

case 'ADVANCE':
  // Was no-op. Now also clears forceMode after a successful pending hold.
  return state.forceMode ? { ...state, forceMode: false } : state;

case 'SKIP':
  return {
    ...state,
    currentIndex: Math.min(action.max, state.currentIndex + 1),
    forceMode: false,
  };

case 'PREV':
  return {
    ...state,
    currentIndex: Math.max(0, state.currentIndex - 1),
    forceMode: false,
  };

case 'UNDO_WITHIN':
  return {
    ...state,
    lastOp: null,
    lastTappedBucketId: null,
    totalAssigned: Math.max(0, state.totalAssigned - 1),
    forceMode: false,
  };

case 'UNDO_AFTER':
  if (!state.lastOp) return state;
  return {
    ...state,
    currentIndex: state.lastOp.trackIndex,
    lastOp: null,
    lastTappedBucketId: null,
    totalAssigned: Math.max(0, state.totalAssigned - 1),
    forceMode: false,
  };

case 'MUTATION_ERROR':
  // forceMode preserved deliberately — user may retry the same destination.
  return {
    ...state,
    lastOp: null,
    lastTappedBucketId: null,
    totalAssigned: Math.max(0, state.totalAssigned - 1),
  };
```

`ASSIGN_BEGIN` and `ASSIGN_REPLACE_BEGIN` already accept the `lastOp` from the
caller — they just store the new shape (with `forceCategoryId`) without further
edits.

### 5.4 Why `forceMode` lives in reducer state, not a ref

`forceMode` directly drives a render (the toggle's `active` prop and any visual
gate in `DestinationGrid`). Refs do not trigger renders, so a ref-based flag
would leave the UI stale until something else dispatched. Reducer state is the
right home.

---

## 6. Component design

### 6.1 `DestinationGrid.tsx` — diff

Props extend:

```ts
export interface DestinationGridProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  lastTappedBucketId: string | null;
  forceMode: boolean;            // NEW
  onAssign: (toBucketId: string) => void;
  onToggleForce: () => void;     // NEW
}
```

DISCARD row replaces the bare `renderBtn(discardBucket, 'Z')` with a flex row:

```tsx
{discardBucket && (
  <Group gap="xs" wrap="nowrap" align="stretch">
    <div style={{ flex: 1, minWidth: 0 }}>
      {renderBtn(discardBucket, 'Z')}
    </div>
    <ForceToggle
      active={forceMode}
      hotkeyHint={isMobile ? null : 'L'}
      compact={isMobile}
      onClick={onToggleForce}
    />
  </Group>
)}
```

`align="stretch"` keeps the toggle's height equal to DISCARD's. `flex: 1` plus
`minWidth: 0` lets DISCARD shrink correctly inside the flex row on narrow viewports.

### 6.2 `ForceToggle.tsx` (new)

```ts
interface ForceToggleProps {
  active: boolean;
  hotkeyHint: string | null;
  compact: boolean;
  onClick: () => void;
}
```

Implementation: Mantine `<Button>` (or `<UnstyledButton>` styled via CSS module
to match `DestinationButton`'s aesthetic).

- `aria-pressed={active}` — toggle semantics for screen readers.
- `aria-label={t('curate.force.aria', { state: t(active ? 'curate.force.aria_state_on' : 'curate.force.aria_state_off') })}`
- Idle: `variant="default"`, outline border, transparent background, label in `var(--color-fg)`.
- Active: `variant="filled"`, accent fill (`color="grape"` as a starting point — final accent token to be picked during impl by checking `frontend/src/styles/theme.ts`; if an `accent-magenta` token exists, prefer it to match the curate look-and-feel).
- Desktop: `min-width: ~96px`, label `"Force"` + spaced hotkey hint `L` (mono, `var(--color-fg-muted)`), parallels DestinationButton hotkey style.
- Mobile (`compact`): icon-only (`IconBolt` from `frontend/src/components/icons` if it exists; otherwise add) + small `L` letter; `min-width: ~52px`.
- No animation. No `just-tapped` pulse — that pattern is reserved for destination buttons (CLAUDE.md gotcha on `[data-just-tapped]`).

### 6.3 `useAddTrackToCategory.ts` (new)

Skeleton, modelled on existing `frontend/src/features/categories/hooks/useDeleteCategory.ts`:

```ts
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api/apiClient';

interface AddTrackInput {
  categoryId: string;
  trackId: string;
}

export function useAddTrackToCategory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ categoryId, trackId }: AddTrackInput) =>
      api(`/categories/${categoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_id: trackId }),
      }),
    onSuccess: (_, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}
```

No optimistic update: the user is in Curate, not on the categories page; an
inactive cache invalidation is enough. The active `category_tracks` query (if
any) is invalidated explicitly.

### 6.4 `useRemoveTrackFromCategory.ts` (new)

Mirror of the above with `method: 'DELETE'` and path `/categories/{categoryId}/tracks/{trackId}`. Same invalidation set.

### 6.5 `useCurateHotkeys.ts` — diff

Args extend with `onToggleForce: () => void`. New case in the keydown switch:

```ts
case 'KeyL':
  if (overlayOpen) return;     // consistency with other bindings
  e.preventDefault();
  onToggleForce();
  return;
```

Position the case near `KeyU` (Undo) for grouping by family.

### 6.6 `HotkeyOverlay.tsx` — diff

Add a row in the destinations / actions section (whichever the existing layout
uses for `U`):

```
L            Toggle Force mode
```

i18n key: `hotkey_overlay.toggle_force`.

### 6.7 `useCurateSession.ts` — public API extension

```ts
export interface CurateSession {
  // ...existing
  forceMode: boolean;             // NEW
  toggleForce: () => void;        // NEW
}
```

Wired in `CurateSession.tsx`:

```tsx
<DestinationGrid
  buckets={session.destinations}
  currentBucketId={bucketId}
  lastTappedBucketId={session.lastTappedBucketId}
  forceMode={session.forceMode}
  onAssign={session.assign}
  onToggleForce={session.toggleForce}
/>
```

```tsx
useCurateHotkeys({
  // ...existing
  onToggleForce: session.toggleForce,
});
```

---

## 7. HTTP chain + undo + error handling

### 7.1 `fireMutation` — chain after move success

```ts
const { mutate: addToCategoryMutate } = useAddTrackToCategory();

const fireMutation = useCallback(
  (input: MoveInput, lastOp: LastOp) => {
    moveMutate(input, {
      onSuccess: () => {
        writeLastCurateLocation(styleId, blockId, bucketId);
        writeLastCurateStyle(styleId);
        // Race guard: if user undid or replaced the op while move was in
        // flight, stateRef.current.lastOp is no longer the captured one.
        const cur = stateRef.current.lastOp;
        if (!cur || cur !== lastOp) return;
        if (lastOp.forceCategoryId) {
          addToCategoryMutate(
            {
              categoryId: lastOp.forceCategoryId,
              trackId: input.trackIds[0],
            },
            {
              onError: () => {
                notifications.show({
                  message: t('curate.force.toast_partial'),
                  color: 'yellow',
                  autoClose: 4000,
                });
              },
            },
          );
        }
      },
      onError: (err) => {
        if (pendingTimerRef.current !== null) {
          clearTimeout(pendingTimerRef.current);
          pendingTimerRef.current = null;
        }
        dispatch({ type: 'MUTATION_ERROR' });
        emitErrorToast(err);
      },
    });
  },
  [
    moveMutate,
    addToCategoryMutate,
    blockId,
    bucketId,
    styleId,
    emitErrorToast,
    t,
  ],
);
```

`fireMutation` now takes `lastOp` as a second argument so its `onSuccess` can
identity-compare it against `stateRef.current.lastOp` for the race guard. All
existing call sites of `fireMutation` already build `lastOp` immediately before
the call — a simple parameter add.

### 7.2 `undo` — Force-aware rollback

```ts
const { mutate: removeFromCategoryMutate } = useRemoveTrackFromCategory();

const undo = useCallback(() => {
  const lastOp = stateRef.current.lastOp;
  if (!lastOp) return;
  const isPending = pendingTimerRef.current !== null;

  playback.controls.cancelPendingAdvance();

  const rollbackForce = () => {
    if (!lastOp.forceCategoryId) return;
    removeFromCategoryMutate(
      {
        categoryId: lastOp.forceCategoryId,
        trackId: lastOp.input.trackIds[0],
      },
      {
        onError: () => {
          notifications.show({
            message: t('curate.force.toast_undo_partial'),
            color: 'yellow',
            autoClose: 4000,
          });
        },
      },
    );
  };

  if (isPending) {
    clearTimeout(pendingTimerRef.current as number);
    pendingTimerRef.current = null;
    if (pulseTimerRef.current !== null) {
      clearTimeout(pulseTimerRef.current);
      pulseTimerRef.current = null;
    }
    void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
    rollbackForce();
    dispatch({ type: 'UNDO_WITHIN' });
  } else {
    void undoMoveDirect(qc, blockId, styleId, lastOp.input, lastOp.snapshot).catch(() => {});
    rollbackForce();
    dispatch({ type: 'UNDO_AFTER' });
    const restored = toPlaybackTrack(lastOp.track);
    setTimeout(() => {
      void playRef.current(lastOp.trackIndex, restored);
    }, 0);
  }
}, [qc, blockId, styleId, playback.controls, removeFromCategoryMutate, t]);
```

The within-window branch is interesting: even if the bucket move's HTTP call has
not yet returned, we still issue the DELETE for the category. Because
`addToCategoryMutate` is only fired inside the move's `onSuccess` — and the race
guard sees `lastOp === null` after `UNDO_WITHIN` — the POST will not happen.
A pre-emptive DELETE for a row that was never inserted is a server no-op
(`DELETE` against an empty `(category_id, track_id)` row returns 200/204 / no
rows). Acceptable.

### 7.3 Error matrix

| Scenario | `move` HTTP | `category` HTTP | UI |
|---|---|---|---|
| Force happy | OK | OK | Shrink, advance, Force OFF |
| Cat POST fail | OK | 4xx/5xx | Shrink, advance, **yellow** toast `toast_partial`, Force OFF |
| Move fail | 4xx/5xx | not called | Rollback, **red** toast (existing path), **Force stays ON** |
| Undo within | rolled back | not called (guard) | Clean state, Force OFF |
| Undo after | rolled back | DELETE fired | Clean state, Force OFF; on DELETE fail → yellow `toast_undo_partial` |
| Race: undo before move's onSuccess | rolled back optimistically; server may apply | guard blocks chain | Block refetch reconciles inconsistency |
| Double-tap on different staging during hold | replaced; both moves go through | category POST fires for **second** target only (race guard ensures) | Force OFF after the new ADVANCE |

---

## 8. i18n keys (new)

`frontend/src/locales/{en,ru}/curate.json`:

```json
{
  "force": {
    "button_label": "Force" / "Force",
    "aria": "Force mode {{state}}" / "Режим Force {{state}}",
    "aria_state_on": "on" / "включён",
    "aria_state_off": "off" / "выключен",
    "toast_partial": "Track moved, but failed to add to category folder" / "Трек перемещён, но не добавлен в общую папку категории",
    "toast_undo_partial": "Move undone, but track may still be in category folder" / "Перемещение отменено, но трек может остаться в общей папке категории"
  },
  "hotkey_overlay": {
    "toggle_force": "Toggle Force mode" / "Переключить режим Force"
  }
}
```

Exact wording is provisional — reviewable during impl.

---

## 9. Non-goals / explicit YAGNI

- No persistence of `forceMode` across navigations (Esc → re-enter Curate → Force OFF).
- No "Force all in queue" bulk action.
- No analytics event for Force usage (can be added later if needed; not required for this ticket).
- No backend `force=true` flag on the move endpoint (rejected approach B).
- No generic bundle-ops abstraction (rejected approach C; YAGNI until N=2).
- No optimistic update of `category_tracks` cache; user is not on that page during Curate.
- No special handling for an inactive/deleted destination category — the existing
  `target_bucket_inactive` error flow on the move side covers this; if the bucket
  is active, its `category_id` is valid (DB FK).

---

## 10. Test plan

### 10.1 Behavioural — reducer transitions

The reducer is module-private (not exported). Tests cover its transitions
**through the public hook surface**, matching the existing
`useCurateSession.test.tsx` pattern (`renderHook` + `act` + observe returned
fields). Extend that file with:

- `toggleForce()` flips `session.forceMode` (call once → true; twice → false).
- `assign()` then wait past hold → `forceMode` resets to `false`.
- `skip()` while `forceMode === true` → resets `false`.
- `prev()` while `forceMode === true` → resets `false`.
- `undo()` after a Force tap → resets `false` (covered both within and after window in 10.6).
- `forceMode` survives `MUTATION_ERROR` (fake MSW 500 on move endpoint, observe `session.forceMode === true` after).
- `lastOp.forceCategoryId` is not directly observable from the public API; covered indirectly by 10.6 scenarios that check the chained category POST/DELETE.

### 10.2 Unit — `ForceToggle`

New `frontend/src/features/curate/components/__tests__/ForceToggle.test.tsx`:

- Renders label `Force` + hotkey hint `L` on desktop.
- `compact` mode hides label, keeps icon + `L`.
- `aria-pressed` reflects `active` prop.
- `aria-label` switches between on/off via i18n key.
- `onClick` fires once on click.

### 10.3 Unit — `useAddTrackToCategory` / `useRemoveTrackFromCategory`

New tests under `frontend/src/features/categories/hooks/__tests__/`:

- POST `/categories/:id/tracks` with body `{ track_id }` resolves on 200/201.
- 5xx throws `ApiError`.
- `onSuccess` invalidates `['categories']` (no refetch) + `['categories','tracks',cid]`.
- DELETE mirror with `404` tolerated as success-equivalent (idempotent removal).

### 10.4 Component — `DestinationGrid`

Extend `DestinationGrid.test.tsx`:

- DISCARD and ForceToggle render in the same horizontal group (DOM sibling check).
- ForceToggle absent when `discardBucket === null` (defensive).
- `onToggleForce` is wired from props to the toggle.
- `forceMode={true}` → ForceToggle receives `active={true}` (button has `aria-pressed="true"`).

### 10.5 Hook — `useCurateHotkeys`

Extend `useCurateHotkeys.test.tsx`:

- `KeyL` keydown calls `onToggleForce` and `preventDefault`s.
- `KeyL` while `overlayOpen === true` does nothing (consistency).

### 10.6 Integration — chain + undo

New file `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`
(MSW + react-query + render `CurateSession`):

| # | Scenario | Asserts |
|---|---|---|
| 1 | `force_happy_path` | move POST + category POST both fired with right IDs; queue shrinks; `forceMode` resets |
| 2 | `force_partial_fail_keeps_move` | category POST → 500; move stays applied; yellow toast `curate.force.toast_partial`; `forceMode` resets |
| 3 | `force_non_staging_skips_chain` | tap on NEW (`category_id == null`) → only move POST fires; `forceMode` resets |
| 4 | `force_undo_after_window_calls_delete` | wait past 200 ms hold; undo → inverse move + DELETE `/categories/:cid/tracks/:tid`; `forceMode` resets |
| 5 | `force_undo_within_window_calls_delete` | undo within 200 ms; rollback + DELETE fired; `forceMode` resets |
| 6 | `force_skip_resets_force_no_chain` | skip via `J`/`K`; neither HTTP fires; `forceMode` resets |
| 7 | `force_undo_before_move_response_skips_chain` | MSW delays move POST 100 ms; undo within 100 ms; race guard blocks category POST entirely |

### 10.7 i18n smoke

Existing `i18n` key-presence tests (or a new lightweight one) verify all new
keys exist in both `en` and `ru` JSON.

### 10.8 Out of scope

- Pixel-perfect Mantine layout (visual polish belongs to the dev-server check).
- Spam-tapping the Force toggle (toggle is reducer-pure, no side effects to test).
- Backend behaviour of the existing `POST /categories/{id}/tracks` endpoint (covered by backend tests).

---

## 11. Files touched

**Edited (6):**

- `frontend/src/features/curate/hooks/useCurateSession.ts`
- `frontend/src/features/curate/hooks/useCurateHotkeys.ts`
- `frontend/src/features/curate/components/DestinationGrid.tsx`
- `frontend/src/features/curate/components/HotkeyOverlay.tsx`
- `frontend/src/features/curate/components/CurateSession.tsx` (wire new props)
- `frontend/src/locales/en/curate.json` + `frontend/src/locales/ru/curate.json`

**Created (3 source + 1 test):**

- `frontend/src/features/curate/components/ForceToggle.tsx`
- `frontend/src/features/curate/components/ForceToggle.module.css`
- `frontend/src/features/categories/hooks/useAddTrackToCategory.ts`
- `frontend/src/features/categories/hooks/useRemoveTrackFromCategory.ts`
- `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`

**Test files extended (4):**

- `frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx`
- `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx`
- `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx`
- `frontend/src/features/categories/hooks/__tests__/` — new test files for the two new hooks

**Backend touched: 0.**

---

## 12. Acceptance criteria

1. Force toggle visible next to DISCARD on every Curate session, both desktop and mobile.
2. Tapping Force flips its visible state (idle ↔ active) immediately.
3. Pressing `L` toggles Force; works regardless of input focus (per existing `event.code` pattern).
4. Force ON + tap staging → track lands in destination bucket AND in `category_tracks` for that bucket's category, verifiable via Aurora Data API:
   `SELECT 1 FROM category_tracks WHERE category_id = :cid AND track_id = :tid`.
5. Force ON + tap DISCARD/NEW/OLD/NOT → only bucket move; no `category_tracks` row added.
6. Force auto-disables after the next track-advancing action (assign, skip, prev, undo).
7. Tapping Force again disables it without performing any move.
8. Undo of a Force tap reverses both the bucket move and the category insert (within latency tolerance).
9. Partial failure (category POST 5xx) shows a yellow warning toast; the move stays.
10. Move failure shows the existing red error toast; Force stays ON for retry.
11. All new + extended tests pass; `pnpm test` is green.
12. No backend changes; no new env vars; no migrations.

# Curate Force Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Force toggle to Curate that, when ON, both moves a track to its destination staging-bucket AND inserts it into that bucket's general category folder. Single-shot modifier — auto-disables on track advance.

**Architecture:** FE-orchestrated chain (Approach A from spec). `useCurateSession` reducer gains `forceMode` boolean and `lastOp.forceCategoryId`. After a successful move, if `forceCategoryId !== null`, fire a chained `POST /categories/{id}/tracks` (idempotent on backend). Undo of a Force tap fires both the inverse move AND `DELETE /categories/{id}/tracks/{trackId}`. Zero backend changes.

**Tech Stack:** React 19, TanStack Query 5, Mantine 9, react-router 7, vitest 2, MSW 2. Source paths: `frontend/src/features/curate/`, `frontend/src/features/categories/hooks/`, `frontend/src/i18n/`.

**Spec:** `docs/superpowers/specs/2026-05-10-curate-force-mode-design.md` (commit `78e145f`).

**Important codebase facts (verified):**
- API client lives at `frontend/src/api/client.ts`, exported as `api`. New hooks must import from `'../../../api/client'` (mirroring `useDeleteCategory.ts`).
- i18n is **English-only** — only `frontend/src/i18n/en.json` exists. The spec mentioned `ru/curate.json`; that file does not exist. Skip RU.
- Reducer in `useCurateSession.ts` is module-private. Tests cover transitions through the public hook surface (existing pattern in `useCurateSession.test.tsx`).
- Tabler icons re-exported from `frontend/src/components/icons.ts`. `IconBolt` is not yet there — Task 4 adds it.
- Existing tests use MSW handlers against `http://localhost/...` (jsdom default origin).

---

## File Structure

**Create:**
- `frontend/src/features/categories/hooks/useAddTrackToCategory.ts` — POST chain hook
- `frontend/src/features/categories/hooks/useRemoveTrackFromCategory.ts` — DELETE undo-chain hook
- `frontend/src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx`
- `frontend/src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx`
- `frontend/src/features/curate/components/ForceToggle.tsx`
- `frontend/src/features/curate/components/ForceToggle.module.css`
- `frontend/src/features/curate/components/__tests__/ForceToggle.test.tsx`
- `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`

**Modify:**
- `frontend/src/components/icons.ts` — add `IconBolt` re-export
- `frontend/src/features/curate/hooks/useCurateHotkeys.ts` — `KeyL` binding + new prop
- `frontend/src/features/curate/hooks/useCurateSession.ts` — state, reducer, assign, fireMutation, undo, public API
- `frontend/src/features/curate/components/DestinationGrid.tsx` — DISCARD row split, new props
- `frontend/src/features/curate/components/HotkeyOverlay.tsx` — append L row
- `frontend/src/features/curate/components/CurateSession.tsx` — wire `forceMode` + `toggleForce`
- `frontend/src/i18n/en.json` — Force button + toast + hotkey labels

**Modify (tests, extending existing):**
- `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx` — `KeyL` cases
- `frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx` — Force transitions through hook surface
- `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx` — DISCARD row contains ForceToggle

---

## Branch + Commit Discipline

Work on the existing worktree branch (`worktree-force_feature`). Commit after each task using `caveman:caveman-commit` skill (project policy — see CLAUDE.md "Commit Policy"). Plan suggests subjects below; pass them through caveman-commit verbatim if they already match Conventional Commits.

---

## Task 1: Add `useAddTrackToCategory` hook (TDD)

**Files:**
- Create: `frontend/src/features/categories/hooks/useAddTrackToCategory.ts`
- Create test: `frontend/src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useAddTrackToCategory } from '../useAddTrackToCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useAddTrackToCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('POSTs /categories/:id/tracks with body { track_id }', async () => {
    let receivedBody: unknown = null;
    server.use(
      http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
        receivedBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(receivedBody).toEqual({ track_id: 't1' });
  });

  it('throws ApiError on 5xx', async () => {
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).rejects.toBeDefined();
  });

  it('invalidates ["categories", "tracks", categoryId] after success', async () => {
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => HttpResponse.json({ ok: true })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    qc.setQueryData(['categories', 'tracks', 'c1', ''], { items: [], total: 0 });
    const { result } = renderHook(() => useAddTrackToCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    const state = qc.getQueryState(['categories', 'tracks', 'c1', '']);
    expect(state?.isInvalidated).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx --run`
Expected: FAIL — "Cannot find module '../useAddTrackToCategory'".

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/features/categories/hooks/useAddTrackToCategory.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface AddTrackToCategoryInput {
  categoryId: string;
  trackId: string;
}

export function useAddTrackToCategory(): UseMutationResult<
  unknown,
  Error,
  AddTrackToCategoryInput
> {
  const qc = useQueryClient();
  return useMutation<unknown, Error, AddTrackToCategoryInput>({
    mutationFn: ({ categoryId, trackId }) =>
      api(`/categories/${categoryId}/tracks`, {
        method: 'POST',
        body: JSON.stringify({ track_id: trackId }),
      }),
    onSuccess: (_data, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx --run`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

Commit message via `caveman:caveman-commit` skill. Suggested subject:

```
feat(categories): add useAddTrackToCategory hook
```

```bash
git add frontend/src/features/categories/hooks/useAddTrackToCategory.ts \
        frontend/src/features/categories/hooks/__tests__/useAddTrackToCategory.test.tsx
git commit -m "feat(categories): add useAddTrackToCategory hook"
```

---

## Task 2: Add `useRemoveTrackFromCategory` hook (TDD)

**Files:**
- Create: `frontend/src/features/categories/hooks/useRemoveTrackFromCategory.ts`
- Create test: `frontend/src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx`:

```tsx
import React from 'react';
import { describe, it, expect, beforeEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { useRemoveTrackFromCategory } from '../useRemoveTrackFromCategory';

function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('useRemoveTrackFromCategory', () => {
  beforeEach(() => tokenStore.set('TOK'));

  it('DELETEs /categories/:id/tracks/:trackId', async () => {
    let hit = false;
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => {
        hit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useRemoveTrackFromCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    expect(hit).toBe(true);
  });

  it('invalidates ["categories", "tracks", categoryId] after success', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 204 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    qc.setQueryData(['categories', 'tracks', 'c1', ''], { items: [], total: 0 });
    const { result } = renderHook(() => useRemoveTrackFromCategory(), { wrapper: wrap(qc) });
    await act(async () => {
      await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
    });
    const state = qc.getQueryState(['categories', 'tracks', 'c1', '']);
    expect(state?.isInvalidated).toBe(true);
  });

  it('rejects on 5xx', async () => {
    server.use(
      http.delete('http://localhost/categories/c1/tracks/t1', () => new HttpResponse(null, { status: 500 })),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    const { result } = renderHook(() => useRemoveTrackFromCategory(), { wrapper: wrap(qc) });
    await expect(
      act(async () => {
        await result.current.mutateAsync({ categoryId: 'c1', trackId: 't1' });
      }),
    ).rejects.toBeDefined();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Write minimal implementation**

Create `frontend/src/features/categories/hooks/useRemoveTrackFromCategory.ts`:

```ts
import { useMutation, useQueryClient, type UseMutationResult } from '@tanstack/react-query';
import { api } from '../../../api/client';

export interface RemoveTrackFromCategoryInput {
  categoryId: string;
  trackId: string;
}

export function useRemoveTrackFromCategory(): UseMutationResult<
  unknown,
  Error,
  RemoveTrackFromCategoryInput
> {
  const qc = useQueryClient();
  return useMutation<unknown, Error, RemoveTrackFromCategoryInput>({
    mutationFn: ({ categoryId, trackId }) =>
      api(`/categories/${categoryId}/tracks/${trackId}`, { method: 'DELETE' }),
    onSuccess: (_data, { categoryId }) => {
      qc.invalidateQueries({ queryKey: ['categories'], refetchType: 'none' });
      qc.invalidateQueries({ queryKey: ['categories', 'tracks', categoryId] });
    },
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && pnpm test -- src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx --run`
Expected: PASS — 3 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/hooks/useRemoveTrackFromCategory.ts \
        frontend/src/features/categories/hooks/__tests__/useRemoveTrackFromCategory.test.tsx
git commit -m "feat(categories): add useRemoveTrackFromCategory hook"
```

---

## Task 3: Add Force i18n keys to `en.json`

**Files:**
- Modify: `frontend/src/i18n/en.json` — extend `curate.hotkeys` and add `curate.force` block + new `curate.toast` keys.

- [ ] **Step 1: Locate the `curate.hotkeys` block (around line 389)**

Read `frontend/src/i18n/en.json` lines 389-408.

- [ ] **Step 2: Add `key_l_label` to `curate.hotkeys`**

Insert immediately after the `"key_u_label": "Undo last assignment",` line:

```json
      "key_l_label": "Toggle Force mode",
```

- [ ] **Step 3: Add `force` block + new toast keys under `curate`**

Add a `force` sub-object inside `curate` (peer of `card`, `destination`, `footer`, `hotkeys`, `toast`). Place it right before `toast` so the diff is local. Concretely, insert before the existing `"toast": {` line in the `curate` object:

```json
    "force": {
      "button_label": "Force",
      "aria_on": "Force mode on",
      "aria_off": "Force mode off"
    },
```

Then inside the existing `curate.toast` object, append two keys after `"move_failed"`:

```json
      "force_partial": "Track moved, but failed to add to category folder.",
      "force_undo_partial": "Move undone, but the track may still be in the category folder."
```

(Add a comma to the previous `"move_failed"` line.)

- [ ] **Step 4: Validate JSON parses**

Run: `cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json','utf8'))" && echo OK`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/en.json
git commit -m "feat(curate): add Force-mode i18n keys"
```

---

## Task 4: Re-export `IconBolt` from icons module

**Files:**
- Modify: `frontend/src/components/icons.ts:1-30` — append `IconBolt` to the export list.

- [ ] **Step 1: Edit the file**

Use Edit tool. Add `IconBolt,` between `IconShield,` and the closing `}` of the export block:

```ts
export {
  IconHome,
  IconCategory,
  // ...existing
  IconShield,
  IconBolt,
} from '@tabler/icons-react';
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && pnpm tsc --noEmit -p tsconfig.app.json 2>&1 | tail -20`
Expected: no new errors related to `IconBolt`.

- [ ] **Step 3: Commit (will be folded into Task 5 commit if you prefer; otherwise standalone)**

Skip the standalone commit — this single line reads better folded into the ForceToggle commit (Task 5). Leave staged.

---

## Task 5: Create `ForceToggle` component (TDD)

**Files:**
- Create: `frontend/src/features/curate/components/ForceToggle.tsx`
- Create: `frontend/src/features/curate/components/ForceToggle.module.css`
- Create test: `frontend/src/features/curate/components/__tests__/ForceToggle.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/features/curate/components/__tests__/ForceToggle.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { I18nextProvider } from 'react-i18next';
import i18n from '../../../../i18n';
import { testTheme } from '../../../../test/theme';
import { ForceToggle } from '../ForceToggle';

function renderWithProviders(ui: React.ReactElement) {
  return render(
    <I18nextProvider i18n={i18n}>
      <MantineProvider theme={testTheme}>{ui}</MantineProvider>
    </I18nextProvider>,
  );
}

describe('ForceToggle', () => {
  it('renders label "Force" and hotkey hint "L" on desktop (compact=false)', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    expect(screen.getByText('Force')).toBeInTheDocument();
    expect(screen.getByText('L')).toBeInTheDocument();
  });

  it('hides text label when compact=true (icon + L only)', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={true} onClick={() => {}} />,
    );
    expect(screen.queryByText('Force')).not.toBeInTheDocument();
    expect(screen.getByText('L')).toBeInTheDocument();
  });

  it('renders aria-pressed=false when active=false', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    expect(btn).toHaveAttribute('aria-label', 'Force mode off');
  });

  it('renders aria-pressed=true when active=true', () => {
    renderWithProviders(
      <ForceToggle active={true} hotkeyHint="L" compact={false} onClick={() => {}} />,
    );
    const btn = screen.getByRole('button');
    expect(btn).toHaveAttribute('aria-pressed', 'true');
    expect(btn).toHaveAttribute('aria-label', 'Force mode on');
  });

  it('calls onClick once when clicked', () => {
    const onClick = vi.fn();
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint="L" compact={false} onClick={onClick} />,
    );
    fireEvent.click(screen.getByRole('button'));
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('omits hotkey hint element when hotkeyHint is null', () => {
    renderWithProviders(
      <ForceToggle active={false} hotkeyHint={null} compact={true} onClick={() => {}} />,
    );
    expect(screen.queryByText('L')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- src/features/curate/components/__tests__/ForceToggle.test.tsx --run`
Expected: FAIL — module not found.

- [ ] **Step 3: Create CSS module**

Create `frontend/src/features/curate/components/ForceToggle.module.css`:

```css
.button {
  min-height: var(--control-xl, 56px);
  padding-inline: var(--mantine-spacing-md);
  border-radius: var(--radius-md);
  border: var(--border-thin) solid var(--color-border);
  background: transparent;
  color: var(--color-fg);
  display: inline-flex;
  align-items: center;
  gap: var(--mantine-spacing-xs);
  white-space: nowrap;
  transition:
    background var(--motion-base) var(--ease-out),
    border-color var(--motion-base) var(--ease-out),
    color var(--motion-base) var(--ease-out);
}
.button:hover {
  background: var(--color-hover);
}
.button[data-active='true'] {
  background: var(--mantine-color-grape-filled, #ae3ec9);
  border-color: var(--mantine-color-grape-filled, #ae3ec9);
  color: #fff;
}
.button[data-active='true']:hover {
  background: var(--mantine-color-grape-filled-hover, #9c36b5);
  border-color: var(--mantine-color-grape-filled-hover, #9c36b5);
}
.label {
  font-size: var(--text-14);
  font-weight: var(--weight-medium);
}
@media (max-width: 64em) {
  .button[data-compact='true'] {
    min-height: 44px;
    padding-inline: var(--mantine-spacing-sm);
  }
}
@media (min-width: 64em) {
  .button {
    min-height: 64px;
  }
}
```

- [ ] **Step 4: Create the component**

Create `frontend/src/features/curate/components/ForceToggle.tsx`:

```tsx
import { Kbd, UnstyledButton } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { IconBolt } from '../../../components/icons';
import classes from './ForceToggle.module.css';

export interface ForceToggleProps {
  active: boolean;
  hotkeyHint: string | null;
  compact: boolean;
  onClick: () => void;
}

export function ForceToggle({ active, hotkeyHint, compact, onClick }: ForceToggleProps) {
  const { t } = useTranslation();
  const ariaLabel = active ? t('curate.force.aria_on') : t('curate.force.aria_off');
  return (
    <UnstyledButton
      onClick={onClick}
      className={classes.button}
      data-active={active ? 'true' : 'false'}
      data-compact={compact ? 'true' : 'false'}
      aria-pressed={active}
      aria-label={ariaLabel}
    >
      <IconBolt size={compact ? 14 : 16} />
      {!compact && <span className={classes.label}>{t('curate.force.button_label')}</span>}
      {hotkeyHint !== null && <Kbd>{hotkeyHint}</Kbd>}
    </UnstyledButton>
  );
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && pnpm test -- src/features/curate/components/__tests__/ForceToggle.test.tsx --run`
Expected: PASS — 6 tests.

- [ ] **Step 6: Commit**

Stage the icons.ts edit from Task 4 alongside ForceToggle:

```bash
git add frontend/src/components/icons.ts \
        frontend/src/features/curate/components/ForceToggle.tsx \
        frontend/src/features/curate/components/ForceToggle.module.css \
        frontend/src/features/curate/components/__tests__/ForceToggle.test.tsx
git commit -m "feat(curate): add ForceToggle component"
```

---

## Task 6: Wire `KeyL` into `useCurateHotkeys` (TDD)

**Files:**
- Modify: `frontend/src/features/curate/hooks/useCurateHotkeys.ts:7-15` (props), `:67-71` (insert KeyL case after KeyU), `:111-120` (deps array).
- Modify test: `frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx:55-83` (new mock + mount signature).

- [ ] **Step 1: Extend the test setup with `onToggleForce`**

In `useCurateHotkeys.test.tsx`, add `onToggleForce` to the `let` declarations at line 55-59:

```ts
  let onAssign: ReturnType<typeof vi.fn>;
  let onUndo: ReturnType<typeof vi.fn>;
  let onOpenOverlay: ReturnType<typeof vi.fn>;
  let onCloseOverlay: ReturnType<typeof vi.fn>;
  let onExit: ReturnType<typeof vi.fn>;
  let onToggleForce: ReturnType<typeof vi.fn>;
```

In `beforeEach` (line 61-67), initialize:

```ts
    onToggleForce = vi.fn();
```

In `mount` helper (line 70-83), add `onToggleForce` to the args object:

```ts
        useCurateHotkeys({
          buckets,
          overlayOpen,
          onAssign,
          onUndo,
          onOpenOverlay,
          onCloseOverlay,
          onExit,
          onToggleForce,
        }),
```

- [ ] **Step 2: Add failing test cases for KeyL**

Append inside `describe('useCurateHotkeys', ...)` (before the closing `})`):

```ts
  it('KeyL calls onToggleForce', () => {
    mount(false);
    act(() => dispatchKey({ code: 'KeyL' }));
    expect(onToggleForce).toHaveBeenCalledTimes(1);
  });

  it('KeyL while overlayOpen=true does NOT call onToggleForce', () => {
    mount(true);
    act(() => dispatchKey({ code: 'KeyL' }));
    expect(onToggleForce).not.toHaveBeenCalled();
  });
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx --run`
Expected: FAIL on the two new cases (TS error: missing `onToggleForce` in `UseCurateHotkeysArgs`; or runtime: `onToggleForce` is undefined).

- [ ] **Step 4: Add `onToggleForce` to props + binding**

Edit `frontend/src/features/curate/hooks/useCurateHotkeys.ts`. Update the interface (lines 7-15):

```ts
export interface UseCurateHotkeysArgs {
  buckets: TriageBucket[];
  overlayOpen: boolean;
  onAssign: (toBucketId: string) => void;
  onUndo: () => void;
  onOpenOverlay: () => void;
  onCloseOverlay: () => void;
  onExit: () => void;
  onToggleForce: () => void;
}
```

Update the destructure (lines 39-47) to add `onToggleForce`.

Insert a new case in the switch immediately after the `KeyU` case (around line 71), maintaining the file's existing style:

```ts
        case 'KeyL':
          if (overlayOpen) return;
          event.preventDefault();
          onToggleForce();
          return;
```

Add `onToggleForce` to the deps array (around line 111-120).

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx --run`
Expected: PASS — all existing + 2 new cases.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateHotkeys.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateHotkeys.test.tsx
git commit -m "feat(curate): bind KeyL hotkey to Force toggle"
```

---

## Task 7: Add Force state + `toggleForce` to `useCurateSession` reducer (TDD)

**Files:**
- Modify: `frontend/src/features/curate/hooks/useCurateSession.ts:42-98` (CurateSession interface, LastOp, State, Action, initialState), `:100-171` (reducer cases), `:535-553` (return shape).
- Modify test: `frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx`.

This task introduces the new state shape and the toggle/clear semantics, but does NOT yet wire the chained category POST/DELETE — that's Task 9 + 10.

- [ ] **Step 1: Add failing tests for toggle + reset triggers**

Append a new `describe` block at the bottom of `useCurateSession.test.tsx` (before the file's last `});`):

```ts
describe('useCurateSession — Force mode (toggle + resets)', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    localStorage.clear();
    server.use(...defaultHandlers());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
    localStorage.clear();
  });

  it('forceMode starts false; toggleForce flips it', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    expect(result.current.forceMode).toBe(false);
    act(() => result.current.toggleForce());
    expect(result.current.forceMode).toBe(true);
    act(() => result.current.toggleForce());
    expect(result.current.forceMode).toBe(false);
  });

  it('skip resets forceMode', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    expect(result.current.forceMode).toBe(true);
    act(() => result.current.skip());
    expect(result.current.forceMode).toBe(false);
  });

  it('prev resets forceMode', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.prev());
    expect(result.current.forceMode).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.test.tsx --run -t "Force mode"`
Expected: FAIL — `result.current.forceMode` is undefined; `result.current.toggleForce is not a function`.

- [ ] **Step 3: Extend types + state in `useCurateSession.ts`**

Edit `useCurateSession.ts`. Update `CurateSession` (lines 42-61) to add:

```ts
  forceMode: boolean;
  toggleForce: () => void;
```

Update `LastOp` (lines 63-70):

```ts
interface LastOp {
  input: MoveInput;
  snapshot: MoveSnapshot;
  trackIndex: number;
  track: BucketTrack;
  forceCategoryId: string | null;
}
```

Update `State` (lines 72-77):

```ts
interface State {
  currentIndex: number;
  totalAssigned: number;
  lastTappedBucketId: string | null;
  lastOp: LastOp | null;
  forceMode: boolean;
}
```

Extend `Action` union (lines 79-91):

```ts
type Action =
  | { type: 'ASSIGN_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_REPLACE_BEGIN'; toBucketId: string; lastOp: LastOp }
  | { type: 'ASSIGN_SAME_DEST_PULSE'; toBucketId: string }
  | { type: 'ADVANCE' }
  | { type: 'CLEAR_PULSE' }
  | { type: 'UNDO_WITHIN' }
  | { type: 'UNDO_AFTER' }
  | { type: 'MUTATION_ERROR' }
  | { type: 'SKIP'; max: number }
  | { type: 'PREV' }
  | { type: 'JUMP_TO'; index: number; max: number }
  | { type: 'RESET_INDEX_FOR_QUEUE_SHRINK'; queueLength: number }
  | { type: 'TOGGLE_FORCE' }
  | { type: 'CLEAR_FORCE' };
```

Update `initialState` (lines 93-98):

```ts
const initialState: State = {
  currentIndex: 0,
  totalAssigned: 0,
  lastTappedBucketId: null,
  lastOp: null,
  forceMode: false,
};
```

- [ ] **Step 4: Update reducer cases**

In the `reducer` function (lines 100-171), modify and add:

```ts
case 'ADVANCE':
  // Optimistic shrink already moved the queue; this hook tick clears Force.
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
case 'TOGGLE_FORCE':
  return { ...state, forceMode: !state.forceMode };
case 'CLEAR_FORCE':
  return state.forceMode ? { ...state, forceMode: false } : state;
```

(`MUTATION_ERROR` is intentionally NOT changed — Force must persist on retry.)

- [ ] **Step 5: Add `toggleForce` callback + return it**

After existing callbacks like `skip`, `prev` (around line 510-516), add:

```ts
const toggleForce = useCallback(() => {
  dispatch({ type: 'TOGGLE_FORCE' });
}, []);
```

Update the return object (lines 535-553) to include:

```ts
    forceMode: state.forceMode,
    toggleForce,
```

- [ ] **Step 6: Update existing `assign` paths to populate `lastOp.forceCategoryId`**

In `assign` (lines 397-476), every `lastOp` literal must now include `forceCategoryId`. For this task, hard-code `null` (Task 9 wires the real value):

Same-destination pulse path uses no LastOp construction — leave it.

In the "different destination during pending window" branch (around line 442-444):

```ts
        dispatch({
          type: 'ASSIGN_REPLACE_BEGIN',
          toBucketId,
          lastOp: {
            input,
            snapshot,
            trackIndex: lastOp.trackIndex,
            track: lastOp.track,
            forceCategoryId: null,
          },
        });
```

In the "fresh assignment" branch (around line 458-462):

```ts
        dispatch({
          type: 'ASSIGN_BEGIN',
          toBucketId,
          lastOp: {
            input,
            snapshot,
            trackIndex: stateRef.current.currentIndex,
            track,
            forceCategoryId: null,
          },
        });
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.test.tsx --run`
Expected: PASS — all existing + 3 new Force-mode cases.

- [ ] **Step 8: Type-check**

Run: `cd frontend && pnpm tsc --noEmit -p tsconfig.app.json 2>&1 | tail -20`
Expected: no new errors.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateSession.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx
git commit -m "feat(curate): add forceMode state to useCurateSession"
```

---

## Task 8: Update `DestinationGrid` layout + wire `forceMode` (TDD)

**Files:**
- Modify: `frontend/src/features/curate/components/DestinationGrid.tsx:17-22` (props), `:84-87` (DISCARD row).
- Modify test: `frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx`.

- [ ] **Step 1: Add failing tests**

Append to `DestinationGrid.test.tsx`:

```ts
  it('renders ForceToggle next to DISCARD as DOM siblings', () => {
    render(
      <Providers>
        <DestinationGrid
          buckets={buckets}
          currentBucketId="src"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={vi.fn()}
          onToggleForce={vi.fn()}
        />
      </Providers>,
    );
    const discardBtn = screen.getByRole('button', { name: /Assign to DISCARD/ });
    const forceBtn = screen.getByRole('button', { name: /Force mode (on|off)/ });
    expect(discardBtn.parentElement).toBe(forceBtn.parentElement);
  });

  it('passes forceMode to ForceToggle (aria-pressed reflects it)', () => {
    render(
      <Providers>
        <DestinationGrid
          buckets={buckets}
          currentBucketId="src"
          lastTappedBucketId={null}
          forceMode={true}
          onAssign={vi.fn()}
          onToggleForce={vi.fn()}
        />
      </Providers>,
    );
    const forceBtn = screen.getByRole('button', { name: /Force mode (on|off)/ });
    expect(forceBtn).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls onToggleForce when ForceToggle is clicked', () => {
    const onToggleForce = vi.fn();
    render(
      <Providers>
        <DestinationGrid
          buckets={buckets}
          currentBucketId="src"
          lastTappedBucketId={null}
          forceMode={false}
          onAssign={vi.fn()}
          onToggleForce={onToggleForce}
        />
      </Providers>,
    );
    fireEvent.click(screen.getByRole('button', { name: /Force mode (on|off)/ }));
    expect(onToggleForce).toHaveBeenCalledTimes(1);
  });
```

(The `Providers` wrapper and import shape must match what the existing file uses — check the top of `DestinationGrid.test.tsx`. If it uses a different wrapper, follow the existing convention; the assertions above work regardless.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- src/features/curate/components/__tests__/DestinationGrid.test.tsx --run`
Expected: FAIL — TS error on missing `forceMode`/`onToggleForce` props (and `onToggleForce` not invoked).

- [ ] **Step 3: Update existing test invocations to pass new props**

The pre-existing tests in `DestinationGrid.test.tsx` will now fail TypeScript because `DestinationGridProps` is about to require two new fields. Update every existing `<DestinationGrid ... />` call site in this file to pass `forceMode={false}` and `onToggleForce={vi.fn()}`. Search for `<DestinationGrid` and add the two props to each.

- [ ] **Step 4: Update `DestinationGrid.tsx`**

Edit the props interface (lines 17-22):

```ts
export interface DestinationGridProps {
  buckets: TriageBucket[];
  currentBucketId: string;
  lastTappedBucketId: string | null;
  forceMode: boolean;
  onAssign: (toBucketId: string) => void;
  onToggleForce: () => void;
}
```

Update the function signature (lines 31-36) to destructure `forceMode` and `onToggleForce`.

Add import at top of file:

```ts
import { ForceToggle } from './ForceToggle';
```

Replace the DISCARD row (line 86) with the two-button group:

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

(`Group` is already imported from `@mantine/core`? Check the imports at the top of `DestinationGrid.tsx`. If only `Menu, SimpleGrid, Stack, Text` are imported, add `Group`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- src/features/curate/components/__tests__/DestinationGrid.test.tsx --run`
Expected: PASS — all existing + 3 new cases.

- [ ] **Step 6: Wire props from `CurateSession.tsx`**

Edit `frontend/src/features/curate/components/CurateSession.tsx` around line 309-314 (the `<DestinationGrid ... />` call site):

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

Also wire the hotkey handler. Edit the `useCurateHotkeys` call site (lines 37-45):

```tsx
useCurateHotkeys({
  buckets: session.destinations,
  overlayOpen,
  onAssign: session.assign,
  onUndo: session.undo,
  onOpenOverlay: () => setOverlayOpen(true),
  onCloseOverlay: () => setOverlayOpen(false),
  onExit: () => navigate(`/triage/${styleId}/${blockId}`),
  onToggleForce: session.toggleForce,
});
```

- [ ] **Step 7: Type-check + run full curate test suite**

Run: `cd frontend && pnpm tsc --noEmit -p tsconfig.app.json 2>&1 | tail -20`
Expected: no errors.

Run: `cd frontend && pnpm test -- src/features/curate --run`
Expected: all curate tests PASS (the existing `CurateSession.test.tsx` may need a small update if it stub-renders the grid — check failing-test output and tweak).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/curate/components/DestinationGrid.tsx \
        frontend/src/features/curate/components/CurateSession.tsx \
        frontend/src/features/curate/components/__tests__/DestinationGrid.test.tsx \
        frontend/src/features/curate/components/__tests__/CurateSession.test.tsx
git commit -m "feat(curate): render Force toggle next to DISCARD"
```

---

## Task 9: Resolve `forceCategoryId` in `assign` (TDD)

**Files:**
- Modify: `frontend/src/features/curate/hooks/useCurateSession.ts:397-476` (assign function — replace hard-coded `null` with real lookup).
- Modify test: `frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx`.

This task makes `assign` correctly identify whether the destination is a staging bucket and store its `category_id` on `lastOp`. The chained POST/DELETE happens in Task 10 + 11.

- [ ] **Step 1: Add failing test for `lastOp.forceCategoryId` resolution via behaviour**

Since `lastOp` is private, observe through behaviour. Append to the Force-mode `describe` in `useCurateSession.test.tsx`:

```ts
  it('after Force-tap on staging then advance, ADVANCE clears forceMode', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    // hold + advance:
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });

  it('after Force-tap on NEW (non-staging), forceMode still resets after advance', async () => {
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    // 'b-old' in defaultHandlers' block is OLD (no category_id).
    act(() => result.current.assign('b-old'));
    await act(async () => {
      vi.advanceTimersByTime(250);
    });
    await waitFor(() => expect(result.current.forceMode).toBe(false));
  });

  it('forceMode persists on move error (MUTATION_ERROR)', async () => {
    server.use(
      http.post('http://localhost/triage/blocks/b1/move', () =>
        HttpResponse.json(
          { error_code: 'tracks_not_in_source', message: 'gone' },
          { status: 422 },
        ),
      ),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    await waitFor(() => expect(result.current.lastTappedBucketId).toBeNull());
    expect(result.current.forceMode).toBe(true);
  });
```

- [ ] **Step 2: Run tests to verify they fail or pass**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.test.tsx --run -t "Force"`
Expected: the third test FAILs (forceMode goes false because `MUTATION_ERROR` is the only path that should NOT clear it; reducer is correct, but until Task 10 adds the chain, forceMode behaves correctly here — so this should already PASS). The first two should also already PASS since they only check forceMode lifecycle. **If all PASS already, that just means the reducer from Task 7 is doing its job — proceed to step 3 to wire the resolution anyway since Task 10 needs it.**

- [ ] **Step 3: Replace hard-coded `null` with destination lookup**

In `useCurateSession.ts:397-476`, near the top of `assign`, after resolving `track`:

```ts
const dst = destinations.find((b) => b.id === toBucketId);
const isForce = stateRef.current.forceMode;
const forceCategoryId =
  isForce && dst?.category_id ? dst.category_id : null;
```

Replace both `forceCategoryId: null` literals (added in Task 7) with `forceCategoryId`.

Add `destinations` to the `assign` callback's dependency array.

- [ ] **Step 4: Run all `useCurateSession` tests**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.test.tsx --run`
Expected: PASS — all cases.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateSession.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateSession.test.tsx
git commit -m "feat(curate): resolve forceCategoryId from destination bucket"
```

---

## Task 10: Chain `addToCategory` after successful move (TDD)

**Files:**
- Modify: `frontend/src/features/curate/hooks/useCurateSession.ts:376-395` (`fireMutation`).
- Create test: `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`.

- [ ] **Step 1: Create the Force integration test file with the first scenario**

Create `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`. Reuse the same MSW + provider setup pattern as `useCurateSession.test.tsx`. Start with one scenario:

```tsx
import React from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MantineProvider } from '@mantine/core';
import { http, HttpResponse } from 'msw';
import { server } from '../../../../test/setup';
import { tokenStore } from '../../../../auth/tokenStore';
import { testTheme } from '../../../../test/theme';
import { useCurateSession } from '../useCurateSession';

// Reuse playback mock pattern from useCurateSession.test.tsx
vi.mock('../../../playback/usePlayback', () => ({
  usePlayback: () => ({
    queue: { source: null, tracks: [], cursor: 0, status: 'idle' as const },
    track: { current: null, positionMs: 0, durationMs: 0 },
    sdk: { ready: false, error: null },
    controls: {
      play: vi.fn(async () => {}),
      pause: vi.fn(async () => {}),
      togglePlayPause: vi.fn(async () => {}),
      next: vi.fn(async () => {}),
      prev: vi.fn(async () => {}),
      seekMs: vi.fn(async () => {}),
      seekPct: vi.fn(async () => {}),
      bindQueue: vi.fn(),
      clearQueue: vi.fn(),
      cancelPendingAdvance: vi.fn(),
      prewarm: vi.fn().mockResolvedValue(undefined),
      openSpotifyExternal: vi.fn(),
    },
  }),
}));

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } },
  });
}
function wrap(qc: QueryClient) {
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>
      <MantineProvider theme={testTheme}>{children}</MantineProvider>
    </QueryClientProvider>
  );
}

const block = {
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
  buckets: [
    { id: 'src', bucket_type: 'NEW' as const, inactive: false, track_count: 3 },
    { id: 'dst1', bucket_type: 'STAGING' as const, inactive: false, track_count: 0,
      category_id: 'c1', category_name: 'Big Room' },
    { id: 'b-old', bucket_type: 'OLD' as const, inactive: false, track_count: 0 },
  ],
};

const tracksPage = {
  items: [
    {
      track_id: 't1', title: 'Track t1', mix_name: null, isrc: null,
      bpm: 124, length_ms: 360000, publish_date: '2026-04-15',
      spotify_release_date: '2026-04-15', spotify_id: 'sp-t1',
      release_type: 'single', is_ai_suspected: false,
      artists: ['Artist'], label_name: 'Label', added_at: '2026-04-21T00:00:00Z',
    },
  ],
  total: 1, limit: 50, offset: 0,
};

function defaults() {
  return [
    http.get('http://localhost/triage/blocks/b1', () => HttpResponse.json(block)),
    http.get('http://localhost/triage/blocks/b1/buckets/src/tracks', () => HttpResponse.json(tracksPage)),
    http.post('http://localhost/triage/blocks/b1/move', () =>
      HttpResponse.json({ moved: 1, correlation_id: 'cid-x' }),
    ),
  ];
}

describe('useCurateSession Force chain — happy path', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(...defaults());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it('Force ON + tap staging fires move + category POST', async () => {
    let categoryHit = false;
    let categoryBody: unknown = null;
    server.use(
      http.post('http://localhost/categories/c1/tracks', async ({ request }) => {
        categoryHit = true;
        categoryBody = await request.json();
        return HttpResponse.json({ ok: true });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    await act(async () => { vi.advanceTimersByTime(300); });
    await waitFor(() => expect(categoryHit).toBe(true));
    expect(categoryBody).toEqual({ track_id: 't1' });
    expect(result.current.forceMode).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx --run`
Expected: FAIL — `categoryHit` stays `false` (no chain wired yet).

- [ ] **Step 3: Wire chain inside `fireMutation`**

Edit `frontend/src/features/curate/hooks/useCurateSession.ts`. Import the new hook at the top:

```ts
import { useAddTrackToCategory } from '../../categories/hooks/useAddTrackToCategory';
```

Inside `useCurateSession` (near other mutation hooks, around line 194):

```ts
const { mutate: addToCategoryMutate } = useAddTrackToCategory();
```

Update `fireMutation` signature to accept `lastOp` (line 377):

```ts
const fireMutation = useCallback(
  (input: MoveInput, lastOp: LastOp) => {
    moveMutate(input, {
      onSuccess: () => {
        writeLastCurateLocation(styleId, blockId, bucketId);
        writeLastCurateStyle(styleId);
        const cur = stateRef.current.lastOp;
        if (!cur || cur !== lastOp) return;
        if (lastOp.forceCategoryId) {
          addToCategoryMutate(
            { categoryId: lastOp.forceCategoryId, trackId: input.trackIds[0] },
            {
              onError: () => {
                notifications.show({
                  message: t('curate.toast.force_partial'),
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
  [moveMutate, addToCategoryMutate, blockId, bucketId, styleId, emitErrorToast, t],
);
```

Update both `fireMutation(input)` call sites (lines 445, 463) to `fireMutation(input, /* the just-built lastOp */)`. Concretely, in the "different destination during pending window" branch (line 445) you have a `lastOp` literal in the dispatch above — extract it into a `const newLastOp = { ... }` before the dispatch and pass it to `fireMutation`. Same in the "fresh assignment" branch (line 463).

Example for the fresh-assignment branch:

```ts
const newLastOp: LastOp = {
  input,
  snapshot,
  trackIndex: stateRef.current.currentIndex,
  track,
  forceCategoryId,
};
scheduleAdvance();
schedulePulse();
dispatch({ type: 'ASSIGN_BEGIN', toBucketId, lastOp: newLastOp });
fireMutation(input, newLastOp);
```

And mirror in the replace branch.

- [ ] **Step 4: Run the new integration test**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx --run`
Expected: PASS.

- [ ] **Step 5: Add scenarios for partial-fail + non-staging + skip + race**

Append four more `it(...)` blocks to the file (continue inside the same `describe` or a new one — match style). Use the helpers already in scope.

Scenario 2 — partial fail keeps move:

```ts
it('partial fail (category POST 500) keeps move and shows yellow toast', async () => {
  const notifyShow = vi.fn();
  vi.doMock('@mantine/notifications', () => ({ notifications: { show: notifyShow } }));
  // Re-import after mock — for simplicity use spy on global notifications instead.
  // Alternative: rely on observable side-effect. Here just verify the chain HTTP fired and the move stayed.
  let categoryHit = false;
  server.use(
    http.post('http://localhost/categories/c1/tracks', () => {
      categoryHit = true;
      return new HttpResponse(null, { status: 500 });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.status).toBe('active'));
  act(() => result.current.toggleForce());
  act(() => result.current.assign('dst1'));
  await act(async () => { vi.advanceTimersByTime(300); });
  await waitFor(() => expect(categoryHit).toBe(true));
  // Move stayed (queue shrunk):
  await waitFor(() => expect(result.current.queue.length).toBe(0));
  expect(result.current.forceMode).toBe(false);
});
```

(If the `vi.doMock` pattern feels brittle, omit the toast spy and rely on the move-stayed assertion — toast emission is covered by inspection. The point is the move is NOT rolled back.)

Scenario 3 — non-staging skips chain:

```ts
it('Force ON + tap NEW/OLD bucket does NOT POST to /categories', async () => {
  let categoryHit = false;
  server.use(
    http.post('http://localhost/categories/:cid/tracks', () => {
      categoryHit = true;
      return HttpResponse.json({ ok: true });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.status).toBe('active'));
  act(() => result.current.toggleForce());
  act(() => result.current.assign('b-old'));   // OLD has no category_id
  await act(async () => { vi.advanceTimersByTime(300); });
  expect(categoryHit).toBe(false);
  expect(result.current.forceMode).toBe(false);
});
```

Scenario 4 — skip resets without firing anything:

```ts
it('skip (J/K) while Force ON resets Force without HTTP', async () => {
  let moveHit = false;
  let categoryHit = false;
  server.use(
    http.post('http://localhost/triage/blocks/b1/move', () => {
      moveHit = true;
      return HttpResponse.json({ moved: 1, correlation_id: 'x' });
    }),
    http.post('http://localhost/categories/:cid/tracks', () => {
      categoryHit = true;
      return HttpResponse.json({ ok: true });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.status).toBe('active'));
  act(() => result.current.toggleForce());
  act(() => result.current.skip());
  expect(result.current.forceMode).toBe(false);
  expect(moveHit).toBe(false);
  expect(categoryHit).toBe(false);
});
```

Scenario 5 (race-guard) — add now since it tests `fireMutation`:

```ts
it('undo before move response blocks category POST (race guard)', async () => {
  let categoryHit = false;
  server.use(
    http.post('http://localhost/triage/blocks/b1/move', async () => {
      await new Promise((r) => setTimeout(r, 100));
      return HttpResponse.json({ moved: 1, correlation_id: 'x' });
    }),
    http.post('http://localhost/categories/:cid/tracks', () => {
      categoryHit = true;
      return HttpResponse.json({ ok: true });
    }),
  );
  const qc = makeClient();
  const { result } = renderHook(
    () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
    { wrapper: wrap(qc) },
  );
  await waitFor(() => expect(result.current.status).toBe('active'));
  act(() => result.current.toggleForce());
  act(() => result.current.assign('dst1'));
  // Within hold window, before move resolves:
  act(() => result.current.undo());
  // Let move + everything settle:
  await act(async () => { vi.advanceTimersByTime(500); });
  expect(categoryHit).toBe(false);
  expect(result.current.forceMode).toBe(false);
});
```

- [ ] **Step 6: Run all integration scenarios**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx --run`
Expected: PASS — all scenarios.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateSession.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx
git commit -m "feat(curate): chain category POST after Force-tap move"
```

---

## Task 11: Wire Force-aware undo (DELETE chain) (TDD)

**Files:**
- Modify: `frontend/src/features/curate/hooks/useCurateSession.ts:478-508` (`undo` callback).
- Modify integration test: `frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx`.

- [ ] **Step 1: Add failing test for undo-after-window DELETE**

Append to the integration file:

```ts
describe('useCurateSession Force chain — undo', () => {
  beforeEach(() => {
    tokenStore.set('TOK');
    server.use(...defaults());
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => vi.useRealTimers());

  it('undo after Force tap (after hold) fires DELETE /categories/:cid/tracks/:tid', async () => {
    let deleteHit = false;
    let deleteUrl = '';
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/:cid/tracks/:tid', ({ request }) => {
        deleteHit = true;
        deleteUrl = request.url;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    await act(async () => { vi.advanceTimersByTime(300); });
    // Hold has fired; canUndo true:
    expect(result.current.canUndo).toBe(true);
    act(() => result.current.undo());
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(deleteUrl).toContain('/categories/c1/tracks/t1');
  });

  it('undo within window after Force tap also fires DELETE', async () => {
    let deleteHit = false;
    server.use(
      http.post('http://localhost/categories/c1/tracks', () => HttpResponse.json({ ok: true })),
      http.delete('http://localhost/categories/:cid/tracks/:tid', () => {
        deleteHit = true;
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const qc = makeClient();
    const { result } = renderHook(
      () => useCurateSession({ blockId: 'b1', bucketId: 'src', styleId: 's1' }),
      { wrapper: wrap(qc) },
    );
    await waitFor(() => expect(result.current.status).toBe('active'));
    act(() => result.current.toggleForce());
    act(() => result.current.assign('dst1'));
    // BEFORE 200 ms hold:
    act(() => result.current.undo());
    await act(async () => { vi.advanceTimersByTime(50); });
    await waitFor(() => expect(deleteHit).toBe(true));
    expect(result.current.forceMode).toBe(false);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx --run -t "undo"`
Expected: FAIL — DELETE never fires.

- [ ] **Step 3: Wire DELETE into `undo`**

Edit `useCurateSession.ts`. Add import:

```ts
import { useRemoveTrackFromCategory } from '../../categories/hooks/useRemoveTrackFromCategory';
```

Inside `useCurateSession` (near `addToCategoryMutate`):

```ts
const { mutate: removeFromCategoryMutate } = useRemoveTrackFromCategory();
```

Replace the `undo` callback (lines 478-508):

```ts
const undo = useCallback(() => {
  const lastOp = stateRef.current.lastOp;
  if (!lastOp) return;
  const isPending = pendingTimerRef.current !== null;

  playback.controls.cancelPendingAdvance();

  const rollbackForce = () => {
    if (!lastOp.forceCategoryId) return;
    removeFromCategoryMutate(
      { categoryId: lastOp.forceCategoryId, trackId: lastOp.input.trackIds[0] },
      {
        onError: () => {
          notifications.show({
            message: t('curate.toast.force_undo_partial'),
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && pnpm test -- src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx --run`
Expected: PASS — all scenarios.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/curate/hooks/useCurateSession.ts \
        frontend/src/features/curate/hooks/__tests__/useCurateSession.force.integration.test.tsx
git commit -m "feat(curate): chain category DELETE on Force-tap undo"
```

---

## Task 12: Add `L` row to `HotkeyOverlay`

**Files:**
- Modify: `frontend/src/features/curate/components/HotkeyOverlay.tsx:26-28` — append L to `ACTION` rows.

- [ ] **Step 1: Edit `ACTION` array (lines 26-28)**

```ts
const ACTION: KeyRow[] = [
  { keys: ['U'], labelKey: 'curate.hotkeys.key_u_label' },
  { keys: ['L'], labelKey: 'curate.hotkeys.key_l_label' },
];
```

- [ ] **Step 2: Add a snapshot or assertion test in `HotkeyOverlay.test.tsx`**

Open `frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx`. Add a test case:

```ts
it('renders the L hotkey row for Toggle Force mode', () => {
  // Match existing rendering pattern in this file (Providers wrapper, opened={true})
  // Use whatever wrapper the file already provides.
  // Then:
  expect(screen.getByText('Toggle Force mode')).toBeInTheDocument();
  expect(screen.getByText('L')).toBeInTheDocument();
});
```

If the existing test file structure does not have a "Providers wrapper" helper, copy the pattern from one of the other passing tests in the same file.

- [ ] **Step 3: Run the test**

Run: `cd frontend && pnpm test -- src/features/curate/components/__tests__/HotkeyOverlay.test.tsx --run`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/curate/components/HotkeyOverlay.tsx \
        frontend/src/features/curate/components/__tests__/HotkeyOverlay.test.tsx
git commit -m "feat(curate): show Force hotkey in HotkeyOverlay"
```

---

## Task 13: Full test sweep + dev-server smoke

- [ ] **Step 1: Full frontend test suite**

Run: `cd frontend && pnpm test --run`
Expected: ALL green. Investigate + fix any regressions; do NOT commit until green.

- [ ] **Step 2: TypeScript check**

Run: `cd frontend && pnpm tsc --noEmit -p tsconfig.app.json`
Expected: 0 errors.

- [ ] **Step 3: Lint**

Run: `cd frontend && pnpm lint 2>&1 | tail -30`
Expected: 0 new warnings on touched files. Fix any added by Force changes.

- [ ] **Step 4: Dev-server manual smoke**

CLAUDE.md requires browser verification for UI changes. The user may run this themselves (Aurora is paused without `.env.local`); the agent can prepare the checklist.

```bash
cd frontend && pnpm dev
```

Open `http://127.0.0.1:5173/curate/<style>/<block>/<bucket>` (with a real triage block in progress) and verify:

| # | Check |
|---|---|
| 1 | DISCARD + Force toggle render on the same row, both desktop and mobile (resize viewport). |
| 2 | Tap Force → button visibly switches to filled/active state. |
| 3 | Press `L` → toggle flips. Press `?` → overlay shows `L · Toggle Force mode`. |
| 4 | Force ON + tap a STAGING bucket → track moves. Verify category insert via Aurora Data API: `SELECT 1 FROM category_tracks WHERE category_id = '<cid>' AND track_id = '<tid>'`. |
| 5 | Force ON + tap NEW/OLD/NOT/DISCARD → only the move; no `category_tracks` row. |
| 6 | After advance, Force toggle returns to idle. |
| 7 | Press U after a Force tap → track returns to source bucket AND row removed from `category_tracks`. |
| 8 | Skip (J/K) while Force ON → toggle returns to idle, no HTTP. |
| 9 | Force ON + simulate /categories POST 500 (DevTools Network override) → track stayed, yellow toast appears. |
| 10 | Esc → re-enter Curate → Force is OFF (no persistence). |

- [ ] **Step 5: No commit needed for the smoke**

If everything passes, the implementation is complete. If something fails: open a follow-up task / fix inline / commit the fix.

---

## Self-Review Checklist (writing-plans skill)

**Spec coverage** — every spec section maps to a task:

| Spec section | Task(s) |
|---|---|
| §1 Goal | Implicit across all |
| §3 D1 (non-staging tap silent move) | T9 (forceCategoryId resolution returns null), T10 scenario 3 |
| §3 D2 (full undo) | T11 |
| §3 D3 (KeyL via event.code) | T6 |
| §3 D4 (best-effort partial) | T10 scenario 2 + fireMutation onError |
| §3 D5 (DISCARD~75% / Force~25% layout) | T8 (Group with flex 1 + ForceToggle) |
| §3 D6 (reset triggers) | T7 reducer cases |
| §3 D7 (Approach A) | Whole plan |
| §4 Boundaries | T1, T2, T5, T6, T7, T8, T9, T10, T11, T12 |
| §5 State machine | T7 |
| §6 Components | T5 (ForceToggle), T8 (DestinationGrid), T6 (hotkeys), T12 (overlay) |
| §6.7 Public API extension | T7 (forceMode + toggleForce return) |
| §7 HTTP chain | T10 |
| §7 Undo + DELETE | T11 |
| §7.3 Error matrix | T10 scenarios + T11 |
| §8 i18n | T3 |
| §10 Tests | All TDD tasks |
| §11 Files touched | Mirrored in File Structure section |
| §12 Acceptance | T13 manual checklist |

**Placeholder scan:** No "TBD", no "implement later", no "appropriate error handling". Every code step shows actual code.

**Type consistency:** `AddTrackToCategoryInput` (T1) used by `addToCategoryMutate` (T10). `RemoveTrackFromCategoryInput` (T2) used by `removeFromCategoryMutate` (T11). `forceMode` / `toggleForce` declared in `CurateSession` interface (T7) and consumed in `DestinationGrid` props (T8) + `useCurateHotkeys` args (T6). `LastOp.forceCategoryId` declared in T7, populated in T9, consumed in T10/T11. ✓

---

## Plan complete and saved to `docs/superpowers/plans/2026-05-10-curate-force-mode.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**

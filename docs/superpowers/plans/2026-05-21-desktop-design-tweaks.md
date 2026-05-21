# Desktop Design Tweaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a collapsible desktop navbar (header toggle), narrow both players by 15% (520→442px), and highlight the playing track in the category player like triage does.

**Architecture:** Mantine `AppShell` already supports `navbar.collapsed.desktop`; add session state + a `Burger` toggle in the header. Player widths are single constants. The category highlight mirrors triage's `data-current` + `bg` row pattern, threaded `CategoryDetailPage → TracksTab → TrackRow`. Frontend-only.

**Tech Stack:** React 19, TypeScript, Mantine 9, react-router, react-i18next (EN-only), Vitest + Testing Library. pnpm; run frontend commands from `frontend/`.

**Spec:** `docs/superpowers/specs/2026-05-21-desktop-design-tweaks-design.md`

---

## File structure

**Changed**
- `frontend/src/routes/_layout.tsx` — collapsible navbar + Burger; export `AppShellInner` for testing. (+test)
- `frontend/src/i18n/en.json` — `appshell.toggle_nav` key.
- `frontend/src/features/categories/components/CategoryPlayerPanel.module.css` — 520 → 442.
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — 520 → 442 (both branches).
- `frontend/src/features/categories/components/TrackRow.tsx` — `isCurrent` highlight. (+test)
- `frontend/src/features/categories/components/TracksTab.tsx` — thread `currentTrackId`.
- `frontend/src/features/categories/routes/CategoryDetailPage.tsx` — pass current track id.

**New**
- `frontend/src/routes/__tests__/_layout.test.tsx`

No backend/API/schema/router-config change.

---

### Task 1: Collapsible desktop navbar

**Files:**
- Modify: `frontend/src/i18n/en.json`
- Modify: `frontend/src/routes/_layout.tsx`
- Test: `frontend/src/routes/__tests__/_layout.test.tsx`

- [ ] **Step 1: Add the i18n key**

In `frontend/src/i18n/en.json`, find the `"appshell"` object (has `wordmark`, `home`, `categories`, …). Add a key:
```json
"toggle_nav": "Toggle navigation"
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/routes/__tests__/_layout.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import { MemoryRouter } from 'react-router';
import '../../i18n';

// Force desktop so the Burger + navbar render (jsdom has no matchMedia match).
vi.mock('@mantine/hooks', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@mantine/hooks')>();
  return { ...actual, useMediaQuery: () => true };
});
// UserMenu uses useAuth(); stub it so the layout test needs no auth provider.
vi.mock('../../components/UserMenu', () => ({ UserMenu: () => null }));

import { AppShellInner } from '../_layout';

function r() {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <AppShellInner />
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe('AppShellInner navbar toggle', () => {
  it('toggles the navbar collapse via the Burger', async () => {
    r();
    const burger = screen.getByLabelText('Toggle navigation');
    expect(burger).toHaveAttribute('aria-expanded', 'true'); // expanded by default
    await userEvent.click(burger);
    expect(burger).toHaveAttribute('aria-expanded', 'false'); // collapsed
    await userEvent.click(burger);
    expect(burger).toHaveAttribute('aria-expanded', 'true'); // expanded again
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

From `frontend/`: `pnpm test src/routes/__tests__/_layout.test.tsx`
Expected: FAIL — `AppShellInner` is not exported / no Burger with that label yet.

- [ ] **Step 4: Implement the collapsible navbar**

Edit `frontend/src/routes/_layout.tsx`:

1. Update imports:
```tsx
import { AppShell, Burger, Group, NavLink, Stack, Text, useMantineTheme } from '@mantine/core';
import { useDisclosure, useMediaQuery } from '@mantine/hooks';
```
(`Burger` added to `@mantine/core`; `useDisclosure` added to `@mantine/hooks` — keep `useMediaQuery`.)

2. Export the inner component (for the test) — change `function AppShellInner()` to `export function AppShellInner()`.

3. Inside `AppShellInner`, add the session collapse state near the other hooks (after `const isDesktop = ...`):
```tsx
  const [navCollapsed, { toggle: toggleNav }] = useDisclosure(false);
```

4. Update the `navbar` prop on `<AppShell>`:
```tsx
      navbar={
        isDesktop
          ? { width: 240, breakpoint: 'md', collapsed: { desktop: navCollapsed, mobile: true } }
          : undefined
      }
```

5. Replace the header's inner content to add the Burger on the left (desktop only):
```tsx
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            {isDesktop && (
              <Burger
                opened={!navCollapsed}
                onClick={toggleNav}
                size="sm"
                aria-label={t('appshell.toggle_nav')}
                aria-expanded={!navCollapsed}
              />
            )}
            <Text fw={700} size="lg">
              {t('appshell.wordmark')}
            </Text>
          </Group>
          <UserMenu />
        </Group>
      </AppShell.Header>
```
(`aria-expanded={!navCollapsed}` is forwarded by Mantine `Burger` to its `<button>` — it makes the toggle both accessible and testable. Mantine `Burger` does not set `aria-expanded` on its own.)

Leave the desktop `AppShell.Navbar`, `AppShell.Main`, and the mobile footer unchanged.

- [ ] **Step 5: Run the test**

From `frontend/`: `pnpm test src/routes/__tests__/_layout.test.tsx`
Expected: PASS.

- [ ] **Step 6: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: no errors (2 pre-existing warnings in `useCurateSession.ts` + `theme.ts` are OK).

- [ ] **Step 7: Commit**

NO `Co-Authored-By` trailer (pre-commit hook rejects it).
```bash
git add frontend/src/routes/_layout.tsx frontend/src/routes/__tests__/_layout.test.tsx frontend/src/i18n/en.json
git commit -m "feat(frontend): collapsible desktop navbar via header burger"
```

---

### Task 2: Narrow both players to 442px

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.module.css`
- Modify: `frontend/src/features/triage/components/BucketPlayerPanel.tsx`

- [ ] **Step 1: Category player CSS module**

In `frontend/src/features/categories/components/CategoryPlayerPanel.module.css`, change the `.root` width:
```css
.root {
  width: 442px;
  flex-shrink: 0;
  padding: var(--mantine-spacing-md);
  border-right: 1px solid var(--mantine-color-default-border);
  height: 100%;
  overflow-y: auto;
}
```
(Only the `width` value changes from `520px` to `442px`; keep the other rules exactly.)

- [ ] **Step 2: Triage player inline width**

In `frontend/src/features/triage/components/BucketPlayerPanel.tsx`, BOTH `<Stack>` roots currently use `style={{ width: 520, flexShrink: 0, minWidth: 0 }}`. Change BOTH to:
```tsx
style={{ width: 442, flexShrink: 0, minWidth: 0 }}
```

- [ ] **Step 3: Typecheck + run the touched player tests**

From `frontend/`: `pnpm typecheck && pnpm test src/features/triage/components/__tests__/BucketPlayerPanel.test.tsx src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: no type errors; tests pass (width is a style constant; no test asserts the exact px, so they stay green).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/categories/components/CategoryPlayerPanel.module.css frontend/src/features/triage/components/BucketPlayerPanel.tsx
git commit -m "style(frontend): narrow category and triage players to 442px"
```

---

### Task 3: Highlight the playing track in the category player

**Files:**
- Modify: `frontend/src/features/categories/components/TrackRow.tsx`
- Test: `frontend/src/features/categories/components/__tests__/TrackRow.test.tsx`
- Modify: `frontend/src/features/categories/components/TracksTab.tsx`
- Modify: `frontend/src/features/categories/routes/CategoryDetailPage.tsx`

- [ ] **Step 1: Add the failing TrackRow test**

In `frontend/src/features/categories/components/__tests__/TrackRow.test.tsx`, add (uses the existing `W` desktop wrapper + `baseTrack` fixture; `TrackRow` requires a `categoryId` prop):

```tsx
  it('marks the row data-current when isCurrent', () => {
    const { container } = render(
      <W>
        <TrackRow track={baseTrack} variant="desktop" categoryId="c1" isCurrent />
      </W>,
    );
    expect(container.querySelector('[data-current="true"]')).not.toBeNull();
  });

  it('has no data-current when not current', () => {
    const { container } = render(
      <W>
        <TrackRow track={baseTrack} variant="desktop" categoryId="c1" />
      </W>,
    );
    expect(container.querySelector('[data-current="true"]')).toBeNull();
  });
```

Place them inside the existing top-level `describe` (or a nested one). If `baseTrack`/`W` are named differently, use the real names from the file.

- [ ] **Step 2: Run to verify the first test fails**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: "marks the row data-current when isCurrent" FAILS — no `data-current` rendered yet.

- [ ] **Step 3: Add `isCurrent` to `TrackRow`**

In `frontend/src/features/categories/components/TrackRow.tsx`:

1. Add `isCurrent?: boolean` to `TrackRowProps`:
```tsx
export interface TrackRowProps {
  track: CategoryTrack;
  variant: 'desktop' | 'mobile';
  categoryId: string;
  actions?: ReactNode;
  onPlay?: () => void;
  isCurrent?: boolean;
}
```

2. Destructure it: `export function TrackRow({ track, variant, categoryId, actions, onPlay, isCurrent }: TrackRowProps) {`

3. Desktop branch — the row is `<Table.Tr>`. Change it to:
```tsx
    return (
      <Table.Tr
        data-current={isCurrent ? 'true' : undefined}
        bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}
      >
```

4. Mobile branch — the row is `<Card withBorder padding="sm" style={{ position: 'relative' }}>`. Change it to:
```tsx
    <Card
      withBorder
      padding="sm"
      style={{ position: 'relative' }}
      data-current={isCurrent ? 'true' : undefined}
      bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}
    >
```

(Same token + marker as the triage `BucketTrackRow`. Leave all other row content unchanged.)

- [ ] **Step 4: Run the TrackRow test**

From `frontend/`: `pnpm test src/features/categories/components/__tests__/TrackRow.test.tsx`
Expected: PASS (existing tests + 2 new).

- [ ] **Step 5: Thread `currentTrackId` through `TracksTab`**

In `frontend/src/features/categories/components/TracksTab.tsx`:

1. Add to `TracksTabProps`:
```tsx
  currentTrackId?: string | null;
```

2. Destructure `currentTrackId` in the component params.

3. Pass `isCurrent` to BOTH `<TrackRow>` renders (the mobile `items.map` and the desktop `items.map`). Add this prop to each:
```tsx
              isCurrent={currentTrackId != null && track.id === currentTrackId}
```
(In the mobile map the variable is `tr` — use `tr.id`: `isCurrent={currentTrackId != null && tr.id === currentTrackId}`. Match the actual loop variable name in each map.)

- [ ] **Step 6: Pass the playing track id from `CategoryDetailPage`**

In `frontend/src/features/categories/routes/CategoryDetailPage.tsx`, the `tracksTab` element renders `<TracksTab ... onPlay={playTrack} />`. Add:
```tsx
      currentTrackId={playback.track.current?.id ?? null}
```
(`playback` is already obtained via `usePlayback()` at the top of the component.)

- [ ] **Step 7: Typecheck + lint + run category tests**

From `frontend/`:
```
pnpm typecheck && pnpm lint && pnpm test src/features/categories
```
Expected: no type/lint errors (only the 2 pre-existing warnings); all category tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/features/categories/components/TrackRow.tsx frontend/src/features/categories/components/__tests__/TrackRow.test.tsx frontend/src/features/categories/components/TracksTab.tsx frontend/src/features/categories/routes/CategoryDetailPage.tsx
git commit -m "feat(categories): highlight the currently playing track row"
```

---

### Task 4: Full verification

- [ ] **Step 1: Whole suite**

From `frontend/`: `pnpm test`
Expected: all tests pass.

- [ ] **Step 2: Typecheck + lint**

From `frontend/`: `pnpm typecheck && pnpm lint`
Expected: clean (only the 2 pre-existing warnings).

- [ ] **Step 3: Manual smoke test (golden path)**

Start `pnpm dev` from `frontend/`. On desktop:
- Click the header Burger → the navbar hides and the content expands; click again → it returns. Reload → navbar is expanded again (session-only). On mobile width the footer nav shows and there is no Burger.
- Open a category and a triage staging bucket → both player panels are narrower (~442px).
- Play a track in the category player → its row is highlighted (same subtle background as the triage current-row); the highlight follows playback to the next track.

If the UI cannot be exercised in a browser, say so explicitly rather than claiming success.

---

## Self-review notes

- **Spec coverage:** collapsible navbar + Burger + session state + i18n (Task 1); 442px both players (Task 2); category current-track highlight threaded page→tab→row, mirroring triage (Task 3). No backend/router change.
- **Testability decision:** Mantine `Burger` does not emit `aria-expanded` and `AppShell.Navbar` exposes no `data-collapsed` in jsdom (both verified by probe), so the Burger is given an explicit `aria-expanded={!navCollapsed}` — accessible and assertable. `AppShellInner` is exported so the test can mount it with a stubbed `UserMenu` + `useMediaQuery→true`.
- **Type/name consistency:** `isCurrent?: boolean` on `TrackRow`; `currentTrackId?: string | null` on `TracksTab`; `data-current` + `bg="var(--mantine-color-default-hover)"` match the triage `BucketTrackRow` exactly. Width `442` used in both player roots and the CSS module.
- **Placeholder scan:** none.

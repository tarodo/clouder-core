# Desktop Design Tweaks — Design Spec

**Date:** 2026-05-21
**Status:** Approved (design confirmed; spec for the record)
**Scope:** Three desktop UI refinements: (1) a collapsible main navbar toggled by a header button; (2) narrow both players (category + triage) by 15%; (3) highlight the currently-playing track in the category player, mirroring triage.

## Goal

Small desktop polish across the app shell and the two players. The main navbar can be hidden to give the content more room; both player panels get narrower; and the category player highlights the playing row the way the triage bucket player already does.

## Out of scope

- Mobile layout (uses a footer nav, no navbar) — unchanged.
- Persisting the collapsed state across reloads — session-only (in-memory), defaults to expanded on each load.
- An icon-only "rail" collapsed state — collapse fully hides the navbar (Mantine's native `collapsed` behavior).
- Any backend / API / schema change.

## Decisions (from brainstorming)

- **Collapse is session-only**, default expanded; resets on reload (no localStorage).
- **Players narrow to 442px** (520 × 0.85).
- **Highlight reuses the same token** as triage: `bg="var(--mantine-color-default-hover)"` + a `data-current` marker.

## 1. Collapsible main navbar (desktop)

In `frontend/src/routes/_layout.tsx` (`AppShellInner`):
- Add session state: `const [navCollapsed, { toggle: toggleNav }] = useDisclosure(false);` (from `@mantine/hooks`; `false` = expanded).
- Change the `navbar` prop to include the collapsed flag:
  ```tsx
  navbar={isDesktop ? { width: 240, breakpoint: 'md', collapsed: { desktop: navCollapsed, mobile: true } } : undefined}
  ```
  Mantine hides the navbar and expands `AppShell.Main` to full width when `collapsed.desktop` is true.
- Add a toggle in `AppShell.Header`, on the LEFT (before the wordmark), desktop-only:
  ```tsx
  {isDesktop && (
    <Burger opened={!navCollapsed} onClick={toggleNav} size="sm" aria-label={t('appshell.toggle_nav')} />
  )}
  ```
  `Burger` from `@mantine/core`; `opened={!navCollapsed}` so it shows the "X" when the navbar is open and the hamburger when collapsed. The header is restructured to a left group (Burger + wordmark) and the existing `UserMenu` on the right.
- Mobile (footer nav) is untouched — no Burger there.
- New i18n key `appshell.toggle_nav` ("Toggle navigation") in `frontend/src/i18n/en.json`.

## 2. Narrow both players to 442px

- `frontend/src/features/categories/components/CategoryPlayerPanel.module.css`: `.root { width: 520px }` → `width: 442px` (keep the other rules).
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx`: both `<Stack>` roots (empty-state + playing-state) currently `style={{ width: 520, flexShrink: 0, minWidth: 0 }}` → `width: 442`.

## 3. Highlight the playing track in the category player

Mirror the triage `BucketTrackRow` `data-current` + `bg` pattern.

- `frontend/src/features/categories/components/TrackRow.tsx`: add an optional `isCurrent?: boolean` prop. On the desktop `Table.Tr` and the mobile `Card`, set `data-current={isCurrent ? 'true' : undefined}` and `bg={isCurrent ? 'var(--mantine-color-default-hover)' : undefined}`. All other props/behavior unchanged.
- `frontend/src/features/categories/components/TracksTab.tsx`: add `currentTrackId?: string | null` to its props; pass `isCurrent={currentTrackId != null && track.id === currentTrackId}` to each `<TrackRow>` (both the mobile and desktop maps).
- `frontend/src/features/categories/routes/CategoryDetailPage.tsx`: pass `currentTrackId={playback.track.current?.id ?? null}` to `<TracksTab>` (the `playback` object is already in scope there).

## Edge cases

- **Collapse:** purely visual; no data effects. On reload the navbar is expanded again (session-only). Mobile never shows the Burger.
- **Highlight:** when nothing plays, `playback.track.current` is null → `currentTrackId` null → no row highlighted. When the playing track is not in the visible list, no row matches → nothing highlighted (correct).
- **Width:** 442px applies on desktop where the player renders in a split; the surrounding layout supplies the rest.

## Testing (TDD)

- **`_layout` (collapsible navbar):** render with `useMediaQuery` mocked to `true` (desktop); assert the `Burger` toggle renders and that clicking it flips its `aria-expanded` (Mantine `Burger` reflects `opened` via `aria-expanded`) — i.e. open→closed→open. (jsdom can't measure the navbar slide, so assert via the toggle's accessible state + that nav links still render.)
- **`TrackRow` (categories):** with `isCurrent` → the row carries `data-current="true"`; without `isCurrent` → the attribute is absent. Mirror the triage `BucketTrackRow` current-row test.
- **Width (442px):** verified by reading the CSS/inline style — no dedicated test (it's a style constant, consistent with how the prior 520px change was handled).
- Re-run the touched feature suites (`CategoryDetailPage`, `TracksTab`, `BucketPlayerPanel`) to confirm no regressions.

## Files touched

**Changed**
- `frontend/src/routes/_layout.tsx` — collapsible navbar + Burger toggle. (+test)
- `frontend/src/i18n/en.json` — `appshell.toggle_nav` key.
- `frontend/src/features/categories/components/CategoryPlayerPanel.module.css` — 520 → 442.
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — 520 → 442 (both branches).
- `frontend/src/features/categories/components/TrackRow.tsx` — `isCurrent` highlight. (+test)
- `frontend/src/features/categories/components/TracksTab.tsx` — thread `currentTrackId`.
- `frontend/src/features/categories/routes/CategoryDetailPage.tsx` — pass current track id.

No backend/API/schema/router-config change.

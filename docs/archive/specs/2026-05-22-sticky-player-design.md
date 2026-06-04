# Sticky (Floating) Player — Design Spec

**Date:** 2026-05-22
**Status:** Approved (design confirmed; spec for the record)
**Scope:** Make the desktop player panel (category + triage) stick below the header while a long track list (100–300 rows) scrolls, instead of scrolling away with the page.

## Goal

On desktop, the player sits in a left column of a `Flex` next to a long track list. When the page scrolls, the player currently scrolls out of view. Make it `position: sticky` so it stays pinned below the fixed header while the list scrolls. CSS-only; no JS.

## Out of scope

- Mobile: the player is a separate fullscreen `/player` route there — no sticky needed (sticky simply has no effect without a scrolling layout, so the change is harmless on mobile).
- Any change to player content, playback logic, or the track list.
- Backend / API / schema.

## Decisions (from brainstorming)

- **Offset:** stick at header height + a small gap, using Mantine's `--app-shell-header-offset` var (fallback `3.5rem` = 56px).
- **Tall player:** when the panel is taller than the viewport, it scrolls internally (`max-height` + `overflow-y: auto`) so the bottom isn't clipped.
- **Both players** (category + triage), desktop only. No automated test for the sticky behavior itself (CSS layout isn't meaningfully testable in jsdom); existing player tests must stay green.

## Background — current state

- The scroll container is the document: Mantine `AppShell` (default layout, no `layout` prop) renders a fixed header (`height: 56`) and the page/body scrolls; `AppShell.Main` carries the header offset. Confirmed no custom `overflow` on `html`/`body`/`#root`/`Main`.
- Desktop split: `CategoryDetailPage` / `BucketDetailPage` render a `<Flex gap="lg" align="flex-start" wrap="nowrap">` with the player panel + the list. `align="flex-start"` means the player is not stretched to the Flex's full height — required for sticky to have room to move.
- **`CategoryPlayerPanel.module.css` `.root`**: `width: 442px; flex-shrink: 0; padding: var(--mantine-spacing-md); border-right: 1px solid var(--mantine-color-default-border); height: 100%; overflow-y: auto;`. The `height: 100%` is inert (parent has auto height).
- **`BucketPlayerPanel.tsx`**: both `<Stack>` roots (empty-state + playing-state) use inline `style={{ width: 442, flexShrink: 0, minWidth: 0 }}`.

## 1. Category player — `CategoryPlayerPanel.module.css`

Update `.root`: drop the inert `height: 100%`, add sticky positioning + a viewport-bounded max height (keep `width`, `flex-shrink`, `padding`, `border-right`, `overflow-y`):

```css
.root {
  width: 442px;
  flex-shrink: 0;
  align-self: flex-start;
  position: sticky;
  top: calc(var(--app-shell-header-offset, 3.5rem) + var(--mantine-spacing-sm));
  max-height: calc(100vh - var(--app-shell-header-offset, 3.5rem) - var(--mantine-spacing-md));
  padding: var(--mantine-spacing-md);
  border-right: 1px solid var(--mantine-color-default-border);
  overflow-y: auto;
}
```

## 2. Triage player — `BucketPlayerPanel.tsx`

Both `<Stack>` roots currently `style={{ width: 442, flexShrink: 0, minWidth: 0 }}`. Change BOTH to add the sticky props:

```tsx
style={{
  width: 442,
  flexShrink: 0,
  minWidth: 0,
  alignSelf: 'flex-start',
  position: 'sticky',
  top: 'calc(var(--app-shell-header-offset, 3.5rem) + var(--mantine-spacing-sm))',
  maxHeight: 'calc(100vh - var(--app-shell-header-offset, 3.5rem) - var(--mantine-spacing-md))',
  overflowY: 'auto',
}}
```

(Applying to both branches keeps the empty-state and playing-state consistent. The triage panel is rendered only in the desktop split — `BucketDetailPage` gates the panel on `isDesktop && isStagingBucket`; on the mobile `/player` route the same component renders without a scrolling sibling, where sticky is a no-op.)

## Edge cases

- **Player taller than viewport:** `max-height` + `overflow-y: auto` → the panel scrolls internally; nothing is clipped.
- **Short list (no page scroll):** sticky has nothing to do; the player renders normally at the top.
- **Mobile `/player` route:** the panel renders full-width with no scrolling sibling; `position: sticky` is inert — no visual regression.
- **`--app-shell-header-offset` missing:** the `3.5rem` fallback (= the 56px header) keeps the offset correct.

## Testing

- No automated test for sticky positioning (CSS layout/scroll is not meaningfully assertable in jsdom).
- Verify by reading the CSS/inline style and by a manual desktop smoke test (scroll a 100+ track list; the player stays pinned below the header; a tall player scrolls internally).
- Re-run the existing `CategoryPlayerPanel` / `BucketPlayerPanel` / `CategoryDetailPage` / `BucketDetailPage` tests to confirm the style changes don't break rendering.

## Files touched

**Changed**
- `frontend/src/features/categories/components/CategoryPlayerPanel.module.css` — `.root` sticky.
- `frontend/src/features/triage/components/BucketPlayerPanel.tsx` — both `<Stack>` roots sticky.

No backend/API/schema/router change. No new tests.

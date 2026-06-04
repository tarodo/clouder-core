# Remove Focus Ring + Tag Checkmark — Design

**Date:** 2026-05-23
**Scope:** Frontend only. No backend/DB.

## Goal

Two small UI cleanups the user requested:

1. **Redundant checkmark:** in the category player's tag cloud, a selected (assigned) tag shows a Mantine `Chip` checkmark icon. The soft-tint color already conveys selection, so the checkmark adds nothing — remove it.
2. **Distracting focus ring:** clicking play / a tag / a category leaves a black focus outline on the element across all players. The app is mouse + global-hotkey driven (no keyboard Tab navigation), so the outline is meaningless and distracting. Remove the focus ring everywhere, including text inputs (the user confirmed text fields too — they still show a border-color change on focus, so they're not lost).

## Background

- The black ring is **Mantine's focus ring**. The theme sets `primaryColor: "neutral"` with `primaryShade: { light: 9 }` (`theme.ts:68-69`) — i.e. the primary color is near-black, and Mantine's focus ring uses the primary color. `focusRing` is not set, so it defaults to `'auto'`. Setting `focusRing: 'never'` removes the ring from all Mantine components.
- There is **no custom `:focus` outline CSS** and the `theme.other.borderFocus` token is defined but unused — nothing else paints a focus outline.
- The checkmark is the Mantine `Chip` checked-state icon, rendered in the `iconWrapper` slot. `PlayerPanelTagCloud.tsx` currently styles `iconWrapper` with a color; hiding that slot removes the checkmark.

## Design

### #1 — Hide the tag checkmark (category player)

In `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`, change the Chip's `styles.iconWrapper` from a color override to `{ display: 'none' }`. The checkmark disappears; the assigned/unassigned distinction remains via the soft tint (assigned) vs neutral (unassigned) label styling, which is unchanged. Toggle behavior (`onChange` → `onAdd`/`onRemove`) is unchanged.

### #2 — Remove the focus ring app-wide

In `frontend/src/theme.ts`, add `focusRing: "never"` to the `createTheme({...})` object (near `primaryColor`/`primaryShade`). This removes Mantine's focus ring from every Mantine component (the play `ActionIcon`/`Button`, the tag `Chip`s, category rows/links, text inputs, etc.) on both mouse and keyboard. Text inputs keep their focus border-color change (separate from the ring), so they remain distinguishable while typing.

**Fallback (only if needed):** during implementation, reproduce on the category, triage, and curate players. If any *non-Mantine native* element (a raw `<button>`/`<input>`/`<a>`/category row) still shows a UA outline after `focusRing: 'never'`, add a minimal global reset `:focus { outline: none; }` to `frontend/src/tokens.css`. If `focusRing: 'never'` alone clears it, do not add the global reset (YAGNI).

## Testing / verification

- **#1:** unit test in `PlayerPanelTagCloud.test.tsx` — assert the assigned chip's `.mantine-Chip-iconWrapper` is hidden (`display: none`) or the check icon is not visible.
- **#2:** `focusRing: 'never'` is a theme/visual change not reliably unit-testable; verify manually by reproducing the click-then-no-outline behavior on all three players during implementation. A light assertion that `clouderTheme.focusRing === 'never'` may be added if a theme test exists.
- Gate: `pnpm typecheck && pnpm lint && pnpm test` all green.

## Out of scope

- Backend/DB.
- Tag checkmarks on triage/curate players (the request named the category player). If those panels render the same chip checkmark, note as a follow-up — do not change here unless trivially identical.
- Keeping any focus ring for keyboard navigation (the user chose to remove it everywhere).

## Acceptance criteria

1. In the category player, selected tags show no checkmark; selection is still obvious from the soft tint.
2. Clicking play / a tag / a category on any player leaves no black focus outline; the outline does not appear on mouse or keyboard interaction anywhere in the app.
3. Text inputs still visibly indicate focus via their border color (not a ring).
4. `pnpm typecheck && pnpm lint && pnpm test` all green.

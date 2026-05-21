# Distribution Buttons Style — Design Spec

**Date:** 2026-05-21
**Status:** Draft (awaiting user review)
**Scope:** Replace the `Chip`-style distribution controls (shipped in the player-polish change) with `Button`-style controls in two places: the triage bucket player's distribution buttons, and the category player's playlist assignment buttons.

## Goal

The just-shipped polish unified distribution controls to Mantine `Chip`s. The preferred look is actual `Button`s (the style the curate destination grid uses). Convert:
- **Triage** `BucketDistributeButtons`: `Chip` → `Button`, laid out 2-per-row on mobile / 3-per-row on desktop, with the DISCARD button in light red. (This reverts to the pre-Chip implementation.)
- **Category player** `PlayerPanelPlaylistCloud`: `Chip` → `Button`, laid out 2-per-row everywhere, preserving the membership toggle (filled when the track is in the playlist) and the numeric hotkey hint.

The category tag cloud (`PlayerPanelTagCloud`) stays as colored `Chip`s — only the playlist cloud changes.

## Out of scope

- Reusing curate's `DestinationButton` component. It lives in `features/curate`, which imports from `features/triage` and `features/categories`; importing it back would create a dependency cycle. It also carries curate-specific concerns (single-shot pulse, inactive-bucket titles, its own hotkey layout). The "button style" is achieved with plain Mantine `Button`s instead.
- The category tag cloud (`PlayerPanelTagCloud`) — unchanged (colored chips).
- Player layout, 520px width, staging-only gate, LabelTile placement — all from the prior polish, unchanged.
- Any backend / API / schema change.

## Background — current state

- **`BucketDistributeButtons`** (`frontend/src/features/triage/components/BucketDistributeButtons.tsx`) currently renders a `Group` of `Chip`s (`checked={false}`, `onChange → onDistribute`, DISCARD `color="red"`). Before the polish it rendered a `SimpleGrid cols={{ base: 2, md: 3 }}` of `Button`s (DISCARD `variant="light" color="red"`).
- **`PlayerPanelPlaylistCloud`** (`frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx`) renders a `Group wrap` of `Chip`s: `checked={selected}`, `variant={selected ? 'filled' : 'outline'}`, with a hotkey `Badge` (labels `1`-`9`,`0`) + playlist name, `onChange` toggles add/remove. Shows "No active playlists" when empty.
- Hotkeys: `useCategoryPlayerHotkeys` maps number keys to `onTogglePlaylistByIndex` independently of the rendering, so the hotkey behavior is unaffected by the chip→button swap; the visible hotkey hint should be kept.
- `bucketLabel(b, t)` gives the triage button label (category name for STAGING, `"DISCARD"` for the discard bucket).

## 1. Triage `BucketDistributeButtons` — Chip → Button

Rewrite the control list back to `Button`s in a responsive grid:
- `SimpleGrid cols={{ base: 2, md: 3 }} spacing="xs" verticalSpacing="xs"` (2 per row on mobile, 3 per row on desktop).
- Each `Button`: `size="sm"`, `variant={b.bucket_type === 'DISCARD' ? 'light' : 'default'}`, `color={b.bucket_type === 'DISCARD' ? 'red' : undefined}` (DISCARD = light red), `onClick={() => onDistribute(b.id)}`, `aria-label={bucketLabel(b, t)}`, `styles={{ label: { whiteSpace: 'normal' } }}`, label `{bucketLabel(b, t)}`.
- Keep the section heading (`triage.bucket_player.distribute.heading`) and the `destinations.length === 0 → null` behavior.

This is the pre-Chip version restored.

## 2. Category `PlayerPanelPlaylistCloud` — Chip → Button (2 per row)

Rewrite the playlist list as a 2-column grid of toggle buttons:
- `SimpleGrid cols={2} spacing="xs" verticalSpacing="xs"` (2 per row on all breakpoints).
- Each `Button`: `fullWidth`, `size="sm"`, `variant={selected ? 'filled' : 'default'}` (filled = the track is in that playlist), `onClick={() => (selected ? onRemove(pl.id) : onAdd(pl.id))}`, `leftSection={hotkey ? <Badge variant="default" size="xs" radius="sm">{hotkey}</Badge> : undefined}`, label `{pl.name}`. Keep `styles={{ label: { whiteSpace: 'normal' } }}` so long names wrap.
- `selected = inPlaylist.has(pl.id)`; `hotkey = idx < HOTKEY_LABELS.length ? HOTKEY_LABELS[idx] : null` (unchanged logic).
- Keep the "No active playlists" empty state (`playlists.length === 0`).

`PlayerPanelTagCloud` is untouched.

## Data flow & edge cases

- **Triage:** tap a button → `onDistribute(bucketId)` (one-shot move + advance, unchanged in `useBucketDistribute`). DISCARD rendered light red.
- **Category playlist:** tap a button → toggles playlist membership via `onAdd`/`onRemove` (unchanged handlers in `CategoryPlayerPanel`); `filled` reflects current membership. Numeric hotkeys keep working via `useCategoryPlayerHotkeys`.
- **Empty:** triage with no destinations → `null`; categories with no active playlists → "No active playlists" text.
- **Long labels:** `whiteSpace: 'normal'` lets button labels wrap rather than overflow.

## Testing (TDD)

- **`BucketDistributeButtons`:** renders a `Button` per destination (assert by `role: 'button'` + name); DISCARD button present; `onDistribute(id)` fires on click; empty → renders nothing. (Update the current text/chip-oriented test back to button-role queries.)
- **`PlayerPanelPlaylistCloud`:** renders a `Button` per playlist; clicking an unselected playlist calls `onAdd`, clicking a selected one calls `onRemove`; the selected playlist's button uses the `filled` variant (assert via `data-variant="filled"` on the Mantine button or an equivalent attribute); "No active playlists" when empty. (Rewrite the existing chip-oriented test.)
- Re-run the affected player tests: `BucketPlayerPanel.test.tsx` (its distribute queries are text-based and work for buttons), `CategoryPlayerPanel.test.tsx`, and the categories player hotkey integration test (`integration.player.test.tsx`) — the hotkey path is unchanged and must stay green.

## Files touched

**Changed**
- `frontend/src/features/triage/components/BucketDistributeButtons.tsx` — Chip → Button grid. (+ its test)
- `frontend/src/features/categories/components/PlayerPanelPlaylistCloud.tsx` — Chip → 2-per-row toggle buttons. (+ its test)

No backend/API/schema/router change. The triage panel test may need its distribute queries reaffirmed (text queries already match buttons), and the categories hotkey integration test must be verified still green.

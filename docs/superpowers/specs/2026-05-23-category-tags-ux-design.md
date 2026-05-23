# Category Tags UX — Design

**Date:** 2026-05-23
**Scope:** Frontend only (`frontend/src/features/categories` + `frontend/src/features/tags`). No backend, DB, API, or tag-palette changes.

## Goal

Two fixes for the tags on the category-detail page (`/categories/:styleId/:id`):

1. **Hotkeys bug:** clicking a label tag kills the playback/playlist keyboard shortcuts (a, s, d, f, g, j, k, u, 0–9) until the user clicks empty space to blur. Fix so shortcuts keep working after a tag click.
2. **Tag colors too loud:** tags use a full saturated fill that pulls attention off the track. Switch to a soft tinted "label" look (light tint background + colored text + subtle border), computed client-side from each tag's stored color.

## Background / root cause

### Hotkeys
The shortcut handler registers a global `window` keydown listener in `frontend/src/features/categories/hooks/useCategoryPlayerHotkeys.ts`. It early-returns when the event target is "editable":

```ts
// useCategoryPlayerHotkeys.ts:22-28 (current)
function isEditable(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (target.isContentEditable) return true;
  return false;
}
```

The player-panel tag cloud (`PlayerPanelTagCloud.tsx`) renders each tag as a Mantine `<Chip>`. A Mantine `Chip` is a visually-hidden `<input type="checkbox">` + label. Clicking a tag moves focus to that checkbox `<input>`. Subsequent keydown events then have `event.target.tagName === 'INPUT'`, so `isEditable` returns `true` and **every shortcut is suppressed** until the input is blurred (clicking empty space). The guard conflates "focus is on an `<input>`" with "the user is typing" — but a checkbox is not text entry.

### Colors
Tag colors are API-driven: each tag has a nullable `color` hex field, drawn from a fixed saturated palette (`frontend/src/features/tags/lib/tagPalette.ts`, `TAG_PALETTE` — tailwind-500 values like `#ef4444`). They are applied as a full fill:
- `TagPill.tsx` (track-row tags) — inline `backgroundColor: color` + WCAG-contrast text via `pickPillTextColor`.
- `PlayerPanelTagCloud.tsx` — Mantine `Chip` with `variant={selected ? 'filled' : 'outline'}` and `color={tag.color ?? 'gray'}` (filled = solid saturated fill).

Colors are stored per-tag server-side, so changing the palette would only affect new assignments. The fix must soften **all existing tags** without touching stored data → compute the soft look client-side from the stored hex.

## Design

### Part 1 — Refine the hotkey guard (approach A)

In `useCategoryPlayerHotkeys.ts`, change `isEditable` to suppress shortcuts only for genuine **text-entry** contexts:

- `<textarea>`, `<select>`, and `contentEditable` → suppress (unchanged).
- `<input>` → suppress **only** for text-like types. Treat these `<input type>` values as **non-editable** (do NOT suppress): `checkbox`, `radio`, `button`, `submit`, `reset`, `file`, `range`, `color`, `image`. Any other input type (incl. empty/unset, which defaults to `text`: `text`, `search`, `email`, `url`, `tel`, `password`, `number`, and the date/time family) → suppress.
- Implementation: read `(target as HTMLInputElement).type` (lowercased) and check membership in a `NON_EDITABLE_INPUT_TYPES` set; if in the set, return `false`.

Effect: a focused tag Chip's checkbox no longer suppresses the shortcuts → keys work immediately after a tag click. The fix is general (covers any focusable checkbox/radio/widget input), not specific to this Chip.

Accepted trade-off: if a keyboard user Tab-focuses a Chip and presses Space, the global handler's `Space → play/pause` (with `preventDefault`) wins over the native checkbox toggle. Negligible in practice — tags are mouse-clicked in this app.

### Part 2 — Soft tinted tags (variant C)

**New helper** in `frontend/src/features/tags/lib/tagPalette.ts`:

```
softTagColors(hex: string | null | undefined): { bg: string; fg: string; border: string }
```

- Parse the hex to RGB.
- `bg` = `rgba(r, g, b, 0.13)` (light tint).
- `border` = `rgba(r, g, b, 0.30)` (subtle hairline).
- `fg` = a darkened, readable version of the same hue. Convert to HSL, clamp lightness to ≈ 38% (and keep reasonable saturation), convert back to hex. This keeps the tag's color identity while staying legible on the light tint, including for very dark stored colors (e.g. slate `#0f172a`) and very light ones.
- `null`/invalid color → neutral grey tint: `bg` ≈ `rgba(100,116,139,0.12)`, `fg` ≈ `#475569`, `border` ≈ `rgba(100,116,139,0.30)`.

**Apply the soft look (all from the stored `tag.color`; palette and DB untouched):**

- `frontend/src/features/tags/components/TagPill.tsx` — replace the full-fill style (`backgroundColor: color` + `pickPillTextColor`) with `softTagColors`: `background: bg`, `color: fg`, `border: 1px solid border`. `pickPillTextColor` becomes unused for the pill fill — remove it if it has no remaining callers, otherwise leave it.
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — keep the Mantine `Chip` (toggle = tag assigned/unassigned) but render the soft look via the `styles` prop:
  - **assigned (checked):** soft tint — `background: bg`, label `color: fg`, `border: 1px solid border`.
  - **unassigned (unchecked):** neutral — no fill, dimmed grey border + grey text — so the assigned/unassigned distinction stays obvious.
  - This replaces reliance on Mantine's `filled`/`outline` variant + `color` prop for the visual.

Both surfaces share `softTagColors`, so track-row pills and player-panel chips look consistent.

## Testing

- **`softTagColors`** (unit, `tagPalette` test): a saturated hex → expected `bg`/`border` rgba and a darker `fg`; `null` → neutral grey set; a near-black hex (`#0f172a`) → still produces a legible `fg` and a light `bg`.
- **`isEditable`** (unit): a focused `<input type="checkbox">` target → `false` (not suppressed); `<input type="text">` / unset → `true`; `<textarea>` / `contentEditable` → `true`. (Export `isEditable` from the hook module for testability if not already, or test via the hook's behavior with synthesized keydown events.)
- **`TagPill`** (component): renders with the soft background/fg/border derived from a given color.
- **`PlayerPanelTagCloud`** (component): assigned vs unassigned chips render visually distinct (assigned = colored soft tint, unassigned = neutral).
- Regression: existing category-detail / hotkey / tag tests stay green; `pnpm typecheck && pnpm lint && pnpm test`.

## Out of scope

- Backend, DB, API, the stored `TAG_PALETTE` values, and tag colors outside the category-detail page.
- Replacing the Mantine `Chip` with a custom toggle (kept as a fallback only if the `styles` override proves impractical during implementation — not the planned path).

## Acceptance criteria

1. On `/categories/:styleId/:id`, clicking a label tag and then pressing a/s/d/f/g/j/k/u/0–9 triggers the shortcut **without** first clicking empty space.
2. Tags on track rows and in the player panel render as soft tinted labels (light tint bg, colored text, subtle border) derived from each tag's stored color; existing tags are softened with no data migration.
3. In the player panel, assigned vs unassigned tags remain clearly distinguishable.
4. `pnpm typecheck && pnpm lint && pnpm test` all green.

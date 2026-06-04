# Tag Pill Sizing — Design

**Date:** 2026-05-23
**Scope:** Frontend only. No backend/DB.

## Goal

Two tag-sizing cleanups the user requested:

1. **Category player — stable chip size on select.** In the category player tag cloud, inactive tags are all one size, but selecting a tag visibly changes its size (it shrinks). Only the color should change on select; the size must stay constant.
2. **Track table tags column — uniform short pills.** In the track table tags column, pills are sized purely to their text, so a 1-character and a 2-character tag render at different widths and look ragged. A 1-char and a 2-char tag should be the same width; only tags longer than 2 chars should grow.

## Background / root cause

### #1 — why the chip changes size

Mantine `Chip`'s label (`.mantine-Chip-label`, hashed `.m_be049a53`) sets its horizontal padding from a CSS variable, and **switches that variable when checked**:

```css
.m_be049a53            { padding-inline: var(--chip-padding-sm); }          /* = 1.25rem  = 20px */
.m_be049a53:where([data-checked]) { padding-inline: var(--chip-checked-padding-sm); } /* = 0.625rem = 10px */
```

Normally the ~10px gained on the left when checked is filled by the check-icon wrapper. We already hide that wrapper (`PlayerPanelTagCloud.tsx` → `styles.iconWrapper: { display: 'none' }`, shipped earlier). So a checked chip just becomes ~20px narrower than the same chip unchecked → the visible "size jump." The label's bg/color/border are already overridden via `styles.label`; only `paddingInline` is left to Mantine, so the checked-state padding still applies.

The `:where([data-checked])` selector has **0 specificity** (`:where()` contributes nothing), so an inline style on the label (which is what the `styles.label` prop produces) wins without `!important`.

### #2 — why short pills differ in width

`TrackTagsCell.tsx` renders each tag as `TagPill`. `TagPill` is `display: inline-flex` with `px={8}` and **no `min-width`**, so its width is exactly its text width + 16px. "A", "AB", "ACID" therefore differ in width. `TagPill` is shared — also used by `TrackTagsPopover` and `TagsManagerModal`.

To make 1-char and 2-char tags *identical regardless of which letters* (an "I" vs a "W"), a min-width in a proportional (sans) font is not enough: a wide 2-char pair can still exceed it. A monospace font makes every glyph one `ch` wide, so `min-width: 2ch` guarantees every ≤2-char tag is exactly the same width. The design system already ships a mono family (`--font-mono: "Geist Mono", …` in `tokens.css`).

## Design

### #1 — pin the chip label padding (category player)

In `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`, add `paddingInline: 'var(--chip-padding-sm)'` to the `styles.label` object in **both** the `selected` and unselected branches. Keep everything else (bg/color/border, the hidden `iconWrapper`) unchanged. This holds the inline padding constant at the unchecked value (20px/side) for both states, so the checked-state Mantine rule cannot shrink the chip. Only color/bg/border change on select; width is constant.

(No `!important` needed — inline style beats the `:where([data-checked])` 0-specificity rule.)

### #2 — uniform short pills (global TagPill)

In `frontend/src/features/tags/components/TagPill.tsx`, add to the pill `Box`'s inline `style`:

- `fontFamily: 'var(--font-mono)'`
- `minWidth: 'calc(2ch + 18px)'` — 2 chars of mono text plus the existing `px={8}` (8px × 2 = 16px) plus the `1px` border (× 2 = 2px). The global `*{ box-sizing: border-box }` (tokens.css) makes `min-width` include both padding and border, so both must be added explicitly to reserve 2ch of *content*. (The first implementation used `+ 16px` and the 1px border made 2-char pills 2px wider than 1-char ones — the browser test caught it; corrected to `+ 18px`.)
- `justifyContent: 'center'` — center the text within the min-width box (the `×` remove button, when present, stays right-aligned within the centered flex content; acceptable — remove is only used in the popover/manager, not the table).

Result: any tag ≤2 chars renders at the same `calc(2ch + 16px)` width, centered; tags of 3+ chars grow naturally. `px={8}`, radius, colors, the optional `onRemove` `×` are unchanged.

**Scope:** this changes `TagPill` itself, so it applies to **all** its usages — the track table column (`TrackTagsCell`), the tag popover (`TrackTagsPopover`), and the tags manager (`TagsManagerModal`). The user approved the global treatment for consistency (short codes, mono, uniform — a coherent "pro tool" look) over a table-only prop.

## Testing / verification

Per the project's verify-in-a-real-browser rule (jsdom does not apply stylesheets or compute layout), the load-bearing assertions go through the **browser harness** (`@vitest/browser` + Playwright, `*.browser.test.tsx`, run locally via `pnpm test:browser` — excluded from the default `pnpm test` and CI). jsdom-level tests stay as cheap structural guards.

- **#1 (browser):** render `PlayerPanelTagCloud` with one tag, capture the chip label's rendered width unchecked vs checked (toggle `assignedTagIds`), assert the two widths are equal (or assert `getComputedStyle(label).paddingInline` is identical in both states).
- **#2 (browser):** render `TagPill` for a 1-char and a 2-char name, assert `getBoundingClientRect().width` is equal; render a 5-char name and assert its width is greater. Assert `getComputedStyle(pill).fontFamily` includes the mono family.
- **jsdom guards (default suite):** `TagPill` inline style carries `min-width: calc(2ch + 16px)` / `justify-content: center` / mono font-family; `PlayerPanelTagCloud` selected + unselected chip labels both carry the same `padding-inline`.
- Gate: `pnpm typecheck && pnpm lint && pnpm test` all green; `pnpm test:browser` green locally.

## Out of scope

- Backend/DB, tag data model, the tag color palette.
- Making the category player chips uniform-width across tags (the request was only that selecting a tag not change *its own* size). Not changing chip width-per-tag.
- Truncating long tags — the user wants long tags to grow, not truncate.
- Dark-theme review of mono pills (no dark-mode toggle currently ships).

## Acceptance criteria

1. Selecting/deselecting a tag in the category player changes only its color/fill — its width does not change.
2. In the track table tags column, every 1-char and 2-char tag is the same width; tags of 3+ chars are wider.
3. The same uniform/mono pill treatment applies wherever `TagPill` is used (table, popover, manager).
4. `pnpm typecheck && pnpm lint && pnpm test` all green; the browser harness (`pnpm test:browser`) green locally.

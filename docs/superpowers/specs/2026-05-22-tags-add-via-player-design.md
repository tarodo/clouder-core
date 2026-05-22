# Move Tag-Adding to the Player — Design Spec

**Date:** 2026-05-22
**Status:** Approved (design confirmed; spec for the record)
**Scope:** On the category page, make the table's Tags column read-only (remove the inline "+" add affordance) and add a "+" to the player's Tags block that opens the full tag picker/creator. Tag editing moves from the per-row table cell to the player.

## Goal

The per-row tag editing in the table (a "+" + a popover anchored in each row's Tags cell) is awkward. Move tag adding to the player, where the user is already focused on the playing track. The table Tags column becomes a read-only display; the player's Tags block gains a "+" that opens the existing pick/create popover for the current track.

## Out of scope

- Changing the popover itself (`TrackTagsPopover`) — reused as-is.
- The player's tag chips (toggle existing tags for the current track) — kept; the "+" is additive.
- Any backend / API / schema change.

## Decisions (from brainstorming)

- **Table Tags column = read-only:** pills display only, not clickable, no "+", no popover. All tag editing happens in the player.
- **Player "+" = full popover:** reuse `TrackTagsPopover` (search/pick existing + create new with color, then assign), anchored to a "+" placed after the tag chips.
- **Empty state in the player:** when the current track has no tags, still show the "+" so the user can create/assign the first one.

## Background — current state

- **`TrackTagsCell`** (`frontend/src/features/tags/components/TrackTagsCell.tsx`) renders the row's tag pills (each wrapped in a button that opens the popover) plus a "+" `ActionIcon`; both open `TrackTagsPopover`. Props: `{ categoryId, trackId, tags }`. Used by `TrackRow` (categories) only.
- **`TrackTagsPopover`** (`.../TrackTagsPopover.tsx`) is the full tag editor: search existing tags (checkbox assign/unassign), and create a new tag (name + color) then assign. Props: `{ opened, onClose, target, categoryId, trackId, currentTagIds }`. It owns its add/remove/create mutations.
- **`PlayerPanelTagCloud`** (`frontend/src/features/categories/components/PlayerPanelTagCloud.tsx`) renders all tags as toggle `Chip`s (filled = assigned to the current track), `onAdd`/`onRemove` toggle assignment. Props: `{ trackId, assignedTagIds, onAdd, onRemove }`. Shows "No tags yet" when there are no tags. No create affordance.
- **`CategoryPlayerPanel`** renders a "Tags" section: a heading + `<PlayerPanelTagCloud trackId assignedTagIds onAdd onRemove />`. It has `categoryId` in scope (prop) and the current track id.
- i18n: `tags.cell.add_aria` ("Add tag" aria) already exists.

## 1. Table Tags column → read-only

Simplify `TrackTagsCell` to display-only:
- Props become `{ tags: readonly TrackTagsCellTag[] }` (drop `categoryId`/`trackId`).
- Render `<Group gap={4} wrap="wrap">{tags.map((tag) => <TagPill key={tag.id} name={tag.name} color={tag.color} />)}</Group>` — no buttons, no "+", no popover, no `opened` state.
- Remove now-unused imports (`useState`, `ActionIcon`, `UnstyledButton`, `IconPlus`, `useTranslation`, `TrackTagsPopover`).
- Update the call site in `frontend/src/features/categories/components/TrackRow.tsx` to `<TrackTagsCell tags={track.tags} />` (drop `categoryId`/`trackId` args). `TrackTagsCell` is used only by `TrackRow` — verify no other importer before changing the prop shape.

`TrackTagsPopover` is NOT deleted — it moves to the player.

## 2. Player Tags block → add "+" with the full popover

In `PlayerPanelTagCloud`:
- Add a `categoryId: string` prop (needed by `TrackTagsPopover`).
- Add local `const [opened, setOpened] = useState(false)`.
- After the tag chips (inside the same `Group`, as the last element — "after all tags"), render a "+" `ActionIcon` (`IconPlus`, `aria-label={t('tags.cell.add_aria')}`) as the `target` of a `TrackTagsPopover` with `categoryId`, `trackId`, `currentTagIds={assignedTagIds}`.
- Empty state: when there are no tags, still render the "+" (so the first tag can be created). Replace the bare "No tags yet" early return with a layout that shows the hint text alongside (or just) the "+".
- The existing chips + `onAdd`/`onRemove` toggle behavior is unchanged; the popover handles its own add/remove/create via its internal mutations.

In `CategoryPlayerPanel`, pass `categoryId={categoryId}` to `<PlayerPanelTagCloud>`.

## Data flow & edge cases

- **Add via player "+":** opens `TrackTagsPopover` → pick an existing tag (assign) or create a new one (name+color) and assign → its mutations optimistically update the category-tracks cache and `useTags()` → the new chip appears in the cloud; the table row's pills update via the same cache.
- **Table:** purely displays `track.tags`; no interaction.
- **No current track:** `CategoryPlayerPanel` already early-returns its empty state before the Tags section, so the player Tags block (and "+") only render when a track is playing.
- **No tags at all:** the player shows the "+" (create the first tag); the table shows an empty Tags cell.

## Testing (TDD)

- **`TrackTagsCell`:** renders a `TagPill` per tag; there is NO add button (`queryByRole('button', { name: /add tag/i })` is null) and no popover. (Update/replace the existing cell test, which asserted the "+"/popover.)
- **`PlayerPanelTagCloud`:** renders the "+" add button (by `tags.cell.add_aria`); clicking it opens the `TrackTagsPopover` (e.g. the search input appears); existing chip toggle (`onAdd`/`onRemove`) still fires; the empty-tags state still shows the "+". (Extend the existing test; it will need a `categoryId` prop and likely a `QueryClientProvider` since the popover uses `useTags`/mutations — wrap accordingly or mock as the existing player tests do.)
- Update the `TrackRow` call site so its tests still pass (the cell no longer needs `categoryId`/`trackId`).
- Re-run `CategoryPlayerPanel` tests (the Tags section gains a `categoryId` prop pass-through).

## Files touched

**Changed**
- `frontend/src/features/tags/components/TrackTagsCell.tsx` — read-only display. (+test)
- `frontend/src/features/categories/components/TrackRow.tsx` — update `TrackTagsCell` usage.
- `frontend/src/features/categories/components/PlayerPanelTagCloud.tsx` — add "+" + popover + `categoryId`. (+test)
- `frontend/src/features/categories/components/CategoryPlayerPanel.tsx` — pass `categoryId` to the tag cloud.

No backend/API/schema/router change. `TrackTagsPopover` reused unchanged.

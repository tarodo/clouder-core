# Track Tags — Frontend Design

**Date:** 2026-05-11
**Scope:** Frontend (`frontend/`) for the user-tag vocabulary and per-track tag assignment introduced by the backend spec `2026-05-11-track-tags-design.md`. Includes one backend change — making `user_tags.color` nullable — that is a precondition for the UI.
**Status:** Design — pending implementation plan

## Problem

The backend exposes user-tag CRUD and per-track tag assignment, plus tag-based filtering on `GET /categories/{id}/tracks`. The user needs a way to:

1. Manage a personal tag vocabulary (create, rename, delete; pick a colour or leave the tag colourless).
2. Attach and detach tags on individual tracks inside the category detail page.
3. Filter the category's track list by a tag set with AND/OR semantics.

This spec covers all three. Curate, triage, and any other future surface that wants tag-aware UI will reuse the components introduced here.

## Goals

- Tag-vocabulary modal reachable from the category detail page.
- Inline tag chips on every track row in the category track table; click opens a popover that adds/removes tags atomically.
- New tag can be created on-the-fly from the popover (search → no match → "Create X" → choose colour or skip).
- Tag-set filter above the track table (multiselect + ALL/ANY toggle), URL-synced.
- `color` is optional everywhere — a tag without a colour renders as a neutral outlined pill.

## Non-goals

- Bulk track-tag operations (select N tracks → apply / clear).
- Tag UI in curate, triage, or any non-categories surface.
- Tag analytics (per-tag counts, usage).
- Drag-and-drop reordering of the vocabulary.
- Server-side search in the vocabulary modal (local prefix filter is enough until the typical vocabulary exceeds ~50 entries).
- Per-style or per-category tag scoping — the vocabulary is global per user.

## Precondition: backend nullable `color`

The current backend (committed in this branch) treats `color` as a `NOT NULL text` with regex validation. The frontend needs colour to be optional. The implementation plan therefore opens with a small BE change before the frontend work begins.

**Changes required (one commit, before any FE code):**

- New Alembic revision: `ALTER TABLE user_tags ALTER COLUMN color DROP NOT NULL`.
- `db_models.py`: `color: Mapped[str | None] = mapped_column(Text, nullable=True)`.
- `tags_repository.py`: `create_tag` / `rename_tag` accept `color: str | None`. Insert / update pass `None` when caller omits it.
- `curation_handler.py`: in `_handle_create_tag` / `_handle_rename_tag`, treat missing `color` as `None`. Validate the regex only when `color is not None`. `name` remains required on create, optional on patch (same as today).
- `scripts/generate_openapi.py`: `color` schema becomes `{"type": ["string", "null"], "pattern": "^#[0-9A-Fa-f]{6}$"}` on both request bodies and the `TagRow` response. The response field stays present (`null` when unset). Regenerate `docs/openapi.yaml`.
- New unit tests in `tests/unit/test_tags_repository.py` and `tests/unit/test_curation_handler_tags.py` for the `color=None` path (create, patch, list).

After this commit lands, `pnpm api:types` regenerates `frontend/src/api/schema.d.ts` with `color: string | null`, and the rest of the plan proceeds.

## Architecture

### File structure

```
frontend/src/features/tags/
├── components/
│   ├── TagPill.tsx              # readonly chip with colour OR neutral outline
│   ├── TrackTagsCell.tsx        # pills + "+" trigger; owned popover state
│   ├── TrackTagsPopover.tsx     # search + checkbox list + inline create form
│   ├── TagsManagerModal.tsx     # vocabulary CRUD
│   ├── TagFormFields.tsx        # shared name + colour fields (used by create AND rename)
│   ├── ColorSwatchPicker.tsx    # 12 swatches + "no colour" option
│   └── TagsFilterBar.tsx        # multiselect + ALL/ANY toggle + "Manage tags" button
├── hooks/
│   ├── useTags.ts               # GET /tags (single unfiltered fetch)
│   ├── useCreateTag.ts
│   ├── useRenameTag.ts
│   ├── useDeleteTag.ts
│   ├── useAddTrackTag.ts        # POST /tracks/{id}/tags (optimistic)
│   └── useRemoveTrackTag.ts     # DELETE /tracks/{id}/tags/{tag_id} (optimistic)
├── lib/
│   ├── tagPalette.ts            # 12 hex constants + CSS-variable aliases
│   ├── tagSchemas.ts            # Zod create/rename schemas (color optional)
│   ├── normalizeTagName.ts      # mirrors BE `_normalize_tag_name`
│   └── tagsUrlState.ts          # URL <-> {tag_ids, match} (de)serialiser
└── index.ts                     # re-export TrackTagsCell, TagsFilterBar, TagsManagerModal
```

The `features/tags/` directory owns every tag-related component. `features/categories/` only imports the three high-level re-exports and modifies its existing query hook + tracks tab.

### Modified files in `features/categories/`

- `hooks/useCategoryTracks.ts` — extend query key and URL params with `tagIds: readonly string[]` and `tagMatch: 'all' | 'any'`. Sort `tagIds` lexicographically before joining so the same filter always yields the same cache key.
- `components/TracksTab.tsx` — render `<TagsFilterBar>` above the table (next to the search input). Pull selected tag ids + match from URL state via `tagsUrlState`. Pass them to `useCategoryTracks`. Render `<TagsManagerModal>` lazily when the manager button is clicked.
- `components/TrackRow.tsx` — add a second column (desktop, after the title cell) and a section (mobile, under the artist line) that hosts `<TrackTagsCell>`. Existing `actions` slot is unchanged.

### Cross-feature contract

`features/tags/index.ts` re-exports exactly:

- `TrackTagsCell` (props: `{ trackId: string; categoryId: string; tags: TrackTag[] }`)
- `TagsFilterBar` (props: `{ selectedIds: string[]; match: 'all' | 'any'; onChange: (next: { selectedIds: string[]; match: 'all' | 'any' }) => void }`)
- `TagsManagerModal` (props: `{ opened: boolean; onClose: () => void }`)

These are the only public symbols. Hooks (`useTags`, etc.) are also re-exported but only used inside the tags feature in v1.

## UX

### TracksTab — filter row

```
┌─────────────────────────────────────────────────────────────────────┐
│ [🔍 search…  ]  [🏷 Vocal × Dark × ⌄]  ◉ ALL ○ ANY  [⚙ Manage tags] │
└─────────────────────────────────────────────────────────────────────┘
```

- The search input stays where it is (left). Tag filter sits next to it.
- The `MultiSelect` shows selected tags as coloured pills; the dropdown lists every tag with its colour swatch (or neutral marker when colour is null) and a checkbox.
- `ALL` / `ANY` `SegmentedControl` is only visible when at least one tag is selected. Default = `all`.
- "Manage tags" button is `Button variant="default"` on the right. Click opens `TagsManagerModal`.
- Both the selected ids and the match mode live in `?tags=tg1,tg2&match=any` URL search params via `useSearchParams`. Refreshing the page or sharing the link preserves the filter.

### TrackRow — tag cell

**Desktop** — a new `<Table.Td>` inserted **immediately after the title cell**. Contents: `<TrackTagsCell>` rendering current tag pills inline plus a trailing `+` trigger button (`ActionIcon variant="subtle"`).

**Mobile** — `<TrackTagsCell>` rendered as its own line under the artist text. Same content.

The cell is always present even when the track has zero tags (just the `+` button visible).

### TrackTagsPopover

Mantine `Popover` (`position="bottom-start"`, `withinPortal`, `shadow="md"`). Opens when either:

- the user clicks `+` in `TrackTagsCell`, or
- the user clicks any existing pill in the cell.

Body:

```
┌──────────────────────────────────────┐
│ 🔍 Найти / создать тег…             │
├──────────────────────────────────────┤
│ ☑ ● Vocal                            │
│ ☑   Dark             (no colour)     │
│ ☐ ● Drum                             │
│ ☐ ● Bass                             │
├──────────────────────────────────────┤
│  + Создать «hyper»                   │
│    [colour swatches × 12 ] [✕]      │
└──────────────────────────────────────┘
```

- Search input filters the list by `normalizedName` (case-insensitive prefix). Local-only.
- Checkbox click fires `useAddTrackTag` or `useRemoveTrackTag` immediately. Optimistic; rollback on error.
- "Создать «X»" appears below the list when the search term has no exact case-insensitive match. Clicking the row reveals the inline `ColorSwatchPicker` row (still inside the popover) for one click to pick a colour, or `✕` to leave it colourless. Hitting Enter or clicking the row again creates the tag (`POST /tags`) and immediately attaches it to the track (`POST /tracks/{trackId}/tags`).
- Pressing Escape, clicking outside, or clicking the trigger again closes the popover.
- Cap at 50 tags per track (mirror BE `_MAX_TAGS_PER_TRACK`). Once a track has 50 attached, the popover disables remaining checkboxes and shows an inline hint "Максимум 50 тегов".

### TagsManagerModal

Mantine `Modal` (`size="lg"`, `centered`).

```
┌────────────────────────────────────────────────┐
│ Управление тегами                          [×] │
├────────────────────────────────────────────────┤
│ [+ Новый тег]                  🔍 [search… ]   │
├────────────────────────────────────────────────┤
│ ● Vocal                  [✏ Renane] [🗑 Delete]│
│   Dark   (no colour)     [✏ Rename] [🗑 Delete]│
│ ● Drum                   [✏ Rename] [🗑 Delete]│
│   …                                            │
└────────────────────────────────────────────────┘
```

- "+ Новый тег" expands an inline `TagFormFields` row at the top of the list: `TextInput` (name) + `ColorSwatchPicker` + `Save` / `Cancel` buttons.
- The same `TagFormFields` replaces the row inline when the user clicks the pencil (`Rename`) icon.
- Trash icon opens a Mantine `modals.openConfirmModal` — "Удалить тег "X"? Будет снят со всех треков." Confirm fires `DELETE /tags/{id}`.
- Local prefix search filters the on-screen list. Server-side pagination is supported by the API but not exposed in the UI in v1.
- After every mutation: invalidate `['tags']`; after delete, also invalidate `['categories', 'tracks', ...]` to drop the now-removed pills on currently visible track rows.

### Pill rendering (`TagPill`)

- **With colour** — pill background = `color`, text colour = black or white chosen by `luminance(color)` (helper in `lib/tagPalette.ts`).
- **Without colour** — pill is a neutral outlined chip: `border: 1px solid var(--mantine-color-default-border)`, transparent background, default text colour.
- Optional `withRemove` prop adds an `×` icon (used inside `MultiSelect` rendering, not on read-only rows).

### Mobile considerations

- `TrackTagsCell` renders as its own line; pills wrap.
- Mantine `Popover` is full-width-with-padding on `xs` screens; works fine for the search-and-checkbox layout.
- `TagsManagerModal` becomes `fullScreen` below `sm`.
- `TagsFilterBar` collapses to a single full-width `MultiSelect` row with the `ALL/ANY` toggle on its own line below. The "Manage tags" button moves under the search input.

## Data flow

### Query keys

```ts
const tagsKey = () => ['tags'] as const;     // single unfiltered list; filter is local
// Server-side search on `GET /tags?search=` exists but is unused in v1 — the
// vocabulary is small enough that local prefix filtering inside both the
// popover and the manager modal is faster and avoids extra round-trips.

const trackTagsListKey = (trackId: string) =>
  ['tracks', trackId, 'tags'] as const;   // currently only used for invalidation

const categoryTracksKey = (
  id: string,
  search: string,
  sort: CategoryTrackSort,
  order: SortOrder,
  tagIds: readonly string[],          // lexicographically sorted
  tagMatch: 'all' | 'any',
) =>
  ['categories', 'tracks', id, search, sort, order, [...tagIds].sort().join(','), tagMatch] as const;
```

### Mutations

- `useAddTrackTag({ trackId, tagId, categoryId })`
  - `onMutate`: cancel queries on `['categories', 'tracks', categoryId]`, snapshot, patch every page's `items` (find row, push new tag into `tags`).
  - `mutationFn`: `POST /tracks/{trackId}/tags` body `{ tag_id }`.
  - `onError`: rollback snapshot, surface error toast.
  - `onSettled`: invalidate `['categories', 'tracks', categoryId]`.

- `useRemoveTrackTag({ trackId, tagId, categoryId })`
  - Same shape, `DELETE /tracks/{trackId}/tags/{tagId}`, filter the tag out of `tags`.

- `useCreateTag({ name, color })`
  - Optimistic insert into `tagsKey('')` (the unfiltered list). `onError` rollback. `onSuccess` returns the created `TagRow` so the popover can chain the `useAddTrackTag` call.

- `useRenameTag({ tagId, name, color })`
  - Optimistic patch of the list.

- `useDeleteTag({ tagId })`
  - Optimistic removal from the list.
  - `onSettled`: invalidate both `['tags']` and the *root* `['categories', 'tracks']` (drops the deleted pill on every cached category page).

### URL state

`features/tags/lib/tagsUrlState.ts` exports:

```ts
export const readTagsUrlState = (searchParams: URLSearchParams) => ({
  selectedIds: (searchParams.get('tags') ?? '').split(',').filter(Boolean),
  match: (searchParams.get('match') === 'any' ? 'any' : 'all') as 'all' | 'any',
});
export const writeTagsUrlState = (
  searchParams: URLSearchParams,
  next: { selectedIds: string[]; match: 'all' | 'any' },
) => {
  const params = new URLSearchParams(searchParams);
  if (next.selectedIds.length) params.set('tags', [...next.selectedIds].sort().join(','));
  else params.delete('tags');
  if (next.match === 'any') params.set('match', 'any');
  else params.delete('match');     // default omitted
  return params;
};
```

`TracksTab` reads/writes via `useSearchParams()` (react-router 7).

### Error mapping

| BE `error_code`                | Trigger                                            | UI                                                       |
| ------------------------------ | -------------------------------------------------- | -------------------------------------------------------- |
| `tag_name_conflict`            | TagsManagerModal create/rename                     | Inline `TagFormFields` field error; toast as fallback    |
| `invalid_name`/`invalid_color` | Server-side fallback (client Zod catches first)    | Inline form error                                        |
| `tag_not_found`                | Add/remove on a freshly-deleted tag                | Toast "Тег больше не существует"; invalidate `tags`      |
| `track_not_in_any_category`    | Should be impossible from this UI but mapped       | Toast "Этот трек больше не в категории"                  |
| `too_many_tags`                | Server-side fallback (UI caps at 50)               | Toast + disable further additions                        |
| `invalid_match`                | Server-side fallback (toggle restricts to all/any) | Toast "Неверный режим фильтра"                           |

## Edge cases

- **Empty vocabulary** — popover shows only the search input and (if anything typed) a single "Создать «X»" row. Filter bar shows the multiselect with placeholder "Нет тегов".
- **Tag deleted between fetch and click** — `useAddTrackTag` returns 404 `tag_not_found`; we toast and invalidate `tags` so the popover re-renders without the stale entry.
- **`color = null` round-trip** — every component handles both `string` and `null`. The popover's colour-picker also exposes a "clear" affordance (`✕`) for editing the existing colour back to null.
- **Filter contains an unknown tag id** (URL pasted from another user's session) — backend silently ignores it, returning an empty page when ALL is selected. Acceptable; we don't auto-prune the URL.
- **Concurrent edits on the same track** — every mutation is optimistic but server-final. If two clients race, the last write wins and the next refetch reflects it.
- **Mobile popover keyboard** — `MultiSelect`/search field auto-focuses on open; closing keyboard collapses the popover height naturally.

## Testing

### Unit (vitest + RTL + msw)

- `lib/tagPalette.ts` — luminance helper picks white text on dark swatches, black on light.
- `lib/normalizeTagName.ts` — matches BE behaviour for edge inputs (multiple spaces, leading/trailing whitespace, mixed case).
- `lib/tagsUrlState.ts` — round-trip + empty / single / multi / unknown match value.
- `hooks/useTags.ts` — single fetch, stable cache key, no params.
- `hooks/useAddTrackTag.ts` + `useRemoveTrackTag.ts` — optimistic patch / rollback / invalidation.
- `hooks/useCreateTag.ts` — 201 + 409 conflict.
- `hooks/useDeleteTag.ts` — cascade-invalidate `categories/tracks`.
- `components/TagPill.tsx` — coloured vs colourless render.
- `components/ColorSwatchPicker.tsx` — 12 swatches + clear → onChange(null).
- `components/TrackTagsPopover.tsx` — search filter; checkbox click triggers add/remove; "Создать «X»" only appears when miss; inline colour picker.
- `components/TagsManagerModal.tsx` — list, create form, rename inline, delete confirm.
- `components/TagsFilterBar.tsx` — pill display, ALL/ANY toggle, calls onChange with sorted ids.

### Integration (vitest + msw, full page mount)

- `TracksTab` with tag filter: select two tags from the bar → query string updates → `useCategoryTracks` fetches with `?tags=...&match=all` → msw returns filtered rows.
- End-to-end inside the tab: create tag (modal) → close → assign to track via popover → filter list by that tag (only this row remains) → unassign from track → tag pill disappears → delete tag (modal) → filter empties and falls back to full list.

### Out of scope (Playwright/Cypress)

This spec stays inside vitest. Mantine `Modal` and `Popover` are jsdom-friendly with the existing test setup shims.

## Files touched (summary)

**Backend (precondition commit):**
- `alembic/versions/<rev>_user_tags_color_nullable.py` (new).
- `src/collector/db_models.py`.
- `src/collector/curation/tags_repository.py`.
- `src/collector/curation_handler.py`.
- `scripts/generate_openapi.py` + regenerated `docs/openapi.yaml`.
- `tests/unit/test_tags_repository.py`, `tests/unit/test_curation_handler_tags.py`.

**Frontend (subsequent commits):**
- New: `frontend/src/features/tags/**` (components/hooks/lib + `index.ts`).
- Modified: `frontend/src/features/categories/hooks/useCategoryTracks.ts`.
- Modified: `frontend/src/features/categories/components/TracksTab.tsx`.
- Modified: `frontend/src/features/categories/components/TrackRow.tsx`.
- Modified: `frontend/src/api/schema.d.ts` (regenerated).
- New i18n keys under `frontend/src/i18n/en.json` `tags.*`.

## Out of scope (deferred to future iterations)

- Tag UI in curate / triage screens.
- Bulk multi-select track operations using `PUT /tracks/{id}/tags`.
- Tag analytics / counts.
- Hash-from-name colour fallback (we just store `null` instead).
- Drag-and-drop reordering of the vocabulary.
- Tag suggestions from Spotify / Beatport metadata.

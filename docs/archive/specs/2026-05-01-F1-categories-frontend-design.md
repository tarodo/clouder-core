# F1 — Categories Frontend (Layer 1 UI)

**Date:** 2026-05-01
**Status:** brainstorm stage — design approved, awaiting implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F1**.
**Backend prerequisite:** [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md) — already shipped to prod.
**Frontend prerequisite:** [`2026-04-30-frontend-bootstrap-design.md`](./2026-04-30-frontend-bootstrap-design.md) — A2 merged in PR #29.
**Successor blockers:** F8 Home (consumes `track_count` per category), F5 Curate (uses category list at finalize-time).

## 1. Context and Goal

A2 shipped the SPA shell with placeholder routes. `Categories` sidebar item currently renders an `EmptyState` "Coming soon". F1 fills it in.

After F1 ships, a logged-in user can:

- Navigate to `Categories` from the sidebar and land on their last-visited style (or first style for first visit).
- Switch between styles via a toolbar selector.
- See all categories of the current style in their stable user-controlled order.
- Create a new category (modal on desktop, bottom drawer on mobile).
- Rename a category (same form pattern).
- Soft-delete a category via confirm modal.
- Reorder categories via drag-and-drop (`@dnd-kit`), with full keyboard / screen-reader accessibility.
- Open a category detail page and inspect the tracks already in it (read-only list with server-side search and load-more pagination).

Out of scope: adding/removing tracks via direct UI (Curate F5 territory), cross-style flat list (deferred to F8 Home or later), category restore (`FUTURE-C1` — backend not exposed).

## 2. Scope

**In scope:**

- Three new routes — index redirect, list, detail.
- New feature folder `frontend/src/features/categories/` with routes / components / hooks / lib.
- DnD reorder via `@dnd-kit/sortable`.
- Form validation mirroring server constraints (`name` 1..64 chars after trim, no control chars, no whitespace-only) via Zod + `@mantine/form` (with `mantine-form-zod-resolver`).
- React-query hooks for the 7 endpoints F1 actually uses (see §6).
- i18n keys (EN-only, RU mirrored in iter-2b — keys must mirror existing structure in `frontend/src/i18n/en.json`).
- Unit tests (Vitest + Testing Library) for components + hooks, integration tests for the page-level flows using MSW (Mock Service Worker — already wired in A2).

**Out of scope:**

- Cross-style list endpoint (`GET /categories`) — deferred to Home (F8).
- Add-track / remove-track UI inside the tracks tab — deferred to Curate (F5).
- Bulk operations on categories — `FUTURE-C3` (backend not exposed).
- Restore from soft-delete — `FUTURE-C1` (backend not exposed).
- Category metadata beyond `name` (description, color, cover) — `FUTURE-C5`.
- Production deploy of the SPA (CC-1 in roadmap, separate ticket).
- Playwright E2E (CC-2 deferred per roadmap recommendation).

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Per-style routing only.** `/categories/:style_id` is canonical; cross-style endpoint not consumed. | Reorder is per-style by spec-C 5.7. Cross-style list has no position semantics. Q2 closed: option **A**. |
| D2 | **Sidebar `Categories` redirects.** Index route `/categories` redirects to `/categories/:style_id` where `style_id` = last visited (localStorage key `clouder.lastStyleId`) or first style alphabetically from `GET /styles`. | No dead-end picker page; URL canonicalises state. Q3 closed: hybrid **A2 + A3**. |
| D3 | **Toolbar `<StyleSelector>` (Mantine `Select`)** in page header switches styles. Updates URL + writes to localStorage on each change. | Lets users switch on the fly without sidebar trip. Pairs with D2 redirect. |
| D4 | **Mutation strategy mixed.** Rename + reorder = optimistic (with rollback on error); create + delete = pessimistic. | Q4 closed: **B3**. Rename-409 / reorder-422 are recoverable; delete confirm modal already provides friction; create needs server-assigned `id`/`position`. |
| D5 | **Forms in Modal (desktop) / Drawer bottom (mobile).** Same hook (`useDisclosure`) opens both; `useMediaQuery('(max-width: 64em)')` switches the container. Delete uses Mantine `modals.openConfirmModal` regardless of viewport. | Q5 closed: **C2 + C4**. Matches OPEN_QUESTIONS Q3 DateRangeField pattern. |
| D6 | **DnD reorder via `@dnd-kit/sortable`.** Drag handle (`IconGripVertical`) on each row left-side. Long-press 250ms initiates drag on touch. | Q7 closed: **G1** (revised after user clarified DnD-restriction applies to Curate only). Keyboard a11y is built-in (Tab → Space → Arrow → Space). No `↑/↓` buttons. |
| D7 | **Optimistic reorder with debounced PUT.** Local swap fires immediately; full-array PUT is debounced 200ms; rapid swaps coalesce. On 422 `order_mismatch` → invalidate + toast "List changed elsewhere — refreshed." | Avoids 3 PUTs for 3 quick drags. Race recovery via cache invalidation. |
| D8 | **Tracks tab read-only with `useInfiniteQuery` + load-more button.** No infinite scroll, no full pagination, no virtualization. Server-side search via debounced `?search=` (300ms, lowercased). | Q6 closed: **D2 + E2**. Predictable on mobile, simple code. Virtualisation not warranted at typical sizes (≪100 tracks/category). |
| D9 | **Tracks tab density = Mantine `<Table>` desktop / `<Stack>` of `<Card>` mobile.** Columns: `Title (mix on second line) | Artists | BPM/Key | Length | Added`. AI-suspected → small warning icon left of title. | Spotify play / ISRC / release_type are deferred until Curate (F5) needs them. |
| D10 | **Validation via Zod schema mirroring server.** `categoryName: z.string().trim().min(1).max(64).refine(no-control-chars).refine(no-whitespace-only)`. Same schema for create + rename. | Same rules as `validate_category_name` in spec-C 6.3. Single source on the client. |
| D11 | **All mutations route 409 / 422 to inline form errors; 4xx-other / 5xx → toast.** `name_conflict` and `validation_error` show under the input field. `order_mismatch` is operationally a refresh, not a form error. | Inline errors are for actionable user input; toasts are for state changes the user cannot fix from the form. |
| D12 | **One PR equivalent — direct merge to `main`.** Solo dev; no PR review cycle. Branch `feat/categories-crud` created in worktree, merged via `git merge --no-ff`, pushed straight to `origin main`. | TD-6 branch protection not yet configured (roadmap notes); user opted out of GitHub PR. Commits via `caveman:caveman-commit` skill (CLAUDE.md mandate). |
| D13 | **Feature folder, not type-split.** `frontend/src/features/categories/{routes,components,hooks,lib}/`. Co-locates everything F1-related. | Existing `frontend/src/` mixes route-based + small `components/`. Feature-folder isolates the new surface and simplifies later sub-feature additions (track add/remove in F5). |
| D14 | **Bundle additions: `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, `mantine-form-zod-resolver`.** `zod` already installed. ~30 KB minified for dnd-kit + ~5 KB resolver. | Code-splitting (CC-3) is recommended before F8 to keep Home fast; F1 alone does not block. |
| D15 | **`/categories/:style_id/:id`** is the detail route — id is the category UUID, not nested under style in path because spec-C uses flat detail routes. | Mirrors backend URL design (spec-C D10 shallow-nested). |
| D16 | **localStorage key namespace `clouder.*`.** Specifically `clouder.lastStyleId`. | Avoids collisions with future state (`clouder.colorScheme`, etc.). One-line helper in `lib/lastVisitedStyle.ts`. |
| D17 | **Empty states cover four cases.** (1) zero styles → instructional EmptyState pointing at admin ingest; (2) zero categories in style → CTA "Create first category"; (3) zero tracks in category → "No tracks yet — finalize a triage block to populate"; (4) zero search results → "No tracks match '<term>'" with reset action. | Per design system § EmptyState. Copy in §10. |

## 4. UI Surface

### 4.1 Routes

```
/categories
   └── CategoriesIndexRedirect            — no UI, redirect-only
/categories/:style_id
   └── CategoriesListPage                  — P-09
/categories/:style_id/:id
   └── CategoryDetailPage                  — P-10 (tracks tab inside)
```

`/categories/:style_id` invalid UUID → 404 page (existing `RouteErrorBoundary`).
`/categories/:style_id/:id` 404 from `GET /categories/{id}` → page-level not-found.

### 4.2 CategoriesListPage (P-09)

Layout (desktop ≥ 64em):

```
[Page header]
  Title: "Categories"
  StyleSelector (Mantine Select, pinned right) — switches /categories/:style_id
  Primary CTA: <Button leftSection=<IconPlus>> Create category </Button>

[Body]
  CategoriesList (DndContext + SortableContext)
    └── CategoryRow x N
          ├── DragHandle (IconGripVertical, 24px hit-target)
          ├── Name (clickable → detail)
          ├── track_count badge (mono, "12 tracks")
          └── KebabMenu (Rename / Delete)

[EmptyState] (when N = 0 in current style)
  Icon: IconCategory
  Title: "No categories yet"
  Body: "Create your first category for {{style_name}}."
  CTA: Same Create button
```

Mobile (< 64em): same surface; CategoryRow drops kebab into row-tail icon button; primary CTA becomes a sticky bottom bar `<Button fullWidth>`.

### 4.3 CategoryDetailPage (P-10)

Layout:

```
[Breadcrumb]
  Categories  /  {{style_name}}  /  {{category_name}}

[Page header]
  Title: {{category_name}} (large)
  Subtitle: "{{track_count}} tracks · created {{relative_time}}"
  Actions row: Rename · Delete · (no Reorder here — list-page only)

[Tracks tab] — single tab; structure left in place for future F5/F8 sub-tabs.
  TextInput (IconSearch left, debounced 300ms) → ?search=
  Active-search badge (when ?search non-empty): "Search: '{{term}}' ✕"

  TracksTable (desktop) / TrackCardStack (mobile)
    └── TrackRow x N
  LoadMoreButton — "Show more (N remaining)" — hidden when total ≤ shown

[EmptyState] (when search empty + zero tracks)
  Body: "No tracks yet — finalize a triage block to populate."

[EmptyState] (when search non-empty + zero results)
  Body: "No tracks match '{{term}}'."
  CTA: Clear search
```

### 4.4 Create / Rename forms

Modal/Drawer body (same component, `<CategoryFormDialog mode="create"|"rename">`):

```
[Form]
  TextInput
    label: "Name"
    description: "Up to 64 characters."
    placeholder: "Tech House"
    error: { from Zod (client) | from API 409 (server) }
    autoFocus: true
    maxLength: 64 (UI hint, server is source of truth)

[Footer]
  Cancel | Save (or Create)
```

Submit:
- Client validation runs first; if fail — inline error, no API call.
- Optimistic rename: cache update happens before request. If 409 → roll back + inline error.
- Pessimistic create: spinner on Save until 201 → close + invalidate `categoriesByStyle` cache.

### 4.5 Delete confirm

`modals.openConfirmModal({ title, children, labels, confirmProps })`:

```
Title: "Delete category?"
Children: "Delete '{{name}}'? Tracks remain in history but become invisible."
labels: { confirm: "Delete", cancel: "Cancel" }
confirmProps: { color: "red" }
```

On confirm: pessimistic — spinner on confirm CTA until 204, then close + invalidate cache + toast "Category deleted."

## 5. Component Catalog

| Component | Anatomy | Mantine base | Owner |
|---|---|---|---|
| `CategoriesIndexRedirect` | none — runs effect, returns `<Navigate>` | — | F1 |
| `CategoriesListPage` | Page header + StyleSelector + List + EmptyState | `Stack`, `Group` | F1 |
| `CategoryDetailPage` | Breadcrumb + header + actions + TracksTab | `Breadcrumbs`, `Stack` | F1 |
| `StyleSelector` | Select with styles, controlled value = `style_id` | `Select` | F1 |
| `CategoriesList` | `DndContext` + `SortableContext` + map of rows | — | F1 |
| `CategoryRow` | Drag handle + name link + count badge + kebab | `Group`, `ActionIcon`, `Menu`, `Badge` | F1 |
| `CategoryFormDialog` | Mode-aware (create/rename) form in Modal/Drawer | `Modal`, `Drawer`, `TextInput`, `Button` | F1 |
| `TracksTab` | Search input + table/cards + load-more | `TextInput`, `Table`, `Card`, `Stack`, `Button` | F1 |
| `TrackRow` | Title + mix + artists + BPM + length + added + AI flag | `Table.Tr`, `Table.Td`, `Card.Section` | F1 |
| `EmptyState` | Existing — reuse from `frontend/src/components/EmptyState.tsx` | — | reused |
| `RouteErrorBoundary` | Existing — reuse | — | reused |

`CategoryRow` is the only component that needs `useSortable` from `@dnd-kit/sortable`. It exposes `attributes`, `listeners`, `setNodeRef`, `transform`, `transition`. The row applies `transform` via inline style and binds `listeners` to the drag handle only (not the whole row), so click on name navigates instead of triggering drag.

## 6. Data Flow

### 6.1 React-query keys

```ts
['styles']                                    // useStyles
['categories', 'byStyle', styleId]            // useCategoriesByStyle
['categories', 'detail', categoryId]          // useCategoryDetail
['categories', 'tracks', categoryId, search]  // useCategoryTracks (infinite)
```

`'styles'` is invalidated on auth events (already by AuthProvider in A2). `'byStyle'` invalidates after create / delete / reorder. `'detail'` invalidates after rename / delete. `'tracks'` does not invalidate within F1 — track membership only changes via Curate (F5).

### 6.2 Hooks (one file each under `hooks/`)

| Hook | Endpoint | Notes |
|---|---|---|
| `useStyles()` | `GET /styles` | Single page (limit=200), no pagination in F1. |
| `useCategoriesByStyle(styleId)` | `GET /styles/{styleId}/categories` | limit=200 (categories per style ≪ 200 per spec-C). Single page. |
| `useCategoryDetail(id)` | `GET /categories/{id}` | Used by detail page header. |
| `useCategoryTracks(id, search)` | `GET /categories/{id}/tracks` | `useInfiniteQuery`; `getNextPageParam` from `offset + items.length` while `total > offset + items.length`. limit=50. |
| `useCreateCategory(styleId)` | `POST /styles/{styleId}/categories` | Pessimistic. `onSuccess` invalidates `byStyle`. |
| `useRenameCategory(id, styleId)` | `PATCH /categories/{id}` | Optimistic. `onMutate` snapshots and patches both `byStyle` and `detail`. `onError` rolls back. `onSettled` invalidates. |
| `useDeleteCategory(id, styleId)` | `DELETE /categories/{id}` | Pessimistic. `onSuccess` invalidates `byStyle`. |
| `useReorderCategories(styleId)` | `PUT /styles/{styleId}/categories/order` | Optimistic + 200ms debounce of PUT body. Race recovery on 422. |

### 6.3 Optimistic reorder algorithm

```ts
// Pseudocode
let pendingTimer: NodeJS.Timeout | null = null
let latestOrder: string[] | null = null

function onDragEnd({ active, over }) {
  if (!over || active.id === over.id) return
  const current = queryClient.getQueryData(['categories','byStyle',styleId])
  const next = arrayMove(current.items, indexOf(active.id), indexOf(over.id))
  queryClient.setQueryData(['categories','byStyle',styleId], { ...current, items: next })
  latestOrder = next.map(c => c.id)
  if (pendingTimer) clearTimeout(pendingTimer)
  pendingTimer = setTimeout(flush, 200)
}

async function flush() {
  if (!latestOrder) return
  const order = latestOrder
  latestOrder = null
  pendingTimer = null
  try { await reorderApi(styleId, order) }
  catch (e) {
    if (is422(e, 'order_mismatch')) {
      queryClient.invalidateQueries(['categories','byStyle',styleId])
      notifications.show({ message: t('categories.toast.race_refreshed'), color: 'yellow' })
    } else {
      // generic error — invalidate + toast
    }
  }
}
```

The hook owns the timer + `latestOrder` ref; it is keyed on `styleId` so switching styles cancels the pending flush.

### 6.4 Style switching

`StyleSelector.onChange(newStyleId)`:

1. `localStorage.setItem('clouder.lastStyleId', newStyleId)`
2. `navigate('/categories/' + newStyleId)`

`CategoriesIndexRedirect`:

```tsx
function CategoriesIndexRedirect() {
  const { data: styles, isLoading } = useStyles()
  if (isLoading) return <FullScreenLoader/>
  if (!styles?.items?.length) return <NoStylesEmptyState/>
  const last = localStorage.getItem('clouder.lastStyleId')
  const target = styles.items.find(s => s.id === last)?.id ?? styles.items[0].id
  return <Navigate to={`/categories/${target}`} replace/>
}
```

## 7. Validation

### 7.1 Zod schema (`lib/categorySchemas.ts`)

`CONTROL_CHARS` matches ASCII C0 + DEL + C1 control bytes.

```ts
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/
export const categoryNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(64, 'name_too_long')
  .refine(s => !CONTROL_CHARS.test(s), 'name_control_chars')
export const createCategorySchema = z.object({ name: categoryNameSchema })
export const renameCategorySchema = createCategorySchema
```

Error keys `name_required`, `name_too_long`, `name_control_chars` map to i18n in §10.

### 7.2 Form integration

```ts
import { useForm } from '@mantine/form'
import { zodResolver } from 'mantine-form-zod-resolver'

const form = useForm({
  initialValues: { name: '' },
  validate: zodResolver(createCategorySchema),
})
```

Server 409 `name_conflict` → `form.setFieldError('name', t('categories.errors.name_conflict'))`.
Server 422 `validation_error` → top-level form error (rare; client validation should prevent it).

## 8. Error UX Mapping

| Code | Origin | UX |
|---|---|---|
| `validation_error` (422) | rename / create | Inline form error (top-level message). Should not happen in practice (client mirrors server). |
| `name_conflict` (409) | rename / create | Inline error under name input. Roll back optimistic patch on rename. |
| `category_not_found` (404) | detail / patch / delete | Page-level not-found UI on detail. Toast + invalidate `byStyle` for patch / delete (likely raced with another tab). |
| `style_not_found` (404) | list / create | Page-level not-found. Should be unreachable: `StyleSelector` only offers existing styles. |
| `track_not_found` (404) | tracks tab | Skipped — F1 does not add tracks. |
| `order_mismatch` (422) | reorder | Toast `categories.toast.race_refreshed` + invalidate. No inline error (drag UI is already done). |
| `unauthorized` (401) | any | AuthProvider in A2 already redirects to `/login` on 401. No F1 special handling. |
| 503 cold-start (`Service Unavailable`) | any | Existing `apiClient` has cold-start retry baked in (A2). Toast only on terminal failure. |
| Network failure | any | Existing toast pattern (`errors.network` key from A2). |

Toasts use `@mantine/notifications` with positions inherited from A2 (`top-right`).

## 9. Code Layout

### 9.1 New files

```
frontend/src/features/categories/
├── routes/
│   ├── CategoriesIndexRedirect.tsx
│   ├── CategoriesListPage.tsx
│   └── CategoryDetailPage.tsx
├── components/
│   ├── CategoriesList.tsx
│   ├── CategoryRow.tsx
│   ├── StyleSelector.tsx
│   ├── CategoryFormDialog.tsx
│   ├── TracksTab.tsx
│   └── TrackRow.tsx
├── hooks/
│   ├── useStyles.ts
│   ├── useCategoriesByStyle.ts
│   ├── useCategoryDetail.ts
│   ├── useCategoryTracks.ts
│   ├── useCreateCategory.ts
│   ├── useRenameCategory.ts
│   ├── useDeleteCategory.ts
│   └── useReorderCategories.ts
├── lib/
│   ├── categorySchemas.ts
│   └── lastVisitedStyle.ts
└── index.ts
```

### 9.2 Modified files

- `frontend/src/routes/router.tsx` — register the three new routes; remove import of placeholder `categories.tsx`.
- `frontend/src/routes/categories.tsx` — **deleted** (placeholder no longer needed).
- `frontend/src/i18n/en.json` — add `categories.*` namespace (keys in §10).
- `frontend/package.json` — add `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, `mantine-form-zod-resolver`.

### 9.3 No backend changes

Confirmed: spec-C ships all 7 endpoints F1 needs (`GET /styles` + 6 categories endpoints). `pnpm api:types` does not need to be re-run; existing `frontend/src/api/schema.d.ts` already includes them.

## 10. i18n Keys

Add under `frontend/src/i18n/en.json` (mirror existing structure; RU lands in iter-2b):

```json
{
  "categories": {
    "page_title": "Categories",
    "create_cta": "Create category",
    "loading": "Loading categories…",
    "track_count_one": "{{count}} track",
    "track_count_other": "{{count}} tracks",
    "row_menu": { "rename": "Rename", "delete": "Delete" },
    "form": {
      "name_label": "Name",
      "name_description": "Up to 64 characters.",
      "name_placeholder": "Tech House",
      "create_title": "Create category",
      "rename_title": "Rename category",
      "save": "Save",
      "create_submit": "Create",
      "cancel": "Cancel"
    },
    "delete_modal": {
      "title": "Delete category?",
      "body": "Delete '{{name}}'? Tracks remain in history but become invisible.",
      "confirm": "Delete",
      "cancel": "Cancel"
    },
    "toast": {
      "created": "Category created.",
      "renamed": "Category renamed.",
      "deleted": "Category deleted.",
      "race_refreshed": "List changed elsewhere — refreshed.",
      "generic_error": "Couldn't save changes. Please retry."
    },
    "errors": {
      "name_required": "Name is required.",
      "name_too_long": "Name must be 64 characters or less.",
      "name_control_chars": "Name contains forbidden characters.",
      "name_conflict": "A category with this name already exists in this style."
    },
    "empty_state": {
      "no_categories_title": "No categories yet",
      "no_categories_body": "Create your first category for {{style_name}}.",
      "no_tracks_title": "No tracks yet",
      "no_tracks_body": "Finalize a triage block to populate this category.",
      "no_search_results_title": "No tracks match '{{term}}'.",
      "clear_search": "Clear search"
    },
    "no_styles": {
      "title": "No styles available",
      "body": "Styles are populated by admin ingest. Ask an admin to seed Beatport data."
    },
    "detail": {
      "tracks_search_placeholder": "Search by title…",
      "tracks_load_more": "Show more ({{remaining}} remaining)",
      "back_to_list": "Back to categories",
      "actions": { "rename": "Rename", "delete": "Delete" }
    },
    "tracks_table": {
      "title": "Title",
      "artists": "Artists",
      "bpm": "BPM",
      "length": "Length",
      "added": "Added",
      "ai_suspected_aria": "AI-suspected"
    }
  }
}
```

Pluralisation uses i18next ICU (`_one` / `_other`) — already configured by A2.

Domain terms `BPM`, `Length`, `Added` stay literal (per CLAUDE.md memory: "Domain terms not translated").

## 11. Testing

### 11.1 Unit (Vitest + Testing Library)

`features/categories/lib/__tests__/categorySchemas.test.ts`:

- Empty / whitespace-only / 65-char / 64-char / control-chars / unicode all behave as documented.
- `categoryNameSchema.parse(' Tech  House ')` → `'Tech  House'` (trim only — server collapses internal whitespace for uniqueness, client preserves display).

`features/categories/lib/__tests__/lastVisitedStyle.test.ts`:

- Read returns `null` when unset; write+read round-trip.

`features/categories/components/__tests__/CategoryRow.test.tsx`:

- Renders name, badge, kebab.
- Drag handle has `aria-roledescription="sortable"`.
- Click on name navigates; click on drag handle does not.

`features/categories/components/__tests__/CategoryFormDialog.test.tsx`:

- Empty submit → inline `name_required` error.
- 65-char submit → inline `name_too_long`.
- Successful create → `onSuccess` callback fires with new category.

`features/categories/components/__tests__/StyleSelector.test.tsx`:

- Renders styles from query; change triggers navigate + localStorage write.

`features/categories/hooks/__tests__/useReorderCategories.test.tsx`:

- Two rapid swaps → one PUT (debounce coalesces).
- 422 response → cache invalidate + toast.

### 11.2 Integration (Vitest + MSW)

`features/categories/__tests__/CategoriesListPage.integration.test.tsx`:

1. **Index redirect → first style.** No localStorage → land on first style. With localStorage → land on stored style.
2. **List render + create.** Mock `byStyle` empty. Click Create → form opens → submit "Tech House" → list updates with one row.
3. **Optimistic rename rollback.** Rename row → cache patches before MSW responds → MSW responds 409 → row reverts + inline error visible.
4. **Delete confirm + invalidate.** Click kebab → Delete → confirm modal → Confirm → row removed.
5. **DnD reorder optimistic + race recovery.** Drag row 0 → row 2 → cache shows new order before MSW responds → MSW responds 422 → cache invalidated to canonical order + toast.

`features/categories/__tests__/CategoryDetailPage.integration.test.tsx`:

1. **Tracks render + load-more.** Mock 60-track total, limit=50 → first page renders 50 + "Show more (10 remaining)" → click → renders all 60, button hides.
2. **Search + reset.** Type "Tech" → debounced 300ms → MSW receives `?search=tech` → results filtered. Click clear-search → ?search dropped.
3. **Empty search results.** Type "zzz" → empty list with "No tracks match 'zzz'" + clear CTA.
4. **404 on stale category.** Navigate to `/categories/{style}/{deleted_id}` → page-level not-found UI.

### 11.3 No E2E

Playwright (CC-2) deferred per roadmap. Manual smoke before merge:

1. Sign in.
2. `Categories` sidebar → land on style.
3. Create category → rename → reorder via DnD → delete.
4. Open detail → search → load more.
5. Switch styles via toolbar → URL + localStorage update.
6. Refresh page → land on same style.

### 11.4 Coverage

No numeric gate. Every hook has at least one unit test; every page has at least one happy-path integration test; every error UX branch covered (Q4 / D11) at least once.

## 12. Delivery

1. Branch `feat/categories-crud` created from `main` in worktree `.claude/worktrees/new_front`.
2. Sequential commits per natural boundary (folder scaffold → hooks → list page → detail page → DnD → tests → i18n). Each commit message produced by `caveman:caveman-commit` (CLAUDE.md mandate).
3. `pnpm install` (lockfile updated for new deps), `pnpm test` green, `pnpm build` green.
4. `pnpm dev` manual smoke against local backend (worktree A2 already verified `pnpm api:types` matches).
5. `git checkout main && git merge feat/categories-crud --no-ff` — preserves history.
6. `git push origin main` — direct (TD-6 branch protection not configured; user opted out of PR review for this ticket).
7. Roadmap update: append a `LESSONS.md` line "F1 — what bit me" entry (per recommendation in roadmap discussion).

CI (`.github/workflows/pr.yml`) runs on push to `main` and validates the merge commit. Local `pnpm test` is the authoritative pre-merge gate.

## 13. Open Items, Edge Cases, Future Flags

### 13.1 Edge cases worth a comment

- **Style deleted server-side while user has it in localStorage.** `CategoriesIndexRedirect` falls back to first style; no error. Worth a code comment.
- **All styles deleted while page open.** `useStyles` returns empty list → `NoStylesEmptyState` (rare; admin-side action).
- **Optimistic rename on a row currently being dragged.** DnD context discards drag on data change — `@dnd-kit` handles via `id` stability. Tests cover.
- **Browser back during pending reorder flush.** Component unmount cancels timer; final state is whatever server has. Consistent with optimistic semantics.

### 13.2 Future flags (post-iter-2a)

- **`FUTURE-F1-1`** — cross-style flat list view at `/categories` (re-uses `GET /categories`). Lands when Home (F8) needs the data shape.
- **`FUTURE-F1-2`** — restore-from-soft-delete UI. Backend `FUTURE-C1` ships first; UI then exposes "Recently deleted" list.
- **`FUTURE-F1-3`** — bulk operations (multi-select rename / delete / reorder). Backend `FUTURE-C3` first.
- **`FUTURE-F1-4`** — inline rename (click name → edit-in-place). Considered and deferred (Q5 option C3): adds disclosure surface, mobile UX is worse with virtual keyboard.
- **`FUTURE-F1-5`** — column customisation for tracks tab (show/hide ISRC, release_type, key, AI flag). Lands when Curate (F5) introduces multi-select context.

### 13.3 Cross-ticket dependencies

- **F8 Home** consumes `track_count` for dashboard tiles — same `useCategoriesByStyle` hook applies; can be extracted to shared if Home needs cross-style aggregate.
- **F5 Curate** finalize promotes tracks into a category — invalidates `categories.tracks` cache key (Curate hook responsibility, not F1).
- **F2 Triage list** does not consume categories — independent.

## 14. Acceptance Criteria

- All routes (§4.1) resolve; index redirect lands on last/first style.
- StyleSelector switches styles via Select; URL + localStorage update.
- Category list renders in `position` order; DnD reorder works on desktop (mouse) and mobile (long-press 250ms) and via keyboard (Tab → Space → Arrow → Space).
- Create / rename forms validate per Zod (§7.1); 409 maps to inline error; 200 closes form + invalidates cache.
- Delete confirms via `modals.openConfirmModal` and removes row.
- Detail page renders track count + actions + tracks tab.
- Tracks tab supports server-side search (300ms debounce) and load-more pagination.
- All four empty states covered (D17).
- `pnpm test` green (≥ 70 tests passing — A2 baseline 46 + new ~24).
- `pnpm build` produces under 700 KB minified bundle.
- Manual smoke (§11.3) green against local dev backend.

## 15. References

- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket F1.
- Backend prereq: [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md).
- Frontend bootstrap: [`2026-04-30-frontend-bootstrap-design.md`](./2026-04-30-frontend-bootstrap-design.md).
- Pages catalog Pass 1: `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` — P-09..P-13.
- Component spec sheet: `docs/design_handoff/04 Component spec sheet.html`.
- Open questions: `docs/design_handoff/OPEN_QUESTIONS.md` — Q1..Q13. Q4 + Q5 resolved during this brainstorm (see §1, D6, D7).
- Project memory: `project_clouder_curation_ux.md` — DnD restriction scope clarified 2026-05-01.
- Tokens: `docs/design_handoff/tokens.css`, `frontend/src/tokens.css`, `frontend/src/theme.ts`.

# F2 — Triage List + Create Frontend (Layer 2 UI, partial)

**Date:** 2026-05-02
**Status:** brainstorm stage — design approved, awaiting implementation plan
**Author:** @tarodo (via brainstorming session)
**Parent roadmap:** [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket **F2**.
**Backend prerequisite:** [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md) — already shipped to prod.
**Frontend prerequisite:** [`2026-05-01-F1-categories-frontend-design.md`](./2026-05-01-F1-categories-frontend-design.md) — F1 merged 2026-05-02.
**Successor blockers:** F3 Triage detail (consumes the row → detail navigation built here), F4 Finalize (consumes block detail), F5 Curate (consumes block detail), F8 Home (composes triage block summaries).

## 1. Context and Goal

F1 shipped Categories CRUD on the SPA shell. The `Triage` sidebar item still renders an `EmptyState` "Coming soon". F2 fills in the **list + create + soft-delete** slice of the triage surface. Detail view (F3), buckets / move / transfer (F3 internals), and finalize (F4) are out of scope.

After F2 ships, a logged-in user can:

- Navigate to `Triage` from the sidebar and land on their last-visited style (or first style for first visit).
- Switch between styles via the same `StyleSelector` toolbar component as F1.
- See triage blocks of the current style split into `Active | Finalized | All` tabs with per-tab counters.
- Create a new triage block via Modal (desktop) / Drawer (mobile). Form is `name` (auto-suggested as `<style_name> W<isoWeek(date_from)>`, mutable) plus a Mantine `DatePickerInput` range.
- Soft-delete a block via kebab → `modals.openConfirmModal`.
- Click a row to open the detail page route (renders an F3-stub `EmptyState` placeholder until F3 ships).

Out of scope for F2: block detail content (P-16, F3), bucket / track listing inside a block (F3), move / transfer (F3 internals), finalize (F4), Curate (F5), restore from soft-delete (`FUTURE-D5`, backend not exposed), bulk-create.

## 2. Scope

**In scope:**

- Three new routes — index redirect, list page, detail-stub.
- New feature folder `frontend/src/features/triage/` with routes / components / hooks / lib.
- Shared `StyleSelector` extracted from `features/categories/components/` to a reusable location (F1 owned it; both features now consume the same component).
- Tabbed list (`Active | Finalized | All`) with `useInfiniteQuery` load-more pagination.
- Create form: Mantine `DatePickerInput type="range"` + `TextInput` with auto-suggest, Modal/Drawer dispatcher mirroring F1 `CategoryFormDialog`.
- 503 cold-start UX: modal closes, three-step auto-invalidate (immediate, +15s, +30s), terminal toast if block never appears.
- Soft-delete via `modals.openConfirmModal`, pessimistic.
- Form validation via Zod + `mantine-form-zod-resolver` (already installed).
- React-query hooks for the 4 endpoints F2 actually uses (see §6).
- i18n keys (EN-only, `triage.*` namespace; RU mirrored in iter-2b).
- Unit tests (Vitest + Testing Library) for components, helpers, and hooks; integration tests via MSW.

**Out of scope:**

- Block detail page (P-16 / F3).
- Bucket-track listing, move, transfer, finalize (F3 / F4).
- Cross-style flat list view at `/triage` — deferred (`FUTURE-F2-1`); per-style isolation chosen in D1.
- Search / filter beyond status tabs — deferred (`FUTURE-F2-2`); MVP list is small per (user, style).
- Block rename — backend does not expose a rename endpoint; out of scope (`FUTURE-F2-3`).
- Restore from soft-delete — backend `FUTURE-D5`.
- Production deploy of the SPA (CC-1 in roadmap).
- Playwright E2E (CC-2 deferred).

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | **Per-style routing only.** `/triage/:style_id` is canonical; cross-style endpoint not consumed. Mirror F1 D1. | User explicitly requested isolation between styles to avoid cross-style confusion. Triage is by-construction a per-(style, window) operation. Cross-style aggregate has no operational value at MVP. |
| D2 | **Sidebar `Triage` redirects.** Index route `/triage` redirects to `/triage/:style_id` where `style_id` = last visited (localStorage key `clouder.lastTriageStyleId`) or first style alphabetically from `useStyles`. | Mirror F1 D2. Independent localStorage key so categories ↔ triage navigation does not bleed. |
| D3 | **Toolbar `<StyleSelector>`** in page header switches styles. Same component as F1. | Reuse — see D14. |
| D4 | **Tabs `Active | Finalized | All`.** Default tab `Active`. Each tab is an independent `useInfiniteQuery` keyed by `status`. Counter rendered in tab label (`Active · 2`) from `total` returned by the first page. | DJ workflow has 1–3 active blocks at a time and a growing finalized archive. Splitting tabs keeps Active dense, Finalized out of the way. |
| D5 | **List sort `created_at DESC, id ASC`.** Backend default. No user-controlled sort in F2 (`FUTURE-F2-2`). | Most recent block at the top is the right default for working sessions. |
| D6 | **Row content:** `name | date_from..date_to | track_count badge | created_at relative-time` + kebab. Finalized tab swaps `created_at` for `finalized_at`. Click row → `/triage/:style_id/:id` (F3 destination). | Spec-D `TriageBlockSummary` provides all fields. Click-row navigation is built now; F3 fills the destination. |
| D7 | **Mutation strategy: pessimistic for create + delete.** Mirror F1 (no optimistic create — server assigns id; no optimistic delete — confirm modal already provides friction). No rename / reorder mutations exist for triage. | F1 D4 paid optimistic only on rename/reorder; F2 has neither. |
| D8 | **Modal (desktop) / Drawer bottom (mobile).** `useDisclosure` opens both; `useMediaQuery('(max-width: 64em)')` switches container. Mirror F1 D5. | Same UX expectations as F1 forms. |
| D9 | **Auto-suggest name `<style_name> W<isoWeek(date_from)>`.** Updates as `date_from` changes **only while the user has not edited the name field manually** (tracked via a `userEditedName` ref toggled `true` on the first user keystroke in the field). After manual edit, auto-sync stops permanently for that modal session. | DJs default to `Tech House W17` style names; auto-suggest removes a routine keystroke without overwriting deliberate user input. ISO week from `date_from` matches the conventional release-window naming. |
| D10 | **Date range validation.** `date_from` and `date_to` both required; `date_to >= date_from` (mirror server-side spec-D §5.2 422 condition). No upper bound on window width at MVP — user is the only operator. | Server is the source of truth; client mirrors the same rule for inline error UX. |
| D11 | **503 cold-start UX (spec-D §5.2 known runtime risk).** On terminal 503 from `POST /triage/blocks` (after `apiClient` cold-start retry), modal closes, yellow toast `triage.toast.create_pending` shows, and the hook auto-invalidates `byStyle` queries at t=0, t=+15s, t=+30s. If a block matching `(name, date_from, date_to)` appears in any of those refetches, hook stops polling and shows `triage.toast.create_eventually_succeeded`. If after t=+30s nothing matches, terminal toast `triage.toast.create_failed_to_confirm` prompts the user to try again. | Spec-D explicitly flags this; UI must guide the user. Auto-poll removes the cognitive load of "did it succeed?" without enabling a duplicate-block retry race. |
| D12 | **Soft-delete via `modals.openConfirmModal`, pessimistic.** Body copy explains tracks already promoted to categories remain there (the source pointer is `ON DELETE SET NULL` on hard-delete only — soft-delete keeps the audit). | Mirror F1 D11 + spec-D §5.10. Single confirm step, no undo (`FUTURE-D5`). |
| D13 | **All mutations route 422 / 4xx-other / 5xx → toasts.** No inline server errors on triage create form except 422 `validation_error` (which Zod should pre-empt). | Triage form has no `name_conflict` analogue — backend does not enforce uniqueness (spec-D D2). |
| D14 | **Extract `StyleSelector` and `useStyles` to shared locations.** F1 currently owns `StyleSelector` at `features/categories/components/StyleSelector.tsx` and the `useStyles` hook in `features/categories/hooks/`. F2 needs both. To avoid a feature-folder cross-import, move `StyleSelector` → `frontend/src/components/StyleSelector.tsx` (the existing top-level `components/` already hosts shared atoms like `EmptyState`) and `useStyles` → `frontend/src/hooks/useStyles.ts`. Update F1's imports. Tests move alongside. | One-line dependency direction rule: features depend on `components/` and `hooks/`, never on each other. Co-locating with `EmptyState` matches existing convention. |
| D15 | **Keep an F3 stub at `/triage/:style_id/:id`.** Component `TriageDetailStub` renders the existing "Coming soon" `EmptyState` so row click does not 404. F3 replaces this component without touching the route registration. | F1 demonstrated EmptyState placeholders are fine in the live SPA. Eliminating the stub later is a one-file diff. |
| D16 | **localStorage key namespace `clouder.*`.** Specifically `clouder.lastTriageStyleId`. Independent from F1's `clouder.lastStyleId`. | Avoids categories ↔ triage navigation bleed. Same convention as F1 D16. |
| D17 | **Bundle additions: none.** `@mantine/dates`, `dayjs`, `zod`, `mantine-form-zod-resolver` are all installed (F1 + bootstrap). ISO-week computation uses `dayjs/plugin/isoWeek` (already shipped with `dayjs`). | Zero new dependencies in F2; bundle stays under 700 KB minified target. |
| D18 | **Empty states cover four cases.** (1) no styles — instructional EmptyState pointing at admin ingest (reuse F1 copy); (2) zero blocks in style on the active filter — CTA "Create first triage block" / "No finalized blocks yet" / "No blocks yet"; (3) no result on the All tab — same as (2); per-tab text. | Per design system § EmptyState. Copy in §10. |
| D19 | **One PR equivalent — direct merge to `main`.** Solo dev; branch `feat/triage-list-create` created in worktree, merged via `git merge --no-ff`, pushed to `origin main`. | Same delivery shape as F1 D12. Commits via `caveman:caveman-commit` skill (CLAUDE.md mandate). |

## 4. UI Surface

### 4.1 Routes

```
/triage
   └── TriageIndexRedirect              — no UI, redirect-only
/triage/:style_id
   └── TriageListPage                   — P-14
/triage/:style_id/:id
   └── TriageDetailStub                 — F3 placeholder (Coming soon EmptyState)
```

`/triage/:style_id` invalid UUID → 404 page (existing `RouteErrorBoundary`).
The legacy `frontend/src/routes/triage.tsx` placeholder is deleted; `routes/router.tsx` switches to the new feature folder.

### 4.2 TriageListPage (P-14)

Layout (desktop ≥ 64em):

```
[Page header]
  Title: "Triage"
  StyleSelector (Mantine Select, pinned right) — switches /triage/:style_id
  Primary CTA: <Button leftSection=<IconPlus>> New triage block </Button>

[Tabs]
  Active · {count}    Finalized · {count}    All · {count}
  (Mantine Tabs; counter shown only when total > 0; spinner placeholder until first page resolves)

[Body — per active tab]
  TriageBlocksList
    └── TriageBlockRow x N
          ├── Name (clickable → detail)
          ├── DateRangeText (mono "2026-04-20 → 2026-04-26")
          ├── track_count badge ("123 tracks")
          ├── RelativeTimeText (created_at on Active+All; finalized_at on Finalized)
          └── KebabMenu (Delete)
  LoadMoreButton — "Show more ({{remaining}} remaining)"

[EmptyState] (per tab when zero results)
  Active:    "No active triage blocks. Create one to start sorting this style's releases."
  Finalized: "No finalized blocks yet."
  All:       "No triage blocks yet for this style."
  CTA on Active + All: same Create button
```

Mobile (< 64em): primary CTA collapses to a sticky bottom bar `<Button fullWidth>`. Kebab moves into row-tail icon button. Tabs render full-width (Mantine `Tabs` defaults are responsive).

### 4.3 TriageDetailStub (F3 placeholder)

Renders existing `EmptyState` with `IconLayoutColumns` + title "Triage block — coming soon" + body "Block detail will land in F3."  Component file lives in `features/triage/routes/` so F3 replacement is purely additive.

### 4.4 Create form (P-15) — `<CreateTriageBlockDialog>`

Modal/Drawer body:

```
[Form]
  DatePickerInput
    label: "Window"
    description: "First and last release date covered by this block."
    type: "range"
    valueFormat: "YYYY-MM-DD"
    error: { from Zod (client) }
    autoFocus: true

  TextInput
    label: "Name"
    description: "Up to 128 characters."
    placeholder: "Tech House W17"
    error: { from Zod (client) }
    maxLength: 128 (UI hint, server is source of truth)
    onChange: marks userEditedName ref true on first keystroke

[Footer]
  Cancel | Create
```

Auto-suggest behaviour (D9):

```ts
// Pseudo
useEffect(() => {
  if (userEditedName.current) return
  if (!form.values.dateRange?.[0]) return
  const week = dayjs(form.values.dateRange[0]).isoWeek()
  form.setFieldValue('name', `${styleName} W${week}`, { validate: false })
}, [form.values.dateRange?.[0], styleName])
```

Submit:

- Client validation (Zod) runs first; if fail — inline errors, no API call.
- Spinner on Create CTA until 201 → close + invalidate `byStyle` for the active tab AND the `All` tab → toast `triage.toast.created`.
- 503 path (D11): close modal → yellow toast `triage.toast.create_pending` → schedule three invalidates at t=0, +15s, +30s. Each invalidate refetches all relevant tabs. After each refetch, look for a block whose `(name, date_from, date_to)` matches the submitted payload. First match → cancel pending timers → toast `triage.toast.create_eventually_succeeded`. After t=+30s with no match → toast `triage.toast.create_failed_to_confirm`.
- 422 `validation_error` → top-level form error (rare; client mirrors).
- Other 4xx / 5xx → toast `triage.toast.generic_error`.

The 503 detection logic lives in `useCreateTriageBlock` — it inspects the rejection error shape (apiClient throws an error with `status: 503` or `apiGwShape: true`) and switches branches.

### 4.5 Delete confirm

`modals.openConfirmModal({ title, children, labels, confirmProps })`:

```
Title: "Delete triage block?"
Children: "Delete '{{name}}'? Tracks already promoted to categories stay there. Tracks still in staging are removed."
labels: { confirm: "Delete", cancel: "Cancel" }
confirmProps: { color: "red" }
```

On confirm: spinner on confirm CTA until 204, then close + invalidate `byStyle` (all tabs of the current style) + toast `triage.toast.deleted`.

## 5. Component Catalog

| Component | Anatomy | Mantine base | Owner |
|---|---|---|---|
| `TriageIndexRedirect` | none — runs effect, returns `<Navigate>` | — | F2 |
| `TriageListPage` | Page header + StyleSelector + Tabs + List + EmptyState | `Stack`, `Group`, `Tabs` | F2 |
| `TriageDetailStub` | EmptyState placeholder | `EmptyState` (existing) | F2 |
| `StyleSelector` | Select with styles, controlled by URL `style_id` | `Select` | F1 → moved to shared |
| `TriageBlocksList` | Tabbed orchestrator + `useInfiniteQuery` per status + load-more | `Tabs.Panel`, `Stack`, `Button` | F2 |
| `TriageBlockRow` | Name link + date range + count badge + relative time + kebab | `Group`, `ActionIcon`, `Menu`, `Badge`, `Text` | F2 |
| `CreateTriageBlockDialog` | Mode-less form in Modal/Drawer | `Modal`, `Drawer`, `DatePickerInput`, `TextInput`, `Button` | F2 |
| `EmptyState` | Existing — reuse | — | reused |
| `RouteErrorBoundary` | Existing — reuse | — | reused |

`TriageBlockRow` does not need `useSortable` — DnD reorder is not part of triage (spec-D D14 makes bucket-types fixed; reorder of blocks themselves was never in scope).

## 6. Data Flow

### 6.1 React-query keys

```ts
['styles']                                                  // useStyles (reuse F1)
['triage', 'byStyle', styleId, status]                      // useTriageBlocksByStyle (status: 'IN_PROGRESS' | 'FINALIZED' | undefined)
['triage', 'detail', blockId]                               // reserved for F3, not used in F2
```

`'styles'` is invalidated on auth events. `'triage','byStyle'` invalidates after create / delete.

The status segment of the key produces three distinct caches per style — switching tabs is instant after first fetch.

### 6.2 Hooks (one file each under `hooks/`)

| Hook | Endpoint | Notes |
|---|---|---|
| `useStyles()` | `GET /styles` | Reuse F1's hook; do not duplicate. If F1's hook lives in `features/categories/hooks/`, extract to `frontend/src/hooks/useStyles.ts` alongside the `StyleSelector` move (D14). |
| `useTriageBlocksByStyle(styleId, status)` | `GET /styles/{styleId}/triage/blocks?status=&limit=50&offset=` | `useInfiniteQuery`; `getNextPageParam` from `offset + items.length` while `total > offset + items.length`. limit=50. `status` undefined → omit param (All tab). |
| `useCreateTriageBlock(styleId)` | `POST /triage/blocks` | Pessimistic. `onSuccess` invalidates `byStyle` for all 3 tabs of `styleId`. On 503 → schedules pending-recovery flow (D11). |
| `useDeleteTriageBlock(styleId)` | `DELETE /triage/blocks/{id}` | Pessimistic. `onSuccess` invalidates `byStyle` for all 3 tabs of `styleId`. |

### 6.3 Pending-recovery flow (`useCreateTriageBlock` 503 branch)

```ts
// Pseudocode
async function mutationFn(input) {
  try {
    return await apiClient.post('/triage/blocks', input)
  } catch (err) {
    if (isApiGwServiceUnavailable(err)) {
      schedulePendingRecovery({ styleId, payload: input })
      throw new PendingCreateError() // distinct error so onError shows the yellow toast
    }
    throw err
  }
}

function schedulePendingRecovery({ styleId, payload }) {
  const matcher = (block) =>
    block.name === payload.name &&
    block.date_from === payload.date_from &&
    block.date_to === payload.date_to
  const tickAt = [0, 15_000, 30_000]
  let resolved = false
  tickAt.forEach((delay, idx) => {
    setTimeout(async () => {
      if (resolved) return
      const result = await refetchAllTabs(styleId)
      const found = result.some((page) => page.items.some(matcher))
      if (found) {
        resolved = true
        notifications.show({ message: t('triage.toast.create_eventually_succeeded'), color: 'green' })
      } else if (idx === tickAt.length - 1) {
        notifications.show({ message: t('triage.toast.create_failed_to_confirm'), color: 'red' })
      }
    }, delay)
  })
}
```

Recovery is fire-and-forget at the hook level (timers stored in a module-scoped `Map<string, Timeout[]>` keyed by request id, cleared if a subsequent successful create with the same payload races in). On unmount of the page, the timers continue — they are cheap and the user might switch tabs.

### 6.4 Style switching

`StyleSelector.onChange(newStyleId)` (per-feature wrapper):

1. `localStorage.setItem('clouder.lastTriageStyleId', newStyleId)`
2. `navigate('/triage/' + newStyleId)`

`TriageIndexRedirect`:

```tsx
function TriageIndexRedirect() {
  const { data: styles, isLoading } = useStyles()
  if (isLoading) return <FullScreenLoader/>
  if (!styles?.items?.length) return <NoStylesEmptyState/>
  const last = localStorage.getItem('clouder.lastTriageStyleId')
  const target = styles.items.find(s => s.id === last)?.id ?? styles.items[0].id
  return <Navigate to={`/triage/${target}`} replace/>
}
```

### 6.5 Tab counters

The `Active` and `Finalized` counters consume the `total` field from the first page of each respective `useInfiniteQuery`. The `All` counter is `Active + Finalized` derived in the page (avoids a third request). On tabs that have not been visited yet, counter renders a Mantine `<Loader size="xs" />` until the first page lands. Cache `staleTime: 30s` prevents tab clicks from re-fetching unnecessarily.

## 7. Validation

### 7.1 Zod schemas (`lib/triageSchemas.ts`)

```ts
const CONTROL_CHARS = /[\x00-\x1f\x7f-\x9f]/
export const triageNameSchema = z
  .string()
  .trim()
  .min(1, 'name_required')
  .max(128, 'name_too_long')
  .refine(s => !CONTROL_CHARS.test(s), 'name_control_chars')

export const triageDateRangeSchema = z
  .tuple([z.date(), z.date()])
  .refine(([from, to]) => to >= from, 'date_range_invalid')

export const createTriageBlockSchema = z.object({
  name: triageNameSchema,
  dateRange: triageDateRangeSchema,
})
```

Error keys map to i18n in §10.

### 7.2 Form integration

```ts
import { useForm } from '@mantine/form'
import { zodResolver } from 'mantine-form-zod-resolver'

const form = useForm({
  initialValues: { name: '', dateRange: [null, null] as [Date|null, Date|null] },
  validate: zodResolver(createTriageBlockSchema),
})
```

DateRange field renders inline `date_range_invalid` under the `DatePickerInput` if `to < from`.

The submission marshals `dateRange` to `{ date_from: dayjs(from).format('YYYY-MM-DD'), date_to: dayjs(to).format('YYYY-MM-DD') }` for the POST body.

## 8. Error UX Mapping

| Code | Origin | UX |
|---|---|---|
| `validation_error` (422) | create / delete | Inline form error (top-level message). Should not happen in practice (client mirrors server). |
| `style_not_found` (404) | list / create | Page-level not-found UI. Should be unreachable: `StyleSelector` only offers existing styles. |
| `triage_block_not_found` (404) | delete | Toast `triage.toast.delete_not_found` + invalidate `byStyle` (raced with another tab; spec-D §5.10 returns 404 for already-soft-deleted rows too). |
| `unauthorized` (401) | any | AuthProvider redirects to `/login`. |
| 503 `Service Unavailable` (API GW envelope) | create | D11 pending-recovery flow (yellow toast + auto-invalidate at 0/15/30s). |
| 503 `Service Unavailable` | delete | Existing `apiClient` cold-start retry; terminal 503 → toast `errors.network` + invalidate. |
| Network failure | any | Existing toast pattern (`errors.network`). |

Toasts use `@mantine/notifications` (top-right inherited from A2).

## 9. Code Layout

### 9.1 New files

```
frontend/src/features/triage/
├── routes/
│   ├── TriageIndexRedirect.tsx
│   ├── TriageListPage.tsx
│   └── TriageDetailStub.tsx
├── components/
│   ├── TriageBlocksList.tsx
│   ├── TriageBlockRow.tsx
│   └── CreateTriageBlockDialog.tsx
├── hooks/
│   ├── useTriageBlocksByStyle.ts
│   ├── useCreateTriageBlock.ts
│   └── useDeleteTriageBlock.ts
├── lib/
│   ├── triageSchemas.ts
│   ├── isoWeek.ts                    # tiny dayjs.isoWeek wrapper
│   ├── lastVisitedTriageStyle.ts
│   └── pendingCreateRecovery.ts      # exported helper used by useCreateTriageBlock
└── index.ts
```

### 9.2 Refactor — extract shared

```
frontend/src/components/StyleSelector.tsx            # moved from features/categories/components/
frontend/src/components/__tests__/StyleSelector.test.tsx   # moved alongside
frontend/src/hooks/useStyles.ts                      # moved from features/categories/hooks/
frontend/src/hooks/__tests__/useStyles.test.ts       # moved alongside
```

Update F1 imports:

- `features/categories/routes/CategoriesIndexRedirect.tsx`
- `features/categories/routes/CategoriesListPage.tsx`

The move is mechanical — files relocated, imports rewritten. No behaviour change. F1 tests stay green.

### 9.3 Modified files

- `frontend/src/routes/router.tsx` — register the three new triage routes; remove import of placeholder `triage.tsx`.
- `frontend/src/routes/triage.tsx` — **deleted** (placeholder no longer needed).
- `frontend/src/i18n/en.json` — add `triage.*` namespace (keys in §10).
- F1 imports for `StyleSelector` and `useStyles` (D14 refactor).

### 9.4 No backend changes

Confirmed: spec-D ships all 4 endpoints F2 needs. `pnpm api:types` does not need to be re-run; `frontend/src/api/schema.d.ts` already includes them after the F1 round.

## 10. i18n Keys

Add under `frontend/src/i18n/en.json` (mirror existing structure; RU lands in iter-2b):

```json
{
  "triage": {
    "page_title": "Triage",
    "create_cta": "New triage block",
    "loading": "Loading triage blocks…",
    "track_count_one": "{{count}} track",
    "track_count_other": "{{count}} tracks",
    "tabs": {
      "active": "Active",
      "finalized": "Finalized",
      "all": "All",
      "counter": "{{label}} · {{count}}"
    },
    "row": {
      "date_range": "{{from}} → {{to}}",
      "menu": { "delete": "Delete" }
    },
    "form": {
      "create_title": "New triage block",
      "name_label": "Name",
      "name_description": "Up to 128 characters.",
      "name_placeholder": "Tech House W17",
      "date_range_label": "Window",
      "date_range_description": "First and last release date covered by this block.",
      "date_range_placeholder": "Pick range",
      "create_submit": "Create",
      "cancel": "Cancel"
    },
    "delete_modal": {
      "title": "Delete triage block?",
      "body": "Delete '{{name}}'? Tracks already promoted to categories stay there. Tracks still in staging are removed.",
      "confirm": "Delete",
      "cancel": "Cancel"
    },
    "toast": {
      "created": "Triage block created.",
      "deleted": "Triage block deleted.",
      "create_pending": "Creation is taking longer than usual. We'll refresh the list automatically.",
      "create_eventually_succeeded": "Triage block created (it took a moment).",
      "create_failed_to_confirm": "Couldn't confirm creation. Please refresh and try again.",
      "delete_not_found": "Block already deleted elsewhere.",
      "generic_error": "Something went wrong. Please retry."
    },
    "errors": {
      "name_required": "Name is required.",
      "name_too_long": "Name must be 128 characters or less.",
      "name_control_chars": "Name contains forbidden characters.",
      "date_range_required": "Pick a date range.",
      "date_range_invalid": "End date must be on or after start date."
    },
    "empty_state": {
      "no_active_title": "No active triage blocks",
      "no_active_body": "Create one to start sorting this style's releases.",
      "no_finalized_title": "No finalized blocks yet",
      "no_finalized_body": "Finalize a block to see it here.",
      "no_blocks_title": "No triage blocks yet",
      "no_blocks_body": "Create your first block for {{style_name}}."
    }
  }
}
```

Pluralisation uses i18next ICU (`_one` / `_other`).

Domain terms `BPM`, `Length`, `NEW`/`OLD`/`NOT`/`DISCARD`/`UNCLASSIFIED`/`FINALIZED` stay literal per CLAUDE.md memory.

## 11. Testing

### 11.1 Unit (Vitest + Testing Library)

`features/triage/lib/__tests__/triageSchemas.test.ts`:

- Empty / whitespace-only / 129-char / 128-char / control-chars all behave per Zod rules.
- `triageDateRangeSchema` rejects `to < from`; accepts `to == from`.
- `createTriageBlockSchema` round-trips a valid input.

`features/triage/lib/__tests__/isoWeek.test.ts`:

- 2026-04-20 (Monday) → ISO week 17.
- 2026-01-01 (Thursday) → ISO week 1 (year boundary).
- 2025-12-29 (Monday) → ISO week 1 of 2026.
- 2024-12-30 (Monday) → ISO week 1 of 2025.

`features/triage/lib/__tests__/lastVisitedTriageStyle.test.ts`:

- Read returns `null` when unset; write+read round-trip; doesn't collide with `clouder.lastStyleId`.

`features/triage/components/__tests__/TriageBlockRow.test.tsx`:

- Renders name, date range, count badge, relative time, kebab.
- Click on name → `<Link>` navigates to detail.
- Kebab → Delete opens confirm modal.
- Finalized variant shows `finalized_at` instead of `created_at`.

`features/triage/components/__tests__/CreateTriageBlockDialog.test.tsx`:

- Empty submit → both inline errors (`name_required`, `date_range_required`).
- 129-char name → `name_too_long`.
- Invalid range (to < from) → `date_range_invalid`.
- **Auto-suggest**: pick range starting `2026-04-20` → name input fills with `"<Style> W17"`.
- **Auto-suggest preserved on user edit**: type into name → change date range → name not overwritten.
- 503 path: mock create rejection → modal closes, yellow toast visible.

`features/triage/hooks/__tests__/useTriageBlocksByStyle.test.tsx`:

- First page renders with `total` and `items`. Next page button hidden when `total ≤ shown`.
- Status segment changes the cache key (two parallel observers on the same style do not interfere).

`features/triage/hooks/__tests__/useCreateTriageBlock.test.tsx`:

- Happy 201 → `byStyle` cache invalidated for all 3 tabs.
- 503 path: schedules three timers; first refetch finds matching block → green toast.
- 503 path: timer 3 with no match → red toast.
- 503 path: page unmount → timers still fire (no leak crash).

`features/triage/hooks/__tests__/useDeleteTriageBlock.test.tsx`:

- 204 → invalidates all 3 tabs.
- 404 `triage_block_not_found` → toast `triage.toast.delete_not_found` + invalidate.

### 11.2 Integration (Vitest + MSW)

`features/triage/__tests__/TriageListPage.integration.test.tsx`:

1. **Index redirect → first style.** No localStorage → land on first style. With localStorage → land on stored style.
2. **Tabs render with counters.** Mock 2 active + 1 finalized → `Active · 2` and `Finalized · 1` and `All · 3`. Click Finalized → list switches to the 1 finalized block.
3. **Create happy.** Click Create → form opens → pick range → name auto-fills → submit → list updates with new block on Active tab and All tab. Switch tab → cached.
4. **Create 503 eventual success.** Mock POST → 503; subsequent GET (after auto-invalidate) → list now contains the block (background-completed). Yellow toast then green toast. Modal closed throughout.
5. **Create 503 terminal failure.** Mock POST → 503; subsequent GETs never include the block. Red toast at t=+30s.
6. **Delete confirm + invalidate.** Click kebab → Delete → confirm → row removed from all tabs.
7. **Empty states (per tab).** Active tab with zero results → `no_active_*`. Finalized tab with zero → `no_finalized_*`. All tab with zero → `no_blocks_*`.
8. **No styles.** `useStyles` returns `{items: []}` → `no_styles` empty state (reuse F1 copy).

`features/triage/__tests__/TriageRouting.integration.test.tsx`:

1. **Detail stub.** Navigate to `/triage/{style}/{id}` → renders `TriageDetailStub` placeholder (Coming soon EmptyState).
2. **Style switch via selector.** Change `StyleSelector` → URL + localStorage update; list refetches for new style.

### 11.3 No E2E

Playwright (CC-2) deferred per roadmap. Manual smoke before merge:

1. Sign in.
2. `Triage` sidebar → land on style.
3. Create block (happy path against deployed prod API).
4. Open detail → confirm stub renders.
5. Delete block.
6. Switch styles via selector → URL + localStorage update.
7. Refresh page → land on same style.
8. Manually trigger 503 (dev fallback: stop Vite proxy briefly, attempt create; or rely on Aurora cold-start after 5min idle if `min_acu=0` still applies).

### 11.4 Coverage

No numeric gate. Every hook has at least one unit test; every page has at least one happy-path integration test; every documented error UX branch (D11, D12, §8) has at least one test.

## 12. Delivery

1. Branch `feat/triage-list-create` created from `main` in worktree `.claude/worktrees/f2_task` (already created).
2. Sequential commits per natural boundary:
   - StyleSelector + useStyles refactor (move to shared)
   - hooks scaffold
   - components scaffold (Row, List, Dialog)
   - routes (Index redirect, ListPage, DetailStub)
   - i18n keys
   - tests
   Each commit message produced by `caveman:caveman-commit`.
3. `pnpm test` green, `pnpm build` green.
4. `pnpm dev` manual smoke against deployed prod API.
5. `git checkout main && git merge feat/triage-list-create --no-ff`.
6. `git push origin main` (TD-6 branch protection still not configured).
7. Roadmap update: append F2 lessons section, mark F2 row shipped.

CI runs on push to `main` and validates the merge commit.

## 13. Open Items, Edge Cases, Future Flags

### 13.1 Edge cases worth a comment

- **Style deleted server-side while user has it in localStorage.** `TriageIndexRedirect` falls back to first style; no error. Same as F1.
- **All styles deleted while page open.** `useStyles` returns empty list → `NoStylesEmptyState` (rare).
- **503 timers across navigation.** Pending-recovery timers fire even if the user navigates away from the triage page; the toast appears wherever the user currently is (notification system is global). Acceptable — the user explicitly initiated a create and benefits from the late confirmation.
- **Browser refresh during pending recovery.** Timers are lost (in-memory only). No silent duplicate; on refresh `byStyle` is fresh. If the block was eventually created, the user sees it; if not, they retry. Documented as acceptable.
- **Two parallel creates with identical `(name, date_from, date_to)`.** Possible if user double-clicks Create in fast succession (D7 pessimistic does not block double-submit if button is not disabled — implementation MUST disable on submit). Test covers.
- **ISO week year boundary.** `dayjs.isoWeek()` returns the ISO week number which can belong to the previous or next calendar year — name is just a label; no logic depends on parsing the week back to a date range.

### 13.2 Future flags (post-iter-2a)

- **`FUTURE-F2-1`** — cross-style flat list at `/triage`. Re-uses `GET /triage/blocks`. Lands when Home (F8) needs the data shape or user testing reveals demand.
- **`FUTURE-F2-2`** — search / sort / additional filters on the list. Lands when block counts grow.
- **`FUTURE-F2-3`** — block rename. Backend endpoint not yet exposed; would require a spec-D follow-up.
- **`FUTURE-F2-4`** — bulk-create (one POST per style covering N windows). Backend not exposed.
- **`FUTURE-F2-5`** — undo for soft-delete. Backend `FUTURE-D5` first; UI then exposes "Recently deleted" list.
- **`FUTURE-F2-6`** — pre-create count preview ("This window contains N tracks across X categories"). Backend would need a count-only endpoint or expensive client-side compute. Defer until UX feedback motivates it.

### 13.3 Cross-ticket dependencies

- **F3 Triage detail** replaces `TriageDetailStub` with the real page. Imports `useTriageBlocksByStyle` cache implicitly (invalidates from F3 mutations cascade). No prop contract needed.
- **F4 Finalize** invalidates `triage.byStyle` after `POST /triage/blocks/{id}/finalize` flips status. F4 hook responsibility.
- **F5 Curate** consumes block detail (F3) — does not depend on F2 directly.
- **F8 Home** may want a triage block summary tile — `useTriageBlocksByStyle` exists; can be extended to a cross-style hook later.

## 14. Acceptance Criteria

- All routes (§4.1) resolve; index redirect lands on last/first style.
- `StyleSelector` (now shared) switches styles via Select; URL + localStorage update.
- Tabs `Active | Finalized | All` render with counters; switching tabs is instant after first fetch.
- List renders in `created_at DESC` order; load-more pagination works on each tab.
- Create form auto-suggests `<style> W<isoWeek>`; preserves user edits.
- Create form validates per Zod (§7.1); 422 maps to inline error; 201 closes form + invalidates cache + green toast.
- 503 cold-start UX: yellow toast on close → eventual green toast (if block appears) or red toast (if not) at t=+30s.
- Delete confirm via `modals.openConfirmModal` → 204 → row removed from all tabs.
- All four empty states covered (D18).
- F1 still green after `StyleSelector` + `useStyles` move (no behaviour change).
- `pnpm test` green (≥ 110 tests passing — F1 baseline 91 + new ~20).
- `pnpm build` produces under 700 KB minified bundle (no new deps, target unchanged).
- Manual smoke (§11.3) green against deployed prod API.

## 15. References

- Roadmap: [`2026-05-01-frontend-iter-2a-roadmap.md`](../plans/2026-05-01-frontend-iter-2a-roadmap.md) — ticket F2.
- Backend prereq: [`2026-04-28-spec-D-triage-design.md`](./2026-04-28-spec-D-triage-design.md).
- F1 prereq: [`2026-05-01-F1-categories-frontend-design.md`](./2026-05-01-F1-categories-frontend-design.md).
- Frontend bootstrap: [`2026-04-30-frontend-bootstrap-design.md`](./2026-04-30-frontend-bootstrap-design.md).
- Pages catalog Pass 1: `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` — P-14 (BlocksList), P-15 (CreateBlock).
- Component spec sheet: `docs/design_handoff/04 Component spec sheet.html`.
- Open questions: `docs/design_handoff/OPEN_QUESTIONS.md` — Q3 (DateRangeField).
- Tokens: `docs/design_handoff/tokens.css`, `frontend/src/tokens.css`, `frontend/src/theme.ts`.

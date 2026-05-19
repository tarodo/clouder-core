# Label Frontend Design

**Date:** 2026-05-19
**Branch:** `worktree-collect_info` (worktree of `main`)
**Scope:** Frontend only — three surfaces consuming the label-enrichment backend shipped in PRs #82–#90. Includes the backend additions strictly required to feed these surfaces (list/backlog/runs/user-detail endpoints + `label_id` on triage track payload).
**Out of scope:** Artist enrichment (UI shell prepares for it; data layer absent). Mobile triage tile (deferred — desktop only). Favorites/bookmarking. Notable-artists drill-down.

## Goal

Expose the enriched label data already stored in `clouder_label_info` through three independent UI surfaces:

- **Library** — public-auth catalog letting any logged-in user browse labels by style and read enriched detail.
- **Admin enrichment dashboard** — admin tool for finding labels with no info, batch-enqueuing enrichment, and inspecting run results as raw JSON.
- **Triage player tile** — compact label-info card next to the desktop triage player, shown when the current track's label has completed enrichment.

All three reuse one TypeScript type tree (`LabelInfo`, `LabelEnrichmentRun`, `LabelSummary`) generated from `frontend/src/api/schema.d.ts` after backend regeneration.

## Architecture

**Single feature folder for user-facing surface:** `frontend/src/features/library/` owns Library routes and the reusable `LabelTile` component. Triage imports `LabelTile` directly — no duplicate code path. Admin enrichment pages live under `frontend/src/features/admin/` next to the existing coverage / spotify-not-found pages, sharing the Mantine `Tabs`-based `AdminLayout`.

**Data flow:**
```
schema.d.ts (generated)
  → frontend/src/api/labels.ts (typed thin wrappers)
    → features/library/hooks/* (user-facing queries)
    → features/admin/hooks/* (admin queries + mutations)
      → routes / components (presentational)
```

**Routing root `/library`** — entity-agnostic. Detail-page shell is split into a generic `<EntityDetailLayout>` (header + tab strip + sidebar slots) consumed today by `LabelDetailPage` and tomorrow by `ArtistDetailPage` with no shell rewrite. Tabs `<EntityTabs>` (Labels / Artists) render at the index level with Artists disabled-with-tooltip in v1.

**State:** TanStack Query handles all server state. No global label store. URL is single source of truth for current style / filters / pagination cursor. Selection state (admin backlog checkboxes) lives in a single page-scoped `useState<Set<labelId>>` — no Redux/Zustand.

## Tech Stack

- React 19, TypeScript, Vite (existing)
- Mantine 9 components — `Card`, `Tabs`, `Table`, `Drawer`, `Pagination`, `Combobox`, `Code`, `Tooltip`, `Skeleton`, `Badge` (no new dependencies)
- TanStack Query 5 (existing)
- React Router 7 (existing)
- i18next for all user-visible strings (existing)
- `@tabler/icons-react` (existing) for channel icons

## Backend prerequisites

The following must be added to backend before frontend work begins. Each is small (single route, no new tables).

### B1. Add `label_id` to triage `BucketTrack` payload

**File:** `src/collector/handler.py` — triage bucket-tracks query.
**Change:** join `clouder_labels` on `tracks.label_id`, expose `label_id: str | null` on the response item.
**FE consumer:** `useBucketTracks` adds `label_id: string | null` to `BucketTrack` interface; triage tile reads it.

### B2. `GET /labels` — user-facing list

```
GET /labels?style=drum-and-bass&q=fokuz&cursor=opaque&limit=50
→ 200 { items: LabelSummary[], next_cursor: string | null }
```

`LabelSummary` shape:
```typescript
{
  id: string;
  name: string;
  style: string;
  status: 'none' | 'queued' | 'running' | 'completed' | 'failed' | 'outdated';
  // present iff status === 'completed':
  info: {
    tagline: string | null;
    country: string | null;
    primary_styles: string[];
    activity: 'unknown' | 'dormant' | 'low' | 'steady' | 'high' | 'fire_hose';
    updated_at: string;  // ISO
  } | null;
}
```

Auth: any logged-in user. Sort: `name ASC` default; `?sort=recent` sorts by `info.updated_at DESC`. Empty `style` returns all styles; `q` is case-insensitive prefix match on `name`.

### B3. `GET /labels/{label_id}` — user-facing detail

```
GET /labels/{label_id}
→ 200 LabelDetail
→ 404 { error: 'label_not_found' }
```

`LabelDetail` is the `LabelInfo` schema (see `src/collector/label_enrichment/schemas.py`) **minus admin-only fields** (`run_id`, `prompt_version`, `prompt_slug`, `vendors_used`, `merged_at_run_id`, `token_cost`, `provenance`). All scalar info fields + URL channels + `notable_artists` + `primary_styles` + `secondary_styles` + `ai_content` + `ai_reasoning` + `tagline` + `summary` stay. The user-facing route reads from `clouder_label_info` directly.

Auth: any logged-in user. If `status != 'completed'`, return 404 (no partial reads).

### B4. `GET /admin/labels/backlog` — admin

```
GET /admin/labels/backlog?style=drum-and-bass&status=none&cursor=&limit=100
→ 200 { items: BacklogLabel[], next_cursor: string | null, total_estimate: number }
```

`BacklogLabel` shape:
```typescript
{
  id: string;
  name: string;
  style: string;
  status: 'none' | 'failed' | 'outdated';
  track_count: number;     // # tracks referencing this label (selection priority hint)
  last_attempted_at: string | null;  // ISO; null when status === 'none'
}
```

"Backlog" = labels with **no `clouder_label_info` row** (`status='none'`) OR row with `status='failed'` OR `status='completed'` and `updated_at` older than the configured staleness threshold (rename status to `'outdated'` in response). `completed` and `queued` and `running` are excluded.

Auth: admin only.

### B5. `GET /admin/labels/enrich-runs` — admin

```
GET /admin/labels/enrich-runs?status=completed&cursor=&limit=50
→ 200 { items: RunSummary[], next_cursor: string | null }
```

`RunSummary` shape mirrors the existing `GET /admin/labels/enrich-runs/{run_id}` response minus the per-cell expansion. Sort: `created_at DESC`. Auth: admin only.

### B6. Expand `GET /admin/labels/enrich-runs/{run_id}` with `cells[]`

Existing response keeps all current fields; add:
```typescript
cells: {
  cell_id: string;
  label_id: string;
  label_name: string;
  vendor: 'gemini' | 'openai' | 'tavily_deepseek' | 'deepseek';
  status: 'ok' | 'error';
  latency_ms: number;
  cost_usd: number;
  error_message: string | null;
}[]
```

Read from `clouder_label_enrichment_cells WHERE run_id = $1`. No pagination — runs are capped at 100 labels × ~4 vendors = max ~400 cells.

### B7. `GET /admin/labels/enrich/options` — admin

```
GET /admin/labels/enrich/options
→ 200 {
  vendors: ['gemini', 'openai', 'tavily_deepseek'],
  prompt_versions: [{ slug: 'label_v3_app_fields', version: '1.0.0', is_default: true }, ...],
  default_models: { gemini: 'gemini-2.5-pro', openai: 'gpt-5.1', tavily_deepseek: 'deepseek-chat' },
  merge: { vendor: 'deepseek', default_model: 'deepseek-chat' }
}
```

Static config baked from backend constants in `src/collector/label_enrichment/prompts/registry.py` and `vendors/pricing.py`. Auth: admin only. Frontend uses this to populate the enqueue drawer pickers — no hardcoded vendor / version lists in FE.

---

## Surface 1 — Library (user-facing label browser)

### Routes

```
/library                                     → redirect to /library/<defaultStyle>
/library/:styleId                            → LibraryListPage (Labels tab active)
/library/:styleId/labels/:labelId            → LabelDetailPage
/library/:styleId/artists/:artistId          → reserved, not implemented v1
```

`defaultStyle` follows the same convention as `/categories` (currently `drum-and-bass`).

### Components

```
features/library/
├── routes/
│   ├── LibraryIndexRedirect.tsx
│   ├── LibraryListPage.tsx
│   └── LabelDetailPage.tsx
├── components/
│   ├── EntityTabs.tsx              # Labels (active) | Artists (disabled tooltip)
│   ├── LibraryFilters.tsx          # style picker + search + sort
│   ├── LabelCard.tsx               # grid item
│   ├── LabelListGrid.tsx           # cards grid + infinite scroll
│   ├── EntityDetailLayout.tsx      # generic header/tabs/sidebar shell
│   ├── LabelDetailHeader.tsx       # name, country, founded year, status
│   ├── LabelChannelLinks.tsx       # icon row of all label.*_url channels
│   ├── LabelOverviewTab.tsx        # tagline, summary, notable_artists
│   ├── LabelStylesTab.tsx          # primary/secondary styles + ai_content
│   └── LabelTile.tsx               # compact card (also used by triage)
├── hooks/
│   ├── useLabelsList.ts
│   ├── useLabelDetail.ts
│   └── useLabelInfo.ts             # used by triage tile; cache-key independent
└── lib/
    ├── channelMeta.ts              # icon + display name per URL channel
    ├── countryFlag.ts              # ISO-2 → emoji flag
    └── formatLabel.ts              # tagline truncate, activity badge text
```

### List page (`/library/:styleId`)

**Layout:**

```
┌─────────────────────────────────────────────────────────────────┐
│ EntityTabs                       [Labels ●] [Artists (soon)]    │
├─────────────────────────────────────────────────────────────────┤
│ LibraryFilters                                                  │
│   [Style: drum-and-bass ▾]  [Search: ____ ]  [Sort: A→Z ▾]      │
├─────────────────────────────────────────────────────────────────┤
│ LabelListGrid (responsive: 1 col mobile, 2 tablet, 3 desktop)   │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐                       │
│   │ Card     │ │ Card     │ │ Card     │                       │
│   └──────────┘ └──────────┘ └──────────┘                       │
│   ...                                                           │
│   [Load more]   (or infinite scroll on desktop)                 │
└─────────────────────────────────────────────────────────────────┘
```

**`LabelCard` content:**
- Top row: country flag + label name (bold) + activity badge (only if `info.activity !== 'unknown'`)
- Tagline (2-line clamp; `info.tagline ?? 'No description yet.'`)
- Primary styles as Mantine `Badge` row (max 3 visible + "+N" overflow)
- If `status !== 'completed'`: grey "Info pending" pill instead of tagline + styles
- Card click → navigate to detail; `Card` has cursor pointer + hover elevation

**Filter behavior:**
- `styleId` is in the URL — changing it via the picker is `navigate('/library/<newStyle>')`
- `q` and `sort` are URL search params (`?q=fokuz&sort=recent`) so back/forward preserves state
- Search input debounced 250ms before pushing to URL

**Pagination:** TanStack `useInfiniteQuery` with `next_cursor`. Desktop (`>=1024px`) triggers `fetchNextPage` on intersection of sentinel; below that a `<Pagination>` "Load more" button.

**Empty / error states:**
- No results for filter → "No labels match these filters."
- API 5xx → existing `RouteErrorBoundary` fallback
- Loading: 6 `<Skeleton>` cards

### Detail page (`/library/:styleId/labels/:labelId`)

**Layout (desktop ≥1024px):**

```
┌────────────────────────────────────────────────────┬──────────┐
│ LabelDetailHeader                                  │ Sidebar  │
│   ← Back to drum-and-bass                          │ Channels │
│   Fokuz Recordings                  [Active]       │  · Web   │
│   🇳🇱 Rotterdam · Founded 1999                      │  · SC    │
├────────────────────────────────────────────────────┤  · BC    │
│ [ Overview ] [ Styles ]                            │  · BP    │
├────────────────────────────────────────────────────┤  · IG    │
│ Overview tab (default):                            │  · Tw    │
│   Tagline                                          │  ...     │
│   Summary (markdown render of `info.summary`)      │          │
│   Notable artists: [chip] [chip] [chip] ...        │          │
│                                                    │          │
│ Styles tab:                                        │          │
│   Primary: [chip] [chip] [chip]                    │          │
│   Secondary: [chip] [chip] [chip]                  │          │
│   AI content: [Badge: none_detected ✓]             │          │
│   AI reasoning (collapsed by default)              │          │
└────────────────────────────────────────────────────┴──────────┘
```

**Layout (mobile <768px):**
- Sidebar collapses to a third tab "Links" (icon row in tab content)
- Single column, tabs become a vertical Mantine `Tabs.List` at top

**`LabelChannelLinks`:**

Iterates over `channelMeta` array which defines display order: website, bandcamp, soundcloud, beatport, residentadvisor, discogs, instagram, twitter. Each rendered as Mantine `ActionIcon` with `<Tooltip>`. Hidden channels (URL is `null`) are skipped (not greyed out).

**Markdown rendering:**

`info.summary` is plain text from backend. v1 renders it inside `<Text component="p">` with `style={{ whiteSpace: 'pre-wrap' }}` — no markdown library added. If backend later emits markdown, add `react-markdown` in a follow-up (out of scope here).

**Empty / error states:**
- `404` from API → "Information for this label hasn't been collected yet." + (admin only, gated via `getAuthSnapshot().user.is_admin` — same check as `requireAdmin` loader) button "Enqueue enrichment" that opens the admin drawer pre-filled with this label
- `5xx` → `RouteErrorBoundary`
- `notable_artists` empty → hide that section (no header)
- Inactive label (`status === 'inactive'`) → "Inactive" badge in header instead of "Active"

### Hooks

```typescript
// useLabelsList.ts
export function useLabelsList(params: {
  styleId: string;
  q: string;
  sort: 'name' | 'recent';
}) {
  return useInfiniteQuery({
    queryKey: ['library', 'labels', params],
    queryFn: ({ pageParam }) => api(`/labels?style=${params.styleId}&q=${params.q}&sort=${params.sort}&cursor=${pageParam ?? ''}`),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
}

// useLabelDetail.ts
export function useLabelDetail(labelId: string | null) {
  return useQuery({
    queryKey: ['library', 'labelDetail', labelId],
    queryFn: () => api(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
  });
}

// useLabelInfo.ts — used by triage tile; thinner than useLabelDetail
export function useLabelInfo(labelId: string | null | undefined) {
  return useQuery({
    queryKey: ['labelInfo', labelId],
    queryFn: () => api(`/labels/${labelId}`),
    enabled: !!labelId,
    staleTime: 5 * 60_000,
    retry: (count, err) => count < 1 && !is404(err),
  });
}
```

`useLabelDetail` and `useLabelInfo` hit the same endpoint but use **different cache keys** so they don't fight: the library detail page should stay subscribed even when the triage tile invalidates, and vice versa.

---

## Surface 2 — Admin enrichment dashboard

### Routes

```
/admin/labels/enrich                         → AdminEnrichmentBacklogPage
/admin/labels/enrich/runs                    → AdminEnrichmentRunsPage
/admin/labels/enrich/runs/:runId             → AdminEnrichmentRunDetailPage
```

`AdminLayout.tsx` `TAB_VALUES` extended to include `/admin/labels/enrich` and `/admin/labels/enrich/runs`. Run-detail page renders inside the same layout (it inherits the parent tab as active).

### Components

```
features/admin/components/enrichment/
├── BacklogTable.tsx
├── BacklogToolbar.tsx              # filters + selection summary
├── EnqueueDrawer.tsx               # vendor + prompt + model picker, submit
├── RunsTable.tsx
├── RunStatusBadge.tsx
├── RunDetailHeader.tsx
├── RunDetailCellsTable.tsx
└── RunJsonViewer.tsx               # raw GET response + copy button

features/admin/hooks/
├── useLabelBacklog.ts
├── useEnrichmentRuns.ts
├── useEnrichmentRunDetail.ts
├── useEnrichmentOptions.ts
└── useEnqueueEnrichment.ts         # mutation; invalidates backlog + runs lists

features/admin/routes/
├── AdminEnrichmentBacklogPage.tsx
├── AdminEnrichmentRunsPage.tsx
└── AdminEnrichmentRunDetailPage.tsx
```

### Backlog page (`/admin/labels/enrich`)

**Layout:**

```
┌─────────────────────────────────────────────────────────────────┐
│ BacklogToolbar                                                  │
│   [Style: all ▾] [Status: all ▾]  Selected: 0    [Enqueue …]   │
├─────────────────────────────────────────────────────────────────┤
│ BacklogTable                                                    │
│  ☐ Name         Style          Status    Tracks   Last try     │
│  ☐ Fokuz Rec.   drum-and-bass  none      142      —             │
│  ☐ V.I.M. Rec.  drum-and-bass  failed    18       2026-05-12   │
│  ...                                                            │
│                                       [Load more]               │
└─────────────────────────────────────────────────────────────────┘
```

- Header checkbox: toggles all rows on **current page** (not all results — explicit, no surprise)
- Row click navigates to the user-facing detail (`/library/<style>/labels/<id>`) so admin can verify state visually
- Action button enabled only when selection > 0; label dynamically reads "Enqueue 23 labels"
- Sorting: status badge color (none = grey, failed = red, outdated = yellow)

**EnqueueDrawer** (Mantine `Drawer` from right):
- Title: "Enqueue N labels for enrichment"
- Form fields (populated from `useEnrichmentOptions`):
  - Vendors: Multi-select checkboxes, all 3 enabled by default
  - Prompt version: Combobox, default = `is_default: true` from options
  - Models per vendor: editable text input next to each vendor row, defaulted from options
  - Merge vendor: shown as readonly Badge "deepseek"
  - Merge model: text input defaulted from options
- Submit calls `useEnqueueEnrichment` with the assembled `POST /admin/labels/enrich` body
- On 202 success: close drawer, show success notification with link to `/admin/labels/enrich/runs/<run_id>`, clear selection, invalidate `useLabelBacklog`
- On 4xx/5xx error: show error notification with message from `error.detail`, keep drawer open

### Runs list page (`/admin/labels/enrich/runs`)

**Layout:**

```
┌─────────────────────────────────────────────────────────────────┐
│ Status filter: [All ▾]                                          │
├─────────────────────────────────────────────────────────────────┤
│ RunsTable                                                       │
│   Created          Run id    Status     Cells (ok/err/tot) Cost │
│   2026-05-19 14:22 a045c…    completed  3/0/3              $0.02│
│   2026-05-19 13:01 b1c2d…    failed     12/5/17            $0.08│
│   ...                                                           │
│                                       [Load more]               │
└─────────────────────────────────────────────────────────────────┘
```

- Row click → `/admin/labels/enrich/runs/<run_id>`
- Run-id column displays first 8 chars + clipboard-copy icon
- Auto-refresh while any row has `status in ('queued','running')`: TanStack `refetchInterval: 5_000` until none remain in flight; then disable interval

### Run detail page (`/admin/labels/enrich/runs/:runId`)

**Layout:**

```
┌─────────────────────────────────────────────────────────────────┐
│ ← Back to runs                                                  │
│ RunDetailHeader                                                 │
│   Run a045c834…   [completed]                                   │
│   Created 14:22 · Started 14:22 · Finished 14:23  (41s)         │
│   Cells: 3 ok / 0 err / 3 total          Cost: $0.0155          │
│   Prompt: label_v3_app_fields@1.0.0                             │
│   Vendors: gemini, openai, tavily_deepseek + merge: deepseek    │
├─────────────────────────────────────────────────────────────────┤
│ [ Summary ] [ Cells ] [ Raw JSON ]                              │
├─────────────────────────────────────────────────────────────────┤
│ Summary tab: counters cards + vendor breakdown (count/cost/avg) │
│ Cells tab:   RunDetailCellsTable                                │
│              Label · Vendor · Status · Latency · Cost · Error   │
│ Raw JSON:    RunJsonViewer (full GET response, copy button)     │
└─────────────────────────────────────────────────────────────────┘
```

**`RunJsonViewer`:**
- Wraps Mantine `Code block`. No external syntax-highlighter — `<pre>` with `whiteSpace: 'pre-wrap'`, `JSON.stringify(data, null, 2)`.
- Copy-to-clipboard button in top-right corner uses Mantine `CopyButton`.
- Tab is keyboard-focusable; supports Cmd-A select-all over the JSON.

**`RunDetailCellsTable`:**
- Groups rows by `label_id` with collapsible group headers when run has >1 labels
- Status cell: green check for `ok`, red x for `error` (Mantine `Badge`)
- Error column truncated to 60 chars with full-text in `Tooltip`

---

## Surface 3 — Triage player tile

### Mounting point

`features/curate/components/CurateSession.tsx`. The "triage player" is the curate session opened over a triage bucket (route `/curate/:styleId/:blockId/:bucketId`) — it uses `<PlayerCard>` and tracks `session.currentTrack` (a `BucketTrack`). The tile sits in a right-rail column added with Mantine `Group`. Existing layout stays full width on mobile; right rail only renders at `>=1024px`.

For symmetry, the same tile also mounts in `features/categories/components/CategoryPlayerPanel.tsx` (the categories player) using the analogous current-track plumbing — same component, same hook, different track-source. This is a one-line addition and is included so users see the tile in both player surfaces, not just curate.

### Component

```tsx
// features/library/components/LabelTile.tsx
export function LabelTile({ labelId, styleId }: { labelId: string | null; styleId: string }) {
  const { data, isLoading, isError } = useLabelInfo(labelId);
  if (!labelId || isError) return null;
  if (isLoading) return <LabelTileSkeleton />;
  if (!data) return null;
  return (
    <Card withBorder padding="md" w={320}>
      <Group gap="xs">
        <CountryFlag iso2={data.country} />
        <Anchor component={Link} to={`/library/${styleId}/labels/${labelId}`} fw={600}>
          {data.label_name}
        </Anchor>
      </Group>
      <Text size="sm" lineClamp={2} mt="xs">
        {data.tagline ?? data.summary}
      </Text>
      <Group gap={6} mt="sm">
        {pickTopChannels(data, 3).map((ch) => (
          <ActionIcon key={ch.kind} component="a" href={ch.url} target="_blank" rel="noopener noreferrer" variant="subtle">
            <ch.Icon size={16} />
          </ActionIcon>
        ))}
      </Group>
      <Anchor component={Link} to={`/library/${styleId}/labels/${labelId}`} size="sm" mt="sm">
        Read more →
      </Anchor>
    </Card>
  );
}
```

**`pickTopChannels(info, 3)`** — priority order: website > soundcloud > bandcamp > beatport > residentadvisor > discogs > instagram > twitter. Skips any null URL. Returns up to 3.

### Mounting code

```tsx
// in CurateSession.tsx (curate flow over triage bucket)
const session = useCurateSession({ styleId, blockId, bucketId });
const { width } = useViewportSize();  // Mantine

return (
  <Group align="flex-start" gap="md">
    <Box flex={1}>
      <PlayerCard ... />
    </Box>
    {width >= 1024 && (
      <LabelTile
        labelId={session.currentTrack?.label_id ?? null}
        styleId={styleId}
      />
    )}
  </Group>
);

// in CategoryPlayerPanel.tsx (analogous)
{width >= 1024 && (
  <LabelTile
    labelId={effectiveRich.label?.id ?? null}
    styleId={styleId}
  />
)}
```

`session.currentTrack` is a `BucketTrack` (after backend B1 adds `label_id`). `effectiveRich.label.id` already exists on the categories player (`CategoryTrack.label: {id, name}`).

### Data fetch

`useLabelInfo` is the single hook. Cache lives 5 minutes (the data rarely changes). Tile flickers prevented because the hook keys on `labelId` — same label between consecutive tracks reuses cache.

### Behavior

- Track has no `label_id` → tile renders nothing (returns `null`)
- Track has `label_id` but backend returns 404 (no `clouder_label_info` row) → tile returns null silently
- Backend 5xx → tile returns null + logs to console; player must NOT break (no error boundary swallows player)
- Loading state shows a `LabelTileSkeleton` of identical dimensions to avoid layout shift

---

## Shared API surface

```typescript
// frontend/src/api/labels.ts (new)

import type { components, paths } from './schema';

export type LabelSummary       = paths['/labels']['get']['responses'][200]['content']['application/json']['items'][number];
export type LabelDetail        = paths['/labels/{label_id}']['get']['responses'][200]['content']['application/json'];
export type BacklogLabel       = paths['/admin/labels/backlog']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunSummary         = paths['/admin/labels/enrich-runs']['get']['responses'][200]['content']['application/json']['items'][number];
export type RunDetail          = paths['/admin/labels/enrich-runs/{run_id}']['get']['responses'][200]['content']['application/json'];
export type EnrichmentOptions  = paths['/admin/labels/enrich/options']['get']['responses'][200]['content']['application/json'];
export type EnrichBody         = paths['/admin/labels/enrich']['post']['requestBody']['content']['application/json'];
```

No additional wrapper types — components consume the generated shape directly. This means any backend rename surfaces as a TypeScript error at build time.

---

## Router additions

```tsx
// frontend/src/routes/router.tsx — diff

// INSIDE the AppShellLayout children block (next to categories / triage / curate / playlists):
{
  path: 'library',
  children: [
    { index: true, element: <LibraryIndexRedirect /> },
    { path: ':styleId', element: <LibraryListPage /> },
    { path: ':styleId/labels/:labelId', element: <LabelDetailPage /> },
  ],
},

// INSIDE the admin AdminLayout children block (next to coverage / spotify-not-found):
{ path: 'labels/enrich', element: <AdminEnrichmentBacklogPage /> },
{ path: 'labels/enrich/runs', element: <AdminEnrichmentRunsPage /> },
{ path: 'labels/enrich/runs/:runId', element: <AdminEnrichmentRunDetailPage /> },
```

`AdminLayout.tsx` `TAB_VALUES` becomes:

```typescript
const TAB_VALUES = [
  '/admin/coverage',
  '/admin/spotify-not-found',
  '/admin/labels/enrich',
  '/admin/labels/enrich/runs',
] as const;
```

The Tabs `active` detection logic uses `startsWith`, which already matches `/admin/labels/enrich/runs/<id>` → `/admin/labels/enrich/runs`. The two tabs do not conflict because `startsWith` runs left-to-right and `/admin/labels/enrich/runs` is checked before `/admin/labels/enrich` — invert iteration to longest-first to avoid bugs:

```typescript
const active =
  [...TAB_VALUES].sort((a, b) => b.length - a.length).find((v) => location.pathname.startsWith(v))
  ?? TAB_VALUES[0];
```

---

## i18n

All user-visible strings added under three i18n namespaces, matching existing convention:

- `library.*` — list page, detail page, tile
- `admin.enrichment.*` — backlog, runs, run-detail
- `library.tile.*` — triage tile-specific labels (reused inside `LabelTile` so triage doesn't define its own copies)

English strings written inline in PR; Russian (existing `frontend/src/i18n/locales/ru/`) follows the same key tree, translated as the next plan step.

---

## Error handling

| Surface         | Failure mode               | UX                                                              |
| --------------- | -------------------------- | --------------------------------------------------------------- |
| Library list    | API 5xx                    | `RouteErrorBoundary` (existing)                                 |
| Library list    | Empty results              | "No labels match these filters."                                |
| Library detail  | 404                        | "Information not yet collected" + admin-only enqueue CTA       |
| Library detail  | 5xx                        | `RouteErrorBoundary`                                            |
| Admin backlog   | 5xx                        | `RouteErrorBoundary`                                            |
| Admin backlog   | Empty                      | "Caught up! No labels missing info."                            |
| Admin enqueue   | 4xx (validation)           | Notification with `error.detail`, drawer stays open             |
| Admin enqueue   | 5xx                        | Generic error notification + retry button                       |
| Run detail      | 404                        | "Run not found" with back-link                                  |
| Triage tile     | Any error                  | Silently render null — player must not break                   |

---

## Testing

Per existing convention (see `frontend/src/features/triage/__tests__/`):

**Hook unit tests:** one test file per hook. Mock `api` via existing `setupTests.ts` infrastructure. Verify query-key shape, error propagation, parameter encoding.

**Component tests:** Vitest + React Testing Library. Coverage targets:

- `LabelCard.test.tsx` — pending / completed / status badges / click navigation
- `LabelTile.test.tsx` — null when no labelId, null when 404, render shape on success, viewport-gating not its responsibility (parent controls)
- `EntityTabs.test.tsx` — Artists tab disabled with tooltip
- `EnqueueDrawer.test.tsx` — form fills from options, submit body assembles correctly, error toast on failure
- `RunJsonViewer.test.tsx` — copy button, JSON renders
- `BacklogTable.test.tsx` — checkbox semantics (per-page select, not select-all-results)

**Route smoke tests:** one per route, mounting under `MemoryRouter`. Verifies the page renders without throwing and shows the expected hero element. No deep snapshot.

**No E2E.** Matches existing project policy.

---

## Folder structure final

```
frontend/src/features/library/                       # NEW
├── components/
│   ├── EntityTabs.tsx
│   ├── EntityDetailLayout.tsx
│   ├── LibraryFilters.tsx
│   ├── LabelCard.tsx
│   ├── LabelListGrid.tsx
│   ├── LabelDetailHeader.tsx
│   ├── LabelChannelLinks.tsx
│   ├── LabelOverviewTab.tsx
│   ├── LabelStylesTab.tsx
│   ├── LabelTile.tsx
│   └── LabelTileSkeleton.tsx
├── hooks/
│   ├── useLabelsList.ts
│   ├── useLabelDetail.ts
│   └── useLabelInfo.ts
├── lib/
│   ├── channelMeta.ts
│   ├── countryFlag.ts
│   ├── pickTopChannels.ts
│   └── formatLabel.ts
├── routes/
│   ├── LibraryIndexRedirect.tsx
│   ├── LibraryListPage.tsx
│   └── LabelDetailPage.tsx
├── __tests__/
│   └── (component + hook + route tests)
└── index.ts

frontend/src/features/admin/                          # EXTEND
├── components/enrichment/                            # NEW subfolder
│   ├── BacklogTable.tsx
│   ├── BacklogToolbar.tsx
│   ├── EnqueueDrawer.tsx
│   ├── RunsTable.tsx
│   ├── RunStatusBadge.tsx
│   ├── RunDetailHeader.tsx
│   ├── RunDetailCellsTable.tsx
│   └── RunJsonViewer.tsx
├── hooks/                                            # EXTEND
│   ├── useLabelBacklog.ts
│   ├── useEnrichmentRuns.ts
│   ├── useEnrichmentRunDetail.ts
│   ├── useEnrichmentOptions.ts
│   └── useEnqueueEnrichment.ts
└── routes/                                           # EXTEND
    ├── AdminEnrichmentBacklogPage.tsx
    ├── AdminEnrichmentRunsPage.tsx
    └── AdminEnrichmentRunDetailPage.tsx

frontend/src/api/labels.ts                            # NEW (type re-exports)
frontend/src/features/curate/                         # MOUNT only
└── components/CurateSession.tsx                      # MODIFY: add <LabelTile/> right rail
frontend/src/features/categories/                     # MOUNT only
└── components/CategoryPlayerPanel.tsx                # MODIFY: add <LabelTile/> right rail
frontend/src/features/triage/                         # MOUNT only (track shape)
└── hooks/useBucketTracks.ts                          # MODIFY: add label_id to BucketTrack interface
```

---

## Open calls (locked-in defaults; flag to revisit later if needed)

1. **Library uses `/library/:styleId` not `/labels/:styleId`** — entity-agnostic root reads cleaner when artists arrive.
2. **Artists tab disabled-with-tooltip** rather than absent — preserves URL/component shape for v2 with zero refactor.
3. **Notable-artists chips inert in v1** — clickable in v2 when artist detail page exists.
4. **No bulk enrich from user-facing pages** — strictly admin.
5. **Cost / token / provenance hidden from user-facing detail endpoint** — backend sanitizes B3 response.
6. **Mobile triage tile dropped** — vertical space too cramped; deep-link from track row is the fallback (out of scope).
7. **Run JSON view uses `<pre>` + copy button** — no fancy tree viewer; raw JSON is the demand.
8. **Prompt + vendor + model lists fetched from `B7` `enrich/options`** — no hardcoded FE constants.
9. **Markdown rendering of `summary` deferred** — plain `pre-wrap` v1. Add `react-markdown` when backend signals markdown content.
10. **No favorites / personal lists** — out of scope.
11. **No sort by track-count or recency on backlog table v1** — natural admin order (most-tracks first) controlled by backend; v2 can add column sort if needed.
12. **No live run progress streaming** — 5s polling while runs are in flight; switch to SSE/WebSocket only if cost / latency becomes a problem.
13. **Backend B1 (`label_id` on triage track) is the smallest backend change and is required before triage tile ships** — gates Surface 3 only; Surfaces 1 and 2 can ship without it.

---

## Out of scope (explicit non-goals)

- Artist enrichment (data layer, UI shell ready)
- Pencil-style theming pass / pixel-perfect mockups (use existing Mantine theme tokens)
- Bookmarks / favorites / personal label lists
- Filter by AI content status on user-facing list
- Run cancellation UI (no backend endpoint yet)
- Stuck-run reconciler UI (separate spec, Phase 2 of backend)
- Re-enqueue from user-facing detail (admin-only via the existing drawer with the label pre-selected)
- I18n translations to Russian — separate PR step

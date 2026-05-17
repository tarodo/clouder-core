# F8 Home / Dashboard — Frontend Design

**Date:** 2026-05-09
**Status:** Shipped 2026-05-09 (merge `7eca6f8`)
**Roadmap:** `docs/superpowers/plans/2026-05-01-frontend-iter-2a-roadmap.md` (F8)
**Design ref:** `docs/design_handoff/02 Pages catalog · Pass 1 (Auth-Triage).html` § P-04 / P-08
**Backend ref:** `docs/openapi.yaml` (no new endpoints — composes existing data)

---

## 1. Goal

Replace the placeholder `routes/home.tsx` with a working dashboard that drops the user back into curation work in one click and surfaces actionable status across all their styles.

Home is **not** a navigation hub or a vanity-stats screen. It is a hybrid Resume + Status entry point.

## 2. Behavioural contract

When a signed-in user lands on `/`:

1. **Resume hero** points at the user's last in-flight curation context, falling back through three layers:
   1. localStorage `clouder.lastCurate` — last Curate session, validated against current data (block must exist and be `IN_PROGRESS`).
   2. Freshest `IN_PROGRESS` Triage block across all styles (sort by `updated_at` desc).
   3. Empty state with CTA "Create first triage block" → `/triage?create=1`.
2. **Counters** show:
   - `awaitingTriageCount` — sum of `track_count` over all `IN_PROGRESS` blocks (block-level total, not bucket-specific). Bucket-level UNCLASSIFIED breakdown would require a detail fetch per block (N+1) and is out of scope.
   - `activeBlocksCount` — number of `IN_PROGRESS` blocks across all styles.
   Both are clickable and lead to `/triage`.
3. **Active blocks list** shows top-5 `IN_PROGRESS` blocks (sort by `updated_at` desc) with `{week_label} · {style_name}` and the block's `track_count`. Each row links to `/triage/:styleId/:id`. Footer "View all" link if total > 5.

If the user has no styles bound (rare multi-tenant edge), Home renders "No styles assigned yet. Contact admin." in the hero slot, with counters and list hidden.

## 3. Architecture

### 3.1 File layout

New feature folder per CLAUDE.md feature-folder convention:

```
frontend/src/features/home/
├── hooks/
│   ├── useHomeData.ts                # composer: useQueries → aggregates
│   ├── useResumeTarget.ts            # localStorage + blocksByStyle → discriminated target
│   ├── homeActiveBlocksQueryOptions.ts  # query options factory (non-infinite)
│   └── __tests__/
├── components/
│   ├── ResumeHero.tsx                # 3 states: curate / triage / empty
│   ├── CountersGrid.tsx              # 2-col SimpleGrid
│   ├── ActiveBlocksList.tsx          # top-5 + "View all"
│   ├── HomeSkeleton.tsx              # parallel skeleton for all sections
│   ├── NoStylesEmpty.tsx             # multi-tenant edge: no styles assigned
│   └── __tests__/
├── lib/
│   ├── weekLabel.ts                  # ISO date → "YYYY-Www" label
│   └── __tests__/
└── routes/
    └── HomePage.tsx                  # thin composer
```

`frontend/src/routes/router.tsx` updates the `/` route to import from `features/home/routes/HomePage`. The existing placeholder `frontend/src/routes/home.tsx` is removed.

### 3.2 Reuse of existing localStorage helpers

The Curate feature already ships `frontend/src/features/curate/lib/lastCurateLocation.ts` with the writer + reader pair:

- `LAST_CURATE_LOCATION_KEY = 'clouder.lastCurateLocation'` — `Record<styleId, { blockId, bucketId, updatedAt }>`
- `LAST_CURATE_STYLE_KEY = 'clouder.lastCurateStyle'` — single string, last-visited style id
- `readLastCurateLocation(styleId)`, `readLastCurateStyle()`, `writeLastCurate*`, `clearLastCurateLocation`

`CurateSessionPage` already calls both writers on mount (no F5 modification needed).

`useResumeTarget` consumes the existing readers — no new hook for localStorage. Validation against `TriageBlockSummary` (status only, no bucket array available in summary) lives in `useResumeTarget`. The existing `isStaleLocation(loc, block: TriageBlock)` helper is NOT used here because it requires the full block detail; Home does its own summary-level validation.

If a third consumer appears (e.g. MiniBar wants the same restore signal), promote the hook to `frontend/src/hooks/` per the established pattern.

### 3.3 Data flow

```
HomePage
  └── useHomeData()
        ├── useStyles()  ───────────── styles.items[]
        └── useQueries(styles.items.map(s =>
              homeActiveBlocksQueryOptions(s.id)))    # GET /styles/:id/triage/blocks?status=IN_PROGRESS&limit=50
              └── blocksByStyle: Record<styleId, TriageBlockSummary[]>

  derived (in useHomeData):
    activeBlocks: TriageBlockSummary[]      # flat, sorted updated_at desc
    activeBlocksCount: number               # activeBlocks.length
    awaitingTriageCount: number             # sum of activeBlocks[i].track_count
    topActiveBlocks: TriageBlockSummary[]   # activeBlocks.slice(0, 5)
    partialError: boolean                   # true if any useQueries entry failed
    refetchAll: () => void                  # invalidate styles + per-style queries

  └── useResumeTarget(activeBlocks, blocksByStyle, lastCurateSession)
        → { kind: 'curate', session: LastCurateSession, block: TriageBlockSummary }
        | { kind: 'triage', block: TriageBlockSummary }
        | { kind: 'empty' }
```

Note: `homeActiveBlocksQueryOptions` is a Home-specific (non-infinite) query option factory keyed `['home', 'activeBlocks', styleId]`. It does NOT reuse the `useTriageBlocksByStyle` infinite cache (different key, different shape) — this avoids cache cross-pollution between Home (single page, status-pinned) and Triage list (paginated, all statuses).

Cache strategy:

- All queries `staleTime: 30s`.
- `refetchOnWindowFocus: true` (Mantine 9 / TanStack default).
- No polling.

N+1 caveat: no aggregation endpoint exists. Per CLAUDE.md ("composes existing data") we fan out one query per style. Typical user has 1–3 styles, so 1–3 parallel calls. Beyond ~10 styles per user this would warrant a backend `/me/dashboard` endpoint, but that is out of F8 scope.

## 4. Components

### 4.1 ResumeHero

Three render states keyed off `useResumeTarget` discriminator:

- `curate` — "Continue · {styleName} → {blockName} → {bucketLabel}", N tracks left, primary `<Button component={Link} to="/curate/:style/:block/:bucket">Continue</Button>`.
- `triage` — "Open latest block · {styleName} · {blockName}" with `<Button component={Link} to="/triage/blocks/:id">Open block</Button>`.
- `empty` — "No active triage yet" with `<Button component={Link} to="/triage?create=1">Create first triage block</Button>`. The `?create=1` query param is a small extension to `TriageBlocksListPage` (F2): on mount, if `searchParams.get('create') === '1'` and styles loaded, open the create modal and strip the param.

Visual: light card per layout option A (rejected the dark hero of option B). `border: 1px solid var(--color-border); border-radius: var(--radius-md);` per design tokens.

### 4.2 CountersGrid

`<SimpleGrid cols={2} spacing="xs">` with two `<Counter>` cards (counter is a small inline component, not promoted to `components/`). Each card is a clickable `<UnstyledButton component={Link} to="/triage">`. Layout per design system: 32px mono number + 11px uppercase label.

### 4.3 ActiveBlocksList

Mantine `<Stack>` of up to 5 rows. Each row is `<UnstyledButton component={Link}>` with flex justify-between: left `{weekLabel} · {styleName}`, right `{block.track_count}` mono.

`weekLabel` derivation: parse `block.date_from` (ISO date) → ISO-week string `YYYY-Www` (e.g. `2026-W18`). Helper added inline; tracked as candidate for `lib/dates.ts` if reused.

Footer `<Anchor component={Link} to="/triage">View all ({total} blocks)</Anchor>` shown only if `total > 5`.

Empty state (styles exist, IN_PROGRESS = 0): inline `<EmptyState>` with the same CTA as the hero (no second create button needed; the section collapses to a hint).

### 4.4 HomeSkeleton

`<Stack>` of: `<Skeleton h={88}>` (hero), `<SimpleGrid cols={2}>` × 2 `<Skeleton h={72}>`, `<Skeleton h={200}>` (list). Single skeleton for the whole page — no per-section skeleton flicker (one flip when all queries resolve).

### 4.5 HomePage

Wrapper-split composer to satisfy `react-hooks/rules-of-hooks` (any post-load hook must run after a fresh component mount, not after an early return). `HomePage` owns guards; `HomeReady` owns the data-bound hooks; `HomeError` owns the inline failure surface.

```tsx
export function HomePage() {
  const { data, isLoading, isError, error, refetchAll } = useHomeData();
  if (isLoading) return <HomeSkeleton />;
  if (isError || !data) return <HomeError refetchAll={refetchAll} error={error} />;
  if (data.styles.length === 0) return <NoStylesEmpty />;
  return <HomeReady data={data} refetchAll={refetchAll} />;
}

function HomeError({ refetchAll, error }: { refetchAll: () => void; error?: unknown }) {
  // Alert color="red" with home.error.full / home.error.full_retry copy.
  // Renders <Code>{t('errors.correlation_id', { id })}</Code> when
  // error instanceof ApiError && error.correlationId is truthy.
}

function HomeReady({ data, refetchAll }: { data: HomeData; refetchAll: () => void }) {
  const target = useResumeTarget(data.activeBlocks, data.blocksByStyle);
  // Stack maw={720} with optional partial-error Alert (color="yellow",
  // home.error.partial / home.error.partial_retry), ResumeHero, CountersGrid,
  // ActiveBlocksList.
}
```

Note: an earlier draft used `<RouteErrorBoundary />` as the full-error fallback; in implementation `RouteErrorBoundary` calls `useRouteError()` which returns `undefined` outside a route-level errorElement, so the user got a generic "Something broke" with a useless "Back to home" CTA and no retry. The inline `<HomeError>` above replaces that path — see commits `219838b` and `0a30a3f`.

## 5. localStorage

### 5.1 Shape (existing — reused as-is)

Defined in `frontend/src/features/curate/lib/lastCurateLocation.ts`:

```ts
// Key: 'clouder.lastCurateLocation'
type Storage = Record<styleId, { blockId: string; bucketId: string; updatedAt: string }>;

// Key: 'clouder.lastCurateStyle'
// value: styleId (string)
```

`updatedAt` is an ISO timestamp string — Home parses it via `new Date(updatedAt).getTime()` for the stale-window check.

### 5.2 Reader functions (existing — reused)

```ts
readLastCurateStyle(): string | null;
readLastCurateLocation(styleId: string): { blockId, bucketId, updatedAt } | null;
clearLastCurateLocation(styleId: string): void;
```

Home composes them in `useResumeTarget`: `style = readLastCurateStyle()` → `loc = readLastCurateLocation(style)` → combine into a transient `ResumeSession = { styleId, blockId, bucketId, updatedAt }`. No new hook is introduced.

### 5.3 Writer integration

Already in place: `frontend/src/features/curate/routes/CurateSessionPage.tsx:13-17` calls `writeLastCurateLocation(styleId, blockId, bucketId)` and `writeLastCurateStyle(styleId)` on mount whenever route params change. F8 adds **no** code to the Curate feature.

### 5.4 Validation in `useResumeTarget`

```
1. styleId = readLastCurateStyle(); if null → fallback
2. loc = readLastCurateLocation(styleId); if null → fallback
3. if Date.now() - new Date(loc.updatedAt).getTime() > 7 days → clearLastCurateLocation(styleId) + fallback
4. block = blocksByStyle[styleId]?.find(b => b.id === loc.blockId)
5. if !block OR block.status !== 'IN_PROGRESS' → clearLastCurateLocation(styleId) + fallback
6. else → { kind: 'curate', session: { styleId, ...loc }, block }
```

`fallback` = first IN_PROGRESS block in `activeBlocks` (already sorted updated_at desc) → `{ kind: 'triage', block }`. If `activeBlocks` is empty → `{ kind: 'empty' }`.

Stale window of 7 days picks "user came back from vacation" up as a fresh start, not a stale resume.

Bucket existence is NOT validated client-side — list summaries do not include the buckets array, and a detail fetch per block would inflate the page's request count. If the bucket has been removed (e.g. STAGING bucket gone after a category was deleted), the user lands on `/curate/:style/:block/:bucket` and Curate's existing 404 handler resolves it. This is acceptable tail latency for a rare edge case.

### 5.5 Privacy

localStorage is per-origin. No secrets stored. Spotify token continues to live in-memory only (PB16 contract unchanged).

## 6. States

### 6.1 Loading

- `useStyles` pending → `HomeSkeleton`.
- `useStyles` resolved, any `useQueries` pending → `HomeSkeleton` (aggregates not yet valid).
- All resolved → real content.

Single skeleton, single flip. No partial render.

### 6.2 Error

- `useStyles` error → inline `<HomeError>` rendering `<Alert color="red" variant="light" title={t('home.error.full')}>` ("Couldn't load your dashboard.") with a `Retry` button wired to `refetchAll`. When `error instanceof ApiError && error.correlationId` truthy, the alert appends `<Code>{t('errors.correlation_id', { id })}</Code>` so support / debug stories keep the correlation id visible.
- One or more `useQueries` failed → `useHomeData` surfaces `partialError: true`. `HomeReady` renders content as usual + a top `<Alert color="yellow" variant="light" title={t('home.error.partial')}>` ("Some styles failed to load.") with a `Retry` button calling `refetchAll`.
- Aurora cold-start 503 (per CLAUDE.md gotcha): TanStack Query default retries (3 × exponential backoff) handle it. Skeleton stays longer; no cold-start banner on Home (low impact, user just waits).
- Distinct copy / colour / scope for the two paths is deliberate: the partial state still shows usable data, so a yellow advisory is right; the full state hides everything until retry, so a red alert with the correlation id is right.

### 6.3 Empty

- No styles bound: hero "No styles assigned yet. Contact admin." Counters and list hidden.
- Styles exist, IN_PROGRESS = 0, no localStorage: hero `empty` CTA "Create first triage block". Counters `0` / `0`. List section replaced by inline empty state.
- Styles exist, IN_PROGRESS = 0, localStorage stale or invalid: clear localStorage, treat as previous case.

### 6.4 i18n

All strings in `frontend/src/i18n/en.json` under `home.*`. RU bundle deferred to CC-4 (F9). Final shipped key set (snake_case leaves):

- `home.resume.curate.{title,context,cta}`
- `home.resume.triage.{title,context,cta}`
- `home.resume.empty.{title,body,cta}`
- `home.counters.{awaiting_triage,active_blocks,tracks_unit}`
- `home.active_blocks.{title,view_all,empty_body}`
- `home.error.{partial,partial_retry,full,full_retry}`
- `home.no_styles.{title,body}`

`home.counters.blocks_unit` was scaffolded in Task 1 but never consumed — `view_all` includes "blocks" inline — and was removed in commit `0a30a3f`.

## 7. Testing

### 7.1 Unit (vitest)

- `weekLabel.test.ts` — ISO date → `YYYY-Www`. Cover Jan 1 corner cases (week 53/01).
- `useResumeTarget.test.ts` — table-driven scenarios:
  1. localStorage curate-valid → `kind: 'curate'`.
  2. curate but block FINALIZED → fallback + cleared.
  3. curate but block missing → fallback + cleared.
  4. curate but stale (>7d) → fallback + cleared.
  5. no localStorage, IN_PROGRESS blocks exist → `kind: 'triage'`.
  6. no localStorage, no IN_PROGRESS → `kind: 'empty'`.
- `useHomeData.test.ts` — MSW-backed; verify aggregates `awaitingTriageCount` (sum of `track_count`), `activeBlocksCount`, `topActiveBlocks` (sort updated_at desc + slice 5), `partialError` (one query 500s → flag set, others succeed).

### 7.2 Component (RTL + jsdom)

- `ResumeHero.test.tsx` — render all three discriminated states; correct link target; clickable area.
- `CountersGrid.test.tsx` — number rendering; `/triage` navigation.
- `ActiveBlocksList.test.tsx` — empty, 1–4 rows, 5+ rows (footer visible); row click navigation; weekLabel formatting.

### 7.3 Integration (`frontend/src/features/home/routes/__tests__/HomePage.test.tsx`)

- Cold mount: MSW handlers — `/styles` → 2 styles, `/styles/:id/triage/blocks?status=IN_PROGRESS` → mocked summaries. Skeleton → content. Counters summed across both styles.
- localStorage path: pre-seed `clouder.lastCurateStyle` + `clouder.lastCurateLocation[styleId]` valid → hero `curate` shows correct target with link `/curate/:styleId/:blockId/:bucketId`.
- Stale localStorage: `updatedAt` 8 days ago → fallback to `triage` and `clouder.lastCurateLocation` cleared for that styleId.
- Block FINALIZED after save: localStorage points to a block currently in FINALIZED status → fallback + cleared.
- Empty: 0 IN_PROGRESS blocks, no localStorage → hero `empty` with CTA `/triage?create=1`.
- Partial error: one `useQueries` entry fails (500) → warning Alert visible + remaining content rendered.
- No styles: `/styles` → `{ items: [], total: 0, ... }` → "Contact admin" hero, counters/list hidden.

### 7.4 Test infra reminders (CLAUDE.md)

- `MantineProvider theme={testTheme}` required (Skeleton + Alert use Mantine).
- `notifyManager.setScheduler(queueMicrotask)` already in `setup.ts`.
- MSW handlers on `http://localhost/...`.
- `gcTime: Infinity` on test QueryClient.

### 7.5 Coverage target

`frontend/src/features/home/` ≥ 90% lines.

## 8. Out-of-scope

- Backend `/me/dashboard` aggregation endpoint. N+1 fan-out is acceptable at current scale.
- Recent Categories widget (rejected during brainstorming).
- "Tracks awaiting curation" counter (rejected during brainstorming).
- Per-style breakdown in counters (layout A has no right rail).
- AI-suspected counters (`/labels` does not project `is_ai_suspected` per CLAUDE.md gotcha — backend work required, deferred).
- Real-time updates (SSE / polling) — Phase 2.
- Cold-start banner on Home — low impact, automatic retry sufficient.
- Code-splitting (CC-3) — separate ticket, does not block F8.
- i18n RU bundle (CC-4) — wired in F9.
- Dark theme toggle (CC-5) — wired in F9.

## 9. Accepted tech debt

- N parallel `useQueries` instead of one aggregation endpoint. Acceptable up to ~10 styles per user.
- localStorage validation is client-side. If the backend deletes a block and the user returns within a render frame, one frame may show a stale hero before validation kicks in. Acceptable — subsequent state flip is silent.
- `useLastCurateSession` is written **only** from Curate. Users who jump straight to Triage detail without entering Curate produce no resume entry. By design — resume = last Curate session, not last visited page.

## 10. Dependencies

No new packages. Uses existing Mantine 9, TanStack Query 5, react-router 7, react-i18next.

Bundle impact estimate: ~5–8 KB minified (3 hooks, 4 components, JSX). Within current ~910 KB / 271 KB gz envelope.

## 11. Backwards compatibility

- Existing `/` route is the placeholder `EmptyState` — fully replaced. No production users depend on the placeholder.
- F2 `TriageListPage` gains a small `?create=1` query param handler that opens the create-modal on mount and strips the param. Backward-compatible (param absent → existing behaviour).
- F5 `CurateSessionPage` already writes localStorage; no change required.

## 12. Implementation note

Before kicking off the implementation plan, run a quick sanity check on `GET /styles/{id}/triage/blocks` — confirm `bucket_type` and `track_count` field names match the schema referenced here. Schema drift between `docs/openapi.yaml` and live API has bitten F2/F3 once before; cheap to verify.

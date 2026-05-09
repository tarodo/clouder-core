# F8 Home / Dashboard — Frontend Design

**Date:** 2026-05-09
**Status:** Draft for review
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
   1. localStorage `clouder.lastCurate` — last Curate session, validated against current data (block must exist and be ACTIVE, bucket must exist).
   2. Freshest ACTIVE Triage block across all styles (sort by `updated_at` desc).
   3. Empty state with CTA "Create first triage block" → `/triage?create=1`.
2. **Counters** show:
   - `awaitingTriageCount` — sum of `track_count` over UNCLASSIFIED buckets in all ACTIVE blocks.
   - `activeBlocksCount` — number of ACTIVE blocks across all styles.
   Both are clickable and lead to `/triage`.
3. **Active blocks list** shows top-5 ACTIVE blocks (sort by `updated_at` desc) with `{week_label} · {style_name}` and UNCLASSIFIED count. Each row links to `/triage/blocks/:id`. Footer "View all" link if total > 5.

If the user has no styles bound (rare multi-tenant edge), Home renders "No styles assigned yet. Contact admin." in the hero slot, with counters and list hidden.

## 3. Architecture

### 3.1 File layout

New feature folder per CLAUDE.md feature-folder convention:

```
frontend/src/features/home/
├── hooks/
│   ├── useHomeData.ts            # composer: useQueries → aggregates
│   ├── useResumeTarget.ts        # localStorage → fallback ACTIVE → null
│   ├── useLastCurateSession.ts   # localStorage read/write
│   └── __tests__/
├── components/
│   ├── ResumeHero.tsx            # 3 states: curate / triage / empty
│   ├── CountersGrid.tsx          # 2-col SimpleGrid
│   ├── ActiveBlocksList.tsx      # top-5 + "View all"
│   ├── HomeSkeleton.tsx          # parallel skeleton for all sections
│   └── __tests__/
└── routes/
    └── HomePage.tsx              # thin composer
```

`frontend/src/routes/router.tsx` updates the `/` route to import from `features/home/routes/HomePage`. The existing placeholder `frontend/src/routes/home.tsx` is removed.

### 3.2 Cross-feature dependency

`useLastCurateSession.write()` is consumed by **`features/curate/`**, not Home. The Curate session page writes the localStorage entry on mount and after each cursor advance. Home only reads.

This is a one-direction cross-feature import (`features/curate/` → `features/home/hooks/`). Rationale per CLAUDE.md lesson #21 ("Extract shared atoms BEFORE the second consumer ships"): Home is the second consumer (Curate is the writer). The hook lives in `features/home/hooks/` because Home owns the read semantics; Curate is just a callsite.

If a third consumer appears (e.g. MiniBar wants the same restore signal), promote the hook to `frontend/src/hooks/` per the established pattern.

### 3.3 Data flow

```
HomePage
  └── useHomeData()
        ├── useStyles()  ───────────── styles[]
        └── useQueries(styles.map(s =>
              triageBlocksByStyleQueryOptions(s.id, { status: 'ACTIVE', limit: 50 })))
              └── blocksByStyle: Map<styleId, TriageBlockSummary[]>

  derived (in useHomeData):
    activeBlocks: TriageBlockSummary[]      # flat, sorted updated_at desc
    activeBlocksCount: number
    awaitingTriageCount: number             # sum of UNCLASSIFIED bucket track_count
    topActiveBlocks: TriageBlockSummary[]   # activeBlocks.slice(0, 5)
    partialError: boolean                   # true if any useQueries entry failed
    refetchAll: () => void                  # invalidate styles + per-style queries

  └── useResumeTarget(activeBlocks, blocksByStyle)
        → { kind: 'curate', styleId, blockId, bucketId, ... }
        | { kind: 'triage', block: TriageBlockSummary }
        | { kind: 'empty' }
```

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

Mantine `<Stack>` of up to 5 rows. Each row is `<UnstyledButton component={Link}>` with flex justify-between: left `{weekLabel} · {styleName}`, right `{unclassifiedCount}` mono.

`weekLabel` derivation: parse `block.date_from` (ISO date) → ISO-week string `YYYY-Www` (e.g. `2026-W18`). Helper added inline; tracked as candidate for `lib/dates.ts` if reused.

Footer `<Anchor component={Link} to="/triage">View all ({total} blocks)</Anchor>` shown only if `total > 5`.

Empty state (styles exist, ACTIVE = 0): inline `<EmptyState>` with the same CTA as the hero (no second create button needed; the section collapses to a hint).

### 4.4 HomeSkeleton

`<Stack>` of: `<Skeleton h={88}>` (hero), `<SimpleGrid cols={2}>` × 2 `<Skeleton h={72}>`, `<Skeleton h={200}>` (list). Single skeleton for the whole page — no per-section skeleton flicker (one flip when all queries resolve).

### 4.5 HomePage

Thin composer, ~25 lines:

```tsx
export function HomePage() {
  const { data, isLoading, isError, partialError, refetchAll } = useHomeData();
  if (isLoading) return <HomeSkeleton />;
  if (isError) return <RouteErrorBoundary />;
  return (
    <Stack gap="md" maw={720} mx="auto" px="md">
      {partialError && <Alert color="warning" variant="light" /* ... retry */ />}
      <ResumeHero target={data.resumeTarget} />
      <CountersGrid awaitingTriage={data.awaitingTriageCount} activeBlocks={data.activeBlocksCount} />
      <ActiveBlocksList blocks={data.topActiveBlocks} total={data.activeBlocksCount} />
    </Stack>
  );
}
```

## 5. localStorage

### 5.1 Shape

Key: `clouder.lastCurate`

```ts
type LastCurateSession = {
  styleId: string;        // UUID
  blockId: string;        // UUID
  bucketId: string;       // UUID
  styleName: string;      // for hero render without extra fetch
  blockName: string;
  bucketType: 'NEW' | 'OLD' | 'NOT' | 'DISCARD' | 'UNCLASSIFIED' | 'STAGING';
  savedAt: number;        // Date.now()
};
```

### 5.2 Hook contract

```ts
useLastCurateSession(): {
  read: () => LastCurateSession | null;
  write: (session: LastCurateSession) => void;
  clear: () => void;
};
```

- `read` wraps `JSON.parse` in try/catch; corrupt entry → returns `null` (does not throw).
- `write` wraps `localStorage.setItem` in try/catch; QuotaExceeded swallowed silently.
- `clear` calls `localStorage.removeItem`.

### 5.3 Writer integration (Curate)

`frontend/src/features/curate/routes/CurateSessionPage.tsx` calls `write({ ... })`:

- On mount (initial entry).
- On each successful `assign` mutation (cursor advanced).

Throttled via `useRef` to ≤ 1 call/sec. Implementation: stamp a timestamp ref, skip writes within 1000 ms of the last.

### 5.4 Validation in `useResumeTarget`

```
1. read() → last
2. if last == null → fallback to freshest ACTIVE block
3. if Date.now() - last.savedAt > 7 days → clear() + fallback
4. lookup blocksByStyle[last.styleId]
5. if not found, or block.status !== 'ACTIVE', or last.bucketId not in block.buckets[].id → clear() + fallback
6. else → { kind: 'curate', ...last }
```

Stale window of 7 days picks "user came back from vacation" up as a fresh start, not a stale resume.

### 5.5 Privacy

localStorage is per-origin. No secrets stored. Spotify token continues to live in-memory only (PB16 contract unchanged).

## 6. States

### 6.1 Loading

- `useStyles` pending → `HomeSkeleton`.
- `useStyles` resolved, any `useQueries` pending → `HomeSkeleton` (aggregates not yet valid).
- All resolved → real content.

Single skeleton, single flip. No partial render.

### 6.2 Error

- `useStyles` error → `<RouteErrorBoundary>` (existing, retry button).
- One or more `useQueries` failed → `useHomeData` surfaces `partialError: true`. `HomePage` renders content + a top `<Alert color="warning" variant="light">` with retry button calling `refetchAll`.
- Aurora cold-start 503 (per CLAUDE.md gotcha): TanStack Query default retries (3 × exponential backoff) handle it. Skeleton stays longer; no cold-start banner on Home (low impact, user just waits).

### 6.3 Empty

- No styles bound: hero "No styles assigned yet. Contact admin." Counters and list hidden.
- Styles exist, ACTIVE = 0, no localStorage: hero `empty` CTA "Create first triage block". Counters `0` / `0`. List section replaced by inline empty state.
- Styles exist, ACTIVE = 0, localStorage stale or invalid: clear localStorage, treat as previous case.

### 6.4 i18n

All strings in `frontend/src/i18n/en.json` under `home.*`. RU bundle deferred to CC-4 (F9). Keys to add:

- `home.resume.curate.title`, `home.resume.curate.cta`
- `home.resume.triage.title`, `home.resume.triage.cta`
- `home.resume.empty.title`, `home.resume.empty.cta`
- `home.counters.awaitingTriage.label`, `home.counters.activeBlocks.label`
- `home.activeBlocks.title`, `home.activeBlocks.viewAll`, `home.activeBlocks.empty`
- `home.error.partial`, `home.error.partialRetry`
- `home.noStyles.title`, `home.noStyles.body`

## 7. Testing

### 7.1 Unit (vitest)

- `useLastCurateSession.test.ts` — read corrupt JSON → `null`; write under quota; clear; idempotent re-read.
- `useResumeTarget.test.ts` — table-driven scenarios:
  1. localStorage curate-valid → `kind: 'curate'`.
  2. curate but block finalized → fallback + clear.
  3. curate but block missing → fallback + clear.
  4. curate but bucket missing → fallback + clear.
  5. curate but stale (>7d) → fallback + clear.
  6. no localStorage, ACTIVE blocks exist → `kind: 'triage'`.
  7. no localStorage, no ACTIVE → `kind: 'empty'`.
- `useHomeData.test.ts` — mock `useStyles` + `useQueries`; verify aggregates `awaitingTriageCount` (sum), `activeBlocksCount`, `topActiveBlocks` (sort + slice), `partialError`.

### 7.2 Component (RTL + jsdom)

- `ResumeHero.test.tsx` — render all three discriminated states; correct link target; clickable area.
- `CountersGrid.test.tsx` — number rendering; `/triage` navigation.
- `ActiveBlocksList.test.tsx` — empty, 1–4 rows, 5+ rows (footer visible); row click navigation; weekLabel formatting.

### 7.3 Integration (`frontend/src/features/home/routes/__tests__/HomePage.test.tsx`)

- Cold mount: MSW handlers — `/styles` → 2 styles, `/styles/:id/triage/blocks?status=ACTIVE` → mocked summaries. Skeleton → content. Counters summed across both styles.
- localStorage path: pre-seed `clouder.lastCurate` valid → hero `curate` shows correct target.
- Stale localStorage: `savedAt = Date.now() - 8d` → fallback + cleared (assert `localStorage.getItem === null`).
- Block finalized after save: localStorage points to a block currently in FINALIZED status → fallback + cleared.
- Empty: 0 ACTIVE blocks, no localStorage → CTA `/triage?create=1`.
- Partial error: one `useQueries` entry fails → alert + remaining content.
- No styles: `/styles` → `[]` → "Contact admin" hero, counters/list hidden.

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
- F2 `TriageBlocksListPage` gains a small `?create=1` query param handler. Backward-compatible (param absent → existing behaviour).
- F5 `CurateSessionPage` gains a localStorage write call. No visible change.

## 12. Implementation note

Before kicking off the implementation plan, run a quick sanity check on `GET /styles/{id}/triage/blocks` — confirm `bucket_type` and `track_count` field names match the schema referenced here. Schema drift between `docs/openapi.yaml` and live API has bitten F2/F3 once before; cheap to verify.

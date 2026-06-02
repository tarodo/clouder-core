# Decouple artist/label detail pages from style

**Date:** 2026-06-02
**Status:** Approved design, pending implementation plan
**Scope:** Frontend only. No backend, API, DB, or OpenAPI changes.

## Problem

Artist and label detail pages are reachable only through style-scoped frontend
routes:

```
/library/:styleId/artists/:artistId   → ArtistDetailPage
/library/:styleId/labels/:labelId      → LabelDetailPage
```

`styleId` is used **only** for the URL guard and the "← Back to {style}" link.
The data fetch ignores it — `useArtistDetail(artistId)` hits `GET /artists/{id}`
and `useLabelDetail(labelId)` hits `GET /labels/{id}`, neither takes a style.

Because the route requires a `styleId`, every link-builder must thread one in.
Contexts with no single style — the playlist player panel above all — cannot
build the URL, so the artist/label name renders as plain text instead of a link.
This is documented in the code itself (`ArtistTile.tsx:13`):

```ts
/** Present on bucket/category players → name links to library detail. Absent on playlists. */
styleId?: string;
```

`PlaylistPlayerPanel` calls `<LabelTile labelId=... labelName=... />` and
`<ArtistsPanel artists=... />` with no `styleId`, so both render plain `<Text>`.

## Goal

Make artist and label detail pages canonically addressable at top-level routes
so any context can link to them unconditionally:

```
/artists/:artistId   → ArtistDetailPage
/labels/:labelId     → LabelDetailPage
```

## Non-goals

- **No backend / API / DB / OpenAPI changes.** `GET /artists/{artist_id}`
  (`artist_detail_user`) and `GET /labels/{label_id}` (`label_detail_user`)
  already exist in `infra/api_gateway.tf` and take only the id.
- **Library list pages stay style-scoped.** `/library/:styleId` (labels of a
  style) and `/library/:styleId/artists` (artists of a style) are an intentional
  browse-by-style surface. The list endpoints filter by `?style=` query param
  (`useLabelsList`, `useArtistsList`). Untouched.
- **Not** turning `notable_artists` / `notable_collaborators` text into links —
  separate enhancement.

## Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Scope | Global decouple | One canonical URL per entity; all conditional `styleId` link code disappears. |
| URL shape | Top-level `/artists/:id`, `/labels/:id` | Clean split: `/library/...` = browse-by-style, `/artists` & `/labels` = entity pages. No collision with `:styleId`. |
| Back navigation | Browser history (`navigate(-1)`), fallback `/library` | Context preserved for free (playlist → playlist, list → list). Fallback covers deep-link / new tab. |

## Changes (frontend only)

### 1. Routing — `src/routes/router.tsx`
- Remove from the `library` children:
  - `{ path: ':styleId/labels/:labelId', element: <LabelDetailPage /> }`
  - `{ path: ':styleId/artists/:artistId', element: <ArtistDetailPage /> }`
- Keep `{ path: ':styleId', element: <LibraryListPage /> }` (labels list) and
  `{ path: ':styleId/artists', element: <ArtistsListPage /> }` (artists list).
- Add as top-level children of `AppShellLayout` (auth-guarded):
  - `{ path: 'artists/:artistId', element: <ArtistDetailPage /> }`
  - `{ path: 'labels/:labelId', element: <LabelDetailPage /> }`

### 2. Detail pages
- `src/features/library/routes/ArtistDetailPage.tsx`: drop `styleId` from
  `useParams`; guard on `artistId` only (`if (!artistId) return <Navigate to="/library" replace />`);
  stop passing `styleId` to `ArtistDetailHeader`.
- `src/features/library/routes/LabelDetailPage.tsx`: same for `labelId` /
  `LabelDetailHeader`.

### 3. Back button — `useBackOrFallback` hook + headers
- New hook (e.g. `src/features/library/hooks/useBackOrFallback.ts` or a shared
  location): returns a handler that does `navigate(-1)` when in-app history
  exists (`location.key !== 'default'`), else `navigate(fallback)`.
- `src/features/library/components/ArtistDetailHeader.tsx` and
  `LabelDetailHeader.tsx`: drop the `styleId` prop; replace the
  `<Anchor component={Link} to={/library/${styleId}/...}>` back link with a
  button/anchor wired to `useBackOrFallback('/library')`.
- i18n: new key `library.detail.back` = `"← Back"` in `src/i18n/en.json`.
  `library.detail.back_to_list` (`"Back to {{style}}"`) is removed if no longer
  referenced after the change.

### 4. Link-builders — always a link, point to top-level, drop `styleId`
- `src/features/library/components/ArtistTile.tsx`: remove `styleId` prop and the
  ternary; always render `<Anchor component={Link} to={/artists/${artistId}}>`.
- `src/features/library/components/LabelTile.tsx`: same → `/labels/${labelId}`.
- `src/features/library/components/ArtistCard.tsx`: `to={/artists/${item.id}}`;
  drop `styleId`.
- `src/features/library/components/LabelCard.tsx`: `to={/labels/${item.id}}`;
  drop `styleId`.
- `src/features/library/components/ArtistsTable.tsx`: `to={/artists/${it.id}}`
  (was `/library/${p.styleId}/artists/${it.id}`).
- `src/features/library/components/LabelsTable.tsx`: `to={/labels/${it.id}}`.
- `src/features/library/components/ArtistsPanel.tsx`: drop `styleId` prop
  (was threaded to `ArtistTile`).
- `src/features/admin/components/enrichment/BacklogTable.tsx`:
  `to={/library/${row.style}/labels/${row.id}}` → `to={/labels/${row.id}}`.

### 5. Callers that threaded `styleId` — simplify
- `src/features/playlists/components/PlaylistPlayerPanel.tsx`: already passes no
  `styleId`; now gets working links for free (the payoff).
- `src/features/triage/components/BucketPlayerPanel.tsx`,
  `src/features/curate/components/CurateSession.tsx`,
  `src/features/categories/components/CategoryPlayerPanel.tsx`: remove the
  `styleId={...}` prop passed to `LabelTile` / `ArtistsPanel`.
- `EntityTabs`, `ArtistsListPage`, `LibraryListPage`: keep `styleId` for their
  own list navigation (style tabs switch `/library/:styleId` ↔
  `/library/:styleId/artists`); only the card → detail link changes.

## Test impact (TDD anchors)

- `src/features/playlists/components/__tests__/PlaylistPlayerPanel.test.tsx:181`
  — `it('renders LabelTile with label name as plain text (no link)')` inverts:
  the label name must now be a link to `/labels/:id`.
- `ArtistTile.test.tsx`, `LabelTile.test.tsx` — remove the "no `styleId` → plain
  text" case; assert the name is always a link to the top-level route.
- `ArtistCard` / `LabelCard`, `ArtistsTable.preference.test.tsx`,
  `LabelsTable.test.tsx`, `ArtistsPanel.test.tsx` /
  `ArtistsPanel.browser.test.tsx`, `LabelCard.test.tsx` — update expected hrefs
  to `/artists/:id` and `/labels/:id`.
- `src/features/library/routes/__tests__/ArtistDetailPage.test.tsx` — render at
  `/artists/:artistId` (not the style-scoped path); assert back button behavior.
- `src/features/admin/components/...` `BacklogTable` test — update label href if
  asserted.
- Any router/integration test referencing the old detail paths.

## Verification

- `cd frontend && pnpm typecheck && pnpm lint && pnpm test` (all three — CI runs
  tsc via the vite build and eslint; vitest alone misses them).
- Browser check (jsdom applies no styles): the playlist player panel renders a
  clickable artist + label link, and the back button on a standalone detail page
  returns to the previous page. Use `pnpm test:browser` for affected
  `*.browser.test.tsx` (CLAUDE.md gotcha #11).

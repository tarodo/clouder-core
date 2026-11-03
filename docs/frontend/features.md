# Frontend Features Reference

Stack: React 19, Mantine 9, react-router 7, TanStack Query 5, Zustand 5, i18next.
See `docs/adr/0009-frontend-stack.md` for the stack decision.

## Feature-folder convention

Every product surface lives under `frontend/src/features/<feature>/` with four sub-directories:

```
features/<feature>/
  routes/       — page components registered in router.tsx
  components/   — feature-local presentational components
  hooks/        — data-fetching and stateful hooks
  lib/          — pure utilities, types, constants
```

Shared code (API client, auth, i18n, test helpers, design tokens) lives at `frontend/src/` directly.

Current features: `admin`, `categories`, `curate`, `home`, `playback`, `playlists`, `tags`, `triage`.

## Routing

Top-level route table: `frontend/src/routes/router.tsx`.

Route tree summary:

| Path | Component | Loader |
|------|-----------|--------|
| `/login` | `LoginPage` | `redirectIfAuthenticated` |
| `/auth/return` | `AuthReturnPage` | — |
| `/` | `AppShellLayout` (shell) | `requireAuth` |
| `/` (index) | `HomePage` | — |
| `/categories/:styleId` | `CategoriesListPage` | — |
| `/categories/:styleId/:id` | `CategoryDetailPage` | — |
| `/categories/:styleId/:id/player` | redirect to `/categories/:styleId/:id` (old links) | — |
| `/triage/:styleId` | `TriageListPage` | — |
| `/triage/:styleId/:id` | `TriageDetailPage` | — |
| `/triage/:styleId/:id/buckets/:bucketId` | `BucketDetailPage` | — |
| `/curate/:styleId/:blockId/:bucketId` | `CurateSessionPage` | — |
| `/playlists/:id` | `PlaylistDetailPage` | — |
| `/admin` | `AdminLayout` | `requireAuth` + `requireAdmin` |
| `/admin/coverage` | `AdminCoveragePage` | — |
| `/admin/spotify-not-found` | `AdminSpotifyNotFoundPage` | — |
| `*` | `NotFoundPage` | — |

`CategoryDetailPage` has no player page of its own: on desktop the player sits beside the list, on a phone (`CategoryPlayerPanel phone`) above it once a track plays, as a compact card with buttons that move the track to another category of the style or take it out. A tap on a track scrolls the player under the app header; an auto-advance leaves the scroll alone.

The desktop list (`TracksTab`) is a table of one-line rows: names truncate, tags show the first four and a "+N", artists and labels link to their pages, both dates read `YYYY-MM-DD`, the speech-bubble column is the track's YouTube comment count (`comment_count`: the collector reads one page, so 100 shows as `100+`; `—` when not collected, disabled or failed; the playlist tiles show it on the meta line). A red × removes a track from the category (the row menu keeps playlists and Move to). The columns icon in the header picks the optional columns, per device in `localStorage` (`clouder.category_columns_hidden`, Length off by default); too many for the width scroll sideways inside the table.

### `requireAuth` loader

`frontend/src/auth/requireAuth.ts:5`

Awaits `bootstrapPromise()` (resolved once `AuthProvider` completes its first `/auth/refresh` attempt), then reads `getAuthSnapshot()`. Redirects to `/login` if status is not `authenticated`.

`redirectIfAuthenticated` is the inverse: bounces logged-in users away from `/login` to `/`.

### `requireAdmin` loader

`frontend/src/auth/requireAdmin.ts:5`

Same bootstrap await, then checks `snap.user.is_admin`. Redirects to `/` on any non-admin. Both checks are client-side only; the API enforces them server-side too.

## Vite proxy

`frontend/vite.config.ts`

The dev server proxies API calls to `VITE_API_BASE_URL` (from `frontend/.env.local`). Without the variable, `proxy` is `undefined` and all API routes fall through to the SPA, breaking `/auth/login` (it lands in `NotFoundPage`).

Two proxy categories:

**`BACKEND_ONLY_PREFIXES`** — always proxied to the API, no bypass:
`/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/logout`, `/me`, `/styles`, `/tracks`, `/artists`, `/labels`, `/albums`, `/runs`, `/collect_bp_releases`.

**`SPA_AWARE_PREFIXES`** — `/categories`, `/triage`, `/admin`:
These prefixes collide with SPA route paths. The proxy applies a `bypass` function: GET requests with `Accept: text/html` (browser navigations, F5, deep-link paste) return `/index.html` so react-router handles them. XHR/fetch calls with `Accept: application/json` are proxied to the backend.

`/auth/return` is a SPA-only route and is deliberately absent from both lists.

## Admin gating

Admin surfaces are gated at two levels:

1. **Route loader** (`requireAdmin`) — redirects non-admins to `/` before the admin page mounts. Evaluated on every navigation.
2. **UI** — the `Admin` nav item in `AppShellLayout` renders only when `auth.state.user.is_admin` is truthy.

The `is_admin` flag comes from the `/me` endpoint, stored in `AuthProvider` state after each `/auth/refresh` round-trip.

Admin-only routes:

- `GET /admin/coverage` → `AdminCoveragePage` — Beatport ingest coverage grid. The "Styles" popover (`StyleVisibilityPopover`) hides/shows styles via `PATCH /admin/styles/{style_id}`.
- `GET /admin/spotify-not-found` → `AdminSpotifyNotFoundPage` — tracks with no Spotify match.

`POST /admin/beatport/ingest` is the current ingestion endpoint (the older `POST /collect_bp_releases` is deprecated). Both share `_run_beatport_ingest` in the backend handler.

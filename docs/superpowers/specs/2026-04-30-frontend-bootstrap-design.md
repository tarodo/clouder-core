# Frontend Bootstrap — Auth + AppShell scaffold (A2)

**Date:** 2026-04-30
**Status:** Design (awaiting user review before writing-plans)
**Owners:** Roman (review), Claude (writing)
**Predecessors:**
- `docs/design_handoff/` — Mantine 9 handoff package (tokens, theme, page catalogs, spec sheet, OPEN_QUESTIONS, MANTINE_9_NOTES, a11y, i18n).
- `docs/superpowers/specs/2026-04-25-spec-A-user-auth-design.md` — backend auth design.
- `docs/frontend.md` — backend integration guide.
- `docs/openapi.yaml` — API contract.

---

## Goal

Bootstrap the CLOUDER frontend codebase inside `clouder-core` (monorepo, `frontend/` directory) and ship a working **sign-in flow + protected AppShell skeleton** with placeholder routes for every iter-2a destination (Home, Categories, Triage, Curate, Profile).

After this work merges, every subsequent iter-2a feature is a single PR that fills one placeholder route. Auth, routing, layout, theme, i18n, error envelope handling, API client, React Query, and CI are paid up-front and do not need to be revisited.

## Non-goals

- Implementing Home, Categories, Triage, Curate, or Profile content. They land as `<EmptyState>` "Coming soon" cards.
- Spotify Web Playback SDK integration (lands with PlayerCard tickets, P-24/P-25).
- Production deploy pipeline (CloudFront + S3). Ships against prod API via `pnpm dev` + Vite proxy. Public URL is a separate ticket.
- Dark theme. iter-2a locks `defaultColorScheme="light"` per OPEN_QUESTIONS Q1.
- E2E tests. Playwright lands once Categories CRUD provides enough UI surface to justify it.
- i18n languages other than EN. `react-i18next` infra ships from day one per `i18n.md`.

## Decisions log (from brainstorming)

| # | Topic | Decision | Why |
|---|---|---|---|
| 1 | Code location | Monorepo: `frontend/` directory inside `clouder-core`. | Solo dev, atomic contract+UI PRs, OpenAPI lives next to its consumer. |
| 2 | Build tool | Vite 5 + React 19 + TypeScript 5. **No Next.js.** | Auth-gated SPA, no SEO need, Spotify SDK is browser-only, Mantine 9 SSR adds friction without payoff. (React 19 chosen during T1 implementation: Mantine 9 line declares React 19 as a peer dep — the design handoff said "Mantine 9 / React 18+" but no Mantine 9 release ever supported React 18.) |
| 3 | Routing | `react-router` 7 data router (`createBrowserRouter`, `loader`/`action`/`errorElement`). | Loaders gate protected routes; `errorElement` standardises error UX. |
| 4 | API client | `openapi-typescript` for types from `docs/openapi.yaml` + 50-line hand-written `fetch` wrapper. **No `openapi-fetch` runtime.** | Free types, full control over 401-retry and refresh, zero runtime lock-in. |
| 5 | Auth state | React Context + `useReducer` in `AuthProvider`. **No Zustand, no localStorage for token.** | Small state, no extra dep, access token must stay in-memory (Q5 OPEN_QUESTIONS). |
| 6 | Server cache | `@tanstack/react-query` 5. | Standard idiom for SPA cache + retry + window-focus. |
| 7 | Forms | `@mantine/form` + `zod` via `schemaResolver`. | Per Mantine 9 handoff README. |
| 8 | Cross-origin auth | Vite dev-server proxy in dev (with `cookieDomainRewrite: 'localhost'`); CloudFront with `/api/*` behaviour in prod (separate ticket). | Single-origin keeps the `SameSite=Strict` refresh cookie working without backend changes. |
| 9 | OAuth callback | Spotify redirects to **SPA route `/auth/return`**, not API `/auth/callback`. SPA route fetches `/auth/callback` through proxy and reads JSON. Backend code unchanged; only `SPOTIFY_OAUTH_REDIRECT_URI` env value changes. | SPA-friendly OAuth pattern without backend HTML rendering. |
| 10 | Tests | Vitest + `@testing-library/react` + MSW. **No E2E in A2.** | Component+integration coverage is enough for the surface area; Playwright pays off once CRUD routes ship. |
| 11 | Pre-commit hooks | None. CI catches lint/type/test. | Solo dev; husky ceremony costs more than it saves at this scale. |

## Architecture

### Monorepo layout (additions only)

```
clouder-core/
├── frontend/                          # NEW
│   ├── package.json
│   ├── pnpm-lock.yaml
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── .env.example
│   ├── eslint.config.js
│   ├── public/                        # favicon, Geist + Geist Mono self-hosted
│   ├── src/
│   │   ├── main.tsx
│   │   ├── theme.ts                   # copy of docs/design_handoff/theme.ts
│   │   ├── tokens.css                 # copy of docs/design_handoff/tokens.css
│   │   ├── i18n/
│   │   │   ├── index.ts
│   │   │   ├── en.json
│   │   │   └── README.md              # domain-term policy
│   │   ├── api/
│   │   │   ├── schema.d.ts            # GENERATED via `pnpm api:types`
│   │   │   ├── client.ts              # fetch wrapper + 401-retry
│   │   │   ├── error.ts               # ApiError + envelope parser
│   │   │   └── queries/
│   │   │       └── useMe.ts
│   │   ├── auth/
│   │   │   ├── AuthProvider.tsx
│   │   │   ├── useAuth.ts
│   │   │   ├── tokenStore.ts          # in-memory singleton
│   │   │   ├── requireAuth.ts         # router loader
│   │   │   └── bootstrap.ts           # bootstrapPromise singleton
│   │   ├── routes/
│   │   │   ├── router.tsx
│   │   │   ├── _layout.tsx            # AppShell
│   │   │   ├── login.tsx              # P-01..P-03
│   │   │   ├── auth.return.tsx        # OAuth landing (SPA route)
│   │   │   ├── home.tsx               # EmptyState "Coming soon"
│   │   │   ├── categories.tsx         # EmptyState
│   │   │   ├── triage.tsx             # EmptyState
│   │   │   ├── curate.tsx             # EmptyState
│   │   │   └── profile.tsx            # EmptyState
│   │   ├── components/
│   │   │   ├── icons.ts               # tabler re-exports per spec sheet
│   │   │   ├── EmptyState.tsx
│   │   │   ├── HotkeyHint.tsx         # custom, NOT Mantine Kbd
│   │   │   ├── FullScreenLoader.tsx
│   │   │   ├── LongOperationOverlay.tsx
│   │   │   └── RouteErrorBoundary.tsx
│   │   ├── lib/
│   │   │   ├── queryClient.ts
│   │   │   ├── env.ts                 # zod-validated import.meta.env
│   │   │   └── useElapsedTime.ts
│   │   └── test/
│   │       ├── setup.ts
│   │       └── handlers.ts            # MSW handlers
│   ├── tests/
│   │   └── e2e/                       # empty placeholder for Phase 2
│   └── README.md
└── .github/workflows/pr.yml           # MODIFIED: add `frontend` job, gate `tests`/`alembic-check` on backend paths
```

No deletions. No moves. No backend code changes. One Terraform variable changes value (`spotify_oauth_redirect_uri`).

### Tech stack (locked)

```
runtime
  vite 5 · react 18 · typescript 5 · react-router 7
  @mantine/core 9 · @mantine/hooks · @mantine/dates · @mantine/form · @mantine/notifications
  @tabler/icons-react
  @tanstack/react-query 5
  zod 3
  react-i18next · i18next
  dayjs

devDeps
  openapi-typescript
  vitest · @testing-library/react · @testing-library/user-event · @testing-library/jest-dom
  msw
  eslint · @typescript-eslint · eslint-plugin-react-hooks · eslint-plugin-jsx-a11y
  prettier
  jsdom
```

### Vite proxy (dev)

```ts
// vite.config.ts
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_');
  const target = env.VITE_API_BASE_URL;       // e.g. https://abc123.execute-api.us-east-1.amazonaws.com
  const proxy = Object.fromEntries(
    ['/auth', '/me', '/categories', '/styles', '/tracks', '/artists', '/labels',
     '/albums', '/triage', '/runs', '/collect_bp_releases'].map(p => [
      p, {
        target,
        changeOrigin: true,
        secure: true,
        cookieDomainRewrite: 'localhost',  // strip Domain attr so Set-Cookie binds to localhost
      }
    ])
  );
  return {
    plugins: [react()],
    server: { proxy },
    resolve: { alias: { '@': '/src' } },
  };
});
```

`VITE_API_BASE_URL` from `.env.local`. Browser sees only `localhost:5173` — same-origin from its point of view. `cookieDomainRewrite: 'localhost'` makes the upstream `Set-Cookie` headers bind to localhost, so the `SameSite=Strict` refresh cookie (set by backend `_refresh_cookie`, see `auth_handler.py:620`) is sent back on subsequent `/auth/refresh` calls. Backend `Secure` attribute works on localhost because Chrome / Firefox treat localhost as a secure context.

### CI

`.github/workflows/pr.yml` — adjustments:

```yaml
on:
  pull_request:
    paths:
      - 'frontend/**'
      - 'src/**'
      - 'tests/**'
      - 'alembic/**'
      - 'requirements*.txt'
      - 'pytest.ini'
      - 'infra/**'
      - 'docs/openapi.yaml'   # frontend types depend on this
      - '.github/workflows/pr.yml'

jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      frontend: ${{ steps.filter.outputs.frontend }}
      backend:  ${{ steps.filter.outputs.backend }}
      infra:    ${{ steps.filter.outputs.infra }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            frontend:
              - 'frontend/**'
              - 'docs/openapi.yaml'
            backend:
              - 'src/**'
              - 'tests/**'
              - 'alembic/**'
              - 'requirements*.txt'
              - 'pytest.ini'
            infra:
              - 'infra/**'

  frontend:
    needs: changes
    if: needs.changes.outputs.frontend == 'true'
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with: { version: 9 }
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
      - run: pnpm install --frozen-lockfile
      - run: pnpm api:types && git diff --exit-code src/api/schema.d.ts
      - run: pnpm typecheck
      - run: pnpm lint
      - run: pnpm test
      - run: pnpm build

  tests:        # existing backend pytest job
    needs: changes
    if: needs.changes.outputs.backend == 'true'
    # ... existing steps

  alembic-check:
    needs: changes
    if: needs.changes.outputs.backend == 'true'
    # ... existing steps

  terraform:
    needs: changes
    if: needs.changes.outputs.infra == 'true'
    # ... existing steps
```

`pnpm api:types` regenerates `src/api/schema.d.ts` from `../docs/openapi.yaml`; CI fails if the diff is non-empty (catches stale generated types).

## OAuth flow (final)

```
[user] click "Sign in with Spotify"  on /login
   │
   └─ window.location = '/auth/login'
        │
        └─ Vite proxy → backend GET /auth/login
              │
              └─ 302 → https://accounts.spotify.com/authorize?...
                    │
                    └─ user approves
                          │
                          └─ Spotify redirect → ${SPA_ORIGIN}/auth/return?code=...&state=...
                                │
                                └─ SPA renders <AuthReturnPage>
                                      │
                                      ├─ useEffect: fetch('/auth/callback?code=...&state=...')
                                      │      │
                                      │      └─ Vite proxy → backend GET /auth/callback
                                      │            │
                                      │            └─ 200 JSON {access_token, user, ...}
                                      │              + Set-Cookie: refresh_token (HttpOnly, Secure, SameSite=Strict)
                                      │
                                      ├─ tokenStore.set(access_token)
                                      ├─ AuthProvider.signIn(user, access_token)
                                      └─ navigate('/', { replace: true })
```

**Backend change required:** Terraform var `spotify_oauth_redirect_uri` switches from `${API_GW}/auth/callback` to `${SPA_ORIGIN}/auth/return`. Dev value: `http://localhost:5173/auth/return`. Prod value lands with the CloudFront deploy ticket — until then, only dev URL is registered. Spotify Developer Dashboard accepts multiple redirect URIs simultaneously, so dev and prod URLs can coexist.

**Backend code:** unchanged. `_handle_callback` keeps returning JSON 200. The `oauth_redirect` cookie path that `_handle_login` sets is no longer used (pre-existing dead code; not in scope to remove).

## Components (in scope for A2)

Each unit is described as: **what it does · contract · dependencies**.

### `tokenStore` (`src/auth/tokenStore.ts`)

Module-level singleton holding the access token. Not React state — `apiClient` reads it without re-rendering.

```ts
let token: string | null = null;
export const tokenStore = {
  get: () => token,
  set: (t: string | null) => { token = t; },
};
```

Token never lands in `localStorage` / `sessionStorage` (XSS-stealable). Lost on hard reload — `AuthProvider` recovers via `POST /auth/refresh` on mount.

Depends on: nothing.

### `AuthProvider` (`src/auth/AuthProvider.tsx`)

Holds auth state in a Context. State machine:

```ts
type AuthState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'authenticated'; user: Me; expiresAt: number }
  | { status: 'unauthenticated' }
  | { status: 'error'; error: ApiError };
```

Public API via `useAuth()`:

- `state` — current auth state.
- `signIn(user, accessToken, expiresIn)` — sets `tokenStore`, schedules refresh timer 5 min before expiry, dispatches `authenticated`.
- `signOut()` — calls `POST /auth/logout`, clears `tokenStore`, clears React Query cache, dispatches `unauthenticated`, navigates `/login`.
- `refresh()` — calls `POST /auth/refresh`, on success updates `tokenStore` + reschedules timer; on failure dispatches `unauthenticated`.

On mount: dispatches `loading`, calls `refresh()` once, resolves `bootstrapPromise` (used by `requireAuth`).

Depends on: `apiClient`, `tokenStore`, `bootstrapPromise`, `react-router` navigate.

### `bootstrapPromise` (`src/auth/bootstrap.ts`)

Promise that resolves when `AuthProvider` finishes its initial bootstrap. Used by `requireAuth` loader (which cannot consume Context):

```ts
let resolveBootstrap: () => void;
export const bootstrapPromise = new Promise<void>(r => { resolveBootstrap = r; });
export const completeBootstrap = () => resolveBootstrap();
```

`AuthProvider` calls `completeBootstrap()` after first refresh attempt (success or failure).

### `apiClient` (`src/api/client.ts`)

Wraps `fetch`. ~50 lines.

```ts
async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const token = tokenStore.get();
  const headers = new Headers(init?.headers);
  headers.set('Accept', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init?.body) headers.set('Content-Type', 'application/json');

  const res = await fetch(path, { ...init, headers, credentials: 'include' });

  if (res.status === 401 && token) {
    const refreshed = await tryRefreshOnce();
    if (refreshed) {
      headers.set('Authorization', `Bearer ${tokenStore.get()}`);
      return retry(path, { ...init, headers });
    }
    notifyAuthFailure();
    throw await ApiError.from(res);
  }

  if (!res.ok) throw await ApiError.from(res);
  if (res.status === 204) return undefined as T;
  return res.json();
}
```

`tryRefreshOnce` is debounced — concurrent 401s share one refresh promise.
`notifyAuthFailure` dispatches an `auth:expired` `CustomEvent` that `AuthProvider` listens for (avoids circular import).

Depends on: `tokenStore`, `ApiError`.

### `ApiError` (`src/api/error.ts`)

```ts
export class ApiError extends Error {
  constructor(
    readonly code: string,
    readonly status: number,
    message: string,
    readonly correlationId?: string,
    readonly raw?: unknown,
  ) { super(message); }

  static async from(res: Response): Promise<ApiError> {
    const correlationId = res.headers.get('x-correlation-id') ?? undefined;
    let body: unknown = null;
    try { body = await res.json(); } catch { /* HTML / empty */ }

    if (body && typeof body === 'object' && 'error_code' in body) {
      const b = body as { error_code: string; message: string };
      return new ApiError(b.error_code, res.status, b.message, correlationId, body);
    }
    if (res.status === 503 && body && typeof body === 'object' && 'message' in body
        && (body as any).message === 'Service Unavailable') {
      return new ApiError('cold_start', 503, 'Backend warming up', correlationId, body);
    }
    return new ApiError('unknown', res.status, res.statusText, correlationId, body);
  }
}
```

### `queryClient` (`src/lib/queryClient.ts`)

```ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) =>
        err instanceof ApiError &&
        err.code !== 'forbidden' && err.code !== 'not_found' &&
        count < 2,
      staleTime: 30_000,
      refetchOnWindowFocus: false,
    },
    mutations: { retry: false },
  },
});
```

### `useMe` (`src/api/queries/useMe.ts`)

```ts
export const useMe = () =>
  useQuery({ queryKey: ['me'], queryFn: () => api<Me>('/me') });
```

Only this query in A2. Pattern repeated for every subsequent endpoint.

### `requireAuth` loader (`src/auth/requireAuth.ts`)

```ts
export const requireAuth: LoaderFunction = async () => {
  await bootstrapPromise;
  const snap = getAuthSnapshot();           // module-level singleton mirror of state
  if (snap.status === 'authenticated') return null;
  throw redirect('/login');
};
```

Pairs with `redirectIfAuthenticated` for `/login` and `/auth/return`:

```ts
export const redirectIfAuthenticated: LoaderFunction = async () => {
  await bootstrapPromise;
  if (getAuthSnapshot().status === 'authenticated') throw redirect('/');
  return null;
};
```

### Router (`src/routes/router.tsx`)

```ts
export const router = createBrowserRouter([
  { path: '/login', element: <LoginPage />, loader: redirectIfAuthenticated, errorElement: <RouteErrorBoundary /> },
  { path: '/auth/return', element: <AuthReturnPage />, errorElement: <RouteErrorBoundary /> },
  {
    element: <AppShellLayout />,
    loader: requireAuth,
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: '/', element: <HomePage /> },
      { path: '/categories', element: <CategoriesPage /> },
      { path: '/triage', element: <TriagePage /> },
      { path: '/curate', element: <CuratePage /> },
      { path: '/profile', element: <ProfilePage /> },
    ],
  },
  { path: '*', element: <NotFoundPage /> },
]);
```

### Pages

| Route | Implementation in A2 | Spec |
|---|---|---|
| `/login` | Hero with "Sign in with Spotify" CTA. P-02 / P-03 substates derived from `error.code` query param after failed return. | Pages catalog Pass 1 P-01..P-03 |
| `/auth/return` | OAuth landing. `<FullScreenLoader>` while exchanging, `<P03ErrorState>` on failure. | Custom (no spec — hidden state) |
| `/` Home | `<EmptyState>` "Home — coming soon" with link back hint. | Pages catalog S-02 EmptyState exemplar |
| `/categories` | `<EmptyState>` "Categories — coming soon" | S-02 |
| `/triage` | `<EmptyState>` "Triage — coming soon" | S-02 |
| `/curate` | `<EmptyState>` "Curate — coming soon" | S-02 |
| `/profile` | `<EmptyState>` "Profile — coming soon" + sign-out button (only working profile feature in A2). | S-02 |

### `AppShellLayout` (`src/routes/_layout.tsx`)

Mantine `<AppShell>`:

- `>=md` (64em): `navbar` left rail, 5 items (Home/Categories/Triage/Curate/Profile) using `@tabler/icons-react`.
- `<md`: `footer` bottom tabs, same 5 items.
- `header`: CLOUDER wordmark + `<UserMenu>` (display name, sign-out) on right.
- `<Outlet />` in `main`.

Responsive flip via Mantine 9 `useMatches({ base: 'mobile', md: 'desktop' })` per handoff README.

`<UserMenu>` reads `useAuth()` — display name from `state.user`.

### `EmptyState` (`src/components/EmptyState.tsx`)

Per `04 Component spec sheet.html` § EmptyState. Props:

```ts
type EmptyStateProps = {
  title: string;
  body?: string;
  icon?: ReactNode;
  action?: { label: string; onClick: () => void };
};
```

### `LongOperationOverlay` + `useElapsedTime` (`src/components/`, `src/lib/`)

Cascading copy on long ops (B7 from brief). Not used in A2 (auth is fast) — defined and exported so feature tickets can drop it in.

### Icons (`src/components/icons.ts`)

Re-export `@tabler/icons-react` per Icon mapping in spec sheet:

```ts
export {
  IconHome, IconCategory, IconLayoutColumns, IconAdjustments, IconUser,
  IconPlayerPlay, IconPlayerPause, IconPlayerSkipForward, IconPlayerSkipBack,
  IconChevronUp, IconChevronDown, IconDots, IconCopy, IconLogout,
} from '@tabler/icons-react';
```

Single source for icon swaps if Mantine ever changes recommended set.

### i18n (`src/i18n/`)

`react-i18next` initialised in `src/i18n/index.ts`. EN-only `en.json` flat-by-screen keys (`auth.signin`, `errors.cold_start`, etc.). Domain terms `NEW`/`OLD`/`NOT`/`DISCARD`/`UNCLASSIFIED`/`FINALIZED`/`BPM`/`key` excluded from translation per `i18n.md`.

A2 only adds keys that A2 actually renders (auth + AppShell labels + EmptyState placeholders + error toasts). Other strings land with the feature ticket that uses them.

## Data flow

### Bootstrap (page load)

```
main.tsx
   └─ MantineProvider + i18n init + tokens.css imported
       └─ QueryClientProvider
           └─ AuthProvider
                ├─ dispatch loading
                ├─ refresh()
                │     ├─ ok  → tokenStore.set(token), dispatch authenticated, schedule timer
                │     └─ 401 → dispatch unauthenticated
                └─ completeBootstrap()
           └─ <RouterProvider>
                └─ requireAuth (waits on bootstrapPromise) → redirect or render
```

### Authenticated request

```
useMe() → useQuery → queryFn = api('/me')
            ├─ tokenStore.get() → Authorization header
            ├─ ok → return Me
            └─ 401 → tryRefreshOnce
                       ├─ ok  → retry api('/me') with new token
                       └─ fail → dispatch CustomEvent 'auth:expired'
                                   → AuthProvider listens, dispatches unauthenticated
                                   → router redirects /login on next nav
```

### Sign-out

```
POST /auth/logout (cookie revoked server-side)
   ├─ tokenStore.set(null)
   ├─ queryClient.clear()
   ├─ dispatch unauthenticated
   └─ navigate('/login')
```

### Token refresh timer

`AuthProvider` schedules `setTimeout(refresh, expires_in_ms - 5*60*1000)` on every authenticated transition (signIn or refresh). Cleared on signOut and unmount.

## Error handling

### Layers

| Layer | Catches | Behaviour |
|---|---|---|
| `apiClient` | HTTP errors, network errors, body-parse errors | Throws `ApiError`. |
| React Query | Throws from queryFn / mutationFn | Maps to `query.error: ApiError`; UI reads `query.isError` + `error.code`. |
| Router `errorElement` | Throws from loaders, actions, route render | `<RouteErrorBoundary>` full-page state with retry. |
| Top-level `<ErrorBoundary>` | React render errors | Full-page P-03 generic error + "Reload app". |

### Error code mapping

| `error.code` | HTTP | UX |
|---|---|---|
| `validation_error` | 400 | Inline under form (Mantine form validators handle most). |
| `unauthorized` | 401 | Transparent refresh-retry. Second 401 → signOut + `/login`. |
| `forbidden` | 403 | `<EmptyState>` "Not yours" + back home. |
| `not_found` | 404 | `<EmptyState>` "Not found" + back link. |
| `cold_start` | 503 (API GW) | Toast "Backend warming up, retrying…" + auto-retry once after 3s. Second failure → toast with manual retry button. |
| `server_error` | 5xx | Red Mantine notification + retry button. Includes `correlation_id`. |
| network failure | — | Toast "Connection lost". React Query auto-retries per defaults. |
| `unknown` | — | Generic toast with `correlation_id` for debug. |

### Long-operation copy (B7)

Stages, controlled by `useElapsedTime`:

- `t < 5s` — spinner on CTA, surrounding UI disabled.
- `5s ≤ t < 15s` — `<Loader>` overlay + "Cold start, hang on…".
- `t ≥ 15s` — warning copy "Это занимает дольше обычного. Если ничего не произойдёт — обновите страницу, операция могла уже выполниться."

Not exercised in A2 (auth is fast). Component lands so feature tickets reuse it.

## Testing

| Level | Tool | A2 coverage |
|---|---|---|
| Unit | Vitest | `apiClient` 401-retry, `tokenStore`, `ApiError.from`, `requireAuth`/`redirectIfAuthenticated` loaders, `env.ts` zod validation. |
| Component | Vitest + `@testing-library/react` | `AuthProvider` reducer transitions, `LoginPage` CTA, `AuthReturnPage` success + failure, `AppShellLayout` responsive (mock `useMatches`), `EmptyState` rendering, `UserMenu` sign-out. |
| Integration | Vitest + MSW | Bootstrap → authenticated, bootstrap → unauthenticated, sign-in flow, 401-refresh-retry, 401 fail → unauthenticated, sign-out. |
| E2E | Playwright | Deferred to Phase 2 (after Categories CRUD lands). |

`pnpm test` = vitest. `pnpm test --coverage` for local coverage check; no enforced threshold in CI.

### MSW handlers (`src/test/handlers.ts`)

```ts
http.get('/me', ({ request }) => {
  const auth = request.headers.get('Authorization');
  if (!auth?.startsWith('Bearer ')) return HttpResponse.json(errEnv('unauthorized'), { status: 401 });
  return HttpResponse.json(meFixture);
}),
http.post('/auth/refresh', () => HttpResponse.json({ access_token: 'fresh', expires_in: 1800, ... })),
http.post('/auth/logout', () => HttpResponse.json({ ok: true })),
http.get('/auth/callback', () => HttpResponse.json(callbackFixture)),
```

### Lint / typecheck

- ESLint flat config: `@typescript-eslint`, `react-hooks`, `jsx-a11y`.
- `tsc -b --noEmit` strict.
- Prettier on save (no pre-commit hook).

## Backend / infra coordination

Single change required outside `frontend/`:

- `infra/terraform.tfvars` (or whatever ops file holds it): `spotify_oauth_redirect_uri = "http://localhost:5173/auth/return"` for dev, plus the prod URL once CloudFront ships.
- Spotify Developer Dashboard: add `http://localhost:5173/auth/return` to redirect URI whitelist.

CORS on API Gateway is **not required for dev** under Vite proxy: browser sees only `localhost:5173`, fetch never hits API GW directly. Leave `cors_allowed_origins` empty in `terraform.tfvars` for dev. CORS becomes relevant only if a future ticket bypasses the proxy (e.g., direct API GW calls from a separately-hosted SPA without CloudFront), at which point the prod origin gets added. Document this carve-out in `frontend/README.md`.

## Rollout

1. PR introduces `frontend/` directory, `.github/workflows/pr.yml` adjustments, README pointer from repo root.
2. CI green: typecheck, lint, vitest, build, OpenAPI types diff-check.
3. Manual smoke: `pnpm dev` → visit `localhost:5173` → click sign-in → Spotify OAuth → `/auth/return` → land on `/` AppShell → see Home "Coming soon".
4. Feature tickets land one-by-one filling each placeholder route.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| OpenAPI drifts from backend, types stale | CI runs `pnpm api:types` and fails on diff. |
| Refresh cookie blocked in dev | Vite proxy keeps single-origin; `credentials: 'include'` works under same-origin. |
| Spotify rejects `localhost:5173/auth/return` redirect URI | Dashboard whitelist includes it explicitly. Documented in README. |
| AppShell responsive bug between 64em flips | Component tests mock `useMatches`; manual QA at 420px / 768px / 1280px before merge. |
| Bundle size grows (Mantine + Tabler + Spotify SDK) | Vite `build.rollupOptions.output.manualChunks` for Mantine/Tabler split. Tracked, not optimised in A2. |

## After this lands

The next iter-2a tickets (one PR each):

1. Home / Dashboard (P-05..P-08) — uses style switcher, this-week active blocks.
2. Categories CRUD (P-09..P-12) — spec-C endpoints + reorder.
3. Triage list + create modal + detail (P-13..P-21) — spec-D endpoints.
4. Curate mobile + desktop (P-22..P-23) — destination buttons + hotkeys.
5. PlayerCard + sticky mini + Device picker (P-24..P-25) — Spotify SDK integration.
6. Patterns polish — S-01..S-10 loading/empty/error parity audit.
7. Phase 2: Playwright E2E suite covering full curation session.
8. Production deploy: CloudFront + S3 Terraform module, custom domain optional.

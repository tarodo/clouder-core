# CLOUDER frontend

React SPA built with Vite, TypeScript, Mantine 9. Lives in the `clouder-core`
monorepo so contract changes (OpenAPI, Terraform) and UI changes can ship in a
single PR.

## Prerequisites

- Node.js ≥ 22
- pnpm ≥ 9 (`corepack enable && corepack prepare pnpm@9 --activate`)
- A working backend at `${VITE_API_BASE_URL}` (the Beatport collector API
  Gateway URL — get it via `cd infra && terraform output -raw api_endpoint`).
- Spotify Developer Dashboard application with `http://localhost:5173/auth/return`
  in the Redirect URIs whitelist.

## Setup

```bash
cd frontend
cp .env.example .env.local
# edit .env.local, set VITE_API_BASE_URL to the API Gateway invoke URL
pnpm install
pnpm api:types          # regenerate src/api/schema.d.ts from ../docs/openapi.yaml
```

## Scripts

| Command | Description |
|---|---|
| `pnpm dev` | Start Vite dev server on http://localhost:5173 |
| `pnpm build` | Type-check + production build into `dist/` |
| `pnpm preview` | Preview the production build locally |
| `pnpm typecheck` | `tsc --noEmit` strict |
| `pnpm lint` | ESLint over `src/` |
| `pnpm test` | Vitest single run (jsdom + RTL + MSW) |
| `pnpm test:watch` | Vitest watch mode |
| `pnpm test:coverage` | Coverage report (no enforced threshold) |
| `pnpm api:types` | Regenerate API types from `../docs/openapi.yaml` |

## Architecture (short version)

- **Routing:** `react-router` 7 data router (`createBrowserRouter` in
  `src/routes/router.tsx`). Protected routes share a `requireAuth` loader that
  awaits a `bootstrapPromise` resolved by `AuthProvider`.
- **Auth:** `AuthProvider` (`src/auth/`) holds state in a `useReducer`.
  Access token sits in a module-level singleton (`tokenStore`) so the `fetch`
  wrapper can read it without re-rendering. Refresh cookie is HttpOnly +
  `SameSite=Strict`; we keep it usable in dev by running same-origin via the
  Vite proxy with `cookieDomainRewrite: 'localhost'`.
- **API:** `src/api/client.ts` is a 100-line `fetch` wrapper with 401-retry,
  envelope parsing into `ApiError`, and a debounced refresh path. Types come
  from `pnpm api:types` (committed at `src/api/schema.d.ts`).
- **Server cache:** `@tanstack/react-query`. Hooks live in `src/api/queries/`.
- **Theme:** `tokens.css` (CSS variables) + `theme.ts` (Mantine projection),
  copied verbatim from `docs/design_handoff/`. Don't drift — re-copy when
  the handoff is updated.
- **i18n:** `react-i18next` initialised in `src/i18n/index.ts`. EN-only this
  iteration. Domain terms (NEW/OLD/NOT/DISCARD/BPM/key) are not translated.

## OAuth flow

```
[user] click "Sign in with Spotify" on /login
  → window.location = '/auth/login'
  → Vite proxy → backend GET /auth/login
  → 302 → Spotify
  → user approves
  → Spotify redirect → http://localhost:5173/auth/return?code=...&state=...
  → SPA <AuthReturnPage>
       └─ fetch('/auth/callback?code=...&state=...')
            └─ Vite proxy → backend
                 └─ 200 JSON {access_token, expires_in, user}
                   + Set-Cookie: refresh_token (HttpOnly, Secure, SameSite=Strict;
                                                rewritten to Domain=localhost)
       └─ tokenStore.set(access_token); AuthProvider.signIn(...)
       └─ navigate('/', { replace: true })
```

## Adding a new endpoint

1. Backend ships the route → `pnpm api:types` regenerates `src/api/schema.d.ts`.
2. Add a query/mutation hook under `src/api/queries/`.
3. Use it from a route file. The `apiClient` handles auth + 401-retry.

## Backend coordination

- Spotify Developer Dashboard must include `http://localhost:5173/auth/return`
  in Redirect URIs.
- `infra/terraform.tfvars` must set `spotify_oauth_redirect_uri =
  "http://localhost:5173/auth/return"` (dev). Prod URL ships with the
  CloudFront ticket.
- CORS on API Gateway is **not** required under the Vite proxy: the browser
  only sees `localhost:5173`. Leave `cors_allowed_origins = []` unless a
  future ticket bypasses the proxy.

## What this scope ships

Sign-in, sign-out, AppShell with responsive nav, placeholders for Home /
Categories / Triage / Curate / Profile. Each placeholder lands as a separate
PR filling in the spec for that page.

## What this scope explicitly does NOT ship

- Spotify Web Playback SDK (lands with PlayerCard / Curate tickets).
- Production hosting (CloudFront + S3 + custom domain — separate ticket).
- Dark theme (iter-2b).
- Playwright E2E (Phase 2 once Categories CRUD lands).

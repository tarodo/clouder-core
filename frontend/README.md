# CLOUDER frontend

React 19 + Vite 5 + TypeScript 5 + Mantine 9 SPA. Lives in the `clouder-core`
monorepo so backend contract changes (OpenAPI, Terraform) and UI changes can
ship in a single PR.

---

## Quick start (local dev)

```bash
cd frontend
cp .env.example .env.local
# edit .env.local — set VITE_API_BASE_URL to the prod API Gateway URL:
#   echo "VITE_API_BASE_URL=$(cd ../infra && terraform output -raw api_endpoint)" > .env.local
pnpm install
pnpm api:types          # regenerate src/api/schema.d.ts from ../docs/openapi.yaml
pnpm dev
# open http://127.0.0.1:5173/
```

> **Important:** open `127.0.0.1`, **not** `localhost`. The Spotify whitelist
> and Lambda env var both pin `127.0.0.1`; opening `localhost` will fail
> OAuth. See [Local dev hits prod backend](#local-dev-hits-prod-backend).

### Prerequisites

- Node.js ≥ 22 (Node 25 works; the `engines.node` field accepts ≥ 22)
- pnpm ≥ 9 (`corepack enable && corepack prepare pnpm@9.12.3 --activate`)
- AWS CLI authenticated against the account that owns the prod backend
  (needed only when you want to read the API GW URL via `terraform output`)
- Spotify Developer Dashboard application with `http://127.0.0.1:5173/auth/return`
  in the Redirect URIs whitelist
- Lambda env var `SPOTIFY_OAUTH_REDIRECT_URI` set to the same URL on the
  `beatport-prod-auth-handler` function (see [Backend coordination](#backend-coordination))

---

## Scripts

| Command | Description |
|---|---|
| `pnpm dev` | Start Vite dev server on `http://127.0.0.1:5173` |
| `pnpm build` | Type-check + production build into `dist/` |
| `pnpm preview` | Preview the production build locally |
| `pnpm typecheck` | `tsc --noEmit` strict |
| `pnpm lint` | ESLint over `src/` |
| `pnpm test` | Vitest single run (jsdom + RTL + MSW) |
| `pnpm test:watch` | Vitest watch mode |
| `pnpm test:coverage` | Coverage report (no enforced threshold) |
| `pnpm api:types` | Regenerate API types from `../docs/openapi.yaml` |

---

## Architecture (short version)

- **Routing:** `react-router` 7 data router (`createBrowserRouter` in
  `src/routes/router.tsx`). Protected routes share a `requireAuth` loader
  that awaits a `bootstrapPromise` resolved by `AuthProvider`.
- **Auth:** `AuthProvider` (`src/auth/`) holds state in a `useReducer`.
  The access token sits in a module-level singleton (`tokenStore`) so the
  `fetch` wrapper can read it without re-rendering. The refresh cookie is
  HttpOnly + `Secure` + `SameSite=Strict`; the Vite proxy strips its
  `Domain` attribute so it binds host-only on the dev origin.
- **API:** `src/api/client.ts` is a ~100-line `fetch` wrapper with
  401-retry, envelope parsing into `ApiError`, and a debounced refresh
  path. Types come from `pnpm api:types` (committed at
  `src/api/schema.d.ts`).
- **Server cache:** `@tanstack/react-query`. Hooks live in
  `src/api/queries/`.
- **Theme:** `tokens.css` (CSS variables) + `theme.ts` (Mantine
  projection), copied verbatim from `docs/design_handoff/`. Don't drift —
  re-copy when the handoff is updated.
- **i18n:** `react-i18next` initialised in `src/i18n/index.ts`. EN-only
  this iteration. Domain terms (NEW/OLD/NOT/DISCARD/BPM/key) are not
  translated.

---

## OAuth flow (dev)

```
[user] click "Sign in with Spotify" on /login
  → window.location = '/auth/login'
  → Vite proxy → backend GET /auth/login
  → 302 → Spotify
  → user approves
  → Spotify redirect → http://127.0.0.1:5173/auth/return?code=...&state=...
  → SPA <AuthReturnPage>
       └─ useRef-guarded fetch('/auth/callback?code=...&state=...')
            └─ Vite proxy → backend
                 └─ 200 JSON {access_token, expires_in, user}
                   + Set-Cookie: refresh_token
                       (HttpOnly, Secure, SameSite=Strict, no Domain attr)
       └─ tokenStore.set(access_token); AuthProvider.signIn(...)
       └─ navigate('/', { replace: true })

[page reload]
  → AuthProvider bootstrap
       └─ POST /auth/refresh        (rotates the refresh cookie)
       └─ GET  /me                  (rebuild user; refresh response carries
                                     only tokens, not user info)
       └─ signIn → render AppShell
```

---

## Adding a new endpoint

1. Backend ships the route → `pnpm api:types` regenerates
   `src/api/schema.d.ts`.
2. Add a query/mutation hook under `src/api/queries/`.
3. Use it from a route file. The `apiClient` handles auth + 401-retry.

---

## Local dev hits prod backend

**This is the current setup.** The Vite proxy forwards every API request
to `${VITE_API_BASE_URL}` (the prod API Gateway URL). There is no local
backend.

Implications:

- Every dev sign-in creates a session row in **prod** Aurora.
- Every dev category, triage block, etc. is a **prod** record.
- Mistakes in `frontend/` cannot brick the backend, but reading the wrong
  endpoint will read prod data.

This is acceptable for a solo-dev pre-public iteration but is the first
thing to fix once a second person joins or once shareable URLs are
needed. See [Future: isolated environments](#future-isolated-environments).

---

## Production deployment (NOT in this scope)

The frontend runs only via `pnpm dev` today. Production hosting lands in
a follow-up ticket. The plan:

- **Static hosting:** S3 bucket fronted by CloudFront, with
  `default → S3` and `path /api/* → API Gateway` cache behaviours so the
  prod SPA and prod API share an origin (no CORS headache).
- **Custom domain (optional):** Route 53 record + ACM certificate in
  us-east-1 (CloudFront only accepts certs from us-east-1).
- **Spotify whitelist:** add the prod redirect URI alongside the dev one.
- **Lambda env:** `SPOTIFY_OAUTH_REDIRECT_URI` must be reset on every
  prod deploy to point at the prod URL — the dev override applied via
  AWS CLI today drifts from `infra/terraform.tfvars`. See [Known dev
  drift](#known-dev-drift).

Estimated cost for the audience scale: < $1/month CloudFront + S3.

---

## Future: isolated environments

Once we want to iterate on the backend without breaking prod data,
two paths exist. Pick one — they don't compose well.

### Option A: Local Lambda in Docker

Run the Lambda code locally inside the AWS Lambda runtime container,
hit it from the Vite proxy.

- **Tools:** [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/serverless-sam-cli-install.html)
  + Docker Desktop. `sam local start-api` mounts the Python source and
  serves a local API Gateway emulator on `http://127.0.0.1:3000`.
- **Pros:** zero extra AWS spend, fast iteration, deterministic
  environment, fully offline.
- **Cons:**
  - Aurora Serverless v2 cannot run in LocalStack — you still need a
    real Aurora cluster (or Postgres-in-Docker as a stand-in, with the
    risk of drift from RDS Data API behaviour).
  - Spotify OAuth tokens cannot be encrypted with KMS locally without
    running LocalStack pro tier.
  - Cold-start, IAM auth quirks, and API GW behaviours (29 s timeout,
    503 cold-start envelopes) don't surface locally.
  - Adds ~15 minutes to onboarding for every new contributor.

Verdict: only worth it if backend code churns daily and prod-blast
radius hurts. Today the backend is stable.

### Option B: Separate AWS environment (dev + prod)

Stand up a parallel Terraform stack named `clouder-dev`, deploy the
Lambdas + Aurora there, point `frontend/.env.local` at the dev API GW.

- **Tools:** Terraform workspaces, or a separate state file per env.
- **Pros:**
  - Real AWS — what you test is what ships. RDS Data API, Lambda cold
    starts, KMS encryption all behave identically.
  - Prod data is untouched. Wreck dev however you want.
  - First step toward a "staging" environment when a second person
    joins.
- **Cons:**
  - ~$60–80/month: one Aurora Serverless v2 cluster (min ACU 0.5,
    ~$43/mo) + duplicated Lambdas (free tier mostly covers them) +
    duplicated KMS keys + duplicated CloudFront if you also stage the
    SPA.
  - Terraform refactor: bind every resource name to a variable so
    `clouder-dev-*` and `clouder-prod-*` can coexist. The current code
    hard-codes `beatport-prod-` via `var.project + var.environment` —
    re-deploying with `var.environment = "dev"` should mostly work
    (per `CLAUDE.md`), but the S3 backend key is hard-coded to
    `clouder-core/prod/...` and needs splitting.
  - Spotify Developer Dashboard whitelist must include all three
    redirect URIs (prod, dev, localhost dev).

Verdict: the more sensible choice for solo-to-small-team. Defer until
the backend rate of change increases or a second person needs to
break things safely.

### Recommendation

Stay on the current "Vite proxy → prod" setup until either trigger
fires:

1. The backend gets touched ≥ weekly and prod blast radius starts
   hurting.
2. Someone else joins the project.

Then jump straight to **Option B** (separate AWS env). Option A is a
local optimisation that pays back only for very high backend churn,
which CLOUDER doesn't have.

---

## Backend coordination

The dev frontend talks to the prod backend, so a few backend knobs
must be aligned:

| Item | Required value (dev) | Where it lives |
|---|---|---|
| Spotify Developer Dashboard → Redirect URIs | `http://127.0.0.1:5173/auth/return` | Spotify console |
| Lambda env `SPOTIFY_OAUTH_REDIRECT_URI` on `beatport-prod-auth-handler` | `http://127.0.0.1:5173/auth/return` | AWS Lambda (set via `terraform apply` or CLI) |
| Terraform var `spotify_oauth_redirect_uri` in `infra/terraform.tfvars` | `http://127.0.0.1:5173/auth/return` | local file (not committed) |
| CORS on API Gateway (`cors_allowed_origins`) | empty `[]` | `infra/terraform.tfvars` |

CORS is not required while the SPA goes through the Vite proxy — the
browser only ever sees `127.0.0.1:5173`.

### Updating the Lambda env var

Two paths:

```bash
# Option 1 — Terraform (preferred, but currently broken locally; see
# "Known dev drift" below):
cd infra
terraform init -input=false \
  -backend-config="bucket=beatport-prod-tfstate-223458487728" \
  -backend-config="key=clouder-core/prod/terraform.tfstate" \
  -backend-config="region=us-east-1" \
  -backend-config="dynamodb_table=beatport-prod-tf-locks" \
  -backend-config="encrypt=true"
terraform apply

# Option 2 — AWS CLI direct (used during smoke-testing this scaffold):
aws lambda get-function-configuration \
  --function-name beatport-prod-auth-handler \
  --query 'Environment' --output json | python3 -c "
import json, sys
env = json.load(sys.stdin)
env['Variables']['SPOTIFY_OAUTH_REDIRECT_URI'] = 'http://127.0.0.1:5173/auth/return'
print(json.dumps(env, indent=2))
" > /tmp/auth-handler-env.json
aws lambda update-function-configuration \
  --function-name beatport-prod-auth-handler \
  --environment file:///tmp/auth-handler-env.json
aws lambda wait function-updated --function-name beatport-prod-auth-handler
```

---

## Known dev drift

A handful of things you should fix before the next major iteration. None
block local dev today, but they will bite later.

1. **`scripts/package_lambda.sh:8` invokes bare `python`.** macOS only
   ships `python3`. Until this is fixed, `terraform apply` fails locally
   with `Call to function "filebase64sha256" failed: open
   .../dist/collector.zip: no such file or directory`. CI works (uses
   Python 3.12 from the `setup-python` action).
2. **Lambda `SPOTIFY_OAUTH_REDIRECT_URI` was set via AWS CLI**, not via
   `terraform apply`. The next prod deploy will revert it to whatever
   `infra/terraform.tfvars` says. The local `tfvars` already says
   `http://127.0.0.1:5173/auth/return`, so the next deploy is a no-op
   diff — but re-verify after every deploy.
3. **`frontend/src/theme.ts:277`** carries an unused
   `eslint-disable @typescript-eslint/no-empty-interface` comment. It's
   verbatim from `docs/design_handoff/theme.ts`; fix upstream so we can
   re-copy.
4. **Bundle size warning** at build time: `dist/assets/index-*.js` is
   ~544 KB minified (Mantine + Tabler + react-query + react-router). For
   iter-2a this is acceptable. Add `build.rollupOptions.output.manualChunks`
   when feature tickets start importing additional Mantine surface area.

---

## Smoke-test gotchas (what the design didn't anticipate)

These bugs surfaced only after wiring the full OAuth round-trip end-to-end
against the real backend. The fixes are committed and live in code; this
section just preserves the lessons so the next dev doesn't rediscover them.

| Symptom | Root cause | Fix |
|---|---|---|
| Browser: `127.0.0.1 refused to connect` | Vite default `localhost` binds IPv6 (`::1`) only on Node 22+; Spotify redirects to `127.0.0.1` | `server.host: '127.0.0.1'` in `vite.config.ts` |
| `/auth/return?code=…` returns API GW 404 `{"message":"Not Found"}` | Proxy prefix `/auth` was matching the SPA route too, sending it to API GW | Narrow proxy list to specific backend endpoints; `/auth/return` stays in SPA |
| OAuth callback: `oauth_exchange_failed: HTTP 400` after a successful first response | React 18 StrictMode runs effects twice; both fired `/auth/callback`; Spotify `code` is single-use, second call gets 400 | `useRef` guard outside the effect closure to dedupe the fetch |
| "Signing you in…" hangs forever despite a 200 from `/auth/callback` | The same StrictMode cleanup toggled the in-effect `cancelled` boolean to true *before* the first response arrived | Remove the `cancelled` flag — the `useRef` already prevents duplicate work |
| Refresh cookie set but not sent on subsequent requests | `cookieDomainRewrite: 'localhost'` rewrote the upstream `Set-Cookie` to bind `Domain=localhost`, which the browser refuses to send to a `127.0.0.1` origin | `cookieDomainRewrite: ''` strips `Domain` so the cookie binds host-only on the actual origin |
| Every page reload bounces back through Spotify OAuth | Bootstrap effect fired `/auth/refresh` twice in StrictMode; second call hit backend replay-detection (rotated hash mismatch) and revoked all sessions | `bootstrapStarted` ref outside the effect; bootstrap runs exactly once |
| `state.user` undefined after refresh, AppShell crashes on render | `/auth/refresh` returns only tokens, not user; old code wired `body.user` (undefined) into `signIn` | Fetch `/me` after `/auth/refresh` succeeds, then `signIn(user, …)` |
| Just-authenticated user redirected to `/login` | `getAuthSnapshot()` was mirrored via `useEffect`; the mirror runs only on the next render, but `completeBootstrap()` resolves immediately, so `requireAuth` reads the stale `'loading'` snapshot | Update `snapshot` synchronously inside every dispatching helper (`signIn`, `signOut`, `refresh`'s catch, listeners, bootstrap) — keep the mirror effect as a safety net |

---

## What this scope ships

Sign-in, sign-out, AppShell with responsive nav, placeholders for Home /
Categories / Triage / Curate / Profile. Each placeholder lands as a
separate PR filling in the spec for that page.

## What this scope explicitly does NOT ship

- Spotify Web Playback SDK (lands with PlayerCard / Curate tickets).
- Production hosting (CloudFront + S3 + custom domain — separate ticket).
- Dark theme (iter-2b).
- Playwright E2E (Phase 2 once Categories CRUD lands).
- Local backend / isolated dev env (see [Future: isolated
  environments](#future-isolated-environments)).

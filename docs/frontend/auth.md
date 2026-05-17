# Frontend Auth Reference

See `docs/adr/0011-spotify-token-bundling.md`, `docs/adr/0015-refresh-cookie-replay.md`.

## AuthProvider and tokenStore

`frontend/src/auth/AuthProvider.tsx`

`AuthProvider` wraps the entire app tree. It maintains a `useReducer`-based `AuthState`:

```ts
type AuthState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'authenticated'; user: Me; expiresAt: number; spotifyAccessToken: string | null }
  | { status: 'unauthenticated' }
  | { status: 'error'; error: ApiError };
```

`getAuthSnapshot()` exposes the latest state as a module-level singleton. Route loaders (`requireAuth`, `requireAdmin`) read this snapshot after awaiting `bootstrapPromise()`.

### Bootstrap flow

On mount, `AuthProvider` fires `POST /auth/refresh` once. This is intentional and harmless even pre-login: the refresh endpoint returns 401 when no valid cookie is present, `AuthProvider` transitions to `unauthenticated`, and `completeBootstrap()` resolves `bootstrapPromise`.

`bootstrapStarted` ref (`frontend/src/auth/AuthProvider.tsx:114`) guards against React StrictMode's double-mount: without it, two simultaneous `/auth/refresh` requests would be sent with the same cookie. The backend rotates the token on the first request; the second sees a stale hash and triggers replay detection — revoking all sessions. The guard ensures only one bootstrap attempt fires per page load.

### Token storage

`tokenStore` (`frontend/src/auth/tokenStore.ts`) — module-level variable holding the CLOUDER JWT. Set by `AuthProvider.signIn`, cleared by `signOut` and on auth expiry.

`apiClient` reads `tokenStore.get()` to build the `Authorization: Bearer` header on every request. On 401, the client attempts a silent `/auth/refresh` and retries once.

### Token refresh scheduling

`AuthProvider` schedules a proactive refresh `REFRESH_LEEWAY_MS` (5 min) before `expires_in` using `setTimeout`. The timer is stored in `refreshTimer` ref. `signOut` is the only path that cancels it — StrictMode's cleanup-and-remount cycle intentionally does NOT cancel the timer to avoid killing the refresh schedule for the still-mounted instance.

On silent-refresh success the client dispatches a synthetic `auth:refreshed` custom event. `AuthProvider` listens and re-schedules. On failure it dispatches `auth:expired`; `AuthProvider` transitions to `unauthenticated`.

## Refresh-cookie replay detection

See `docs/adr/0015-refresh-cookie-replay.md`.

The backend implements single-use refresh tokens with hash rotation. Reusing the same refresh cookie (e.g. from a stale tab, a second `useEffect` firing in StrictMode, or a browser back/forward restore) is detected as a replay attack. The response revokes **all** of the user's active sessions — not just the current one.

Recovery: only a fresh `/auth/login` OAuth round-trip restores sessions. There is no "undo" on the server side.

For developers: if every page load bounces to `/login` during development, the cause is almost always a replay. Clear cookies and log in fresh.

## Spotify access token bundling

`frontend/src/auth/spotifyTokenStore.ts`

The Spotify access token is returned alongside the CLOUDER JWT on two endpoints:

- `POST /auth/callback` — initial OAuth callback
- `POST /auth/refresh` — token refresh (both tokens rotated together)

`AuthProvider` calls `spotifyTokenStore.set(body.spotify_access_token)` whenever either endpoint succeeds. The store is an in-memory module singleton with no persistence — it survives soft navigations but is wiped on tab close or hard reload.

The Spotify Web Playback SDK reads the token via its `getOAuthToken(cb)` callback, which synchronously calls `spotifyTokenStore.get()`. Token rotation is transparent to the SDK.

Rule: **never persist `spotifyAccessToken` to localStorage, sessionStorage, or cookies.**

See `docs/adr/0011-spotify-token-bundling.md`.

## Beatport token in memory only

`frontend/src/features/admin/lib/bpTokenStore.ts`

`bpTokenStore` is a module-scoped store for the Beatport API token entered by admins. It implements `useSyncExternalStore` subscription so components re-render on change (`useBpToken()` hook).

Lifecycle: token survives soft navigations within the tab but is wiped on tab close or hard reload (no localStorage, no sessionStorage, no cookies). This is intentional — Beatport tokens must not be persisted.

The `UserMenu` renders a "Reset Beatport token" item exclusively for users where `is_admin` is true. Clicking it calls `bpTokenStore.clear()`.

Token is sent once in `POST /admin/beatport/ingest`. Do not log it on the frontend, do not pass it in URL query parameters (would leak in `Referer` headers).

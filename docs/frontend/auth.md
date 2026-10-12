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

**Hidden idle tabs skip the timed refresh.** `/auth/refresh` touches Aurora, and with `min_acu=0` each call keeps the cluster awake ~10 min — a forgotten tab refreshing every 25 min held it up ~40 % of the day. When the timer fires while `document.visibilityState === 'hidden'` and no music plays, `AuthProvider` only marks the refresh due and runs it on the next `visibilitychange` to visible; API calls made meanwhile refresh on 401. `PlaybackProvider` sets `sessionKeepAlive` (`frontend/src/auth/sessionKeepAlive.ts`) while the queue is playing or buffering, so a hidden tab playing music keeps refreshing its Spotify token.

The Spotify device poll (`usePolling`) pauses its interval in the same hidden-and-silent case — its Spotify 401 an hour later would otherwise call `/auth/refresh`. Keep-alive counts only music playing in this tab, not on a remote device.

**One refresh at a time.** `refreshSession()` in `api/client.ts` is the only caller of `/auth/refresh` — a page-wide single-flight shared by `AuthProvider.refresh` (bootstrap, timer, tab shown, Spotify 401) and the 401 retry, wrapped in a browser-wide Web Lock (`navigator.locks`, `clouder-auth-refresh`) so two windows shown at once don't send one cookie twice. Two concurrent calls with one cookie would trip replay detection (below). A 401 for a token that was already replaced while the request was in flight retries with the new token instead of refreshing again.

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

## No Beatport token in the browser

The SPA never handles a Beatport token. An ingest started from the Coverage page sends only the style and period to `POST /admin/beatport/ingest`; the API Lambda logs in to Beatport with the SSM credentials auto-ingest uses and keeps the token in memory for that request.

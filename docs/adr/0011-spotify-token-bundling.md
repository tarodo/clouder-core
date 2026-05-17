# ADR-0011: Spotify token bundled with CLOUDER auth refresh
Status: Accepted
Date: 2026-05-17

## Context

The Spotify Web Playback SDK requires a valid Spotify access token to initialise. This token is distinct from the CLOUDER JWT: it is issued by Spotify (not CLOUDER), scoped to playback and playlist-modification operations, and has its own expiry and rotation lifecycle.

Three approaches were considered for delivering the Spotify token to the SPA.

**Separate Spotify token endpoint** — the SPA calls a dedicated `GET /auth/spotify-token` endpoint to fetch the token. This adds a network round-trip on every page load and requires its own refresh scheduling logic in the frontend. It also exposes the token in a URL that must be protected, adding CORS and auth complexity.

**Piggyback on the CLOUDER auth flow** — the Spotify token is included in the response body of `/auth/callback` and `/auth/refresh`. Both endpoints already touch the Aurora session record and already hold the user's Spotify credentials. Adding `spotify_access_token` to the response payload is a two-line change on the backend. The SPA's existing `AuthProvider` refresh cycle naturally delivers a fresh Spotify token at the same cadence as the CLOUDER JWT rotation (every ~30 minutes). No separate scheduling is needed.

**LocalStorage persistence** — the token could be stored in `localStorage` so it survives page reloads without a network call. This is a security anti-pattern for OAuth access tokens: `localStorage` is accessible to any JavaScript running on the page (XSS risk), and persisting Spotify credentials is explicitly against Spotify's developer terms of service.

The piggyback approach was chosen for simplicity and correctness.

## Decision

The backend includes a fresh Spotify access token in the response payload of `/auth/callback` and `/auth/refresh`. The SPA stores it in an in-memory `spotifyTokenStore` (mirror of `tokenStore`). It is never persisted to `localStorage`, `sessionStorage`, or cookies. The Spotify Web Playback SDK reads it via `getOAuthToken(cb)` on every callback invocation.

## Consequences

- `spotifyTokenStore` survives soft navigations (react-router route changes) but is wiped on tab close or hard reload. After a hard reload, the SPA's bootstrap `POST /auth/refresh` call re-populates the store before the SDK is initialised.
- The `SPOTIFY_OAUTH_REDIRECT_URI` Lambda env var on `beatport-prod-auth-handler` must point to the CloudFront URL, not the API Gateway URL. The `oauth_state` and `oauth_verifier` cookies are bound to the CloudFront domain; if the Spotify redirect lands on the API Gateway domain, the cookies are absent and the CSRF check fails (`csrf_state_mismatch`).
- The CloudFront URL must be manually added to the Redirect URIs allow-list in the Spotify Developer Dashboard — Terraform cannot automate this.
- React StrictMode mounts effects twice in development. `AuthProvider` guards against double-bootstrap with a `bootstrapStarted.current` ref. Without the guard, two simultaneous `POST /auth/refresh` calls would trigger replay detection and revoke all sessions (see ADR-0015).
- If the Spotify token in `spotifyTokenStore` expires mid-session (tokens are valid for 1 hour), the SDK's next `getOAuthToken(cb)` invocation will receive an expired token. The `AuthProvider` proactive refresh (5 min before CLOUDER JWT expiry) re-populates the store; SDK playback should not be affected in practice because the CLOUDER JWT rotates on the same cadence.

**Cross-references:** `../frontend/auth.md`, `../api/auth-flow.md`.

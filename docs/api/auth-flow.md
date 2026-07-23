# Auth Flow Reference

CLOUDER authentication is OAuth 2.0 (Authorization Code + PKCE) against Spotify, layered with a short-lived CLOUDER JWT access token and a rotating HttpOnly refresh cookie. Spotify Premium is required; free accounts are rejected at `/auth/callback`.

## OAuth start

```
GET /auth/login[?redirect_uri=<url>]
```

**No auth required.**

The handler:

1. Generates a random `state` (UUID hex) and a PKCE `code_verifier` / `code_challenge` pair.
2. Sets two short-lived (10 min) HttpOnly cookies on the CloudFront domain:
   - `oauth_state=<state>; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600`
   - `oauth_verifier=<verifier>; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=600`
3. Optionally sets `oauth_redirect=<redirect_uri>; ...` if `redirect_uri` is present and in the allow-list (`ALLOWED_FRONTEND_REDIRECTS`).
4. Returns `302` to the Spotify Authorize URL with scopes:
   ```
   user-read-email user-read-private
   playlist-modify-public playlist-modify-private ugc-image-upload
   playlist-read-private playlist-read-collaborative
   streaming user-read-playback-state user-modify-playback-state
   ```

The scope list lives in `SPOTIFY_SCOPES` (`src/collector/auth_handler.py`). `playlist-modify-*` backs playlist publish, `ugc-image-upload` backs cover upload, and `playlist-read-private` / `playlist-read-collaborative` back importing a user's own (non-public) Spotify playlist.

**Changing this list requires re-consent.** A refresh does not widen an existing token's scopes — every already-connected user must go through `/auth/login` again before the new scopes take effect. Until they do, a call needing a new scope gets Spotify `403`, surfaced as `spotify_scope_insufficient` (HTTP 412).

The browser follows the redirect to Spotify's login/consent page.

## OAuth callback

```
GET /auth/callback?code=<code>&state=<state>
```

**No auth required.** Spotify redirects the browser here after the user grants consent.

**CSRF state check:** The handler reads `oauth_state` and `oauth_verifier` from the incoming cookies and verifies:
- `cookies.oauth_state == query.state` — mismatch raises `csrf_state_mismatch` (400).
- `oauth_verifier` is present — missing raises `csrf_state_mismatch` (400).

These cookies are bound to the **CloudFront domain**, not the API Gateway domain. The redirect URI configured on the Lambda (`SPOTIFY_OAUTH_REDIRECT_URI`) must therefore point to the CloudFront URL (`https://<cloudfront-domain>/auth/return`). If you configure it to the API GW domain (`*.execute-api.amazonaws.com`), Spotify lands the browser on a different host; the cookie is absent → CSRF check always fails. See [ADR-0011](../adr/0011-spotify-token-bundling.md) for context.

> **Manual step:** The CloudFront URL must also be added to the Redirect URIs allow-list in the Spotify Developer Dashboard — Terraform cannot automate this.

After the state check:

1. Exchanges `code` + `code_verifier` with Spotify's token endpoint (PKCE).
2. Fetches the user profile (`/me`) using the returned Spotify access token.
3. Rejects non-Premium accounts (`premium_required`, 403).
4. Upserts the CLOUDER user record and stores the encrypted Spotify access + refresh tokens in Aurora (KMS envelope encryption via `KMS_USER_TOKENS_KEY_ARN`).
5. Creates a new session, issues a CLOUDER refresh JWT and signs it with `JWT_SIGNING_KEY_SSM_PARAMETER` (HS256). The SHA-256 hash of the JWT is stored in the session row — this is the replay-detection anchor (see [ADR-0015](../adr/0015-refresh-cookie-replay.md)).
6. Issues a short-lived CLOUDER access JWT.

**Response — 200 OK:**

```json
{
  "access_token": "<clouder-hs256-jwt>",
  "spotify_access_token": "<spotify-issued-access-token>",
  "expires_in": 1800,
  "user": {
    "id": "<clouder-user-uuid>",
    "spotify_id": "<spotify-id>",
    "display_name": "Display Name",
    "is_admin": false
  },
  "correlation_id": "<uuid>"
}
```

**Set-Cookie headers on the response:**

| Cookie | Path | Attributes | Notes |
|--------|------|------------|-------|
| `refresh_token=<jwt>` | `/auth/refresh` | HttpOnly Secure SameSite=**Strict** | Scoped to refresh endpoint only |
| `oauth_state=` | `/` | Max-Age=0 | Cleared |
| `oauth_verifier=` | `/` | Max-Age=0 | Cleared |

The `refresh_token` is **not** in the response body. Store `access_token` in memory only (e.g. `tokenStore` / `spotifyTokenStore`). See [ADR-0011](../adr/0011-spotify-token-bundling.md) for the decision to bundle `spotify_access_token` in the CLOUDER auth stream.

**Subsequent authenticated requests:** pass `Authorization: Bearer <access_token>` on every call. The Lambda Authorizer (`auth_authorizer`) validates the JWT and injects `user_id` + `session_id` into the request context.

## Token refresh

```
POST /auth/refresh
```

**No body. No Authorization header.** The browser sends the `refresh_token` cookie automatically (same-site path `/auth/refresh`).

The handler:

1. Reads `refresh_token` cookie → verifies signature and expiry.
2. Loads the active session from Aurora; checks `user_id` matches.
3. Computes SHA-256 of the inbound JWT and compares to `session.refresh_token_hash`. A mismatch means the token was already used → **replay detected** (see below).
4. Decrypts the stored Spotify refresh token (KMS envelope) and calls Spotify's token refresh endpoint.
5. Re-encrypts and upserts the new Spotify tokens.
6. Rotates the CLOUDER refresh JWT: issues a new JWT, updates `session.refresh_token_hash`.
7. Issues a new CLOUDER access JWT.

**Response — 200 OK:**

```json
{
  "access_token": "<new-clouder-jwt>",
  "spotify_access_token": "<new-spotify-access-token>",
  "expires_in": 1800,
  "correlation_id": "<uuid>"
}
```

**Set-Cookie on response:**

| Cookie | Notes |
|--------|-------|
| `refresh_token=<new-jwt>; Path=/auth/refresh; HttpOnly; Secure; SameSite=Strict` | Replaces old cookie |

The SPA (AuthProvider) calls `POST /auth/refresh` on mount (bootstrap), then schedules the next refresh 5 minutes before `expires_in` elapses. The `/auth/refresh` response does not include user identity — the SPA fetches `GET /me` separately after a successful refresh to reconstitute user state.

See [ADR-0011](../adr/0011-spotify-token-bundling.md) and [ADR-0015](../adr/0015-refresh-cookie-replay.md).

## Replay detection

**Trigger:** `POST /auth/refresh` is called with a refresh JWT whose SHA-256 hash does not match `session.refresh_token_hash` (i.e. the token was already rotated by a prior request).

**Action:** `revoke_all_user_sessions` — every session for that user is immediately revoked. This protects against stolen cookie replay: if an attacker uses an old cookie and the legitimate client later rotates it (or vice versa), both are invalidated.

**Error response — 401:**

```json
{
  "error_code": "refresh_replay_detected",
  "message": "...",
  "correlation_id": "<uuid>"
}
```

**Recovery:** only a fresh `/auth/login` → `/auth/callback` round-trip restores access. No other endpoint can recover a user locked out this way.

**Dev gotcha:** React StrictMode mounts effects twice. Without the `bootstrapStarted` guard in `AuthProvider`, both mounts fire `POST /auth/refresh` with the same cookie in rapid succession. The first succeeds and rotates the token; the second presents the now-stale hash → replay detection → all sessions revoked on every page reload. The SPA guards against this with a `bootstrapStarted.current` ref.

See [ADR-0015](../adr/0015-refresh-cookie-replay.md).

## Sequence diagram

```mermaid
sequenceDiagram
    participant B as Browser
    participant CF as CloudFront
    participant APIGW as API Gateway
    participant Auth as auth-handler Lambda
    participant Spotify as Spotify OAuth

    Note over B,Auth: OAuth start
    B->>APIGW: GET /auth/login
    APIGW->>Auth: invoke
    Auth-->>B: 302 Location: accounts.spotify.com/authorize?...<br/>Set-Cookie: oauth_state=<s>; oauth_verifier=<v>

    B->>Spotify: follows redirect (user logs in / consents)
    Spotify-->>B: 302 Location: <CloudFront>/auth/return?code=<c>&state=<s>

    Note over B,Auth: OAuth callback (Spotify redirects to CloudFront URL)
    B->>CF: GET /auth/return?code=<c>&state=<s>
    CF->>APIGW: proxy to GET /auth/callback?code=<c>&state=<s><br/>(with oauth_state + oauth_verifier cookies)
    APIGW->>Auth: invoke
    Auth->>Auth: verify state cookie == query.state (CSRF check)
    Auth->>Spotify: POST /api/token (code + verifier exchange)
    Spotify-->>Auth: access_token + refresh_token
    Auth->>Spotify: GET /me (fetch profile)
    Spotify-->>Auth: profile (product=premium)
    Auth->>Auth: upsert user; store encrypted Spotify tokens; create session
    Auth-->>B: 200 {access_token, spotify_access_token, expires_in, user}<br/>Set-Cookie: refresh_token=<jwt>; Path=/auth/refresh; HttpOnly; Secure; SameSite=Strict<br/>Set-Cookie: oauth_state=; Max-Age=0 (clear)<br/>Set-Cookie: oauth_verifier=; Max-Age=0 (clear)

    Note over B,Auth: Authenticated request
    B->>APIGW: GET /me  Authorization: Bearer <access_token>
    APIGW->>Auth: invoke (authorizer injects user_id, session_id)
    Auth-->>B: 200 {id, spotify_id, display_name, is_admin, sessions}

    Note over B,Auth: Token refresh (cookie sent automatically)
    B->>APIGW: POST /auth/refresh  (Cookie: refresh_token=<jwt>)
    APIGW->>Auth: invoke
    Auth->>Auth: verify JWT sig+expiry; check hash vs session.refresh_token_hash
    Auth->>Spotify: POST /api/token (Spotify refresh_token grant)
    Spotify-->>Auth: new Spotify access_token (+ possibly new Spotify refresh_token)
    Auth->>Auth: rotate session hash; issue new CLOUDER JWTs
    Auth-->>B: 200 {access_token, spotify_access_token, expires_in}<br/>Set-Cookie: refresh_token=<new-jwt>; Path=/auth/refresh; HttpOnly; Secure; SameSite=Strict
```

## Related endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/auth/login` | — | Start OAuth flow |
| `GET` | `/auth/callback` | — | Spotify redirect target |
| `POST` | `/auth/refresh` | Cookie | Rotate tokens |
| `POST` | `/auth/logout` | Cookie | Revoke current session |
| `GET` | `/me` | Bearer | Profile + active sessions |
| `DELETE` | `/me/sessions/{session_id}` | Bearer | Revoke another session |

## Error codes

| `error_code` | HTTP | Cause |
|---|---|---|
| `csrf_state_mismatch` | 400 | `oauth_state` cookie missing or does not match `state` param |
| `validation_error` | 400 | `code` or `state` query params missing |
| `premium_required` | 403 | Spotify account is not Premium |
| `oauth_exchange_failed` | 502 | Spotify token endpoint returned an error |
| `refresh_invalid` | 401 | Refresh cookie missing, invalid JWT, or session not found |
| `refresh_replay_detected` | 401 | Token hash mismatch — all sessions revoked |
| `spotify_revoked` | 401 | Spotify has revoked the vendor token |

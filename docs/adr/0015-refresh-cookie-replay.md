# ADR-0015: Refresh-cookie replay = revoke all sessions
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER uses rotating HttpOnly refresh cookies. On every `POST /auth/refresh` call, the server issues a new refresh JWT and stores its SHA-256 hash in the session row. The old hash is invalidated. If a subsequent refresh request presents a JWT whose hash does not match the stored hash — meaning the token was already rotated — the server has detected a replay.

A replay can happen legitimately (React StrictMode double-mount, browser back/forward cache restoring a stale tab) or maliciously (an attacker intercepted the old cookie and is using it after the legitimate client already rotated it). The server cannot distinguish between these two cases by examining the request alone.

Two responses to replay detection were considered. **Revoke only the current session**: the presented token's session is revoked, the user must log in on that device, but other devices are unaffected. This is lenient but insecure: if the attacker intercepted the cookie and the legitimate client rotates first, the attacker's subsequent use of the old cookie would only revoke the already-rotated session — not the new attacker-controlled one. **Revoke all sessions**: every session for the affected user is immediately invalidated. This is the conservative choice: any replay, regardless of who caused it, triggers a full reset.

Revoking all sessions is the correct security response because the replay detection serves as a trip-wire for cookie theft. If an attacker has a copy of a user's refresh cookie, the safest response is to force re-authentication on all devices — the user notices the logout, changes their password if warranted, and the attacker's stolen token becomes useless.

The usability cost is real: a legitimate cause (React StrictMode, tab restore) triggers the same all-sessions revocation. The `AuthProvider` guards against the StrictMode case with a `bootstrapStarted.current` ref that prevents the second mount from firing a second `POST /auth/refresh`. Tab restore cache is not guarded against at the application level — users who experience it must re-log-in.

## Decision

Reusing the same refresh cookie revokes every active session of the affected user. The only recovery path is a fresh `/auth/login` round-trip. There is no graceful re-auth on a single device.

## Consequences

- A user whose refresh cookie is replayed (for any reason) loses all active sessions across all devices. This is intentional and not a bug.
- The recovery UX is: clear all browser cookies, navigate to `/auth/login`, complete the Spotify OAuth flow. Session re-establishment takes ~5 seconds.
- During development: avoid replaying raw HTTP requests that include the `refresh_token` cookie (e.g. from curl or Postman saved requests). Always use browser-based navigation for session-sensitive flows. If every page load in development bounces to `/login`, the cause is almost always an unguarded double `POST /auth/refresh` triggering replay detection — verify the `bootstrapStarted.current` guard is in place.
- `error_code: refresh_replay_detected` (HTTP 401) is the indicator in server responses. Logging or monitoring for this error code helps distinguish legitimate security events from StrictMode false positives.
- There is no "undo" for the revocation. The server-side `revoke_all_user_sessions` call is immediate and permanent until the user re-authenticates.
- A future mitigation for the tab-restore case could be a client-side check (e.g. storing the token hash in sessionStorage and refusing to re-send a previously-used cookie), but this is not implemented and would add frontend complexity without eliminating the server-side enforcement.

**Cross-references:** `../frontend/auth.md`, `../api/auth-flow.md`.

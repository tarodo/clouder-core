# spec-A — User & Auth Foundation

**Date:** 2026-04-25
**Status:** brainstorm stage
**Author:** @tarodo (via brainstorming session)
**Parent:** [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md) — this spec implements §6 spec-A and resolves §7.6 mini-questions tagged "Decide in spec-A".
**Sibling:** [`2026-04-18-vendor-sync-readiness-design.md`](./2026-04-18-vendor-sync-readiness-design.md) — this spec takes ownership of `user_vendor_tokens` table previously deferred there.

## 1. Context and Goal

The clouder-core backend currently runs as an open serverless ingestion pipeline — anyone with the API endpoint can call `POST /collect_bp_releases` and read canonical core data. The parent spec (§7.1, §7.5) requires multi-tenant SaaS shape with JWT-gated access for everything; the curation specs (spec-C, spec-D, spec-E) all depend on a `user_id` flowing through every request.

This spec adds the foundation layer. After it ships:

- A user can log in via Spotify OAuth, get a JWT, and call user-scoped endpoints.
- Non-Premium Spotify users are blocked at OAuth callback (§7.3 — Web Playback SDK requirement).
- Ingest endpoints (`POST /collect_bp_releases`, `POST /spotify_search`, etc.) are restricted to admins.
- Other curation specs can rely on `event.requestContext.authorizer.user_id` and `is_admin` being present.

## 2. Scope

**In scope:**

- New tables: `users`, `user_sessions`, `user_vendor_tokens` (latter previously designed in 2026-04-18 spec, never built).
- New Lambda: `auth_handler` — handles `GET /auth/login`, `GET /auth/callback`, `POST /auth/refresh`, `POST /auth/logout`, `GET /me`.
- New Lambda: `auth_authorizer` — API Gateway Lambda Authorizer that validates JWT and surfaces `(user_id, is_admin)` to downstream handlers.
- KMS envelope encryption for Spotify refresh tokens stored in `user_vendor_tokens`.
- JWT issue / refresh / revoke with `user_sessions` row per active login.
- Premium check at OAuth callback (block non-Premium with informative response).
- Admin gating for existing ingest endpoints via `is_admin` claim from authorizer context.
- Infrastructure additions: KMS key, SSM param for JWT signing key, API Gateway routes, Lambda Authorizer wiring, IAM policies.

**Out of scope:**

- CloudFront / S3 frontend hosting setup (Q3 §7.6 mentioned single-origin via CloudFront — that's a frontend-deploy concern handled by spec-G).
- Categories, triage, release-playlist tables and endpoints — covered by spec-C/D/E.
- Multi-vendor OAuth (YT Music, Deezer, Apple, Tidal) — `user_vendor_tokens` schema accommodates them, but only Spotify rows are written by this spec.
- Frontend code itself.
- Migration of any existing user data — there is none.
- Self-service admin promotion (`is_admin` is config-driven via env var; spec-A does not expose a UI).

## 3. Architectural Decisions

Recap of decisions resolved during the brainstorming session for this spec. Each is binding for the implementation plan.

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | Roll our own OAuth handler + JWT (not AWS Cognito). | We have only one identity provider (Spotify) with Premium-gate; Cognito's federation requires extra triggers and still needs `user_vendor_tokens`. Same cost (~$1/mo dominated by KMS CMK), simpler control. |
| D2 | API Gateway **Lambda Authorizer** for all non-`/auth/*` routes. | Clean separation, single source of validation truth, 5-min cache on token TTL means near-zero overhead per request. |
| D3 | **Single-origin** via CloudFront (frontend + API behind one host). Frontend deploy is spec-G. | Allows clean cookie-based refresh-token without `SameSite=None` cross-site complexity. |
| D4 | **Hybrid token transport.** Refresh token in `HttpOnly Secure SameSite=Strict` cookie; access token (our JWT) in JSON response body, frontend keeps it in memory only. Spotify access token (for Web Playback SDK) returned in JSON, frontend hands it to the SDK. | Refresh-token survives XSS; access-token short TTL bounds replay window. |
| D5 | Admin via env var `ADMIN_SPOTIFY_IDS=spotify_id1,spotify_id2`. Re-evaluated on every login (idempotent). | Declarative, audit-friendly, no DB-bootstrap hack, easy to demote (drop from list + redeploy). |
| D6 | Stateful session model via `user_sessions` table. Logout = delete row, refresh = check row. JWT contains `session_id`; authorizer trusts signature + expiry, refresh path checks DB. | Instant logout, multi-device visibility, refresh-token-replay detection — all for one extra Aurora row per login. |
| D7 | Premium check at OAuth callback. Non-Premium → return informative response with deep-link to Spotify Premium upgrade, no DB write. Premium hint shown on login screen. | Prevents Web Playback SDK init failure; matches §7.3 + §7.6 resolution. |

## 4. Data Model

### 4.1 `users`

| Column        | Type           | Constraints                              |
|---------------|----------------|------------------------------------------|
| id            | String(36)     | PK (UUID)                                |
| spotify_id    | String(64)     | NOT NULL, UNIQUE                         |
| display_name  | Text           | nullable                                 |
| email         | Text           | nullable                                 |
| is_admin      | Boolean        | NOT NULL, default=false                  |
| created_at    | DateTime(tz)   | NOT NULL                                 |
| updated_at    | DateTime(tz)   | NOT NULL                                 |

Indexes: `idx_users_spotify_id` (unique).

`is_admin` is set on every login from the env var list; this column is the cached value other Lambdas read via authorizer context.

`email` is collected from Spotify but treated as informational, not a primary key.

### 4.2 `user_sessions`

| Column             | Type           | Constraints                                   |
|--------------------|----------------|-----------------------------------------------|
| id                 | String(36)     | PK (UUID; equals JWT `session_id` claim)      |
| user_id            | String(36)     | NOT NULL, FK → `users.id`                     |
| refresh_token_hash | String(64)     | NOT NULL (SHA-256 of refresh-JWT)             |
| user_agent         | Text           | nullable                                      |
| ip_address         | String(45)     | nullable (IPv6-sized)                         |
| created_at         | DateTime(tz)   | NOT NULL                                      |
| last_used_at       | DateTime(tz)   | NOT NULL                                      |
| expires_at         | DateTime(tz)   | NOT NULL                                      |
| revoked_at         | DateTime(tz)   | nullable                                      |

Indexes: `idx_user_sessions_user` (user_id), `idx_user_sessions_expires` (expires_at) for cron cleanup.

A row is created on each successful OAuth callback. `refresh_token_hash` allows replay detection: refresh issues a new refresh-JWT, updates the row's hash, invalidates the previous one. If a request arrives with a hash that doesn't match the stored row, the session is revoked (potential replay).

### 4.3 `user_vendor_tokens`

Per the 2026-04-18 spec design, with the FK to `users` now active.

| Column            | Type         | Constraints                              |
|-------------------|--------------|------------------------------------------|
| user_id           | String(36)   | PK (composite), FK → `users.id`          |
| vendor            | String(32)   | PK (composite) (`spotify` for now)       |
| access_token_enc  | BYTEA        | NOT NULL (envelope-encrypted)            |
| refresh_token_enc | BYTEA        | nullable (envelope-encrypted)            |
| data_key_enc      | BYTEA        | NOT NULL (KMS-encrypted data key)        |
| scope             | Text         | nullable                                 |
| expires_at        | DateTime(tz) | nullable (Spotify access-token expiry)   |
| updated_at        | DateTime(tz) | NOT NULL                                 |

PK: `(user_id, vendor)`.

Envelope structure: a fresh data key is generated via `KMS.GenerateDataKey` per token-rotation event; the plaintext data key encrypts `access_token` and `refresh_token`; `data_key_enc` stores the KMS-wrapped data key. To decrypt, Lambda calls `KMS.Decrypt(data_key_enc)` then AES-decrypts the token bytes.

Data-key plaintext is held only in Lambda memory, with a 5-minute in-memory cache to avoid hammering KMS (per §10.1 cost analysis).

## 5. API Surface

All routes return JSON. Errors follow the existing `{error_code, message, correlation_id}` shape.

### 5.1 `GET /auth/login`

**Public** (no Authorizer).

Query params: optional `redirect_uri` (relative path on the frontend, validated against an allow-list).

Behaviour: builds Spotify OAuth URL with PKCE, sets `state` and `code_verifier` cookies (`HttpOnly Secure SameSite=Lax`, `max_age=600`), returns `302 Location: <spotify_authorize_url>`.

Scopes (combined Mode 1 + Mode 2 per parent §7.3):
```
user-read-email user-read-private playlist-modify-public playlist-modify-private streaming user-read-playback-state user-modify-playback-state
```

PKCE config: `code_verifier = base64url(os.urandom(32))`, `code_challenge_method = S256`.

### 5.2 `GET /auth/callback?code=...&state=...`

**Public** (no Authorizer).

Behaviour:

1. Verify `state` cookie matches query param. Mismatch → `400 csrf_state_mismatch`.
2. Exchange `code` for Spotify tokens using `code_verifier` cookie.
3. Call Spotify `GET /me`. If `product != "premium"` → `403 premium_required` with body `{error_code, message, upgrade_url: "https://www.spotify.com/premium/"}`. **No DB write.**
4. Upsert `users` row by `spotify_id` (creating if new). Set `is_admin = (spotify_id IN ADMIN_SPOTIFY_IDS_env)`.
5. Encrypt Spotify tokens via KMS envelope, upsert `user_vendor_tokens` row.
6. Create `user_sessions` row with new `session_id`, `refresh_token_hash`, `expires_at = now() + 7d`.
7. Issue our access-JWT (30 min, `{sub: user_id, session_id, is_admin, exp}`) and refresh-JWT (7 days, `{sub: user_id, session_id, exp}`).
8. Set refresh-JWT in `HttpOnly Secure SameSite=Strict` cookie path=`/auth/refresh`, `max_age=604800`.
9. Clear `state` and `code_verifier` cookies.
10. Return JSON `{access_token, spotify_access_token, expires_in: 1800, user: {id, spotify_id, display_name, is_admin}}`.

### 5.3 `POST /auth/refresh`

**Public** (no Authorizer — refresh-cookie is the credential).

Behaviour:

1. Read refresh-JWT from cookie. Missing or invalid signature → `401 refresh_invalid`.
2. Check `user_sessions` row exists, not revoked, not expired.
3. Verify `refresh_token_hash` matches the JWT. **Mismatch** = potential replay → revoke this session AND all sibling sessions for the user (refresh-token-family), return `401 refresh_replay_detected`.
4. Refresh Spotify access-token via stored refresh-token. If Spotify returns `400 invalid_grant` (per §10.1 K1.14) → revoke session, delete `user_vendor_tokens` row, return `401 spotify_revoked` to force re-OAuth.
5. Re-encrypt new Spotify access-token via KMS envelope, update `user_vendor_tokens`.
6. Issue new access-JWT and new refresh-JWT (rotation). Update `user_sessions.refresh_token_hash` and `last_used_at`.
7. Set new refresh-JWT cookie.
8. Return JSON `{access_token, spotify_access_token, expires_in: 1800}`.

### 5.4 `POST /auth/logout`

**Public** (no Authorizer — works with or without valid JWT).

Behaviour: read refresh-JWT from cookie; if valid and session exists, mark `revoked_at = now()`. Clear cookie. Return `204 No Content`.

### 5.5 `GET /me`

**Authorizer-protected.**

Returns `{id, spotify_id, display_name, email, is_admin, sessions: [{id, created_at, last_used_at, user_agent, current: bool}, ...]}`.

`current` flags the session matching the request's `session_id`. Future: spec-G can offer "log out from this device" by deleting a non-current session.

### 5.6 `DELETE /me/sessions/{session_id}`

**Authorizer-protected.**

Lets a user revoke a non-current session. `400 cannot_revoke_current` if `session_id` matches current.

### 5.7 Existing routes — admin gating

The following routes (currently open) become admin-only after the authorizer is wired:

- `POST /collect_bp_releases`
- `GET /tracks/spotify-not-found`

The following stay open to any authenticated user (per §7.5 — canonical core is shared but JWT-gated):

- `GET /tracks`, `/artists`, `/albums`, `/labels`, `/styles`
- `GET /runs/{run_id}`

The authorizer attaches `is_admin` to request context; each handler that requires admin checks `if not authorizer_ctx['is_admin']: return 403 admin_required`. (Cleaner alternatives — separate admin API or per-route policy — are deferred; a simple flag-check matches the small admin-set use case.)

## 6. Lambda Authorizer Behaviour

API Gateway HTTP API Lambda Authorizer, `simple` response format, TTL 300s.

Input: `Authorization: Bearer <access_jwt>` header.

Logic:
1. Verify JWT signature with HS256 + secret from SSM SecureString param `/clouder/auth/jwt_signing_key` (cached in-memory for 5 min).
2. Verify `exp` not past.
3. Return `{isAuthorized: true, context: {user_id, session_id, is_admin}}`.

On failure return `{isAuthorized: false}` (API Gateway turns into `401`).

The authorizer does NOT check `user_sessions` — the access-JWT is short-lived (30 min). Revocation latency = up to 30 min for active sessions (acceptable given short TTL). Refresh path catches revocation via DB check.

## 7. KMS Strategy

- **One Customer Managed Key** (`alias/clouder-user-tokens`) for `user_vendor_tokens` envelope encryption.
- IAM policy: only `auth_handler` and `release_mirror_worker` (when spec-E ships) get `kms:Decrypt` and `kms:GenerateDataKey`.
- Key rotation: AWS-managed annual rotation enabled (`enable_key_rotation = true`).
- Cost: ~$1/mo fixed + negligible per-op (per §10.1 calculation). Sub-cent at ~1000 user scale.

JWT signing key (HS256 secret) lives in SSM SecureString, NOT KMS-encrypted-at-application-level (SSM SecureString already uses KMS at rest with the AWS-managed key). Rationale: HS256 secret is shared between authorizer and auth_handler — both need fast access, both run in the same AWS account, SSM-level encryption is sufficient.

Manual rotation procedure for HS256 key: change SSM param value, redeploy. All in-flight access-tokens become invalid → users get a 401 → frontend hits `/auth/refresh` → new access-token issued under new key. 30-min disruption window. Acceptable for an emergency rotation; for routine rotation we can use a JWKS-style two-key window (deferred to ops).

## 8. Configuration

### 8.1 New env vars (auth_handler + auth_authorizer)

| Var | Source | Purpose |
|-----|--------|---------|
| `JWT_SIGNING_KEY_SSM_PARAMETER` | Terraform | SSM SecureString name for HS256 secret |
| `KMS_USER_TOKENS_KEY_ARN` | Terraform | KMS CMK for `user_vendor_tokens` envelope |
| `SPOTIFY_OAUTH_CLIENT_ID` | SSM SecureString | Spotify app client ID |
| `SPOTIFY_OAUTH_CLIENT_SECRET` | SSM SecureString | Spotify app client secret |
| `SPOTIFY_OAUTH_REDIRECT_URI` | Terraform | Full URL like `https://app.clouder.dev/auth/callback` |
| `ADMIN_SPOTIFY_IDS` | Terraform `*.tfvars` (gitignored) | Comma-separated admin Spotify IDs |
| `ALLOWED_FRONTEND_REDIRECTS` | Terraform | Allow-list of `redirect_uri` paths for `/auth/login` |
| `JWT_ACCESS_TOKEN_TTL_SECONDS` | Terraform, default `1800` (30 min) | |
| `JWT_REFRESH_TOKEN_TTL_SECONDS` | Terraform, default `604800` (7 days) | |
| `AURORA_*` | existing | DB connection (Data API) |

### 8.2 New SSM params (created by Terraform)

- `/clouder/auth/jwt_signing_key` — SecureString, generated random 32-byte base64.
- `/clouder/spotify/oauth_client_id` — SecureString.
- `/clouder/spotify/oauth_client_secret` — SecureString.

### 8.3 Existing service-creds

`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` (used by spotify_handler for ISRC lookup, service-mode) stay separate from the OAuth client. Different Spotify app, different scopes set ("Web API only" vs "Web Playback SDK + Web API"). Two app-registrations on Spotify Developer Dashboard.

## 9. Infra Deltas (Terraform)

New resources:

- `aws_kms_key` + `aws_kms_alias` for `user-tokens`.
- `aws_ssm_parameter` × 3 (jwt_signing_key, oauth_client_id, oauth_client_secret).
- `aws_lambda_function.auth_handler` + role + log group.
- `aws_lambda_function.auth_authorizer` + role + log group.
- `aws_apigatewayv2_authorizer` of type `REQUEST`, identity sources `$request.header.Authorization`, response mode `SIMPLE`, TTL 300.
- `aws_apigatewayv2_route` for: `GET /auth/login`, `GET /auth/callback`, `POST /auth/refresh`, `POST /auth/logout`, `GET /me`, `DELETE /me/sessions/{session_id}`.
- Update existing routes (`POST /collect_bp_releases`, `GET /runs/{run_id}`, `GET /tracks/...`, `GET /artists/...`, etc.) to attach the authorizer.
- IAM additions: auth_handler gets `kms:GenerateDataKey`, `kms:Decrypt` on the user-tokens key, `ssm:GetParameter` on the three SSM params, `rds-data:ExecuteStatement` for `users` / `user_sessions` / `user_vendor_tokens`.
- Authorizer gets `ssm:GetParameter` on `/clouder/auth/jwt_signing_key` only (no DB, no KMS).

CloudWatch log retention: same as existing Lambdas (7 days default, configurable via existing `log_retention_in_days` var).

## 10. Error Handling

| Error code | HTTP | Trigger |
|-----------|------|---------|
| `csrf_state_mismatch` | 400 | OAuth state cookie ≠ query param |
| `oauth_exchange_failed` | 502 | Spotify token exchange HTTP error |
| `premium_required` | 403 | Spotify `/me` returns non-Premium |
| `spotify_revoked` | 401 | `invalid_grant` from Spotify on refresh |
| `refresh_invalid` | 401 | Missing/malformed/expired refresh-JWT |
| `refresh_replay_detected` | 401 | refresh_token_hash mismatch — session-family revoked |
| `admin_required` | 403 | Authorizer succeeded but `is_admin=false` for admin route |
| `cannot_revoke_current` | 400 | DELETE /me/sessions on the active session |
| `auth_invalid` | 401 | Authorizer-level rejection (forwarded from API Gateway) |

Existing error codes (validation_error, db_not_configured, etc.) unchanged.

## 11. Testing Strategy

### Unit tests (`tests/unit/`)

- `test_jwt_issue_verify.py` — HS256 round-trip, expiry, signature tampering, claims schema.
- `test_pkce.py` — code_verifier ↔ code_challenge correctness for known vectors.
- `test_kms_envelope.py` — round-trip with mocked `boto3.client('kms')` (`moto` library).
- `test_authorizer_logic.py` — accept valid, reject expired / invalid signature / missing.
- `test_admin_gating.py` — env var parsing, `is_admin` derivation.
- `test_premium_check.py` — Spotify `/me` response stubs (`product=premium|free|open`).

### Integration tests (`tests/integration/`)

- `test_auth_flow.py` — full login → callback → refresh → /me → logout, against ephemeral Postgres + LocalStack KMS/SSM.
- `test_refresh_replay.py` — issue refresh, refresh once (rotation), then re-use old refresh → expect family-revocation.
- `test_admin_route_gate.py` — call `POST /collect_bp_releases` as admin (200) vs non-admin (403) vs no-token (401).

### What we deliberately don't test

- Real Spotify OAuth round-trip (use stubbed responses; live integration test is manual smoke).
- KMS rotation behaviour (AWS-managed).

## 12. Acceptance Criteria

Spec-A is "done" (= ready for spec-B/C/D/E to start) when:

1. Migrations create `users`, `user_sessions`, `user_vendor_tokens` and pass alembic check.
2. `auth_handler` and `auth_authorizer` Lambdas deployed; routes wired in API Gateway.
3. Manual smoke: a real Premium Spotify account can log in, receive JWT, hit `/me`, log out.
4. Manual smoke: a non-Premium account hits `/auth/callback` and gets `403 premium_required` with upgrade URL. No DB row left behind.
5. `POST /collect_bp_releases` returns `401 auth_invalid` without JWT, `403 admin_required` for non-admin user, `200` for admin.
6. Refresh-token rotation works: two consecutive `/auth/refresh` calls succeed; using the first refresh-token after the second call returns `401 refresh_replay_detected` and revokes the session-family.
7. Cost dashboards show KMS within ~$1.50/month at 10-user scale (per §10.1 estimate).
8. CI passes (alembic, terraform, pytest).

## 13. Open Mini-Questions for spec-A Implementation

- **Premium message copy.** Exact text + upgrade-CTA for the `403 premium_required` response. Decide during implementation by trying a few options on the actual login page (will be in spec-G frontend, but copy is owned here).
- **Cookie domain in dev.** Locally (no CloudFront) the frontend runs on `localhost:5173` and API on `localhost:3000` — different origins, so `SameSite=Strict` blocks cookie. Mitigation: dev override via env var (`COOKIE_SAMESITE=Lax`) or run both on the same dev port via Vite proxy. Decide during implementation.
- **Two Spotify apps registration.** This spec assumes two separate Spotify developer apps: one for service-creds (existing, ISRC lookup), one for user OAuth (new, with Web Playback SDK and playlist-modify scopes). Confirmed during implementation by looking at Spotify dashboard restrictions on scope mixing.

## 14. References

- Parent: `2026-04-25-old-version-feature-parity-design.md` §6 (spec-A scope), §7.1, §7.3, §7.5, §7.6 (Premium fallback resolution), §10.5 (old auth code knowledge dump)
- Sibling: `2026-04-18-vendor-sync-readiness-design.md` §5.1 (`user_vendor_tokens` schema design)
- AWS docs: Lambda Authorizer for HTTP API, KMS envelope encryption, SSM SecureString
- Spotify Web API: Authorization Code with PKCE, `GET /me`, Web Playback SDK requirements

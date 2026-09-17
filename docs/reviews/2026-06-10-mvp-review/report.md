# CLOUDER full MVP review — report

**Reviewed commit:** 1614a1d007f677f6f69c5d1567443f004a03a097  
**Spec:** ../../superpowers/specs/2026-06-10-mvp-full-review-design.md  
**Date:** 2026-06-18  
**Status:** FINAL

## Verdict

**ready with reservations**

No P0 findings exist, so this is not an automatic blocker. But twelve P1s cluster in exactly the dimensions the rule flags: DATA and SEC. The deciding findings:

- **Aurora has deletion protection off, skips the final snapshot, and sets no explicit backup retention** (confirmed at `infra/rds.tf:18-19`). For a single multi-tenant database holding all user data, one `terraform destroy`, a forced cluster replacement, or a console fat-finger is irreversible total data loss with at most a 1-day recovery window. This alone caps the verdict.
- **`db_models.py` omits 13 live tables**, so the next `alembic revision --autogenerate` emits `DROP TABLE` for every user's categories, playlists, enrichment, and preferences — catastrophic and invisible until triggered.
- **Stateless authorizer never invalidates issued access tokens on revocation** (SEC), weakening the very guarantee ADR-0015 exists to provide.

Per the stated rule (P1s in SEC/DATA ⇒ at most "ready with reservations"), and because none of these is a hard P0 launch-stopper for a small trusted DJ circle, the project is shippable only once the data-loss and identity-concurrency items are addressed.

## Executive summary

CLOUDER's review surfaced 105 substantive findings (0 P0, 12 P1, 44 P2, 49 P3). The architecture is sound and the codebase is review-ready: no critical launch-stopper, and the strongest areas are the canonicalization/curation domain logic, the documented ADR trail, and a disciplined frontend with clear auth and playback conventions.

The weakest area is **durability and data integrity**, where most P1s concentrate. Three themes recur:

1. **Catastrophic data-loss exposure with no guardrail** — Aurora has no deletion protection, no final snapshot, and no explicit PITR/backup retention. This is one command (or one forced-replacement diff) away from losing all tenant data.
2. **Schema drift between `db_models.py` and the live DB** — 13 tables are missing from the declared model, so the documented "autogenerate to add a column" workflow silently produces `DROP TABLE` migrations.
3. **Concurrency TOCTOU across the data path** — identity minting, triage `move_tracks`, and `/auth/refresh` all read-then-act without a guard, producing orphaned canonical rows, tracks duplicated across buckets, and self-inflicted all-session revocation. Plus reliability gaps: ingest stranding a run at `RAW_SAVED` on enqueue failure with no reconciliation, synchronous Beatport fetch blowing the 29s gateway budget, and deploy applying Lambda code before migrations.

**Recommended fix order:**

1. Aurora protection — enable `deletion_protection`, set `skip_final_snapshot = false`, set explicit `backup_retention_period`. (Cheapest, highest-impact, blocks irreversible loss.)
2. Reconcile `db_models.py` against the 13 missing tables; add a CI guard that fails on autogenerate drift.
3. Add concurrency guards (unique constraints / `INSERT … ON CONFLICT` / transactional checks) to identity minting and `move_tracks`; dedupe `/auth/refresh` callers.
4. Add enqueue-failure reconciliation for `RAW_SAVED` runs; ordering deploy-before-migrate; bound the Beatport fetch.
5. Tighten the stateless authorizer (short access TTL or a revocation check) and sweep P2s.

Ship to the DJ circle once items 1-3 land.

## Findings by dimension

## Security & tokens

Overall this dimension is in reasonable shape: signing-secret-backed JWT verification is sound (HS256 pinned, signatures verified, no forgery path), and the codebase's headline invariant — `bp_token` never logged or persisted — holds today. The two genuinely serious findings are functional security gaps rather than forgery holes: session revocation does not bind already-issued access tokens (P1), and an unguarded second `/auth/refresh` caller races the guarded one to trip ADR-0015 replay detection and silently log the user out everywhere (P1). The remaining findings are defense-in-depth hardening, least-privilege drift in shared IAM, and routine dependency/scanner hygiene — all low individual impact but worth clearing to keep the token-handling story tight.

### [SEC-001] P1 — Revoking a session does not invalidate already-issued access tokens (stateless authorizer)

- **Where:** `src/collector/auth_authorizer.py:39-66`; `src/collector/auth_handler.py:414-417,421,521,618`; `infra/auth.tf:163` (`authorizer_result_ttl_in_seconds=300`)
- **Evidence:** `auth_authorizer.lambda_handler` only calls `verify_access_token` (`auth_authorizer.py:50`) and returns the identity context — it never consults `user_sessions` (grep confirms no repository/session lookup in `auth_authorizer.py`). Therefore `revoke_session` (logout `auth_handler.py:521`, `DELETE /me/sessions/{id}` `auth_handler.py:618`) and `revoke_all_user_sessions` on replay (`auth_handler.py:416`) mark the session revoked, but the already-minted access JWT keeps verifying until its own `exp`. Access TTL defaults to 1800s (`auth_settings.py:39-41`). API Gateway additionally caches the authorizer result for 300s keyed on the Authorization header (`infra/auth.tf:163`, `variables.tf:413-417`), so even token-expiry propagation lags. The ADR-0015 "revoke all sessions on replay" trip-wire is meant to neutralize a stolen cookie, but a stolen/leaked access token survives that revocation for up to ~30 minutes.
- **Risk:** An attacker holding a stolen access token retains full API access for up to the access TTL after the user (or replay detection) revokes all sessions. Logout and per-session revocation are likewise not immediate. This materially weakens the security guarantee ADR-0015 is designed to provide.
- **Recommendation:** Either shorten the access TTL substantially (e.g. 5 min) to bound the exposure window, or have the authorizer (or each downstream handler) validate `session_id` against an active-session/revocation check (e.g. a short-TTL revocation list keyed by `session_id`). Document the residual window in ADR-0015 if a stateless authorizer is retained.
- **Effort:** L

### [SEC-002] P1 — Two independent /auth/refresh callers share no dedupe — concurrent refresh trips replay detection and revokes ALL of the user's sessions

- **Where:** `frontend/src/api/client.ts:8-40,58-74`; `frontend/src/auth/AuthProvider.tsx:156-174`; `frontend/src/features/playback/PlaybackProvider.tsx:114,209,314,657-660`
- **Evidence:** There are two unrelated code paths that POST `/auth/refresh` with the same HttpOnly refresh cookie. (1) The fetch wrapper's silent 401 retry: `client.ts:59` calls `tryRefreshOnce()`, which is guarded by the module-level `inflightRefresh` promise (`client.ts:18`). (2) `AuthProvider.refresh()` (`AuthProvider.tsx:158`) calls `api('/auth/refresh')` as a plain POST — it does NOT go through `tryRefreshOnce`, so it never touches `inflightRefresh`. `AuthProvider.refresh()` is invoked by the proactive expiry timer (`AuthProvider.tsx:134`), on bootstrap (`AuthProvider.tsx:201`), on SDK `authentication_error` (`PlaybackProvider.tsx:314`), and as `onAuthExpired` for EVERY Spotify Web API 401 (`PlaybackProvider.tsx:114`). The device picker polls `getMyDevices({onAuthExpired})` every 30s (5s when open) and on every window focus while `sdkReady` (`PlaybackProvider.tsx:657-660`, `usePolling.ts:16-26`). When the Spotify access token expires, that poll gets a 401 and fires `onAuthExpired -> AuthProvider.refresh()` (the UNGUARDED path); if a normal CLOUDER API call hits a 401 in the same window it fires `client.tryRefreshOnce()` (the guarded path). Both POST `/auth/refresh` with the same cookie; per ADR-0015 the backend rotates the token on the first and sees a stale hash on the second -> replay detected -> revoke every session of the user. The `bootstrapStarted` guard (`AuthProvider.tsx:115`) only stops the StrictMode double-mount at bootstrap; it does nothing for timer-vs-401 or poll-vs-API-call races during normal use.
- **Risk:** During ordinary use (token nearing expiry while playback device polling is active, or a window-focus burst) two refreshes race and the backend revokes ALL of the user's sessions. The user is silently logged out everywhere and must do a fresh OAuth round-trip — and on a small DJ circle this is a recurring, hard-to-reproduce session-loss bug, not a rare edge.
- **Recommendation:** Route every `/auth/refresh` through a single shared in-flight dedupe. Make `AuthProvider.refresh()` delegate to the same `inflightRefresh` promise used by `client.tryRefreshOnce()` (export it / move it to a shared module), or have `AuthProvider.refresh()` call `tryRefreshOnce()` directly and rebuild state from the dispatched `auth:refreshed` event. The dedupe must be a process-wide singleton so the scheduled timer, bootstrap, SDK auth-error handler, and the fetch-wrapper retry all coalesce onto one network request.
- **Effort:** M

### [SEC-003] P2 — IAM policy allows '*' resource for restrictable actions

- **Where:** `infra/iam.tf:19`
- **Evidence:** checkov CKV_AWS_356 fails: `aws_iam_policy_document.collector_lambda` grants actions on Resource `'*'`.
- **Risk:** Over-broad permissions widen the blast radius if the collector Lambda is compromised.
- **Recommendation:** Scope each action to specific resource ARNs where AWS supports resource-level permissions.
- **Effort:** M

### [SEC-004] P3 — JWT verifier accepts future-issued tokens (verify_iat disabled in production)

- **Where:** `src/collector/auth/jwt_utils.py:104-127`
- **Evidence:** `_decode()` passes `options={"verify_iat": False, ...}` with the comment "iat may be in the future in tests" (`jwt_utils.py:112`). This is the only decode path for BOTH access tokens (`auth_authorizer.py:50 -> verify_access_token`) and refresh tokens (`auth_handler.py:405 -> verify_refresh_token`), so it runs in production, not just tests. The code requires `exp`/`iat`/`sub`/`typ`/`session_id` present and manually rejects expired tokens (`jwt_utils.py:124-125`), but never validates that `iat` is not in the future. Signature is still verified (no `verify_signature` override) and `algorithms` is pinned to `["HS256"]` (`jwt_utils.py:108`), so this is not a forgery hole — an attacker cannot mint a token without the SSM signing secret.
- **Risk:** A token whose `iat` is set far in the future (only mintable by a holder of the signing secret, or by a clock-skew bug in the issuer) is accepted as valid. With min_acu and a 7-day refresh TTL the practical impact is negligible, but the test-justification comment leaking into prod behavior means `iat` sanity is silently unenforced; if future logic ever keys off `iat` (e.g. "reject tokens issued before a credential-rotation timestamp") it would be bypassable.
- **Recommendation:** Drop `verify_iat:False` for the production decode path (let PyJWT validate `iat`, with a small leeway), or add an explicit `iat <= now + leeway` check in `_decode`. Keep the test relaxation behind a test-only flag rather than the shared decoder.
- **Effort:** S

### [SEC-005] P3 — Token-bearing auth responses lack Cache-Control: no-store

- **Where:** `src/collector/auth_handler.py:379-391` (callback), `486-504` (refresh)
- **Evidence:** `_handle_callback` and `_handle_refresh` return 200 JSON bodies containing `access_token` and `spotify_access_token` (`auth_handler.py:358-369, 495-503`) with headers limited to `Content-Type` and `x-correlation-id` — no `Cache-Control` or `Pragma`. The SPA is served same-origin behind CloudFront (`infra/auth.tf:62`, `infra/frontend.tf`). No response sets `Cache-Control: no-store` or `private` on any token-bearing body.
- **Risk:** Defense-in-depth gap: token-bearing responses rely entirely on the CloudFront/API-Gateway default of not caching POST/authorized responses. A future CloudFront cache-policy or shared-proxy misconfiguration could cache a response containing a bearer/Spotify token. No evidence this is currently exploited (callback is GET but state-gated; refresh is POST).
- **Recommendation:** Add `Cache-Control: no-store` (and `Pragma: no-cache`) to the headers of every auth response that carries a token in its body (callback, refresh) — ideally in the shared `_json_response` helper for the auth Lambda.
- **Effort:** S

### [SEC-006] P3 — Spotify token-endpoint error payload echoed verbatim into the auth HTTP error body

- **Where:** `src/collector/auth/spotify_oauth.py:147-157` and `src/collector/auth_handler.py:235-244`
- **Evidence:** `_post_token` raises `SpotifyOAuthError(f"spotify token endpoint returned HTTP {status}: {parsed}")` and `SpotifyTokenRevokedError(f"...invalid_grant: {parsed}")` embedding the full parsed Spotify response (`spotify_oauth.py:151,154`). In `_handle_callback`/`_handle_refresh` this is wrapped as `OAuthExchangeFailedError(str(exc))` (`auth_handler.py:292,437`), and `_error_response` copies `exc.message` straight into the JSON response body (`auth_handler.py:236-240`). Note this does NOT leak to logs — the `AppError` log path emits only `error_code`/`status_code`/`error_type`, never `message` (`auth_handler.py:107-116`) — and Spotify token-endpoint error bodies normally contain only `{error,error_description}`, not token material.
- **Risk:** Information disclosure of upstream (Spotify) error internals to the API caller. Low: token-endpoint error responses do not contain access/refresh tokens, and the client is the user's own browser. Still surfaces raw third-party payloads through CLOUDER's error envelope, which is unnecessary coupling.
- **Recommendation:** Have `OAuthExchangeFailedError` carry a generic client-facing message and keep the detailed `{parsed}` only in a server-side log field (which is already redaction-gated), rather than passing `str(exc)` into the response body.
- **Effort:** S

### [SEC-007] P3 — bp_token logging safety depends entirely on the ALLOWED_LOG_FIELDS allow-list; redaction layer is effectively dead

- **Where:** `src/collector/logging_utils.py:13-14,120-141`
- **Evidence:** `log_event` sanitizes via `_sanitize_fields` (`logging_utils.py:136-141`) which is an allow-list: only keys in `ALLOWED_LOG_FIELDS` survive. No allow-listed field is sensitive, so the separate `redact_sensitive_data` pass (which only matches exact key names in `SENSITIVE_KEYS={'bp_token','authorization','token','access_token'}`) never actually fires today. The invariant "bp_token never logged" currently holds ONLY because no `log_event` call passes a token-bearing field name. If a future field carrying a nested dict with a token were added to `ALLOWED_LOG_FIELDS`, redaction would catch it only if the inner key were literally named one of the four `SENSITIVE_KEYS` (case-insensitive exact match) — e.g. a key named `'bearer'` or `'secret'` or `'credentials'` would pass through unredacted.
- **Risk:** No current leak. Latent risk: the two-layer defense is really one layer (the allow-list). A maintainer adding a new allow-listed field that nests credential data, or renaming a sensitive key, could silently break the no-log invariant with no test catching it, since the redaction layer covers only four exact names.
- **Recommendation:** Keep the allow-list as the primary gate (it is sound). Add a unit test asserting that passing `bp_token=...` (and a nested `{'authorization': ...}`) to `log_event` produces output with no token substring, to lock the invariant. Optionally broaden `SENSITIVE_KEYS` to a substring/regex match (e.g. anything containing `'token'`,`'secret'`,`'password'`,`'authorization'`,`'bearer'`) so the redaction backstop is meaningful.
- **Effort:** S

### [SEC-008] P3 — EC2 ENI networking permissions (Resource "*") granted to all 9 Lambdas on the shared role, only db_migration is VPC-attached

- **Where:** `infra/iam.tf:228-239` (`AllowLambdaVpcNetworking`, `resources=["*"]`); only `aws_lambda_function.db_migration` has `vpc_config` (`lambda.tf:75-78`)
- **Evidence:** The `collector_lambda` role grants `ec2:CreateNetworkInterface` / `DeleteNetworkInterface` / `DescribeNetworkInterfaces` / `Assign/UnassignPrivateIpAddresses` on Resource `"*"`. This role is shared by all 9 Lambdas (api, canonicalization, db_migration, spotify_search, vendor_match, label/artist enrichers, auto_enrich_dispatch, auth, curation per `iam.tf:14`, `auth.tf:44`, `curation.tf:8`), but only db_migration runs inside the VPC and actually needs ENI management.
- **Risk:** Least-privilege drift: 8 non-VPC Lambdas hold ENI-management permissions they never use. ec2 ENI actions don't support resource-level ARNs, so `"*"` is unavoidable, but the grant should be isolated to the one VPC Lambda. A compromise of any non-VPC Lambda gains ENI manipulation capability it should not have.
- **Recommendation:** Move the `AllowLambdaVpcNetworking` statement to a separate role (or a separate attached policy) used only by db_migration, rather than the shared `collector_lambda` role, mirroring how `auth_authorizer` already has its own narrow role (`auth.tf:78-110`).
- **Effort:** M

### [SEC-009] P3 — Tavily API key transmitted in the request JSON body instead of an Authorization header

- **Where:** `src/collector/label_enrichment/vendors/tavily_deepseek.py:100-113` and `:132-146`
- **Evidence:** Both Tavily POSTs send the credential inside the JSON body: `json={"api_key": self._tavily_key, "query": ...}`. The key (resolved from SSM at runtime, `settings.py:253`) is therefore part of the request payload rather than a header. On the second (social-domain) pass the same body-embedded key is sent again. Tavily's current API expects Bearer auth in the Authorization header; body `api_key` is the legacy form. Note: the value is NOT logged (vendor errors go to cells, not logs; `ALLOWED_LOG_FIELDS` in `logging_utils.py:14` has no key field), and httpx error messages do not include the request body, so cell-error leakage is not demonstrable here.
- **Risk:** Secrets in request bodies are more likely to be captured by intermediary/proxy/CDN body-logging than header auth, and body-embedded keys are a deprecated Tavily auth mode that can break on vendor API changes. Lower impact than header exposure but a needless secret-handling footgun.
- **Recommendation:** Move the Tavily credential to the `Authorization: Bearer <key>` header (httpx `headers={...}`) and drop `api_key` from the JSON body, matching the current Tavily API contract.
- **Effort:** S

### [SEC-010] P3 — Third-party GitHub Actions pinned to mutable major tags, not commit SHAs

- **Where:** `.github/workflows/deploy.yml:24,27,33,42,135,140`; `.github/workflows/pr.yml:20-21,33,42,93,99,160,163`
- **Evidence:** All actions use floating major tags: `actions/checkout@v4`, `aws-actions/configure-aws-credentials@v4`, `actions/setup-python@v5`, `hashicorp/setup-terraform@v3`, `pnpm/action-setup@v4`, `actions/setup-node@v4` (deploy.yml), and `dorny/paths-filter@v3` (`pr.yml:21`). None are pinned to a full commit SHA.
- **Risk:** deploy.yml assumes the OIDC AWS role (`id-token: write`, full terraform apply + SSM put-parameter on production credentials). A compromised or retagged third-party action (especially the AWS-credentials and setup-terraform actions, or dorny/paths-filter which sees the diff) would execute with that production AWS access. Mutable tags make a supply-chain push silently land on the next deploy.
- **Recommendation:** Pin every third-party action to a full-length commit SHA (with a comment noting the version), and enable Dependabot for GitHub Actions to track upgrades. First-party `actions/*` can stay on tags if policy allows, but the AWS/terraform/paths-filter actions should be SHA-pinned.
- **Effort:** S

### [SEC-011] P3 — checkov: IAM policy allows unconstrained write access

- **Where:** `infra/iam.tf:19`
- **Evidence:** checkov CKV_AWS_111 fails: `aws_iam_policy_document.collector_lambda` allows write actions without resource constraints.
- **Risk:** Compromise of the collector role permits broad writes beyond its intended scope.
- **Recommendation:** Constrain write actions to specific ARNs / add conditions.
- **Effort:** M

### [SEC-012] P3 — checkov: Lambda environment variables not encrypted with CMK

- **Where:** `infra/lambda.tf:1`
- **Evidence:** checkov CKV_AWS_173 fails on 11 Lambda functions — env vars use the default key, not a customer-managed KMS key.
- **Risk:** Env vars are encrypted at rest by AWS default key; CMK is defense-in-depth. Relevant only if any secret/token is stored in env vars.
- **Recommendation:** Confirm no token/secret lives in Lambda env vars (use Secrets Manager); optionally enable a CMK.
- **Effort:** S

### [SEC-013] P3 — checkov: SQS queues not encrypted at rest

- **Where:** `infra/sqs.tf:1`
- **Evidence:** checkov CKV_AWS_27 fails on 12 SQS queues — no server-side encryption configured.
- **Risk:** Queue payloads (ingest/enrichment messages) sit unencrypted at rest; low risk if no token/PII is in message bodies.
- **Recommendation:** Enable SSE-SQS (`sqs_managed_sse_enabled`) on all queues; verify no token is ever placed in a message body.
- **Effort:** S

### [SEC-014] P3 — pnpm audit: vitest UI server arbitrary file read/execute

- **Where:** `frontend/package.json`
- **Evidence:** pnpm audit reports a CRITICAL advisory: when the Vitest UI server is listening, an arbitrary file can be read and executed.
- **Risk:** Dev/test-only dependency; only exploitable when the Vitest UI server runs and is reachable — not in the production runtime.
- **Recommendation:** Bump vitest to the patched version; never expose the Vitest UI server on a routable interface.
- **Effort:** S

### [SEC-015] P3 — pnpm audit: vite server.fs.deny bypass on Windows alternate paths

- **Where:** `frontend/package.json`
- **Evidence:** pnpm audit reports a HIGH advisory: vite `server.fs.deny` bypass on Windows alternate data-stream paths.
- **Risk:** Dev-server-only and Windows-only; not part of the deployed artifact.
- **Recommendation:** Bump vite to the patched version.
- **Effort:** S

### [SEC-016] P3 — pnpm audit: ws memory-exhaustion DoS from tiny fragments

- **Where:** `frontend/package.json`
- **Evidence:** pnpm audit reports a HIGH advisory: ws memory exhaustion DoS from tiny fragments and data chunks.
- **Risk:** Transitive dependency; production impact depends on whether ws serves runtime traffic (typically dev tooling only).
- **Recommendation:** Bump the dependency pulling in ws to a version requiring the patched ws.
- **Effort:** S

### [SEC-017] P3 — pnpm audit: form-data CRLF injection via unescaped field names

- **Where:** `frontend/package.json`
- **Evidence:** pnpm audit reports a HIGH advisory: CRLF injection in form-data via unescaped multipart field names and filenames.
- **Risk:** Transitive build/test dependency; low runtime exposure unless form-data is used against attacker-controlled field names.
- **Recommendation:** Bump the transitive form-data to the patched version.
- **Effort:** S

## Data integrity

The ingest → canonicalization → curation pipeline is broadly additive-by-design (ON CONFLICT/identity-map upserts), which protects against the most common re-run hazards, but several integrity gaps undermine that safety in failure and concurrency scenarios. The most serious issues are silent, condition-dependent: enqueue/read failures that strand a week's data with no retry or alarm, a read-then-mint identity pattern with no concurrency guard that permanently orphans canonical rows, a triage move that can duplicate tracks across buckets, and a schema-model drift that arms `alembic revision --autogenerate` to DROP 13 live production tables. On the infrastructure side, the single Aurora cluster holding all tenant data has deletion protection off, takes no final snapshot, and has no explicit backup retention — a one-command total-loss exposure. Most failures here are invisible (HTTP 200, "completed" runs, green-ish dashboards) until a downstream gap or a destructive operation surfaces them, so prioritising the P1 reconciliation/concurrency/migration/backup items will yield the largest reduction in irreversible-loss risk.

### [DATA-001] P1 — Concurrent runs of same style/week create duplicate orphaned canonical rows (read-then-mint identity has no concurrency guard)

- **Where:** `src/collector/canonicalize.py:443-476` (`_resolve_label`), `:513-546` (`_resolve_artist`), `:548-585` (`_resolve_album`), `:478-511` (`_resolve_style`), `:587-656` (`_resolve_track`); `alembic/versions/20260301_01_init_clouder_schema.py:78-138`
- **Evidence:** Canonical-row dedup is a read-then-mint pattern: `find_identity(source, entity_type, external_id)` returns `None` → mint `uuid4` → `create_label/artist/album/style/track` with `ON CONFLICT (id) DO NOTHING` → queue `UpsertIdentityCmd`. The `clouder_*` tables have NO unique constraint on `(source, entity_type, external_id)` or `normalized_name` — only the synthetic `id` PK (init schema `20260301_01:78-138`). The `identity_map` ON CONFLICT key is `(source, entity_type, external_id)` (`repositories.py:455,491`). Each ingest mints a fresh `run_id` (`handler.py:360`); the canonicalization SQS ESM has no `maximum_concurrency` cap (`infra/lambda.tf:97-101`) and the queue is a standard (non-FIFO) at-least-once queue (`infra/sqs.tf:6-18`). Two concurrent canonicalizations of the same Beatport entity (a normal admin re-run, or an SQS duplicate delivery racing a retry) both read `find_identity=None` under READ COMMITTED (no advisory lock, no `SELECT FOR UPDATE`, no SERIALIZABLE — verified absent), both mint distinct uuids, both `create_*(...)` succeed (different ids, `DO NOTHING` never fires), and `batch_upsert_identities` collapses `identity_map` to ONE row pointing at whichever transaction commits last.
- **Risk:** Two `clouder_labels`/`clouder_artists`/`clouder_albums`/`clouder_tracks` rows are created for the same Beatport entity; `identity_map` points at only one, so the other is a permanently orphaned canonical row. Downstream FKs (`track.album_id`, `track.style_id`, `track_artists`) and curation overlays can attach to the orphaned id, producing duplicate tracks/artists in the catalogue that survive future re-ingests (`find_identity` now finds the surviving mapping and never touches the orphan). Silent gradual catalogue corruption that worsens with each concurrent/overlapping ingest.
- **Recommendation:** Make canonical creation concurrency-safe: either (a) insert the identity FIRST with `INSERT ... ON CONFLICT (source, entity_type, external_id) DO UPDATE ... RETURNING clouder_id` and derive the canonical id from the winning row, (b) take a `pg_advisory_xact_lock(hashtext(source||entity_type||external_id))` before `find_identity` within the phase transaction, or (c) serialize the worker (FIFO queue keyed by style/week, or ESM `maximum_concurrency=1`). Option (a) is the cleanest — it removes the read-then-mint race entirely.
- **Effort:** M

### [DATA-002] P1 — Concurrent triage move_tracks unconditionally re-inserts into target, duplicating tracks across buckets

- **Where:** `src/collector/curation/triage_repository.py:448-494` (`move_tracks`); INSERT at `:483-492` inserts the full `track_id_list`, not the rows actually deleted
- **Evidence:** The presence SELECT (`:448`) and the status/inactive guard (`:399-433`) run OUTSIDE the transaction; only DELETE+INSERT are wrapped (`:465`). The DELETE is `WHERE triage_bucket_id=:from_id AND track_id IN (...)` and the INSERT into `to_bucket` is unconditional over the full `track_id_list` with `ON CONFLICT (triage_bucket_id, track_id) DO NOTHING`. The PK is `(triage_bucket_id, track_id)`, so the same track may live in multiple buckets of one block (no per-block uniqueness, `alembic/versions/20260428_15_triage.py:137`).
- **Risk:** Two concurrent moves of the same track from one source bucket to different targets (A: from→X, B: from→Y) both pass the out-of-tx presence check; A deletes+inserts to X, B's DELETE is a no-op but B still inserts to Y. The track now exists in BOTH X and Y. Bucket `track_counts` inflate, and finalize promotes the track into multiple categories. `moved` is also over-reported. The same TOCTOU lets a move land after a concurrent finalize flips the block (guard read outside tx).
- **Recommendation:** Move the guard and presence SELECT inside the transaction; make the INSERT insert only the rows the DELETE actually removed (e.g. `DELETE ... RETURNING track_id`, then INSERT those), or perform the move via a single `UPDATE` of `triage_bucket_id` with block-scoped uniqueness.
- **Effort:** M

### [DATA-003] P1 — Ingest enqueue failure permanently strands a run at RAW_SAVED with no retry or reconciliation

- **Where:** `src/collector/handler.py:438-498,957-974`
- **Evidence:** `_run_beatport_ingest` writes the S3 snapshot, inserts the `ingest_runs` row at status RAW_SAVED (`handler.py:431`), then calls `_enqueue_canonicalization`. If the SQS `send_message` raises, the exception is swallowed and converted to `EnqueueResult(ENQUEUE_FAILED)` (`handler.py:957-974`); the API still returns HTTP 200 with `run_status=RAW_SAVED` (`handler.py:463-471`). Nothing re-enqueues. A grep for RAW_SAVED across `src/` and `infra/` shows the status is only ever set (`handler.py:431`) and read — there is no sweeper, cron, or reconciliation job that re-drives RAW_SAVED runs. `RunStatus` has no in-progress state (`models.py:24-28`), so a stranded run is indistinguishable from a worker that is mid-flight.
- **Risk:** A transient SQS outage (or the queue being disabled/misconfigured, `handler.py:889-919`) silently drops the week's data from canonicalization: the raw snapshot sits in S3, the run row says RAW_SAVED forever, but the tracks never enter the catalogue. The admin sees HTTP 200 success and a green-ish run, and the week is silently absent from the catalog with no alarm (DLQ alarms only cover messages that were actually enqueued).
- **Recommendation:** On enqueue failure, mark the run FAILED (so GET /runs and coverage surface it) instead of returning 200/RAW_SAVED, and/or add a periodic reconciliation that finds RAW_SAVED runs older than N minutes and re-enqueues them by `run_id`+`s3_key` (idempotent because canonicalization replays cleanly). At minimum add a CloudWatch metric/alarm on `canonicalization_enqueue_failed`.
- **Effort:** M

### [DATA-004] P1 — db_models.py omits 13 live tables — `alembic revision --autogenerate` would emit DROP TABLE for all of them

- **Where:** `src/collector/db_models.py` (whole file); `alembic/env.py:16,48-53`
- **Evidence:** `env.py` sets `target_metadata = Base.metadata` (`env.py:16`) and configures autogenerate with `compare_type=True, compare_server_default=True` and NO `include_object`/`include_name` filter (`env.py:48-53`; grep for `include_object`/`include_name` returns nothing). `db_models.py` declares only 23 `__tablename__`s, but migrations create 36 live tables. Tables present in the DB (created by migrations 14/22/23/25/26, never dropped) yet ABSENT from `db_models.py`: `categories`, `category_tracks`, `clouder_label_enrichment_runs`, `clouder_label_enrichment_cells`, `clouder_label_info`, `clouder_artist_enrichment_runs`, `clouder_artist_enrichment_cells`, `clouder_artist_info`, `clouder_user_label_prefs`, `clouder_user_artist_prefs`, `auto_enrich_config`, `label_auto_enrich_state`, `artist_auto_enrich_state`. With autogenerate, SQLAlchemy compares the live DB against `Base.metadata`; tables in the DB but not in metadata are rendered as `op.drop_table(...)`.
- **Risk:** The next developer who runs `alembic revision --autogenerate` to add a column gets a migration that silently DROPs 13 production tables — every user's categories, playlists-source links, all label/artist enrichment results, user preferences, and auto-enrich config/state. If applied, this is catastrophic multi-tenant data loss. The omission is invisible until someone autogenerates; the project's own `db_models.py` docstring presents it as "the Alembic schema source of truth," inviting exactly this workflow.
- **Recommendation:** Add SQLAlchemy models for all 13 missing tables to `db_models.py` so `Base.metadata` is a faithful mirror of the migration-defined schema, OR add an `include_object`/`include_name` hook in `env.py` that refuses to emit drops for tables not modeled (allowlist). Add a CI check (e.g. `alembic check`) that fails when autogenerate detects diffs, so metadata drift is caught at PR time.
- **Effort:** M

### [DATA-005] P1 — Aurora cluster has deletion protection off, skips final snapshot, and has no explicit backup retention/PITR

- **Where:** `infra/rds.tf:18-19` (`deletion_protection = false`, `skip_final_snapshot = true`); `rds.tf:1-26` (no `backup_retention_period` / `preferred_backup_window`)
- **Evidence:** `aws_rds_cluster.aurora` sets `deletion_protection = false` and `skip_final_snapshot = true` (`rds.tf:18-19`). The resource has no `backup_retention_period`, no `preferred_backup_window`, and no PITR/AWS Backup plan anywhere in infra (grep across `infra/` for `backup_retention`/`point_in_time`/`backtrack` returns nothing), so the cluster relies on the AWS default of 1-day automated backups. This is the single Aurora cluster holding the entire canonical catalogue, all per-user curation/overlay data (categories/playlists/triage/tags), sessions, and KMS-encrypted vendor tokens — every write in `repositories.py` and `curation/*_repository.py` targets it. (Also flagged by checkov CKV_AWS_139: RDS cluster lacks deletion protection.)
- **Risk:** A `terraform destroy`, an accidental cluster replacement (e.g. a forced-replacement attribute change), or a fat-finger console delete is not blocked and leaves NO final snapshot. Recovery is then bounded by the 1-day default PITR window. For a multi-tenant DB holding all tenant data, this is a single-command total-data-loss exposure with a very short recovery horizon.
- **Recommendation:** Set `deletion_protection = true` and `skip_final_snapshot = false` (with a `final_snapshot_identifier`) for the prod cluster, and set an explicit `backup_retention_period` (e.g. 7–14 days) plus a `preferred_backup_window`. Aurora PITR is automatic within the retention window once retention is set. Gate destructive overrides behind a separate variable so non-prod can still tear down freely.
- **Effort:** S

### [DATA-006] P2 — Worker performs no completeness check between the S3 snapshot and the recorded item_count

- **Where:** `src/collector/worker_handler.py:82-116`; `src/collector/storage.py:92-107`
- **Evidence:** The API records `item_count` (the number of releases fetched) on the `ingest_runs` row (`handler.py:404,432`) and in `meta`. The worker reads the snapshot via `storage.read_releases(s3_key)` which silently filters to dict items (`[item for item in parsed if isinstance(item, dict)]`, `storage.py:107`) and never compares `len(raw_tracks)` against the run's `item_count` (`worker_handler.py:83-89`). On success it overwrites `processed_count` with `result.tracks_processed` and marks COMPLETED unconditionally (`worker_handler.py:112-116`). There is no assertion that the snapshot it canonicalized is the snapshot originally fetched, nor that it is non-empty/non-truncated.
- **Risk:** A truncated or partially-overwritten snapshot (see DATA-008) is canonicalized as if complete and marked COMPLETED. Because canonicalization only ADDs via ON CONFLICT/identity-map, missing tracks are silently never inserted — gradual, invisible catalog gaps. A 0-item snapshot also marks COMPLETED with `processed_count=0`, indistinguishable from a genuinely empty week.
- **Recommendation:** In the worker, compare `len(raw_tracks)` against the run's persisted `item_count` (fetch the run row first) and fail (transient) on mismatch, or at least emit a warning metric. Reject empty snapshots when `item_count>0`.
- **Effort:** M

### [DATA-007] P2 — conservative_update_track overwrites isrc/bpm/length_ms whenever upstream value differs (silent canonical mutation)

- **Where:** `src/collector/repositories.py:647-694`; `src/collector/canonicalize.py:611-626`
- **Evidence:** For an existing track, `_resolve_track` calls `conservative_update_track` (`canonicalize.py:611`). The SQL (`repositories.py:654-671`) uses COALESCE for most fields (fill-nulls-only) but a CASE for `isrc`/`bpm`/`length_ms` that fills nulls AND overwrites when `WHEN isrc <> :isrc THEN :isrc`. This is the only non-additive mutation in the entire ingest path. Re-running an older or noisier Beatport week (the S3 snapshot key omits `run_id` and overwrites per style/week, `storage.py:245-248`) replays differing values over the canonical row.
- **Risk:** If Beatport ever returns a different/incorrect `isrc`, `bpm`, or `length_ms` for a track already canonicalized with a good value, the canonical record is silently overwritten with the newer-but-worse value, with no provenance check or confidence gate. Gradual, hard-to-detect catalogue corruption.
- **Recommendation:** Decide intended precedence: either keep first-seen authoritative for these immutable-ish fields (COALESCE only), or require a higher-confidence source to overwrite. If overwrite is intended, log the before/after so divergence is auditable.
- **Effort:** M

### [DATA-008] P2 — Re-ingesting the same style/week overwrites the S3 snapshot and spawns a duplicate, racing canonicalization job

- **Where:** `src/collector/storage.py:245-248`; `src/collector/handler.py:360,414-446`
- **Evidence:** The S3 key is `{raw_prefix}/style_id={style_id}/year={year}/week={week:02d}/releases.json.gz` (`storage.py:245-248`) — it omits `run_id`. Each ingest POST mints a fresh `run_id = str(uuid.uuid4())` (`handler.py:360`). Two POSTs for the same style/week therefore produce two distinct run_ids and two `ingest_runs` rows, but write to the SAME S3 key (the second `write_run_artifacts` overwrites the first, `storage.py:55-90`) and enqueue two canonicalization messages each pointing at that same key (`handler.py:921-929`). The workers for run A and run B both call `read_releases(s3_key)` against whatever bytes currently live at the key.
- **Risk:** If run A's worker reads the key AFTER run B has overwritten it, run A canonicalizes run B's data yet records its result under run A's run_id and item_count — `processed_count` and run state become inconsistent with the snapshot the row claims to describe. Worse, if run B fetched a smaller/partial set (e.g. an upstream Beatport hiccup), it clobbers run A's complete snapshot, and any later re-read of run A's key (e.g. a DLQ redrive) now sees the degraded data. This is silent, condition-dependent corruption of run provenance.
- **Recommendation:** Include `run_id` in the S3 key so each run owns an immutable snapshot (the row already preserves per-run identity); or make the snapshot key content-addressed. This also fixes the overwrite-of-good-data-by-bad-data hazard (and unblocks DATA-013's read-after-overwrite path).
- **Effort:** M

### [DATA-009] P2 — Empty/unknown-shaped Beatport pages are silently dropped during pagination with no integrity signal

- **Where:** `src/collector/beatport_client.py:64-84,158-165`
- **Evidence:** `_extract_items` returns `[]` for any page whose item array is not under one of `results`/`items`/`releases`/`data` (`beatport_client.py:158-165`). The pagination loop blindly `all_items.extend(items)` and continues as long as `next` is present (`beatport_client.py:73-78`). A page that returns 200 with items under an unexpected key, or a transient upstream returning an empty list while still advancing `next`, contributes zero rows but is not distinguished from a genuinely empty page. The only safety net is the 300-page cap (`beatport_client.py:84`).
- **Risk:** Upstream schema drift or a partial upstream response silently reduces `item_count`, the snapshot is written and canonicalized as complete, and the week ends up with fewer tracks than Beatport actually returned — gradual catalog under-population with no error or alarm.
- **Recommendation:** Treat an unexpected/empty page-shape mid-pagination (page with no recognised item key) as an error or at least emit a warning metric; consider cross-checking against an upstream total-count field when present.
- **Effort:** S

### [DATA-010] P2 — Transient S3 read failure misclassified as permanent error → message dropped, run marked FAILED, no retry/DLQ (silent data loss)

- **Where:** `src/collector/worker_handler.py:21` (`_PERMANENT_ERRORS`), `:82-83`, `:139-180`; `src/collector/storage.py:92-107` (`read_releases`)
- **Evidence:** `read_releases` wraps EVERY S3 exception into `StorageError`: `except Exception as exc: raise StorageError(...)` (`storage.py:96-97`) — this catches transient S3 conditions (SlowDown/503 throttling, connection resets, read timeouts) identically to genuinely-corrupt payloads. `StorageError` is listed in `_PERMANENT_ERRORS = (ValueError, TypeError, KeyError, StorageError)` (`worker_handler.py:21`). In the handler, `is_permanent = isinstance(exc, _PERMANENT_ERRORS)` (`worker_handler.py:140`); permanent → `set_run_failed` then `continue` (`worker_handler.py:176-179`), which deletes the SQS message WITHOUT re-raising, so it never cycles toward the `maxReceiveCount=5` DLQ (`infra/sqs.tf:14-17`). The raw S3 snapshot is keyed by style/year/week with no run_id, so there is no automatic re-enqueue path.
- **Risk:** A momentary S3 throttle/timeout during the read phase permanently abandons that run: the message is deleted, the run sits FAILED, and the already-fetched raw releases are never canonicalized. The catalogue silently misses an entire weekly ingest with no DLQ artifact to replay from — operators only see a FAILED row.
- **Recommendation:** Separate transient from permanent S3 failures: in `read_releases`, re-raise the original boto3 `ClientError` (or a dedicated `TransientStorageError`) for retryable S3 codes (SlowDown, RequestTimeout, 5xx, throttling) so `worker_handler` re-raises and lets SQS redrive/DLQ handle it; reserve `StorageError` (permanent) only for decode/shape errors (gzip/json/non-list payload, `storage.py:99-107`). Equivalently, drop `StorageError` from `_PERMANENT_ERRORS` and add a narrow permanent decode-error type.
- **Effort:** S

### [DATA-011] P2 — All-vendors-failed enrichment re-run overwrites previously-good label/artist info with a failure placeholder

- **Where:** `src/collector/label_enrichment/orchestrator.py:117-127` (+ `aggregator.py:393-411`); mirrored in `src/collector/artist_enrichment/orchestrator.py:113-126`
- **Evidence:** `enrich_label_for_run()` calls `merge_cells()` then `upsert_label_info()` UNCONDITIONALLY. When every vendor cell fails to parse (quota/outage/429/timeout), `aggregator.merge_cells()` returns the Case-1 placeholder `LabelInfo(summary="All vendor sources failed.", confidence=0.0)` with default status (`aggregator.py:393-411`). `repository.upsert_label_info()` (`repository.py:759-809`) is an `INSERT ... ON CONFLICT (label_id) DO UPDATE SET merged=EXCLUDED.merged, tagline/country/founded_year/primary_styles/ai_content/... = EXCLUDED.*` — i.e. it overwrites ALL columns of an already-enriched row. There is no guard that skips the write (or preserves prior data) when all cells failed. `project_ai_suspected()` then re-projects the 0.0-confidence result. Same code shape in `artist_enrichment/orchestrator.py:113-126` / `upsert_artist_info`.
- **Risk:** A re-enrichment (manual admin re-run, or auto-dispatch on a triage block) that hits a transient Gemini/OpenAI/Tavily outage or shared quota exhaustion silently clobbers a good, previously-enriched label/artist with an empty "All vendor sources failed" stub (tagline/country/styles wiped, confidence 0.0). This is silent gradual corruption of curated catalogue metadata that no error surfaces — the run is marked "completed", `cells_error` just increments.
- **Recommendation:** In `enrich_label_for_run`/`enrich_artist_for_run`, skip `upsert_label_info`/`upsert_artist_info` (and `project_ai_suspected`) when merge meta has `all_failed=True` (or `merged.confidence==0.0 and ok==0`), OR change the upsert to COALESCE-merge non-null fields so a failed run never nulls out existing data. Keep recording the failed cells + run counters for observability.
- **Effort:** S

### [DATA-012] P2 — Spotify import is non-atomic: per-track upsert + separate append, partial failure leaves orphaned imported tracks

- **Where:** `src/collector/curation_handler.py:1063-1145` (`_handle_import_spotify`); `repo.upsert_imported_track` called per-track in a loop (`:1103`, each its own tx in `playlists_repository.py:864`) then `repo.append_tracks` once (`:1124`, a separate tx)
- **Evidence:** Each `upsert_imported_track` opens its own transaction inserting `clouder_tracks` + `user_imported_tracks`. The playlist `append_tracks` runs in a later, independent transaction. A Spotify `get_track` failure mid-loop (`:1094`) or a Lambda timeout (30s, `infra/curation.tf`) between the import loop and append leaves `clouder_tracks`/`user_imported_tracks` rows committed but never added to the playlist.
- **Risk:** Orphaned `spotify_user_import` rows accumulate in `clouder_tracks` (no cleanup path; FK `ondelete` on `user_imported_tracks` is CASCADE only from `users`). They permanently widen the user's track scope (`validate_tracks_in_scope` EXISTS on `user_imported_tracks`) and silently bloat the catalogue. The client sees a 5xx with no record of what was imported.
- **Recommendation:** Accept partial import as the documented contract OR wrap import+append in one transaction; at minimum return the imported-but-not-appended track_ids so the client can retry idempotently.
- **Effort:** M

### [DATA-013] P2 — OAuth callback writes user, vendor-token, and session as three separate untransacted statements

- **Where:** `src/collector/auth_handler.py:303-347` (`upsert_user`, `upsert_vendor_token`, `create_session`)
- **Evidence:** On `GET /auth/callback` the handler calls `upsert_user` (`303-312`), then `upsert_vendor_token` (`316-327`), then `create_session` (`339-347`) — three independent Data API `execute()` calls, none sharing a `transaction_id` (`auth/auth_repository.py` exposes no transaction path). A failure after `upsert_user` but before `create_session` leaves a `users` row with no session; a failure after create_session-without-vendor-token would leave a session whose later `/auth/refresh` immediately fails the `vendor_token is None` check and revokes the session (`auth_handler.py:420-422`).
- **Risk:** Partial account-creation state on an unauthenticated entry point: orphaned `users`/`user_vendor_tokens` rows, or a session that cannot refresh. Self-healing on the next successful login (all writes are upserts keyed by `spotify_id` / `(user_id,vendor)`), so impact is a failed login attempt rather than durable corruption, but the state is inconsistent until then.
- **Recommendation:** Wrap the three writes in a single `self._data_api.transaction()` with `transaction_id` threaded into `upsert_user`/`upsert_vendor_token`/`create_session` so the user, vendor token, and session are created atomically.
- **Effort:** M

### [DATA-014] P2 — checkov: RDS cluster has no AWS Backup plan

- **Where:** `infra/rds.tf:1`
- **Evidence:** checkov CKV2_AWS_8 fails: `aws_rds_cluster.aurora` is not covered by an AWS Backup plan.
- **Risk:** Recovery depends solely on automated snapshots/PITR; for a multi-tenant store the retention window must be confirmed adequate for the MVP RPO (see DATA-005, where retention is currently the 1-day default).
- **Recommendation:** Confirm `backup_retention_period` and PITR meet the recovery target (handled by DATA-005); optionally add an AWS Backup plan for longer-term, cross-account copies.
- **Effort:** S

### [DATA-015] P3 — S3 snapshot write is non-atomic across the two objects and orphans releases.json.gz on partial failure

- **Where:** `src/collector/storage.py:55-90`; `src/collector/handler.py:409-417`
- **Evidence:** `write_run_artifacts` issues two independent `put_object` calls — `releases.json.gz` first, then `meta.json` (`storage.py:56-73`). If the second put fails, the first has already committed but the function raises `StorageError` (`storage.py:81-82`), so `_run_beatport_ingest` aborts before `create_ingest_run` (`handler.py:416-417`) — leaving the releases object in S3 with no meta and no `ingest_runs` row. The raw bucket has versioning on and no lifecycle policy (per system map §5.4), so these orphans accumulate.
- **Risk:** Orphaned snapshots are never canonicalized (no run row → never enqueued) and never cleaned up — unbounded S3 growth from partial-write retries, plus a snapshot/row pair that can silently disagree if downstream tooling assumes releases+meta are written together.
- **Recommendation:** Write meta first (or keep persisting the run row only after both succeed, which it already does), and add an S3 lifecycle rule to expire orphaned/old raw objects and non-current versions. Optionally write a single combined object to make the snapshot atomic.
- **Effort:** S

### [DATA-016] P3 — Migration 16 downgrade re-imposes NOT NULL on ingest_runs.iso_year/iso_week without backfilling admin-path rows — downgrade aborts

- **Where:** `alembic/versions/20260509_16_admin_ingest_runs.py:42-52`
- **Evidence:** `upgrade()` makes `iso_year`/`iso_week` nullable (`16:20-21`) precisely so admin-path ingests can leave them NULL (per system map §2.1, admin route forces iso fields to None). `downgrade()` at `16:51-52` calls `op.alter_column(... nullable=False)` on both columns with only a code comment ("Truncate/backfill those rows before downgrading") and NO backfill statement — unlike migrations 06 and 18 which DO `UPDATE ... WHERE col IS NULL` before re-tightening (`06:30`, `18:31-33`).
- **Risk:** If any admin-initiated `ingest_runs` row exists (NULL `iso_year`/`iso_week`), running this downgrade fails with a NOT NULL violation and rolls back, blocking the entire down-migration. Low blast radius (downgrades are rare/operator-driven and it fails safe rather than losing data), but inconsistent with the codebase's own backfill-before-tighten pattern.
- **Recommendation:** Mirror migrations 06/18: add an `op.execute` to backfill a sentinel (or delete admin-only rows) before the `alter_column(... nullable=False)`, or document in the migration docstring that downgrade past rev 16 requires manual data cleanup.
- **Effort:** S

### [DATA-017] P3 — Playlist remove_track conflates 'track not in playlist' with 'playlist not found' (404)

- **Where:** `src/collector/curation/playlists_repository.py:498-539` returns False both when the playlist is missing and when the track is absent; handler maps False→`PlaylistNotFoundError` at `src/collector/curation_handler.py:943-947`
- **Evidence:** `remove_track` returns False at `:523` when the track row is absent (playlist exists) and the handler raises `PlaylistNotFoundError('Playlist or track not found')` for that same False. The optimistic client (`useRemoveTrackFromPlaylist`) cannot distinguish an idempotent no-op (already removed) from a genuinely missing playlist, unlike the categories path which treats 404 `track_not_in_category` as idempotent success.
- **Risk:** Idempotent re-removal (e.g. retried mutation, double-tap) returns a 404 that the client surfaces as an error and may roll back the optimistic shrink, producing a confusing UI state. No data corruption.
- **Recommendation:** Return distinct outcomes (playlist-missing vs track-absent) and have the handler treat track-absent as 204/idempotent, matching the categories remove semantics.
- **Effort:** S

### [DATA-018] P3 — validate_tracks_in_scope runs in a separate statement from append_tracks (TOCTOU on playlist scope)

- **Where:** `src/collector/curation_handler.py:907-918` (`_handle_add_playlist_tracks`): `validate_tracks_in_scope` (`:907`) and `repo.append_tracks` (`:915`) are independent calls; scope SQL at `playlists_repository.py:828-844`, append at `:408-496`
- **Evidence:** The scope check (EXISTS over `category_tracks`/`playlist_tracks`/`user_imported_tracks`) is an untransacted SELECT; `append_tracks` then opens its own transaction. Between them a concurrent category/playlist delete could remove the only basis for a track being in-scope.
- **Risk:** A track could be appended to a playlist a few ms after losing its in-scope basis. Low impact: scope only governs which catalogue tracks a user may reference, the track still exists, and `user_id` is bound in both queries (no cross-tenant leak). Mainly a correctness footgun.
- **Recommendation:** If strict scope enforcement matters, fold the scope check into the `append_tracks` transaction; otherwise document it as best-effort.
- **Effort:** S

### [DATA-019] P3 — User search input in LIKE patterns has no ESCAPE clause — % and _ act as wildcards (correctness footgun, not injection)

- **Where:** `src/collector/repositories.py:764,788,873,901,944,963,977,993` (`LIKE :search` built as `f"%{search.lower()}%"`); same pattern in curation list endpoints
- **Evidence:** `find_tracks_not_found_on_spotify`/`list_tracks`/`count_tracks`/`list_artists`/`list_albums`/`list_styles` all do `params["search"] = f"%{search.lower()}%"` then SQL `... LIKE :search` with no ESCAPE clause (e.g. `repositories.py:763-764, 872-873, 900-901`). The search term IS bound as a Data API parameter (no SQL injection), but literal `%` or `_` in the user's search string are interpreted as LIKE wildcards rather than matched literally.
- **Risk:** Pure correctness/UX: a user searching for a title containing `%` or `_` gets over-broad matches. No security impact — the value is parameterized, never interpolated into SQL text. No data corruption (read-only paths).
- **Recommendation:** If literal substring matching is intended, escape `%`, `_` and `\` in the user term and append `ESCAPE '\'` to the LIKE clause, or use `position()`/`ILIKE` on an escaped term. Low priority; cosmetic for an internal DJ tool.
- **Effort:** S
```

Note: I consolidated the two duplicate Aurora prose findings (identical `infra/rds.tf:18-19` evidence) plus checkov CKV_AWS_139 into DATA-005, and kept the distinct AWS-Backup-plan checkov finding (CKV2_AWS_8) as DATA-014. All 22 input findings are represented across 19 deduplicated entries. The four verifications I ran (worker_handler `_PERMANENT_ERRORS`, storage `read_releases` blanket `except Exception`, `rds.tf` flags, and the swallowed enqueue exception in `handler.py`) all matched the supplied evidence.

## Architecture

The system's macro-architecture is sound: a clean SQS-fanned ingest pipeline, a single `_ROUTE_TABLE` dispatch source of truth, a typed Pydantic settings layer, and a documented repository convention give the codebase a coherent skeleton. The most material weaknesses are seams where stated invariants are not machine-enforced — the OpenAPI generator never runs in CI, LLM enrichment vendors bypass the `providers/` registry and its `VENDORS_ENABLED` kill switch entirely (ADR-0004), and the highest-spend path has no architectural cost cap. A second cluster is erosion of layering discipline: a 1960-line handler god-module, raw SQL leaking outside repositories, tenant-identity extraction copy-pasted across six handlers, and config read two different ways. None are cross-tenant breaches, but several are latent cost or drift hazards that compound as new spec routes land.

### [ARCH-001] P2 — LLM enrichment vendors bypass the providers/ registry and VENDORS_ENABLED gate (ADR-0004 not honored)

**Where:** `src/collector/label_enrichment/orchestrator.py:159-197` (`build_adapters_from_run_config`) and `src/collector/label_enrichment_handler.py:106-111`; artist mirror in `src/collector/artist_enrichment/orchestrator.py:155-157`; cf. `src/collector/providers/registry.py:_BUILDERS` and `docs/adr/0004`.

**Evidence:** ADR-0004 states third-party music services are wrapped behind role Protocols (incl. `EnrichProvider`) in `providers/`, gated by `VENDORS_ENABLED`, so "disabling a vendor is a single env var change." But the live label/artist enrichment path constructs `GeminiAdapter`/`OpenAIAdapter`/`TavilyDeepSeekAdapter` directly in `build_adapters_from_run_config` (orchestrator.py:167-194) from `run_row['vendors']`, never touching `providers.registry` or `_enabled_vendors()`. The merge client is likewise a raw OpenAI/DeepSeek client built in the handler (`_build_merge_client`, label_enrichment_handler.py:53-56). The registry's only `EnrichProvider` is `SpotifyEnricher`, which is dead code (`providers/spotify/enrich.py:5`). grep confirms `artist_enrichment_handler`/`orchestrator` reference no registry symbols at all.

**Risk:** The dominant cost driver in the system (labels|artists × vendors × (generate+merge), Tavily internally 3 HTTP calls) has NO `VENDORS_ENABLED` kill switch. Disabling a misbehaving or key-revoked LLM vendor requires removing it from each run's stored `vendors` list or a code/SSM change — defeating ADR-0004's stated cost-control and revoked-key purpose. Tooling and tests that assume the registry governs all vendor calls are wrong for the highest-spend path.

**Recommendation:** Either route enrichment adapters through `providers/registry` as `EnrichProvider` implementations behind `VENDORS_ENABLED`, or add an explicit per-vendor enable gate read from settings inside `build_adapters_from_run_config` so an operator can disable gemini/openai/tavily_deepseek without a deploy. Update ADR-0004 to reflect the actual boundary.

**Effort:** M

### [ARCH-002] P2 — OpenAPI contract can silently drift from handlers/gateway: CI checks schema.d.ts against the committed yaml but never regenerates the yaml

**Where:** `.github/workflows/pr.yml:169-176`; `scripts/generate_openapi.py:1222` (`ROUTES`); `docs/api/openapi.yaml`.

**Evidence:** The contract lives in three independent places (system map gotcha #8): infra `route_key` declarations, the handler dispatch tables (`handler.py` / `curation_handler._ROUTE_TABLE`), and `scripts/generate_openapi.py:ROUTES` (which produces `docs/api/openapi.yaml`). The frontend CI job (pr.yml:169-176) runs `pnpm api:types` and fails if `frontend/src/api/schema.d.ts` diverges from the committed `docs/api/openapi.yaml`. But grep confirms no CI step ever runs `generate_openapi.py` and diff-checks its output against the committed yaml (the only references are inside the script itself). `docs/api/openapi.yaml` is a 163k checked-in artifact. So the verified invariant is "schema.d.ts matches the committed yaml," not "the yaml matches the actual routes." A developer who adds a route to infra + the handler but forgets to run `generate_openapi.py` leaves the yaml (and therefore schema.d.ts) stale, and all of CI stays green.

**Risk:** Frontend types and the documented API contract drift from the real backend surface with no automated detection. The SPA can be coded against a route shape that no longer matches the handler, surfacing only at runtime. The "three places" invariant has no machine enforcement at the yaml-vs-code seam.

**Recommendation:** Add a CI job (backend filter) that runs `PYTHONPATH=src python scripts/generate_openapi.py` to a temp file and `git diff --exit-code` against `docs/api/openapi.yaml`, mirroring the existing schema.d.ts freshness check. This closes the generator→yaml seam so the existing yaml→schema.d.ts check becomes transitively sound.

**Effort:** S

### [ARCH-003] P2 — Auto-enrichment block fan-out has no architectural size cap (uncapped per-dispatch LLM multiplier gated only by claim-dedup)

**Where:** `src/collector/label_enrichment/auto_dispatch.py:73-123`; `src/collector/artist_enrichment/auto_dispatch.py:101-118`; `src/collector/curation_handler.py:1534` (finalize trigger).

**Evidence:** `_dispatch_labels` calls `claim_labels(sorted(set(label_ids)))` then enqueues one SQS message per claimed label in batches of `_SQS_BATCH=10`, with no upper bound on `len(label_ids)` derived from a triage block (`label_ids_for_triage_block` / `artist_ids_for_triage_block`). Each enqueued item then costs vendors × (1 generate + 1 merge) LLM calls (the Tavily adapter is internally 3 HTTP calls). The only limiter is `claim_labels` dedup, which prevents re-dispatching already-claimed labels but does not cap a single dispatch. The auto path fires on every triage-block finalize.

**Risk:** A large finalized block (or first-ever enrichment of many labels) issues an unbounded burst of LLM calls — the largest uncapped cost multiplier in the system — with no architectural throttle. `maximum_concurrency=8` on the worker ESM bounds parallelism but not total spend; SQS just serializes the same total volume.

**Recommendation:** Add a per-dispatch cap (e.g. max labels/artists per auto-run, with remainder deferred) and/or a daily enrichment budget gate in `claim_labels`/`create_run`. Surface the cap as a config var so a runaway block cannot translate directly into thousands of vendor calls.

**Effort:** M

### [ARCH-004] P3 — curation_handler.py is a 1960-line god-module mixing categories, triage, tags, playlists, publish, match-review, and client construction

**Where:** `src/collector/curation_handler.py:1-1960`.

**Evidence:** A single handler file holds 44 route handlers across five distinct subdomains (categories, triage, tags, playlists, match-review) plus inline S3/Spotify/YTMusic client-builder helpers (e.g. `_build_spotify_user_client`, `_build_ytmusic_user_client` near lines 1860-1893) and a late mid-file `import re as _re` (line 1576). The `_ROUTE_TABLE` dispatch dict (lines 1895-1959) is a clean single source of truth, but the handlers and helpers it references are all colocated in one file.

**Risk:** High cognitive load and merge-contention surface; mixing transport handlers with vendor-client construction makes the publish/import flows harder to test in isolation and obscures the partial-failure paths flagged elsewhere. Drift risk as new spec routes append.

**Recommendation:** Split per-subdomain handler modules (categories/triage/tags/playlists) and extract the vendor-client builders into a small factory module, keeping `_ROUTE_TABLE` as the aggregation point. No behavior change required.

**Effort:** L

### [ARCH-005] P3 — Repository-pattern leak: raw SQL and direct DataAPIClient use in token resolvers and publish service

**Where:** `src/collector/curation/spotify_token_resolver.py:61-123`; `src/collector/curation/ytmusic_token_resolver.py:61-119`; `src/collector/curation/playlists_publish_service.py:168-173`.

**Evidence:** Three non-repository modules hold a `DataAPIClient` and embed SQL directly: `spotify_token_resolver.py` executes `SELECT` (line 70) and `UPDATE user_vendor_tokens SET ...` (lines 121-123); `ytmusic_token_resolver.py` does the same (lines 70, 117-119); `playlists_publish_service.py` runs `SELECT spotify_id FROM users WHERE id = :id` inline (lines 172-173). The codebase's stated convention is that all raw SQL lives in `*_repository.py` / `repositories.py` (§4); these services bypass that and own SQL against `user_vendor_tokens` and `users`.

**Risk:** SQL against the security-sensitive `user_vendor_tokens` table (KMS-encrypted vendor tokens) is scattered outside the repository layer, so schema changes, retry/transaction discipline, and audit of token-table access are no longer centralized. Increases the chance a future edit forgets the parameterization/transaction conventions the repositories enforce.

**Recommendation:** Move these queries into the existing `auth/auth_repository.py` (or a dedicated vendor-token repository) and have the resolvers/publish service depend on that, keeping all SQL — especially `user_vendor_tokens` access — in the repository layer.

**Effort:** M

### [ARCH-006] P3 — Tenant-identity extraction reimplemented independently in 6+ handlers with inconsistent None-handling

**Where:** `src/collector/curation_handler.py:171`; `label_enrichment/routes.py:61`; `label_enrichment/auto_routes.py:31`; `artist_enrichment/routes.py:61`; `artist_enrichment/auto_routes.py:31`; `auth_handler.py:537`; `handler.py:89-95`.

**Evidence:** The identical body parsing `event.requestContext.authorizer.lambda.user_id` is copy-pasted as `_extract_user_id` / `_user_id_or_none` / `_authorizer_context` in at least six modules. They diverge in failure behavior: curation `_user_id_or_none` returns `None` and the caller 401s (curation_handler.py:447-449); enrichment routes are inconsistent within the same file — `handle_put_label_preference` raises "user_id is required" when `None` (routes.py:275-277) but `handle_get_label_user` passes `_extract_user_id(event)` straight into the query allowing `None` (routes.py:233). Tenant isolation is a per-query discipline (no gateway guarantee, per the system map), so each copy is load-bearing for multi-tenant data separation.

**Risk:** A behavior change (claim-name change, admin-claim addition, None-vs-401 policy) must be hand-replicated across all copies; missing one creates an isolation gap or an inconsistent 401/200 contract. A `None` user_id reaching a `WHERE user_id=...` query can return cross-tenant or null-scoped rows depending on the SQL, and the divergence already exists between routes in the same file.

**Recommendation:** Extract one shared `require_user_id(event)` / `optional_user_id(event)` helper (e.g. in a small auth-context module) and have every handler import it; make the "missing identity" decision (raise vs None) explicit and uniform per route category. Add a test asserting all user-scoped routes 401 on a token-less / user_id-less context.

**Effort:** M

### [ARCH-007] P3 — Single dist/collector.zip bundles all heavyweight deps into every Lambda, including the 256MB/5s auth_authorizer

**Where:** `scripts/package_lambda.sh:1-31`; `requirements-lambda.txt`; `infra/auth.tf:112-131` (auth_authorizer 256MB/5s); `src/collector/auth_authorizer.py:5-11`.

**Evidence:** `package_lambda.sh` produces one artifact (`dist/collector.zip`) by `pip install -r requirements-lambda.txt` then copying all of `src/collector`. `requirements-lambda.txt` pulls google-genai, openai, ytmusicapi, sqlalchemy, alembic, cryptography, psycopg[binary]. All 11 Lambdas deploy this same zip (`infra/variables.tf:49-53`). The latency-critical authorizer (256MB memory, 5s timeout, on the hot path of every authenticated request, cached only 300s) imports only PyJWT-level code (auth_authorizer.py:9-11) yet ships the full multi-hundred-MB dependency tree. `psycopg[binary]` is in the runtime artifact even though only the VPC migration Lambda imports it (migration_handler.py:96,113) — it is never imported by a Data-API handler, so the CLAUDE.md "no psycopg at runtime" rule holds, but the binary still inflates every package.

**Risk:** Larger package = slower cold-start init for every function, worst on the small/fast authorizer where init time adds to first-request latency under the 5s timeout. A vulnerable transitive dep in any vendor SDK widens the attack surface of unrelated Lambdas (e.g. the public auth Lambda carries the LLM SDKs). Per-function right-sizing is impossible with one shared artifact.

**Recommendation:** Split packaging: a minimal artifact for auth_authorizer/auth/curation/api (PyJWT, pydantic, boto3, cryptography) and a worker artifact carrying the enrichment SDKs; or move heavy SDKs to a shared Lambda layer attached only to the enrichment/search workers. At minimum drop psycopg from `requirements-lambda.txt` and install it only into the migration build path.

**Effort:** M

### [ARCH-008] P3 — SQS workers loop over Records with per-record continue/raise but no ReportBatchItemFailures — correctness depends entirely on batch_size=1

**Where:** `src/collector/worker_handler.py:50-182`; `infra/lambda.tf:100,143,184,226,275,318` (batch_size vars, no `function_response_types`).

**Evidence:** `worker_handler.lambda_handler` iterates `for record in event['Records']`, using `continue` to drop permanent-error messages and `raise` to redrive transient ones (worker_handler.py:52,55,67,177-180). No ESM in `infra/lambda.tf` sets `function_response_types=['ReportBatchItemFailures']`, and the worker returns `{'processed': n}`, not a `batchItemFailures` shape. This is only correct because every ESM uses `batch_size=1` (the loop processes exactly one record). The code shape (a loop with per-record drop/raise) implies multi-record handling that the infra does not actually support safely.

**Risk:** If any `*_batch_size` var is ever raised above 1 (these are configurable terraform vars, not constants), a single transient `raise` re-delivers the whole batch — re-processing already-committed records (canonicalization is idempotent so data is safe, but vendor/LLM calls and Spotify searches would re-fire, multiplying cost) — while there is no per-record partial-failure reporting to limit the blast radius. A latent coupling between code semantics and an infra constant.

**Recommendation:** Either pin the batch_size vars to 1 with a comment that the workers are not partial-batch-safe, or implement `ReportBatchItemFailures` (set `function_response_types` on each ESM and return `{'batchItemFailures': [...]}`) so the loop is genuinely multi-record safe before batch_size is ever increased.

**Effort:** M

### [ARCH-009] P3 — Configuration access split between the typed settings layer and ad-hoc os.environ reads

**Where:** `src/collector/settings.py:133-220` (typed queue-url fields); `label_enrichment/auto_dispatch.py:51`, `routes.py:55`; `artist_enrichment/auto_dispatch.py:49`, `routes.py:55`; `curation/auto_enrich_dispatch.py:23`.

**Evidence:** Queue URLs are defined as typed Pydantic settings fields (`settings.py`: `canonicalization_queue_url`, `spotify_search_queue_url`, `vendor_match_queue_url`, `label_enrichment_queue_url`, `artist_enrichment_queue_url`) and read that way in handler.py:887 and curation_handler.py:404. But the enrichment/dispatch modules bypass the settings layer and read raw `os.environ.get('LABEL_ENRICHMENT_QUEUE_URL')` / `'ARTIST_ENRICHMENT_QUEUE_URL'` / `'AUTO_ENRICH_DISPATCH_QUEUE_URL'` directly, raising bare `RuntimeError` on absence. So the same configuration surface has two readers with different validation, defaulting, and error semantics.

**Risk:** The Pydantic settings classes are no longer the single source of truth for configuration; an env-name typo or rename is caught by the typed layer for some consumers and only at runtime (`RuntimeError`) for others. Aliases/defaults defined in `settings.py` (e.g. the `CANONICALIZATION_QUEUE_URL`/`CANONICALIZE_QUEUE_URL` dual alias) are not honored on the os.environ path.

**Recommendation:** Route all queue-URL access through the settings layer (add the enrichment/dispatch queue URLs to the appropriate Settings class and read them via `get_*_settings()`), removing the direct `os.environ.get` calls so configuration validation is uniform.

**Effort:** S

### [ARCH-010] P3 — _scope_check validates the track is in the user's overall scope, not in the specific playlist named in the URL

**Where:** `src/collector/curation_handler.py:315-320` (`_scope_check`), used by `_handle_match_candidates` (323-339) and `_handle_resolve_match` (349-385); route `POST /playlists/{id}/tracks/{track_id}/match-resolve`.

**Evidence:** `_scope_check` confirms (1) `repo.get(user_id=user_id, playlist_id=pid)` is not `None` (playlist belongs to caller) and (2) the track is in `validate_tracks_in_scope` (any of the user's categories/playlists/imported tracks, `playlists_repository.py:82-104`). It never asserts the track is actually a member of playlist `{id}`. The `{id}` path param is therefore only an ownership token, not a real constraint linking the track to that playlist.

**Risk:** No cross-tenant breach (both checks are user-scoped), but the route's contract is misleading: a caller can resolve a YT Music match for any track in their library via any playlist they own, even if that track is not in that playlist. Combined with the global `vendor_track_map` (separate finding), this widens who can trigger a shared-state write. Low impact for the MVP audience.

**Recommendation:** Either drop `{id}` from the match-resolve/candidates routes (they are effectively track-scoped, not playlist-scoped) or add a membership check that the track exists in `playlist_tracks` for `{id}` so the URL semantics match enforcement.

**Effort:** S

## AWS cost

Overall this dimension is **weak for a money-sensitive MVP**, and the weakness is concentrated where the dollars actually are: third-party LLM/search vendor spend, not AWS compute. The dominant exposure — the enrichment fan-out — is non-idempotent at every layer (no pre-vendor gate, blind counter increments, `maxReceiveCount=3` redrive, and an uncapped per-block fan-out), so a single transient Aurora blip or Lambda timeout can re-spend the full vendor cost for a whole batch of items. Compounding this, there is no AWS Budget or billing alarm anywhere, and the alarms that do exist page nobody because the SNS topic defaults to empty — so the team would learn of a runaway from the vendor invoice, not from monitoring. The remaining issues (S3 versioning with no lifecycle, N+1 Data API round-trips, redundant Spotify re-enqueue) are real but secondary to the unbounded-vendor-spend cluster.

### [COST-001] P2 — No AWS Budget or billing alarm anywhere in infra

**Where:** `infra/` (entire Terraform tree; grep for `aws_budgets_budget` / `EstimatedCharges` / `aws_ce_` returns nothing).
**Evidence:** Grep across all `*.tf` files for `aws_budgets`, `billing`, `EstimatedCharges`, `aws_ce_` returns zero matches (confirmed). The only cost-adjacent guardrail is the Aurora ACU-near-max alarm (`alarms.tf:103-121`), which caps DB compute at 2 ACU but says nothing about the dominant spend drivers: LLM enrichment fan-out (~N×6 upstream calls per triage-block auto-enrich, no block-size cap), Spotify ISRC self-perpetuating search (`spotify_handler.py:267` `auto_continue` re-enqueue), and Beatport 300-page paginated fetch (`beatport_client.py:52`). None of these vendor-spend paths has any AWS-side budget ceiling or billing-threshold alarm.
**Risk:** A runaway auto-enrich over a large triage block, a stuck Spotify `auto_continue` loop, or a leaked/abused API key produces unbounded third-party LLM/vendor charges with no AWS-native early warning. For a small-DJ-circle MVP this is the single largest dollar exposure and it is completely unmonitored.
**Recommendation:** Add an `aws_budgets_budget` (monthly cost budget with NOTIFY thresholds at e.g. 50/80/100%) and a CloudWatch `EstimatedCharges` alarm in `us-east-1` routed to the alarm SNS topic. Pair with a hard cap on auto-enrich block fan-out size in the dispatch layer.
**Effort:** S

### [COST-002] P2 — Every CloudWatch/SQS/Aurora alarm pages nobody by default (alarm_sns_topic_arn defaults to empty)

**Where:** `infra/variables.tf:230-234`; `infra/alarms.tf:47-48,72-73,98-99,119-120`; `infra/logging.tf:88-89`.
**Evidence:** `variable "alarm_sns_topic_arn" { default = "" }` (`variables.tf:233`, confirmed). Every alarm wires actions conditionally: `alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []` (`alarms.tf:47-48, 72-73, 119-120`; `logging.tf:88-89`). With the default empty value, the Lambda-errors, duration-p95, Aurora-ACU-near-max, and all six DLQ-depth alarms are created but have zero notification targets.
**Risk:** A DLQ filling with failed paid-work messages, an Aurora ACU saturation, or a failing enrichment worker triggers an alarm that silently goes to ALARM state and notifies no one. The team learns of cost/reliability incidents only via the AWS bill, defeating the purpose of the alarms.
**Recommendation:** Make `alarm_sns_topic_arn` required (no default) or create an SNS topic + email subscription in-module and default the alarms to it. At minimum document that alarms are inert until the var is supplied and gate `terraform apply` on it for prod.
**Effort:** S

### [COST-003] P2 — Enrichment worker re-spends ALL paid vendor calls on SQS redrive (no idempotency gate before vendor fan-out)

**Where:** `src/collector/label_enrichment_handler.py:114`; `src/collector/artist_enrichment_handler.py:102`; `src/collector/label_enrichment/orchestrator.py:91-115`; `src/collector/artist_enrichment/orchestrator.py:90-111`.
**Evidence:** The SQS worker calls `enrich_label_for_run` / `enrich_artist_for_run` with NO try/except around the paid call (`label_enrichment_handler.py:114`, `artist_enrichment_handler.py:102`; the only try/except wraps Pydantic validation, confirmed). Inside, `run_vendors_parallel` executes the paid Gemini + OpenAI + Tavily (2 Tavily HTTP + 1 DeepSeek) + DeepSeek-merge calls UNCONDITIONALLY (`orchestrator.py:93` then `merge_cells` at `:117`). All persistence — `insert_cell`, `upsert_label_info`, `increment_run_counters` — happens AFTER the paid calls (`orchestrator.py:105-134`). `insert_cell` has `ON CONFLICT (run_id,label_id,vendor) DO NOTHING` (`repository.py:713`) which protects the DB row but does NOT gate the already-completed paid call. There is no "cells already exist for this run+label?" check before `run_vendors_parallel`, and `mark_run_running` (`repository.py:731`) is a no-op when already 'running' but does not short-circuit the vendor calls. Any exception during persistence (Data API `ThrottlingException`/`StatementTimeout`, JSON encode, etc.) OR a Lambda timeout (not a Python exception, so the visibility timeout simply re-exposes the message) raises/redrives the message.
**Risk:** Every redrive re-incurs the full vendor spend for that label/artist (~6 upstream LLM/search calls for the default 3-vendor set). With label/artist queue `maxReceiveCount=3` (`infra/variables.tf:452,505`), a label whose persistence keeps failing pays up to 3× the full vendor cost before reaching the DLQ. A transient Aurora throttle or a 900s timeout window where vendors finished but writes did not turns into duplicate paid LLM/Tavily/DeepSeek billing across the whole batch of claimed items.
**Recommendation:** Make the worker idempotent BEFORE spending: at the top of `enrich_*_for_run`, check whether cells already exist for `(run_id, label_id)` (e.g. `SELECT 1 FROM clouder_label_enrichment_cells WHERE run_id=:r AND label_id=:l`) or whether `clouder_label_info.last_run_id` already equals this run, and skip the vendor fan-out if so. Alternatively wrap `enrich_*_for_run` in try/except that, on persistence failure after vendor calls, persists what it can and does NOT re-raise (so the message is not redriven). Lowering `maxReceiveCount` to 1 for the enrichment queues would also cap re-spend.
**Effort:** M

### [COST-004] P2 — Auto-enrichment fan-out per triage block is uncapped (block size is an unbounded paid-call multiplier)

**Where:** `src/collector/label_enrichment/auto_repository.py:236-248` (`label_ids_for_triage_block`) and `claim_labels:108-181`; `src/collector/artist_enrichment/auto_repository.py:108` (`claim_artists`) + `artist_ids_for_triage_block`; `src/collector/label_enrichment/auto_dispatch.py:155-162`; `src/collector/auto_enrich_dispatch_handler.py:26-27`.
**Evidence:** On triage-block finalize, the dispatch worker calls `try_dispatch_for_triage_block` + `try_dispatch_artists_for_triage_block` (`auto_enrich_dispatch_handler.py:26-27`). `label_ids_for_triage_block` (`auto_repository.py:236`) is a plain `SELECT DISTINCT` with no `LIMIT`, and `claim_labels` (`auto_repository.py:108-181`) chunks in `_IN_CHUNK=500` but applies no upper bound on total claimed labels; the same holds for artists. Each claimed label/artist becomes one SQS message → one full vendor run (~6 upstream calls for the default 3-vendor set). The only limiter is the per-item `_MAX_ATTEMPTS=2` claim dedup (`auto_repository.py:11`). By contrast the MANUAL enrich path is explicitly capped at `max_length=100` labels (`label_enrichment/messages.py:45`) — the auto path has no equivalent cap.
**Risk:** A single finalize of a large triage block (hundreds of distinct labels + hundreds of distinct artists across the block's tracks) fans out into hundreds of paid LLM/Tavily/DeepSeek enrichment runs with no ceiling, multiplied again by the redrive re-spend in COST-003/COST-006. Spend per finalize scales linearly with block size and is bounded by no config; alarms default to an empty SNS topic so nothing pages.
**Recommendation:** Cap the number of labels/artists claimed per auto-dispatch (e.g. `LIMIT` in `label_ids_for_triage_block`/`claim_labels` or a configurable `max_auto_enrich_items_per_block`, dropping or deferring the remainder), mirroring the manual path's `max_length=100`. Add a CloudWatch metric/alarm on enrichment-run creation rate.
**Effort:** M

### [COST-005] P2 — enrich_*_for_run double-counts run counters and re-spends LLM vendor calls on SQS redelivery (non-idempotent)

**Where:** `src/collector/label_enrichment/orchestrator.py:93-134` + `repository.py:687-729` (`insert_cell` ON CONFLICT DO NOTHING) vs `repository.py:998-1037` (`increment_run_counters` blind `+=`); `artist_enrichment/repository.py:289-298` + `:253-276`.
**Evidence:** `enrich_label_for_run` runs the vendor fan-out (`run_vendors_parallel`, `orchestrator.py:93`) BEFORE writing cells, then calls `insert_cell` (`ON CONFLICT (run_id,label_id,vendor) DO NOTHING`, `repository.py:713`) and finally `increment_run_counters`, which unconditionally does `cells_ok = cells_ok + :ok` / `cells_error = cells_error + :err` / `cost_usd = cost_usd + :cost` (`repository.py:1017-1019`) with no idempotency guard. SQS at-least-once delivery + `batch_size=1` + no `ReportBatchItemFailures` means a redelivered message (worker timed out after committing cells but before the SDK returned, or any transient post-cell error that re-raises) re-runs ALL vendor LLM calls (re-spend) and increments the counters a SECOND time. The cell rows are protected by `ON CONFLICT DO NOTHING`, but the counter UPDATE is not.
**Risk:** On redelivery: (1) every Gemini/OpenAI/Tavily/DeepSeek call for that item is re-spent (the Tavily adapter alone is 3 upstream HTTP calls); (2) `cells_ok`/`cells_error` overshoot `cells_total`, which can prematurely or incorrectly flip status to 'completed' for OTHER concurrent items, or report counts that exceed `cells_total`. Uncontrolled vendor spend on retry plus corrupted run accounting.
**Recommendation:** Make the counter update idempotent: recompute `cells_ok`/`cells_error` from the cells table (e.g. `SET ... = (SELECT counts FROM cells WHERE run_id=...)`) instead of blind `+=`, OR gate the increment on `insert_cell` having actually inserted (use `RETURNING` / rowcount from the ON CONFLICT). Also check for an existing cell before invoking vendors to avoid the re-spend.
**Effort:** M

### [COST-006] P2 — Enrichment queue maxReceiveCount=3 re-runs full paid LLM vendor fan-out on each redelivery (up to 3× spend per transient failure)

**Where:** `infra/sqs.tf:77-81,98-102`; `infra/variables.tf:449-453,502-506` (`maxReceiveCount` default 3).
**Evidence:** `label_enrichment` and `artist_enrichment` queues use `maxReceiveCount = var.*_queue_max_receive_count` defaulting to 3 (`variables.tf:452, 505`, confirmed). The enrichment workers have no per-LLM-call idempotency (see COST-003) — a re-run re-hits every vendor — and the worker has no try/except around `enrich_label_for_run`, so any non-parse failure (a vendor adapter raising, a DB transient) propagates and the whole message is redriven, re-running the full `vendors × (1 generate + 1 merge)` fan-out (~6 upstream calls for a 3-vendor run, Tavily cell = 3 HTTP calls). With `maxReceiveCount=3` a persistently-failing message costs up to 3 complete vendor fan-outs before reaching the DLQ.
**Risk:** A flaky vendor or DB blip triples the LLM/Tavily/DeepSeek bill for affected items, and at block-scale auto-enrich (no block-size cap, COST-004) this multiplies across many labels/artists. The spend is real money to third parties, not just AWS.
**Recommendation:** Either lower enrichment `maxReceiveCount` to 1-2, or make the worker idempotent at the cell level (skip vendors whose cell already exists for the run before re-calling) so redelivery does not re-incur generate calls. Document the per-retry cost multiplier next to the variable.
**Effort:** M

### [COST-007] P2 — Enrichment ESM has no partial-batch-failure reporting; redrive is the only failure path and always re-spends

**Where:** `infra/lambda.tf:223-235` (label) and `:272-284` (artist) `event_source_mapping`; `src/collector/label_enrichment_handler.py:59-136`; `src/collector/artist_enrichment_handler.py:47-123`.
**Evidence:** Neither enrichment `event_source_mapping` sets `function_response_types = ["ReportBatchItemFailures"]` (grep over `infra/lambda.tf` returns no such key), and neither handler returns a `{batchItemFailures: [...]}` payload — `lambda_handler` returns `{"processed": n}`. `batch_size` defaults to 1 (`infra/variables.tf:473-477, 526-530`), so today one record = one invocation, which limits blast radius, but it means the ONLY way a failure is handled is a whole-message redrive. Combined with the lack of a pre-vendor idempotency gate (COST-003), any post-vendor failure forces a redrive that re-runs the paid vendor calls rather than re-trying only the unfinished persistence step.
**Risk:** If `batch_size` is ever raised above 1 for throughput, a single failing record would redrive the entire batch and re-spend vendor calls for every label/artist in it. Even at `batch_size=1`, the missing idempotency means redrive == re-spend, so the design has no cheap retry of just the DB write.
**Recommendation:** Add `function_response_types = ["ReportBatchItemFailures"]` to both enrichment ESMs and return per-record `itemIdentifier` failures from the handler, and/or split vendor-spend from persistence so a persistence-only retry never re-hits vendors. Document that `batch_size` must stay 1 until idempotency exists.
**Effort:** S

### [COST-008] P2 — Canonicalization does one serial Data API round-trip per entity (N+1 find_identity + per-row create/update)

**Where:** `src/collector/canonicalize.py:451,486,521,558,604,611`; `src/collector/repositories.py:413-441,647-694`.
**Evidence:** Every label/style/artist/album/track is resolved one-by-one: each phase loops entities and calls `self._repository.find_identity(...)` (`canonicalize.py:451/486/521/558/604`), which issues a single-row SELECT via `DataAPIClient.execute` (`repositories.py:413-434`). On a cache hit for a track, `conservative_update_track` issues another single-row UPDATE (`repositories.py:647-694`). There is NO batch identity-lookup method — only `find_identity` (single row) and `batch_upsert_identities` exist. A weekly run of up to 300 pages × 100 tracks (`beatport_client` `max_pages=300`, `per_page=100`) plus their artists/albums means thousands of serial RDS Data API calls. Only the source_entity/identity UPSERTs and track-artist inserts are batched; the lookups and existing-track updates are not.
**Risk:** Each `find_identity`/create/update is a synchronous Data API round-trip (~10-50ms), so a large run serializes into thousands of calls. This (a) drives Data API request cost and repeated Aurora resume churn under `min_acu=0`, and (b) inflates worker wall-clock toward the 900s Lambda timeout; a timeout is not a Python exception, so the run is left silently at `RAW_SAVED` with partial committed data.
**Recommendation:** Batch the identity resolution: pre-load all existing identities for a phase with a single `SELECT ... WHERE (source,entity_type,external_id) IN (...)` before the loop (mirroring the existing IN-list pattern in `propagate_release_type_to_albums`), and collapse existing-track updates into a `batch_execute` UPDATE keyed by id. This turns each phase from O(N) round-trips into O(1)+batch.
**Effort:** M

### [COST-009] P2 — Raw S3 bucket has versioning enabled and no lifecycle policy; same-key overwrites accumulate unbounded noncurrent versions

**Where:** `infra/s3.tf:5-11` (versioning Enabled), no `aws_s3_bucket_lifecycle_configuration` anywhere in `infra/`; `src/collector/storage.py:245-248` (`_base_key` omits `run_id`).
**Evidence:** The raw bucket has `versioning_configuration { status = "Enabled" }` (`s3.tf:8`, confirmed) and grep across `infra/` finds zero `lifecycle_configuration` resources (confirmed). The S3 key is `{raw_prefix}/style_id={id}/year={y}/week={w}/releases.json.gz` keyed by style+year+week only — no `run_id` (`storage.py:245-248`). Re-running the same style/week overwrites `releases.json.gz` and `meta.json` (`handler.py:414`), and because versioning is on, every overwrite creates a new noncurrent version that is never expired. The same bucket also holds Spotify results (`raw/sp/tracks`) and playlist covers (`covers/*`) with no expiration. `tests/integration/test_handler.py:146` (`test_rerun_same_week_overwrites_latest_snapshot_only`) confirms overwrite-on-rerun is expected behavior.
**Risk:** Storage cost grows without bound as runs are re-executed (a normal operational pattern given the retry behavior). Every retried week multiplies stored object versions; with versioning on and no expiration, even deleting current objects leaves all historical versions billed indefinitely.
**Recommendation:** Add an `aws_s3_bucket_lifecycle_configuration` to the raw bucket: expire noncurrent versions after N days, abort incomplete multipart uploads, and optionally transition old raw snapshots to a cheaper storage class. Scope rules per prefix (`raw/`, `raw/sp/`, `covers/`).
**Effort:** S

### [COST-010] P3 — Artist-enrichment worker and auto-enrich dispatch worker have no Errors alarm — a failing paid LLM path is unmonitored

**Where:** `infra/alarms.tf:14-21` (`worker_lambdas` map) and `:29-49` (`lambda_errors` for_each over `all_lambdas`).
**Evidence:** `local.worker_lambdas` (`alarms.tf:14-19`) lists `canonicalization`, `spotify_search`, `vendor_match`, and `label_enricher` — but omits `artist_enricher_worker` and `auto_enrich_dispatch_worker` (confirmed). `local.all_lambdas = merge(api_lambdas, worker_lambdas)` (`alarms.tf:21`) is what the `lambda_errors` alarm iterates (`alarms.tf:30`). Both omitted functions exist (`lambda.tf:239-313`) and run paid LLM fan-out (artist enrichment) / fan-out dispatch (auto_enrich_dispatch). The artist path is a near-exact mirror of the label path with identical Gemini/OpenAI/Tavily+DeepSeek cost.
**Risk:** If the artist enrichment worker starts erroring (malformed vendor responses, partial failures re-driving the SQS message up to `maxReceiveCount=3`), it silently burns LLM spend on retries with no Errors alarm. The dispatch worker driving the fan-out is also unalarmed, so a fan-out storm goes unnoticed.
**Recommendation:** Add `artist_enricher_worker` and `auto_enrich_dispatch_worker` to `local.worker_lambdas` so the `lambda_errors` alarm covers them. (DLQ-depth alarms in `logging.tf` already cover their queues, but per-function Errors closes the gap before redrive.)
**Effort:** S

### [COST-011] P3 — Spotify search batch re-enqueued on every canonicalization delivery, including duplicates and empty re-runs

**Where:** `src/collector/worker_handler.py:134-138, 185-208`; `src/collector/canonicalize.py:95-115`; `infra/sqs.tf:6-19`.
**Evidence:** `_enqueue_spotify_search_after_canonicalization` sends `{"batch_size":2000}` unconditionally after every successful message (`worker_handler.py:135`), with no reference to `result.tracks_processed`. The canonicalization queue is a standard SQS queue (`infra/sqs.tf:6` — no FIFO/dedup, `maxReceiveCount=5`), so it delivers at-least-once; a duplicate delivery or a re-run of an already-canonicalized week (`tracks_processed` could be 0, or all identities already exist) still fires a full Spotify search batch. The Spotify path costs 5+ vendor calls per ISRC miss (neighbour+metadata cascade) and self-perpetuates via `auto_continue` follow-ups.
**Risk:** Each redundant canonicalization delivery triggers a fresh 2000-track Spotify search sweep; `find_tracks_needing_spotify_search` filters already-searched tracks so duplicates are bounded, but a redrive storm or repeated admin re-ingest of the same week multiplies Spotify API spend and Aurora wakeups for no new data.
**Recommendation:** Guard the enqueue on `result.tracks_processed > 0` (or on whether any new/updated tracks lack `spotify_searched_at`). Skipping the enqueue when nothing changed removes the redundant vendor fan-out without affecting correctness.
**Effort:** S

### [COST-012] P3 — Secret-sync step overwrites 8 SSM SecureStrings on every push to main

**Where:** `.github/workflows/deploy.yml:53-79`.
**Evidence:** The `Sync GitHub secrets to SSM Parameter Store` step runs unconditionally on every push to main and issues 8 `aws ssm put-parameter --overwrite` calls (gemini/openai/tavily/deepseek/spotify×2/ytmusic×2). There is no change-detection — values are re-written identically each deploy, and every merge creates a new SSM parameter version.
**Risk:** Minor but unbounded: each deploy bumps 8 SSM parameter versions (SSM keeps up to 100 versions per advanced param / overwrites standard), generates put-parameter API calls, and (since secrets are passed as `--value "${{ secrets.X }}"`) relies entirely on GitHub log-masking for non-exposure. No cost blowup, but the unconditional rewrite is noise and a rotation-audit confounder.
**Recommendation:** Make the sync conditional (only when secrets changed) or move it out of the per-push path into a separate manually/secret-rotation-triggered workflow. Confirm the params are standard-tier so version accumulation is bounded.
**Effort:** S

## Reliability

Reliability is the weakest dimension in this MVP. The dominant theme is **silent failure with no recovery path**: the enrichment, ingest, and canonicalization pipelines all rely on a per-item worker reaching the end of its invocation to advance run state, yet a Lambda timeout is not a Python exception — so any timed-out or DLQ'd worker strands its parent run in a non-terminal status forever, with no sweeper, reconciler, or in-progress state to detect it. This is compounded at the observability layer: every CloudWatch alarm defaults to an empty SNS topic, so DLQ-depth and Lambda-error alarms fire into the void, and two worker Lambdas have no error alarm at all. Two P1 correctness hazards sit on top of this — a self-inflicted session-revocation race in the auth refresh path, and a synchronous Beatport fetch that blows the 29s API Gateway budget while side effects persist — plus a deploy pipeline that ships new Lambda code against the old schema before migrations run. None of these fail loudly; nearly all degrade silently, which is the worst failure mode for an MVP with a small operator team.

### [REL-001] P1 — Two unguarded /auth/refresh callers race and trip replay detection, revoking all sessions

- **Where:** `frontend/src/api/client.ts:8-40,58-74`; `frontend/src/auth/AuthProvider.tsx:156-174,200-207,233-256`
- **Evidence:** Two independent refresh paths POST `/auth/refresh` with the same cookie. The client's silent 401-retry uses `tryRefreshOnce()` whose module-level `inflightRefresh` promise dedups ONLY client-path callers (`client.ts:18,59`). `AuthProvider.refresh()` calls `api('/auth/refresh')` directly (`AuthProvider.tsx:158`) — a 200 response, so it never enters `tryRefreshOnce` and is invisible to `inflightRefresh`. The scheduled proactive refresh (`scheduleRefresh -> refreshRef.current()`, `AuthProvider.tsx:133-135`) and the bootstrap refresh (`AuthProvider.tsx:201`) both go through `AuthProvider.refresh`. The `bootstrapStarted` ref (`AuthProvider.tsx:115,196`) only guards the StrictMode double-bootstrap; it does NOT cross-coordinate with the client's 401-retry path. If a background request 401s (waking the silent retry) at roughly the same moment the scheduled timer fires `AuthProvider.refresh`, both POST `/auth/refresh` with the same cookie. The backend rotates the session hash on the first (`_handle_refresh rotate_session`, `auth_handler.py:464-468`); the second presents the now-stale hash, hitting `if session.refresh_token_hash != inbound_hash: revoke_all_user_sessions` (`auth_handler.py:414-417`).
- **Risk:** A timing coincidence between the proactive refresh timer and a 401-driven silent refresh revokes every session of the user (ADR-0015 all-sessions revocation), forcing a full re-login across all devices. Not malicious replay — a self-inflicted false positive the bootstrap guard does not cover.
- **Recommendation:** Route `AuthProvider.refresh()` through the same `inflightRefresh` dedup as `tryRefreshOnce` (single shared refresh singleton), or have `AuthProvider` listen for `auth:refreshed`/`auth:expired` only and never POST `/auth/refresh` itself except via the shared path. At minimum, suppress the scheduled timer while a client refresh is inflight.
- **Effort:** M

### [REL-002] P1 — Synchronous Beatport fetch (up to 300 pages, no deadline guard) blows the 29s API Gateway budget; side effects persist after client 504

- **Where:** `src/collector/beatport_client.py:33,44-84,100-149`; `src/collector/handler.py:341-446`; `infra/api_gateway.tf:18-23` (no `timeout_milliseconds` → 29s default); `infra/variables.tf:31-35` (`lambda_timeout=120s`)
- **Evidence:** POST `/collect_bp_releases` and POST `/admin/beatport/ingest` call `_run_beatport_ingest` synchronously inside the API Gateway request. `BeatportClient.fetch_weekly_releases` loops up to `max_pages=300` (`beatport_client.py:52,64`), each `_request_page` has `timeout_seconds=15.0` and `max_retries=4` with exponential backoff (`beatport_client.py:33-35,100,136-146`). There is NO deadline/remaining-time guard (unlike `spotify_client.py` which checks `remaining_ms<60_000`). The API Gateway integration sets no `timeout_milliseconds`, so it uses the 29s default; the Lambda timeout is 120s. A genuinely large week (or one slow/retrying page) can exceed 29s — API GW returns 504 to the client while the Lambda keeps running to 120s and only THEN writes the S3 snapshot, `ingest_runs` row, and SQS message (`handler.py:409-446`). Even the happy path of ~300 pages at minimal latency (300 × backoff/network) can exceed both 29s and 120s.
- **Risk:** On any non-trivial style/week the operator gets a 504 with no `run_id`, while the run can still complete server-side (S3 + `ingest_runs` + enqueue) up to the 120s Lambda cap — or be killed mid-fetch by the 120s timeout, leaving nothing persisted and wasted Beatport calls. The 504 is indistinguishable from a real failure, encouraging blind re-runs (each re-run re-pays the full Beatport call volume and overwrites the S3 snapshot).
- **Recommendation:** Make ingest async: have the API route validate, write a 'started' `ingest_runs` row, enqueue a fetch job, and return 202 with `run_id` immediately — move the Beatport fetch+S3 write into a worker Lambda with the 900s budget. Failing that, add a deadline guard in `BeatportClient` using `context.get_remaining_time_in_millis()` to stop paginating before the Lambda dies, cap `max_pages` via config, and lower per-page timeout so total fetch fits the 29s budget.
- **Effort:** L

### [REL-003] P1 — Deploy applies new Lambda code (Terraform apply) BEFORE migrations run — schema/code skew window

- **Where:** `.github/workflows/deploy.yml:81-132` (Terraform apply at :81, migrations at :102)
- **Evidence:** `deploy.yml` runs `terraform apply -auto-approve` (line 83) which republishes `dist/collector.zip` to ALL runtime Lambdas (canonicalization_worker, curation, spotify, etc.) BEFORE the 'Run DB migrations via Lambda' step (line 102) invokes the migration Lambda. New code therefore runs against the OLD schema during the entire window between apply completion and migration success — and permanently if the migration step fails. Concrete instance: `alembic/versions/20260531_30_track_key.py:21-28` adds `clouder_tracks.key_name`/`key_camelot`, and `conservative_update_track` (`repositories.py:647-694`, per system map) writes `key_camelot`. A deploy shipping that canonicalizer build before migration 30 lands makes every canonicalization UPDATE/INSERT referencing `key_camelot` fail with 'column does not exist'.
- **Risk:** Between Terraform apply and migration completion, worker/curation Lambdas executing SQL that references not-yet-created columns fail (canonicalization stuck at RAW_SAVED, curation 5xx). If the migration step fails, the new code is live against the stale schema with no automatic rollback. SQS-driven workers retry into DLQ; user-facing curation returns errors.
- **Recommendation:** Re-order `deploy.yml` so migrations run BEFORE the Terraform apply that swaps Lambda code (expand-then-migrate, or migrate-then-deploy-code), or split into two terraform applies: apply infra+migration-Lambda first, run migrations, then apply the rest. At minimum gate the code swap on migration success. Adopt expand/contract migration discipline so code and schema overlap is always backward-compatible.
- **Effort:** M

### [REL-004] P2 — Enrichment run permanently stuck at 'running' when any per-item worker invocation dies (timeout or DLQ exhaustion)

- **Where:** `src/collector/label_enrichment/repository.py:998-1037` (`increment_run_counters`) + `orchestrator.py:91,129`; `src/collector/artist_enrichment/repository.py:243-276` + `orchestrator.py:90,125`; `src/collector/label_enrichment_handler.py:114-126`; `src/collector/artist_enrichment_handler.py:102-113`
- **Evidence:** A manual/auto run fans out one SQS message per label/artist (`auto_dispatch.py:111-123`). The parent run is created with `status='queued'` and `cells_total = requested_labels * len(vendors)` (`repository.py:644`). The first worker pickup flips it to 'running' (`mark_run_running`, `repository.py:731-740`). The run only flips to 'completed' inside `increment_run_counters`, whose CASE checks `cells_ok + cells_error + :ok + :err >= cells_total` (`repository.py:1020-1027`). `increment_run_counters` runs at the END of `enrich_label_for_run` (`orchestrator.py:129`) — i.e. only if the whole per-item invocation completes. A Lambda timeout is NOT a Python exception (per repo MEMORY 'silent Lambda failures'), so a worker that times out mid-vendor-call never reaches `increment_run_counters` and contributes no delta. Likewise a message that exhausts `maxReceiveCount` (3) and lands in the DLQ (`sqs.tf:77-80`) never contributes its delta. There is no sweeper/reconciler anywhere (grep for sweep/reconcile/stuck across enrichment returns nothing). The per-label auto-state row has a 6h stale-queued recovery (`auto_repository.py:144-147`), but that only re-claims the LABEL for a future run — it never reconciles the already-orphaned run row, which stays 'running' forever.
- **Risk:** Any run where even one item's worker invocation times out or DLQs is permanently stuck at `status='running'` with `cells_ok+cells_error < cells_total`. The admin runs list (`repository.py:420-486`) surfaces it as perpetually in-progress; the admin can never tell a run finished. Over time the runs table accumulates phantom 'running' rows. Because Aurora is Serverless v2 (min ACU 0) and vendor calls are slow (300s timeout), worker timeouts at 900s are plausible under vendor latency. Silent, gradual operational corruption of run state with no alarm.
- **Recommendation:** Add a reconciler (scheduled Lambda or query in the admin runs view) that flips runs to 'failed'/'partial' when `status='running' AND finished_at IS NULL AND created_at < NOW() - INTERVAL` (e.g. 2x worker timeout). Alternatively compute terminal status from elapsed time + DLQ depth rather than relying solely on the per-cell counter reaching `cells_total`. At minimum expose a 'stalled' status in `list_runs` so stuck runs are visible.
- **Effort:** M

### [REL-005] P2 — Runs strand permanently at RAW_SAVED on enqueue failure or worker timeout; no reconciler, no in-progress state, alarms unwired by default

- **Where:** `src/collector/handler.py:438-498,957-974` (enqueue failure non-fatal, returns 200 RAW_SAVED); `src/collector/worker_handler.py:24-182`; `src/collector/models.py:24-28` (no IN_PROGRESS); no EventBridge/scheduler in `infra/`; `infra/variables.tf:230-234` (alarm SNS default empty)
- **Evidence:** `_enqueue_canonicalization` catches all exceptions and returns ENQUEUE_FAILED while the API still returns 200 with `run_status=RAW_SAVED` (`handler.py:438-446,957-974`) — the run is created but never queued, and there is no automatic retry of enqueue. RunStatus has only RAW_SAVED→COMPLETED|FAILED (`models.py:24-28`); there is no in-progress state, so a worker timeout (which is not a Python exception, per the silent-Lambda-failures memory) leaves the row at RAW_SAVED. Grep confirms no `aws_cloudwatch_event_rule` / `aws_scheduler` / `schedule_expression` anywhere in `infra/`, so nothing reconciles stuck runs. On repeated worker timeout the SQS message exhausts `maxReceiveCount=5` (`infra/sqs.tf:16`) into the DLQ; the DLQ-depth alarm exists (`logging.tf:58-90`) but `alarm_sns_topic_arn` defaults to `""` (`variables.tf:230-234`), so nothing pages.
- **Risk:** A run can be silently stuck at RAW_SAVED forever (enqueue failed, or worker repeatedly times out into the DLQ) with no operator signal and no recovery path. GET `/runs/{run_id}` reports RAW_SAVED indefinitely, indistinguishable from in-flight.
- **Recommendation:** Treat ENQUEUE_FAILED as a hard error surfaced to the operator (or retry enqueue with backoff before returning). Add a scheduled reconciler that re-enqueues runs sitting at RAW_SAVED past a threshold, and wire `alarm_sns_topic_arn` so DLQ-depth/Lambda-error alarms actually page. Consider an explicit IN_PROGRESS status to distinguish queued-but-running from never-queued.
- **Effort:** M

### [REL-006] P2 — Worker timeout leaves run permanently at RAW_SAVED with partially committed canonical data

- **Where:** `src/collector/canonicalize.py:53-83, 121, 166, 211, 260, 311, 359`; `src/collector/worker_handler.py:107-180`; `src/collector/models.py:24-28`
- **Evidence:** `process_run` commits one transaction per phase and one per 200-track chunk (`canonicalize.py:121/166/211/260/311/359`); there is no whole-message transaction. `set_run_completed` runs only after all phases succeed (`worker_handler.py:112`). A Lambda timeout (900s) is not a Python exception, so the `except` branch and `set_run_failed` (`worker_handler.py:147`) never run, and RunStatus has no in-progress state (`models.py:24-28`). The message returns to the queue after the 900s visibility timeout and retries up to `maxReceiveCount=5` (`infra/sqs.tf:16`), but a run that times out 5x lands in the DLQ while its `ingest_runs` row is still RAW_SAVED with some phases/chunks already committed.
- **Risk:** Runs silently stuck at RAW_SAVED with partial catalogue data and no automatic reconciliation; GET `/runs/{run_id}` reports RAW_SAVED indefinitely, masking a half-applied ingest. Replay is data-safe (idempotent) but only happens if someone manually redrives; otherwise the row never reaches a terminal state.
- **Recommendation:** Add an explicit RUNNING/IN_PROGRESS status set at message start, plus a sweeper or DLQ alarm-driven reconciliation that detects RAW_SAVED rows older than the worker timeout and re-enqueues or flags them. At minimum, alarm on canonicalization DLQ depth (`logging.tf` already creates the alarm but `alarm_sns_topic_arn` defaults empty).
- **Effort:** M

### [REL-007] P2 — Enrichment DLQs have no consumer and alarms default to no SNS topic — failed enrichment is invisible

- **Where:** `infra/sqs.tf:64-123` (label/artist/auto_enrich DLQs, terminal); `infra/logging.tf:69-90` (dlq_depth alarm); `infra/variables.tf:230-234` (`alarm_sns_topic_arn` default `""`)
- **Evidence:** All three enrichment DLQs (`label_enrichment_dlq`, `artist_enrichment_dlq`, `auto_enrich_dispatch_dlq`) have only `message_retention_seconds` and no redrive/consumer — no Lambda event source mapping targets them and no `redrive_allow_policy` exists (grep of `lambda.tf` for DLQ consumers returns nothing). The `dlq_depth` alarm exists for all six DLQs (`logging.tf:59-90`) but its `alarm_actions`/`ok_actions` are `var.alarm_sns_topic_arn != "" ? [...] : []` and `alarm_sns_topic_arn` defaults to `""` (`variables.tf:230-234`), so by default the alarm fires into the void and pages nobody. Combined with REL-004, a label/artist whose message DLQs is lost (4-day retention for enrichment, `sqs.tf:66/87`) with no automatic reprocessing and no notification.
- **Risk:** An enrichment item that fails `maxReceiveCount` times silently lands in a terminal DLQ, expires after 4 days, and is never enriched — and its parent run stays 'running' forever (see REL-004). With the default empty SNS topic nothing alerts an operator. Failures are completely silent in the default deployment.
- **Recommendation:** Wire `alarm_sns_topic_arn` to a real topic in the prod tfvars (the alarms are otherwise dead), and add a documented DLQ redrive runbook step or a redrive consumer for enrichment DLQs so DLQ'd items can be replayed before the retention window expires.
- **Effort:** S

### [REL-008] P2 — All CloudWatch alarms default to no notification target (alarm_sns_topic_arn empty)

- **Where:** `infra/variables.tf:230-234`; consumed at `alarms.tf:47-48,72-73,98-99,119-120` and `logging.tf:88-89`
- **Evidence:** `variable alarm_sns_topic_arn` defaults to `""` (`variables.tf:233`). Every alarm wires `alarm_actions`/`ok_actions = var.alarm_sns_topic_arn != "" ? [...] : []` (e.g. `alarms.tf:47-48` lambda errors, `:72-73` duration p95, `:119-120` Aurora ACU, `logging.tf:88-89` DLQ depth). With the default empty value, all alarms are created but have zero actions — they change state in the console but page/notify nobody.
- **Risk:** DLQ-depth alarms, Lambda error alarms, and the Aurora ACU-near-max alarm fire into the void by default. The MVP can ship with no operator notified of a stuck worker, a DLQ filling up, or runaway DB capacity until someone manually opens the console.
- **Recommendation:** Provide a non-empty `alarm_sns_topic_arn` (an SNS topic with an email/Slack/PagerDuty subscription) as part of the standard prod tfvars, or create the SNS topic in-repo and default the alarms to it. Document it as a required deploy input.
- **Effort:** S

### [REL-009] P2 — Lambda Errors alarm map omits artist_enricher and auto_enrich_dispatch workers

- **Where:** `infra/alarms.tf:14-22` (`worker_lambdas` local) feeding `lambda_errors` `for_each` at `:29-30`
- **Evidence:** `local.worker_lambdas` (`alarms.tf:14-19`) lists only canonicalization, spotify_search, vendor_match, label_enricher. `all_lambdas = merge(api_lambdas, worker_lambdas)` (`alarms.tf:21`), and the `lambda_errors` alarm iterates `for_each = local.all_lambdas` (`alarms.tf:30`). The `artist_enricher_worker` (`lambda.tf:239`) and `auto_enrich_dispatch_worker` (`lambda.tf:288`) Lambdas exist and have log groups (`logging.tf:46-54`) but are absent from the map, so neither gets a Lambda Errors alarm. The artist path is a near-exact mirror of labels with the same crash surfaces (RuntimeError on missing run, repository writes), and `auto_enrich_dispatch` is the single entry point that fans out BOTH label and artist enrichment for an entire triage block (`auto_enrich_dispatch_handler.py:26-27`).
- **Risk:** A repeatedly-failing artist enricher or dispatch worker emits errors that page nobody and trigger no alarm. The dispatch worker is the most impactful: if it crashes, the whole block's auto-enrichment silently never happens, with no Errors alarm to catch it. Failures are only indirectly visible via the DLQ-depth alarm (`logging.tf:69-90`) — and that only fires after `maxReceiveCount` redrives.
- **Recommendation:** Add `artist_enricher_worker` and `auto_enrich_dispatch_worker` to `local.worker_lambdas` (or a dedicated map) so the existing `lambda_errors` alarm covers them, matching the log-group coverage already present in `logging.tf`.
- **Effort:** S

### [REL-010] P2 — Migration step has no rollback — a failed migration leaves new code live against old schema

- **Where:** `.github/workflows/deploy.yml:102-132`
- **Evidence:** The migration step fails the workflow on FunctionError or `status != 'ok'` (`deploy.yml:127-131`) but only AFTER 'Terraform apply' (line 81) already published the new Lambda code. There is no compensating step to revert the Lambda code or terraform state on migration failure; the job simply exits non-zero. The frontend deploy (line 146) is skipped, but the backend code is already swapped.
- **Risk:** Any migration failure (Aurora won't wake within the timeout, lock contention, a bad DDL, IAM token/role issue) leaves production running new code against the prior schema indefinitely until a human intervenes — silent partial outage of whichever subsystem depends on the missing schema.
- **Recommendation:** Run migrations before the code-swapping apply (see REL-003), or add an explicit rollback/alarm path: on migration failure, re-apply the previous Lambda artifact or fail closed before the apply that changes runtime code. Page on the failure (`alarm_sns_topic_arn` currently defaults empty).
- **Effort:** M

### [REL-011] P2 — Whole `alembic upgrade head` runs as a single transaction with an in-line full-table backfill — Lambda timeout rolls back the entire multi-revision batch

- **Where:** `alembic/env.py:55-56`; `src/collector/migration_handler.py:53`; `alembic/versions/20260531_30_track_key.py:34-51`; `infra/variables.tf` migration_lambda_timeout (900s)
- **Evidence:** `transaction_per_migration` is unset (not in `alembic.ini` or `env.py`), so it defaults to False; `env.py:55` wraps `context.run_migrations()` in one `context.begin_transaction()`. `command.upgrade(config, 'head')` (`migration_handler.py:53`) thus executes ALL pending revisions in a single Postgres transaction. Migration 30 contains a synchronous `UPDATE clouder_tracks ... FROM source_entities JOIN identity_map ...` (`track_key.py:34-51`) that rewrites every track row, joined against the full `source_entities` JSONB payload table — unbounded, no batching. Migrations also build many non-CONCURRENT indexes (grep confirms zero CONCURRENTLY usage), each taking ACCESS EXCLUSIVE locks. The migration Lambda timeout is 900s and Aurora runs `min_acu=0` (cold start). The handler has no try/except around `command.upgrade` (`migration_handler.py:53`).
- **Risk:** On a populated catalogue, a cold-started, single-vCPU (ACU) Aurora doing a full-table JSONB-join UPDATE plus several index builds inside one transaction can exceed the 900s Lambda timeout. The transaction rolls back (no partial-DDL corruption — that part is safe), but `alembic_version` never advances, so the deploy appears to 'fail' and every retry re-runs the whole backfill from scratch, each attempt re-paying cold start and re-locking tables. There is no concurrency guard, so a second invocation (or an auto-retry) can collide on the same locks.
- **Recommendation:** Batch the migration-30 backfill (LIMIT/loop by id range) or move it to a post-migration data job rather than an in-line DDL-transaction UPDATE. Consider setting `transaction_per_migration=True` so each revision commits independently (so a long backfill isn't re-run after a partial-batch timeout), accepting that a failed revision then needs manual `alembic_version` reconciliation. Raise migration Lambda timeout headroom and/or floor Aurora ACU during migration windows.
- **Effort:** M

### [REL-012] P2 — Migration Lambda connects to Aurora with no connect/lock/statement timeout and no resume retry on cold cluster

- **Where:** `src/collector/migration_handler.py:53,80-115`; `alembic/env.py:37-56` (NullPool, no connect_args)
- **Evidence:** `migration_handler` builds a psycopg URL with only `?sslmode=require` (`migration_handler.py:98,114`) and calls `command.upgrade` (line 53) with no `connect_timeout`, `lock_timeout`, or `statement_timeout`. `alembic/env.py:41-45` uses `engine_from_config` with NullPool and no `connect_args`. The whole upgrade runs in one transaction (`env.py:55` `begin_transaction`). The Data API resume-retry (`data_api_retry.py` DatabaseResumingException) does NOT cover this psycopg TCP path. With `min_acu=0` / 300s auto-pause (`rds.tf`), the migration Lambda's first TCP connect must wake a paused cluster; there is no application-level retry around the connect, and a long backfill (e.g. the full-table UPDATE in `20260531_30_track_key.py:34-51`) plus cold-start can approach the 900s Lambda timeout.
- **Risk:** On a cold/paused Aurora the connect may hit libpq's default timeout or the resume may be slow, failing the migration step nondeterministically; a long DDL+backfill holding ACCESS EXCLUSIVE locks with no `lock_timeout` can block runtime writers indefinitely or be killed only by the Lambda's 900s hard timeout (a timeout is not a Python exception, so the failure is opaque).
- **Recommendation:** Add `connect_timeout` and a `SET lock_timeout`/`statement_timeout` via `connect_args`/`options` in `env.py`; add a small retry loop around the initial connect to absorb the Aurora resume; consider a pre-warm Data API ping before invoking the migration Lambda in `deploy.yml`.
- **Effort:** S

### [REL-013] P2 — Refresh handler mutates vendor token and session non-atomically (no transaction)

- **Where:** `src/collector/auth_handler.py:444-468`; `src/collector/auth/auth_repository.py:256-287,202-213`
- **Evidence:** `_handle_refresh` performs three separate Data API auto-commit statements with no enclosing transaction (grep shows no `transaction()`/`begin_transaction` in `auth_handler.py` or `auth_repository.py`): `upsert_vendor_token` writes the new Spotify access+refresh tokens (`auth_handler.py:444-455`), then `issue_refresh_token` mints a new CLOUDER refresh JWT (`auth_handler.py:457-463`), then `rotate_session` updates the session hash to the new JWT's hash (`auth_handler.py:464-468`). If `rotate_session` fails after the vendor-token upsert commits, the persisted Spotify refresh token has advanced but the session still holds the OLD CLOUDER hash; the client receives an error. A subsequent retry with the old cookie still matches the old hash and re-runs, decrypting the just-persisted new Spotify refresh token — recoverable, but if Spotify already invalidated the prior refresh token mid-flight, state can drift. There is no compensating action and no atomicity across the Spotify-side and CLOUDER-side rotations.
- **Risk:** Partial failure between the vendor-token write and session rotation can leave the user's stored Spotify refresh token and CLOUDER session out of sync, occasionally requiring a full re-login. Low frequency (depends on a mid-call Data API failure) but silent when it happens.
- **Recommendation:** Wrap the vendor-token upsert and `rotate_session` in a single `DataAPIClient.transaction()`, threading `transaction_id` into both repo calls. The Spotify HTTP refresh cannot be in the DB transaction, but the two DB writes that depend on it should commit atomically.
- **Effort:** M

### [REL-014] P2 — Spotify publish leaves an orphaned, duplicated playlist when a track-write call fails mid-loop

- **Where:** `src/collector/curation/playlists_publish_service.py:110-146`
- **Evidence:** `publish()` creates/overwrites the Spotify playlist (`create_playlist` line 111 or `update_playlist` line 95), then writes tracks via `replace_tracks(uris[:100])` (line 122) followed by a loop of `append_tracks` for each subsequent 100-URI chunk (lines 123-124). Only AFTER the full loop does it call `self._repo.set_publish_state(...)` (line 142) to persist `spotify_playlist_id` locally. `SpotifyUserClient.append_tracks`/`_request` raise `SpotifyRateLimitedError`/`SpotifyApiError` on persistent 429 or 5xx (`spotify_user_client.py:197-216`) with only 1 retry each. If `replace_tracks` succeeds but a later `append_tracks` raises, the exception propagates out of `publish()`, the handler returns 500, and `set_publish_state` never runs.
- **Risk:** For a first-time publish, the Spotify playlist is created and partially filled but `spotify_playlist_id` is never saved to CLOUDER. A user retry re-enters the `create_playlist` branch (`target_id` is still None) and creates a SECOND Spotify playlist, orphaning the first. Repeated failures multiply orphaned playlists in the user's Spotify account. Multi-track playlists (>100 tracks) are the exposed case.
- **Recommendation:** Persist the created `spotify_playlist_id` immediately after `create_playlist`/`update_playlist` succeeds (before the track-write loop) so a retry reuses the same target via the update path, or wrap `publish` in a try/finally that records `target_id` on partial failure. Treat track-write failures as 'published-but-incomplete' (mark `needs_republish`) rather than discarding the playlist id.
- **Effort:** M

### [REL-015] P2 — YouTube Music publish orphans a partially-filled playlist on add_items failure or 30s Lambda timeout

- **Where:** `src/collector/curation/ytmusic_publish_service.py:115-155` and `src/collector/curation/youtube_data_api_client.py:90-102`
- **Evidence:** `publish()` calls `create_playlist` (line 116) then `add_items(target_id, video_ids)` (line 119); `add_items` issues one `playlistItems.insert` POST per video (`youtube_data_api_client.py:90-102`, 'Data API v3 has no bulk insert'). `set_ytmusic_publish_state` (line 152) is only reached after the entire add loop completes. `_request` raises `YtmusicApiError` on any non-2xx incl. 403 quota-exceeded (`youtube_data_api_client.py:163-165`). A failure (or Lambda timeout) partway through the per-video loop means the YouTube playlist exists with some items but `ytmusic_playlist_id` is never stored locally. The curation Lambda timeout is 30s (`infra/variables.tf:419-422`); 100 sequential inserts can approach that window, and a Lambda timeout is not a Python exception so no cleanup runs.
- **Risk:** Retry re-enters the create branch (line 115, `target_id` still None) and creates a duplicate YouTube playlist, leaving the orphaned partial behind. Worse than the Spotify case because each insert is its own API call (50 quota units) and YouTube's default 10k/day quota means a few large republishes can also exhaust quota mid-loop, guaranteeing the orphan.
- **Recommendation:** Persist `ytmusic_playlist_id` immediately after `create_playlist` returns, before adding items, so retries resume on the same playlist via the incremental-diff path (which is already idempotent). Mark `needs_republish` on partial add failure rather than dropping the id.
- **Effort:** M

### [REL-016] P2 — navigate('/auth/premium-required') targets an unregistered route — Spotify account_error dead-ends on the 404 page

- **Where:** `frontend/src/features/playback/PlaybackProvider.tsx:316-319`; `frontend/src/routes/router.tsx:41-136`
- **Evidence:** On the Spotify Web Playback SDK `account_error` event the provider runs `navigate('/auth/premium-required')` (`PlaybackProvider.tsx:318`). No route with path `/auth/premium-required` is declared in `router.tsx` — the only premium handling is `/login?error=premium_required` (`login.tsx:11-12`) and inline copy in `auth.return.tsx:63-67`. The catch-all `*` route (`router.tsx:135`) renders NotFoundPage, so this navigation lands on the generic 404 instead of a 'Premium required' explanation.
- **Risk:** A non-Premium (or downgraded) Spotify user who triggers playback gets dumped on a meaningless 'Not Found' page with no guidance, instead of the premium-required message. The error is the SDK `account_error`, so it surfaces exactly when the user most needs the explanation.
- **Recommendation:** Either register a `/auth/premium-required` route that renders the premium-required copy, or change the navigation to the existing surface: `navigate('/login?error=premium_required')` (or render the LongOperationOverlay/banner inline). Add a test asserting `account_error` lands on a page that shows `auth.premium_required`.
- **Effort:** S

### [REL-017] P2 — Production deploy runs no tests/lint/plan gate and is path-filter-blind

- **Where:** `.github/workflows/deploy.yml:15-148` (no test step); `.github/workflows/pr.yml:12-39,81-127`
- **Evidence:** `deploy.yml` has no pytest, no `pnpm test`/typecheck/lint, and no `terraform plan` step — it goes straight to `terraform apply -auto-approve` and `aws lambda invoke` migrations. It relies entirely on PR checks. But `pr.yml` jobs are path-filtered (`pr.yml:21-39`): a frontend-only PR runs only `frontend`, skipping `terraform`/`tests`/`alembic-check`. Merging that PR triggers `deploy.yml` which ALWAYS runs full `terraform apply` + migration invoke against prod — infra/backend the PR never validated with `terraform plan` or pytest.
- **Risk:** Drift between main and the last-validated infra plan is applied to production unreviewed. A bad terraform change merged via a path that skipped the `terraform` job (or an out-of-band edit to main) is auto-applied with no plan diff visible and no rollback.
- **Recommendation:** Add a `terraform plan` + test gate inside `deploy.yml` before apply (fail-closed), or require the full PR matrix to pass regardless of path filter for merges to main. Consider a manual-approval environment gate before apply.
- **Effort:** M

### [REL-018] P2 — deploy.yml lacks a concurrency block — concurrent main pushes race terraform apply + migration + frontend

- **Where:** `.github/workflows/deploy.yml:1-17` (no `concurrency:` key)
- **Evidence:** Neither `deploy.yml` nor `pr.yml` declares a `concurrency:` group (grep returns nothing). Two pushes to main within a short window start two `deploy` jobs in parallel. The DynamoDB state lock (init at `deploy.yml:44-51`) serializes `terraform apply`, but the `aws lambda invoke` migration step (102-132), SSM secret sync (53-79), and `scripts/deploy_frontend.sh` S3 sync + CloudFront invalidation (146-148) are not lock-protected.
- **Risk:** Interleaved deploys can apply older code/migration after newer (lost-update on Lambda version, frontend S3 `--delete` sync from a stale build clobbering the newer one, or migration of an older revision running last). With `-auto-approve` and no rollback, recovery is manual.
- **Recommendation:** Add `concurrency: { group: deploy-production, cancel-in-progress: false }` to `deploy.yml` so deploys queue and run strictly serially.
- **Effort:** S

### [REL-019] P3 — begin_transaction retries on post-execution error codes and can orphan a server-side transaction

- **Where:** `src/collector/data_api.py:74-81` (`begin_transaction @retry_data_api()`); `src/collector/data_api_retry.py:17-25`
- **Evidence:** `begin_transaction` is decorated with the broad `retry_data_api()`, whose TRANSIENT_ERROR_CODES includes `StatementTimeoutException` and `InternalServerErrorException`. If the RDS Data API creates the transaction server-side but the response is lost (InternalServerError / timeout after creation), the wrapper retries and calls `begin_transaction` again, obtaining a SECOND `transactionId`. The first transaction is never committed or rolled back by this code (the lost `transactionId` is unknown to the caller), so it lingers until the Data API idle-transaction timeout.
- **Risk:** Orphaned transactions hold locks and consume a Data API transaction slot until they time out (Data API auto-rolls-back idle transactions after several minutes). Under a resume/throttle storm this can briefly block conflicting writes and inflate Aurora wake time/cost. Bounded and rare, but a correctness wrinkle in the retry design.
- **Recommendation:** Decorate `begin_transaction` with `retry_data_api_pre_execution()` (DatabaseResumingException/ServiceUnavailableError/ThrottlingException only) like commit/rollback, since a transaction that may already exist server-side must not be blindly re-created. Post-execution codes here are not safe to retry.
- **Effort:** S

### [REL-020] P3 — log_event silently drops diagnostic fields not in ALLOWED_LOG_FIELDS; enrichment failure paths log no structured context

- **Where:** `src/collector/logging_utils.py:14-100` (ALLOWED_LOG_FIELDS) + `:136-141` (`_sanitize_fields` drops unknown keys); `label_enrichment_handler.py:96-98,128-134`; `artist_enrichment_handler.py:84-86,115-121`; `auto_enrich_dispatch.py:138-142`
- **Evidence:** `_sanitize_fields` only keeps keys present in ALLOWED_LOG_FIELDS and silently discards the rest (`logging_utils.py:138-140`). `label_enrichment_handler` logs `label_enrichment_completed` with `label_name` (`handler.py:133`) and `artist_enrichment_handler` logs `artist_name` (`handler.py:120`), but neither `label_name` nor `artist_name` is in ALLOWED_LOG_FIELDS (grep count 0) — those fields vanish from the emitted log. More importantly, the 'run not found' branch raises a bare RuntimeError with NO `log_event` at all (`label_enrichment_handler.py:96-98`, `artist_enrichment_handler.py:84-86`): the message goes to the DLQ carrying only a generic stack trace, with no structured `run_id`/`label_id` to diagnose which run/item failed (even though `run_id` and `label_id` ARE in the allow-list and could have been logged).
- **Risk:** When an enrichment worker fails or DLQs, the structured logs that survive the allow-list filter omit the human-meaningful identifiers (label/artist name), and the run-not-found failure path emits no structured diagnostic at all. Operators debugging a stuck/failed run must reverse-engineer it from raw exception traces, slowing incident response for exactly the silent-failure scenarios above.
- **Recommendation:** Add a `log_event('ERROR', 'enrichment_run_not_found', run_id=..., label_id=...)` (or `artist_id`) before raising in both handlers. Either add `label_name`/`artist_name` to ALLOWED_LOG_FIELDS or stop passing them so the drop isn't misleading. Consider failing loudly in tests when a passed log field is not allow-listed.
- **Effort:** S

### [REL-021] P3 — Spotify result persistence writes four independent un-transacted batches per chunk

- **Where:** `src/collector/spotify_handler.py:252-254,326-343,346-350`; `src/collector/repositories.py:802-832`
- **Evidence:** `_process_results_chunk` persists each chunk as four separate calls with no `transaction_id`: `batch_upsert_source_entities` (326), `batch_upsert_identities` (329), `batch_update_spotify_results` (343), `propagate_release_type_to_albums` (350). Each auto-commits independently. `batch_update_spotify_results` sets `spotify_searched_at` (`repositories.py:802-832`), and `find_tracks_needing_spotify_search` filters `WHERE spotify_searched_at IS NULL` (`repositories.py:747-748`). If the worker times out/crashes between the identity write and the `searched_at` write, the chunk simply reruns (idempotent). All four are UPSERT/UPDATE so a broad-retry replay is safe — but there is no atomic boundary tying the `spotify_id`/`identity_map` row to the `searched_at` flag.
- **Risk:** A crash partway through a chunk can leave `clouder_tracks.spotify_id` / `identity_map` inconsistent with `spotify_searched_at` across runs; because each write auto-commits, there is no single point that guarantees the searched flag and the match row land together. Low blast radius (idempotent reprocessing self-heals on the next batch), but the invariant is enforced only by ordering, not transactionally.
- **Recommendation:** Wrap the per-chunk writes in a single `with repository.transaction()` block (the methods already accept `transaction_id`), so `source_entities` + `identity_map` + `tracks.spotify_searched_at` commit atomically per chunk.
- **Effort:** S

### [REL-022] P3 — import-spotify and publish run a synchronous per-item vendor-call loop inside the 30s curation Lambda timeout

- **Where:** `src/collector/curation_handler.py:1092-1127` (import) and `1178-1214` (publish) with `infra/variables.tf:419-422`
- **Evidence:** `_handle_import_spotify` loops `sp_client.get_track(sid)` once per submitted ref (lines 1092-1094); `ImportSpotifyTracksIn` caps refs at 50 (`curation/schemas.py:135`) and each `get_track` may sleep+retry on 429/5xx (`spotify_user_client.py:197-211`). `_handle_publish`/`_handle_publish_ytmusic` run the multi-call publish services synchronously. The curation Lambda timeout is 30s (`infra/variables.tf:419-422`). A Lambda timeout is not a Python exception, so partial work (imported `clouder_tracks` rows, partially-populated external playlist) commits with the client receiving a gateway 5xx and no record of what succeeded.
- **Risk:** On a slow vendor or large playlist, the request can time out mid-loop. Import is idempotent on retry (`upsert_imported_track`), so import is mostly safe, but publish timeouts compound the orphan-playlist findings (REL-014, REL-015) and the client gets no actionable partial-result envelope.
- **Recommendation:** For publish, persist the external playlist id before the per-track loop (see REL-014/REL-015). For import, consider chunking/returning a partial result, or move large publishes to an async worker to escape the 30s synchronous window.
- **Effort:** M

### [REL-023] P3 — move_tracks reports inflated 'moved' count when tracks already exist in the target bucket

- **Where:** `src/collector/curation/triage_repository.py:483-494`
- **Evidence:** `move_tracks` deletes the requested ids from the source bucket then INSERTs them into the target with `ON CONFLICT (triage_bucket_id, track_id) DO NOTHING` (lines 483-492), but returns `MoveResult(moved=len(track_id_list))` (line 494) — the full requested count, not RETURNING-counted inserted rows. If a track already exists in the target bucket, the insert is a no-op but it is still counted as moved. Contrast `transfer_tracks` which uses RETURNING `track_id` and counts actual inserts (`triage_repository.py:590-600`).
- **Risk:** The handler returns and logs an overstated moved count (`curation_handler.py:1467`); the frontend optimistic decrement of source `track_count` can drift from the true server state when destination duplicates exist. Cosmetic/correctness drift, not data loss (the move itself is transactional and correct).
- **Recommendation:** Add RETURNING `track_id` to the INSERT and report `moved` = number of rows actually inserted (matching `transfer_tracks`), or document that 'moved' counts requested tracks regardless of target-side duplicates.
- **Effort:** S

---

Note on scope: the source findings list contained two near-duplicate pairs that I merged for the report — the deploy code-before-migration hazard appears twice (subsystems `migrations` and `ci`), consolidated into REL-003; and the artist/dispatch Errors-alarm gap appears twice (subsystems `enrichment` and `infra`), consolidated into REL-009. If you need them kept as separate line items per subsystem, say so and I will split them back out.

## Tests & CI

The unit suite is broad and the canonicalization, storage, and publish-service modules are reasonably well covered at the unit level, but the test strategy has a structural blind spot: nothing exercises SQL against a real Postgres or the RDS Data API, so the entire runtime data path is validated only as string content against fakes. CI gating is also incomplete in two consequential ways — the deploy pipeline runs no tests at all before applying terraform and migrating the production database, and the OpenAPI contract has no freshness gate, so backend/frontend contract drift can merge green. Several of the highest-leverage paths (admin-route gating completeness, retry-decorator wiring, publish partial-failure, concurrent auth refresh) are exactly the ones with no regression guard, which means the bugs flagged elsewhere in this review can be reintroduced with the suite still passing. Overall health: moderate, with the CI gaps (TEST-001, TEST-002) and the real-DB gap (TEST-003) being the items most worth fixing first.

### [TEST-001] P2 — Deploy workflow runs no tests; push to main goes straight to terraform apply + DB migration
- **Where:** `.github/workflows/deploy.yml:15-148`
- **Evidence:** `deploy.yml` triggers on `push: branches: [main]` (verified: lines 3-6) and its single `deploy` job runs Package Lambda → Terraform apply (lines 81-100) → `aws lambda invoke` migration (lines 102-132) → frontend deploy (lines 146-148). There is no pytest, typecheck, lint, build, or terraform-plan step (confirmed: grep for `pytest|pnpm test|pnpm lint|pnpm typecheck|terraform plan` in `deploy.yml` returns nothing). All test gating lives in `pr.yml`, which runs only on `pull_request` (`pr.yml:3-6`). Any commit reaching main without a passing PR — direct push, admin merge bypassing required checks, or a hotfix — deploys completely untested.
- **Risk:** A change that reaches main without passing PR checks applies terraform and runs the Alembic migration Lambda against production Aurora with zero test verification. A bad migration is a data-integrity event on the single shared multi-tenant DB.
- **Recommendation:** Make deploy depend on the test suite — either gate deploy on the PR-check status via branch protection requiring `pr.yml` jobs, or add a `pytest -q` + `terraform plan` precondition job to `deploy.yml` that must pass before `terraform apply`. At minimum, enforce that main is PR-only and the `tests` job is a required status check.
- **Effort:** S

### [TEST-002] P2 — openapi.yaml freshness is never gated; CI diffs schema.d.ts against a possibly-stale committed openapi.yaml
- **Where:** `.github/workflows/pr.yml:169-176`
- **Evidence:** The frontend job runs `pnpm api:types` (= `openapi-typescript ../docs/api/openapi.yaml -o src/api/schema.d.ts`, `frontend/package.json:22`) then fails if `src/api/schema.d.ts` drifts (`pr.yml:170-176`). But nothing regenerates `docs/api/openapi.yaml` itself from its source of truth `scripts/generate_openapi.py` and diffs it (confirmed: grep for `generate_openapi` across `.github/workflows/` returns no match). CLAUDE.md gotcha #8 states openapi.yaml is generated and must be regenerated after editing routes in `infra/*.tf` or `generate_openapi.py:ROUTES`. If a dev adds a route but forgets to regenerate openapi.yaml, the committed (stale) openapi.yaml and committed (stale-derived) schema.d.ts still agree, so the diff check passes — the frontend ships typed against a contract missing the new route.
- **Risk:** Backend route additions/changes can merge with an out-of-date OpenAPI contract; the frontend's generated types silently lag the real API surface, producing untyped/incorrect client calls that typecheck green. Drift compounds because the only consistency check compares two artifacts both derived from the same stale file.
- **Recommendation:** Add a CI step (backend job) that runs `PYTHONPATH=src python scripts/generate_openapi.py` to a temp file and `git diff --exit-code docs/api/openapi.yaml`, failing if the committed openapi.yaml is not freshly generated. Trigger on changes to `infra/**`, `scripts/generate_openapi.py`, or `src/**`.
- **Effort:** S

### [TEST-003] P2 — No real-Postgres / RDS Data API fidelity test; all repo SQL is validated only as string content against fakes
- **Where:** `tests/integration/test_triage_handler.py:1-27`
- **Evidence:** Every integration test uses an in-memory FakeRepo (`tests/integration/test_curation_handler.py:26`, `test_handler.py:11-30` FakeS3/FakeSQS) and every repository unit test drives a captured-SQL fake DataAPIClient asserting only string fragments (e.g. `test_triage_repository.py:249-261` asserts `'INSERT INTO triage_bucket_tracks' in sql`). No moto, no psycopg, no conftest fixture spins up Postgres for handler/repository tests (confirmed: no `moto` reference anywhere under `tests/`; only the alembic-check CI job uses a real postgres service, and that only runs `alembic upgrade head` twice, `pr.yml:73-79`). `test_triage_handler.py:1-27` documents this explicitly: "We do not have a psycopg-backed Aurora fixture in this repo... A future task (T28 - real-DB integration tests) could add psycopg-backed end-to-end verification." So the dynamic IN-list/WHERE SQL, ON CONFLICT upsert semantics, and `DataAPIClient._to_field` type coercion (datetime tz-stripping `data_api.py:152-156`, Decimal→stringValue, dict/list→JSON) are never executed against a real engine.
- **Risk:** A SQL syntax error, a wrong ON CONFLICT target, a column-type mismatch, or a Data-API parameter-coercion bug passes the entire suite because no test runs the SQL through Postgres or the Data API. First detection is production — the one DB path the system can never psycopg-bypass.
- **Recommendation:** Add a real-Postgres integration tier (the already-scoped T28 task): run the alembic schema into the `pr.yml` postgres service and execute representative repository writes/reads (canonicalize upserts, a triage move, a dynamic-WHERE list query) end to end. Even a thin psycopg-backed adapter mirroring `DataAPIClient`'s parameter coercion would catch the most likely bug class.
- **Effort:** L

### [TEST-004] P2 — Admin-route gating completeness has no regression test; _ADMIN_ROUTES coverage of /admin/* is unguarded
- **Where:** `tests/unit/test_handler_admin_gating.py:42-105`
- **Evidence:** `test_handler_admin_gating.py` verifies a few individual routes: `/collect_bp_releases` returns 403 without admin (lines 42-59), `/tracks/spotify-not-found` requires admin (lines 62-76), and a non-admin list route stays 200 (lines 79-105). No test asserts that the `_ADMIN_ROUTES` frozenset (`handler.py:60-86`) covers every `/admin/*` route registered in the API Gateway integrations. The system map flags exactly this footgun: a new `/admin/*` gateway route omitted from that frozenset is reachable by any authenticated (non-admin) user, because the JWT authorizer admits any valid token regardless of `is_admin` and admin enforcement is application-level only. There is no cross-check test comparing the gateway route table to `_ADMIN_ROUTES`.
- **Risk:** Adding an `/admin/*` route to `infra/api_gateway.tf` and the handler dispatch but forgetting to add it to `_ADMIN_ROUTES` makes an admin-only operation reachable by any authenticated tenant user, and no test catches the omission — a silent privilege-escalation regression on a multi-tenant SaaS.
- **Recommendation:** Add a unit test that enumerates the handler's admin-intended routes (or parses the gateway route definitions) and asserts each is present in `_ADMIN_ROUTES`, plus a parametrized test that every admin route returns 403 for `is_admin=False`. Fail CI when a new admin route is added without admin gating.
- **Effort:** M

### [TEST-005] P3 — Frontend quality gates (typecheck/lint/test/build) skip entirely on backend-only PRs
- **Where:** `.github/workflows/pr.yml:151-181`
- **Evidence:** The `frontend` job is `if: needs.changes.outputs.frontend == 'true'` (`pr.yml:152-153`), and the `frontend` paths-filter only matches `frontend/**`, `docs/api/openapi.yaml`, and `.github/workflows/pr.yml` (`pr.yml:25-28`). A backend PR that regenerates `docs/api/openapi.yaml` triggers the frontend job via the openapi path — good — but a backend change that alters the API contract without touching `docs/api/openapi.yaml` (the exact staleness case in TEST-002) never runs `pnpm typecheck`/`api:types`, so the schema-drift gate is bypassed. Browser tests (`pnpm test:browser`) are also excluded from CI entirely (confirmed: no `browser` reference in workflows), so visual/CSS/focus regressions are never gated — documented as intentional in CLAUDE.md #11, but it means jsdom-green is the only automated signal.
- **Risk:** Backend contract changes that should ripple into the typed frontend client are not validated on backend-only PRs unless openapi.yaml is also touched; combined with the missing openapi-freshness gate, frontend/backend contract drift can land green. Visual regressions are never machine-checked.
- **Recommendation:** Couple the frontend schema-freshness check to backend changes — add `src/**` and `scripts/generate_openapi.py` to the frontend paths-filter (or run the openapi-regeneration+diff in the backend job). Consider a lightweight headless-browser job in CI to gate the most critical visual flows.
- **Effort:** S

### [TEST-006] P3 — No coverage for Beatport 300-page cap, per-page timeout/retry exhaustion, or missing-run-row worker path
- **Where:** `tests/unit/test_beatport_client.py` (no 300/max_pages/timeout cases); `tests/integration/test_handler.py:108,163,260`
- **Evidence:** grep over `test_beatport_client.py` and `test_providers_beatport.py` finds no assertion for `max_pages=300` (the `UpstreamUnavailableError` "pagination exceeded safety limit" branch at `beatport_client.py:84`), nor for TimeoutError/URLError retry exhaustion (`beatport_client.py:143-149`), nor for the 401/403→UpstreamAuthError short-circuit at the client level. The 300-page loop — the only structural guard against runaway Beatport call volume — is untested. On the handler side, the integration happy-path and rerun tests run with `create_clouder_repository_from_env→None` (`test_handler.py:108,163`); the create_ingest_run-skipped-but-enqueued path is exercised but its downstream worker effect (FK failure / no-op status update) is not tested anywhere. Storage failure paths themselves are well covered (`tests/unit/test_storage.py:72-136`).
- **Risk:** Regressions in the page cap, per-page timeout handling, or the auth-error short-circuit — the mechanisms bounding Beatport cost and latency inside the request budget — would ship undetected. The cost/latency-critical paths are the least tested.
- **Recommendation:** Add unit tests: (1) next-link loop hitting max_pages raises `UpstreamUnavailableError`; (2) repeated TimeoutError/URLError across max_retries+1 raises `UpstreamUnavailableError` after exactly max_retries sleeps; (3) 401/403 raises `UpstreamAuthError` without retry. Add an integration test asserting the API returns an error (not 200) when the repository is unconfigured, or a worker test for the missing-run-row FK path.
- **Effort:** M

### [TEST-007] P3 — conservative_update_track overwrite-on-difference semantics are untested
- **Where:** `src/collector/repositories.py:654-671`; `tests/unit/test_canonicalize.py:213-236`
- **Evidence:** The only test touching the update path (`test_canonicalizer_reuses_existing_identity_and_updates_track`, `test_canonicalize.py:213`) uses a FakeRepo that records `updated_tracks==['track-1']` but never executes the COALESCE-vs-CASE SQL. No test asserts the riskiest distinction in the subsystem: that isrc/bpm/length_ms overwrite on difference while mix_name/key/dates only fill nulls. No repository-level test exercises `conservative_update_track` against real SQL semantics.
- **Risk:** A regression that flips a COALESCE to an overwrite (or vice versa) — directly governing the related DATA finding — would pass the entire unit suite undetected.
- **Recommendation:** Add a focused test that asserts the field-by-field merge: existing non-null isrc/bpm/length_ms get overwritten when the new value differs, are preserved when the new value is null, and COALESCE fields never overwrite a non-null existing value.
- **Effort:** S

### [TEST-008] P3 — saturday_week trans-year boundary cases not exercised despite correct logic
- **Where:** `src/collector/saturday_week.py:46-57`; `tests/unit/test_saturday_week.py:1-67`
- **Evidence:** Exhaustive verification (years 2018-2040) confirms `first_saturday`/`weeks_in_year`/`saturday_week_range`/`week_of_date` are correct and round-trip-continuous across all Jan-1-weekday cases (Sat=53-week years 2022/2028/2033/2039, Sun-start years mapping Jan 1 back to prev year's week 53, etc.) with zero gaps. But the suite covers only 2026/2027/2028 plus a single prev-year case (`test_saturday_week.py:57-59`); the 53-week year and the Sunday-Jan-1 "belongs to previous year week 53" branch (`week_of_date` saturday < fs path, `saturday_week.py:50-55`) are only partially exercised.
- **Risk:** Low — logic is verified correct here, but the previous-year-attribution branch and 53-week-year math have no regression guard, so a future off-by-one in that branch could ship silently.
- **Recommendation:** Add parametrized tests for a Sunday-Jan-1 year (e.g. 2023→Jan 1 maps to (2022,53)) and a 53-week year (2028) full round-trip, plus the `week_of_date` previous-year branch explicitly.
- **Effort:** S

### [TEST-009] P3 — No test covers the publish partial-failure / orphan-playlist path for Spotify or YouTube Music
- **Where:** `tests/unit/test_playlists_publish_service.py:62-230`; `tests/unit/test_ytmusic_publish_service.py:108-266`
- **Evidence:** Both publish-service suites cover first-publish, republish, orphan-on-edit-404, cover failure, and nothing-to-publish, but neither has a test where `create_playlist` succeeds and a subsequent track-write (`append_tracks` / `add_items`) raises. There is no assertion that the playlist id is or is not persisted on partial track-write failure, so the orphan/duplicate behavior in the related findings is unguarded by tests.
- **Risk:** The most damaging publish failure mode (orphaned/duplicated external playlists) can regress or be "fixed" incorrectly with no test catching it. The coverage gap masks a real reliability bug.
- **Recommendation:** Add tests that make the second track-write call raise (e.g. `SpotifyRateLimitedError` / `YtmusicApiError`) and assert the desired persistence behavior (id saved, `needs_republish` set) so retries don't create duplicates.
- **Effort:** S

### [TEST-010] P3 — Tavily adapter test masks the two-call (general + social-domain) behavior with a single mocked response
- **Where:** `tests/unit/test_label_enrichment_vendor_tavily.py:21-54` vs adapter `src/collector/label_enrichment/vendors/tavily_deepseek.py:99-161`
- **Evidence:** `test_tavily_deepseek_happy_path` sets `http.post.return_value = tavily_resp` (one response) but the adapter calls `self._http.post` TWICE — the general search (lines 100-113) and the social-domain second pass with `include_domains=SOCIAL_DOMAINS` (lines 132-146). With `return_value`, both calls return the SAME object, so the `seen_urls` dedup (lines 153-161) merely collapses identical results and the test still passes. The test never asserts call count, never asserts the `include_domains` payload, and never exercises the real merge of two distinct result sets. The failure test (lines 57-71) covers only the first-post exception. So the documented "3 upstream calls per cell / social second pass" behavior is effectively untested.
- **Risk:** Regressions in the social-domain pass (wrong domains, dropped second call, broken dedup, double-counting citations/cost) would not be caught — provider mocking fidelity does not match the real two-stage call shape that drives both result quality and per-cell spend.
- **Recommendation:** Use `http.post.side_effect=[general_resp, social_resp]` with distinct URLs, assert `http.post.call_count==2`, assert the second call carries `include_domains=SOCIAL_DOMAINS`, and assert merged/deduped citations from both sets.
- **Effort:** S

### [TEST-011] P3 — Retry path is unit-tested only on the bare decorator, never wired through DataAPIClient or the canonicalizer N+1 path
- **Where:** `tests/unit/test_data_api_retry.py`; `tests/unit/test_data_api.py:254-277`; `src/collector/data_api.py:27-97`
- **Evidence:** `test_data_api_retry.py` exercises the decorator in isolation with synthetic ClientErrors, and `test_data_api.py` covers transaction commit/rollback with a fake client — but no test asserts that `DataAPIClient.execute`/`batch_execute`/`begin_transaction` actually retry on a `DatabaseResumingException` end to end (the decorators are applied at `data_api.py:27,51,74,83,91` but never triggered through a real method call in tests). There is also no test for the canonicalizer's per-entity resolve path under a mid-loop transient failure (e.g. `find_identity` raising), nor for the broad-retry-replays-a-whole-batch idempotency claim documented at `data_api_retry.py:43-56`.
- **Risk:** The decorator-to-method wiring (which decorator guards which method, and that pre-execution vs broad sets are applied to the right calls) is not regression-protected; a refactor could swap `retry_data_api_pre_execution` for `retry_data_api` on commit/rollback — re-introducing the double-apply hazard the split was designed to prevent — with all tests still green.
- **Recommendation:** Add tests that call `DataAPIClient.execute`/`commit_transaction` with a stub rds-data client raising `ClientError('DatabaseResumingException')` / `('StatementTimeoutException')` and assert retry-vs-no-retry per method, plus a canonicalizer test where `find_identity` fails mid-chunk to lock in the transaction-rollback + classification behavior.
- **Effort:** S

### [TEST-012] P3 — No test covers the concurrent-refresh / replay-revoke-all-sessions path
- **Where:** `frontend/src/auth/__tests__/AuthProvider.test.tsx:23-219`; `frontend/src/api/__tests__/client.test.ts`
- **Evidence:** `AuthProvider.test.tsx` contains only happy-path single-refresh transitions (loading→authenticated, refresh-fail→unauthenticated, signOut, `auth:expired`/`auth:refreshed` handling, spotify token roll). Grep for `inflight|concurrent|replay|race` in `AuthProvider.test.tsx` returns nothing. No test asserts that `AuthProvider.refresh()` and `client.tryRefreshOnce()` coalesce into a single `/auth/refresh`, nor that two near-simultaneous refresh triggers result in exactly one network call. The most security-sensitive auth behavior (the ADR-0015 replay → all-sessions-revoked seam) is entirely unguarded by tests.
- **Risk:** The dedupe regression flagged in the related frontend finding can be introduced or worsened with zero test signal; refactors of the refresh paths cannot be safely verified.
- **Recommendation:** Add a test that fires the scheduled/AuthProvider refresh and a client 401-retry refresh concurrently (mock `/auth/refresh` and assert it is hit exactly once), and a test asserting both callers share one in-flight promise. Co-locate with the dedupe fix.
- **Effort:** M

## Docs & ADR drift

The documentation set has drifted hard around one event: the replacement of the Perplexity-based `ai_search` screening subsystem with the multi-vendor LLM enrichment pipeline (Gemini/OpenAI/Tavily/DeepSeek). That migration deleted a table, a worker, a client module, and a propagation function, but the corresponding ops runbooks, deploy guide, two ADRs, and three core orientation docs were never updated — so they now point operators and agents at resources that no longer exist. The drift is uniformly P2/P3 (stale-but-misleading rather than secret-leaking), but it concentrates in exactly the documents read during incidents and onboarding, which amplifies its real-world cost. A separate, structural gap — no documented backup/DR procedure for the single production database — compounds the runbook problem. Every code-side claim in these findings was verified against the current tree (deploy.yml, infra/sqs.tf, src/collector, alembic migrations).

### [DOCS-001] P2 — Runbook references non-existent ai-search-dlq / ai_search_worker / Perplexity resources

- **Where:** `docs/ops/runbook.md:68,76,148-162,181` vs `infra/sqs.tf`, `infra/lambda.tf`.
- **Evidence:** `runbook.md:68` lists `beatport-prod-ai-search-dlq` among the DLQ alarms; the DLQ-cause table (`:76`) and reserved-concurrency table (`:157`) reference an `ai_search_worker` throttled against a "Perplexity 5 RPS limit." None exist. `infra/sqs.tf` defines exactly six queue families — `canonicalization`, `spotify_search`, `vendor_match`, `label_enrichment`, `artist_enrichment`, `auto_enrich_dispatch` (verified: 12 `aws_sqs_queue` resources, queue+DLQ each). `grep -ri 'ai_search\|ai-search\|perplexity' infra/` returns nothing. The runbook's DLQ list also omits the three real enrichment DLQs (`label_enrichment`, `artist_enrichment`, `auto_enrich_dispatch`).
- **Risk:** During an incident the operator is steered toward a queue, Lambda, and vendor that were all removed, and diagnoses 429s against Perplexity instead of the real Gemini/OpenAI/Tavily/DeepSeek path. Worse, the real enrichment DLQs are absent from the alarm list, so the document gives no guidance for the failure modes that can actually occur. This is the on-call-path document, which is why it is the only P2 here.
- **Recommendation:** Rewrite the DLQ-alarm, DLQ-cause, and reserved-concurrency sections to enumerate the six real DLQs and the actual enrichment vendors; delete every `ai_search`/`ai_search_worker`/Perplexity row.
- **Effort:** S

### [DOCS-002] P3 — docs/ops/deploy.md is badly stale: wrong secrets, wrong vendor vars, dead ai-search worker, masked deploy ordering

- **Where:** `docs/ops/deploy.md:32-47,73-84,97-105` vs `.github/workflows/deploy.yml:53-100`.
- **Evidence:** `deploy.md:33` documents syncing `/clouder/perplexity/api_key`; `:41` and `:43` pass `-var ai_search_enabled=true` and `-var perplexity_api_key_ssm_parameter=...`; the GitHub-Secrets table (`:79`) lists `PERPLEXITY_API_KEY` as required. The actual `deploy.yml` syncs **eight** SSM params — gemini/openai/tavily/deepseek api keys, spotify client_id/secret, ytmusic client_id/secret (`:56-79`) — and applies `gemini/openai/tavily/deepseek/ytmusic` vars plus `vendor_match_enabled=true`, `spotify_oauth_redirect_uri`, `admin_spotify_ids`, `allowed_frontend_redirects` (`:84-100`). No `perplexity`/`ai_search` var exists. The manual-ops example (`deploy.md:101`) targets `--function-name beatport-prod-ai-search-worker`, a Lambda that no longer exists (its tables were dropped in `alembic/versions/20260518_21_drop_ai_search_results.py`).
- **Risk:** An operator setting up or rotating secrets provisions dead SSM parameters and never sets the four LLM keys and two ytmusic keys the deploy actually consumes — producing enrichment/publish failures that are hard to trace back to the runbook. The doc also misstates the apply→migrate step ordering, so the document is unreliable precisely where the steps are riskiest.
- **Recommendation:** Regenerate deploy.md from the current `deploy.yml`: list all eight synced SSM params, the real `-var` set, and the full secret/variable inventory (including `ALLOWED_FRONTEND_REDIRECTS`, `ADMIN_SPOTIFY_IDS`, `SPOTIFY_OAUTH_REDIRECT_URI`); remove all Perplexity/ai-search references and fix the step ordering.
- **Effort:** S

### [DOCS-003] P3 — docs/data/search-and-enrichment.md documents the deleted Perplexity worker, perplexity_client.py, and ai_search_results table as live

- **Where:** `docs/data/search-and-enrichment.md:3,110-232`; also `docs/architecture.md:36,64` and `docs/data/data-model.md:35,120,160`.
- **Evidence:** `search-and-enrichment.md:3` says enrichment uses "Spotify and Perplexity"; lines 110-232 ("Perplexity label and artist screening") cite `src/collector/search_handler.py` and `src/collector/search/perplexity_client.py`, describe an `EntitySearchMessage` worker, the `ai_search_results` DDL, and `propagate_ai_flag`. None exist: `ls src/collector/search_handler.py src/collector/search/` → no such file; `grep -r 'EntitySearchMessage\|perplexity_client\|search_handler\|propagate_ai_flag' src/collector` → zero hits; the table was dropped in `20260518_21`. `architecture.md:36` still draws a `Perplexity API` node and `:64` states "Perplexity is used to flag AI-suspected labels"; `data-model.md:35` lists `ai_search_results` as a current enrichment table and `:120/:160` attribute `is_ai_suspected` to "Perplexity search propagation."
- **Risk:** These are the primary backend/data orientation docs, linked from `architecture.md` and the role-folder map in `CLAUDE.md`. They send any agent investigating the AI-screening flow to two non-existent source files and a dropped table, and assert that Perplexity is a live vendor when it survives only in a stale docstring (`providers/registry.py:4`) and a comment (`settings.py:19`).
- **Recommendation:** Rewrite the "Perplexity label and artist screening" section to describe the current LLM-enrichment AI-flag mirror (label/artist enrichment workers, no Perplexity, no `ai_search_results`); replace the Perplexity node in `architecture.md` and the `ai_search_results` row in `data-model.md`.
- **Effort:** M

### [DOCS-004] P3 — ADR-0008 describes a removed Perplexity/ai_search_results subsystem as the live AI-flag mechanism

- **Where:** `docs/adr/0008-ai-suspected-flag.md` (whole ADR, Status: Accepted); contradicted by `alembic/versions/20260518_21_drop_ai_search_results.py` and `src/collector/label_enrichment/repository.py:817-836`.
- **Evidence:** ADR-0008 (`Status: Accepted`, not superseded; README index) states `is_ai_suspected` is set by `propagate_ai_flag` reading `ai_search_results` (Perplexity JSONB) on labels/artists/tracks. Reality: migration `20260518_21` drops `ai_search_results`; `propagate_ai_flag` has zero definitions or callers in `src/collector` (verified grep). The flag is now mirrored from the multi-vendor LLM enrichment via `_mirror_ai_content` (`repository.py:817-836`: `UPDATE clouder_labels SET is_ai_suspected = :value`, gated on `merged.confidence >= threshold` and `merged.ai_content in (SUSPECTED, CONFIRMED)`, cleared on `NONE_DETECTED`) — i.e. ADR-0016's pipeline.
- **Risk:** An agent following ADR-0008 hunts for a Perplexity client, an `ai_search_results` table, and a `propagate_ai_flag` function that were all deleted, and may wire AI-flag work to the dead subsystem. The threshold/clear semantics happen to survive in the new code, but the entire described data path and table are gone, so the ADR misleads on "where does this flag come from."
- **Recommendation:** Mark ADR-0008 `Superseded by ADR-0016` (and update the README index status), or rewrite its Decision/Consequences to describe the current source: `is_ai_suspected` mirrored from `merged.ai_content` in the label-enrichment consensus, confidence-gated, with no `ai_search_results` table.
- **Effort:** S

### [DOCS-005] P3 — ADR-0019 states YT Music publish uses ytmusicapi, but publish goes through the YouTube Data API v3

- **Where:** `docs/adr/0019-youtube-music-vendor.md:36-43`; contradicted by `src/collector/curation/youtube_data_api_client.py:1-9` and `ytmusic_publish_service.py`.
- **Evidence:** ADR-0019's Decision (the **Publish** bullet) says publish "Uses `ytmusicapi` authenticated + Google device-flow OAuth." The actual publish client is `YoutubeDataApiClient`, whose module docstring (`youtube_data_api_client.py:1-9`) states: "ytmusicapi's OAuth (device-flow) path is broken upstream for write operations … We therefore publish via the official YouTube Data API v3, reusing the SAME Google OAuth bearer token and `youtube` scope" (base `https://www.googleapis.com/youtube/v3`). Match (lookup) still correctly uses unauthenticated ytmusicapi per the ADR; only the publish transport drifted.
- **Risk:** The ADR misattributes the publish transport. An agent trusting it would debug or extend publish against ytmusicapi's broken OAuth write path — the exact failure mode the code was rewritten to avoid. Device-flow OAuth and the token reuse are still accurate, so the drift is narrow but lands on the load-bearing "how do we publish" detail.
- **Recommendation:** Amend ADR-0019's Decision bullet (or add a follow-up note) to state that publish uses the official YouTube Data API v3 (`YoutubeDataApiClient`) over the same Google OAuth token/scope because ytmusicapi's OAuth write path is broken upstream; ytmusicapi remains only for unauthenticated match search.
- **Effort:** S

### [DOCS-006] P3 — No backup/restore/DR procedure documented in docs/ops despite detailed scaling docs

- **Where:** `docs/ops/aurora.md` (covers scaling, IAM auth, master secret, cold-start — no backup section); `docs/ops/deploy.md` and `README.md` contain zero backup/snapshot/restore mentions.
- **Evidence:** `aurora.md` documents Serverless scaling, IAM auth, the migrator grant, master-secret retention, and cold-start in depth, but has no section on backup retention, PITR, snapshot restore, or disaster recovery. `grep -i 'backup\|snapshot\|restore\|disaster\|recover\|pitr' docs/ops/aurora.md docs/ops/deploy.md README.md` returns nothing. Combined with the infra gap (`skip_final_snapshot=true`, no `backup_retention_period`), there is no documented recovery path for the single production database.
- **Risk:** If the cluster is lost or corrupted, the operator has no documented procedure (restore-from-snapshot, PITR window, expected RPO/RTO). The undocumented 1-day default retention and the missing final snapshot are never surfaced to whoever runs the deploy.
- **Recommendation:** Add a "Backups & disaster recovery" section to `docs/ops/aurora.md` stating the configured retention/PITR window, the restore-from-snapshot and PITR-restore CLI steps, and the expected RPO/RTO — ideally alongside fixing the infra backup config so docs and reality agree.
- **Effort:** S

## Stats

- **Pipeline:** 114 raw finder findings + 25 scanner findings kept = 139 merged → 139 after dedup → **105 survived** 3-lens adversarial verification → **99 presented** after synthesis consolidated duplicate findings.
- **Finders run:** 26/26 (subsystem × dimension matrix).
- **Scanners:** bandit, pip-audit (×2), pnpm audit, tsc, eslint, checkov — see `scanners.md`.

**Presented findings by severity:**

| Severity | Count |
|---|---|
| P0 | 0 |
| P1 | 10 |
| P2 | 42 |
| P3 | 47 |
| **Total** | **99** |

**By subsystem:**

| Subsystem | Count |
|---|---|
| curation | 15 |
| infra | 15 |
| ci | 14 |
| enrichment | 13 |
| ingest | 10 |
| auth | 9 |
| canonicalization | 8 |
| migrations | 6 |
| data-access | 4 |
| frontend | 3 |
| system | 2 |


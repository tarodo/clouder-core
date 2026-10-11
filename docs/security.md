# Security: threat model

CLOUDER is a small multi-tenant SaaS: a few DJs sign in with Spotify, and one admin runs ingest. The repo is public. This page lists what is worth protecting, where the trust boundaries are, which threats each boundary faces and what stops them, and the gaps that are known and accepted.

## Assets

| Asset | Where | Why it matters |
|---|---|---|
| Users' Spotify and YouTube OAuth tokens | Aurora `user_vendor_tokens`, KMS envelope | They act on the user's real accounts (publish playlists) |
| CLOUDER sessions | Refresh JWT in an HttpOnly cookie, its hash in `user_sessions` | Whoever holds one is the user for up to 7 days |
| JWT signing key | SSM SecureString | Mints any session, including admin |
| Beatport credentials and tokens | GitHub secrets → SSM SecureString; tokens in memory only | Ingest source; the account belongs to the owner |
| Vendor API keys (Gemini, OpenAI, Tavily, DeepSeek, YouTube) | GitHub secrets → SSM SecureString | Paid usage |
| Users' curation data and personal data | Aurora, lake (see [privacy.md](privacy.md)) | Their work, their email |
| The AWS account | GitHub OIDC deploy role | Everything above |

## Trust boundaries

```
Browser ──HTTPS──▶ CloudFront (SPA) ──▶ API Gateway ──▶ Lambda authorizer ──▶ API Lambdas ──▶ Aurora (Data API), S3, SQS
                                                                              └──▶ Spotify · YouTube · Beatport · LLM vendors
GitHub Actions ──OIDC──▶ AWS (Terraform, Lambda code, SSM)
```

### 1. Browser ↔ API

| Threat | Control |
|---|---|
| Stolen login (CSRF on the OAuth callback, code interception) | Spotify OAuth Authorization Code + PKCE; `state` and `code_verifier` in HttpOnly, Secure, SameSite=Lax cookies (10 min), checked on the callback; post-login redirects only to an allow-list (`ALLOWED_FRONTEND_REDIRECTS`). See [api/auth-flow.md](api/auth-flow.md). |
| Token theft through XSS | The access JWT and the Spotify access token live in memory only, never in `localStorage`, `sessionStorage` or cookies ([frontend/auth.md](frontend/auth.md)). The refresh token is an HttpOnly, Secure, SameSite=Strict cookie scoped to `/auth/refresh`. The SPA never uses `dangerouslySetInnerHTML`, so third-party text (YouTube comments, LLM research) renders escaped. |
| Replayed refresh token | Refresh rotation: every refresh issues a new token and stores its SHA-256 hash. Presenting an old one revokes every session of that user ([ADR-0015](adr/0015-refresh-cookie-replay.md)). |
| Forged or expired JWT | A Lambda authorizer verifies the HS256 signature, expiry and claims on every protected route; access tokens live 30 minutes. Admin routes also check the `is_admin` claim in the handler. |
| One user reading another's data | Every overlay query is scoped by the authorizer's `user_id`, never by a client-supplied id. Cover uploads use 5-minute presigned PUT URLs under `covers/<user_id>/`; confirm checks the prefix and the size (256 KB). |
| Abuse, scraping, cost attacks | API Gateway stage throttling (100 rps, burst 200), JSON access logs, Lambda timeouts. The SPA reaches the API through its own CloudFront origin and API Gateway sends no CORS headers, so a page on another origin cannot call the API from a browser. |
| Clickjacking, MIME sniffing, downgrade | CloudFront response headers: HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`; Content-Security-Policy in report-only mode. |

### 2. Lambda ↔ data stores

| Threat | Control |
|---|---|
| A compromised function reaching everything | One IAM role per Lambda, least privilege (`infra/lambda_roles.tf`): each role lists its own queues, bucket prefixes, SSM parameters and Data API cluster. |
| SQL injection | All SQL takes bind parameters through the RDS Data API. Identifiers built at runtime (user deletion) come from the Postgres catalog, never from input. Athena date literals are validated before they are inlined ([CLAUDE.md gotcha 13](../CLAUDE.md)). |
| Leaking OAuth tokens from the database | Vendor tokens are encrypted with a per-row data key under a KMS key with rotation on; a database dump without `kms:Decrypt` is useless. |
| Secrets in logs | Structured logs pass through an allow-list of field names (`ALLOWED_LOG_FIELDS`); anything else is dropped. `bp_token` and OAuth tokens are never logged or persisted. |
| Public buckets | Every bucket has a public access block; the SPA bucket is reachable only through CloudFront (OAC). Aurora sits in private subnets and is reached only through the Data API. |
| Losing data to a mistake | Aurora deletion protection, 7-day point-in-time restore, final snapshot; versioned raw bucket. See [ops/failure-modes.md](ops/failure-modes.md). |

### 3. Lambda ↔ third parties

| Threat | Control |
|---|---|
| A vendor key leaking or being overspent | Keys live in SSM, read at runtime by the one function that needs them. Enrichment runs only on demand or for finalized triage blocks, through SQS with DLQs and a throttle alarm. |
| Prompt injection through web search results in LLM enrichment | LLM output is stored as data and shown as text; it never runs as code, SQL or tool calls. |
| Beatport credentials exposed | They exist only in GitHub secrets and SSM; auto-ingest logs in per run and keeps the token in memory. Ingests started from the Coverage page log in the same way server-side; no Beatport token ever reaches the browser. |

### 4. GitHub ↔ AWS

| Threat | Control |
|---|---|
| Long-lived cloud credentials in CI | No AWS keys anywhere: both workflows assume roles through GitHub OIDC. Pull requests plan under a read-only role (`clouder-prod-gha-plan`) that only pull-request jobs can assume and only the `terraform` job may request; it cannot change AWS resources or read vendor secrets, but it reads the Terraform state, whose JWT signing key makes it roughly application-admin; credentials are configured after the Lambda is packaged and the frontend built, so no dependency install runs with them ([ADR-0028](adr/0028-ci-roles.md)). |
| A malicious or careless change deployed | `main` takes changes only through pull requests with 8 required checks (tests with a coverage gate, lint, types, Terraform, dbt, dependency audit, frontend); admins are not exempt. Only jobs in the `production` environment, which accepts protected branches only, can assume the deploy role; its ARN and the credentials it syncs to SSM exist only there. |
| A vulnerable dependency | Locked Python dependencies with `pip-audit`, `pnpm audit` on runtime packages, Dependabot for pip, npm, Actions and Terraform. |
| Secrets or account ids in the public repo | Scripts take ARNs from the environment; a test fails on any real account id in a tracked file. |

## Known gaps

- **The CI role split is only half rolled out (2026-10-11).** Pull requests already plan under the read-only role, but until the deploy role's trust drops `pull_request` and its ARN moves into the `production` environment ([ADR-0028](adr/0028-ci-roles.md)), a same-repo pull request that edits `pr.yml` can still assume it.
- **The deploy role has AdministratorAccess.** Only the `production` environment can assume it, so a compromised `main` controls the whole account. The fix is a scoped Terraform role; it is deferred because the Terraform surface changes often and branch protection guards the path.
- **The JWT signing key is in the Terraform state.** Whoever can plan — today only the owner's pull requests — can read it and mint sessions. Moving it out of state (a write-only attribute, or generating it outside Terraform) comes before anyone else gets push access.
- **Minimum TLS is CloudFront's default for `*.cloudfront.net` (TLSv1).** Browsers negotiate TLS 1.2+ anyway; enforcing it needs a custom domain with an ACM certificate.
- **CSP is report-only.** Enforcing needs an inventory of what the Spotify Web Playback SDK loads.
- **No WAF.** Throttling and authorizer checks cover the current scale; a WAF is worth it once sign-up is open.
- **HS256 with one shared key.** Fine with one issuer and one verifier in the same account. Rotating it signs every user out.
- **An access token outlives a revocation by up to 30 minutes.** Revocation acts on refresh tokens; access tokens are not checked against a deny list.
- **YouTube Music publishing runs in Google's OAuth "Testing" mode:** refresh tokens expire after 7 days and only listed test users can connect.

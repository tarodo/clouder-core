# CLOUDER MVP review — automated scanner results

**Status:** FINAL
**Reviewed commit:** 1614a1d007f677f6f69c5d1567443f004a03a097

Raw JSON outputs live in `/tmp` (not committed). Kept hits are converted to the
finding schema in `working/scanner-findings.json` and verified alongside finder
output in Phase 4.

## bandit (Python SAST)

```
bandit -r src/collector -f json
```

- Total issues: 90 (severity HIGH 0 / MEDIUM 73 / LOW 17).
- Filter: severity ≥ MEDIUM **and** confidence ≥ MEDIUM → **63 kept**.

| Test | Count | Severity/Confidence | Disposition |
|---|---|---|---|
| B608 hardcoded_sql_expressions | 58 | MEDIUM/MEDIUM | Kept, grouped per file (9 findings) |
| B310 urllib urlopen | 5 | MEDIUM/HIGH | Kept as 1 aggregate finding |

B608 hits by file: triage_repository.py (14), repositories.py (11),
label_enrichment/repository.py (7), curation/tags_repository.py (7),
artist_enrichment/repository.py (6), curation/playlists_repository.py (5),
label_enrichment/auto_repository.py (3), artist_enrichment/auto_repository.py (3),
curation/categories_repository.py (2). These flag string-built SQL; the
verification phase confirms whether user input is parameterized via the Data API.

## pip-audit (Python dependency CVEs)

```
pip-audit -r src/collector/requirements.txt
pip-audit -r requirements-dev.txt
```

- Runtime deps: **No known vulnerabilities.**
- Dev deps: **No known vulnerabilities.**
- Kept: 0.

## pnpm audit (frontend dependency CVEs)

```
pnpm audit --json
```

- Total advisories: 13 (critical 1 / high 4 / moderate 6 / low 2).
- Filter: high + critical → **5 kept**.

| Severity | Module | Issue |
|---|---|---|
| critical | vitest | Arbitrary file read/execute when UI server listening (dev-only) |
| high | react-router | DoS via unbounded path expansion in `__manifest` |
| high | ws | Memory-exhaustion DoS from tiny fragments |
| high | form-data | CRLF injection via unescaped multipart field names |
| high | vite | `server.fs.deny` bypass on Windows alternate paths (dev-only) |

## tsc (TypeScript typecheck)

```
pnpm typecheck
```

- Errors: **0**. Kept: 0.

## eslint (frontend lint)

```
pnpm lint
```

- 0 errors, 2 warnings (unused eslint-disable in theme.ts; missing useEffect dep).
- Filter: errors only → **0 kept** (warnings noted, not findings).

## checkov (Terraform IaC)

```
checkov -d infra -o json
```

- Resources: 191. Passed 299 / **failed 138** / skipped 0.
- Filter: failed checks mapped to one finding per check_id, excluding pure
  hardening best-practices irrelevant to a small-circle MVP and checks that
  contradict accepted cost behaviors. **10 kept.**

| check_id | Affected | Dimension | Kept finding |
|---|---|---|---|
| CKV_AWS_139 | aurora | DATA (P1) | RDS deletion protection disabled |
| CKV2_AWS_8 | aurora | DATA (P2) | RDS not covered by AWS Backup plan |
| CKV_AWS_116 | 11 lambdas | REL (P2) | No Lambda DLQ / on-failure destination |
| CKV_AWS_115 | 7 lambdas | COST (P2) | No reserved concurrency limit |
| CKV_AWS_309 | 4 auth routes | SEC (P2) | Routes w/o authorization_type (likely the intended public auth endpoints) |
| CKV_AWS_356 | collector role | SEC (P2) | IAM `*` resource for restrictable actions |
| CKV_AWS_111 | collector role | SEC (P2) | IAM unconstrained write access |
| CKV_AWS_173 | 11 lambdas | SEC (P3) | Lambda env vars not CMK-encrypted |
| CKV_AWS_27 | 12 queues | SEC (P3) | SQS not encrypted at rest |
| CKV_AWS_338 | 11 log groups | COST (P3) | Log retention < 1 year / unset |

Not carried forward as findings (best-practice hardening, low MVP signal):
X-Ray tracing (CKV_AWS_50), code-signing (CKV_AWS_272), Lambda-in-VPC
(CKV_AWS_117), CloudFront WAF/logging/geo/TLS, S3 replication/versioning/
lifecycle/access-logging, KMS-CMK-everywhere, SG descriptions. The infra finders
(Phase 3) cover these dimensions with MVP-aware judgment.

# ADR-0029: API Lambdas behind a `live` alias, a smoke test, and automatic rollback
Status: Accepted
Date: 2026-10-11

## Context

Every merge to `main` deploys to production and there is no staging stack
([decisions to revisit](../design/decisions-to-revisit.md)). A deploy that broke the API was
found by users or alarms and undone by reverting the PR and waiting for a full CI and deploy
cycle. The Lambda zip was also not byte-reproducible, so every plan showed all 18 functions
changing and a version per deploy would have meant a new version every time.

Options considered: aliases with CodeDeploy traffic shifting (canary) — strong, but a second
deployment system for six functions and a handful of users; aliases on all 18 functions —
re-pointing SQS mappings, EventBridge and Scheduler targets and Step Functions tasks for
workers whose failures SQS retries and DLQs already absorb; a smoke test alone — detects a
bad deploy but still needs the revert cycle to fix it.

## Decision

- The Lambda zip is byte-reproducible (`scripts/deterministic_zip.py`), so a version is
  published only when code changes.
- The six API functions (`collector-api`, `curation`, `auth-handler`, `auth-authorizer`,
  `analytics-api`, `telemetry`) publish versions; API Gateway integrations and the authorizer
  call their `live` alias. Alias-scoped invoke permissions exist before any integration
  switches to them.
- The deploy snapshots the alias versions before `terraform apply`, runs `scripts/smoke.py`
  after the frontend sync, and on any failure points every alias back to its snapshot
  version (`scripts/api_aliases.py restore`).
- The smoke test never writes and never touches Aurora: each Lambda gets a request it answers
  before any I/O, plus three public URLs; a unit test runs every smoke event through the real
  handler with AWS calls forbidden.

## Consequences

- A broken API deploy costs the minutes until the smoke step, not a revert cycle.
- The next apply moves the aliases forward again: after a rollback the fix is a revert or a
  new commit (fix forward).
- Not rolled back: the frontend, the workers, DB migrations (backward compatible by policy).
- Versions accumulate: ~25 MB per function version, ~150 MB per code-changing deploy against
  the account's 300 GB limit (0.45 GB used on 2026-10-11) — pruning is not needed yet
  ([scalability](../scalability.md#lambda-versions)).

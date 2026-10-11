# 2026-10-11 — Background workers took the API's Lambda capacity

## Summary

A triage block finalize fanned out into about 240 background jobs. The comment-collection worker had no concurrency cap and the enrichers were capped at 8 each, while the whole AWS account allows 10 concurrent Lambda executions. The workers took every slot, the API functions were throttled, and API Gateway answered 5xx. No alarm fired: alarms watched function errors, and a throttle is not one. The third hiring-audit review found it in the 30-day metrics the same morning.

## Impact

Between 04:42 and 04:49 UTC, 16 of about 200 API requests failed with 5xx for the one active user (the owner, triaging in the app). The background jobs were delayed and retried by SQS; none reached a dead-letter queue.

## Timeline (UTC)

- 04:38–04:47 — the owner triages a week: 21 track moves, 11 block lists, then `triage_block_finalized`.
- 04:4x — the finalize reaches the auto-enrich dispatch worker, which enqueues 131 comment collections, 80 artist and 32 label enrichments.
- 04:47 — comments (uncapped), artist and label enrichers (capped at 8 each) fill the account pool. Throttles in that window: comments 176, artist 53, label 37, `clouder-prod-collector-api` 10, `clouder-prod-auth-handler` 5.
- 04:48–04:49 — API Gateway returns 15 × 5xx (one more at 04:42); the queues drain and errors stop.
- 09:17 — found while reviewing Lambda throttles and API 5xx for the audit.

## Root cause

One shared pool of 10 executions and no budget for it. The enricher caps (8 + 8) were meant to leave room for interactive functions but together exceeded the pool on their own; the comments worker, added later, had no cap; nothing checked the sum against the quota.

## Fix

- Every SQS event source mapping has a `maximum_concurrency` cap with validation; `tests/unit/test_concurrency_infra.py` fails on a mapping without one and on caps that, with 20 executions for the API and scheduled jobs, exceed the quota.
- The quota increase to 100 is requested through AWS Support; `infra/concurrency.tf` holds the value the worker budget is planned for. Asking Terraform for it failed the first deploy of the fix: the Service Quotas API refuses values below the AWS default of 1000, and this account was lowered to 10. Until AWS approves it the account still has 10, so the label and artist enricher caps are lowered from 8 to 2 in `infra/prod.tfvars`: a finalize's fan-out (dispatch, comments, label, artist) then needs 8 of the 10.
- Alarms on throttles of the six API functions, on API Gateway 5xx (5 in 5 minutes) and on account concurrency at 80 % of the quota the account has now (read from Service Quotas, not the requested value), all to the owner's email.

## Detection gap

- Errors alarms only: a throttled invocation is not a function error, and 5xx from API Gateway never reach the function.
- The one throttle alarm (label enricher) existed only with reserved concurrency switched on, which the quota of 10 made impossible.
- API 5xx were on the dashboard, which nobody watches at night.

## Follow-ups

- When the quota increase is approved, remove the interim enricher caps from `infra/prod.tfvars` and decide on `enable_lambda_reserved_concurrency` (it also protects vendor rate limits).
- Earlier in the same 30 days the curation, collector and auth functions were throttled 24 more times; the same mechanism is the likely cause, and the new alarms would have reported each one.

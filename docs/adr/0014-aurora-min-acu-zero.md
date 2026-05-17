# ADR-0014: Aurora Serverless v2 `min_acu=0`
Status: Accepted
Date: 2026-05-17

## Context

CLOUDER's Aurora Serverless v2 cluster is used intermittently: ingest runs a few times per week, enrichment workers are triggered on demand, and user-facing requests cluster around DJ session review periods. Between sessions the cluster can sit idle for hours.

Aurora Serverless v2 supports two idle configurations. With `min_acu >= 0.5`, the cluster is always warm — it maintains at least 0.5 ACUs even with zero traffic. The cost is approximately $43/month for the minimum always-on reservation. With `min_acu=0`, the cluster auto-pauses after the configured idle timeout (`aurora_auto_pause_seconds=300`, i.e. 5 minutes). Auto-pause eliminates the idle cost entirely; the cluster costs nothing when not in use.

The downside of auto-pause is cold-start latency. When the first request arrives after a pause, Aurora resumes — a process that typically takes 15–25 seconds. API Gateway has a hard 29-second integration timeout. A cold-start resume that takes longer than the remaining gateway budget causes API Gateway to return `{"message":"Service Unavailable"}` (capital S/U) — not a CLOUDER application error. The Lambda usually completes the work in background after the gateway times out.

For the current usage pattern — a small DJ circle, non-real-time admin ingests, infrequent session reviews — the cold-start risk is acceptable. The first request after an idle period may fail but can simply be retried 5–10 seconds later, by which time the cluster is warm. The ~$43/month saving is material for a personal project budget.

If first-request latency becomes unacceptable (e.g. a user-facing search feature with SLA requirements), `aurora_serverless_min_acu=0.5` can be set in `infra/terraform.tfvars` and applied via `terraform apply`. This change takes effect within a few minutes.

## Decision

Aurora Serverless v2 is configured with `aurora_serverless_min_acu = 0` and `aurora_auto_pause_seconds = 300`. The cluster auto-pauses after five minutes of idle. The cost saving is roughly $43 / month relative to always-warm `min_acu = 0.5`.

## Consequences

- The first request after ≥ 5 minutes of idle may return a 503 from API Gateway. The CLOUDER application did not fail — only the gateway timed out. The correct user-facing message is "please retry in a few seconds".
- Distinguishing Aurora cold-start 503 from application 503: API Gateway's envelope is `{"message": "Service Unavailable"}` (capital letters, no `error_code`). CLOUDER's application errors always include `error_code` and `correlation_id`.
- `DataAPIClient` uses two retry decorators: `retry_data_api` on `execute`/`batch_execute`/`begin_transaction` (retries on `DatabaseResumingException` among other transient codes) and `retry_data_api_pre_execution` on `commit_transaction`/`rollback_transaction`. The retry logic absorbs short resume times (< ~25 s) transparently, but long resumes exceed the Lambda's own timeout budget.
- Lambda workers (canonicalization, Spotify search, AI search, vendor match) are SQS-triggered and have their own timeout budgets independent of API Gateway. Aurora cold-start during a worker invocation will also trigger `DatabaseResumingException` retries; the worker's longer timeout (up to 900 s for canonicalization) absorbs the resume time without failure.
- To permanently eliminate cold-start 503s: set `aurora_serverless_min_acu = 0.5` in `infra/terraform.tfvars` and run `terraform apply`. No code changes are required.

**Cross-references:** `../ops/aurora.md`, `../ops/runbook.md`.

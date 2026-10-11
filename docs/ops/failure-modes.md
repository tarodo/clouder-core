# Failure modes, RPO and RTO

What breaks, how we find out, what the user sees, and how to recover. Every alarm emails the owner through one SNS topic. Alarm names carry the `clouder-prod-` prefix; `<fn>` is a Lambda name (`clouder-prod-curation`, …). RPO is how much data can be lost; RTO is how long until the function works again.

## Failure modes

| Failure | Detection | Impact | Recovery | RPO / RTO |
|---|---|---|---|---|
| **Aurora paused** (`min_acu = 0`, idle > 300 s) | `<fn>-duration-p95` on the API Lambdas; workers log `DatabaseResumingException` | The first API request after idle can time out (503); workers retry through SQS; auto-ingest and data quality wait for the resume themselves | Automatic. Retry the request. [Runbook: cold-start 503](runbook.md#cold-start-503), [ADR-0014](../adr/0014-aurora-min-acu-zero.md) | 0 / under a minute |
| **Aurora at capacity** | `clouder-prod-aurora-acu-near-max` | Slow queries, API timeouts | Raise `max_acu` in Terraform ([aurora.md](aurora.md#serverless-v2-scaling)) | 0 / one deploy |
| **Aurora data lost or corrupted** (bad migration, bad delete) | Data-quality checks (`clouder-prod-data-quality-failed-checks`), user reports | Wrong or missing curation data | Point-in-time restore to a new cluster, repoint Terraform ([aurora.md](aurora.md#data-protection)) | ~5 min (latest restorable time) / restore + repoint, not rehearsed yet |
| **Beatport login or API down** | `clouder-prod-auto-ingest-failed`, `<fn>-errors` on `auto-ingest` | No new weeks ingested; the catalog lags | Automatic: the due weeks stay due and the next run (3 a day) picks them up. Credentials: [runbook](runbook.md#auto-ingest-run-failed) | 0 (Beatport is the source) / the next scheduled run |
| **Spotify bans the app (429, long Retry-After)** | `spotify_search_paused` in the worker log; tracks without a Spotify link | Spotify links arrive after the ban (hours) | Automatic: the ban is stored in `vendor_rate_limits` and one delayed resume message restarts the search after it ([runbook](runbook.md#spotify-search-paused-rate-limit-ban)) | 0 / the ban's length |
| **Spotify, YouTube or an LLM vendor down or rate-limited** | `<fn>-errors` on the worker; DLQ `…-dlq-has-messages` after the retries | Enrichment, matching or comments arrive late; publishing returns an error to the user, who retries | SQS redelivers after the visibility timeout; then redrive the DLQ ([runbook](runbook.md#dlq-messages)) | 0 while the message is in the DLQ (14 days; 4 for the enrichers, 1 for auto-enrich dispatch) / redrive |
| **DLQ growth** (a poison message, a code bug) | `…-dlq-has-messages` (any message) | That work item is stuck | Read the message, fix, redrive ([runbook](runbook.md#dlq-messages)) | 0 / one fix |
| **Firehose cannot deliver telemetry** | `clouder-prod-telemetry-delivery-freshness` (records older than 15 min) | Home analytics cards go stale | Fix the permission or schema; Firehose retries for 24 h ([runbook](runbook.md#telemetry-delivery-stalled)) | 0 within 24 h, events beyond that are lost / one fix |
| **dbt build or Athena fails** | `clouder-prod-transform-failed` | Silver/gold stop advancing; the cards stay correct for two missed nights because they read the last three days from bronze | Read the CodeBuild log, fix, re-run ([runbook](runbook.md#nightly-dbt-build-failed)) | 0 (rebuilt from bronze) / one build |
| **Raw S3 object deleted or overwritten** | Backfill or canonicalization errors on a missing key | That run cannot be replayed | Restore the previous version (the bucket is versioned), then replay ([backfill.md](backfill.md)) | 0 / restore + replay |
| **A bad deploy** | The deploy's smoke test; `<fn>-errors`, `<fn>-duration-p95` | Errors on the changed routes until the smoke step | API Lambdas: the deploy points their `live` aliases back to the previous versions automatically ([deploy.md](deploy.md#rollback)). Frontend and workers: revert the PR. Migrations run first and are written to be backward compatible | 0 / minutes (API), one CI + deploy cycle (the rest) |
| **IAM regression** (a role lost a permission) | `<fn>-errors` with `AccessDenied` in the log | That function fails; SQS messages retry, then land in the DLQ | Fix `infra/lambda_roles.tf`, deploy, redrive. `tests/unit/test_iam_per_function_infra.py` guards the wiring | 0 / one deploy |
| **Upstream data drift** (Beatport changes a field) | `clouder-prod-contract-drift`, `clouder-prod-quarantined-records` | Bad records go to quarantine instead of the catalog | Update the contract, replay the affected runs ([runbook](runbook.md#contract-drift-or-quarantined-records), [contracts.md](../data/contracts.md)) | 0 (raw is kept) / fix + replay |
| **Data quality regression** (stale, missing or implausible data) | `clouder-prod-data-quality-failed-checks` (nightly, 00:10 UTC) | Depends on the check | [data-quality.md](../data/data-quality.md) | — |
| **API abuse or a traffic spike** | 429s in the access log ([runbook](runbook.md#429-too-many-requests-from-the-api)) | Excess requests get 429 | Stage throttling (100 rps, burst 200) holds; raise it in Terraform if legitimate | 0 / immediate |

## Data stores

| Store | Protection | RPO | RTO |
|---|---|---|---|
| Aurora | Deletion protection, 7-day point-in-time restore, final snapshot on delete | ~5 minutes | Restore to a new cluster and repoint Terraform; not rehearsed yet |
| S3 raw (`releases.json.gz`, `meta.json`, covers) | Versioned, no force-destroy; old versions move to Glacier Instant Retrieval after 30 days and never expire | 0 | Minutes per object (instant retrieval), then a backfill replay |
| S3 lake bronze (telemetry, catalog snapshots) | Not versioned | Everything not yet in silver | Silver keeps the deduplicated history; the raw events themselves cannot be recovered |
| Iceberg silver / gold | Iceberg snapshots (Athena keeps 5 days after `VACUUM`); rebuildable from bronze | 0 while bronze exists | One `dbt build --full-refresh` |
| SSM parameters | GitHub secrets are the source; the deploy workflow writes them | 0 | Run the Deploy workflow |
| Terraform state | S3 backend outside this configuration | — | — |

## Known gaps

- **The lake bucket is not versioned and has `force_destroy = true`** (it was renamed once and its data was disposable then). Losing it loses the raw telemetry; silver keeps the history.
- **Aurora restore has not been rehearsed.** The procedure is documented; the RTO is an estimate until it is run once.
- **Short DLQ retention on the enrichers (4 days) and auto-enrich dispatch (1 day).** An outage noticed later than that loses those work items; label and artist runs can be started again from the admin enrichment pages.
- **Errors alarms treat missing data as not breaching**, so a function that is never invoked never alarms. Freshness checks (data quality, telemetry freshness, the auto-ingest run alarm) cover the scheduled paths.

# Scalability notes

CLOUDER serves a closed group of DJs: about 98k canonical tracks, 3–5k new tracks a week, a
mean ingest run of 671 tracks and a largest one of 3,656. This page says what each part does at
10× and 100× that volume, where it stops, and the next step — with measured numbers where they
exist. It deliberately describes levers, not prices.

## Summary

| Part | Today | 10× | 100× | First limit | Next step |
|---|---|---|---|---|---|
| Canonicalization worker | ≤ 1 min per run | largest week ≈ 6–9 min | largest week > 1 h | 900 s Lambda timeout | Split a run into chunks (see below) |
| Data API payloads | chunked | chunked | chunked | 1 MB result / 4 MB request | Already paged and size-bounded |
| Admin ingest (API path) | ≤ 16 s fetch | ≈ minutes | — | 29 s API Gateway limit | Use auto-ingest (900 s Lambda) or make the admin path asynchronous |
| SQS workers | unreserved | throttled by quota | throttled by quota | 10 concurrent executions (account) | Raise the quota, then turn on reserved concurrency (the Terraform switch exists) |
| Spotify / YouTube Music matching | per track | 10× calls | 100× calls | Vendor rate limits (429 → SQS retry) | SQS delay and per-worker concurrency caps |
| Duplicate-artist detection | 34.7k artists | 347k | 3.5M | Pairwise comparison | Blocking keys before comparing |
| Lakehouse (Athena) | small | linear | linear | Bytes scanned per query | Already incremental MERGE + compaction; keep date pruning |
| Aurora Serverless v2 | 0–2 ACU | raise max ACU | raise max ACU, review indexes | `aurora_serverless_max_acu = 2` | Raise the ceiling; the floor stays 0 |
| API Gateway | 100 rps stage limit | fine | raise limits | Stage throttle | Raise `throttling_rate_limit` |

## Canonicalization — measured

`scripts/bench_canonicalize.py` runs the real canonicalizer against Postgres through a Data API
stand-in and counts calls ([full table](benchmarks/canonicalization.md#scale-after-2026-10-08)):

| Week | Tracks | Data API calls | Local s |
|---|---:|---:|---:|
| 10× mean | 6,710 | 278 | 2.4 |
| 10× largest | 36,560 | 1,385 | 20.5 |
| 100× mean | 67,100 | 2,520 | 23.6 |
| 100× largest | 365,600 | 13,601 | 156.6 |

Calls grow linearly at about 38 per 1,000 tracks, so the per-entity round-trips that used to
dominate are gone. In production the batches are large and each call costs more than the
small-call model suggests: the measured rate after the set-based change is 9.9–14.8 s per
1,000 tracks. At that rate:

- **10×:** the largest week takes about 6–9 minutes — inside the 15-minute Lambda limit.
- **100×:** the largest week needs more than an hour. One message per run no longer fits.

**Next step at 100×:** split a raw run into chunks of a few thousand releases and process them
as separate SQS messages (or a Step Functions Map over the chunks, as the backfill already
does). Each chunk's upserts are independent and replay-safe, so chunks can retry on their own.

## Data API limits

The RDS Data API returns at most 1 MB per result and accepts at most 4 MB per batch request.
Reads are paged and `BatchExecuteStatement` calls are split by payload size (since the first
full backfill hit the 4 MB limit), so these limits do not grow with volume — the per-call
latency does, and the chunking above is the answer to it.

## Ingest

The slowest Beatport download today takes 16 s, inside API Gateway's 29 s limit for the admin
endpoint. At 10× the pages grow with it, so an admin-triggered ingest of a very large week
would time out at the gateway (the Lambda itself would finish). Scheduled ingest already runs
in its own Lambda with a 900 s timeout and is unaffected; the admin path would return
`202 Accepted` and hand the work to the same Lambda.

## Workers and concurrency

The AWS account allows 10 concurrent Lambda executions, and AWS keeps all 10 unreserved, so no
function can reserve capacity. Under 10× load the SQS workers (Spotify search, vendor match,
enrichment) compete for those 10 slots and back up in their queues — slower, not lossy, since
every queue has a DLQ and redrive. The next step is a quota increase to at least 35 and
`enable_lambda_reserved_concurrency = true` (per-worker values already in Terraform).

## Matching

Spotify lookup and YouTube Music matching are per track: cost grows linearly, and vendor rate
limits answer 429, which the workers turn into SQS retries. Duplicate-artist detection is the
quadratic part: comparing every artist with every other at 100× (3.5M artists) is out of the
question, so candidates would first be grouped by blocking keys — normalized name, shared
Spotify artist id, "feat." variants — and compared only within a group. Today 19 groups of
equal names exist, and they are reviewed by hand ([entity resolution](data/entity-resolution.md)).

## Lakehouse

Telemetry is small, and the dbt models are incremental (MERGE on `event_id` with a 2-day
lookback) with Iceberg compaction, so nightly cost tracks new data, not history. The Home
cards read silver history plus a 3-day bronze tail; at 100× events the main lever is keeping
queries pruned by date, which the models and the API already do.

## Lambda versions

The six API functions publish a version per code change ([ADR-0029](adr/0029-api-aliases-smoke-rollback.md)): about 25 MB each, ~150 MB per code-changing deploy, against the account's 300 GB code-storage limit (0.45 GB used on 2026-10-11) — roughly 2,000 code deploys before pruning old versions is needed.

## Aurora

Aurora Serverless v2 runs between 0 (auto-pause) and 2 ACU. At 10× the ceiling is the first
knob (`aurora_serverless_max_acu`); at 100× (about 10M tracks) the query plans of the catalog
endpoints and the triage claims (`FOR UPDATE SKIP LOCKED`) deserve a review before raising it
further.

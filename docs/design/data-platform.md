# Design: the CLOUDER data platform

How Beatport releases become a canonical, enriched catalog that DJs curate every week, and how listening telemetry becomes analytics. This is the design view; the operating details live in [`docs/data/`](../data/README.md) and [`docs/ops/`](../ops/README.md).

## Goals

- **Weekly freshness.** Every active style's closed Saturday-week ([ADR-0003](../adr/0003-saturday-week.md)) is in the catalog by the end of the following Monday, without anyone pressing a button ([ADR-0027](../adr/0027-auto-ingest.md)).
- **One canonical catalog shared by all users**, with per-user state layered on top ([ADR-0002](../adr/0002-multi-tenant-overlay.md)).
- **Replayable.** Raw data is kept, and every transformation can be re-run over it — previewed first — and converges ([ADR-0024](../adr/0024-replayable-canonicalization-backfill.md)).
- **Trustworthy.** Bad upstream records are quarantined, not loaded ([ADR-0026](../adr/0026-raw-data-contract.md)); the data itself has SLOs and alarms, not just the pipeline ([ADR-0023](../adr/0023-sql-data-quality-checks.md)).
- **Near-zero cost at rest.** A small group uses it a few hours a week: every component scales to zero.

## Non-goals

- Real-time or sub-hour freshness: releases arrive weekly.
- A general-purpose warehouse or BI tool: analytics serve the app's own cards.
- Multi-region availability: an outage of a few hours costs a delayed week, not revenue.
- Arbitrary upstream sources: the provider abstraction ([ADR-0004](../adr/0004-provider-abstraction.md)) allows them, but only Beatport ingests today.

## Architecture

```
Beatport ──▶ auto-ingest / admin ingest ──▶ S3 raw (style/year/week, kept, versioned)
                                                  │ SQS
                                                  ▼
                       contract screening ──▶ quarantine (with reasons) + drift alarm
                                                  │
                                                  ▼
                set-based canonicalization ──▶ Aurora (identity map + canonical catalog)
                                                  │ SQS fan-out
                         ┌────────────────────────┼─────────────────────────┐
                         ▼                        ▼                         ▼
               Spotify ISRC search    YouTube Music matching      LLM label / artist research
                                       (human review queue)
Aurora ──▶ nightly SQL checks (SLOs) ──▶ CloudWatch metrics + alarm
Aurora ──▶ nightly catalog export ──▶ S3 bronze ─┐
SPA telemetry ──▶ Firehose ──▶ S3 bronze ────────┴─▶ dbt on Athena ──▶ Iceberg silver / gold ──▶ analytics API
```

- **Raw zone first.** Ingest writes the untouched API response before anything else; every later step can be replayed from it. A run is a (style, Saturday-week) pair.
- **Canonicalization** screens records against the contract, normalizes them and upserts tracks, artists, albums and labels in a few set-based statements per entity type ([ADR-0022](../adr/0022-set-based-canonicalization.md)). Writes carry the observation time, so replaying an older run never overwrites newer data.
- **Enrichment** runs as independent SQS workers with DLQs, so a vendor outage delays one kind of enrichment and nothing else.
- **Runtime database access** goes only through the RDS Data API ([ADR-0001](../adr/0001-data-api-runtime.md)): no connections, pools or VPC plumbing in Lambda.
- **Lakehouse.** Telemetry lands in bronze through Firehose; a nightly dbt build makes deduplicated Iceberg tables, an SCD2 track history and a plays fact ([ADR-0025](../adr/0025-iceberg-dbt-lakehouse.md)). The analytics API reads silver history plus the last three days of bronze, so a failed build does not drop days.

## Alternatives considered

| Decision | Chosen | Alternatives | Why |
|---|---|---|---|
| Operational store | Aurora Serverless v2, PostgreSQL, Data API | DynamoDB; provisioned RDS with a driver | Relational catalog with joins and constraints; scales to zero; no connection management from Lambda. Costs: resume latency, 1 MB / 4 MB payload limits, explicit transaction ids ([postmortem](../postmortems/2026-04-15-identity-lookup-outside-transaction.md)). |
| Ingest state | Raw zone kept forever, transforms replayable | Transform in flight, keep only results | Canonicalization changed several times; replay turned each change into a previewed backfill instead of a re-download. |
| Canonical writes | Set-based upserts, one transaction per phase | Row-by-row lookups and inserts | Round-trips went from per entity to about 38 per 1,000 tracks ([scalability](../scalability.md)); concurrency-safe by `ON CONFLICT`. |
| Bad records | Contract screening with quarantine | Fail the run; schema-on-read | One malformed record must not block a week; drift must be visible the day it starts. |
| Data quality | Eleven SQL checks in a nightly Lambda | Great Expectations, Soda, dbt tests on Aurora | The checks are SQL either way; a Lambda adds no service, and the results become CloudWatch metrics with one alarm. |
| Analytics | Iceberg + dbt on Athena | Redshift Serverless; Parquet rollups by hand; DuckDB in Lambda | Pay per query, nothing running at rest, MERGE and SCD2 in SQL with tests that run on DuckDB in CI. |
| Orchestration | SQS per worker; Step Functions for backfill and the nightly build | One state machine for everything; Kafka | Workers fail independently with their own DLQs; state machines only where the order matters. |

## SLOs

From [`docs/data/data-quality.md`](../data/data-quality.md), checked every night:

| Area | Objective |
|---|---|
| Freshness | every active style's Saturday-week is in the catalog by the end of the following Monday (UTC) |
| Completeness | ISRC on ≥ 99 % and a Spotify match for ≥ 95 % of the last 30 days' tracks |
| Integrity | no orphan identity rows; no ingest run stuck without a final status |
| Plausibility | no BPM or length outside physical ranges |

## Failure modes

Each failure, the alarm that reports it, its impact and recovery: [`docs/ops/failure-modes.md`](../ops/failure-modes.md). The design choices that limit the blast radius: raw kept and versioned (any transform can be redone), one queue and DLQ per worker (a vendor outage stays local), the bronze tail in analytics (two missed builds are invisible), quarantine instead of failure (one bad record never blocks a week).

## Evolution

What changes at 10× and 100× the current volume is measured in [`docs/scalability.md`](../scalability.md). In order:

1. **Chunk large runs** (100×): the largest week would exceed the 15-minute Lambda limit; split a run into chunks processed as separate messages, as the backfill already does.
2. **Raise concurrency quotas**, then turn on the reserved-concurrency switch per worker to protect vendor rate limits.
3. **Blocking keys for duplicate-artist detection** before the pairwise comparison grows quadratically.
4. **Per-field observation times** so an out-of-order replay can never restore a value the newest observation dropped ([postmortem](../postmortems/2026-10-07-backfill-merged-tracks.md)).
5. **A `canonicalizer_version` per row**, so a backfill can target only rows written by an older version.

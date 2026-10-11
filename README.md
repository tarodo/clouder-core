# CLOUDER

**A serverless data pipeline on AWS — and the DJ curation app built on it.**

[![Deploy](https://github.com/tarodo/clouder-core/actions/workflows/deploy.yml/badge.svg)](https://github.com/tarodo/clouder-core/actions/workflows/deploy.yml)

![Curating a week of releases one keystroke per track: the 596 tracks left count down to “Bucket finished”](docs/assets/demo.gif)

*Sample data, sped up: a week of new releases cleared one keystroke per track.*

**At a glance:** ~98k canonical tracks, 3–5k new every week · 18 Lambda functions, 2 Step Functions workflows · 11 nightly data-quality SLOs · ~3,300 automated tests · every merge to `main` deploys to production.

Every week brings a new wave of electronic-music releases on Beatport. For a DJ, turning "what came out this week" into "what goes into my set" means pulling the releases, matching each track across Spotify and YouTube Music, checking labels and artists, auditioning, and sorting into playlists. CLOUDER automates the data side of that workflow and gives a small group of DJs a fast, keyboard-first app for the human side.

Under the hood it is a real data system: scheduled batch ingestion into an S3 raw zone, a canonical catalog in Aurora PostgreSQL built by entity resolution, data contracts and nightly data-quality checks, asynchronous enrichment workers, and an Iceberg lakehouse built by dbt on Athena. Everything is defined in Terraform and deployed by GitHub Actions on every merge to `main`.

> **Status:** in production for a small closed group of DJs (access goes through a Spotify allow-list), so the screenshots below are rendered from the app's components with sample data.

## Measured results

The engineering decisions behind the system and what each one bought, measured on production data.

| Decision | Result | Details |
|---|---|---|
| Set-based SQL canonicalization instead of row-by-row Data API calls | 55 calls for an average week; 9.9–14.8 s per 1,000 tracks (16–24× faster) | [benchmark](docs/benchmarks/canonicalization.md), [ADR-0022](docs/adr/0022-set-based-canonicalization.md) |
| Replay-safe writes keyed on observation time, previewed as a dry-run diff | 153 runs / 100,268 tracks replayed in 7 min 56 s; a second run changes nothing | [backfill](docs/ops/backfill.md), [ADR-0024](docs/adr/0024-replayable-canonicalization-backfill.md) |
| Iceberg silver/gold built by dbt on Athena | Aggregate query in 0.77 s (~8× faster), SCD2 track history, deduplicated events | [lakehouse](docs/data/lakehouse.md), [ADR-0025](docs/adr/0025-iceberg-dbt-lakehouse.md), [lineage](https://tarodo.github.io/clouder-core/) |
| A data contract on every raw record, with quarantine and drift alarms | Bad records never reach the catalog; on replayed history the drift alarm would have fired on 2026-09-13 | [contracts](docs/data/contracts.md), [ADR-0026](docs/adr/0026-raw-data-contract.md) |
| 11 nightly SQL data-quality checks with SLOs | The first run caught two styles lagging a week behind | [data quality](docs/data/data-quality.md), [ADR-0023](docs/adr/0023-sql-data-quality-checks.md) |
| The YouTube Music matcher measured on human decisions and a labelled sample | 100 of 100 automatic matches correct (error < ~3 % at 95 % confidence); the 0.92 threshold stays, since 0.90 would publish 27 wrong videos | [entity resolution](docs/data/entity-resolution.md) |
| Scheduled ingest (EventBridge Scheduler) with a Beatport login per run | Two styles a week behind caught up the next day (`styles_behind` 2 → 0); 45 style-weeks in the first three days, 0 failed, no manual step | [auto-ingest](docs/data/auto-ingest.md), [ADR-0027](docs/adr/0027-auto-ingest.md) |

## Architecture

```mermaid
flowchart LR
  SPA["React SPA<br/>S3 + CloudFront"] --> APIGW["API Gateway<br/>Lambda authorizer"]
  APIGW --> API["API Lambdas<br/>collector · curation · auth<br/>analytics · telemetry"]
  SCHED["EventBridge Scheduler"] --> AI["auto-ingest λ"]
  API & AI -->|"Beatport API"| RAW[("S3 raw zone")]
  API & AI --> Q[["SQS + DLQ"]]
  API & AI --> DB
  Q --> CAN["canonicalization λ<br/>contract · set-based upserts"]
  RAW --> CAN
  CAN --> DB[("Aurora PostgreSQL<br/>via RDS Data API")]
  CAN -->|SQS| ENR["enrichment workers<br/>Spotify · YouTube Music · LLM research"]
  API -->|SQS| ENR
  ENR --> DB
  BF["Step Functions backfill"] --> RAW & DB
  DQ["nightly DQ checks"] --> DB
  API -->|telemetry| FH["Kinesis Firehose"] --> BRZ[("S3 bronze")]
  DB -->|nightly export| BRZ
  BRZ --> DBT["Step Functions + CodeBuild<br/>dbt build"] --> SIL[("Iceberg silver / gold")]
  SIL & BRZ --> ATH["Athena"] --> API
```

The full diagram and the list of all 18 Lambda functions are in [`docs/architecture.md`](docs/architecture.md); [`docs/engineering-highlights.md`](docs/engineering-highlights.md) points to the code worth reading first. Key decisions (all 29 in [`docs/adr/`](docs/adr/README.md)):

| Decision | Why | ADR |
|---|---|---|
| RDS Data API instead of a DB driver in Lambda | Survives Aurora auto-pause; no connection pooling; most functions need no VPC | [0001](docs/adr/0001-data-api-runtime.md) |
| Shared canonical catalog + per-user overlay | One ingest serves every user; curation state stays private | [0002](docs/adr/0002-multi-tenant-overlay.md) |
| Provider abstraction behind `VENDORS_ENABLED` | Add or disable a music vendor without touching pipeline code | [0004](docs/adr/0004-provider-abstraction.md) |
| Aurora Serverless v2 with `min_acu = 0` | Pauses when idle; the cold-start trade-off is documented with a mitigation | [0014](docs/adr/0014-aurora-min-acu-zero.md) |
| Plain SQL checks + CloudWatch, not a DQ framework | Eleven checks did not justify a framework's dependencies | [0023](docs/adr/0023-sql-data-quality-checks.md) |
| Iceberg + dbt only where live queries fell short | Deduplication, history and small files were real problems | [0025](docs/adr/0025-iceberg-dbt-lakehouse.md) |
| Login per run for scheduled ingest | No long-lived Beatport token stored anywhere | [0027](docs/adr/0027-auto-ingest.md) |

### Where the data lives

```text
s3://<raw-bucket>/                      versioned; old versions move to Glacier IR and never expire
  raw/bp/releases/
    style_id=<id>/year=<yyyy>/week=<ww>/
      releases.json.gz                  the untouched Beatport response; every step replays from here
      meta.json                         run metadata
    _quarantine/run_id=<run>/           records that failed the data contract, with reasons
  covers/<user_id>/                     playlist covers (presigned uploads)

s3://<analytics-lake>/
  bronze/events/dt=<date>/event_name=<name>/         Firehose → Parquet, Glue partition projection
  bronze/catalog_export/snapshot_dt=<date>/<table>/  nightly catalog snapshot (14 days)
  lakehouse/                                         Iceberg silver/gold, built by dbt on Athena
  governance/deleted_users/                          erasure tombstones (see docs/privacy.md)
```

Aurora PostgreSQL holds the operational model: source entities → identity map
(`source × entity_type × external_id → canonical id`) → canonical catalog → per-user overlay.

## What this project demonstrates

**Data engineering**
- Partitioned raw zone on S3 with run metadata and a run state machine; replay-safe, idempotent reprocessing from raw with a dry-run diff.
- Canonicalization through an identity map (`source × entity_type × external_id → canonical id`), set-based upserts sized to the Data API limits.
- Cross-vendor entity resolution: ISRC matching, metadata fallback, fuzzy scoring, a human review queue, and measured precision.
- Data contracts with record-level quarantine and drift alarms; nightly data-quality checks with SLOs.
- An event lakehouse: schema-validated telemetry → Firehose → Parquet bronze → dbt (incremental MERGE, SCD2) → Iceberg silver/gold on Athena, with unit and data tests and published lineage.

**Cloud & infrastructure**
- 18 AWS Lambda functions, 7 SQS work queues each with a dead-letter queue, 2 Step Functions state machines, EventBridge Scheduler, Aurora Serverless v2, S3, Kinesis Data Firehose, Glue, Athena, CodeBuild, API Gateway, CloudFront, KMS, SSM — 239 Terraform resource definitions.
- GitHub Actions with OIDC (no long-lived AWS keys), path-filtered PR checks, and a two-phase deploy that lands DB migrations before API code.
- A least-privilege IAM role per Lambda; API Gateway throttling and JSON access logs; Aurora deletion protection with 7-day backups; error alarms on every function, routed to email through SNS.

**Software engineering**
- About 3,300 automated tests: ~2,090 backend (including a suite against a real PostgreSQL 16), ~1,230 frontend (unit and real-browser layout tests), plus dbt unit and data tests.
- CI gates on every PR: ruff and mypy, an 80 % coverage floor, locked Python dependencies with pip-audit, a runtime `pnpm audit`, a route-consistency check (Terraform ↔ OpenAPI ↔ handler code); Dependabot for pip, npm, Actions and Terraform.
- 29 Architecture Decision Records, an incident runbook, and per-role documentation that is checked by tests (links, Lambda inventory, removed components).

## AWS services

| Service | How it is used |
|---|---|
| **Lambda** (Python 3.12) | 18 functions: API handlers and a JWT authorizer, SQS workers, scheduled jobs, backfill steps, DB migrations |
| **API Gateway** (HTTP API) | 106 operations; everything except the auth routes (`/auth/login`, `/auth/callback`, `/auth/refresh`, `/auth/logout`) goes through a Lambda authorizer |
| **SQS** | 7 work queues, each with a dead-letter queue and redrive policy |
| **Step Functions** | Backfill (plan → map over runs → summarize → DQ check) and the nightly dbt transform |
| **EventBridge / Scheduler** | Nightly catalog export and data-quality checks; daily auto-ingest planning with one-time run schedules |
| **S3** | Versioned raw zone with a quarantine prefix; analytics lake; SPA hosting |
| **Aurora PostgreSQL Serverless v2** | Canonical catalog and user data via the RDS Data API; auto-pause |
| **Kinesis Data Firehose** | Telemetry ingest with JSON → Parquet conversion and dynamic partitioning |
| **Glue Data Catalog + Athena** | Bronze tables with partition projection; Iceberg silver/gold; per-user analytics |
| **CodeBuild** | Runs `dbt build` for the nightly transform |
| **CloudWatch + SNS** | Structured JSON logs, API access logs, log metric filters, alarms on every function's errors and on data/pipeline health, email notifications |
| **KMS / SSM / Secrets Manager** | Envelope encryption of users' OAuth tokens; vendor credentials; Aurora credentials |
| **CloudFront** | SPA delivery with Origin Access Control |
| **IAM** | A least-privilege execution role per Lambda (its own log group and only what its code uses); GitHub OIDC deploy role |

**Deliberately not used:** Redshift, EMR/Spark, Kinesis Data Streams/MSK, ECS/EKS, Glue ETL jobs. At ~100k tracks and a few hundred events a day they would add cost and moving parts without solving a problem this system has; where an alternative was weighed, the trade-off is recorded — Redshift Serverless and Kafka in [`docs/design/data-platform.md`](docs/design/data-platform.md#alternatives-considered), Glue ETL and Spark in [ADR-0025](docs/adr/0025-iceberg-dbt-lakehouse.md) — and [`docs/scalability.md`](docs/scalability.md) says what changes at 10× and 100×.

## Data pipeline

1. **Ingest.** The auto-ingest Lambda runs at times set in the admin (fixed, or N random per day). It logs in to Beatport, picks the due Saturday-week of every visible style first and then backfills missing weeks evenly, and for each one writes `releases.json.gz` + `meta.json` to the S3 raw zone, records an `ingest_runs` row and enqueues canonicalization. An admin can run the same path on demand.
2. **Screen and canonicalize.** An SQS worker screens every raw record against the data contract (failures go to quarantine with reasons, drift raises an alarm), normalizes it into typed entities and upserts them set-based. Writes use the observation time, so replaying an older run never overwrites newer data.
3. **Enrich.** Workers look tracks up on Spotify (ISRC, then metadata), match them to YouTube Music with fuzzy scoring and a review queue, and research labels and artists across several LLM and search vendors.
4. **Curate.** Users triage the week's tracks with one keystroke per destination; categories, tags and playlists form a private overlay on the shared catalog and can be published to Spotify or YouTube Music.
5. **Check.** Every night eleven SQL checks measure freshness, volume, completeness, integrity and plausibility and publish CloudWatch metrics with an alarm.
6. **Analyze.** Telemetry flows through Firehose into the bronze lake; a nightly export snapshots catalog dimensions; a nightly dbt build turns both into Iceberg silver/gold, which the analytics API reads together with the live bronze tail.
7. **Reprocess.** When canonicalization changes, the backfill state machine replays stored raw runs — first as a dry run that reports what would change, then for real.

**When something fails.** Each worker has its own queue and dead-letter queue, so a vendor outage delays one kind of enrichment and nothing else. Bad upstream records go to quarantine instead of failing the run. A failed nightly dbt build leaves the analytics cards correct for two more nights, because they read the last three days straight from bronze. Every failure mode, its alarm and its recovery are listed in [`docs/ops/failure-modes.md`](docs/ops/failure-modes.md).

## Screenshots

Rendered from the app's React components with sample data (`cd frontend && pnpm screenshots`); the live app is behind a Spotify allow-list.

**Curate** — one keystroke per destination:

![Curate view](docs/assets/curate.png)

**Triage** — the week's tracks split into buckets:

![Triage buckets](docs/assets/triage.png)

**Admin** — ingest coverage by style × week and the auto-ingest schedule:

![Coverage and auto-ingest](docs/assets/coverage.png)

**Analytics** — listening, curation funnel and time per track:

![Analytics cards](docs/assets/analytics.png)

**Operations** — production, last 7 days, from the CloudWatch dashboard defined in Terraform ([`infra/dashboard.tf`](infra/dashboard.tf); refresh with `scripts/dashboard_snapshots.py`). Aurora scales to zero between sessions, and with a handful of requests per window the p95 shows the first request after a resume — the price of `min_acu = 0` ([ADR-0014](docs/adr/0014-aurora-min-acu-zero.md)):

![Lambda errors](docs/assets/dashboard-lambda-errors.png)
![API latency p95](docs/assets/dashboard-api-latency-p95.png)
![Aurora capacity](docs/assets/dashboard-aurora-capacity.png)

Data quality is charted next to the pipeline: one point per nightly check run against its SLO line ([data-quality.md](docs/data/data-quality.md)):

![Data quality: completeness](docs/assets/dashboard-data-quality-completeness.png)

## By the numbers

| | |
|---|---|
| Canonical catalog | ~98k canonical tracks (2026-10-07), from 107,795 raw records |
| Spotify match rate | 96.85 % of recent tracks (nightly data-quality check) |
| Lambda invocations | 156k in 30 days (2026-09-08 → 10-08), 0.016 % errors |
| Infrastructure | 18 Lambda functions · 7 SQS queues + DLQs · 2 state machines · 239 Terraform resource definitions |
| API | 106 operations |
| Delivery | 265+ merged pull requests; every merge to `main` deploys to production |

## Production readiness

- **Delivery.** `main` accepts changes only through pull requests with 8 required checks (tests with an 80 % coverage gate, ruff and mypy, dependency audit, real-PostgreSQL tests, Terraform, dbt, frontend). Pull requests plan Terraform under a read-only AWS role and see the same inputs the deploy applies; every merge deploys through GitHub Actions with OIDC — no long-lived AWS keys — and migrations land before the code that needs them ([ADR-0028](docs/adr/0028-ci-roles.md)). A smoke test gates each deploy and, if it fails, points the API Lambdas back to their previous versions ([ADR-0029](docs/adr/0029-api-aliases-smoke-rollback.md)).
- **Reliability.** A dead-letter queue on every work queue; permanent and transient errors handled differently; replay-safe writes; Aurora deletion protection with 7-day point-in-time recovery; [failure modes](docs/ops/failure-modes.md) with RPO/RTO; five blameless [postmortems](docs/postmortems/README.md).
- **Observability.** Error alarms on every Lambda function plus pipeline and data-health alarms, all routed to email through SNS; a CloudWatch dashboard defined in Terraform; structured JSON logs with correlation ids; API access logs.
- **Data governance.** A data contract on every raw record; nightly data-quality SLOs; documented retention; one command erases a user from Aurora, S3 and the Iceberg tables ([privacy](docs/privacy.md)).
- **Security.** A least-privilege role per Lambda; KMS envelope encryption of users' OAuth tokens; PKCE and refresh-token rotation with replay detection; a log-field allow-list; CloudFront security headers; a written [threat model](docs/security.md) with known gaps.
- **Cost guardrails.** Aurora scales to zero when idle, Athena queries have a scan limit, and cold data moves to cheaper storage on a lifecycle; a monthly budget alert is defined in Terraform and switches on with one secret.

## Running it locally

**Try the pipeline without AWS.** `make local-db && make demo` starts PostgreSQL in Docker, migrates it and pushes one synthetic Beatport week (300 tracks plus two malformed records) through the production code — contract screening, set-based canonicalization, the nightly data-quality checks — then replays the week to show it changes nothing. The Data API is replaced by a psycopg stand-in with the same transaction visibility. Output, trimmed:

```json
{"screen": {"valid": 300, "quarantined": 2},
 "first_run": {"tracks_created": 300, "artists_created": 157, "albums_created": 119, "labels_created": 40},
 "second_run": {"tracks_created": 0, "tracks_changed": 0, "artists_created": 0},
 "checks": [{"name": "stuck_ingest_runs", "value": 0.0, "passed": true}, ...]}
```

`make help` lists the other shortcuts (`make test`, `make test-db`, `make lint`, `make typecheck`, `make cov`, `make lock`, …); the raw commands:

```bash
# Backend tests (dependencies are locked: requirements-*.in → requirements-*.txt)
python -m pip install -r requirements-dev.txt
pytest -q

# Tests against a real PostgreSQL (migrate the schema first)
docker compose up -d --wait db   # Postgres 16 on localhost:55433
PYTHONPATH=src ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55433/postgres \
  alembic upgrade head
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres pytest tests/db -q

# Frontend (pnpm test:browser for the real-browser layout tests)
(cd frontend && pnpm install && pnpm test)

# dbt on DuckDB with fixtures
(cd dbt && pip install -r requirements.txt && export DBT_PROFILES_DIR=. \
  && dbt seed --target ci && dbt run --target ci --empty && dbt build --target ci --full-refresh --exclude resource_type:seed)
```

Deployment runs only through GitHub Actions ([`docs/ops/deploy.md`](docs/ops/deploy.md)).

## Repository layout

| Path | Contents |
|---|---|
| `src/collector/` | Lambda handlers, providers, data-access layer, pipeline logic |
| `frontend/` | Vite + React 19 + Mantine SPA |
| `infra/` | Terraform for every AWS resource |
| `dbt/` | Lakehouse models (Athena in prod, DuckDB in CI) |
| `alembic/` | Database migrations |
| `tests/` | Unit, integration and real-PostgreSQL tests |
| `docs/` | Architecture, ADRs, data, backend, frontend and ops guides |
| `experiments/` | Isolated sandboxes whose results fed production decisions |
| `CLAUDE.md`, `graphify-out/`, `docs/superpowers/` | AI-agent context: working instructions, a generated code graph, and the specs and plans behind each change (see *How this was built*) |

## Known limitations & next steps

- One production environment; changes are verified by CI, local real-PostgreSQL tests and dry runs rather than a staging stack.
- Throughput limits are measured, not guessed: canonicalization fits a 10× week easily and reaches the Lambda timeout around 100× the largest week — see [scalability notes](docs/scalability.md).
- Matching precision is measured for YouTube Music only. Next: a labelled sample for Spotify.
- Built for a closed group of DJs: about 98k tracks, growing by 3–5k a week.

## How this was built

I designed, built and operate CLOUDER end to end — product, data model, backend, frontend, infrastructure and on-call. Development is AI-assisted: I use coding agents for implementation and keep design decisions in ADRs, changes in reviewed pull requests with CI gates, and specifications and plans in [`docs/superpowers/`](docs/superpowers/). Every merge to `main` deploys to production.

## License

Source-available, all rights reserved — see [LICENSE](LICENSE).

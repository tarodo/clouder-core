# CLOUDER Architecture

CLOUDER is a multi-tenant SaaS for DJs. A shared canonical music catalogue is fed by a serverless ingest pipeline; per-user overlays (playlists, tags, curation state) sit on top. The user-facing surface is a React SPA that talks to a single API Gateway endpoint.

## System overview

```mermaid
flowchart LR
    subgraph SPA["React SPA (Vite + Mantine 9)"]
        UI[UI: triage, curate, categories, player]
    end

    subgraph API["AWS HTTP API Gateway"]
        APIGW[API Gateway routes]
    end

    subgraph Lambdas["AWS Lambdas"]
        AH["auth-handler"]
        CH["collector-api (API Lambda)"]
        SH["ai-search-worker"]
        SPW["spotify-search-worker"]
        VMW["vendor-match-worker"]
        WH["canonicalization-worker (Worker Lambda)"]
        MH["migration"]
        BF["backfill (Step Functions task)"]
    end

    subgraph Lakehouse["Analytics lakehouse"]
        DBT["dbt build (CodeBuild, nightly)"]
        SIL[(Iceberg silver / gold)]
    end

    subgraph Storage
        S3[(S3 raw/bp/releases/*)]
        SQS[(SQS canonicalization queue + DLQ)]
        Aurora[(Aurora PostgreSQL Serverless v2)]
    end

    subgraph Vendors
        BP[[Beatport API]]
        SP[[Spotify Web API + Web Playback SDK]]
        PX[[Perplexity API]]
    end

    UI <--> APIGW
    APIGW --> AH
    APIGW --> CH
    AH <--> Aurora
    AH <--> SP
    CH --> BP
    CH --> S3
    CH --> SQS
    SQS --> WH
    WH --> S3
    WH --> Aurora
    SH <--> PX
    SH <--> Aurora
    SPW <--> SP
    SPW <--> Aurora
    VMW <--> SP
    VMW <--> Aurora
    MH --> Aurora
    BF --> S3
    BF --> Aurora
    DBT --> SIL
    UI <--> SP
```

## Subsystems

- **Ingest.** API Lambda fetches a Beatport weekly snapshot, writes `releases.json.gz + meta.json` to S3, enqueues a canonicalization job, and records an `ingest_runs` row. See [`docs/data/raw-ingestion.md`](data/raw-ingestion.md). The auto-ingest Lambda runs the same path on an EventBridge Scheduler plan set in the admin: it logs in to Beatport per run and ingests the due week of every visible style, then backfills. See [`docs/data/auto-ingest.md`](data/auto-ingest.md).
- **Canonicalization.** SQS-triggered worker reads the raw snapshot, normalises tracks / artists / albums / labels, and upserts canonical entities into Aurora via the RDS Data API. See [`docs/data/canonicalization.md`](data/canonicalization.md). Stored raw runs can be replayed — previewed first as a dry run — by the backfill state machine. See [`docs/ops/backfill.md`](ops/backfill.md).
- **Search and enrichment.** Per-track ISRC lookup against Spotify, plus a metadata-fallback path for misses. Perplexity is used to flag AI-suspected labels and artists. Results are cached in vendor-match tables. See [`docs/data/search-and-enrichment.md`](data/search-and-enrichment.md).
- **Curation.** The SPA's tap-to-assign UX assigns tracks from triage buckets into per-user playlists. Optimistic shrink keeps the cursor stable. See [`docs/frontend/features.md`](frontend/features.md) and ADR-0010, ADR-0012.
- **Playback.** Spotify Web Playback SDK is lazy-loaded on the first play. The CLOUDER auth refresh stream bundles a Spotify access token; the SPA keeps it in memory only. See [`docs/frontend/playback.md`](frontend/playback.md) and ADR-0011, ADR-0013.
- **Analytics lakehouse.** Telemetry lands in bronze through Firehose; a nightly dbt build on Athena turns it and the catalog snapshots into Iceberg silver/gold (deduplicated events, SCD2 track history, plays). The Home cards read silver history plus the live bronze tail. See [`docs/data/lakehouse.md`](data/lakehouse.md).
- **Operations.** Aurora Serverless v2 with `min_acu=0` (auto-pause). Migrations run via a dedicated Lambda. See [`docs/ops/aurora.md`](ops/aurora.md) and [`docs/ops/deploy.md`](ops/deploy.md).

## Where to read next

- New backend contributor → [`docs/backend/README.md`](backend/README.md).
- New data engineer → [`docs/data/README.md`](data/README.md).
- New frontend contributor → [`docs/frontend/README.md`](frontend/README.md).
- Ops / on-call → [`docs/ops/runbook.md`](ops/runbook.md).
- Why-this-way questions → [`docs/adr/README.md`](adr/README.md).

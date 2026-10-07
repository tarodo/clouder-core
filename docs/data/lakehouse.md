# Lakehouse: silver and gold on Iceberg, built by dbt

Status: deployed with this change; "After" is filled from the first production builds.

## Why

The analytics lake had only a bronze layer. Every Home-card request re-read the whole event
history from small Firehose files; nothing deduplicated an at-least-once delivery; the catalog's
history disappeared after the 14-day snapshot expiry; and every transformation was a SQL string
inside Lambda code — no lineage, no data tests, no docs.

A silver/gold layer on Iceberg, built and tested by dbt, fixes each of these without touching
Aurora or the ingest path.

## Before (2026-10-07)

| | |
|---|---|
| Bronze events | 19,647 events in 1,243 Parquet files, 6.2 MB (median file 4.7 KB) over 38 days — Firehose writes a file per buffer, per event type, per day |
| Duplicates | 0 duplicate `event_id` — delivery is at-least-once, none observed yet, and nothing would remove one |
| Cost of small files | a full-table aggregate scans 555 KB yet takes 7.0 s of engine time |
| Home cards (`analytics-api`, 30 days) | 45 calls, p50 4.1 s, p90 5.6 s, max 6.2 s — each call re-reads all history from bronze |
| Catalog history | nightly full snapshots (1,198 objects, 154 MB) expire after 14 days; no track history beyond that |
| Transformations | SQL strings in Lambda code: no lineage, no data tests, no docs |

## What changed

```
bronze_events ──▶ stg_events ──▶ silver.events ─────────────────────▶ gold.fct_play
                                 (Iceberg, MERGE on event_id,              ▲
                                  dedup, lookback, OPTIMIZE/VACUUM)        │ style as of the play
bronze_catalog_export ──▶ silver.dim_track_history ────────────────────────┘
                          (SCD2, dated by snapshot, incremental)
```

**dbt project (`dbt/`).** Two targets: `prod` — dbt-athena writing Iceberg tables into the Glue
databases `clouder_silver` and `clouder_gold` (data under `s3://…-analytics-lake/lakehouse/`);
`ci` — dbt-duckdb, where seed fixtures stand in for the bronze tables. Dialect differences live in
three macros (`parse_utc_ts`, `dt_minus_days`, `hash_text`).

**`silver.events`.** Incremental MERGE on `event_id`. Each run re-reads bronze partitions from
`max(dt) − 2 days` (late arrivals and redeliveries land there) and keeps the earliest copy of
every `event_id`. Partitioned by `dt`, compacted by `OPTIMIZE … REWRITE DATA USING BIN_PACK`
and cleaned by `VACUUM` after each build.

**`silver.dim_track_history`.** SCD2 of a track's catalog attributes (title, BPM, key, publish
date, album, style, ISRC, release type, AI flag, Spotify release date). A version is dated by
the snapshot that first showed it. Each run folds every retained snapshot newer than the latest
version into the open versions (gaps-and-islands on a row hash): a missed night catches up, a
repeated snapshot changes nothing, and history outlives the 14-day snapshot expiry. The first
build starts history from the oldest retained snapshot.

**`gold.fct_play`.** One row per play — the analytics Lambda's rule (playing stretches capped at
the track's duration, 10-minute fallback) — with the track's style as of the play date; plays
before history starts take the earliest known version.

**Tests.** dbt unit tests (dedup, lookback window, SCD2 first build / incremental fold / no-op
rerun / revert, play capping, point-in-time style), data tests (`unique`, `not_null`,
`accepted_values`, one open version per track, non-overlapping versions) and source freshness.
CI runs them on DuckDB for every change under `dbt/` and parses the Athena target.

**Nightly build.** `clouder-prod-transform` (Step Functions) starts the `clouder-prod-dbt`
CodeBuild project at 00:30 UTC — after the catalog export (00:00) and the data-quality checks
(00:10). CodeBuild clones `main`, installs the pinned dbt versions and runs `dbt build` (unit
tests stay in CI) and `dbt source freshness`. One retry; a failure ends the execution failed and
raises `clouder-prod-transform-failed`.

**Hot/cold read path.** The analytics Lambda reads events as one relation: history before
yesterday from `clouder_silver.events`, yesterday and today from `bronze_events` — each `dt`
from exactly one side (`SILVER_EVENTS_TABLE`; unset = bronze only).

**Docs and lineage.** On every push to `main` under `dbt/`, CI builds the fixtures and publishes
the dbt docs (models, columns, tests, lineage graph) to GitHub Pages:
<https://tarodo.github.io/clouder-core/>. They contain no production data.

## How to run

```bash
SM=$(cd infra && terraform output -raw transform_state_machine_arn)
aws stepfunctions start-execution --state-machine-arn "$SM" --name "manual-$(date +%Y%m%d-%H%M)"
aws logs tail /aws/codebuild/clouder-prod-dbt --since 30m      # model timings, test results

cd dbt && export DBT_PROFILES_DIR=.                              # local, on DuckDB fixtures
dbt seed --target ci && dbt run --target ci --empty && dbt build --target ci --full-refresh
```

A full rebuild of one model in production: start a CodeBuild build of `clouder-prod-dbt` with the
build command overridden to `dbt build --target prod --full-refresh --select <model>`. Rebuilding
`dim_track_history` restarts its history from the retained snapshots (14 days).

## After

Filled from the first production builds.

| | Before | After |
|---|---|---|
| Files behind the events history | 1,243 | pending |
| Full-table aggregate, engine time | 7.0 s | pending |
| Duplicate events removed | — | pending |
| Track versions after the first build | — | pending |
| dbt build time, first (full) / nightly (incremental) | — | pending |
| Home cards p50 / p90 | 4.1 s / 5.6 s | pending |

## What it buys

- History is read from a handful of compacted files instead of one per Firehose buffer; the
  cards scan bronze only for the last two days.
- Exactly one row per event whatever the delivery does, with a test that fails if not.
- Track history (style, BPM, release type, …) accumulates beyond the snapshot window, so "what
  was this track when it was played" has an answer.
- Every transformation has lineage, column docs and tests, reviewed on every change in CI.
- Iceberg makes row-level `DELETE` possible for removing a user's events.

## Not done, and why

- **Incremental (watermark) catalog export.** Snapshots are small and the SCD2 model is already
  incremental over them.
- **Marts nobody reads.** Earlier marts were removed for exactly that reason; `fct_play` is the
  only gold model, kept because it carries the point-in-time style.
- **Time-per-track on `dim_track_history`.** It still joins the latest snapshot; a follow-up.
- **Airflow / MWAA, Glue ETL, Spark.** A nightly `dbt build` over a few megabytes needs one
  CodeBuild job.

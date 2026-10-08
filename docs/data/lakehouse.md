# Lakehouse: silver and gold on Iceberg, built by dbt

Status: deployed; measured on production on 2026-10-07 (card latency pending real traffic).

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
`max(dt) − 2 days` (late arrivals land there) and adds only events silver does not hold yet, so
every `event_id` keeps its earliest copy — also when Firehose redelivers it later. A malformed
client timestamp parses to NULL instead of failing the build. Partitioned by `dt`, compacted by `OPTIMIZE … REWRITE DATA USING BIN_PACK`
and cleaned by `VACUUM` after each build.

**`silver.dim_track_history`.** SCD2 of a track's catalog attributes (title, BPM, key, publish
date, album, style, ISRC, release type, AI flag, Spotify release date). A version is dated by
the snapshot that first showed it. Each run folds every retained snapshot newer than the latest
version into the open versions (gaps-and-islands on a row hash): a missed night catches up, a
repeated snapshot changes nothing, and history outlives the 14-day snapshot expiry. The first
build starts history from the oldest retained snapshot.

**Deleted users.** `stg_events` drops every user listed in `clouder_analytics.deleted_users`
(tombstones written by `scripts/delete_user.py`), so silver and gold never rebuild a deleted
user's events; the data test `assert_deleted_users_absent` checks it on every build. See
[`docs/privacy.md`](../privacy.md).

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
puts `clouder-prod-transform-failed` into ALARM (it emails the owner through the alarm topic,
like every alarm here).

**Hot/cold read path.** The analytics Lambda reads events as one relation: history older than
three days from `clouder_silver.events`, the last three days from `bronze_events` — each `dt`
from exactly one side. Three days cover the build's lookback and two missed nightly builds, so a
failing build does not drop days from the cards. It is switched on by the Terraform variable
`silver_events_table` (empty = bronze only), set in `.github/workflows/deploy.yml` after the
first green build (2026-10-07); removing that `-var` is the rollback.

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
build command overridden to `dbt build --target prod --full-refresh --select <model>`. A full
refresh drops and recreates the table, so clear `silver_events_table` first when rebuilding
`events`. Rebuilding `dim_track_history` restarts its history from the retained snapshots (14
days).

## After (production, 2026-10-07)

| | Before | After |
|---|---|---|
| Files behind the events history | 1,243 | 38 (one per `dt` partition, compacted) |
| Full-table aggregate, engine time | 6.1–7.0 s | 0.77 s on `clouder_silver.events` |
| The hot/cold relation the cards read, whole history | — | 1.8 s (silver history + three days of bronze) |
| Duplicate events | none removed | 0 of 19,647 — none delivered yet; the `unique` test guards it |
| Track history | lost after 14 days | 97,976 versions for 97,973 tracks from the first build (history starts at the oldest retained snapshot, 2026-10-06; 3 tracks changed on 2026-10-07) |
| Nightly build | — | 21/21 models and tests; dbt 46 s, 1 min 54 s with installation |
| Home cards p50 / p90 | 4.1 s / 5.6 s | pending real traffic |

The first production builds found what DuckDB in CI cannot show: dbt-athena needs
`glue:CreateDatabase` for its `CREATE SCHEMA IF NOT EXISTS`, and Athena stores views as Hive
views, which reject `timestamp(6)` while Iceberg tables accept only it. Both were fixed before
the cards were switched to silver.

## What it buys

- History is read from a handful of compacted files instead of one per Firehose buffer; the
  cards scan bronze only for the last three days.
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

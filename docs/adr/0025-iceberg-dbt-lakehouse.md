# ADR-0025: Iceberg silver/gold built by dbt on Athena
Status: Accepted
Date: 2026-10-07

## Context

The analytics lake had only bronze: 1,243 small Firehose files (median 4.7 KB) over 38 days,
re-read in full by every Home-card request (p50 4.1 s, p90 5.6 s); at-least-once delivery with
nothing deduplicating (0 duplicates observed so far); catalog snapshots expiring after 14 days,
so track history was lost; transformation SQL embedded in Lambda code without lineage or tests.

An earlier rollup/marts layer had been removed because nothing read it. This layer has readers:
the Home cards read silver history, and the SCD2 history exists nowhere else. The owner chose
the full scope (Iceberg + dbt) on 2026-10-07.

Options considered:
- **Status quo** — cheap, but the costs above stay.
- **Athena CTAS/MERGE from a Lambda** — no new runtime, but tests, lineage and docs would be
  hand-built.
- **dbt-athena + Iceberg** — incremental models, unit/data tests, freshness, generated docs
  with lineage; Iceberg gives MERGE, compaction, row-level DELETE and time travel on Athena.
- **Glue ETL / Spark** — built for volumes thousands of times larger than 6 MB.

## Decision

- dbt project in `dbt/`: `prod` target on Athena (Iceberg tables in Glue databases
  `clouder_silver` and `clouder_gold`), `ci` target on DuckDB with seed fixtures for bronze.
- `silver.events`: incremental MERGE on `event_id` over a two-day lookback, deduplicated,
  partitioned by `dt`, `OPTIMIZE`/`VACUUM` after each build.
- `silver.dim_track_history`: SCD2 dated by snapshot, folding every newer retained snapshot into
  the open versions on each run.
- `gold.fct_play`: plays with the track's style as of the play date.
- Nightly at 00:30 UTC: Step Functions → CodeBuild `dbt build` (one retry, alarm on failure).
  Unit tests run in CI, not in production builds.
- The analytics Lambda reads history from silver and the last two days from bronze.
- dbt docs with lineage publish to GitHub Pages from CI fixtures.

## Consequences

- A second runtime (dbt in CodeBuild) with pinned versions in `dbt/requirements.txt`; the
  collector Lambda bundle is unchanged.
- Silver is nightly; the cards stay live through the bronze tail. If a nightly build fails, the
  day that should have moved to silver is missing from the cards until the next successful
  build (the alarm fires); the lookback catches it up.
- Athena-specific SQL is only proven by `dbt parse --target prod` in CI and the first production
  build; DuckDB covers logic, not dialect.
- `VACUUM` keeps the default snapshot window, so Iceberg time travel covers the last days.
- Iceberg row-level `DELETE` makes removing one user's events possible (privacy work, G).

**Cross-references:** ADR-0001, ADR-0023, ADR-0024, `docs/data/lakehouse.md`, `dbt/README.md`.

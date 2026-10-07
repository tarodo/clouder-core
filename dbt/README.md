# dbt: analytics silver and gold

Models over the analytics lake, built on Athena (Iceberg) every night and tested on DuckDB in CI.
Why and how it fits: [`docs/data/lakehouse.md`](../docs/data/lakehouse.md), ADR-0025.

## Layout

| Path | What |
|---|---|
| `models/sources.yml` | bronze Glue tables (`clouder_analytics.bronze_events`, `bronze_catalog_export`) |
| `models/staging/stg_events.sql` | typed view over bronze events |
| `models/silver/events.sql` | deduplicated events, incremental MERGE, Iceberg |
| `models/silver/dim_track_history.sql` | SCD2 of track attributes from catalog snapshots |
| `models/gold/fct_play.sql` | plays with the track's style as of the play |
| `macros/dialect.sql` | the SQL fragments that differ between Athena and DuckDB |
| `seeds/fixtures/` | CSV stand-ins for the bronze tables, enabled on DuckDB only |
| `tests/` | singular data tests (SCD2 invariants) |

Unit tests live next to the models (`_silver.yml`, `_gold.yml`).

## Targets

- `ci` (default) — DuckDB file `target/ci.duckdb`; seeds stand in for bronze.
- `prod` — Athena workgroup `beatport-prod-analytics`, data under `s3://clouder-prod-analytics-lake/lakehouse/`. Runs in CodeBuild (`clouder-prod-dbt`), not from laptops.

## Commands

```bash
cd dbt && export DBT_PROFILES_DIR=.
pip install -r requirements.txt

dbt seed --target ci                    # fixtures
dbt run --target ci --empty             # unit tests read the columns of `this`
dbt build --target ci --full-refresh    # models + unit tests + data tests
dbt parse --target prod                 # Athena configs compile (no connection)
dbt docs generate --target ci --static  # target/static_index.html
```

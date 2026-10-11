# Lakehouse Layer (Iceberg + dbt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a tested, documented silver/gold layer to the analytics lake — Iceberg tables built nightly by dbt on Athena — and serve the Home analytics cards from the compacted silver history plus live bronze for the last day.

**Architecture:** A dbt project (`dbt/`) with two targets: `prod` (dbt-athena: Iceberg tables in Glue databases `clouder_silver` / `clouder_gold`) and `ci` (dbt-duckdb with seed fixtures, where dbt unit and data tests run on every PR). Models: `stg_events` (typed view over `bronze_events`), `silver.events` (incremental MERGE on `event_id`: deduplication, late arrivals through a lookback window, OPTIMIZE + VACUUM), `silver.dim_track_history` (SCD2 from the nightly catalog snapshots, incremental, event-dated validity), `gold.fct_play` (one row per play with the track's style as of the play). A CodeBuild project runs `dbt build`, started nightly at 00:30 UTC by a `clouder-prod-transform` Step Functions state machine (retry, alarm on failure). The analytics Lambda reads history from `clouder_silver.events` and the last day from bronze. dbt docs (lineage) publish to GitHub Pages.

**Tech Stack:** dbt-core 1.11, dbt-athena 1.11.1, dbt-duckdb 1.11.0, Apache Iceberg on Athena engine v3 + Glue Data Catalog, AWS CodeBuild, Step Functions, EventBridge, CloudWatch, Terraform, GitHub Actions + Pages, Python 3.12, DuckDB (tests).

**Spec:** inline — "Spec" section below (source: hiring audit §15.3 "E", scope chosen by the owner on 2026-10-07: "full Iceberg + dbt").

## Global Constraints

- Aurora is not touched by this layer; it reads the lake only (`bronze_events`, `bronze_catalog_export`).
- dbt never runs inside a Lambda; production dbt runs in CodeBuild; the collector Lambda zip does not change size.
- Athena gotcha (#13): date literals are inlined after validation, never bound as `ExecutionParameters`; binding `user_id` stays.
- Event ordering by `ts_client` + `event_id`, never `ts_server` (CLAUDE.md #13).
- Pinned versions: `dbt-core~=1.11.0`, `dbt-athena==1.11.1`, `dbt-duckdb==1.11.0` in `dbt/requirements.txt` only (not in `requirements*.txt` of the collector).
- Glue databases `clouder_silver`, `clouder_gold`; table data under `s3://clouder-prod-analytics-lake/lakehouse/`; dbt query results under `athena-results/dbt/` (expires with the existing 7-day rule).
- Least privilege: CodeBuild role (logs, Athena on the workgroup, Glue read on `clouder_analytics` and read/write on `clouder_silver`/`clouder_gold`, S3 read `bronze/*`, read/write `lakehouse/*` and `athena-results/*`); state machine role (start/stop/describe the build + the managed CodeBuild events rule); analytics Lambda gains read on `clouder_silver` and `lakehouse/clouder_silver/*`.
- No money figures in docs. Repo is public: no data, only code and model docs, on GitHub Pages.
- Branch `feat/lakehouse-dbt` from `origin/main`, worktree `../clouder-core-lakehouse`; commits/PR via `caveman:caveman-commit`; `$VENV=<repo>/.venv/bin`; `$DBT=<repo>/.venv-dbt/bin` (created in Task 1); `terraform fmt -check` passes.

## Spec

**Problem (measured 2026-10-07).**

| | |
|---|---|
| Bronze events | 19,647 events in 1,243 Parquet files, 6.2 MB (median file 4.7 KB) over 38 days — Firehose writes a file per buffer per event type per day |
| Duplicates | 0 duplicate `event_id` — Firehose delivery is at-least-once, but none observed yet; nothing deduplicates if one appears |
| Query cost of small files | a full-table aggregate scans 555 KB yet takes 7.0 s engine time |
| Home cards (`analytics-api`, 30 days) | 45 calls, p50 4.1 s, p90 5.6 s, max 6.2 s — every call re-reads all history from bronze |
| Catalog history | nightly full snapshots (1,198 objects, 154 MB) expire after 14 days; no track history beyond that |
| Transformations | SQL strings inside Lambda code: no lineage, no data tests, no docs |

**Decisions.**

1. *dbt on Athena, Iceberg tables.* Silver/gold are Iceberg (MERGE, OPTIMIZE/VACUUM, row-level DELETE for privacy later, time travel). dbt gives incremental models, data + unit tests, source freshness, and docs with lineage.
2. *`silver.events`*: incremental MERGE on `event_id`; each run reads bronze partitions from `max(dt) − 2 days` (late arrivals, Firehose redelivery), keeps one copy per `event_id` (earliest `ts_server`), partitioned by `dt`; post-hooks `OPTIMIZE … REWRITE DATA USING BIN_PACK` and `VACUUM`.
3. *`silver.dim_track_history`* (SCD2): versions of a track's tracked attributes (title, bpm, key_camelot, publish_date, album_id, style_id, isrc, release_type, is_ai_suspected, spotify_release_date) with `valid_from`/`valid_to` dated by the catalog snapshot that first showed the version. Incremental: each run folds every retained snapshot newer than the last version date into the open versions (gaps-and-islands on a row hash), so a missed night catches up and history survives the 14-day snapshot expiry. The first run builds history from all retained snapshots.
4. *`gold.fct_play`*: one row per play (the Lambda's play logic: playing stretches capped at the track duration, 10-min fallback) partitioned by user, with the track's `style_id` as of the play date (first version covers plays before history starts).
5. *Hot/cold read path*: the analytics Lambda reads `clouder_silver.events` for `dt < yesterday` and `bronze_events` for `dt >= yesterday` (UTC), configured by `SILVER_EVENTS_TABLE`; unset = bronze only (tests, rollback).
6. *Runtime*: CodeBuild (`aws/codebuild/standard:7.0`, Python 3.12) clones the public repo's `main`, installs `dbt/requirements.txt`, runs `dbt build --target prod` then `dbt source freshness` (informational). `clouder-prod-transform` (STANDARD) runs it at 00:30 UTC (after the 00:00 export and 00:10 DQ) via `codebuild:startBuild.sync`, retries once, fails visibly; alarm on `ExecutionsFailed ≥ 1`.
7. *CI*: a `dbt` job runs `dbt seed` + `dbt build` on DuckDB (unit tests, data tests) and `dbt parse --target prod` (Athena configs compile) when `dbt/**` changes. *Docs*: on push to `main` touching `dbt/**`, build the DuckDB fixtures, `dbt docs generate --static`, publish `static_index.html` to GitHub Pages.

**Non-goals.** Incremental (watermark) catalog export — snapshots are small and the SCD2 model is already incremental over them; marts nobody reads; replacing the time-per-track style lookup (follow-up: use `dim_track_history`); MWAA/Airflow.

**Success criteria.** CI builds and tests every model on DuckDB; deploy creates the Glue databases, CodeBuild project, state machine, schedule and alarm; the first production build creates the four relations; `docs/data/lakehouse.md` records before/after: files and engine time of the same aggregate on bronze vs silver, duplicates removed, SCD2 versions captured, dbt build time (first full vs incremental), Home-card latency.

## Review Focus

1. **A duplicate `event_id` arrives in a later partition than the original** → one row remains (MERGE), not two. Test: `events_keeps_one_copy_per_event_id` (Task 2 unit) + MERGE semantics on DuckDB `delete+insert` (`test` in Task 2 data tests: `unique`).
2. **A night is missed (no build) or a snapshot repeats** → the next SCD2 run creates no duplicate or spurious versions and catches up. Test: `dim_track_history_incremental_folds_new_snapshots` and `dim_track_history_rerun_is_a_noop` (Task 3 unit).
3. **A track changes back to an earlier state (A→B→A)** → three versions, not two. Test: `dim_track_history_records_a_revert` (Task 3 unit).
4. **Hot/cold boundary** → an event on the cutoff day is counted once even though bronze still holds the history. Test: `test_hot_cold_source_counts_each_event_once` (Task 5).
5. **A play before the first known version of its track** → takes the earliest known style, not NULL. Test: `fct_play_uses_the_style_as_of_the_play` (Task 4 unit).

---

### Task 1: dbt project, fixtures, CI job

**Files:**
- Create: `dbt/dbt_project.yml`, `dbt/profiles.yml`, `dbt/requirements.txt`, `dbt/macros/generate_schema_name.sql`, `dbt/macros/dialect.sql`, `dbt/models/sources.yml`, `dbt/models/staging/stg_events.sql`, `dbt/models/staging/_staging.yml`, `dbt/seeds/fixtures/bronze_events.csv`, `dbt/seeds/fixtures/bronze_catalog_export.csv`, `dbt/seeds/fixtures/_fixtures.yml`
- Modify: `.gitignore` (dbt build output), `.github/workflows/pr.yml` (`dbt` filter + job)

**Interfaces:**
- Produces: `ref('stg_events')` with columns `event_id, session_id, user_id, event_name, track_id, source, duration_ms (bigint), ts_client (varchar), ts_client_utc (timestamp), ts_server_utc (timestamp), dt (varchar)`; macros `parse_utc_ts(col)`, `dt_minus_days(expr, days)`, `hash_text(expr)`; `source('bronze','events')`, `source('bronze','catalog_export')`; targets `ci` (duckdb `target/ci.duckdb`) and `prod` (athena); command pattern `cd dbt && DBT_PROFILES_DIR=. $DBT/dbt <cmd> --target ci`.

- [ ] **Step 1: Local dbt environment**

Run: `cd <repo> && python3.12 -m venv .venv-dbt 2>/dev/null || python -m venv .venv-dbt; .venv-dbt/bin/pip install -q 'dbt-core~=1.11.0' 'dbt-athena==1.11.1' 'dbt-duckdb==1.11.0' && .venv-dbt/bin/dbt --version | head -6`
Expected: dbt core 1.11.x with plugins athena 1.11.1 and duckdb 1.11.0. Ensure `.venv-dbt/` is git-ignored (`git check-ignore .venv-dbt`); if not, add it to `.gitignore` in this task.

- [ ] **Step 2: Write the failing CI check**

Run: `cd <repo>/dbt 2>/dev/null && DBT_PROFILES_DIR=. $DBT/dbt build --target ci || echo "no dbt project"`
Expected: `no dbt project`.

- [ ] **Step 3: Project files**

`dbt/requirements.txt`:

```
dbt-core~=1.11.0
dbt-athena==1.11.1
dbt-duckdb==1.11.0
```

`dbt/dbt_project.yml`:

```yaml
name: clouder
version: "1.0.0"
config-version: 2
profile: clouder

model-paths: ["models"]
macro-paths: ["macros"]
seed-paths: ["seeds"]
test-paths: ["tests"]
target-path: target
clean-targets: [target, dbt_packages, logs]

vars:
  # Bronze partitions re-read by silver.events on each run: late arrivals and
  # Firehose redeliveries land in recent dt partitions.
  events_lookback_days: 2

models:
  clouder:
    staging:
      +materialized: view
      +schema: clouder_silver
    silver:
      +schema: clouder_silver
    gold:
      +schema: clouder_gold

seeds:
  clouder:
    fixtures:
      # Stand-ins for the bronze Glue tables on DuckDB (CI, docs); never in prod.
      +enabled: "{{ target.type == 'duckdb' }}"
      +schema: clouder_analytics
```

`dbt/profiles.yml`:

```yaml
clouder:
  target: "{{ env_var('DBT_TARGET', 'ci') }}"
  outputs:
    ci:
      type: duckdb
      path: "{{ env_var('DBT_DUCKDB_PATH', 'target/ci.duckdb') }}"
      threads: 4
    prod:
      type: athena
      region_name: "{{ env_var('AWS_REGION', 'us-east-1') }}"
      database: awsdatacatalog
      schema: clouder_silver
      work_group: "{{ env_var('DBT_ATHENA_WORKGROUP', 'beatport-prod-analytics') }}"
      s3_staging_dir: "{{ env_var('DBT_S3_STAGING_DIR', 's3://clouder-prod-analytics-lake/athena-results/dbt/') }}"
      s3_data_dir: "{{ env_var('DBT_S3_DATA_DIR', 's3://clouder-prod-analytics-lake/lakehouse/') }}"
      threads: 4
      num_retries: 3
```

`dbt/macros/generate_schema_name.sql`:

```sql
{#- Schemas are Glue databases with fixed names, not <target>_<custom>. -#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {{ (custom_schema_name or target.schema) | trim }}
{%- endmacro %}
```

`dbt/macros/dialect.sql`:

```sql
{#- The few SQL fragments that differ between Athena (Trino) in prod and DuckDB in CI. -#}

{% macro parse_utc_ts(col) %}{{ return(adapter.dispatch('parse_utc_ts', 'clouder')(col)) }}{% endmacro %}
{% macro athena__parse_utc_ts(col) %}cast(from_iso8601_timestamp({{ col }}) at time zone 'UTC' as timestamp(6)){% endmacro %}
{% macro default__parse_utc_ts(col) %}(cast({{ col }} as timestamptz) at time zone 'UTC'){% endmacro %}

{% macro dt_minus_days(expr, days) %}{{ return(adapter.dispatch('dt_minus_days', 'clouder')(expr, days)) }}{% endmacro %}
{% macro athena__dt_minus_days(expr, days) %}cast(date_add('day', -{{ days }}, cast({{ expr }} as date)) as varchar){% endmacro %}
{% macro default__dt_minus_days(expr, days) %}cast(cast({{ expr }} as date) - {{ days }} as varchar){% endmacro %}

{% macro hash_text(expr) %}{{ return(adapter.dispatch('hash_text', 'clouder')(expr)) }}{% endmacro %}
{% macro athena__hash_text(expr) %}lower(to_hex(md5(to_utf8({{ expr }})))){% endmacro %}
{% macro default__hash_text(expr) %}md5({{ expr }}){% endmacro %}
```

`dbt/models/sources.yml`:

```yaml
version: 2

sources:
  - name: bronze
    description: Raw lake tables registered in Glue by Terraform (infra/telemetry.tf, infra/analytics_export.tf).
    schema: clouder_analytics
    tables:
      - name: events
        identifier: bronze_events
        description: Telemetry events delivered by Firehose (Parquet, partitioned by dt and event_name; at-least-once).
        loaded_at_field: "from_iso8601_timestamp(ts_server)"
        freshness:
          warn_after: {count: 1, period: day}
          filter: "dt >= cast(current_date - interval '3' day as varchar)"
      - name: catalog_export
        identifier: bronze_catalog_export
        description: Nightly NDJSON snapshot of the Aurora catalog, partitioned by snapshot_dt and tbl; expires after 14 days.
```

`dbt/models/staging/stg_events.sql`:

```sql
-- Typed view over bronze events; the raw ts_client string is kept for the
-- analytics Lambda's hot/cold union (it parses it itself).
select
    event_id,
    session_id,
    user_id,
    event_name,
    track_id,
    source,
    cast(duration_ms as bigint) as duration_ms,
    ts_client,
    {{ parse_utc_ts('ts_client') }} as ts_client_utc,
    {{ parse_utc_ts('ts_server') }} as ts_server_utc,
    dt
from {{ source('bronze', 'events') }}
where event_id is not null
```

`dbt/models/staging/_staging.yml`:

```yaml
version: 2

models:
  - name: stg_events
    description: Bronze events with parsed UTC timestamps.
    columns:
      - name: event_id
        data_tests: [not_null]
      - name: dt
        data_tests: [not_null]
```

`dbt/seeds/fixtures/bronze_events.csv` (dates relative to the fixture, two users, one duplicate `e2`, plays/pauses):

```csv
event_id,session_id,user_id,dt,ts_server,ts_client,event_name,track_id,source,duration_ms
e1,s1,u1,2026-10-04,2026-10-04T10:12:00+00:00,2026-10-04T10:00:00.000Z,playback_play,t1,triage_player,300000
e2,s1,u1,2026-10-04,2026-10-04T10:12:00+00:00,2026-10-04T10:02:00.000Z,playback_play,t2,triage_player,60000
e2,s1,u1,2026-10-05,2026-10-05T00:01:00+00:00,2026-10-04T10:02:00.000Z,playback_play,t2,triage_player,60000
e3,s1,u1,2026-10-04,2026-10-04T10:12:00+00:00,2026-10-04T10:05:00.000Z,playback_pause,t2,triage_player,
e4,s1,u1,2026-10-04,2026-10-04T10:12:00+00:00,2026-10-04T10:10:00.000Z,playback_play,t1,category_player,300000
e5,s2,u2,2026-10-05,2026-10-05T09:00:05+00:00,2026-10-05T09:00:00.000Z,playback_play,t9,playlist_player,0
e6,s2,u2,2026-10-05,2026-10-05T09:00:05+00:00,2026-10-05T09:01:00.000Z,track_view,t9,,
```

`dbt/seeds/fixtures/bronze_catalog_export.csv` (two snapshots; t1 bpm changes on the second):

```csv
snapshot_dt,tbl,id,title,bpm,key_camelot,publish_date,album_id,style_id,isrc,release_type,is_ai_suspected,spotify_release_date
2026-10-03,clouder_tracks,t1,Track 1,128,8A,2026-09-26,a1,s1,QZ1,single,false,
2026-10-03,clouder_tracks,t2,Track 2,120,5B,2026-09-26,a1,s1,QZ2,single,false,
2026-10-03,clouder_tracks,t9,Track 9,174,1A,2026-09-26,a2,s2,QZ9,album,false,
2026-10-04,clouder_tracks,t1,Track 1,126,8A,2026-09-26,a1,s1,QZ1,single,false,
2026-10-04,clouder_tracks,t2,Track 2,120,5B,2026-09-26,a1,s1,QZ2,single,false,
2026-10-04,clouder_tracks,t9,Track 9,174,1A,2026-09-26,a2,s2,QZ9,album,false,
2026-10-04,clouder_styles,s1,,,,,,,,,,
```

`dbt/seeds/fixtures/_fixtures.yml`:

```yaml
version: 2

seeds:
  - name: bronze_events
    config:
      column_types:
        event_id: varchar
        session_id: varchar
        user_id: varchar
        dt: varchar
        ts_server: varchar
        ts_client: varchar
        event_name: varchar
        track_id: varchar
        source: varchar
        duration_ms: bigint
  - name: bronze_catalog_export
    config:
      column_types:
        snapshot_dt: varchar
        tbl: varchar
        id: varchar
        title: varchar
        bpm: varchar
        key_camelot: varchar
        publish_date: varchar
        album_id: varchar
        style_id: varchar
        isrc: varchar
        release_type: varchar
        is_ai_suspected: varchar
        spotify_release_date: varchar
```

`.gitignore`: add `dbt/target/`, `dbt/logs/`, `dbt/dbt_packages/`, `.venv-dbt/`.

- [ ] **Step 4: Run the CI build locally**

Run: `cd <repo>/dbt && rm -f target/ci.duckdb && DBT_PROFILES_DIR=. $DBT/dbt seed --target ci && DBT_PROFILES_DIR=. $DBT/dbt build --target ci --exclude resource_type:seed && DBT_PROFILES_DIR=. $DBT/dbt parse --target prod`
Expected: seed 2 OK; build PASS=3 (view + 2 tests); parse succeeds with no connection (prod profile not contacted).

- [ ] **Step 5: CI job**

In `.github/workflows/pr.yml`: add output `dbt: ${{ steps.filter.outputs.dbt }}` to `changes`, a filter

```yaml
            dbt:
              - 'dbt/**'
              - '.github/workflows/pr.yml'
```

and the job:

```yaml
  dbt:
    needs: changes
    if: needs.changes.outputs.dbt == 'true'
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: dbt
    env:
      DBT_PROFILES_DIR: .
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dbt
        run: pip install -r requirements.txt
      - name: Build and test on DuckDB (fixtures, unit + data tests)
        run: |
          dbt seed --target ci
          dbt build --target ci --exclude resource_type:seed
      - name: Parse the Athena target
        run: dbt parse --target prod
```

- [ ] **Step 6: Commit**

```bash
git add dbt .gitignore .github/workflows/pr.yml
git commit -m "<caveman-commit output: feat(dbt): scaffold project, fixtures and CI>"
```

---

### Task 2: `silver.events` — incremental Iceberg MERGE with dedup

**Files:**
- Create: `dbt/models/silver/events.sql`, `dbt/models/silver/_silver.yml`

**Interfaces:**
- Consumes: `ref('stg_events')`, `dt_minus_days`, var `events_lookback_days` (Task 1).
- Produces: `ref('events')` — columns of `stg_events`, one row per `event_id`; Glue table `clouder_silver.events` (Iceberg, partitioned by `dt`).

- [ ] **Step 1: Write the failing tests**

Create `dbt/models/silver/_silver.yml`:

```yaml
version: 2

models:
  - name: events
    description: >
      Telemetry events, one row per event_id (Firehose is at-least-once), compacted
      Iceberg. Each run merges bronze partitions from max(dt) - events_lookback_days.
    columns:
      - name: event_id
        data_tests: [unique, not_null]
      - name: user_id
        data_tests: [not_null]
      - name: event_name
        data_tests:
          - not_null
          - accepted_values:
              arguments:
                values: [triage_session_start, triage_session_end, track_view, track_categorized,
                         playback_play, playback_pause, playback_resume, playback_seek,
                         playback_ended, playback_skip, hotkey_used, playlist_add,
                         playlist_reorder, playlist_publish]
      - name: dt
        data_tests: [not_null]

unit_tests:
  - name: events_keeps_one_copy_per_event_id
    model: events
    given:
      - input: ref('stg_events')
        rows:
          - {event_id: e1, user_id: u1, event_name: playback_play, dt: '2026-10-04', ts_client_utc: '2026-10-04 10:00:00', ts_server_utc: '2026-10-04 10:12:00'}
          - {event_id: e1, user_id: u1, event_name: playback_play, dt: '2026-10-05', ts_client_utc: '2026-10-04 10:00:00', ts_server_utc: '2026-10-05 00:01:00'}
          - {event_id: e2, user_id: u1, event_name: playback_pause, dt: '2026-10-04', ts_client_utc: '2026-10-04 10:01:00', ts_server_utc: '2026-10-04 10:12:00'}
    expect:
      rows:
        - {event_id: e1, dt: '2026-10-04'}
        - {event_id: e2, dt: '2026-10-04'}

  - name: events_incremental_reads_only_the_lookback_window
    model: events
    overrides:
      macros:
        is_incremental: true
    given:
      - input: ref('stg_events')
        rows:
          - {event_id: old, user_id: u1, event_name: playback_play, dt: '2026-10-01', ts_client_utc: '2026-10-01 10:00:00', ts_server_utc: '2026-10-01 10:00:00'}
          - {event_id: late, user_id: u1, event_name: playback_play, dt: '2026-10-03', ts_client_utc: '2026-10-03 10:00:00', ts_server_utc: '2026-10-03 10:00:00'}
          - {event_id: new, user_id: u1, event_name: playback_play, dt: '2026-10-05', ts_client_utc: '2026-10-05 10:00:00', ts_server_utc: '2026-10-05 10:00:00'}
      - input: this
        rows:
          - {event_id: seen, user_id: u1, event_name: playback_play, dt: '2026-10-05', ts_client_utc: '2026-10-05 09:00:00', ts_server_utc: '2026-10-05 09:00:00'}
    expect:
      rows:
        - {event_id: late}
        - {event_id: new}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dbt && DBT_PROFILES_DIR=. $DBT/dbt build --target ci --select events`
Expected: error — no model named `events` (unit tests reference a missing model).

- [ ] **Step 3: Implement**

`dbt/models/silver/events.sql`:

```sql
{{ config(
    materialized='incremental',
    unique_key='event_id',
    incremental_strategy=('merge' if target.type == 'athena' else 'delete+insert'),
    table_type='iceberg',
    format='parquet',
    partitioned_by=['dt'],
    on_schema_change='append_new_columns',
    post_hook=([
        "optimize {{ this.render_pure() }} rewrite data using bin_pack",
        "vacuum {{ this.render_pure() }}",
    ] if target.type == 'athena' else []),
) }}

with source_rows as (
    select * from {{ ref('stg_events') }}
    {% if is_incremental() %}
    -- Late arrivals and Firehose redeliveries land in recent partitions; the
    -- MERGE on event_id makes re-reading them idempotent.
    where dt >= (select {{ dt_minus_days('max(dt)', var('events_lookback_days')) }} from {{ this }})
    {% endif %}
),

ranked as (
    select
        *,
        row_number() over (
            partition by event_id
            order by ts_server_utc, ts_client_utc
        ) as copy_no
    from source_rows
)

select
    event_id, session_id, user_id, event_name, track_id, source, duration_ms,
    ts_client, ts_client_utc, ts_server_utc, dt
from ranked
where copy_no = 1
```

- [ ] **Step 4: Run the tests**

Run: `cd dbt && rm -f target/ci.duckdb && DBT_PROFILES_DIR=. $DBT/dbt seed --target ci && DBT_PROFILES_DIR=. $DBT/dbt build --target ci --exclude resource_type:seed && DBT_PROFILES_DIR=. $DBT/dbt parse --target prod`
Expected: both unit tests PASS; `unique_events_event_id` PASS on the fixture (which holds `e2` twice); everything else PASS.

- [ ] **Step 5: Commit**

```bash
git add dbt/models/silver
git commit -m "<caveman-commit output: feat(dbt): silver events with dedup and lookback merge>"
```

---

### Task 3: `silver.dim_track_history` — SCD2 from catalog snapshots

**Files:**
- Create: `dbt/models/silver/dim_track_history.sql`, `dbt/tests/assert_one_open_version_per_track.sql`, `dbt/tests/assert_versions_do_not_overlap.sql`
- Modify: `dbt/models/silver/_silver.yml`

**Interfaces:**
- Consumes: `source('bronze','catalog_export')`, `hash_text` (Task 1).
- Produces: `ref('dim_track_history')` — `track_id, valid_from (date), valid_to (date, null = current), title, bpm, key_camelot, publish_date, album_id, style_id, isrc, release_type, is_ai_suspected, spotify_release_date, row_hash`.

- [ ] **Step 1: Write the failing tests**

Compute the row hash the model will produce for the `this` fixture row (DuckDB `md5` of the `|`-joined values, NULLs as `~`):

Run: `$VENV/python -c "import duckdb; print(duckdb.sql(\"select md5('Track 2|120|5B|2026-09-26|a1|s1|QZ2|single|false|~')\").fetchone()[0])"` — paste the printed hash as `H_T2` below.

Append to `dbt/models/silver/_silver.yml` under `models:`:

```yaml
  - name: dim_track_history
    description: >
      SCD2 of a track's catalog attributes. valid_from/valid_to are snapshot dates
      (valid_to null = current). Each run folds every retained snapshot newer than
      the latest version into the open versions, so missed nights catch up and
      history outlives the 14-day snapshot expiry.
    columns:
      - name: track_id
        data_tests: [not_null]
      - name: valid_from
        data_tests: [not_null]
      - name: row_hash
        data_tests: [not_null]
```

and under `unit_tests:`:

```yaml
  - name: dim_track_history_first_build_creates_versions_per_change
    model: dim_track_history
    given:
      - input: source('bronze', 'catalog_export')
        rows:
          - {snapshot_dt: '2026-10-03', tbl: clouder_tracks, id: t1, title: Track 1, bpm: '128'}
          - {snapshot_dt: '2026-10-04', tbl: clouder_tracks, id: t1, title: Track 1, bpm: '126'}
          - {snapshot_dt: '2026-10-03', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '120'}
          - {snapshot_dt: '2026-10-04', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '120'}
          - {snapshot_dt: '2026-10-04', tbl: clouder_styles, id: s1}
    expect:
      rows:
        - {track_id: t1, valid_from: '2026-10-03', valid_to: '2026-10-04', bpm: '128'}
        - {track_id: t1, valid_from: '2026-10-04', valid_to: null, bpm: '126'}
        - {track_id: t2, valid_from: '2026-10-03', valid_to: null, bpm: '120'}

  - name: dim_track_history_records_a_revert
    model: dim_track_history
    given:
      - input: source('bronze', 'catalog_export')
        rows:
          - {snapshot_dt: '2026-10-01', tbl: clouder_tracks, id: t1, bpm: '128'}
          - {snapshot_dt: '2026-10-02', tbl: clouder_tracks, id: t1, bpm: '126'}
          - {snapshot_dt: '2026-10-03', tbl: clouder_tracks, id: t1, bpm: '128'}
    expect:
      rows:
        - {track_id: t1, valid_from: '2026-10-01', valid_to: '2026-10-02'}
        - {track_id: t1, valid_from: '2026-10-02', valid_to: '2026-10-03'}
        - {track_id: t1, valid_from: '2026-10-03', valid_to: null}

  - name: dim_track_history_incremental_folds_new_snapshots
    model: dim_track_history
    overrides:
      macros:
        is_incremental: true
    given:
      - input: source('bronze', 'catalog_export')
        rows:
          - {snapshot_dt: '2026-10-02', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '120', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false'}
          - {snapshot_dt: '2026-10-05', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '122', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false'}
          - {snapshot_dt: '2026-10-06', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '122', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false'}
      - input: this
        rows:
          - {track_id: t2, valid_from: '2026-10-03', valid_to: null, title: Track 2, bpm: '120', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false', row_hash: H_T2}
    expect:
      rows:
        - {track_id: t2, valid_from: '2026-10-03', valid_to: '2026-10-05', bpm: '120'}
        - {track_id: t2, valid_from: '2026-10-05', valid_to: null, bpm: '122'}

  - name: dim_track_history_rerun_is_a_noop
    # The next snapshot repeats the current version: its recomputed hash must
    # equal the stored one, so no new version appears.
    model: dim_track_history
    overrides:
      macros:
        is_incremental: true
    given:
      - input: source('bronze', 'catalog_export')
        rows:
          - {snapshot_dt: '2026-10-04', tbl: clouder_tracks, id: t2, title: Track 2, bpm: '120', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false'}
      - input: this
        rows:
          - {track_id: t2, valid_from: '2026-10-03', valid_to: null, title: Track 2, bpm: '120', key_camelot: 5B, publish_date: '2026-09-26', album_id: a1, style_id: s1, isrc: QZ2, release_type: single, is_ai_suspected: 'false', row_hash: H_T2}
    expect:
      rows:
        - {track_id: t2, valid_from: '2026-10-03', valid_to: null, bpm: '120'}
```

`dbt/tests/assert_one_open_version_per_track.sql`:

```sql
-- A track has exactly one current version.
select track_id
from {{ ref('dim_track_history') }}
where valid_to is null
group by track_id
having count(*) > 1
```

`dbt/tests/assert_versions_do_not_overlap.sql`:

```sql
-- Closed versions end after they start; a track's versions never overlap.
select track_id, valid_from, valid_to
from (
    select
        track_id, valid_from, valid_to,
        lead(valid_from) over (partition by track_id order by valid_from) as next_from
    from {{ ref('dim_track_history') }}
) v
where (valid_to is not null and valid_to <= valid_from)
   or (next_from is not null and (valid_to is null or valid_to <> next_from))
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dbt && DBT_PROFILES_DIR=. $DBT/dbt build --target ci --select dim_track_history`
Expected: error — no model named `dim_track_history`.

- [ ] **Step 3: Implement**

`dbt/models/silver/dim_track_history.sql`:

```sql
{{ config(
    materialized='incremental',
    unique_key=['track_id', 'valid_from'],
    incremental_strategy=('merge' if target.type == 'athena' else 'delete+insert'),
    table_type='iceberg',
    format='parquet',
) }}

{%- set tracked = ['title', 'bpm', 'key_camelot', 'publish_date', 'album_id', 'style_id',
                   'isrc', 'release_type', 'is_ai_suspected', 'spotify_release_date'] -%}
{%- set parts = [] -%}
{%- for c in tracked -%}
    {%- do parts.append("coalesce(cast(" ~ c ~ " as varchar), '~')") -%}
{%- endfor -%}

with snapshots as (
    select
        cast(snapshot_dt as date) as observed_on,
        id as track_id,
        {{ tracked | join(', ') }}
    from {{ source('bronze', 'catalog_export') }}
    where tbl = 'clouder_tracks'
      and id is not null
    {% if is_incremental() %}
      -- Every retained snapshot after the latest version: a missed night catches up.
      and cast(snapshot_dt as date) > (select max(valid_from) from {{ this }})
    {% endif %}
),

observed as (
    select
        observed_on, track_id, {{ tracked | join(', ') }},
        {{ hash_text("concat_ws('|', " ~ parts | join(', ') ~ ")") }} as row_hash
    from snapshots
    {% if is_incremental() %}
    union all
    -- Current versions take part so a change closes them and a repeat is a no-op.
    select valid_from as observed_on, track_id, {{ tracked | join(', ') }}, row_hash
    from {{ this }}
    where valid_to is null
    {% endif %}
),

changes as (
    select
        *,
        lag(row_hash) over (partition by track_id order by observed_on) as prev_hash
    from observed
),

versions as (
    select * from changes
    where prev_hash is null or prev_hash <> row_hash
)

select
    track_id,
    observed_on as valid_from,
    lead(observed_on) over (partition by track_id order by observed_on) as valid_to,
    {{ tracked | join(', ') }},
    row_hash
from versions
```

- [ ] **Step 4: Run the tests**

Run the Task 2 Step 4 command.
Expected: the four unit tests, the two singular tests and the column tests PASS; on the fixture, t1 has 2 versions, t2 and t9 one each.

- [ ] **Step 5: Commit**

```bash
git add dbt/models/silver dbt/tests
git commit -m "<caveman-commit output: feat(dbt): SCD2 track history from catalog snapshots>"
```

---

### Task 4: `gold.fct_play` — plays with the style as of the play

**Files:**
- Create: `dbt/models/gold/fct_play.sql`, `dbt/models/gold/_gold.yml`

**Interfaces:**
- Consumes: `ref('events')` (Task 2), `ref('dim_track_history')` (Task 3).
- Produces: `ref('fct_play')` — `play_event_id, user_id, track_id, stage, played_at (timestamp), played_on (date), ms (bigint), style_id`.

- [ ] **Step 1: Write the failing tests**

`dbt/models/gold/_gold.yml`:

```yaml
version: 2

models:
  - name: fct_play
    description: >
      One row per play: playing stretches (play/resume up to the user's next playback
      event) capped at the track's duration, 10-minute fallback for unknown durations —
      the same rule as the analytics Lambda. style_id is the track's style as of the
      play date (the earliest known version for plays before history starts).
    columns:
      - name: play_event_id
        data_tests: [unique, not_null]
      - name: user_id
        data_tests: [not_null]
      - name: ms
        data_tests: [not_null]

unit_tests:
  - name: fct_play_caps_stretches_at_the_track_duration
    model: fct_play
    given:
      - input: ref('events')
        rows:
          - {event_id: e1, user_id: u1, event_name: playback_play, track_id: t1, source: triage_player, duration_ms: 300000, ts_client_utc: '2026-10-04 10:00:00'}
          - {event_id: e2, user_id: u1, event_name: playback_play, track_id: t2, source: triage_player, duration_ms: 60000, ts_client_utc: '2026-10-04 10:02:00'}
          - {event_id: e3, user_id: u1, event_name: playback_pause, track_id: t2, source: triage_player, duration_ms: null, ts_client_utc: '2026-10-04 10:02:30'}
          - {event_id: e4, user_id: u1, event_name: playback_play, track_id: t1, source: category_player, duration_ms: 300000, ts_client_utc: '2026-10-04 10:10:00'}
          - {event_id: e9, user_id: u2, event_name: playback_play, track_id: t9, source: playlist_player, duration_ms: 0, ts_client_utc: '2026-10-04 10:01:00'}
      - input: ref('dim_track_history')
        rows: []
    expect:
      rows:
        - {play_event_id: e1, user_id: u1, ms: 120000}
        - {play_event_id: e2, user_id: u1, ms: 30000}
        - {play_event_id: e4, user_id: u1, ms: 300000}
        - {play_event_id: e9, user_id: u2, ms: 600000}

  - name: fct_play_uses_the_style_as_of_the_play
    model: fct_play
    given:
      - input: ref('events')
        rows:
          - {event_id: before, user_id: u1, event_name: playback_play, track_id: t1, source: triage_player, duration_ms: 1000, ts_client_utc: '2026-09-01 10:00:00'}
          - {event_id: during, user_id: u1, event_name: playback_play, track_id: t1, source: triage_player, duration_ms: 1000, ts_client_utc: '2026-10-04 10:00:00'}
          - {event_id: after, user_id: u1, event_name: playback_play, track_id: t1, source: triage_player, duration_ms: 1000, ts_client_utc: '2026-10-06 10:00:00'}
      - input: ref('dim_track_history')
        rows:
          - {track_id: t1, valid_from: '2026-10-03', valid_to: '2026-10-05', style_id: s1}
          - {track_id: t1, valid_from: '2026-10-05', valid_to: null, style_id: s2}
    expect:
      rows:
        - {play_event_id: before, style_id: s1}
        - {play_event_id: during, style_id: s1}
        - {play_event_id: after, style_id: s2}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd dbt && DBT_PROFILES_DIR=. $DBT/dbt build --target ci --select fct_play`
Expected: error — no model named `fct_play`.

- [ ] **Step 3: Implement**

`dbt/models/gold/fct_play.sql`:

```sql
{{ config(materialized='table', table_type='iceberg', format='parquet') }}

{#- Same rule as collector/analytics_handler.py:_plays_cte; 10-minute fallback
    for unknown durations (_FALLBACK_TRACK_MS). -#}
{%- set fallback_ms = 600000 -%}

with ev as (
    select
        user_id, event_id, event_name, track_id, source,
        ts_client_utc as ts,
        cast(coalesce(nullif(duration_ms, 0), {{ fallback_ms }}) as double) as dur_ms
    from {{ ref('events') }}
    where event_name in ('playback_play', 'playback_pause', 'playback_resume', 'playback_ended')
),

seq as (
    select
        *,
        sum(case when event_name = 'playback_play' then 1 else 0 end) over (
            partition by user_id order by ts, event_id
            rows between unbounded preceding and current row
        ) as play_no,
        date_diff('millisecond', ts, lead(ts) over (partition by user_id order by ts, event_id)) as gap_ms
    from ev
),

per_play as (
    select
        user_id,
        play_no,
        max(case when event_name = 'playback_play' then event_id end) as play_event_id,
        max(case when event_name = 'playback_play' then track_id end) as track_id,
        max(case when event_name = 'playback_play' then source end) as stage,
        max(case when event_name = 'playback_play' then dur_ms end) as dur_ms,
        min(case when event_name = 'playback_play' then ts end) as played_at,
        sum(case when event_name in ('playback_play', 'playback_resume')
                 then coalesce(cast(gap_ms as double), dur_ms) else 0 end) as played_ms
    from seq
    where play_no > 0
    group by user_id, play_no
),

plays as (
    select
        play_event_id, user_id, track_id, stage, played_at,
        cast(played_at as date) as played_on,
        cast(least(played_ms, dur_ms) as bigint) as ms
    from per_play
),

versions as (
    select
        track_id, style_id, valid_from, valid_to,
        row_number() over (partition by track_id order by valid_from) = 1 as is_first
    from {{ ref('dim_track_history') }}
)

select
    p.play_event_id, p.user_id, p.track_id, p.stage, p.played_at, p.played_on, p.ms,
    v.style_id
from plays p
left join versions v
    on v.track_id = p.track_id
   and (v.is_first or v.valid_from <= p.played_on)
   and (v.valid_to is null or p.played_on < v.valid_to)
```

- [ ] **Step 4: Run the tests**

Run the Task 2 Step 4 command.
Expected: both unit tests PASS; `unique_fct_play_play_event_id` PASS on the fixture (the duplicated `e2` was removed in silver).

- [ ] **Step 5: Commit**

```bash
git add dbt/models/gold
git commit -m "<caveman-commit output: feat(dbt): gold plays with point-in-time style>"
```

---

### Task 5: Analytics Lambda reads history from silver

**Files:**
- Modify: `src/collector/analytics_handler.py`
- Test: `tests/unit/test_analytics_hot_cold.py` (create)

**Interfaces:**
- Produces: `analytics_handler.events_source(silver_table: str, cutoff: str) -> str` (a parenthesised, aliased relation for `table=`); `serve_listening` / `serve_time_per_track` pass it when `SILVER_EVENTS_TABLE` is set; env var `SILVER_EVENTS_TABLE` (e.g. `clouder_silver.events`; must match `^[a-z_]+\.[a-z_]+$`).

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_analytics_hot_cold.py`:

```python
"""History from silver, the last day live from bronze: each event counted once."""

from __future__ import annotations

from datetime import date, datetime, timezone

import duckdb
import pytest

from collector import analytics_handler as ah
from collector.analytics_handler import DUCKDB

COLS = "event_id VARCHAR, user_id VARCHAR, dt VARCHAR, ts_client VARCHAR, event_name VARCHAR, track_id VARCHAR, duration_ms BIGINT, source VARCHAR"
ROWS = [
    ("e1", "u1", "2026-10-03", "2026-10-03T10:00:00.000Z", "playback_play", "t1", 60000, "triage_player"),
    ("e2", "u1", "2026-10-03", "2026-10-03T10:00:30.000Z", "playback_pause", "t1", None, "triage_player"),
    ("e3", "u1", "2026-10-04", "2026-10-04T10:00:00.000Z", "playback_play", "t2", 60000, "triage_player"),
    ("e4", "u1", "2026-10-04", "2026-10-04T10:00:20.000Z", "playback_pause", "t2", None, "triage_player"),
]


@pytest.fixture()
def con():
    c = duckdb.connect(":memory:")
    c.execute("CREATE SCHEMA clouder_silver")
    c.execute(f"CREATE TABLE bronze_events ({COLS})")
    c.execute(f"CREATE TABLE clouder_silver.events ({COLS})")
    c.executemany("INSERT INTO bronze_events VALUES (?,?,?,?,?,?,?,?)", ROWS)
    # silver holds the history (deduplicated); bronze still has everything
    c.executemany("INSERT INTO clouder_silver.events VALUES (?,?,?,?,?,?,?,?)", ROWS[:2])
    yield c
    c.close()


def _listening(con, table: str) -> dict:
    w = ah.listening_windows(datetime(2026, 10, 4, 12, tzinfo=timezone.utc), 0)
    sql = ah.listening_sql(
        DUCKDB,
        scan_from=w["scan_from"].isoformat(),
        week_from=w["week_from"].isoformat(),
        month_from=w["month_from"].isoformat(),
        tz_offset_min=0,
        table=table,
    )
    cur = con.execute(sql, ["u1"])
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, (None if v is None else str(v) for v in r))) for r in cur.fetchall()]
    return ah.shape_listening(rows, w["today"])


def test_hot_cold_source_counts_each_event_once(con) -> None:
    bronze_only = _listening(con, "bronze_events")

    hot_cold = _listening(con, ah.events_source("clouder_silver.events", "2026-10-04"))

    assert hot_cold == bronze_only
    assert hot_cold["totals"]["week"] == {"listened_ms": 50000, "tracks": 2}


@pytest.mark.parametrize("table, cutoff", [("events; drop", "2026-10-04"), ("clouder_silver.events", "10/04")])
def test_events_source_rejects_unsafe_input(table, cutoff) -> None:
    with pytest.raises(ah.AnalyticsError):
        ah.events_source(table, cutoff)


def test_events_table_defaults_to_bronze(monkeypatch) -> None:
    monkeypatch.delenv("SILVER_EVENTS_TABLE", raising=False)
    assert ah.events_table(date(2026, 10, 4)) == "bronze_events"


def test_events_table_uses_silver_before_yesterday(monkeypatch) -> None:
    monkeypatch.setenv("SILVER_EVENTS_TABLE", "clouder_silver.events")
    assert ah.events_table(date(2026, 10, 4)) == ah.events_source("clouder_silver.events", "2026-10-03")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$VENV/pytest tests/unit/test_analytics_hot_cold.py -q`
Expected: FAIL — `AttributeError: module 'collector.analytics_handler' has no attribute 'events_source'`.

- [ ] **Step 3: Implement**

In `src/collector/analytics_handler.py` (after `_check_dates`):

```python
_TABLE_RE = re.compile(r"^[a-z_]+\.[a-z_]+$")
_EVENT_COLS = "event_id, user_id, dt, ts_client, event_name, track_id, duration_ms, source"


def events_source(silver_table: str, cutoff: str) -> str:
    """Events as one relation: compacted history from silver before `cutoff`,
    the live tail from bronze from `cutoff` on. Silver is built nightly, so the
    tail starts a day back; each dt comes from exactly one side."""
    if not _TABLE_RE.match(silver_table):
        raise AnalyticsError(500, "config_error", "bad SILVER_EVENTS_TABLE")
    _check_dates(cutoff)
    return (
        f"(SELECT {_EVENT_COLS} FROM {silver_table} WHERE dt < '{cutoff}' "
        f"UNION ALL SELECT {_EVENT_COLS} FROM bronze_events WHERE dt >= '{cutoff}') AS events_src"
    )


def events_table(today: date) -> str:
    silver = os.environ.get("SILVER_EVENTS_TABLE", "").strip()
    if not silver:
        return "bronze_events"
    return events_source(silver, (today - timedelta(days=1)).isoformat())
```

In `serve_time_per_track` pass `table=events_table(today)`; in `serve_listening` pass `table=events_table(datetime.now(timezone.utc).date())`. Update the module docstring: history from `clouder_silver.events` (dbt, nightly), the last day from bronze.

- [ ] **Step 4: Run the tests**

Run: `$VENV/pytest tests/unit/test_analytics_hot_cold.py tests/unit/test_analytics_handler.py tests/unit/test_analytics_listening.py tests/unit/test_analytics_time_per_track.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/collector/analytics_handler.py tests/unit/test_analytics_hot_cold.py
git commit -m "<caveman-commit output: feat(analytics): read history from silver events>"
```

---

### Task 6: Infra — Glue databases, CodeBuild, transform state machine, schedule, alarm

**Files:**
- Create: `infra/lakehouse.tf`, `infra/transform.asl.json`
- Modify: `infra/analytics_routes.tf` (analytics Lambda env `SILVER_EVENTS_TABLE` + read IAM), `infra/outputs.tf`
- Test: `tests/unit/test_transform_state_machine.py` (create)

**Interfaces:**
- Consumes: the dbt project (Tasks 1–4) at `dbt/` on `main`; `SILVER_EVENTS_TABLE` (Task 5).
- Produces: Glue DBs `clouder_silver`, `clouder_gold`; CodeBuild `clouder-prod-dbt`; state machine `clouder-prod-transform`; rule `clouder-prod-transform-nightly` (00:30 UTC); alarm `clouder-prod-transform-failed`; output `transform_state_machine_arn`.

- [ ] **Step 1: Write the failing contract test**

`tests/unit/test_transform_state_machine.py`:

```python
"""The transform state machine runs the dbt CodeBuild project synchronously and fails visibly."""

from __future__ import annotations

import json
from pathlib import Path

ASL = Path(__file__).resolve().parents[2] / "infra" / "transform.asl.json"


def _definition() -> dict:
    text = ASL.read_text().replace("${dbt_project_name}", "clouder-prod-dbt")
    assert "${" not in text
    return json.loads(text)


def test_runs_dbt_build_synchronously_with_a_retry() -> None:
    build = _definition()["States"]["DbtBuild"]
    assert build["Resource"] == "arn:aws:states:::codebuild:startBuild.sync"
    assert build["Parameters"]["ProjectName"] == "clouder-prod-dbt"
    assert build["Retry"][0]["MaxAttempts"] == 1
    assert build["TimeoutSeconds"] <= 3600


def test_failure_ends_in_a_fail_state() -> None:
    states = _definition()["States"]
    catch = states["DbtBuild"]["Catch"][0]
    assert catch["ErrorEquals"] == ["States.ALL"]
    assert states[catch["Next"]]["Type"] == "Fail"
```

Run: `$VENV/pytest tests/unit/test_transform_state_machine.py -q` — Expected: 2 failed (`FileNotFoundError`).

- [ ] **Step 2: State machine definition**

`infra/transform.asl.json`:

```json
{
  "Comment": "Nightly dbt build of the analytics lakehouse. docs/data/lakehouse.md",
  "StartAt": "DbtBuild",
  "States": {
    "DbtBuild": {
      "Type": "Task",
      "Resource": "arn:aws:states:::codebuild:startBuild.sync",
      "Parameters": {"ProjectName": "${dbt_project_name}"},
      "TimeoutSeconds": 3600,
      "Retry": [{"ErrorEquals": ["States.ALL"], "IntervalSeconds": 60, "MaxAttempts": 1, "BackoffRate": 1}],
      "Catch": [{"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "BuildFailed"}],
      "ResultSelector": {"build_id.$": "$.Build.Id", "status.$": "$.Build.BuildStatus"},
      "End": true
    },
    "BuildFailed": {
      "Type": "Fail",
      "Error": "DbtBuildFailed",
      "Cause": "dbt build failed; see the clouder-prod-dbt CodeBuild logs."
    }
  }
}
```

Run the contract test — Expected: 2 passed. Validate: render with `sed 's#${dbt_project_name}#clouder-prod-dbt#'` and `aws stepfunctions validate-state-machine-definition --type STANDARD` → `OK` (ruling if not permitted).

- [ ] **Step 3: Terraform**

`infra/lakehouse.tf`:

```hcl
# ── Analytics lakehouse: dbt on Athena, Iceberg silver/gold (docs/data/lakehouse.md) ──
# CodeBuild clones the public repo's main and runs `dbt build`; Step Functions
# starts it nightly after the catalog export (00:00) and the DQ checks (00:10).

locals {
  dbt_project_name     = "${local.name_prefix}-dbt"
  lakehouse_prefix     = "lakehouse"
  analytics_lake_arn   = aws_s3_bucket.analytics_lake.arn
  athena_workgroup_arn = "arn:aws:athena:${var.aws_region}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup}"
  glue_catalog_arn     = "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:catalog"
}

resource "aws_glue_catalog_database" "silver" {
  name = "clouder_silver"
}

resource "aws_glue_catalog_database" "gold" {
  name = "clouder_gold"
}

resource "aws_cloudwatch_log_group" "dbt" {
  name              = "/aws/codebuild/${local.dbt_project_name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dbt" {
  name               = "${local.name_prefix}-dbt-role"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

data "aws_iam_policy_document" "dbt" {
  statement {
    sid       = "AllowOwnLogs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.dbt.arn}:*"]
  }
  statement {
    sid = "AllowAthenaQueries"
    actions = [
      "athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults",
      "athena:StopQueryExecution", "athena:GetWorkGroup",
    ]
    resources = [local.athena_workgroup_arn]
  }
  statement {
    sid       = "AllowReadBronzeCatalog"
    actions   = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition"]
    resources = [local.glue_catalog_arn, "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:database/${aws_glue_catalog_database.analytics.name}", "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.analytics.name}/*"]
  }
  statement {
    sid = "AllowWriteLakehouseCatalog"
    actions = [
      "glue:GetDatabase", "glue:GetTable", "glue:GetTables", "glue:CreateTable", "glue:UpdateTable",
      "glue:DeleteTable", "glue:BatchDeleteTable", "glue:GetPartition", "glue:GetPartitions",
      "glue:BatchGetPartition", "glue:CreatePartition", "glue:BatchCreatePartition",
      "glue:UpdatePartition", "glue:DeletePartition", "glue:BatchDeletePartition",
      "glue:GetTableVersions", "glue:DeleteTableVersion", "glue:BatchDeleteTableVersion",
    ]
    resources = [
      local.glue_catalog_arn,
      aws_glue_catalog_database.silver.arn,
      aws_glue_catalog_database.gold.arn,
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.silver.name}/*",
      "arn:aws:glue:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${aws_glue_catalog_database.gold.name}/*",
    ]
  }
  statement {
    sid       = "AllowListLake"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [local.analytics_lake_arn]
  }
  statement {
    sid       = "AllowReadBronze"
    actions   = ["s3:GetObject"]
    resources = ["${local.analytics_lake_arn}/bronze/*"]
  }
  statement {
    sid       = "AllowWriteLakehouseAndResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload", "s3:ListMultipartUploadParts"]
    resources = ["${local.analytics_lake_arn}/${local.lakehouse_prefix}/*", "${local.analytics_lake_arn}/athena-results/*"]
  }
}

resource "aws_iam_role_policy" "dbt" {
  name   = "${local.name_prefix}-dbt-policy"
  role   = aws_iam_role.dbt.id
  policy = data.aws_iam_policy_document.dbt.json
}

resource "aws_codebuild_project" "dbt" {
  name          = local.dbt_project_name
  service_role  = aws_iam_role.dbt.arn
  build_timeout = 60

  artifacts { type = "NO_ARTIFACTS" }

  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = "aws/codebuild/standard:7.0"
    type         = "LINUX_CONTAINER"

    environment_variable {
      name  = "DBT_TARGET"
      value = "prod"
    }
    environment_variable {
      name  = "DBT_ATHENA_WORKGROUP"
      value = var.athena_workgroup
    }
    environment_variable {
      name  = "DBT_S3_STAGING_DIR"
      value = "s3://${aws_s3_bucket.analytics_lake.bucket}/athena-results/dbt/"
    }
    environment_variable {
      name  = "DBT_S3_DATA_DIR"
      value = "s3://${aws_s3_bucket.analytics_lake.bucket}/${local.lakehouse_prefix}/"
    }
    environment_variable {
      name  = "GIT_REF"
      value = "main"
    }
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.dbt.name
    }
  }

  source {
    type      = "NO_SOURCE"
    buildspec = <<-YAML
      version: 0.2
      phases:
        install:
          runtime-versions:
            python: 3.12
          commands:
            - git clone --depth 1 --branch "$GIT_REF" https://github.com/tarodo/clouder-core.git repo
            - pip install -q -r repo/dbt/requirements.txt
        build:
          commands:
            - cd repo/dbt && DBT_PROFILES_DIR=. dbt build --target prod
            - cd repo/dbt && DBT_PROFILES_DIR=. dbt source freshness --target prod || true
    YAML
  }
}

data "aws_iam_policy_document" "transform_states_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "transform_state_machine" {
  name               = "${local.name_prefix}-transform-sfn-role"
  assume_role_policy = data.aws_iam_policy_document.transform_states_assume.json
}

data "aws_iam_policy_document" "transform_state_machine" {
  statement {
    sid       = "AllowRunDbtBuild"
    actions   = ["codebuild:StartBuild", "codebuild:StopBuild", "codebuild:BatchGetBuilds"]
    resources = [aws_codebuild_project.dbt.arn]
  }
  statement {
    sid       = "AllowSyncIntegrationRule"
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:aws:events:${var.aws_region}:${data.aws_caller_identity.current.account_id}:rule/StepFunctionsGetEventForCodeBuildStartBuildRule"]
  }
}

resource "aws_iam_role_policy" "transform_state_machine" {
  name   = "${local.name_prefix}-transform-sfn-policy"
  role   = aws_iam_role.transform_state_machine.id
  policy = data.aws_iam_policy_document.transform_state_machine.json
}

resource "aws_sfn_state_machine" "transform" {
  name     = "${local.name_prefix}-transform"
  role_arn = aws_iam_role.transform_state_machine.arn
  definition = templatefile("${path.module}/transform.asl.json", {
    dbt_project_name = aws_codebuild_project.dbt.name
  })
}

data "aws_iam_policy_document" "transform_events_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "transform_events" {
  name               = "${local.name_prefix}-transform-events-role"
  assume_role_policy = data.aws_iam_policy_document.transform_events_assume.json
}

resource "aws_iam_role_policy" "transform_events" {
  name = "${local.name_prefix}-transform-events-policy"
  role = aws_iam_role.transform_events.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "states:StartExecution", Resource = aws_sfn_state_machine.transform.arn }]
  })
}

# 00:30 UTC: after the catalog export (00:00) and the data-quality checks (00:10).
resource "aws_cloudwatch_event_rule" "transform_nightly" {
  name                = "${local.name_prefix}-transform-nightly"
  schedule_expression = "cron(30 0 * * ? *)"
}

resource "aws_cloudwatch_event_target" "transform_nightly" {
  rule     = aws_cloudwatch_event_rule.transform_nightly.name
  arn      = aws_sfn_state_machine.transform.arn
  role_arn = aws_iam_role.transform_events.arn
}

resource "aws_cloudwatch_metric_alarm" "transform_failed" {
  alarm_name          = "${local.name_prefix}-transform-failed"
  alarm_description   = "Nightly dbt build failed — see docs/data/lakehouse.md"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.transform.arn }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
  ok_actions    = var.alarm_sns_topic_arn != "" ? [var.alarm_sns_topic_arn] : []
}
```

Before writing it, check what `infra/` already defines for `data.aws_caller_identity.current`, `var.aws_region` and `var.athena_workgroup` (`grep -n "aws_caller_identity\|variable \"aws_region\"\|variable \"athena_workgroup\"" infra/*.tf`) and reuse the existing names; record any rename as a ruling.

In `infra/analytics_routes.tf`: add `SILVER_EVENTS_TABLE = "${aws_glue_catalog_database.silver.name}.events"` to the analytics Lambda's environment, and to its IAM policy: `glue:GetDatabase`, `glue:GetTable`, `glue:GetPartitions` on the catalog, `clouder_silver` database and `clouder_silver/*` tables; `s3:GetObject` on `lakehouse/clouder_silver/*` (and `s3:ListBucket` if the policy does not grant it on the lake bucket already).

Append to `infra/outputs.tf`:

```hcl
output "transform_state_machine_arn" {
  description = "Nightly dbt build state machine (docs/data/lakehouse.md)."
  value       = aws_sfn_state_machine.transform.arn
}
```

- [ ] **Step 4: Format and commit**

Run: `terraform -chdir=infra fmt && terraform -chdir=infra fmt -check && echo clean && $VENV/pytest tests/unit/test_transform_state_machine.py -q`
Expected: `clean`, 2 passed.

```bash
git add infra/lakehouse.tf infra/transform.asl.json infra/analytics_routes.tf infra/outputs.tf tests/unit/test_transform_state_machine.py
git commit -m "<caveman-commit output: feat(infra): nightly dbt build on CodeBuild>"
```

---

### Task 7: dbt docs and lineage on GitHub Pages

**Files:**
- Create: `.github/workflows/dbt-docs.yml`

- [ ] **Step 1: Generate the static docs locally**

Run: `cd dbt && DBT_PROFILES_DIR=. $DBT/dbt docs generate --target ci --static && test -s target/static_index.html && echo "docs ok"`
Expected: `docs ok` (the DuckDB fixture database built by Task 4's run provides the catalog).

- [ ] **Step 2: Workflow**

`.github/workflows/dbt-docs.yml`:

```yaml
name: dbt docs

on:
  push:
    branches: [main]
    paths: ['dbt/**', '.github/workflows/dbt-docs.yml']
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  docs:
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deploy.outputs.page_url }}
    defaults:
      run:
        working-directory: dbt
    env:
      DBT_PROFILES_DIR: .
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - name: Build fixtures and generate docs (lineage + column docs; no production data)
        run: |
          dbt seed --target ci
          dbt run --target ci
          dbt docs generate --target ci --static
          mkdir -p site && cp target/static_index.html site/index.html
      - uses: actions/upload-pages-artifact@v3
        with:
          path: dbt/site
      - id: deploy
        uses: actions/deploy-pages@v4
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/dbt-docs.yml
git commit -m "<caveman-commit output: ci(dbt): publish docs and lineage to Pages>"
```

Pages must be enabled with source "GitHub Actions" before the first run: after merge, `gh api -X POST repos/tarodo/clouder-core/pages -f build_type=workflow` (owner-approved in the E scope choice; a `409` means it is already enabled).

---

### Task 8: Docs — lakehouse guide, ADR-0025, references

**Files:**
- Create: `docs/data/lakehouse.md`, `docs/adr/0025-iceberg-dbt-lakehouse.md`, `dbt/README.md`
- Modify: `docs/adr/README.md` (row + next free `0026`), `docs/data/README.md`, `docs/architecture.md`, `docs/ops/runbook.md` (transform failure), `CLAUDE.md` ("Where things are" analytics line, gotcha #13: no longer "no dbt, no marts")

- [ ] **Step 1: Failing doc check**

Run: `for f in docs/data/lakehouse.md docs/adr/0025-iceberg-dbt-lakehouse.md dbt/README.md; do test -f $f || echo "missing $f"; done; grep -c "0025-iceberg" docs/adr/README.md; grep -c "no dbt" CLAUDE.md`
Expected: three `missing`, `0`, and a non-zero "no dbt" count.

- [ ] **Step 2: Write `docs/data/lakehouse.md`**

Sections: **Why** (bronze is append-only small files read in full on every Home-card request; at-least-once delivery with nothing deduplicating; catalog history lost after 14 days; transformation SQL in Lambda code without lineage/tests); **Before (2026-10-07)** — the Spec table verbatim; **What changed** — layer diagram

```
bronze_events ──▶ stg_events ──▶ silver.events (Iceberg, MERGE on event_id, OPTIMIZE) ──▶ gold.fct_play
                                                                                     ▲
bronze_catalog_export ──▶ silver.dim_track_history (SCD2, event-dated) ─────────────┘
```

  plus the nightly run (00:30 UTC, CodeBuild via `clouder-prod-transform`, alarm), the hot/cold read path, tests (unit + data + freshness), CI on DuckDB, docs URL `https://tarodo.github.io/clouder-core/`; **How to run** (`aws stepfunctions start-execution --state-machine-arn $(terraform output -raw transform_state_machine_arn)`, CodeBuild logs, local `dbt build --target ci`, full refresh: `dbt build --target prod --full-refresh --select <model>` from CodeBuild with an override); **After** — table with rows: files and engine time of the same full-table aggregate (bronze vs silver), duplicates removed, SCD2 versions after the first build, dbt build time first vs incremental, Home-card latency (pending until the first production builds); **What it buys**; **Not done, and why** (Non-goals). No money figures.

- [ ] **Step 3: ADR-0025**

`docs/adr/0025-iceberg-dbt-lakehouse.md` in the ADR-0024 format: Context (Before table facts; the owner's explicit choice of the full scope; dbt leftovers had been removed earlier because nothing read the marts — this time the models have a reader: the Home cards via silver, plus SCD2 history that otherwise expires); Options (status quo; plain Athena CTAS/MERGE from a Lambda; dbt-athena + Iceberg; Glue ETL/Spark — too heavy at 6 MB); Decision (Decisions 1–7); Consequences (new runtime in CodeBuild with pinned versions; nightly freshness for silver, live tail from bronze; Iceberg enables row-level DELETE for user deletion (G); VACUUM keeps 5 days of snapshots for time travel; DuckDB CI cannot prove Athena-specific SQL — `dbt parse --target prod` plus the first production build do). Index row in `docs/adr/README.md`, next free number `0026`.

- [ ] **Step 4: References**

- `dbt/README.md`: layout, targets, commands (seed/build/parse/docs), how fixtures stand in for bronze, link to `docs/data/lakehouse.md`.
- `docs/data/README.md`: `- [Lakehouse](lakehouse.md) — dbt + Iceberg silver/gold, SCD2 track history, nightly build.`
- `docs/architecture.md`: add the dbt/CodeBuild + Step Functions node and a Subsystems line.
- `docs/ops/runbook.md`: section "Nightly dbt build failed" (alarm `clouder-prod-transform-failed`, CodeBuild log group `/aws/codebuild/clouder-prod-dbt`, re-run via `start-execution`; Home cards keep working from bronze for the missing day).
- `CLAUDE.md`: analytics bullet mentions silver/gold via dbt; gotcha #13 says "Analytics SQL: live Athena in the Lambda for the cards (hot/cold over silver + bronze) and dbt models in `dbt/` (nightly)".

- [ ] **Step 5: Verify and commit**

Run the Step 1 command again — Expected: no `missing`, `1`, `0`. Then `grep -nE '\$[0-9]|USD|руб' docs/data/lakehouse.md docs/adr/0025-iceberg-dbt-lakehouse.md dbt/README.md | wc -l` → `0`; `$VENV/pytest -q 2>&1 | tail -1` → all pass.

```bash
git add docs dbt/README.md CLAUDE.md
git commit -m "<caveman-commit output: docs(lakehouse): guide, ADR-0025, references>"
graphify update . && git add graphify-out && git commit -m "chore(graphify): refresh graph after lakehouse"
```

---

## After merge (loop follow-up)

1. Enable Pages (`gh api -X POST repos/tarodo/clouder-core/pages -f build_type=workflow`), confirm the `dbt docs` run publishes.
2. Wait for deploy; start `clouder-prod-transform` once by hand; read the CodeBuild log (model timings) — first build = full.
3. Measure: the full-table aggregate on `clouder_silver.events` vs `bronze_events` (files via `SELECT count(*) FROM "clouder_silver"."events$files"`, engine time, bytes); duplicates = bronze count − silver count; SCD2 = versions and tracks with > 1 version; next night's incremental build time; analytics-api p50 over the following days.
4. Fill "After" in `docs/data/lakehouse.md` (docs PR) and the audit status.

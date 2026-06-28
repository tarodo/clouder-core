# CLOUDER analytics — dbt-athena transforms

Bronze (Firehose + daily exports) → **silver** (staging, one model per event family) →
**gold** (star schema). Built daily by Step Functions + EventBridge Scheduler.

## Layout

- `models/silver/` — `stg_*` per event family. JSON-string `context`/`props` parsed with
  `json_extract_scalar`/`json_extract` (NEVER struct/dot access). `incremental` /
  `insert_overwrite` by `dt`; in-model `row_number() over (partition by event_id) = 1` dedup.
- `models/gold/dims/` — `dim_track/artist/label/user/category` + `bridge_track_artist` +
  `dim_date` (Saturday-week per ADR-0003). Dims read the single `bronze_catalog_export`
  table filtered by partition `tbl` (typed JsonSerDe columns, latest `snapshot_dt`).
- `models/gold/facts/` — `fact_track_decision`, `fact_playback`, `fact_seek`,
  `fact_triage_session`, `fact_funnel_step`.
- `macros/` — `saturday_week.sql` (mirrors `src/collector/saturday_week.py`),
  `surrogate_key.sql` (dependency-free; no `dbt_utils`).
- `tests/` — `assert_dim_date_known_weeks.sql` (live Saturday-week pin).

## Version

`dbt-athena-community==1.9.2` pinned in `analytics/requirements.txt`.

## Local setup

```bash
python3.12 -m venv analytics/.dbt-venv
analytics/.dbt-venv/bin/pip install -r analytics/requirements.txt
```

Run offline parse (no AWS creds needed):

```bash
cd analytics/dbt
DBT_PROFILES_DIR=. AWS_REGION=us-east-1 ../../.dbt-venv/bin/dbt parse --profiles-dir .
```

Other useful commands (require AWS creds + live Athena/S3):

```bash
# run all models
DBT_LAKE_BUCKET=<bucket> .dbt-venv/bin/dbt build --project-dir analytics/dbt --profiles-dir analytics/dbt

# run tests only
DBT_LAKE_BUCKET=<bucket> .dbt-venv/bin/dbt test --project-dir analytics/dbt --profiles-dir analytics/dbt

# check source freshness
DBT_LAKE_BUCKET=<bucket> .dbt-venv/bin/dbt source freshness --project-dir analytics/dbt --profiles-dir analytics/dbt
```

## Python mirror tests

The offline test suite lives in `tests/unit/` and requires:

```bash
PYTHONPATH=src:analytics /path/to/.venv/bin/python -m pytest \
  tests/unit/test_saturday_week_dbt_macro.py \
  tests/unit/test_fact_playback_terminal.py \
  tests/unit/test_dbt_runner.py \
  tests/unit/test_analytics_state_machine.py \
  tests/unit/test_catalog_export_handler.py \
  tests/unit/test_ops_log_export_handler.py \
  tests/unit/test_telemetry_schemas.py \
  tests/unit/test_telemetry_handler.py -q
```

`PYTHONPATH=src:analytics` is required — `analytics/` holds `dbt_runner.py`,
`sat_week_mirror.py`, `playback_terminal_mirror.py`, and `state_machine.asl.json`.

## Deploy (image Lambda — build BEFORE apply)

```bash
AWS_REGION=us-east-1 scripts/package_dbt_runner.sh   # build + push :latest to ECR
cd infra && terraform apply                            # ECR, dbt-runner, Step Functions, Scheduler
```

**Increments 1–3 infrastructure must be applied first** (Firehose, Glue catalog, bronze
S3 layout, telemetry Lambda) before the dbt_runner Lambda or Step Functions execution
will succeed.

EventBridge Scheduler fires `beatport-prod-analytics-daily` at 07:00 UTC:
`[catalog_export ‖ ops_log_export] → dbt run → dbt source freshness → dbt test`.
On freshness/test failure the run goes to `Fail`; `insert_overwrite`-by-`dt` means only
today's gold partition is at risk, so dashboards keep serving prior partitions.

## Lineage

`dbt docs generate` emits the DAG (`target/manifest.json` + `index.html`). Run on demand;
`dbt_runner` accepts `{"command":"docs generate"}`.

> ponytail: documented on-demand step, not yet a scheduled `DbtDocs` ASL state — add one if
> the lineage artifact must refresh every run.

## Cross-increment reconciliation (must hold before the DAG is green)

1. Inc-2 must publish the events Glue table as **`bronze_events`** with `context`/`props`
   typed as `string` (the on-disk Inc-2 draft names it `events` with a struct `context`).
2. `track_ids` is in the Inc-2 `PROP_ALLOWLIST` for `playlist_add`/`playlist_publish`
   (locked-contract verified) — the funnel `playlisted`/`published` UNNEST relies on it.
3. `bronze_catalog_export` exposes the §6 column union (extended in `infra/analytics_export.tf`,
   Inc-4) so dims can read `bpm`/`key_name`/`style_id`/etc.

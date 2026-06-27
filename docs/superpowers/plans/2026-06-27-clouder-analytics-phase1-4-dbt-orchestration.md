# Phase 1 · Increment 4 — dbt transforms + orchestration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to execute this plan. Steps use checkbox (- [ ]) syntax.

**Goal:** Build the transform + orchestration layer of the analytics contour: a `dbt-athena` project (`analytics/dbt/`) that turns `bronze_events` / `bronze_catalog_export` / `bronze_ops` into a silver staging layer (one model per event family, `event_id` dedup, `insert_overwrite` by `dt`, JSON-string `context`/`props` parsed with Athena json functions) and a gold star schema (5 facts + 6 dims + 1 bridge + `dim_date` with a Saturday-week macro mirroring `src/collector/saturday_week.py`), gated by dbt schema tests + source freshness; plus the `dbt-runner` container-image Lambda and a Step Functions Standard state machine `[catalog_export ‖ ops_log_export] → dbt_run → dbt source freshness → dbt_test`, fired daily by EventBridge Scheduler.

**Architecture:** dbt-athena (Hive tables, no Iceberg in P1). Silver = `incremental`/`insert_overwrite` partitioned by `dt`, in-model `row_number() over (partition by event_id order by ts_server)=1` dedup. Gold dims = `table`; gold facts = `incremental`/`insert_overwrite` by `dt`. `context`/`props` are **JSON strings** (`json_extract_scalar`/`json_extract` only — never struct/dot access). Catalog dims read the single `bronze_catalog_export` table filtered by partition `tbl`. The `dbt-runner` is the **only** container-image Lambda in the repo (dbt + adapter exceed the 250 MB zip ceiling — the sanctioned new pattern per recon; existing zip Lambdas are untouched). Orchestration is Step Functions Standard (inside the 4 000 free transitions/mo) + EventBridge Scheduler (~30 invocations/mo ≈ $0). Offline TDD gates = four pytest suites (Saturday-week mirror, fact_playback terminal mirror, `dbt_runner` multi-token command, state-machine ASL shape) + `dbt parse`; SQL data-correctness is proven **live** by `dbt test` inside the DAG.

**Tech Stack:** `dbt-athena-community==1.9.5` (recon: PyPI has `1.9.2…1.9.5`; `1.9.0`/`1.9.1` do **not** exist; `1.9.5` is the latest stable `1.9.x` — pinned over the spec's stale `1.9.2`), dbt-core (transitive), Python 3.12 (`/Users/roman/Projects/clouder-projects/clouder-core/.venv` is 3.12.0; a dedicated `.dbt-venv` from `/opt/homebrew/bin/python3.12` runs `dbt parse`), Docker (`public.ecr.aws/lambda/python:3.12` base), Terraform (`aws_ecr_repository`, `aws_lambda_function` `package_type="Image"`, `aws_sfn_state_machine`, `aws_scheduler_schedule`, IAM), pytest with hand-rolled fakes (`PYTHONPATH=src:analytics`, `.venv` at the MAIN repo root).

**Spec:** docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md — §7 (star schema), §8 (dbt models / materializations / fact_playback terminal / funnel unnest / Saturday-week macro / dbt tests), §9 (orchestration DAG), §11 (dashboards → which fact/dim), §17 step 4 (rollout/DoD). Grounded against `src/collector/saturday_week.py` (week-1 algorithm), `frontend/src/features/playback/PlaybackProvider.tsx` (resume-path recon), the real Inc-2 plan (`bronze_events` Glue columns), the real Inc-3 plan (`bronze_catalog_export` `tbl`-partitioned JsonSerDe table; `bronze_ops`), `infra/variables.tf` (`var.aws_region` default `us-east-1`, `name_prefix=beatport-prod`).

---

## Cross-increment contracts & reconciliation (read before Task 1)

These are **inputs**, not built here. Two require a reconciliation note because the on-disk Inc-1–3 drafts disagree with the locked contract:

1. **`bronze_events` name + column shape (BLOCKING dependency).** The locked contract — and this plan — require Glue table **`bronze_events`** with `context` and `props` typed as **`string`** (serialized JSON). The on-disk Inc-2 draft currently declares the table as `events` with `context` as `struct<…>`. **Inc-2 must publish the table as `bronze_events` with `string` `context`/`props` before this DAG runs green.** This plan parses both with `json_extract_scalar`/`json_extract` per the contract (recon fact #4 confirms strings). Documented in `_sources.yml` and the README.
2. **`bronze_catalog_export` is ONE JsonSerDe table** partitioned by `snapshot_dt` (date) + **`tbl`** (enum: `clouder_tracks,clouder_artists,clouder_track_artists,clouder_labels,clouder_albums,categories,category_tracks`). The Inc-3 Glue table declares only `id,title,name,deleted_at,created_at,updated_at` as typed columns; JsonSerDe exposes **only declared columns**, so reading `bpm`/`key_name`/`style_id`/etc. requires those keys to be **declared**. **Task 8 extends `infra/analytics_export.tf`'s `aws_glue_catalog_table.catalog_export` storage_descriptor with the §6 column union** (non-breaking: JsonSerDe null-fills absent keys per row). Dims then select typed columns filtered by `tbl` — no `json_extract` needed because there is no raw `line` column (recon fact #3).
3. **`bronze_ops`** — one table partitioned by `dt`; event name under the `message` key. Not modeled into the star schema (log-backed Dashboard 5, Inc-5); declared as a source only so `dbt parse`/lineage see it.
4. **`track_ids` IS in the Inc-2 `PROP_ALLOWLIST`** for `playlist_add` and `playlist_publish` (locked-contract verified). The funnel `playlisted`/`published` UNNEST is therefore implemented fully — **no deferral, no "unsourced" claim.**
5. **Source names are exactly** `bronze_events`, `bronze_catalog_export`, `bronze_ops`. No `events`/`ops`/`ops_metrics`/`catalog_clouder_*`.

---

## File structure

| File | Create/Modify | One responsibility |
|---|---|---|
| `analytics/dbt/dbt_project.yml` | Create | Project config; folder-level materializations (silver/gold/dims/facts). |
| `analytics/dbt/profiles.yml` | Create | Athena target; `region_name=env_var('AWS_REGION','us-east-1')`; staging/data dirs from env with parse-safe defaults. |
| `analytics/dbt/models/silver/_sources.yml` | Create | Declares `bronze_events`/`bronze_catalog_export`/`bronze_ops`; **freshness rule on `bronze_events`** (error_after 36h). |
| `analytics/dbt/models/silver/stg_track_categorized.sql` | Create | `track_categorized` family → typed, deduped, props parsed. |
| `analytics/dbt/models/silver/stg_track_view.sql` | Create | `track_view` family. |
| `analytics/dbt/models/silver/stg_triage_session.sql` | Create | `triage_session_start`+`triage_session_end` joined per `session_id`. |
| `analytics/dbt/models/silver/stg_playback.sql` | Create | `playback_play/pause/ended/skip` union (feeds terminal matching). |
| `analytics/dbt/models/silver/stg_playback_seek.sql` | Create | `playback_seek` family. |
| `analytics/dbt/models/silver/stg_playlist.sql` | Create | `playlist_add/reorder/publish` (carries raw `track_ids` JSON for unnest). |
| `analytics/dbt/models/silver/_silver.yml` | Create | not_null/unique/accepted_values on silver. |
| `analytics/dbt/macros/saturday_week.sql` | Create | `first_saturday(year)`, `last_saturday_on_or_before(date)` — mirror of `saturday_week.py`. |
| `analytics/dbt/macros/surrogate_key.sql` | Create | Dependency-free surrogate key (`to_hex(md5(to_utf8(…)))`). |
| `analytics/dbt/models/gold/dims/dim_date.sql` | Create | Date spine + Saturday-week + ISO-week columns. |
| `analytics/dbt/models/gold/dims/dim_track.sql` | Create | `tbl='clouder_tracks'` → `dim_track`. |
| `analytics/dbt/models/gold/dims/dim_artist.sql` | Create | `tbl='clouder_artists'` → `dim_artist`. |
| `analytics/dbt/models/gold/dims/bridge_track_artist.sql` | Create | `tbl='clouder_track_artists'` → track↔artist bridge. |
| `analytics/dbt/models/gold/dims/dim_label.sql` | Create | `tbl='clouder_labels'` → `dim_label`. |
| `analytics/dbt/models/gold/dims/dim_user.sql` | Create | distinct `user_id` from silver → `dim_user` (opaque, no PII). |
| `analytics/dbt/models/gold/dims/dim_category.sql` | Create | `tbl='categories'` → `dim_category` (`category_key` per §7). |
| `analytics/dbt/models/gold/facts/fact_track_decision.sql` | Create | one categorize/undo; degenerate `category_key`. |
| `analytics/dbt/models/gold/facts/fact_playback.sql` | Create | per-play grouping + terminal matching (pause→resume→end resolves to end). |
| `analytics/dbt/models/gold/facts/fact_seek.sql` | Create | one row per `playback_seek`. |
| `analytics/dbt/models/gold/facts/fact_triage_session.sql` | Create | one triage session; `undo_rate`. |
| `analytics/dbt/models/gold/facts/fact_funnel_step.sql` | Create | lifecycle steps; `playlisted`/`published` UNNESTed from `track_ids`; `ingested` from catalog. |
| `analytics/dbt/models/gold/_gold.yml` | Create | not_null/unique/accepted_values/**relationships** for gold. |
| `analytics/dbt/tests/assert_dim_date_known_weeks.sql` | Create | Live singular test: pinned dates → expected Saturday-week. |
| `analytics/sat_week_mirror.py` | Create | Python transcription of the `dim_date` Saturday-week arithmetic (offline pin). |
| `analytics/playback_terminal_mirror.py` | Create | Python transcription of `fact_playback` grouping/terminal logic (offline pin). |
| `analytics/dbt_runner.py` | Create | Lambda handler: `event['command'].split()` → `dbtRunner().invoke()` (multi-token `source freshness`). |
| `analytics/state_machine.asl.json` | Create | ASL (valid JSON with `${…}` tokens) — parallel exports → run → freshness → test; Catch → Fail. |
| `analytics/requirements.txt` | Create | `dbt-athena-community==1.9.5`. |
| `analytics/Dockerfile` | Create | `public.ecr.aws/lambda/python:3.12` + deps + dbt project; `CMD dbt_runner.lambda_handler`. |
| `analytics/dbt/README.md` | Create | Layout, version pin, deploy order, lineage on-demand, reconciliation notes. |
| `scripts/package_dbt_runner.sh` | Create | docker build → ECR login → tag → push `:latest`. |
| `infra/analytics_dbt.tf` | Create | ECR repo, `dbt-runner` image Lambda + role, Step Functions + role, EventBridge Scheduler + role. |
| `infra/analytics_export.tf` | **Modify** | Extend `bronze_catalog_export` storage_descriptor columns to the §6 union (contract #2). |
| `tests/unit/test_saturday_week_dbt_macro.py` | Create | Mirror == `saturday_week.week_of_date` over many dates incl. year boundary. |
| `tests/unit/test_fact_playback_terminal.py` | Create | 5 grouping/terminal cases. |
| `tests/unit/test_dbt_runner.py` | Create | Multi-token split, single-token, failure raises. |
| `tests/unit/test_analytics_state_machine.py` | Create | Parallel branches, run→freshness→test order, payload commands, Catch→Fail. |

---

## Tasks

### Task 0: Branch off origin/main

**Files:** none (git only).

- [ ] Local `main` may lag `origin/main` (worktree-stale-main gotcha). Fetch and branch:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve fetch origin
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve checkout -b feat/analytics-dbt-orchestration origin/main
  ```
  Expected: `Switched to a new branch 'feat/analytics-dbt-orchestration'`. (Branch carries no user/agent prefix — CLAUDE.md.)

---

### Task 1: dbt project scaffold + sources + offline `dbt parse` gate

**Files:** Create `analytics/dbt/dbt_project.yml`, `analytics/dbt/profiles.yml`, `analytics/requirements.txt`, `analytics/dbt/models/silver/_sources.yml`. Create the dedicated dbt venv.

- [ ] **Create the dbt venv and install the adapter** (the only network/pip step; the four pytest suites need none of this):
  ```bash
  /opt/homebrew/bin/python3.12 -m venv /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/python -m pip install --quiet --upgrade pip
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/python -m pip install 'dbt-athena-community==1.9.5'
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt --version
  ```
  Expected: `installed: ... athena: 1.9.5` printed (confirms the pin resolves — `1.9.0`/`1.9.1` would 404). If offline, the structural `dbt parse` gate must run in a network-capable env; the pytest gates below are unaffected.

- [ ] **Create `analytics/requirements.txt`** (FULL):
  ```
  dbt-athena-community==1.9.5
  ```

- [ ] **Create `analytics/dbt/dbt_project.yml`** (FULL):
  ```yaml
  name: clouder_analytics
  version: "1.0.0"
  config-version: 2
  profile: clouder_analytics

  model-paths: ["models"]
  macro-paths: ["macros"]
  test-paths: ["tests"]
  target-path: "target"
  clean-targets: ["target", "dbt_packages"]

  vars:
    lookback_days: 3

  models:
    clouder_analytics:
      +materialized: view
      silver:
        +materialized: incremental
        +incremental_strategy: insert_overwrite
        +table_type: hive
        +partitioned_by: ["dt"]
      gold:
        dims:
          +materialized: table
        facts:
          +materialized: incremental
          +incremental_strategy: insert_overwrite
          +table_type: hive
          +partitioned_by: ["dt"]
  ```

- [ ] **Create `analytics/dbt/profiles.yml`** (FULL — MUST-FIX #7: `AWS_REGION` is the Lambda-auto-injected var with the repo's real default `us-east-1`; no dead `AWS_REGION_NAME`; no `AWS_REGION` set in the Lambda env block; `env_var` defaults keep `dbt parse` offline-safe):
  ```yaml
  clouder_analytics:
    target: prod
    outputs:
      prod:
        type: athena
        database: awsdatacatalog
        schema: clouder_analytics
        region_name: "{{ env_var('AWS_REGION', 'us-east-1') }}"
        s3_staging_dir: "{{ env_var('DBT_S3_STAGING_DIR', 's3://placeholder/athena-results/') }}"
        s3_data_dir: "{{ env_var('DBT_S3_DATA_DIR', 's3://placeholder/marts/') }}"
        s3_data_naming: schema_table
        work_group: primary
        threads: 4
  ```
  > `// ponytail:` §5.4's `gold/`/`silver/` S3 prefixes are conceptual — `external_location` is unsupported on incremental models in dbt-athena, so all tables land under `s3_data_dir` (`s3://<lake>/marts/clouder_analytics/<model>/`) and Inc-5 reads them **by Glue catalog name**, not by prefix. Switch to per-model `external_location` only if a lifecycle rule ever needs the literal `gold/` prefix.

- [ ] **Create `analytics/dbt/models/silver/_sources.yml`** (FULL — MUST-FIX #1/#4/#8: exact names, JSON-string columns, freshness on `bronze_events`):
  ```yaml
  version: 2

  sources:
    - name: clouder_analytics
      schema: clouder_analytics
      description: >
        Bronze layer. context/props on bronze_events are JSON STRINGS (parse with
        json_extract_scalar/json_extract — never struct/dot access). bronze_catalog_export
        is ONE JsonSerDe table partitioned by snapshot_dt + tbl. RECONCILIATION: Inc-2 must
        publish the events table as `bronze_events` with string context/props (see README).
      tables:
        - name: bronze_events
          description: Firehose telemetry envelope; partitioned by dt + event_name.
          loaded_at_field: "from_iso8601_timestamp(ts_server)"
          freshness:
            warn_after: { count: 30, period: hour }
            error_after: { count: 36, period: hour }
          columns:
            - name: event_id
            - name: session_id
            - name: ts_server
            - name: ts_client
            - name: context
              description: JSON string {user_id,device,route,app_version}.
            - name: props
              description: JSON string, per-event fields.
            - name: dt
            - name: event_name
        - name: bronze_catalog_export
          description: One table; one row per Aurora dict; partitioned by snapshot_dt + tbl.
          columns:
            - name: snapshot_dt
            - name: tbl
        - name: bronze_ops
          description: Log-backed ops metrics (Dashboard 5, Inc-5); not modeled into the star schema.
          columns:
            - name: dt
  ```

- [ ] **Run `dbt parse`, expect PASS** (sources resolve, no models yet):
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: last line contains `Wrote manifest to` and exit code 0.

- [ ] **Commit.** Generate the subject with `caveman:caveman-commit` (CLAUDE.md forbids hand-written subjects), then commit with a non-indented heredoc body (EOF at column 0, no `Co-Authored-By`):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add analytics/dbt/dbt_project.yml analytics/dbt/profiles.yml analytics/requirements.txt analytics/dbt/models/silver/_sources.yml
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): scaffold dbt-athena project + bronze sources

  dbt-athena-community 1.9.5; sources bronze_events/bronze_catalog_export/
  bronze_ops with freshness on bronze_events; context/props are JSON strings.
  EOF
  )"
  ```
  (Subject illustrative — use the caveman-commit output.) Expected: `4 files changed`.

---

### Task 2: Saturday-week macros + `dim_date` (RED→GREEN on the Python mirror)

**Files:** Create `tests/unit/test_saturday_week_dbt_macro.py`, `analytics/sat_week_mirror.py`, `analytics/dbt/macros/saturday_week.sql`, `analytics/dbt/macros/surrogate_key.sql`, `analytics/dbt/models/gold/dims/dim_date.sql`, `analytics/dbt/tests/assert_dim_date_known_weeks.sql`.

- [ ] **Write the failing test** `tests/unit/test_saturday_week_dbt_macro.py` (FULL). It pins the `dim_date` SQL arithmetic (transcribed in `sat_week_mirror.py`) against the canonical `collector.saturday_week.week_of_date`:
  ```python
  from datetime import date, timedelta

  import pytest

  from collector.saturday_week import week_of_date
  from sat_week_mirror import saturday_week_of  # Python transcription of dim_date.sql


  def _all_days(y0: int, y1: int):
      d = date(y0, 1, 1)
      end = date(y1, 12, 31)
      while d <= end:
          yield d
          d += timedelta(days=1)


  @pytest.mark.parametrize("d", list(_all_days(2024, 2031)))
  def test_mirror_matches_canonical_every_day(d):
      assert saturday_week_of(d) == week_of_date(d)


  @pytest.mark.parametrize(
      "d",
      [
          date(2026, 1, 1),   # Thu -> belongs to 2025's last week
          date(2026, 1, 2),   # Fri -> still 2025
          date(2026, 1, 3),   # Sat -> 2026 week 1 (first Saturday on/after Jan 1)
          date(2027, 1, 1),   # Fri
          date(2027, 1, 2),   # Sat -> 2027 week 1
          date(2022, 1, 1),   # Sat -> 2022 week 1 (Jan 1 itself is a Saturday)
      ],
  )
  def test_year_boundary_known_dates(d):
      assert saturday_week_of(d) == week_of_date(d)
  ```

- [ ] **Run it, expect FAIL** (mirror module missing):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_saturday_week_dbt_macro.py -q
  ```
  Expected: collection error, `ModuleNotFoundError: No module named 'sat_week_mirror'`, summary `1 error` (exit 2).

- [ ] **Write `analytics/sat_week_mirror.py`** (FULL — exact transcription of the `dim_date.sql` CTE arithmetic below; `isoweekday()` Mon=1..Sun=7 matches Athena `day_of_week`):
  ```python
  """Python transcription of the dim_date.sql Saturday-week arithmetic.

  This is a CONTRACT-PINNING MIRROR: it must compute byte-identical week numbers to
  the SQL in models/gold/dims/dim_date.sql so the offline test can verify the
  algorithm against the canonical src/collector/saturday_week.py. SQL correctness is
  additionally proven live by tests/assert_dim_date_known_weeks.sql in dbt_test.
  """
  from __future__ import annotations

  from datetime import date, timedelta


  def _last_saturday_on_or_before(d: date) -> date:
      delta = ((d.isoweekday() - 6) % 7 + 7) % 7  # Athena: ((day_of_week-6)%7+7)%7
      return d - timedelta(days=delta)


  def _first_saturday(year: int) -> date:
      jan1 = date(year, 1, 1)
      off = ((6 - jan1.isoweekday()) % 7 + 7) % 7  # Athena: ((6-day_of_week(jan1))%7+7)%7
      return jan1 + timedelta(days=off)


  def saturday_week_of(d: date) -> tuple[int, int]:
      saturday = _last_saturday_on_or_before(d)
      fs_curr = _first_saturday(saturday.year)
      if saturday < fs_curr:
          fs_prev = _first_saturday(saturday.year - 1)
          return (saturday.year - 1, (saturday - fs_prev).days // 7 + 1)
      return (saturday.year, (saturday - fs_curr).days // 7 + 1)
  ```

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_saturday_week_dbt_macro.py -q
  ```
  Expected: last line `2928 passed` (2922 daily params + 6 boundary cases; exit 0). If the count differs, it is the day-range arithmetic — the assertion content is what matters.

- [ ] **Write `analytics/dbt/macros/saturday_week.sql`** (FULL — the SQL the mirror transcribes):
  ```sql
  {% macro last_saturday_on_or_before(d) -%}
  date_add('day', -(((day_of_week({{ d }}) - 6) % 7 + 7) % 7), {{ d }})
  {%- endmacro %}

  {% macro first_saturday(year_expr) -%}
  date_add(
    'day',
    ((6 - day_of_week(cast(concat(cast({{ year_expr }} as varchar), '-01-01') as date))) % 7 + 7) % 7,
    cast(concat(cast({{ year_expr }} as varchar), '-01-01') as date)
  )
  {%- endmacro %}
  ```

- [ ] **Write `analytics/dbt/macros/surrogate_key.sql`** (FULL — dependency-free; no `dbt_utils` package):
  ```sql
  {% macro surrogate_key(cols) -%}
  to_hex(md5(to_utf8(concat_ws('||'
    {%- for c in cols %}, coalesce(cast({{ c }} as varchar), '__NULL__'){% endfor -%}
  ))))
  {%- endmacro %}
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/dim_date.sql`** (FULL — Saturday-week per ADR-0003 + ISO-week columns; `iso_week_year` via the week's Thursday):
  ```sql
  with spine as (
      select d as date
      from unnest(sequence(date '2024-01-01', date '2031-12-31', interval '1' day)) as t (d)
  ),
  sat as (
      select date, {{ last_saturday_on_or_before('date') }} as saturday from spine
  ),
  computed as (
      select
          date,
          saturday,
          year(saturday) as sat_year,
          {{ first_saturday('year(saturday)') }} as fs_curr,
          {{ first_saturday('year(saturday) - 1') }} as fs_prev
      from sat
  )
  select
      cast(date_format(date, '%Y%m%d') as integer) as date_key,
      date,
      case when saturday < fs_curr then sat_year - 1 else sat_year end as saturday_week_year,
      case
          when saturday < fs_curr then (date_diff('day', fs_prev, saturday) / 7) + 1
          else (date_diff('day', fs_curr, saturday) / 7) + 1
      end as saturday_week_number,
      year(date_add('day', 4 - day_of_week(date), date)) as iso_week_year,
      week(date) as iso_week_number,
      day_of_week(date) as day_of_week,
      month(date) as month,
      quarter(date) as quarter,
      year(date) as year
  from computed
  ```

- [ ] **Write `analytics/dbt/tests/assert_dim_date_known_weeks.sql`** (FULL — live singular test; returns rows only on mismatch, so it fails the run if the SQL ever diverges from the canonical week-1 rule):
  ```sql
  -- Live contract pin: known Saturday-week boundaries (mirrors saturday_week.py).
  with expected (date, saturday_week_year, saturday_week_number) as (
      values
          (date '2026-01-02', 2025, 53),  -- Fri before first Saturday -> prev year
          (date '2026-01-03', 2026, 1),   -- first Saturday on/after Jan 1
          (date '2026-01-09', 2026, 1),   -- Friday of week 1
          (date '2026-01-10', 2026, 2),
          (date '2022-01-01', 2022, 1)    -- Jan 1 is itself a Saturday
  )
  select e.date
  from expected e
  join {{ ref('dim_date') }} d on d.date = e.date
  where d.saturday_week_year <> e.saturday_week_year
     or d.saturday_week_number <> e.saturday_week_number
  ```

- [ ] **Run `dbt parse`, expect PASS** (macros + dim_date + singular test compile):
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: `Wrote manifest to`, exit 0.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add tests/unit/test_saturday_week_dbt_macro.py analytics/sat_week_mirror.py analytics/dbt/macros/saturday_week.sql analytics/dbt/macros/surrogate_key.sql analytics/dbt/models/gold/dims/dim_date.sql analytics/dbt/tests/assert_dim_date_known_weeks.sql
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add dim_date with Saturday-week macro

  Mirror src/collector/saturday_week.py (week 1 = first Saturday on/after
  Jan 1). Python mirror pins the algorithm offline; a singular dbt test
  pins known boundaries live. Dependency-free surrogate_key macro.
  EOF
  )"
  ```
  Expected: `6 files changed`.

---

### Task 3: Silver staging models (one per event family) + silver tests

**Files:** Create the six `stg_*.sql` + `analytics/dbt/models/silver/_silver.yml`. Every model: parse `context`/`props` JSON strings (MUST-FIX #2), dedup `row_number() over (partition by event_id order by ts_server)=1`, `dt` last column for `insert_overwrite`.

- [ ] **Write `analytics/dbt/models/silver/stg_track_categorized.sql`** (FULL):
  ```sql
  with src as (
      select
          event_id,
          session_id,
          ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.track_id') as track_id,
          try_cast(json_extract_scalar(props, '$.decision_ms') as bigint) as decision_ms,
          json_extract_scalar(props, '$.category_key') as category_key,
          json_extract_scalar(props, '$.action') as action,
          coalesce(
              json_extract_scalar(props, '$.surface'),
              case json_extract_scalar(props, '$.action')
                  when 'moved_to_bucket' then 'triage'
                  when 'categorized_curate' then 'curate'
              end
          ) as surface,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name = 'track_categorized'
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from src
  )
  select event_id, session_id, ts_server, user_id, track_id, decision_ms,
         category_key, action, surface, dt
  from deduped
  where rn = 1
  ```

- [ ] **Write `analytics/dbt/models/silver/stg_track_view.sql`** (FULL):
  ```sql
  with src as (
      select
          event_id,
          session_id,
          ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.track_id') as track_id,
          try_cast(json_extract_scalar(props, '$.dwell_ms') as bigint) as dwell_ms,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name = 'track_view'
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from src
  )
  select event_id, session_id, ts_server, user_id, track_id, dwell_ms, dt
  from deduped where rn = 1
  ```

- [ ] **Write `analytics/dbt/models/silver/stg_triage_session.sql`** (FULL — join start↔end per `session_id`; end carries the metrics):
  ```sql
  with ev as (
      select
          event_id, event_name, session_id, ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.block_id') as block_id,
          json_extract_scalar(props, '$.bucket_id') as bucket_id,
          try_cast(json_extract_scalar(props, '$.session_ms') as bigint) as session_ms,
          try_cast(json_extract_scalar(props, '$.tracks_seen') as bigint) as tracks_seen,
          try_cast(json_extract_scalar(props, '$.tracks_categorized') as bigint) as tracks_categorized,
          try_cast(json_extract_scalar(props, '$.undo_rate') as double) as undo_rate,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name in ('triage_session_start', 'triage_session_end')
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from ev
  ),
  starts as (
      select session_id, user_id, block_id, bucket_id, ts_server as ts_start
      from deduped where rn = 1 and event_name = 'triage_session_start'
  ),
  ends as (
      select session_id, ts_server as ts_end, session_ms, tracks_seen,
             tracks_categorized, undo_rate, dt
      from deduped where rn = 1 and event_name = 'triage_session_end'
  )
  select
      e.session_id, s.user_id, s.block_id, s.bucket_id,
      s.ts_start, e.ts_end, e.session_ms, e.tracks_seen, e.tracks_categorized,
      e.undo_rate, e.dt
  from ends e
  left join starts s on s.session_id = e.session_id
  ```

- [ ] **Write `analytics/dbt/models/silver/stg_playback.sql`** (FULL — union of the 4 playback families; keeps `position_ms`/`duration_ms`/`listen_through_ratio` for terminal matching):
  ```sql
  with src as (
      select
          event_id,
          event_name,
          session_id,
          ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.track_id') as track_id,
          json_extract_scalar(props, '$.source') as source,
          try_cast(json_extract_scalar(props, '$.position_ms') as bigint) as position_ms,
          try_cast(json_extract_scalar(props, '$.duration_ms') as bigint) as duration_ms,
          try_cast(json_extract_scalar(props, '$.listen_through_ratio') as double) as listen_through_ratio,
          try_cast(json_extract_scalar(props, '$.seek_count') as bigint) as seek_count,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name in ('playback_play', 'playback_pause', 'playback_ended', 'playback_skip')
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from src
  )
  select event_id, event_name, session_id, ts_server, user_id, track_id, source,
         position_ms, duration_ms, listen_through_ratio, seek_count, dt
  from deduped where rn = 1
  ```

- [ ] **Write `analytics/dbt/models/silver/stg_playback_seek.sql`** (FULL):
  ```sql
  with src as (
      select
          event_id,
          session_id,
          ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.track_id') as track_id,
          try_cast(json_extract_scalar(props, '$.from_position_ms') as bigint) as from_position_ms,
          try_cast(json_extract_scalar(props, '$.to_position_ms') as bigint) as to_position_ms,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name = 'playback_seek'
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from src
  )
  select event_id, session_id, ts_server, user_id, track_id,
         from_position_ms, to_position_ms, dt
  from deduped where rn = 1
  ```

- [ ] **Write `analytics/dbt/models/silver/stg_playlist.sql`** (FULL — keeps raw `track_ids` as an `array(varchar)` for the funnel unnest; MUST-FIX #3):
  ```sql
  with src as (
      select
          event_id,
          event_name,
          session_id,
          ts_server,
          json_extract_scalar(context, '$.user_id') as user_id,
          json_extract_scalar(props, '$.playlist_id') as playlist_id,
          cast(json_extract(props, '$.track_ids') as array(varchar)) as track_ids,
          try_cast(json_extract_scalar(props, '$.track_count') as bigint) as track_count,
          json_extract_scalar(props, '$.target') as target,
          dt
      from {{ source('clouder_analytics', 'bronze_events') }}
      where event_name in ('playlist_add', 'playlist_reorder', 'playlist_publish')
      {% if is_incremental() %}
      and dt >= date_format(date_add('day', -{{ var('lookback_days') }}, current_date), '%Y-%m-%d')
      {% endif %}
  ),
  deduped as (
      select *, row_number() over (partition by event_id order by ts_server) as rn from src
  )
  select event_id, event_name, session_id, ts_server, user_id, playlist_id,
         track_ids, track_count, target, dt
  from deduped where rn = 1
  ```
  > `// ponytail:` no `stg_hotkey` model — `hotkey_used` has no P1 fact/dashboard consumer (keystroke telemetry only, §3.2). Add one when a dashboard needs it.

- [ ] **Write `analytics/dbt/models/silver/_silver.yml`** (FULL — dedup + parse contract):
  ```yaml
  version: 2

  models:
    - name: stg_track_categorized
      columns:
        - name: event_id
          tests: [not_null, unique]
        - name: action
          tests:
            - accepted_values: { values: ["moved_to_bucket", "categorized_curate", "undo"] }
        - name: surface
          tests:
            - accepted_values: { values: ["triage", "curate"], config: { where: "surface is not null" } }
    - name: stg_track_view
      columns:
        - name: event_id
          tests: [not_null, unique]
    - name: stg_triage_session
      columns:
        - name: session_id
          tests: [not_null, unique]
    - name: stg_playback
      columns:
        - name: event_id
          tests: [not_null, unique]
        - name: event_name
          tests:
            - accepted_values: { values: ["playback_play", "playback_pause", "playback_ended", "playback_skip"] }
    - name: stg_playback_seek
      columns:
        - name: event_id
          tests: [not_null, unique]
    - name: stg_playlist
      columns:
        - name: event_id
          tests: [not_null, unique]
        - name: event_name
          tests:
            - accepted_values: { values: ["playlist_add", "playlist_reorder", "playlist_publish"] }
  ```

- [ ] **Run `dbt parse`, expect PASS** (all six silver models + tests compile):
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: `Wrote manifest to`, exit 0.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add analytics/dbt/models/silver/
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add silver staging models per event family

  Parse JSON-string context/props with json_extract_scalar/json_extract,
  dedup row_number() over event_id, insert_overwrite by dt. No struct access.
  EOF
  )"
  ```
  Expected: `7 files changed`.

---

### Task 4: Gold dimensions + bridge

**Files:** Create the six dim/bridge models. Dims read `bronze_catalog_export` filtered by partition `tbl` (typed JsonSerDe columns — no `json_extract`, no raw `line` column; contract #2). `dim_user` from silver. Surrogate keys via the `surrogate_key` macro (consistent with facts).

- [ ] **Write `analytics/dbt/models/gold/dims/dim_track.sql`** (FULL — `latest snapshot only`; `style_id` aliased to `genre/style_id` intent per §7):
  ```sql
  with latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'clouder_tracks'
  ),
  src as (
      select id, title, bpm, key_name, key_camelot, style_id,
             spotify_release_date, publish_date, album_id, isrc,
             release_type, is_ai_suspected, origin
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join latest l
      where c.tbl = 'clouder_tracks' and c.snapshot_dt = l.snapshot_dt
  )
  select
      {{ surrogate_key(['id']) }} as track_key,
      id as track_id,
      title,
      try_cast(bpm as integer) as bpm,
      key_name,
      key_camelot,
      style_id,
      coalesce(try_cast(spotify_release_date as date), try_cast(publish_date as date)) as release_date,
      album_id,
      isrc,
      release_type,
      cast(is_ai_suspected as boolean) as is_ai_suspected,
      origin
  from src
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/dim_artist.sql`** (FULL):
  ```sql
  with latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'clouder_artists'
  ),
  src as (
      select id, name, normalized_name, is_ai_suspected
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join latest l
      where c.tbl = 'clouder_artists' and c.snapshot_dt = l.snapshot_dt
  )
  select
      {{ surrogate_key(['id']) }} as artist_key,
      id as artist_id,
      name,
      normalized_name,
      cast(is_ai_suspected as boolean) as is_ai_suspected
  from src
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/bridge_track_artist.sql`** (FULL — `clouder_track_artists` junction; keys match dim_track/dim_artist):
  ```sql
  with latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'clouder_track_artists'
  ),
  src as (
      select track_id, artist_id, role
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join latest l
      where c.tbl = 'clouder_track_artists' and c.snapshot_dt = l.snapshot_dt
  )
  select
      {{ surrogate_key(['track_id']) }} as track_key,
      {{ surrogate_key(['artist_id']) }} as artist_key,
      role
  from src
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/dim_label.sql`** (FULL):
  ```sql
  with latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'clouder_labels'
  ),
  src as (
      select id, name, normalized_name
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join latest l
      where c.tbl = 'clouder_labels' and c.snapshot_dt = l.snapshot_dt
  )
  select
      {{ surrogate_key(['id']) }} as label_key,
      id as label_id,
      name,
      normalized_name
  from src
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/dim_user.sql`** (FULL — sourced from event `user_id` per §6; opaque, no PII):
  ```sql
  with ids as (
      select user_id from {{ ref('stg_track_categorized') }} where user_id is not null
      union
      select user_id from {{ ref('stg_track_view') }} where user_id is not null
      union
      select user_id from {{ ref('stg_triage_session') }} where user_id is not null
      union
      select user_id from {{ ref('stg_playback') }} where user_id is not null
      union
      select user_id from {{ ref('stg_playback_seek') }} where user_id is not null
      union
      select user_id from {{ ref('stg_playlist') }} where user_id is not null
  )
  select {{ surrogate_key(['user_id']) }} as user_key, user_id
  from (select distinct user_id from ids)
  ```

- [ ] **Write `analytics/dbt/models/gold/dims/dim_category.sql`** (FULL — from `categories` per MUST-FIX #6; `category_key` is the §7 surrogate PK; **`category_tracks` is NOT used here** — it is only the membership junction, deliberately unmodeled in P1):
  ```sql
  with latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'categories'
  ),
  src as (
      select id, user_id, style_id, name, normalized_name, position, deleted_at
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join latest l
      where c.tbl = 'categories' and c.snapshot_dt = l.snapshot_dt
  )
  select
      {{ surrogate_key(['id']) }} as category_key,
      id as category_id,
      user_id,
      style_id,
      name,
      normalized_name,
      try_cast(position as integer) as position,
      deleted_at
  from src
  ```
  > `// ponytail:` `dim_category.category_key` (surrogate) and `fact_track_decision.category_key` (degenerate bucket-type string, §7) intentionally share a NAME but **not a domain** — no `relationships` test joins them. `category_tracks` membership bridge is unmodeled until a dashboard needs category membership.

- [ ] **Run `dbt parse`, expect PASS** (dims + bridge compile; refs to silver resolve):
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: `Wrote manifest to`, exit 0.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add analytics/dbt/models/gold/dims/
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add gold dimensions from bronze_catalog_export

  dim_track/artist/label/user/category + track-artist bridge, read from the
  single bronze_catalog_export table filtered by tbl (latest snapshot).
  EOF
  )"
  ```
  Expected: `6 files changed`.

---

### Task 5: `fact_playback` terminal matching (RED→GREEN mirror) + the three passthrough facts

**Files:** Create `tests/unit/test_fact_playback_terminal.py`, `analytics/playback_terminal_mirror.py`, `fact_playback.sql`, `fact_seek.sql`, `fact_triage_session.sql`, `fact_track_decision.sql`.

**Recon finding (state it in the model comment):** `PlaybackProvider.togglePlayPause` emits a **fresh `playback_play`** on local resume (idle/ended, and paused-with-no-expected-track → `play()`), but a **remote-device resume calls `spotifyApi.resume()` and emits NO `playback_play`** (PlaybackProvider.tsx ~L443). So grouping by a running `playback_play` count is correct for both: local resume = a new play row (play re-emitted); remote resume = the same play row whose terminal still resolves to the later end/skip.

- [ ] **Write the failing test** `tests/unit/test_fact_playback_terminal.py` (FULL):
  ```python
  import pytest

  from playback_terminal_mirror import resolve_plays


  def ev(name, ts, **kw):
      return {"event_name": name, "ts_server": ts, **kw}


  def test_remote_resume_no_replay_resolves_to_end():
      # play, pause, (remote resume = NO playback_play), end -> ONE play, terminal=end
      events = [
          ev("playback_play", 1, duration_ms=200000, source="triage_player"),
          ev("playback_pause", 2, position_ms=50000),
          ev("playback_ended", 3, duration_ms=200000, listen_through_ratio=0.98),
      ]
      plays = resolve_plays(events)
      assert len(plays) == 1
      assert plays[0]["terminal"] == "playback_ended"
      assert plays[0]["skipped"] is False
      assert plays[0]["listen_through_ratio"] == pytest.approx(0.98)


  def test_local_resume_emits_new_play_two_rows():
      # play, pause, play (local resume re-emit), end -> TWO plays; 2nd resolves to end
      events = [
          ev("playback_play", 1, duration_ms=200000, source="triage_player"),
          ev("playback_pause", 2, position_ms=50000),
          ev("playback_play", 3, duration_ms=200000, source="triage_player"),
          ev("playback_ended", 4, duration_ms=200000, listen_through_ratio=1.0),
      ]
      plays = resolve_plays(events)
      assert len(plays) == 2
      assert plays[0]["terminal"] == "playback_pause"
      assert plays[0]["played_ms"] == 50000
      assert plays[1]["terminal"] == "playback_ended"


  def test_skip_marks_skipped():
      events = [
          ev("playback_play", 1, duration_ms=200000, source="playlist_player"),
          ev("playback_skip", 2, position_ms=12000, duration_ms=200000),
      ]
      plays = resolve_plays(events)
      assert plays[0]["skipped"] is True
      assert plays[0]["played_ms"] == 12000


  def test_pause_only_terminal_is_pause():
      events = [
          ev("playback_play", 1, duration_ms=200000, source="category_player"),
          ev("playback_pause", 2, position_ms=30000),
      ]
      plays = resolve_plays(events)
      assert len(plays) == 1
      assert plays[0]["terminal"] == "playback_pause"
      assert plays[0]["skipped"] is False


  def test_ended_played_ms_from_ratio_when_no_position():
      # playback_ended carries no position_ms (only listen_through_ratio + duration)
      events = [
          ev("playback_play", 1, duration_ms=100000, source="triage_player"),
          ev("playback_ended", 2, duration_ms=100000, listen_through_ratio=0.5),
      ]
      plays = resolve_plays(events)
      assert plays[0]["played_ms"] == 50000
  ```

- [ ] **Run it, expect FAIL** (mirror module missing):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_fact_playback_terminal.py -q
  ```
  Expected: collection error, `ModuleNotFoundError: No module named 'playback_terminal_mirror'`, summary `1 error` (exit 2).

- [ ] **Write `analytics/playback_terminal_mirror.py`** (FULL — transcription of the `fact_playback.sql` algorithm: running `playback_play` count groups plays; terminal = priority(ended/skip) then latest):
  ```python
  """Python transcription of fact_playback.sql per-play grouping + terminal selection.

  CONTRACT-PINNING MIRROR (offline) of the SQL. ASSUMPTION (recon, PlaybackProvider.tsx):
  playback_play is emitted at track start AND on LOCAL pause->resume (togglePlayPause ->
  play()), but NOT on REMOTE-device resume (spotifyApi.resume() bypasses play()). Grouping
  by a running playback_play count therefore makes a local resume a new play row, while a
  remote resume stays in the same group whose terminal still resolves to the later end/skip.
  ponytail: if remote resume ever starts emitting playback_play, the running-count grouping
  still holds (it just splits into a new group).
  """
  from __future__ import annotations

  _TERMINAL_PRIORITY = {"playback_ended": 0, "playback_skip": 0, "playback_pause": 1}


  def resolve_plays(events: list[dict]) -> list[dict]:
      ordered = sorted(events, key=lambda e: e["ts_server"])
      groups: list[dict] = []
      current: dict | None = None
      for e in ordered:
          if e["event_name"] == "playback_play":
              current = {"play": e, "events": []}
              groups.append(current)
          elif current is not None:
              current["events"].append(e)

      plays: list[dict] = []
      for g in groups:
          non_play = g["events"]
          if not non_play:
              continue  # play with no terminal yet (open) -> not a completed play row
          terminal = sorted(
              non_play,
              key=lambda e: (_TERMINAL_PRIORITY.get(e["event_name"], 2), -e["ts_server"]),
          )[0]
          duration_ms = g["play"].get("duration_ms")
          ratio = terminal.get("listen_through_ratio")
          position = terminal.get("position_ms")
          if position is None and ratio is not None and duration_ms is not None:
              position = int(ratio * duration_ms)
          played_ms = position
          if ratio is None and played_ms is not None and duration_ms:
              ratio = played_ms / duration_ms
          plays.append({
              "terminal": terminal["event_name"],
              "skipped": terminal["event_name"] == "playback_skip",
              "played_ms": played_ms,
              "duration_ms": duration_ms,
              "listen_through_ratio": ratio,
              "source": g["play"].get("source"),
          })
      return plays
  ```

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_fact_playback_terminal.py -q
  ```
  Expected: last line `5 passed` (exit 0).

- [ ] **Write `analytics/dbt/models/gold/facts/fact_playback.sql`** (FULL — the SQL the mirror transcribes; `dt` last for `insert_overwrite`):
  ```sql
  -- One play = one playback_play matched to its terminal (pause/end/skip) within
  -- (session_id, track_id). Grouping by a running playback_play count: LOCAL resume
  -- re-emits playback_play (new play row); REMOTE resume (spotifyApi.resume) does NOT
  -- (same group, terminal resolves to the later end/skip). See PlaybackProvider.tsx recon.
  with pb as (
      select * from {{ ref('stg_playback') }}
  ),
  grouped as (
      select *,
          sum(case when event_name = 'playback_play' then 1 else 0 end)
              over (partition by session_id, track_id order by ts_server
                    rows between unbounded preceding and current row) as play_group
      from pb
  ),
  plays as (
      select session_id, track_id, play_group,
             max(user_id) as user_id,
             max(case when event_name = 'playback_play' then source end) as source,
             max(case when event_name = 'playback_play' then duration_ms end) as duration_ms,
             min(case when event_name = 'playback_play' then ts_server end) as play_ts
      from grouped
      group by session_id, track_id, play_group
  ),
  terminals as (
      select session_id, track_id, play_group, event_name, ts_server,
             position_ms, listen_through_ratio,
             row_number() over (
                 partition by session_id, track_id, play_group
                 order by case when event_name in ('playback_ended', 'playback_skip') then 0 else 1 end,
                          ts_server desc
             ) as rn
      from grouped
      where event_name <> 'playback_play'
  ),
  seeks as (
      select session_id, track_id, count(*) as seek_count
      from {{ ref('stg_playback_seek') }}
      group by session_id, track_id
  ),
  joined as (
      select
          p.session_id, p.track_id, p.play_group, p.user_id, p.source, p.duration_ms, p.play_ts,
          t.event_name as terminal, t.position_ms, t.listen_through_ratio, t.ts_server as terminal_ts,
          coalesce(s.seek_count, 0) as seek_count
      from plays p
      join terminals t
        on t.session_id = p.session_id and t.track_id = p.track_id
       and t.play_group = p.play_group and t.rn = 1
      left join seeks s on s.session_id = p.session_id and s.track_id = p.track_id
  )
  select
      {{ surrogate_key(['session_id', 'track_id', 'play_group']) }} as playback_key,
      {{ surrogate_key(['session_id', 'track_id', 'play_group']) }} as event_id,
      {{ surrogate_key(['user_id']) }} as user_key,
      {{ surrogate_key(['track_id']) }} as track_key,
      cast(date_format(from_iso8601_timestamp(terminal_ts), '%Y%m%d') as integer) as date_key,
      source,
      coalesce(position_ms, cast(listen_through_ratio * duration_ms as bigint)) as played_ms,
      duration_ms,
      coalesce(
          listen_through_ratio,
          try(cast(coalesce(position_ms, 0) as double) / nullif(duration_ms, 0))
      ) as listen_through_ratio,
      seek_count,
      terminal = 'playback_skip' as skipped,
      terminal_ts as ts_server,
      date_format(from_iso8601_timestamp(terminal_ts), '%Y-%m-%d') as dt
  from joined
  ```

- [ ] **Write `analytics/dbt/models/gold/facts/fact_seek.sql`** (FULL):
  ```sql
  select
      {{ surrogate_key(['event_id']) }} as seek_key,
      event_id,
      {{ surrogate_key(['user_id']) }} as user_key,
      {{ surrogate_key(['track_id']) }} as track_key,
      cast(date_format(from_iso8601_timestamp(ts_server), '%Y%m%d') as integer) as date_key,
      from_position_ms,
      to_position_ms,
      ts_server,
      date_format(from_iso8601_timestamp(ts_server), '%Y-%m-%d') as dt
  from {{ ref('stg_playback_seek') }}
  ```

- [ ] **Write `analytics/dbt/models/gold/facts/fact_triage_session.sql`** (FULL — `undo_count` from triage `track_categorized(undo)` in the session; `undo_rate` passthrough):
  ```sql
  with undos as (
      select session_id, count(*) as undo_count
      from {{ ref('stg_track_categorized') }}
      where action = 'undo' and surface = 'triage'
      group by session_id
  )
  select
      {{ surrogate_key(['s.session_id']) }} as session_key,
      s.session_id,
      {{ surrogate_key(['s.user_id']) }} as user_key,
      s.block_id,
      s.bucket_id,
      cast(date_format(from_iso8601_timestamp(s.ts_end), '%Y%m%d') as integer) as date_key,
      s.session_ms,
      s.tracks_seen,
      s.tracks_categorized,
      coalesce(u.undo_count, 0) as undo_count,
      s.undo_rate,
      s.ts_start,
      s.ts_end,
      s.dt
  from {{ ref('stg_triage_session') }} s
  left join undos u on u.session_id = s.session_id
  ```

- [ ] **Write `analytics/dbt/models/gold/facts/fact_track_decision.sql`** (FULL — `category_key` kept as a degenerate attribute per §7/MUST-FIX #6; `dwell_ms` null in P1, the decision event carries none — it lives on `track_view`):
  ```sql
  select
      {{ surrogate_key(['event_id']) }} as decision_key,
      event_id,
      {{ surrogate_key(['user_id']) }} as user_key,
      {{ surrogate_key(['track_id']) }} as track_key,
      category_key,  -- degenerate dimension (bucket_type string), NOT a dim_category FK
      cast(date_format(from_iso8601_timestamp(ts_server), '%Y%m%d') as integer) as date_key,
      decision_ms,
      cast(null as bigint) as dwell_ms,  -- ponytail: dwell lives on track_view in P1 (§7)
      action,
      surface,
      ts_server,
      date_format(from_iso8601_timestamp(ts_server), '%Y-%m-%d') as dt
  from {{ ref('stg_track_categorized') }}
  ```

- [ ] **Run `dbt parse`, expect PASS**:
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: `Wrote manifest to`, exit 0.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add tests/unit/test_fact_playback_terminal.py analytics/playback_terminal_mirror.py analytics/dbt/models/gold/facts/fact_playback.sql analytics/dbt/models/gold/facts/fact_seek.sql analytics/dbt/models/gold/facts/fact_triage_session.sql analytics/dbt/models/gold/facts/fact_track_decision.sql
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add playback/seek/triage/decision facts

  fact_playback groups per-play via running playback_play count and selects
  the true terminal (pause->resume->end resolves to end; skipped only when
  terminal is playback_skip). Python mirror pins the grouping offline.
  EOF
  )"
  ```
  Expected: `6 files changed`.

---

### Task 6: `fact_funnel_step` (track_ids UNNEST) + gold tests

**Files:** Create `fact_funnel_step.sql`, `analytics/dbt/models/gold/_gold.yml`.

- [ ] **Write `analytics/dbt/models/gold/facts/fact_funnel_step.sql`** (FULL — MUST-FIX #3: `playlisted`/`published` UNNESTed from per-track `track_ids`; `ingested` from `clouder_tracks.created_at`; window partitioned by `track_key` per §8):
  ```sql
  with viewed as (
      select user_id, track_id, ts_server, 'viewed' as step
      from {{ ref('stg_track_view') }}
  ),
  categorized as (
      select user_id, track_id, ts_server, 'categorized' as step
      from {{ ref('stg_track_categorized') }}
      where action in ('moved_to_bucket', 'categorized_curate')
  ),
  playlisted as (
      select p.user_id, tid as track_id, p.ts_server, 'playlisted' as step
      from {{ ref('stg_playlist') }} p
      cross join unnest(p.track_ids) as t (tid)
      where p.event_name = 'playlist_add'
  ),
  published as (
      select p.user_id, tid as track_id, p.ts_server, 'published' as step
      from {{ ref('stg_playlist') }} p
      cross join unnest(p.track_ids) as t (tid)
      where p.event_name = 'playlist_publish'
  ),
  ingested_latest as (
      select max(snapshot_dt) as snapshot_dt
      from {{ source('clouder_analytics', 'bronze_catalog_export') }}
      where tbl = 'clouder_tracks'
  ),
  ingested as (
      select
          cast(null as varchar) as user_id,
          c.id as track_id,
          date_format(coalesce(try_cast(c.created_at as timestamp),
                               from_iso8601_timestamp(c.created_at)), '%Y-%m-%dT%H:%i:%sZ') as ts_server,
          'ingested' as step
      from {{ source('clouder_analytics', 'bronze_catalog_export') }} c
      cross join ingested_latest l
      where c.tbl = 'clouder_tracks' and c.snapshot_dt = l.snapshot_dt and c.created_at is not null
  ),
  all_steps as (
      select * from ingested
      union all select * from viewed
      union all select * from categorized
      union all select * from playlisted
      union all select * from published
  ),
  keyed as (
      select
          {{ surrogate_key(['user_id']) }} as user_key,
          {{ surrogate_key(['track_id']) }} as track_key,
          step,
          from_iso8601_timestamp(ts_server) as ts
      from all_steps
  ),
  windowed as (
      select *,
          lag(ts) over (partition by track_key order by ts) as prev_ts,
          lag(step) over (partition by track_key order by ts) as prev_step
      from keyed
  )
  select
      {{ surrogate_key(['user_key', 'track_key', 'step', 'ts']) }} as funnel_key,
      user_key,
      track_key,
      cast(date_format(ts, '%Y%m%d') as integer) as date_key,
      step,
      ts,
      prev_step,
      date_diff('millisecond', prev_ts, ts) as ms_since_prev,
      date_format(ts, '%Y-%m-%d') as dt
  from windowed
  ```

- [ ] **Write `analytics/dbt/models/gold/_gold.yml`** (FULL — keys not_null/unique, accepted_values enums, **relationships fact→dim**; no relationships test on the degenerate `category_key`):
  ```yaml
  version: 2

  models:
    - name: dim_date
      columns:
        - name: date_key
          tests: [not_null, unique]
    - name: dim_track
      columns:
        - name: track_key
          tests: [not_null, unique]
    - name: dim_artist
      columns:
        - name: artist_key
          tests: [not_null, unique]
    - name: dim_label
      columns:
        - name: label_key
          tests: [not_null, unique]
    - name: dim_user
      columns:
        - name: user_key
          tests: [not_null, unique]
    - name: dim_category
      columns:
        - name: category_key
          tests: [not_null, unique]
    - name: bridge_track_artist
      columns:
        - name: track_key
          tests:
            - relationships: { to: ref('dim_track'), field: track_key }
        - name: artist_key
          tests:
            - relationships: { to: ref('dim_artist'), field: artist_key }

    - name: fact_track_decision
      columns:
        - name: decision_key
          tests: [not_null, unique]
        - name: event_id
          tests: [not_null]
        - name: action
          tests:
            - accepted_values: { values: ["moved_to_bucket", "categorized_curate", "undo"] }
        - name: surface
          tests:
            - accepted_values: { values: ["triage", "curate"], config: { where: "surface is not null" } }
        - name: user_key
          tests:
            - relationships: { to: ref('dim_user'), field: user_key }
        - name: track_key
          tests:
            - relationships: { to: ref('dim_track'), field: track_key }
        - name: date_key
          tests:
            - relationships: { to: ref('dim_date'), field: date_key }
    - name: fact_playback
      columns:
        - name: playback_key
          tests: [not_null, unique]
        - name: source
          tests:
            - accepted_values: { values: ["triage_player", "playlist_player", "category_player"], config: { where: "source is not null" } }
        - name: track_key
          tests:
            - relationships: { to: ref('dim_track'), field: track_key }
        - name: date_key
          tests:
            - relationships: { to: ref('dim_date'), field: date_key }
    - name: fact_seek
      columns:
        - name: seek_key
          tests: [not_null, unique]
        - name: track_key
          tests:
            - relationships: { to: ref('dim_track'), field: track_key }
    - name: fact_triage_session
      columns:
        - name: session_key
          tests: [not_null, unique]
        - name: date_key
          tests:
            - relationships: { to: ref('dim_date'), field: date_key }
    - name: fact_funnel_step
      columns:
        - name: funnel_key
          tests: [not_null, unique]
        - name: step
          tests:
            - accepted_values: { values: ["ingested", "viewed", "categorized", "playlisted", "published"] }
        - name: date_key
          tests:
            - relationships: { to: ref('dim_date'), field: date_key }
  ```

- [ ] **Run `dbt parse`, expect PASS** (whole project compiles — every `ref`/`source`/macro/test resolves):
  ```bash
  DBT_LAKE_BUCKET=placeholder \
  /Users/roman/Projects/clouder-projects/clouder-core/.dbt-venv/bin/dbt parse \
    --project-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt \
    --profiles-dir /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics/dbt
  ```
  Expected: `Wrote manifest to`, exit 0.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add analytics/dbt/models/gold/facts/fact_funnel_step.sql analytics/dbt/models/gold/_gold.yml
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add fact_funnel_step + gold dbt tests

  playlisted/published UNNEST per-track track_ids (in Inc-2 PROP_ALLOWLIST);
  ingested from clouder_tracks.created_at; window per track_key. Adds
  not_null/unique/accepted_values/relationships across the star schema.
  EOF
  )"
  ```
  Expected: `2 files changed`.

---

### Task 7: `dbt_runner` Lambda (multi-token command) + container assets

**Files:** Create `tests/unit/test_dbt_runner.py`, `analytics/dbt_runner.py`, `analytics/Dockerfile`, `scripts/package_dbt_runner.sh`. (`analytics/requirements.txt` exists from Task 1.)

- [ ] **Write the failing test** `tests/unit/test_dbt_runner.py` (FULL — MUST-FIX #8: a multi-token `source freshness` must split into two args):
  ```python
  import pytest

  import dbt_runner


  class FakeResult:
      def __init__(self, success):
          self.success = success


  class FakeInvoke:
      def __init__(self, success=True):
          self.calls = []
          self.success = success

      def __call__(self, args):
          self.calls.append(args)
          return FakeResult(self.success)


  def test_multi_token_source_freshness_splits():
      inv = FakeInvoke()
      out = dbt_runner.run_dbt("source freshness", "/proj", "/prof", inv)
      assert inv.calls[0][:2] == ["source", "freshness"]
      assert "--project-dir" in inv.calls[0] and "/proj" in inv.calls[0]
      assert "--profiles-dir" in inv.calls[0] and "/prof" in inv.calls[0]
      assert out["success"] is True


  def test_single_token_run():
      inv = FakeInvoke()
      dbt_runner.run_dbt("run", "/proj", "/prof", inv)
      assert inv.calls[0][0] == "run"


  def test_failure_raises_runtime_error():
      inv = FakeInvoke(success=False)
      with pytest.raises(RuntimeError):
          dbt_runner.run_dbt("test", "/proj", "/prof", inv)
  ```

- [ ] **Run it, expect FAIL** (module missing):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_dbt_runner.py -q
  ```
  Expected: collection error, `ModuleNotFoundError: No module named 'dbt_runner'`, summary `1 error` (exit 2).

- [ ] **Write `analytics/dbt_runner.py`** (FULL — dbt imported lazily inside `_dbt_invoke` only, so the test never loads dbt):
  ```python
  """dbt-runner Lambda handler. Runs ONE dbt command per invocation via the in-process
  dbtRunner. The command is split on whitespace so MULTI-TOKEN commands like
  'source freshness' (a distinct dbt subcommand, not covered by build/test) actually
  execute as ['source','freshness',...]. The Step Functions DAG invokes this with
  command='run', then 'source freshness', then 'test'.
  """
  from __future__ import annotations

  import os
  from typing import Any, Callable


  def run_dbt(command: str, project_dir: str, profiles_dir: str,
              invoke: Callable[[list[str]], Any]) -> dict[str, Any]:
      args = command.split() + [
          "--project-dir", project_dir,
          "--profiles-dir", profiles_dir,
      ]
      result = invoke(args)
      if not result.success:
          raise RuntimeError(f"dbt {command!r} failed")
      return {"command": command, "args": args, "success": True}


  def _dbt_invoke(args: list[str]) -> Any:
      from dbt.cli.main import dbtRunner  # heavy; imported only in the real runtime

      return dbtRunner().invoke(args)


  def lambda_handler(event: Any, context: Any) -> dict[str, Any]:
      command = (event or {}).get("command", "build")
      return run_dbt(
          command,
          os.environ.get("DBT_PROJECT_DIR", "/var/task/dbt"),
          os.environ.get("DBT_PROFILES_DIR", "/var/task/dbt"),
          _dbt_invoke,
      )
  ```

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_dbt_runner.py -q
  ```
  Expected: last line `3 passed` (exit 0).

- [ ] **Write `analytics/Dockerfile`** (FULL — build context = repo root; MUST-FIX #5 version pin; no `AWS_REGION` set here — it is Lambda-auto-injected):
  ```dockerfile
  FROM public.ecr.aws/lambda/python:3.12

  COPY analytics/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
  RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

  COPY analytics/dbt_runner.py ${LAMBDA_TASK_ROOT}/dbt_runner.py
  COPY analytics/dbt ${LAMBDA_TASK_ROOT}/dbt

  ENV DBT_PROJECT_DIR=${LAMBDA_TASK_ROOT}/dbt
  ENV DBT_PROFILES_DIR=${LAMBDA_TASK_ROOT}/dbt

  CMD ["dbt_runner.lambda_handler"]
  ```

- [ ] **Write `scripts/package_dbt_runner.sh`** (FULL — build + push `:latest` before `terraform apply`):
  ```bash
  #!/usr/bin/env bash
  set -euo pipefail

  ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  REGION="${AWS_REGION:-us-east-1}"
  ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
  REPO="beatport-prod-dbt-runner"
  REGISTRY="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
  IMAGE="${REGISTRY}/${REPO}:latest"

  aws ecr describe-repositories --repository-names "$REPO" --region "$REGION" >/dev/null 2>&1 \
    || aws ecr create-repository --repository-name "$REPO" --region "$REGION" >/dev/null

  aws ecr get-login-password --region "$REGION" \
    | docker login --username AWS --password-stdin "$REGISTRY"

  docker build --platform linux/amd64 -f "$ROOT_DIR/analytics/Dockerfile" -t "$IMAGE" "$ROOT_DIR"
  docker push "$IMAGE"
  echo "Pushed dbt-runner image: $IMAGE"
  ```

- [ ] **Make the script executable and sanity-check the test suite again** (no docker build here — that needs AWS creds; the script is exercised at deploy time, documented in the README):
  ```bash
  chmod +x /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/scripts/package_dbt_runner.sh
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_dbt_runner.py -q
  ```
  Expected: `3 passed`.

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add tests/unit/test_dbt_runner.py analytics/dbt_runner.py analytics/Dockerfile scripts/package_dbt_runner.sh
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(analytics): add dbt-runner container Lambda

  Handler splits the command so 'source freshness' runs as a distinct dbt
  subcommand. Container image (dbt-athena 1.9.5) is the only image Lambda;
  existing zip Lambdas are untouched. Build/push script for deploy.
  EOF
  )"
  ```
  Expected: `4 files changed`.

---

### Task 8: Step Functions ASL + orchestration Terraform + catalog-table column extension

**Files:** Create `tests/unit/test_analytics_state_machine.py`, `analytics/state_machine.asl.json`, `infra/analytics_dbt.tf`. Modify `infra/analytics_export.tf`.

- [ ] **Write the failing test** `tests/unit/test_analytics_state_machine.py` (FULL — pins the DAG shape; MUST-FIX #9 order and Catch→Fail):
  ```python
  import json
  import pathlib

  ASL = (
      pathlib.Path(__file__).resolve().parents[2]
      / "analytics" / "state_machine.asl.json"
  )


  def _load():
      return json.loads(ASL.read_text())


  def test_parallel_runs_both_exports():
      d = _load()
      start = d["States"][d["StartAt"]]
      assert start["Type"] == "Parallel"
      names = {
          b["States"][b["StartAt"]]["Parameters"]["FunctionName"]
          for b in start["Branches"]
      }
      assert names == {"${catalog_export_arn}", "${ops_log_export_arn}"}


  def test_order_run_then_freshness_then_test():
      d = _load()
      s = d["States"]
      assert s[d["StartAt"]]["Next"] == "DbtRun"
      assert s["DbtRun"]["Next"] == "DbtSourceFreshness"
      assert s["DbtSourceFreshness"]["Next"] == "DbtTest"


  def test_payload_commands():
      d = _load()
      s = d["States"]
      assert s["DbtRun"]["Parameters"]["Payload"]["command"] == "run"
      assert s["DbtSourceFreshness"]["Parameters"]["Payload"]["command"] == "source freshness"
      assert s["DbtTest"]["Parameters"]["Payload"]["command"] == "test"


  def test_quality_gate_catches_to_fail():
      d = _load()
      s = d["States"]
      for state in ("DbtSourceFreshness", "DbtTest"):
          assert any(c["Next"] == "NotifyFailure" for c in s[state]["Catch"])
      assert s["NotifyFailure"]["Type"] == "Fail"
  ```

- [ ] **Run it, expect FAIL** (ASL file missing → `FileNotFoundError` inside the test body, not at collection):
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_analytics_state_machine.py -q
  ```
  Expected: `4 failed` (each test raises `FileNotFoundError`; exit 1).

- [ ] **Write `analytics/state_machine.asl.json`** (FULL — valid JSON; `${…}` tokens live inside string values so `json.loads` works and `templatefile` substitutes them; MUST-FIX #9 order run→freshness→test, Catch keeps yesterday's gold):
  ```json
  {
    "Comment": "CLOUDER analytics daily build: parallel exports -> dbt run -> source freshness -> test.",
    "StartAt": "ExportBronze",
    "States": {
      "ExportBronze": {
        "Type": "Parallel",
        "Next": "DbtRun",
        "Branches": [
          {
            "StartAt": "CatalogExport",
            "States": {
              "CatalogExport": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": { "FunctionName": "${catalog_export_arn}" },
                "End": true
              }
            }
          },
          {
            "StartAt": "OpsLogExport",
            "States": {
              "OpsLogExport": {
                "Type": "Task",
                "Resource": "arn:aws:states:::lambda:invoke",
                "Parameters": { "FunctionName": "${ops_log_export_arn}" },
                "End": true
              }
            }
          }
        ]
      },
      "DbtRun": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
          "FunctionName": "${dbt_runner_arn}",
          "Payload": { "command": "run" }
        },
        "Next": "DbtSourceFreshness",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "NotifyFailure" }]
      },
      "DbtSourceFreshness": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
          "FunctionName": "${dbt_runner_arn}",
          "Payload": { "command": "source freshness" }
        },
        "Next": "DbtTest",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "NotifyFailure" }]
      },
      "DbtTest": {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
          "FunctionName": "${dbt_runner_arn}",
          "Payload": { "command": "test" }
        },
        "Next": "Succeed",
        "Catch": [{ "ErrorEquals": ["States.ALL"], "Next": "NotifyFailure" }]
      },
      "NotifyFailure": {
        "Type": "Fail",
        "Error": "DbtQualityGateFailed",
        "Cause": "dbt freshness or test failed; prior gold dt partitions remain (insert_overwrite is per-dt, so only today's partition is at risk)."
      },
      "Succeed": { "Type": "Succeed" }
    }
  }
  ```
  > `// ponytail:` per the locked order, `dbt run` precedes freshness/test, so "keep serving yesterday's gold" is bounded by `insert_overwrite`-by-`dt`: a failed gate only flags **today's** partition; all prior partitions (yesterday's gold) are untouched and dashboards keep serving them. Move `DbtSourceFreshness` before `DbtRun` only if you want freshness to hard-gate the rebuild.

- [ ] **Run it, expect PASS**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_analytics_state_machine.py -q
  ```
  Expected: last line `4 passed` (exit 0).

- [ ] **Modify `infra/analytics_export.tf`** — extend the `aws_glue_catalog_table.catalog_export` `storage_descriptor` so JsonSerDe exposes the full §6 column union (contract #2). Locate the existing block (the 6 `columns { id|title|name|deleted_at|created_at|updated_at }` entries inside `storage_descriptor`) and add the missing dim columns after `updated_at` (all `string`; dbt casts on read; JsonSerDe null-fills absent keys per `tbl`):
  ```hcl
      # --- Inc-4: dim column union so dbt can read per-tbl fields (schema-on-read) ---
      columns {
        name = "bpm"
        type = "string"
      }
      columns {
        name = "key_name"
        type = "string"
      }
      columns {
        name = "key_camelot"
        type = "string"
      }
      columns {
        name = "spotify_release_date"
        type = "string"
      }
      columns {
        name = "publish_date"
        type = "string"
      }
      columns {
        name = "album_id"
        type = "string"
      }
      columns {
        name = "style_id"
        type = "string"
      }
      columns {
        name = "isrc"
        type = "string"
      }
      columns {
        name = "release_type"
        type = "string"
      }
      columns {
        name = "release_date"
        type = "string"
      }
      columns {
        name = "is_ai_suspected"
        type = "string"
      }
      columns {
        name = "origin"
        type = "string"
      }
      columns {
        name = "normalized_name"
        type = "string"
      }
      columns {
        name = "label_id"
        type = "string"
      }
      columns {
        name = "user_id"
        type = "string"
      }
      columns {
        name = "style_id_category"
        type = "string"
      }
      columns {
        name = "position"
        type = "string"
      }
      columns {
        name = "role"
        type = "string"
      }
      columns {
        name = "track_id"
        type = "string"
      }
      columns {
        name = "artist_id"
        type = "string"
      }
      columns {
        name = "category_id"
        type = "string"
      }
      columns {
        name = "added_at"
        type = "string"
      }
  ```
  (`style_id` is declared once and serves both `clouder_tracks` and `categories` — a JsonSerDe column maps a single JSON key name across all `tbl` partitions, so the placeholder `style_id_category` above is dropped if not needed; keep only real key names. NOTE for the executing agent: the JSON key is `style_id` in both tables, so declare `style_id` **once** and remove the `style_id_category` stub — it exists only to flag that the same key is reused.)

- [ ] **Create `infra/analytics_dbt.tf`** (FULL — ECR repo, image Lambda + role, Step Functions + role, EventBridge Scheduler + role; references `aws_lambda_function.catalog_export`/`ops_log_export` and `aws_s3_bucket.analytics_lake` from Inc-3):
  ```hcl
  locals {
    dbt_runner_lambda_name = "${local.name_prefix}-dbt-runner"
    analytics_sfn_name     = "${local.name_prefix}-analytics-daily"
  }

  # ── ECR repo + image Lambda (the ONLY container-image Lambda in the repo) ──
  resource "aws_ecr_repository" "dbt_runner" {
    name                 = "${local.name_prefix}-dbt-runner"
    image_tag_mutability = "MUTABLE"
    force_delete         = true
  }

  resource "aws_cloudwatch_log_group" "dbt_runner" {
    name              = "/aws/lambda/${local.dbt_runner_lambda_name}"
    retention_in_days = var.log_retention_days
  }

  resource "aws_iam_role" "dbt_runner" {
    name               = "${local.name_prefix}-dbt-runner-role"
    assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  }

  data "aws_iam_policy_document" "dbt_runner" {
    statement {
      sid       = "AllowOwnLogs"
      effect    = "Allow"
      actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
      resources = ["${aws_cloudwatch_log_group.dbt_runner.arn}:*"]
    }
    statement {
      sid    = "Athena"
      effect = "Allow"
      actions = [
        "athena:StartQueryExecution", "athena:GetQueryExecution",
        "athena:GetQueryResults", "athena:StopQueryExecution",
        "athena:GetWorkGroup", "athena:GetDataCatalog",
      ]
      resources = ["*"]
    }
    statement {
      sid    = "Glue"
      effect = "Allow"
      actions = [
        "glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables",
        "glue:GetPartition", "glue:GetPartitions", "glue:BatchCreatePartition",
        "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable",
        "glue:BatchGetPartition",
      ]
      resources = ["*"]
    }
    statement {
      sid    = "LakeReadWrite"
      effect = "Allow"
      actions = [
        "s3:GetObject", "s3:PutObject", "s3:DeleteObject",
        "s3:ListBucket", "s3:GetBucketLocation",
      ]
      resources = [
        aws_s3_bucket.analytics_lake.arn,
        "${aws_s3_bucket.analytics_lake.arn}/*",
      ]
    }
  }

  resource "aws_iam_role_policy" "dbt_runner" {
    name   = "${local.name_prefix}-dbt-runner-policy"
    role   = aws_iam_role.dbt_runner.id
    policy = data.aws_iam_policy_document.dbt_runner.json
  }

  resource "aws_lambda_function" "dbt_runner" {
    function_name = local.dbt_runner_lambda_name
    role          = aws_iam_role.dbt_runner.arn
    package_type  = "Image"
    image_uri     = "${aws_ecr_repository.dbt_runner.repository_url}:latest"
    timeout       = 900
    memory_size   = 3008

    # AWS_REGION is auto-injected by the Lambda runtime (reserved — cannot be set here);
    # profiles.yml reads it via env_var('AWS_REGION','us-east-1').
    environment {
      variables = {
        DBT_S3_STAGING_DIR = "s3://${aws_s3_bucket.analytics_lake.bucket}/athena-results/"
        DBT_S3_DATA_DIR    = "s3://${aws_s3_bucket.analytics_lake.bucket}/marts/"
        DBT_LAKE_BUCKET    = aws_s3_bucket.analytics_lake.bucket
        LOG_LEVEL          = "INFO"
      }
    }

    depends_on = [aws_cloudwatch_log_group.dbt_runner]
  }

  # ── Step Functions Standard state machine ──
  resource "aws_iam_role" "analytics_sfn" {
    name = "${local.name_prefix}-analytics-sfn-role"
    assume_role_policy = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = { Service = "states.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }]
    })
  }

  data "aws_iam_policy_document" "analytics_sfn" {
    statement {
      sid     = "InvokeLambdas"
      effect  = "Allow"
      actions = ["lambda:InvokeFunction"]
      resources = [
        aws_lambda_function.catalog_export.arn,
        aws_lambda_function.ops_log_export.arn,
        aws_lambda_function.dbt_runner.arn,
      ]
    }
  }

  resource "aws_iam_role_policy" "analytics_sfn" {
    name   = "${local.name_prefix}-analytics-sfn-policy"
    role   = aws_iam_role.analytics_sfn.id
    policy = data.aws_iam_policy_document.analytics_sfn.json
  }

  resource "aws_sfn_state_machine" "analytics_daily" {
    name     = local.analytics_sfn_name
    role_arn = aws_iam_role.analytics_sfn.arn
    type     = "STANDARD"
    definition = templatefile("${path.module}/../analytics/state_machine.asl.json", {
      catalog_export_arn = aws_lambda_function.catalog_export.arn
      ops_log_export_arn = aws_lambda_function.ops_log_export.arn
      dbt_runner_arn     = aws_lambda_function.dbt_runner.arn
    })
  }

  # ── EventBridge Scheduler: daily trigger ──
  resource "aws_iam_role" "analytics_scheduler" {
    name = "${local.name_prefix}-analytics-scheduler-role"
    assume_role_policy = jsonencode({
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = { Service = "scheduler.amazonaws.com" }
        Action    = "sts:AssumeRole"
      }]
    })
  }

  data "aws_iam_policy_document" "analytics_scheduler" {
    statement {
      sid       = "StartStateMachine"
      effect    = "Allow"
      actions   = ["states:StartExecution"]
      resources = [aws_sfn_state_machine.analytics_daily.arn]
    }
  }

  resource "aws_iam_role_policy" "analytics_scheduler" {
    name   = "${local.name_prefix}-analytics-scheduler-policy"
    role   = aws_iam_role.analytics_scheduler.id
    policy = data.aws_iam_policy_document.analytics_scheduler.json
  }

  resource "aws_scheduler_schedule" "analytics_daily" {
    name = "${local.name_prefix}-analytics-daily"
    flexible_time_window {
      mode = "OFF"
    }
    schedule_expression          = "cron(0 7 * * ? *)"
    schedule_expression_timezone = "UTC"

    target {
      arn      = aws_sfn_state_machine.analytics_daily.arn
      role_arn = aws_iam_role.analytics_scheduler.arn
    }
  }
  ```

- [ ] **Run `terraform validate`, expect PASS** (needs the AWS provider; `init` downloads it from registry.terraform.io — requires network. `infra/.terraform/` is absent in this worktree, so `init` must run first and there is no offline shortcut):
  ```bash
  terraform -chdir=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra init -backend=false -input=false
  terraform -chdir=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/infra validate
  ```
  Expected: `Success! The configuration is valid.` (If the sandbox has no registry network, run this gate where it can reach registry.terraform.io — do not claim `validate` ran offline.)

- [ ] **Commit** (caveman-commit subject, heredoc body):
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add tests/unit/test_analytics_state_machine.py analytics/state_machine.asl.json infra/analytics_dbt.tf infra/analytics_export.tf
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  feat(infra): orchestrate dbt via Step Functions + Scheduler

  Daily [catalog_export || ops_log_export] -> dbt run -> source freshness ->
  test; freshness/test Catch -> Fail (insert_overwrite by dt keeps prior
  gold). dbt-runner image Lambda + ECR. Extend bronze_catalog_export columns.
  EOF
  )"
  ```
  Expected: `4 files changed`.

---

### Task 9: README + full-suite verification + PR

**Files:** Create `analytics/dbt/README.md`.

- [ ] **Create `analytics/dbt/README.md`** (FULL):
  ```markdown
  # CLOUDER analytics — dbt-athena transforms

  Bronze (Firehose + daily exports) -> **silver** (staging, one model per event family) ->
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
  `dbt-athena-community==1.9.5` (latest stable 1.9.x; `1.9.0`/`1.9.1` do not exist on PyPI).

  ## Local
      python3.12 -m venv .dbt-venv && .dbt-venv/bin/pip install -r ../requirements.txt
      DBT_LAKE_BUCKET=placeholder .dbt-venv/bin/dbt parse --project-dir . --profiles-dir .
  Offline gates (pytest): `test_saturday_week_dbt_macro`, `test_fact_playback_terminal`,
  `test_dbt_runner`, `test_analytics_state_machine`. SQL data-correctness is proven LIVE by
  `dbt test` + `dbt source freshness` inside the DAG.

  ## Deploy (image Lambda — build BEFORE apply)
      AWS_REGION=us-east-1 scripts/package_dbt_runner.sh   # build + push :latest to ECR
      cd infra && terraform apply                          # ECR, dbt-runner, Step Functions, Scheduler

  EventBridge Scheduler fires `beatport-prod-analytics-daily` at 07:00 UTC:
  `[catalog_export || ops_log_export] -> dbt run -> dbt source freshness -> dbt test`.
  On freshness/test failure the run goes to `Fail`; `insert_overwrite`-by-`dt` means only
  today's gold partition is at risk, so dashboards keep serving prior partitions.

  ## Lineage (portfolio)
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
  ```

- [ ] **Run the full offline gate (all four pytest suites together), expect all green**:
  ```bash
  PYTHONPATH=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/src:/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/analytics \
  /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python -m pytest \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_saturday_week_dbt_macro.py \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_fact_playback_terminal.py \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_dbt_runner.py \
  /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/tests/unit/test_analytics_state_machine.py -q
  ```
  Expected: last line `2940 passed` (2928 + 5 + 3 + 4; exit 0). Re-confirm `dbt parse` is green one final time with the Task-6 command.

- [ ] **Commit the README** (caveman-commit subject, heredoc body), then push:
  ```bash
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve add analytics/dbt/README.md
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve commit -m "$(cat <<'EOF'
  docs(analytics): document dbt project + orchestration

  Layout, dbt-athena 1.9.5 pin, deploy order (build image before apply),
  lineage on-demand, and the cross-increment reconciliation notes.
  EOF
  )"
  git -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve push -u origin feat/analytics-dbt-orchestration
  ```
  Expected: `1 file changed`; push prints the branch upstream.

- [ ] **Open the PR** — generate the **title and body** with `caveman:caveman-commit`. **Transcribe the heredoc EXACTLY: body lines and the closing `EOF` sit at column 0, no leading whitespace** (an indented `EOF` never closes `cat <<'EOF'` and `gh pr create` hangs). No AI/`Co-Authored-By` trailer:
  ```bash
  gh -C /Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve pr create --base main --head feat/analytics-dbt-orchestration --title "<caveman title>" --body "$(cat <<'EOF'
  <caveman PR body: dbt-athena project (6 silver, 6 gold dims + bridge + dim_date, 5 gold facts), dbt-runner container Lambda, Step Functions Standard + EventBridge Scheduler daily DAG. Offline gates: Saturday-week mirror, fact_playback terminal mirror, dbt_runner multi-token command, state-machine ASL shape, dbt parse. Live gates: dbt source freshness + dbt test in the DAG. Notes the Inc-2 bronze_events name/shape reconciliation and that track_ids is already in the Inc-2 PROP_ALLOWLIST.>
  EOF
  )"
  ```
  > If the heredoc is error-prone in your shell, write the caveman body to a temp file and pass `gh pr create ... --body-file /tmp/pr_body.md` — this sidesteps the column-0 rule entirely.

---

## MUST-FIX compliance map (verify each before requesting review)

1. **Source names** — `_sources.yml` declares exactly `bronze_events`, `bronze_catalog_export` (single table), `bronze_ops`; no invented per-table catalog sources (Task 1).
2. **Schema-on-read** — every silver model parses `context`/`props` with `json_extract_scalar`/`json_extract` (Task 3); dims read `bronze_catalog_export` typed columns filtered by `tbl` (Task 4), with the Glue column union extended in `infra/analytics_export.tf` (Task 8) since there is no raw `line` column (recon fact #3). No struct/dot access anywhere.
3. **Funnel UNNEST** — `fact_funnel_step.sql` `cross join unnest(track_ids)` for `playlist_add`→`playlisted` and `playlist_publish`→`published`, one row per id; implemented fully (track_ids is in the Inc-2 allowlist) — no deferral (Task 6).
4. **fact_playback terminal** — recon stated: local resume re-emits `playback_play`, remote resume does not. Running-count grouping + priority terminal selection resolves pause→resume→end to the true end; `skipped` only when terminal is `playback_skip`. Assumption named in the model comment + `ponytail:` ceiling; offline `test_fact_playback_terminal.py` (5 cases) (Task 5).
5. **dbt version** — `dbt-athena-community==1.9.5` (exists; `1.9.0`/`1.9.1` do not) in `requirements.txt`, Dockerfile, README, Tech Stack (Tasks 1/7/9).
6. **category_key** — `fact_track_decision.category_key` kept per §7 as a degenerate attribute (no relationships test); `dim_category` built from `categories` (not `category_tracks`, which stays an unmodeled junction) (Tasks 4/5/6).
7. **Region** — `profiles.yml` `region_name: env_var('AWS_REGION','us-east-1')`; no `AWS_REGION` in the Lambda env block (reserved/auto-injected); default = the repo's real `var.aws_region` default `us-east-1` (Tasks 1/8).
8. **Freshness as a real distinct command** — `_sources.yml` carries the freshness rule on `bronze_events`; `dbt_runner.run_dbt` splits `command.split()` so `source freshness` runs as two tokens; a dedicated `DbtSourceFreshness` SFN state invokes it (Tasks 1/7/8).
9. **Orchestration + failure semantics** — `[catalog_export ‖ ops_log_export] → dbt_run → dbt source freshness → dbt_test`, daily via Scheduler; freshness/test `Catch → Fail`; `insert_overwrite`-by-`dt` bounds blast radius so yesterday's gold keeps serving (Task 8).
10. **TDD honesty** — `sat_week_mirror.py`/`playback_terminal_mirror.py` are labeled contract-pinning Python mirrors (RED→GREEN via missing module, then verified against the canonical `saturday_week.py` / the spec rules); SQL data-correctness is proven live by `dbt test`/`source freshness` in the DAG, stated in the README and tasks.
11. **Reconciliation surfaced** — the on-disk Inc-2 draft's `events`/struct `context` conflict with the locked `bronze_events`/string contract is documented (top of plan + README) rather than silently depended upon.
12. **Commits** — every commit/PR subject/title/body generated via `caveman:caveman-commit`; heredoc bodies at column 0; no `Co-Authored-By`; branch `feat/analytics-dbt-orchestration` (no agent prefix).
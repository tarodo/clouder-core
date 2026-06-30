# Analytics v2 — per-user daily dashboard, raw envelope redesign, beatport→clouder rename

**Date:** 2026-06-30
**Status:** Design — awaiting review
**Supersedes:** `2026-06-27-clouder-analytics-pipeline-design.md` (the dbt star-schema pipeline, deleted in full)

## Motivation

The current analytics is unsalvageable on two axes the user named:

- **(B) Wrong metrics.** The dbt star schema (`fact_triage_session`, `fact_playback`, `fact_funnel_step`, 6 dims) measures the wrong things for a DJ curator. We are not refactoring it — we delete it.
- **(D) Bad dashboards.** The existing `/admin/analytics` surfaces are scrapped and rebuilt from one clear question.

We rebuild on the raw event layer. While we are here, two adjacent cleanups ride along (user-requested, one spec):

1. **Redesign the raw envelope** to a typed hybrid shape (no functional dependency on the old JSON-string contract, which only existed to feed the now-deleted dbt silver).
2. **Rename `beatport-prod-*` → `clouder-prod-*`** across infra. "Beatport" is the upstream data *source*, not the product. The genuine Beatport-source code keeps its name.

Data loss of analytics/raw is explicitly acceptable — no migration, no backfill. **Data loss of the curation database (Aurora) is NOT** — see the rename landmine in Part F.

## Scope

**In:** Dashboard #1 (per-user daily). Two marts (`fact_session`, `mart_user_daily`). Raw envelope redesign (hybrid typed). beatport→clouder rename. One frontend instrumentation add (`removed_from_category`).

**Out (later increments):** Any other dashboard. Dimension enrichment (resolving `track_id`/`user_id` → display names). Modeling `bronze_catalog_export` / `bronze_ops`. Cross-user / cohort analytics.

---

## Part A — Delete

Remove the entire dbt layer and its runtime:

- `analytics/dbt/` (all 12 models, macros, tests, profiles)
- `analytics/dbt_runner.py`, `analytics/Dockerfile`, `analytics/requirements.txt`, `analytics/state_machine.asl.json`
- `analytics/sat_week_mirror.py`, `analytics/playback_terminal_mirror.py` (silver mirror helpers)
- `infra/analytics_dbt.tf` (Step Function + scheduler), `infra/analytics_dbt_runner.tf` (dbt container Lambda)
- Old `/admin/analytics` frontend components (the star-schema dashboards)

**Keep:** the raw telemetry ingest path (frontend `telemetry` client → `telemetry_handler` → Firehose → S3 lake) — but its physical schema changes in Part B. Keep `bronze_catalog_export` / `bronze_ops` tables (unused by Dashboard #1, cheap to leave, future dim source). Keep `analytics-api` Lambda shell — repurposed in Part D.

---

## Part B — Raw envelope redesign (hybrid typed)

**Event taxonomy is unchanged** — the 13 `event_name`s and their semantic props stay. Only the *physical* on-disk shape changes: from `context`/`props` as JSON strings to typed top-level columns + a JSON tail.

### New `bronze_events` schema (Glue / Parquet)

Partitions: `dt` (date), `event_name` (enum) — unchanged.

**Envelope (always present):**

| column | type | notes |
|---|---|---|
| `event_id` | string | dedupe key |
| `session_id` | string | client session UUID (secondary; NOT the derived session) |
| `ts_client` | string | ISO8601, untrusted |
| `ts_server` | string | ISO8601, server-stamped — the clock all analytics use |

**Context (flattened, typed):**

| column | type |
|---|---|
| `user_id` | string (server-stamped from authorizer) |
| `device` | string |
| `route` | string |
| `app_version` | string |

**Hot props (typed, nullable — the columns Dashboard #1 queries):**

| column | type | emitted by |
|---|---|---|
| `track_id` | string | view / categorize / playback |
| `source` | string | playback (`triage_player`/`category_player`/`playlist_player`) |
| `action` | string | categorize (`moved_to_bucket`/`categorized_curate`/`undo`/`removed_from_category`), hotkey |
| `category_key` | string | categorize (bucket_type for triage; category id for curate/remove) |
| `surface` | string | categorize (`triage`/`curate`) |
| `decision_ms` | bigint | track_categorized — **triage time-per-track** |
| `dwell_ms` | bigint | track_view |
| `position_ms` | bigint | playback_play/pause/skip |
| `duration_ms` | bigint | playback_* |
| `listen_through_ratio` | double | playback_ended |
| `seek_count` | int | playback_pause |
| `playlist_id` | string | playlist_* |
| `track_count` | int | playlist_add — **category promoted count** |
| `source_category_id` | string | playlist_add — marks category→playlist promote |
| `session_ms` | bigint | triage_session_end |

**Tail (rare / multi-valued):** `props_extra` (string, JSON). Holds keys not worth a typed column: `track_ids[]`, `from_position_ms`, `to_position_ms`, `tracks_seen`, `tracks_categorized`, `undo_rate`, `hotkey_code`, `confirm_overwrite`, `skipped_count`, `target`, `reorder_count`, `block_id`, `bucket_id`. Adding a new rare prop = one line, no Glue migration (preserves the old "schema-on-read" virtue for the long tail).

### Handler changes (`telemetry_handler.py` / `telemetry_schemas.py`)

- `validate_event` still validates the envelope strictly and key-allowlists props per `event_name` (unchanged guarantees: secret-stripping, server-stamped `user_id`, extra-forbidden envelope).
- The emitter changes: instead of `{..., context:{...}, props:{...}}` with two JSON-string columns, it emits a **flat object** — envelope + flattened context + the hot prop keys present for that event, plus `props_extra` (JSON string) for allowlisted keys not promoted to typed columns.
- Firehose JSON→Parquet format conversion maps present keys to typed columns, absent keys → null.

### Instrumentation add — `removed_from_category`

`category_key` for category-remove is the category id; `action='removed_from_category'`. `action` is already an allowlisted key for `track_categorized` and values are not validated → **no backend schema change**. One frontend emit:

`frontend/src/features/categories/components/TrackRowActions.tsx` (remove handler, uses `useRemoveTrackOptimistic`) →
```ts
telemetry.track('track_categorized', {
  track_id: trackId,
  category_key: categoryId,
  action: 'removed_from_category',
});
```

---

## Part C — Sessionization + marts

### Event → activity stream

Each event row maps to exactly one `activity_type`:

- **triage** — `event_name ∈ {triage_session_start, triage_session_end, track_view, track_categorized, hotkey_used}`, OR (`playback_*` AND `source='triage_player'`). (Curate counts as triage: it is the second pass of the `/triage` flow.)
- **category** — (`playback_*` AND `source='category_player'`), OR (`playlist_add` AND `source_category_id IS NOT NULL`), OR (`track_categorized` AND `action='removed_from_category'`).
- **playlist** — `playback_*` AND `source='playlist_player'`.

### Session = gaps-and-islands, 5-min idle, on `ts_server`

Per `(user_id, activity_type)` stream ordered by `ts_server`: a gap > 300s from the previous event starts a new session.

```sql
-- island id within a user+activity_type stream
sum(cast(
  to_unixtime(from_iso8601_timestamp(ts_server))
  - lag(to_unixtime(from_iso8601_timestamp(ts_server)))
      over (partition by user_id, activity_type order by ts_server) > 300
  as integer
)) over (partition by user_id, activity_type order by ts_server
         rows between unbounded preceding and current row) as session_seq
```

### `fact_session` — one row per session (drill-down + percentile source)

| column | derivation |
|---|---|
| `user_id`, `dt`, `activity_type`, `session_seq` | key |
| `ts_start`, `ts_end` | min / max `ts_server` in island |
| `duration_ms` | `ts_end - ts_start` (single-event session ⇒ 0) |
| `tracks_listened` | `count(distinct track_id)` where `event_name='playback_play'` |
| `tracks_promoted` | per rules below |
| `tracks_deleted` | per rules below |

**Promote / delete rules (net of undo):**

- **triage.promoted** = `count(track_categorized where action ∈ ('moved_to_bucket','categorized_curate') and category_key != 'DISCARD')` − `count(action='undo' and category_key != 'DISCARD')`
- **triage.deleted** = `count(... category_key = 'DISCARD')` − `count(action='undo' and category_key = 'DISCARD')`
  (`undo` events carry the reverted `category_key`.)
- **category.promoted** = `sum(track_count)` from `playlist_add` where `source_category_id IS NOT NULL`
- **category.deleted** = `count(track_categorized where action='removed_from_category')`
- **playlist** — promoted/deleted are NULL (session count only, per the user).

### `mart_user_daily` — aggregate per `(user_id, dt, activity_type)` (the dashboard reads this)

| metric | derivation |
|---|---|
| `sessions` | `count(*)` over `fact_session` |
| `avg_tracks_listened` / `avg_tracks_promoted` / `avg_tracks_deleted` | mean over the day's sessions (counts → mean is fine) |
| `p50_duration_ms`, `p90_duration_ms` | `approx_percentile(duration_ms, ARRAY[0.5, 0.9])` over the day's sessions |
| `p50_time_per_track_ms`, `p90_time_per_track_ms` | percentile of per-track time (below) |

**Time-per-track signal (per activity, then percentile over the day):**

- **triage** — `decision_ms` from `track_categorized` (time from shown to decision).
- **category / playlist** — wall-clock: for each `playback_play`, `ts` to the next terminal event (`playback_ended` / `playback_skip` / next `playback_play`) within the same session:
  ```sql
  lead(to_unixtime(...)) over (partition by user_id, activity_type, session_seq
                               order by ts_server) - to_unixtime(...)
  ```
  Computed in a per-track CTE inside the rollup, then `approx_percentile`.

Percentile (not mean) is deliberate: wall-clock is right-skewed by pauses; the user asked for percentiles.

> **ponytail note (sparse data):** this is a small-circle DJ tool. On a 1–2 session day a percentile ≈ the raw values — acceptable and expected, not a bug.

---

## Part D — Pipeline (no dbt, no Step Function)

Repurpose the `analytics-api` Lambda for two jobs:

1. **Scheduled rollup.** EventBridge daily (recompute the last N days, idempotent). The Lambda runs Athena `INSERT OVERWRITE` per `dt` partition: `bronze_events` → `fact_session` → `mart_user_daily`, written as Parquet under `marts/` in the lake, registered as Glue external tables. Gaps-and-islands + percentiles are plain Athena SQL — no container, no dbt, no `/tmp` copy, none of gotcha #13.
2. **GET endpoints** (existing API Gateway + authorizer):
   - `GET /admin/analytics/user-daily?user_id&from&to` → `mart_user_daily` rows.
   - `GET /admin/analytics/sessions?user_id&dt&activity_type` → `fact_session` drill-down.

Athena `ExecutionParameters` mis-parse `'YYYY-MM-DD'` (gotcha #13) → inline validated date literals, never bind them. New routes follow the three-places rule (`_ROUTE_TABLE` + `generate_openapi` + `infra/*_routes.tf`).

---

## Part E — Frontend

Rebuild `/admin/analytics` as a per-user daily view (Mantine):

- User selector + date range.
- Table: rows = `dt × activity_type`; columns = sessions, avg listened/promoted/deleted, p50/p90 duration, p50/p90 time-per-track.
- Row → drill-down into that day's `fact_session` rows.

MVP only — one table, one drill-down. No charts in this increment unless trivially free. Verify layout in a real browser (`pnpm test:browser`), regen `schema.d.ts` against the new OpenAPI.

Plus the `removed_from_category` emit from Part B.

---

## Part F — Rename `beatport-prod-*` → `clouder-prod-*`

`name_prefix = "${var.project}-${var.environment}"` (`infra/main.tf:2`), `var.project = "beatport"` (`infra/variables.tf:4`). Every resource name derives from it. Flipping the var renames everything in one line — but **AWS resource names are immutable**, so Terraform destroys & recreates.

### Two tiers — this is a hard constraint, not optional

- **Stateless (rename freely, destroy/recreate OK):** Lambdas, SQS queues + DLQs, IAM roles/policies, log groups, API Gateway, the frontend bucket. In-flight SQS messages are lost — acceptable.
- **Stateful (recreation = DATA LOSS — must NOT naively recreate):**
  - **Aurora** — `cluster_identifier = "${name_prefix}-aurora"` (`main.tf:27`). Recreate ⇒ **all curation data gone** (tracks, playlists, users, overlays). This is the loss the user did **not** authorize.
  - `db_secret_name` (`${name_prefix}-aurora-credentials`).
  - **Raw ingest bucket** `${name_prefix}-raw-${account_id}` — holds real Beatport-source data. This *is* the "one beatport prefix to keep."

**Approach (recommended default — confirm at review):**
- Decouple stateful resources from `name_prefix`: pin Aurora cluster id, its secret, and the raw bucket to their **current literal names** so the var flip does not touch them. The raw bucket legitimately keeps a `beatport` marker (it is the Beatport source). Aurora keeps its current id to avoid a snapshot/restore migration.
- If the user wants Aurora's *name* changed too, that is a separate, careful **snapshot → restore-under-new-name → repoint** migration (downtime) — out of scope for this spec unless explicitly pulled in.

### Genuine-Beatport code (keep `beatport`, do NOT rename)

`src/collector/beatport_client.py` (`BeatportClient`), route `POST /admin/beatport/ingest`, structlog `beatport_request`/`beatport_response`, `saturday_week.py` comments. These name the upstream source, not the product.

### Also

Two hardcoded defaults in `infra/analytics_routes.tf` (`beatport-prod-analytics-lake`, `beatport-prod-analytics`) — renamed/removed as part of the analytics rework. Update CLAUDE.md gotcha #4 (`beatport-prod-*` → `clouder-prod-*`).

---

## Build order (increments)

1. **Rename (Part F)** first — establishes the `clouder-prod-*` namespace so everything new is born correctly named. Stateful-pinning lands here.
2. **Envelope redesign (Part B)** — new `bronze_events` Glue schema + handler emit + `removed_from_category` instrumentation. Lake reset (no migration).
3. **Marts + pipeline (Parts C, D)** — `fact_session`, `mart_user_daily`, rollup Lambda, GET routes.
4. **Frontend (Part E)** — dashboard + drill-down.

## Open decisions to confirm at review

- **Part F stateful handling:** keep Aurora id as-is (recommended) vs snapshot/restore rename. Default = keep.
- **Rollup cadence / lookback window** (daily, recompute last N days) — pick N.
- **Envelope `props_extra` boundary** — confirm the typed-vs-tail split above matches intent.

## Risks

- Rename blast radius: stateless recreation means brief downtime + new ARNs; sequence behind a maintenance window.
- `bronze_events` is reset — all dashboards start from empty and fill forward. No historical data by design.
- `category.tracks_deleted` and time-per-track for category depend on events that start emitting only at release — empty for past days regardless.

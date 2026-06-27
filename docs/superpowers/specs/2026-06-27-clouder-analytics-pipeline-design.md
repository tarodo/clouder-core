# CLOUDER Analytics Pipeline — Design Spec

**Status:** Proposed (Phase 1) · **Date:** 2026-06-27 · **Owner:** repo owner (data-engineering portfolio) · **Audience:** repo owner + implementing agent

## Summary

CLOUDER today has zero analytics. This spec adds a **separate, idle-zero, serverless lakehouse contour** that captures DJ-curation behavior and playback telemetry, joins it with the Aurora catalog, and serves five dashboards inside the existing SPA. The point is **breadth of a modern serverless data stack** (Firehose → S3 medallion → Glue Catalog → Athena → dbt-athena → Step Functions/EventBridge), not depth. Phase 1 ships the full contour plus in-app dashboards for a **verified all-in cost under ~$2/mo** (ceiling $5). Real BI (Grafana/QuickSight), a warehouse (Redshift Serverless), and streaming/ML (Flink/Personalize) are explicitly deferred to later phases with their own budgets. The contour shares only the API Gateway and the custom authorizer; telemetry ingest is its own standalone Lambda. It never touches the collector, the ingest worker, its SQS, or any Aurora write, and never sees `bp_token`. `user_id` is stamped server-side from the existing authorizer.

---

## 1. Goals & non-goals

### Goals
- Demonstrate a broad, **modern serverless data stack on AWS**, cheap and idle-zero.
- Capture four data domains: **behavior/clickstream, playback telemetry, funnel×catalog, ops/pipeline**.
- Land raw events in a **medallion S3 lake**, model a **star schema with dbt-athena**, and serve **five dashboards** in-app at `/admin/analytics`.
- Keep the analytics contour **isolated** from the user-facing ingest path: **no shared SQS, worker, collector, or Aurora-write path**. The `/v1/telemetry` hop is a **dedicated `telemetry` Lambda** behind the existing API Gateway + authorizer; it writes only to Firehose — never the collector, the worker queue, or Aurora.
- Portfolio legibility: lineage DAG, dbt tests, Terraform IaC, a clear phase roadmap.

### Non-goals (Phase 1)
- No third-party telemetry vendor (Segment/Snowplow/PostHog) — thin in-house SDK only.
- No real-time/streaming analytics — daily batch is enough.
- No external BI tool — dashboards render in the existing React SPA. (QuickSight/Grafana = Phase 2.)
- No warehouse — Athena-on-S3 only. (Redshift = Phase 3.)
- No ML/recommendations. (Personalize/Flink = Phase 4.)
- No per-event real-time consistency guarantees — schema-on-read, lossy-tolerant (dropped events are acceptable; this is product analytics, not billing).

---

## 2. Constraints

| Constraint | Rule |
|---|---|
| **Cost** | Phase 1 hard ceiling **$5/mo**, realistic **<$2/mo**. Every chosen service is idle-zero or inside a perpetual free tier. No always-on compute (no MWAA ~$358/mo, no KDS shards, no Flink). Later phases have their own bands (§15). |
| **Privacy — `bp_token`** | `bp_token` (Beatport admin OAuth) is **never** logged, persisted, sent in a body, or placed in a URL query param (Referer leak). The telemetry envelope schema has no field that can carry it; the SDK reuses the CLOUDER JWT bearer only. Already in `SENSITIVE_KEYS` (`src/collector/logging_utils.py:13`); telemetry envelope must contain no secret-shaped keys. |
| **Aurora access** | Runtime Lambda reaches Aurora **only via the RDS Data API** (`data_api.execute()`), never `psycopg`. Catalog dimensions are therefore **batch-exported** to the lake (§6), never live-joined at query time. |
| **Multi-tenant** | One Aurora DB, admin ingest + shared canonical core + per-user overlay. `user_id` is stamped **server-side from the authorizer**, never trusted from the client body/JWT-claim-in-frontend. Facts carry a surrogate `user_key` (FK to `dim_user`, which holds the opaque `user_id` only — no PII); dashboards aggregate by it. Analytics route is **admin-gated**. |
| **Saturday-week** | Canonical period is Saturday-week, not ISO week (ADR-0003). Week 1 starts the first Saturday on/after Jan 1. `dim_date` carries **both** Saturday-week and ISO-week columns; all weekly dashboard rollups use Saturday-week. Backend already exposes `src/collector/saturday_week.py`. |
| **Route registration** | A new API route needs three places: `handler._route()`, `scripts/generate_openapi.py:ROUTES`, and an `infra/*_routes_*.tf` gateway route (§5.1). Missing the gateway one yields `{"message":"Not Found"}`. |

---

## 3. Event model

### 3.1 Envelope (Segment/Snowplow-style, schema-on-read)

One envelope for every event. The client sends `event_name`, `event_id`, `session_id`, `ts_client`, partial `context`, and `props`. The server **stamps** `context.user_id` and `ts_server` and **never trusts** a client-supplied `user_id`. This is the `TelemetryEnvelope` schema referenced by the OpenAPI route (§5.1).

```jsonc
{
  "event_name": "track_categorized",        // enum, validated server-side
  "event_id":   "01J...ULID",               // client-generated ULID, idempotency key
  "session_id": "uuid-v4",                   // client, fresh per tab, NOT persisted across tab close
  "ts_client":  "2026-06-27T10:00:00.123Z",  // client clock (drift-tolerant)
  "context": {
    "user_id":     null,                      // SERVER-STAMPED from authorizer; client sends null/omits
    "device":      "desktop",                 // 'desktop' | 'mobile' | 'tablet'
    "route":       "/curate/:blockId",        // matched route pattern, not raw URL (no PII)
    "app_version": "2026.06.27+sha"           // build id
  },
  "props": { /* per-event, see table */ }
}
```

Server adds on ingest: `context.user_id` (from authorizer), `ts_server` (ISO8601 UTC). `ts_client` is kept for **clock-drift detection**, never used as the partition key.

### 3.2 MVP event table

`decision_ms`/`dwell_ms` timers start at content availability (component mount / viewport entry), per the recon gotchas — that is the correct, defensible semantic even across alt-tab.

| event_name | props | Fires at (real path) |
|---|---|---|
| `triage_session_start` | `block_id`, `bucket_id` | `frontend/src/features/triage/routes/BucketDetailPage.tsx` — `BucketDetailInner` mount (`useEffect` on route enter, ~L33-48). session_id = `${blockId}:${bucketId}` scope. |
| `triage_session_end` | `session_ms`, `tracks_seen`, `tracks_categorized`, `undo_rate` (= undo_count/total_assigns; `undo_count` = count of triage `track_categorized`(action=`undo`) in the session) | Same file — `BucketDetailInner` `useEffect` cleanup (unmount / nav away). |
| `track_view` | `track_id`, `dwell_ms` | `frontend/src/features/triage/components/BucketTrackRow.tsx` — IntersectionObserver: start timer on viewport entry, emit on exit/unmount. Same pattern reused in `frontend/src/features/categories/routes/CategoryDetailPage.tsx` (~L89-90) and `features/playlists/.../PlaylistDetailPage` (~L100-114). |
| `track_categorized` (triage) | `track_id`, `decision_ms`, `category_key` (=`toBucket.bucket_type`), `action`=`"moved_to_bucket"` | `frontend/src/features/triage/components/MoveToMenu.tsx` onClick → `BucketDetailPage.handleMove` (~L191) → `move.mutate` **onSuccess** (~L199). |
| `track_categorized` (curate) | `track_id`, `decision_ms`, `category_key` (=destination bucket type), `action`=`"categorized_curate"` | `frontend/src/features/curate/hooks/useCurateSession.ts` — `assign()` (~L48) → `move.mutate` onSuccess (ASSIGN_BEGIN reducer ~L99-105). |
| `track_categorized` (undo) | `track_id`, `surface` (`"triage"`\|`"curate"`), `category_key` (reverted-from bucket type), `action`=`"undo"` | triage: `MoveToMenu`/`BucketDetailPage` undo handler → undo mutation onSuccess; curate: `useCurateSession` undo + `useCurateHotkeys` undo case → onSuccess. **Sources** `fact_track_decision.action='undo'` and `fact_triage_session.undo_count`. |
| `playback_play` | `track_id`, `position_ms`=0, `duration_ms`, `source` (`"triage_player"`\|`"playlist_player"`\|`"category_player"`) | `frontend/src/features/playback/PlaybackProvider.tsx` — `play()` (~L336) after resolve (~L376-379). `source` is set **explicitly at the initiating player panel** (`PlaybackProvider` / `PlaylistPlayerPanel` / `CategoryPlayerPanel`), **not** from `playback/routeContext.ts` (which only exposes `{type:'bucket'\|'category'}` and has no playlist context). |
| `playback_pause` | `track_id`, `position_ms`, `duration_ms`, `seek_count` | Same file — `pause()` / `togglePlayPause()` → use **queueDispatch status, not raw SDK state** (remote-device gotcha). |
| `playback_seek` | `track_id`, `from_position_ms`, `to_position_ms` | Same file — `seekMs()`/`seekPct()` (~L399+). **Debounce 500ms** (slider fires per mouse move). Feeds `fact_seek`. |
| `playback_ended` | `track_id`, `duration_ms`, `listen_through_ratio` (=`position_ms/duration_ms`) | Same file — `player_state_changed` listener (~L220-307), auto-advance branch only (URI-mismatch ~L277-289 or natural-end ~L296-307). **Not** user skip. |
| `playback_skip` | `track_id`, `position_ms`, `duration_ms` | Same file — manual `next()`/advance (user skip) **before** natural end (the path `playback_ended` explicitly excludes). **Sources** `fact_playback.skipped=true`. |
| `hotkey_used` (playback) | `hotkey_code` (`Space`/`KeyJ`/`KeyK`/`KeyA`..`KeyG`/`Shift+KeyJ`/`Shift+KeyK`), `action`, `source`=`"playback"` | `frontend/src/features/playback/usePlaybackHotkeys.ts` — keydown handler (~L25-57), each `preventDefault` branch. |
| `hotkey_used` (curate) | `hotkey_code` (`Digit1`..`Digit9`/`KeyQ`/`KeyW`/`KeyE`/`KeyZ`/`KeyU`/`KeyL`/`Slash`), `action` (`assign_destination`/`undo`/`toggle_force`/`open_help`), `source`=`"curate"` | `frontend/src/features/curate/hooks/useCurateHotkeys.ts` — keydown handler (~L46-100+), each switch case. (Keystroke telemetry only; the actual undo decision is the `track_categorized`(undo) event above.) |
| `playlist_add` | `playlist_id`, `track_count` (=`selected.size`), `source_category_id` | `frontend/src/features/playlists/components/AddTracksModal.tsx` — `handleSubmit()` (~L65) → `addMut.mutateAsync` onSuccess (~L72-76). |
| `playlist_reorder` | `playlist_id`, `track_count`, `reorder_count` | `frontend/src/features/playlists/routes/PlaylistDetailPage.tsx` — `handleReorder()` (~L135) → reorder mutation onSuccess (`useReorderPlaylistTracks` ~L22-27). Debounced 200ms. |
| `playlist_publish` | `playlist_id`, `track_count`, `confirm_overwrite`, `skipped_count`, `target` (`"spotify"`\|`"ytmusic"`) | `frontend/src/features/playlists/components/PublishButton.tsx` — `doPublish()` (~L32) onSuccess (~L34-53). `PublishYtMusicButton` is the `ytmusic` variant. |

All events validated against an enum + per-event prop allowlist server-side; unknown `event_name` → reject the single event (not the batch). Schema-on-read means new props need no migration. **Note (skip vs undo):** in **playback**, "skip" is a real terminal event (`playback_skip`); in **triage/curate**, there is no skip — the only reversal is undo (`track_categorized`(undo)). Keep the two distinct.

---

## 4. Telemetry SDK design

Location: `frontend/src/lib/telemetry/sdk.ts` (module-level singleton) + `frontend/src/lib/telemetry/hooks.ts` (optional `useTelemetry()` convenience hook). Mirrors the existing `tokenStore`/`spotifyTokenStore` module-singleton pattern — **no React context**.

### 4.1 Buffering & flush
- **Buffer:** in-memory array. `track(event_name, props)` builds the envelope (client fields + `event_id` ULID + current `session_id` + matched `route`), pushes to buffer. Never throws into caller.
- **Batch flush triggers:**
  1. **Interval** — every 10s if buffer non-empty.
  2. **Size** — when buffer reaches 25 events.
  3. **`visibilitychange` → hidden** and **`pagehide`** — flush immediately (tab backgrounded / closed). This is the critical one for not losing the tail of a session.
- **Idempotency:** `event_id` is a ULID; the pipeline is at-least-once, dedup is a dbt concern (`row_number() over (partition by event_id …)`), not an SDK concern.
- **Session id:** UUID generated fresh on SDK init per tab. **Not** persisted to storage (matches the "session not persisted across tab close" rule). New tab = new session.

### 4.2 Transport — **fetch keepalive, NOT sendBeacon** (blocking AWS fact)

`/v1/telemetry` sits behind the existing custom authorizer and stamps `user_id` from it, so **every** flush — including the unload flush — must carry `Authorization: Bearer <jwt>`. `navigator.sendBeacon` **cannot set custom headers** (spec/MDN confirmed) and would 401. Therefore: `fetch` keepalive, with the bearer attached but **auth-failure suppressed**.

```ts
// frontend/src/lib/telemetry/sdk.ts (transport)
// api() gains a {suppressAuthFailure:true} option: attach bearer + run the
// inflight-deduped refresh as usual, but on refresh failure resolve/throw-and-swallow
// WITHOUT calling notifyAuthFailure()/dispatching 'auth:expired'.
api('/v1/telemetry', {                 // reuse frontend/src/api/client.ts -> reads tokenStore, sets bearer
  method: 'POST',
  keepalive: true,                     // survives visibilitychange/pagehide/unload
  suppressAuthFailure: true,           // a 401 we can't refresh is swallowed, never a logout
  body: JSON.stringify({ events }),
});
```

- **Do not route telemetry through the unmodified `api()` path.** Plain `api()` (`frontend/src/api/client.ts:42-46`) calls `notifyAuthFailure()` on refresh failure — it clears `tokenStore` and dispatches the global `'auth:expired'` event (logout). Telemetry runs on a 10s interval and on `visibilitychange`→hidden (tab still alive); a background POST that 401s and can't refresh would otherwise **log the user out**, violating "telemetry must never surface to the user." The new `{suppressAuthFailure:true}` option attaches the bearer and does the inflight-deduped refresh but swallows the failure instead of notifying.
- **Unload-path caveat:** `/auth/refresh` (`client.ts:21-24`) is **not** keepalive, so a refresh started during `pagehide`/`unload` can be aborted. The unload flush is therefore best-effort with whatever bearer already sits in `tokenStore` — **there is no silent-refresh guarantee on the unload path** (a stale-token unload flush may simply 401 and be dropped). This is acceptable: analytics is loss-tolerant.
- **64KB keepalive cap:** the browser caps the *total* body of all in-flight `keepalive` requests at 64KB. The unload flush must **chunk** the buffer into <64KB POSTs (≈ a few hundred small events; with a 25-event batch cap this is comfortably under, but the chunker is mandatory because the *interval* path can let the buffer grow if a flush failed).
- **Failure = silent, drop.** On network/`ApiError` (including a swallowed 401), **drop the batch** — never retry, never notify (matches §4.3 "No retry/backoff queue"). Telemetry must never block or surface to the user.
- Do **not** cancel the AuthProvider refresh timer; SDK is a passive consumer of `tokenStore`.

### 4.3 What the SDK must never do
- Never read or send `bp_token` (`features/admin/lib/bpTokenStore.ts`) — it has no reason to touch admin state.
- Never set `context.user_id` — server stamps it.
- Never persist events or `session_id` to `localStorage`/`sessionStorage`/cookies.

> `// ponytail:` the SDK is ~120 lines (buffer + 3 triggers + chunked keepalive flush). No retry/backoff queue, no offline IndexedDB store — analytics is loss-tolerant. Add a persistent retry buffer only if dashboards show material event loss.

---

## 5. Ingest pipeline (Phase 1)

```
React SDK ──batched POST /v1/telemetry (bearer, keepalive)──▶ API Gateway (existing) + custom authorizer (→ user_id)
   └─▶ telemetry Lambda (standalone, own role)  (validate envelope, stamp user_id + ts_server)
         └─PutRecordBatch─▶ Kinesis Firehose (Direct PUT, buffer 5min/5MB, JSON→Parquet via Glue schema, dynamic partition by date+event)
               └─▶ S3 bronze ─(dbt-athena daily)─▶ silver ─▶ gold + Glue Data Catalog
                     └─▶ Athena (SQL)  ◀── analytics-api Lambda (standalone) ◀── /admin/analytics SPA route

EventBridge daily ─▶ catalog_export Lambda (Data API → bronze/catalog_export)  ─┐
                  └▶ ops_log_export Lambda (CloudWatch Logs → bronze/ops)        ─┴─▶ [dbt build/test → gold]
```

This is an **isolated contour**. It shares only the API Gateway and the custom authorizer; telemetry ingest is a **standalone `telemetry` Lambda** (§5.1). It must not touch the collector, the Beatport ingest **worker**, its SQS, or any Aurora **write**. The only Aurora read is the daily `catalog_export` (§6).

### 5.1 Route registration (three places — from recon)
1. **New Lambda module `src/collector/telemetry_handler.py`** with its own `lambda_handler(event, context)` entry point — **not** a branch in the collector `handler.py` `_route()` table. It reads `event['requestContext']['authorizer']['lambda']['user_id']` (the `_authorizer_context` pattern, `auth_handler.py:537-545`) and may import shared package code (schemas, `logging_utils`, `secrets`). Standalone, mirroring how `analytics-api` is a separate function (§10.1).
2. **`scripts/generate_openapi.py`** `ROUTES` (before `]` at ~L3727) — full request/response contract (this is what the frontend CI diff-checks against `schema.d.ts`, so no ellipsis):
   ```python
   {"method":"post","path":"/v1/telemetry","auth":AUTH,
    "summary":"Ingest telemetry events",
    "requestBody":{"required":True,"content":{"application/json":{"schema":{
        "type":"object","required":["events"],
        "properties":{"events":{"type":"array","maxItems":256,         # §5.2 batch cap
                                 "items":{"$ref":"#/components/schemas/TelemetryEnvelope"}}}}}}},  # §3.1 envelope
    "responses":{
        "202":{"description":"Accepted","content":{"application/json":{"schema":{
            "type":"object","properties":{"accepted":{"type":"integer"},"rejected":{"type":"integer"}}}}}},
        "400":{"$ref":"#/components/responses/Error"}}}                # standard error envelope (unparseable body only)
   ```
   The 256KB byte cap (§5.2) is enforced in the handler, not the schema. Then regenerate: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`.
3. **`infra/telemetry.tf`** (new): the `aws_lambda_function.telemetry` (own role, §13) + its **own** `aws_apigatewayv2_integration.telemetry_lambda` (AWS_PROXY) + `aws_apigatewayv2_route.telemetry_post`, `route_key="POST /v1/telemetry"`, `target=integrations/${aws_apigatewayv2_integration.telemetry_lambda.id}`, `authorization_type="CUSTOM"`, `authorizer_id=aws_apigatewayv2_authorizer.jwt.id`. Mirrors the standalone `analytics-api` wiring (§10.1), not the collector integration.

> `// ponytail:` **standalone `telemetry` function** for strict isolation — own least-privilege role (Firehose-only), own concurrency, zero collector blast radius. It **shares the one zip** built by `scripts/package_lambda.sh` (same package, different entry point — `collector.telemetry_handler.lambda_handler`), exactly like `catalog_export`/`analytics-api`, so there is no extra build step or new artifact — just one more `aws_lambda_function` pointing at a different handler.

### 5.2 telemetry handler (standalone `telemetry` Lambda, module `src/collector/telemetry_handler.py`)
- Parse body `{events: [...]}`. Reject batch >256 events or >256KB (defense-in-depth, matches the OpenAPI `maxItems`).
- Per event: validate `event_name` enum + prop allowlist (Pydantic models, one per event family). Stamp `context.user_id` from authorizer, `ts_server` UTC. Strip any client-sent `user_id`/secret-shaped keys.
- Drop invalid events individually; respond **202 Accepted** with `{accepted, rejected}` counts. (400 only for an unparseable body.)
- `PutRecordBatch` valid events to Firehose (each record = one NDJSON line, `\n`-terminated). On Firehose partial failure, log counts (allowlisted fields only) and **do not** retry inline (loss-tolerant).
- IAM: the **`telemetry` Lambda has its own least-privilege role** — one `firehose:PutRecordBatch` statement scoped to the telemetry stream, nothing else (see §13). The collector role is untouched.
- Logging: reuse `logging_utils` allowlist (`correlation_id`, `user_id`, `status_code`, `duration_ms`, `event`, `attempt`, counts). Never log envelope `props` verbatim (could carry free-text later); log counts only.

### 5.3 Firehose (Direct PUT, JSON→Parquet)
- **Direct PUT** (not Kinesis Data Streams — no shard/idle cost). `$0.029/GB` ingest.
- **Buffer:** 5 min / 5 MB (whichever first) — already batches, mitigates the 5KB-per-record billing floor.
- **Format conversion JSON→Parquet** requires a **Glue Data Catalog table schema** (confirmed) and adds `$0.018/GB`. Define the bronze table schema in Terraform DDL (see 5.5) — Firehose points at it for conversion.
- **Dynamic partitioning** by `dt` (server date) + `event_name`: `$0.020/GB processed` + `$0.005/1,000 objects`. Partition keys extracted via Firehose jq on the uncompressed JSON before conversion.
- **No Glue Crawler** (crawlers are $0.44/DPU-hr). Tables are declared via Terraform/DDL and partitions handled by partition projection. **Operational cost of the `event_name` partition:** partition projection uses an `enum` that must list every `event_name` value in the Glue table properties (Terraform). Adding a new `event_name` therefore requires a one-line Terraform edit to that enum (the *props* stay schema-on-read; only new partition *values* need the edit). `// ponytail:` ~14 fixed event names — a trivial edit when a new one ships; switch to `dt`-only partitioning (event_name as a plain column) only if the enum churn ever becomes annoying.

### 5.4 S3 medallion layout

Single bucket `beatport-prod-analytics-lake`, prefix-separated layers. **Partition projection** on `dt`+`event_name` avoids partition-registration cost entirely.

```
s3://beatport-prod-analytics-lake/
  bronze/events/                # Firehose Parquet, raw envelope, schema-on-read
    dt=2026-06-27/event_name=track_categorized/part-*.parquet
  bronze/catalog_export/        # daily Aurora dim snapshots (§6), line-delimited JSON (NDJSON)
    snapshot_dt=2026-06-27/clouder_tracks/part-*.json
  bronze/ops/                   # daily ops_log_export: enrichment/latency metrics pulled from CloudWatch (§16.1)
    dt=2026-06-27/part-*.json
  silver/                       # dbt: cleaned, typed, deduped-on-event_id, one model per event family
    fct_events_clean/dt=.../...
  gold/                         # dbt: star schema (facts + dims), the only layer dashboards read
    fact_track_decision/  fact_playback/  fact_seek/  fact_triage_session/  fact_funnel_step/
    dim_track/ dim_artist/ dim_label/ dim_user/ dim_category/ dim_date/
  athena-results/               # Athena query output + result cache (lifecycle-expire 7d)
```

**Lifecycle / retention:** `athena-results/` expires after 7 days; `bronze/` transitions to S3-IA after 90 days. `silver/` and `gold/` are **retained indefinitely** — a few GB of Parquet is pennies. No separate compaction job is needed: gold dims rebuild fully each run (`table`) and gold facts are `insert_overwrite` per `dt` (§8), so partitions are replaced wholesale rather than accreting small files.

### 5.5 Glue Data Catalog
- One database `clouder_analytics`. Bronze table declared in Terraform (`aws_glue_catalog_table`) with the envelope schema so Firehose can convert; the `catalog_export` and `ops` JSON prefixes also get lightweight Glue tables (types applied on read). Silver/gold tables are **created and managed by dbt-athena** (no crawler).
- Free tier: <1M objects / <1M requests = **$0**.

---

## 6. Catalog dimension sourcing (Aurora → lake, batch, no live psycopg)

Dimensions come from the Aurora catalog but **never via live query at dashboard time** (Data-API-only + cost + cold-start). A daily **export step** snapshots the needed tables to `bronze/catalog_export/`, and dbt builds the dims from those snapshots.

- **Mechanism:** a Lambda (`catalog_export`, in the existing collector package) runs the read queries through the **RDS Data API** (`data_api.execute()`, reusing `repositories.py` patterns), pages results, and writes **line-delimited JSON (NDJSON)** to S3. NDJSON deliberately avoids bundling `pyarrow`/`awswrangler` (~120MB unzipped) into the collector zip — that would risk the 250MB unzipped Lambda limit and bloat the collector's cold start, and Parquet isn't required: a lightweight Glue table types the columns and dbt-athena/Athena cast on read. This is the *only* sanctioned Aurora touch — read-only, batched, off the user path.
- **Tables exported (from recon):**

| dim | Aurora source | Key columns |
|---|---|---|
| `dim_track` | `clouder_tracks` | `id, title, bpm, key_name, key_camelot, spotify_release_date, publish_date, album_id, style_id, isrc, release_type, is_ai_suspected, origin, created_at, updated_at` |
| `dim_artist` | `clouder_artists` + `clouder_track_artists` (junction `track_id, artist_id, role`) | `id, name, normalized_name, is_ai_suspected` |
| `dim_label` | `clouder_labels` ← `clouder_albums.label_id` ← `clouder_tracks.album_id` | label `id, name, normalized_name`; album `id, label_id, release_date, release_type` |
| `dim_category` | `categories` (per-user per-style) + `category_tracks` (`category_id, track_id, added_at`) | `id, user_id, style_id, name, normalized_name, position, created_at, deleted_at` |
| `dim_date` | generated in dbt, no source | see §7 |

- **Volume:** full-table snapshots are small (tens of thousands of rows); daily full refresh is simpler than CDC and cheap. `// ponytail:` full snapshot, not incremental — add CDC only if the catalog grows past Data-API paging comfort.
- **`dim_user`:** sourced from the events themselves (distinct `user_id`) plus, if needed, a minimal users export. No PII beyond the opaque `user_id`.

---

## 7. Data model (gold star schema, built by dbt)

### Facts

| fact | grain | columns |
|---|---|---|
| `fact_track_decision` | one categorization or undo | `decision_key (pk), event_id, user_key, track_key, category_key, date_key, decision_ms, dwell_ms, action ('moved_to_bucket'\|'categorized_curate'\|'undo'), surface ('triage'\|'curate'), ts_server` |
| `fact_playback` | one play (a `playback_play` matched to its terminal pause/end/skip) | `playback_key (pk), event_id, user_key, track_key, date_key, source, played_ms, duration_ms, listen_through_ratio, seek_count, skipped (bool), ts_server` |
| `fact_seek` | one seek | `seek_key (pk), event_id, user_key, track_key, date_key, from_position_ms, to_position_ms, ts_server` — sourced from `playback_seek`; powers the Dashboard 4 seek heatmap |
| `fact_triage_session` | one triage session | `session_key (pk), session_id, user_key, block_id, bucket_id, date_key, session_ms, tracks_seen, tracks_categorized, undo_count, undo_rate, ts_start, ts_end` |
| `fact_funnel_step` | one lifecycle step transition per track | `funnel_key (pk), user_key, track_key, date_key, step ('ingested'\|'viewed'\|'categorized'\|'playlisted'\|'published'), ts, prev_step, ms_since_prev` |

> **`action='undo'` is sourced** by the `track_categorized`(undo) event (§3.2) — a deliberate decision to keep the value in the enum (a review note suggested dropping it as "unsourced"; the undo event makes it sourced, so it stays). `fact_playback.skipped` is derived in dbt from whether the terminal event of a play is `playback_skip` (§8).

### Dimensions

| dim | grain | columns |
|---|---|---|
| `dim_track` | track | `track_key (pk), track_id, title, bpm, key_name, key_camelot, genre/style_id, release_date, label_key, is_ai_suspected, origin` |
| `dim_artist` | artist (+ bridge to track for many-to-many) | `artist_key (pk), artist_id, name, normalized_name, is_ai_suspected`; bridge `track_key, artist_key, role` |
| `dim_label` | label | `label_key (pk), label_id, name, normalized_name` |
| `dim_user` | user | `user_key (pk), user_id` (opaque; no PII) |
| `dim_category` | category | `category_key (pk), category_id, user_id, style_id, name, normalized_name, position, deleted_at` |
| `dim_date` | calendar day | `date_key (pk), date, saturday_week_year, saturday_week_number, iso_week_year, iso_week_number, day_of_week, month, quarter, year` — Saturday-week per ADR-0003 (week 1 = first Saturday on/after Jan 1) |

`*_key` are surrogate keys. Facts carry **`user_key`** (FK to `dim_user`); `dim_user` holds only the opaque `user_id`, so there is **no PII to look up** anywhere. `device`/`route`/`app_version` stay in silver (and bronze) and are **not** denormalized into facts — no Phase-1 dashboard segments on them. Add one to a fact only when a dashboard needs that segment.

**Ops domain:** intentionally **outside this star schema** — it is log-backed. `ops_log_export` lands enrichment success/latency metrics to `bronze/ops/`, and Dashboard 5 reads that plus `bronze/events` freshness directly (§11, §16.1). Promote to a `fct_pipeline_runs` fact only if Dashboard 5 outgrows raw reads.

---

## 8. Transform layer (dbt-athena)

- **Adapter:** `dbt-athena` (maintained by dbt Labs, merged into `dbt-labs/dbt-adapters`; active through 2026). Safe to depend on.
- **Project layout:** `analytics/dbt/` — `models/silver/` (staging: clean/type/dedup-on-`event_id`, one model per event family), `models/gold/` (facts + dims above), `seeds/` (e.g. category-key map if needed), `macros/` (Saturday-week date spine).
- **Materializations (Hive Athena tables, no Iceberg in P1):**
  - silver = `incremental`, `incremental_strategy='insert_overwrite'`, partitioned by `dt`.
  - gold dims = `table` (small, full rebuild each run).
  - gold facts = `incremental`, `incremental_strategy='insert_overwrite'`, partitioned by `dt`.
  - In **every** incremental model, dedup at-least-once duplicates **in-model** with `row_number() over (partition by event_id order by ts_server) = 1`. The append window is `dt`; the dedup key is `event_id`. `insert_overwrite` replaces a `dt` partition wholesale, so reprocessing a partition never duplicates rows. Note: `dbt-athena` only supports `append`/`insert_overwrite` on Hive tables — `merge`/`unique_key` upsert needs **Iceberg**, which is deferred to P2 (§15). `insert_overwrite` + in-model `row_number()` gives idempotent dedup without it.
- **`fact_funnel_step` model:** a window function over each track's events ordered by `ts_server` assigns `step`/`prev_step` and computes `ms_since_prev = ts - lag(ts) over (partition by track_key order by ts_server)`. `viewed`/`categorized`/`playlisted` come from `track_view`/`track_categorized`/`playlist_add`; `ingested` is merged from `clouder_tracks.created_at` and `published` from the `playlist_publish` event (joined to the catalog), both from the daily catalog export — no live join.
- **`fact_playback` model:** each `playback_play` is matched to its terminal event within `(session_id, track_id)` ordered by `ts_server` — `playback_ended` (natural end / auto-advance), `playback_skip` (manual next), or the last `playback_pause`. `skipped = (terminal is playback_skip)`; `played_ms = terminal position_ms`; `listen_through_ratio` from `playback_ended` (else `played_ms/duration_ms`); `seek_count` = count of `playback_seek` rows for the play.
- **`fact_seek` model:** one row per `playback_seek` (`from_position_ms`/`to_position_ms`), straight passthrough to gold for the Dashboard 4 heatmap.
- **`dim_date` Saturday-week macro:** generate a date spine and compute `saturday_week_*` (first Saturday on/after Jan 1 = week 1). Mirror the logic in `src/collector/saturday_week.py` so backend and analytics agree.
- **dbt tests (data contract):** `not_null`/`unique` on every surrogate key + `event_id`; `accepted_values` on `event_name`, `action`, `step`, `source`; `relationships` from facts → dims; freshness test on `bronze/events` (fail if newest `dt` older than ~36h). These tests are the Phase-1 quality gate.
- **dbt docs:** `dbt docs generate` emits the lineage DAG as a build artifact (portfolio value).

### Where dbt runs (cheapest)
- **Primary: Lambda container image** (`dbt-runner`) — fits the Lambda **free tier** (~$0), capped at 15 min / 10 GB. A small daily build is well under that.
- **Fallback: Glue Python Shell** at 0.0625 DPU (~$0.0275/hr, 1-min min) — a daily ~5-min build ≈ a few cents/mo. Use only if a build exceeds the 15-min Lambda ceiling.
- Drop Fargate (overkill).

> `// ponytail:` start with the Lambda-container dbt-runner; it's free and the model count is tiny. Migrate to Glue Python Shell only when a `dbt build` measurably approaches 15 min.

---

## 9. Orchestration (Step Functions Standard + EventBridge Scheduler)

Daily pipeline, one **EventBridge Scheduler** rule (~30 invocations/mo ≈ **$0.00003/mo** at $1/M invocations — effectively $0) triggers one **Step Functions Standard** state machine:

```
[ catalog_export (Lambda, Data API → bronze/catalog_export)  ‖  ops_log_export (Lambda, CloudWatch Logs → bronze/ops) ]
   → dbt_run  (dbt-runner: build silver + gold; Firehose has been landing bronze/events continuously)
   → dbt_test (quality gate; on fail → SNS/log, stop, keep serving yesterday's gold)
```

- `catalog_export` and `ops_log_export` run in **parallel** (both land bronze before `dbt_run`).
- **Standard** (not Express) for the daily batch; ~a few hundred state transitions/mo, inside the 4,000 free transitions/mo (permanent).
- On `dbt_test` failure: mark the run failed, emit a structured log + (optional) SNS, **do not** publish stale gold. Dashboards keep serving yesterday's gold.
- No `register_partitions` state: partition projection (§5.4) already covers partition discovery, so a refresh/MSCK step would be a no-op — add one only if a future table ever needs explicit registration.
- Not MWAA: Airflow floor is ~$358/mo (mw1.small) — ~70× the entire Phase-1 budget. Step Functions + Scheduler is the idle-zero choice.

---

## 10. Serving (Phase 1, in-app)

### 10.1 Route + serving gating
- New SPA route **`/admin/analytics`**, admin-gated (reuse the existing admin gate that protects `/admin`). Renders the five dashboards (§11) with Mantine charts.
- **`analytics-api` is a standalone Lambda function** with its own least-privilege role (Athena + S3 read on `gold/` + `athena-results/`). It **may share the zip artifact** (like `catalog_export`) but is a **separate function and integration** — it is *not* a dispatch branch in the collector handler, so the collector role never gains Athena/S3-gold read. The five routes — `GET /v1/analytics/{triage,taste,funnel,playback,ops}` — get their **own admin-gated API Gateway integration** to this function (registered via the three-place rule, §5.1, in a new `infra/analytics_routes.tf`). They are **not** added to the collector handler's `_ADMIN_ROUTES` table; instead `analytics-api` enforces the admin check itself on the authorizer context. Each route runs a **parameterized, pre-written Athena query** against `gold/` — clients pick a date range + filters, never send raw SQL.

### 10.2 Result cache
- Athena query results land in `s3://.../athena-results/`. The `analytics-api` Lambda **reuses Athena's result reuse** (`ResultReuseByAgeConfiguration`, e.g. 60 min) so repeated dashboard loads scan ~$0. Add a thin in-Lambda `@lru_cache` keyed by `(query_id, params)` for the warm-Lambda window.

> `// ponytail:` Athena result-reuse + warm-Lambda memo is the whole cache. No Redis/DynamoDB cache layer — add one only if dashboard concurrency makes Athena latency visible.

### 10.3 Cold-start note
Aurora is **not** in this path, so the ADR-0014 cold-start 503 does not apply to dashboards. Athena queries are independent of Aurora min_acu.

---

## 11. Dashboards (the value story)

| # | Dashboard | Question answered | Metrics | Fact / dim |
|---|---|---|---|---|
| 1 | **Triage efficiency** | Am I getting faster and cleaner at curating? | median `decision_ms` over time, time per category, throughput (tracks/hour), **undo rate** | `fact_track_decision`, `fact_triage_session` (`undo_rate`) × `dim_date`, `dim_category` |
| 2 | **Taste profile (behavior × catalog)** | What music do I actually keep vs skip? | category mix by genre/BPM/key, **label affinity (categorize-rate vs playback skip-rate per label)**, BPM histogram | `fact_track_decision` × `dim_track`, `dim_label`, `dim_artist`; **`fact_playback`** (the skip signal) joined by `track_key` |
| 3 | **Funnel** | Where do tracks drop off from ingest to publish? | lifecycle funnel drop-off %, time-to-publish, weekly throughput by **Saturday-week** | `fact_funnel_step` × `dim_date` (Saturday-week), `dim_track` |
| 4 | **Playback** | Does how I listen predict how I categorize? | listen-through distribution, listen-ratio vs final-category correlation, seek heatmap | `fact_playback` × `dim_track`; **`fact_playback` → `fact_track_decision` → `dim_category`** (join by `track_key`+`user_key`, since `fact_playback` has no `category_key`) for the listen-ratio-vs-category correlation; **`fact_seek`** × `dim_track` for the heatmap |
| 5 | **Ops / pipeline health** | Is the ingest + enrichment pipeline healthy and fresh? | enrichment success rate, latency p50/p95, pipeline freshness lag (newest `dt` vs now) | **log-backed (not the star schema):** `bronze/ops/` (from `ops_log_export`) + `bronze/events` freshness via dbt freshness test |

Dashboard 2's "skip" half and Dashboard 4 both rely on `fact_playback.skipped` (derived from `playback_skip`, §8) — there is no "skip" in triage/curate, only `undo`, so Dashboard 1 reports **undo rate** (the single `fact_triage_session.undo_rate` field), not a "skip+undo" sum. Dashboard 5's ops data comes from the existing structured Lambda logs (allowlisted fields) pulled to `bronze/ops/` by `ops_log_export`; the enrichment metrics fields (`completed_phases`, `failed_after`, `source_hint`, `duration_ms`, `vendor`) are already emitted by `logging_utils.py`.

---

## 12. Cost model (Phase 1, verified, portfolio volume)

Assume a generous **2M small events/mo** (heavy single-user/small-circle use). Firehose 5KB-per-record floor dominates → ~10 GB billed.

| Service | Driver | Verified rate | Est. $/mo |
|---|---|---|---|
| Kinesis Firehose ingest | ~10 GB (5KB floor × 2M) | $0.029/GB | $0.29 |
| Firehose format conversion | ~10 GB | $0.018/GB | $0.18 |
| Firehose dynamic partitioning | ~10 GB + objects | $0.020/GB + $0.005/1k obj | ~$0.25 |
| Athena | ~thousands of queries, ~10 MB floor each | $5/TB, 10 MB min/query | <$0.10 |
| Glue Data Catalog | handful of tables/partitions | free <1M objects/requests | $0.00 |
| Step Functions | ~30 runs × few states | 4,000 free transitions/mo | $0.00 |
| EventBridge Scheduler | ~30 invocations | $1/M invocations | ~$0.00 (≈$0.00003) |
| Lambda (telemetry, analytics-api, dbt-runner, catalog_export, ops_log_export — all in the one shared zip) | portfolio volume | 1M req + 400k GB-s free | ~$0.00 |
| S3 storage | few GB Parquet | $0.023/GB-mo + requests | <$0.20 |
| **Total** | | | **~$1.00–1.50/mo** |

Comfortably under the $5 ceiling. Cost is driven by **event count** (5KB floor), not bytes — Firehose buffering already mitigates it. No always-on compute anywhere. (The `telemetry` function is its own Lambda but shares the collector zip artifact and stays inside the free tier — ~$0.)

---

## 13. Security & privacy

- **`bp_token`:** structurally impossible in this contour — the envelope has no field for it, the SDK never reads `bpTokenStore`, and `bp_token` is already in `SENSITIVE_KEYS` redaction (`logging_utils.py:13`). Telemetry handler logs counts, never `props`.
- **`user_id` server-stamped:** read only from `event['requestContext']['authorizer']['lambda']['user_id']`; any client-sent `user_id` is stripped before Firehose. No frontend-derived identity is trusted.
- **No PII in events:** `route` is the matched pattern (no IDs in the URL string that could be PII), `device`/`app_version` are coarse. `dim_user` is opaque `user_id` only.
- **Admin-gated serving:** `/admin/analytics` (SPA admin gate) + `/v1/analytics/*` (admin check enforced in `analytics-api`) are admin-only. Per-user telemetry is visible only to admins; a user cannot read another user's analytics.
- **Transport:** bearer JWT over HTTPS via the existing authorizer; keepalive flush carries the same bearer (never `bp_token`). 64KB keepalive cap respected by the chunker. Telemetry uses `api(..., {suppressAuthFailure:true})` (§4.2) so a 401 that can't refresh is **swallowed silently** — it never fires `notifyAuthFailure()`/`auth:expired`, so a background or unload telemetry POST can never log the user out.
- **IAM least privilege:** the **`telemetry` Lambda has its own dedicated role** = one `firehose:PutRecordBatch` statement scoped to the telemetry stream, nothing else (the collector role is never touched). `catalog_export` role = Data-API read + `s3:PutObject` on `bronze/catalog_export/*`; `ops_log_export` role = CloudWatch Logs read (the enrichment/worker log groups) + `s3:PutObject` on `bronze/ops/*`; `dbt-runner` = Athena + Glue + S3 on the lake; `analytics-api` = Athena read + S3 read on `gold/` + `athena-results/`. Each function has its own dedicated role.
- **Logging:** allowlist only (`correlation_id, api_request_id, lambda_request_id, user_id, status_code, duration_ms, event, phase, attempt, error_*`); never the raw envelope.

---

## 14. Testing strategy

- **SDK (frontend, jsdom):** unit-test buffer flush triggers (interval/size/visibilitychange), envelope construction, that `bp_token`/`bpTokenStore` is never imported (lint rule + test), that transport uses `keepalive:true` and `api(..., {suppressAuthFailure:true})` (bearer is set **and** a 401 never triggers `notifyAuthFailure`/logout), and chunking stays <64KB. jsdom for logic; no CSS so no `pnpm test:browser` needed here.
- **Telemetry handler (pytest unit):** envelope validation (enum + prop allowlist), `user_id` stamped from authorizer / client `user_id` stripped, invalid event dropped not batch, 202 with counts, batch >256 / >256KB rejected, Firehose `PutRecordBatch` called with NDJSON. Reuse `tests/unit/` conventions; `PYTHONPATH=src`.
- **dbt tests = the data contract:** `not_null`/`unique` keys, `accepted_values` enums, `relationships` fact→dim, **freshness** on bronze, and an in-model dedup assertion (no duplicate `event_id` survives `insert_overwrite`). These run in `dbt_test` in the Step Functions DAG and (Phase 3) in CI.
- **Saturday-week:** a focused test asserting `dim_date` week boundaries match `src/collector/saturday_week.py` (week 1 = first Saturday on/after Jan 1) on a few known dates incl. year boundary. `// ponytail:` one parametrized test, not a suite.
- **OpenAPI drift:** after adding the route, regenerate `docs/api/openapi.yaml` and confirm `frontend/src/api/schema.d.ts` matches (frontend CI gate).
- **Integration smoke (manual/one-shot):** POST a batch → confirm a Parquet object lands in `bronze/events/dt=.../event_name=.../` and Athena `SELECT count(*)` returns it.

---

## 15. Phase roadmap

| Phase | Scope | Key services | Skills demonstrated | Budget (verified) |
|---|---|---|---|---|
| **P1 — Lakehouse MVP** (this spec) | Full contour + dashboards 1–5 in-app | Firehose (Direct PUT, JSON→Parquet), S3 medallion, Glue Catalog, Athena, dbt-athena, Step Functions (Standard), EventBridge Scheduler, Terraform | serverless ingest, lakehouse, star-schema modeling, orchestration, IaC | **~$1–2/mo** (ceiling $5) |
| **P2 — Real BI** *(future task)* | Replace/augment in-app charts with a BI tool; adopt Iceberg table format (enables true `merge`/`unique_key` upsert-by-`event_id`, replacing the P1 `insert_overwrite`+`row_number()` dedup) | **Amazon Managed Grafana on Athena** (default: $9/mo editor, $5/mo viewer) — *or* QuickSight (Author ~$18–24/mo + Reader $0.30/session cap $5) | BI dashboards, semantic layer, Iceberg | **~$9–24/mo** (one seat; Grafana cheaper, fits the band better) |
| **P3 — Warehouse + quality** *(future task)* | Load gold marts into a warehouse, compare lakehouse vs warehouse; add a data-quality gate | **Redshift Serverless** (**8 RPU minimum base** — the smallest selectable, ~$0.36–0.375/RPU-hr → ~$2.88–3.00/hr when active, **auto-pause to zero**) + dbt tests in CI + Glue Data Quality | warehousing, perf comparison, CI data quality | **$20–50/mo** *only with aggressive auto-pause + bursty use; never leave it warm (8 RPU 24/7 ≈ $2,100/mo)* |
| **P4 — Streaming / ML stretch** *(future, cost-gated)* | Live session metrics or clickstream→track recs back into the app | **Managed Flink** (~$170/mo continuous floor — run in bursts/demos only, tear down when idle) *or* **Amazon Personalize** (prefer **v2 per-request recipes / batch inference** to dodge the ~$146/mo always-on TPS floor) | streaming, real-time ML, recommendations | **$0 idle if torn down; $146–170+/mo if left running — explicitly cost-gated** |

**Cross-cutting (all phases):** data contract on the envelope, CI `dbt build` + tests, auto dbt-docs lineage DAG artifact, a mini cost dashboard.

---

## 16. Open questions / risks

1. **Ops-domain log shipping (Dashboard 5):** CloudWatch Lambda logs → S3 needs a subscription filter or scheduled export. **Decision (now first-class):** Phase 1 ships an EventBridge-Scheduler-driven Lambda, **`ops_log_export`**, that pulls the relevant log groups' enrichment/latency metrics to `bronze/ops/`. It is carried through the architecture body: §5 diagram, §9 DAG (parallel sibling of `catalog_export`, before `dbt_run`), §12 cost (5th Lambda line), §13 IAM (own role). Full CloudWatch→Firehose subscription is a P2 nicety. Dashboard 5 starts with enrichment success/latency (from `bronze/ops/`) + pipeline freshness (reads `bronze/events` `dt` — needs no log shipping).
2. **Funnel "ingested" + "published" steps:** `viewed`/`categorized` come from events, but `ingested` and `published` are catalog/Aurora state. **Decision:** derive `ingested` from `clouder_tracks.created_at` and `published` from the `playlist_publish` event + catalog, both joined in dbt from the daily catalog export — no live join. The ordered transition rows (`prev_step`, `ms_since_prev`) are built with a window over per-track events ordered by `ts_server` (§8).
3. **Client clock drift:** `ts_client` can be wrong/skewed. **Decision:** partition and aggregate on `ts_server` only; keep `ts_client` solely for a drift-monitoring metric.
4. **Event loss under unload:** keepalive 64KB cap + best-effort flush (and the no-keepalive `/auth/refresh` on the unload path, §4.2) means some tail events drop on crash/hard-kill or stale-token unload. **Accepted** — analytics is loss-tolerant; dedup on `event_id` handles the at-least-once duplicates, not the at-most-once gaps.
5. **`dim_user` growth / GDPR-style delete:** opaque `user_id` only, no PII, so a user delete = drop their `user_id` rows. **Decision:** add a one-shot partition-rewrite dbt op if/when a user-delete feature lands; out of Phase-1 scope.
6. **Firehose 5KB floor at higher volume:** if event count grows 10×, ingest cost grows with count not bytes. **Mitigation:** the SDK already batches; if needed, server-side bundle multiple envelopes per Firehose record to amortize the 5KB floor. Not needed at portfolio volume.
7. **Catalog export paging limits:** RDS Data API has result-size limits; full-snapshot paging must chunk. **Decision:** page by primary-key range; revisit CDC only past comfort (§6).

---

## 17. Rollout order & definition of done

Ship in this order — each step is independently verifiable and reversible:

1. **SDK behind a flag** (`VITE_TELEMETRY_ENABLED`, default off): buffer + 3 triggers + chunked keepalive transport with `{suppressAuthFailure:true}`. With no backend yet it can point at a dev stream or no-op-drop. Lands SDK unit tests.
2. **`/v1/telemetry` route + landing:** the standalone `telemetry` Lambda + its own role/integration/route (§5.1), the role's `firehose:PutRecordBatch` statement, the Firehose stream + bronze Glue table (Terraform). Flip the flag in a dev build → **events land in `bronze/events/`**.
3. **Catalog + ops export:** `catalog_export` (NDJSON dims) and `ops_log_export` (CloudWatch → `bronze/ops/`) Lambdas → daily snapshots land.
4. **dbt + orchestration:** `analytics/dbt/` (silver + gold), Step Functions state machine, EventBridge Scheduler. **`dbt build` + `dbt_test` green; gold populated.**
5. **Serving:** `analytics-api` standalone Lambda + 5 admin-gated routes + `/admin/analytics` SPA dashboards.

**Phase-1 acceptance checklist (done when all hold):**
- [ ] POST a batch → a Parquet object lands in `bronze/events/dt=.../event_name=.../`; Athena `count(*) > 0`.
- [ ] `catalog_export` and `ops_log_export` land daily snapshots in `bronze/catalog_export/` and `bronze/ops/`.
- [ ] `dbt build` succeeds and **all dbt tests pass** (`not_null`/`unique`/`accepted_values`/`relationships`/freshness/dedup).
- [ ] All **five dashboards render against `gold/`** (Dashboard 5 also against `bronze/ops/` + freshness) via `analytics-api`.
- [ ] `bp_token` appears in no envelope or log; a telemetry 401 that can't refresh **never logs the user out** (SDK test).
- [ ] Measured monthly cost **< $2** (under the $5 ceiling).

---

*Spec written to `/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/service_improve/docs/superpowers/specs/2026-06-27-clouder-analytics-pipeline-design.md`.*
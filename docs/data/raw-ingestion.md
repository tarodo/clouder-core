# Raw ingestion

The raw ingestion pipeline fetches weekly Beatport releases, writes them to S3, records an `ingest_run` row, and enqueues a canonicalization message.

All code lives in `src/collector/handler.py`. The shared entry point is `_run_beatport_ingest`.

---

## Entry points

Two API routes both delegate to `_run_beatport_ingest`:

| Route | Status | Notes |
|---|---|---|
| `POST /admin/beatport/ingest` | Current | Saturday-week based; admin-only |
| `POST /collect_bp_releases` | Deprecated | ISO-week based; kept for backward compatibility; admin-only |

**`POST /admin/beatport/ingest`** expects:

```json
{
  "bp_token": "<beatport session token>",
  "style_id": 1,
  "week_year": 2026,
  "week_number": 18,
  "period_start": null,
  "period_end": null
}
```

`period_start` / `period_end` are optional overrides. When omitted, the range is derived from `saturday_week_range(week_year, week_number)`. When provided, `is_custom_range=true` is recorded on the run.

**`POST /collect_bp_releases`** (deprecated) accepts `iso_year` + `iso_week` (ISO-8601 week numbering) and maps them to a date range via `compute_iso_week_date_range`. Do not add new callers; all new ingests must use the Saturday-week path.

Both routes require the caller to be an admin (enforced by `_require_admin` before dispatch, which checks the Lambda authorizer context for `is_admin=true`).

`bp_token` is a Beatport session token. It must never be logged or stored in S3. `_run_beatport_ingest` only records style/week metadata in `meta`, not the token itself.

---

## Saturday-week convention

Source: `src/collector/saturday_week.py`. See also ADR-0003.

- Week N of year Y starts on Saturday and ends on the following Friday (7-day window, inclusive).
- Week 1 begins on the first Saturday on or after January 1 of year Y.
- Days from January 1 up to (but excluding) that first Saturday belong to the last week of year Y−1.

Key functions:

| Function | Signature | Returns |
|---|---|---|
| `first_saturday` | `(year: int) -> date` | First Saturday of the year |
| `saturday_week_range` | `(year: int, week: int) -> tuple[date, date]` | `(start, end)` inclusive |
| `weeks_in_year` | `(year: int) -> int` | Number of weeks in that year (52 or 53) |
| `week_of_date` | `(d: date) -> tuple[int, int]` | `(year, week)` for any date |

The admin UI uses `week_year` / `week_number` (Saturday-week) exclusively. The legacy `iso_year` / `iso_week` on `ingest_runs` columns are nullable and null for all new runs.

---

## S3 raw layout

Beatport releases are written by `src/collector/storage.py:S3Storage.write_run_artifacts`.

```
s3://{RAW_BUCKET_NAME}/{raw_prefix}/
    style_id={style_id}/
        year={year}/
            week={week}/
                releases.json.gz   — gzip-compressed JSON array of track objects
                meta.json          — run metadata (no bp_token)
```

Default `raw_prefix` = `raw/bp/releases`. Overridable via `RAW_PREFIX` env var.

`releases.json.gz` is a list of Beatport API track objects as returned by the API. The worker (`src/collector/worker_handler.py`) reads this key to start canonicalization.

`meta.json` contains:
```json
{
  "style_id": 1,
  "week_year": 2026,
  "week_number": 18,
  "period_start": "2026-05-02",
  "period_end": "2026-05-08",
  "is_custom_range": false,
  "run_id": "...",
  "correlation_id": "...",
  "item_count": 234,
  "api_pages_fetched": 3,
  "duration_ms": 4200,
  "collected_at_utc": "2026-05-04T10:00:00Z"
}
```

Spotify results land under a separate prefix controlled by `SPOTIFY_RAW_PREFIX` (default `raw/sp/tracks`):
```
raw/sp/tracks/date={YYYY-MM-DD}/{correlation_id}/results.json.gz
raw/sp/tracks/date={YYYY-MM-DD}/{correlation_id}/meta.json
```

---

## ingest_runs state machine

`ingest_runs.status` tracks the lifecycle of each run.

```
              fetch OK + S3 write OK
[start] ──────────────────────────────► RAW_SAVED
                                             │
                    ┌────────────────────────┴──────────────────────┐
                    │ CANONICALIZATION_ENABLED=true                  │ disabled / missing queue URL
                    │ + queue send OK                                │
                    ▼                                                ▼
               QUEUED                                         FAILED_TO_QUEUE
                    │
       (worker picks up SQS message)
                    │
         ┌──────────┴──────────┐
         │ success             │ error
         ▼                     ▼
     COMPLETED              FAILED
```

Alongside `status`, the API response includes a quartet for the SQS enqueue step:

| Field | Type | Meaning |
|---|---|---|
| `processing_status` | `ProcessingStatus` | `QUEUED` or `FAILED_TO_QUEUE` |
| `processing_outcome` | `ProcessingOutcome` | `ENQUEUED`, `DISABLED`, or `ENQUEUE_FAILED` |
| `processing_reason` | `ProcessingReason` nullable | `config_disabled`, `queue_missing`, `enqueue_exception` |

These are returned in the HTTP response body and logged as `collection_completed`. The `ingest_runs` row itself is updated by the worker to `COMPLETED` or `FAILED` after canonicalization.

`GET /runs/{run_id}` returns the current `ingest_runs` row. It returns 503 `db_not_configured` if `AURORA_*` env vars are missing — this is expected in environments without Aurora.

---

## Operational notes

**`FAILED_TO_QUEUE`**: the S3 write and `ingest_runs` row creation succeeded; raw data is persisted. The SQS message was not sent (queue URL missing or SQS error). To retry canonicalization, send a `CanonicalizationMessage` manually to the SQS queue with the `s3_key` from the response.

**API Gateway 29 s timeout**: API GW has a hard 29-second timeout. Bulk ingests with many Beatport API pages can exceed this. The client receives `{"message":"Service Unavailable"}` (API GW format, not CLOUDER's error envelope), but the Lambda usually continues to completion in the background. Check `ingest_runs.status` after a few seconds. Aurora cold-start (when `aurora_serverless_min_acu=0`) can also push the first request past 29 s; see the Ops guide.

**`bp_token` lifecycle**: the token is held in memory only during the Lambda invocation. It is not written to S3, logs, or the database.

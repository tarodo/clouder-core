# Spotify Coverage Stats + Not-Found Retry — Design

Date: 2026-07-13
Status: approved

## Problem

The admin coverage matrix (`/admin/coverage`, styles × Saturday weeks) shows only
ingest-run status. It says nothing about how many of the ingested tracks were
actually matched on Spotify. Separately, tracks that a Spotify search failed to
find (`spotify_searched_at IS NOT NULL AND spotify_id IS NULL`) stay not-found
forever — there is no way to re-run the search for them (e.g. after a track
appears on Spotify later, or after matching logic improves).

## Goals

1. On hover over a coverage-matrix cell (style × week), show how many tracks
   released that week were found on Spotify and how many were not.
2. Let an admin re-run the Spotify search for not-found tracks whose Beatport
   release date (`clouder_tracks.publish_date`) falls in a chosen date range.

## Non-goals

- No per-run attribution of Spotify stats (stats are keyed by the track's
  `publish_date` Saturday week, not by which ingest run brought the track in).
- No new run-tracking/progress UI for the retry — it is fire-and-forget via the
  existing SQS worker; the not-found list itself shows the effect.
- No changes to the Spotify search worker or its matching cascade.
- No DB schema changes. No index on `publish_date` until a query is measurably
  slow.

## Part 1 — Spotify stats in the coverage matrix tooltip

### Backend

New repository method `ClouderRepository.spotify_stats_for_year(week_year)`:

- Year bounds come from `saturday_week` helpers:
  `year_start = first_saturday(week_year)`;
  `year_end = year_start + weeks_in_year(week_year) * 7 - 1` (the last Friday
  of the last week). Both passed as bound date params.
- One aggregate query over `clouder_tracks`, joined to `clouder_styles` and
  `identity_map` (same join as `coverage_for_year`) so rows are keyed by the
  Beatport style id the matrix uses:

```sql
SELECT
    im.external_id                       AS beatport_style_id,
    (t.publish_date - :year_start) / 7 + 1 AS week_number,
    COUNT(*)                             AS total,
    COUNT(*) FILTER (WHERE t.spotify_id IS NOT NULL)                    AS found,
    COUNT(*) FILTER (WHERE t.spotify_id IS NULL
                       AND t.spotify_searched_at IS NOT NULL)           AS not_found,
    COUNT(*) FILTER (WHERE t.isrc IS NOT NULL
                       AND t.spotify_searched_at IS NULL)               AS pending,
    COUNT(*) FILTER (WHERE t.isrc IS NULL)                              AS no_isrc
FROM clouder_tracks t
JOIN clouder_styles cs ON cs.id = t.style_id
JOIN identity_map im
  ON im.source = 'beatport'
 AND im.entity_type = 'style'
 AND im.clouder_entity_type = 'style'
 AND im.clouder_id = cs.id
WHERE t.publish_date BETWEEN :year_start AND :year_end
GROUP BY 1, 2
```

The four buckets are mutually exclusive and sum to `total`:
`found` / `not_found` (searched, no match) / `pending` (has ISRC, not searched
yet) / `no_isrc` (the worker never searches these — distinct from "not found").

`_handle_admin_coverage` calls the method and adds to each style entry:

```json
"spotify_weeks": [
  {"week_number": 27, "total": 50, "found": 45, "not_found": 3,
   "pending": 1, "no_isrc": 1}
]
```

Weeks with no tracks are omitted. `GET /admin/coverage` keeps its route,
params, and existing fields — the change is additive. Regenerate
`docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts` (CI diff-checks).

### Frontend

`CoverageMatrix` / `CoverageMatrixCell`: the cell tooltip becomes a multi-line
ReactNode. Existing run line stays; a second line is added when stats exist for
that style × week:

```
Wk 27 · 2026-07-04 – 2026-07-10 · 120 items
Spotify: 45/50 found · 3 not found · 1 pending · 1 no ISRC
```

`pending` and `no ISRC` segments render only when > 0. The stats line also
renders on cells without a run (empty cells) when tracks exist for that week.
The stats line is hard-coded English, matching the existing tooltip line
(which is not i18n-ized either); Part 2 UI copy goes through i18n.

### Semantics note

A track belongs to the Saturday week of its `publish_date`, regardless of which
ingest run (regular or custom-range) imported it. Tooltip numbers mean "tracks
of this style released this week", not "tracks fetched by this run".

## Part 2 — Retry Spotify search for not-found tracks

### Approach

Reset-and-reuse: reset `spotify_searched_at` for the selected tracks, then send
a regular message to the existing `spotify_search` SQS queue. The worker code
(`spotify_handler.py`) is untouched — it already picks up any track with
`isrc IS NOT NULL AND spotify_searched_at IS NULL`, runs the full ISRC cascade
+ metadata fallback, and drains the pool via `auto_continue` follow-ups.

Known side effect (acceptable, surfaced in the confirm dialog): retried tracks
temporarily leave the not-found list (they become "pending") and reappear only
if the new search also fails.

### New route `POST /admin/spotify/retry-not-found`

Registered in all three places: `_ADMIN_ROUTES` + dispatch in
`src/collector/handler.py`, `scripts/generate_openapi.py:ROUTES`, and the API
Gateway route in `infra/`.

Request body:

```json
{"publish_date_from": "2026-06-01", "publish_date_to": "2026-06-30"}
```

Validation (400 on failure): both dates required, ISO format, `from <= to`.

Handler logic:

1. Reset:

```sql
UPDATE clouder_tracks
SET spotify_searched_at = NULL, updated_at = :now
WHERE isrc IS NOT NULL
  AND spotify_id IS NULL
  AND spotify_searched_at IS NOT NULL
  AND publish_date BETWEEN :from AND :to
```

   The statement ends with `RETURNING id`; the affected-row count is the
   length of the returned row list (the `DataAPIClient.execute()` wrapper
   exposes rows only, not `numberOfRecordsUpdated`).

2. Enqueue `{"batch_size": 200, "auto_continue": true}` to
   `SPOTIFY_SEARCH_QUEUE_URL` when reset count > 0 **or** the range already
   contains pending tracks with ISRC (one cheap COUNT). The second condition
   makes the button idempotent: if a previous call reset rows but failed to
   enqueue, clicking again re-sends the message instead of silently doing
   nothing.

3. Respond `{"queued_count": N, "correlation_id": ...}`. When N = 0 and no
   pending tracks exist in range, no SQS message is sent.

Failure mode: if the SQS send fails after the reset, return 500 with a clear
message. Nothing is lost — the tracks sit in "pending" and are picked up by a
repeat click or by the next regular search message (enqueued after any ingest
canonicalization).

Infra: the API Lambda already has `SPOTIFY_SEARCH_QUEUE_URL`, and the shared
`collector_lambda` IAM role already grants `sqs:SendMessage` on the
`spotify_search` queue (`infra/iam.tf`, `AllowSQSSend`) — no IAM change
needed; only the new API Gateway route is added.

Logging: `spotify_retry_requested` / `spotify_retry_enqueued` /
`spotify_retry_enqueue_failed` events; any new field names must be in
`ALLOWED_LOG_FIELDS`.

### `GET /tracks/spotify-not-found` filter extension

Optional query params `publish_date_from` / `publish_date_to` (ISO dates,
validated the same way), threaded into
`find_tracks_not_found_on_spotify` / `count_tracks_not_found_on_spotify` as an
extra `AND t.publish_date BETWEEN :from AND :to` predicate. Existing `search`,
`limit`, `offset` behavior unchanged.

### Frontend — Spotify not-found page

On `AdminSpotifyNotFoundPage` / `SpotifyNotFoundTable`:

- `DatePickerInput type="range"` above the table filtering the list by
  `publish_date` — the admin first sees exactly which tracks (and how many)
  fall under the retry.
- **Retry search** button: enabled only when both range ends are set. Opens a
  confirm modal showing the current filtered `total` and the note about tracks
  temporarily leaving the list. On confirm: `POST /admin/spotify/retry-not-found`
  via a new `useRetrySpotifySearch` mutation hook → success toast
  "Queued N tracks" → invalidate the not-found list query and the coverage
  query. `queued_count = 0` → neutral toast "nothing to retry".
- New i18n keys in `en.json`.

## Testing

Backend (pytest, existing fake Data API client pattern):

- `spotify_stats_for_year`: SQL shape + year-bound params; bucket arithmetic
  via representative fake rows.
- Coverage handler: `spotify_weeks` merged per style; styles without tracks get
  an empty array.
- Retry handler: date validation (missing / bad format / from > to), reset +
  enqueue happy path, 0-tracks-no-enqueue, pending-in-range-still-enqueues,
  SQS failure → 500.
- Not-found list/count: date-range predicate and params.

Frontend (vitest + msw, no browser tests — no CSS/layout change):

- Tooltip content: with full stats, with zero-only optional buckets, without
  stats.
- Date-range filter wiring into the list query.
- Retry flow: button disabled without range → modal shows count → POST → toast
  → query invalidation.

Contract: regenerate `openapi.yaml` + `schema.d.ts`; frontend typecheck + lint
+ test before merge.

## Rollout

Single deploy: Lambda package + Terraform (new route, possible IAM statement) +
frontend. No migration, no backfill. Feature is admin-only.

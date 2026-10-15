# Track audio analysis API (AI detection first) — design

Date: 2026-10-15. Status: draft for owner review.

## Goal

An external worker, [clouder-analyzer](https://github.com/tarodo/clouder-analyzer) (private repo, runs on the owner's Windows PC), pulls batches of tracks that have a YouTube Music video, analyzes the audio and posts the results back. clouder-core stores the results and shows an **AI** badge on tracks whose audio the detector flags.

The first analyzer was `ai_detect` (ArtifactNet). Update 2026-10-16: the badge now comes from `ai_lofcz` ([lofcz/ai-music-detector](https://github.com/lofcz/ai-music-detector), MIT); `ai_detect` rows stay as a second opinion. The claim hands out every track missing `ai_lofcz`, so the switch re-analyzes the catalog with no data deletion. Embeddings come later, for "similar tracks" and for training an in-house classifier. This design must not block them, but it builds nothing for them now.

clouder-core knows the worker only through the contract below: which tracks to hand out, and what a result looks like. It knows nothing about the model, yt-dlp, the cache or the host.

### Non-goals

- Analysis, download and model code. These belong to the worker's own spec.
- Embedding storage and vector search. That will be a `track_embeddings` table with pgvector, in its own spec.
- Filters or sorting by the AI flag, tooltips, and a score shown in the UI. The owner wants to look at real results first.
- Automatic re-analysis when an analyzer's version changes. Re-analysis is admin-only (`requeue`).
- The old `clouder_tracks.is_ai_suspected`. It is dead and no longer returned by the API (#333). It is a separate signal from label enrichment and stays out of this design.

## Decisions (from the 2026-10-15 grilling)

| Topic | Decision |
|---|---|
| Exchange | The worker pulls work over HTTPS. It claims a batch with a lease and posts results. There are no inbound ports and no AWS keys on the PC. |
| Unit of work | One track. A claim returns the track's video plus every requested analyzer the track still lacks. The worker downloads once and runs them all. |
| Source | Only the `ytmusic` `vendor_track_map` row: the official Art Track, matched on duration and album. A track without one is not handed out. |
| Which tracks | Every track that has a `ytmusic` row. Those rows exist only for new tracks, curated tracks (YouTube sweep), playlist tracks and manually reviewed matches. The archive has none, so this is the sweep's set plus playlist tracks, with no extra filter. |
| Failure | `failed` is final: the track is never handed out again for that analyzer. Only `requeue` with `include_failed` brings it back. |
| Version change | It is recorded and does nothing on its own. `requeue` re-analyzes. |
| Storage | One generic table, `track_analyses`, keyed by `(track_id, analyzer)`. The analyzer type is a column. |
| Auth | An opaque service token `svc_…`. Its SHA-256 lives in SSM, and a separate authorizer guards only `/v1/analysis/*`. |
| Cadence | The worker claims about once a day, so Aurora wakes once a day. |
| UI | A plain **AI** badge next to the title in every track row and every player. All users see it. No tooltip, no filter. |
| Admin | An "AI analysis" card on Admin → Coverage and `POST /admin/analysis/requeue`. The requeue has no UI button. |

## Contract (`/v1/analysis/*`, service token only)

Every call sends `Authorization: Bearer svc_<43 base64url chars>`.

- **401:** the token is missing, wrong or not a service token. A user JWT gets 401 here, and a service token gets 401 on every other route.
- **400:** a validation error. The body is `{"error_code": "validation_error", "message": "...", "correlation_id": "..."}`, the API's usual error envelope.
- **503 or timeout:** Aurora is resuming (ADR-0014). The worker retries with backoff for up to about 2 minutes. This is part of the contract.

### `POST /v1/analysis/claim`

Request:

```json
{ "limit": 20, "analyzers": ["ai_detect"] }
```

- `limit`: 1–50, default 20.
- `analyzers`: 1–8 distinct names, each matching `^[a-z][a-z0-9_]{1,31}$`.

Response `200`:

```json
{
  "lease_id": "6f1c…-uuid",
  "lease_expires_at": "2026-10-16T03:31:00.000000+00:00",
  "tracks": [
    { "track_id": "uuid", "video_id": "dQw4w9WgXcQ", "length_ms": 312000, "analyzers": ["ai_detect"] }
  ]
}
```

- **Empty `tracks`:** there is no work.
- **`length_ms`:** the catalog length, or null. The worker uses it to catch truncated downloads.
- **`analyzers`:** for each track, the subset of the requested names it lacks.
- **Which analyzers a track lacks:** an analyzer is missing when the track has no `track_analyses` row for it, or only a `leased` row whose lease has expired.
- **Lease:** the lease lasts 30 minutes. A track whose lease expires without a result goes back to the pool.
- **Order:** newest tracks first (`clouder_tracks.created_at DESC`).
- **Heartbeat:** each claim, empty or not, stamps the worker's `last_claim_at` and the analyzer names it asked for.

### `POST /v1/analysis/results`

Request: 1–100 items.

```json
{
  "lease_id": "6f1c…-uuid",
  "results": [
    {
      "track_id": "uuid",
      "analyzer": "ai_detect",
      "version": "artifactnet-9.4/rms0.1/median/0.225",
      "status": "ok",
      "result": { "ai_detected": true, "score": 0.71 },
      "error": null,
      "audio_sha256": "64 hex",
      "video_id": "dQw4w9WgXcQ"
    }
  ]
}
```

**Fields:**
- `status` is one of:
  - `ok` — analyzed;
  - `failed` — the download or the analysis failed for good: the video was removed, is region-locked or age-gated;
  - `unusable_source` — the audio cannot carry a verdict, for example a wrong format or no usable segments.
- `version`: 1–64 printable characters.
- `error`: ≤ 500 characters, required unless `status` is `ok`.
- `result`: required when `status` is `ok`, otherwise null. Its JSON is ≤ 32 KB.
- `audio_sha256`: 64 lowercase hex characters, or null.
- `video_id`: ≤ 32 characters, or null.

**Result shape for an AI analyzer (`ai_detect`, `ai_lofcz`) with `ok`:** `ai_detected` (bool) and `score` (a number from 0 to 1) are required. Any other keys, such as segment scores, threshold or model, are stored as they are and never read by clouder-core. Other analyzers' result shapes are opaque to clouder-core until a feature reads them.

**Lease check:** an item is accepted only while its row is still `leased` under this `lease_id`. A late result is accepted if nobody re-leased the track. A track that was re-leased is rejected with `lease_lost`.

Response `200`:

```json
{ "accepted": 19, "rejected": [ { "track_id": "uuid", "analyzer": "ai_detect", "reason": "lease_lost" } ] }
```

Validation errors fail the whole request with 400, so a bad worker build is loud. `lease_lost` is per item.

## Data model (migration 38)

```sql
CREATE TABLE track_analyses (
    track_id      varchar(36) NOT NULL REFERENCES clouder_tracks(id) ON DELETE CASCADE,
    analyzer      varchar(32) NOT NULL,
    status        varchar(16) NOT NULL,      -- leased | ok | failed | unusable_source
    version       varchar(64),               -- null while leased
    result        jsonb,
    error         varchar(500),
    audio_sha256  char(64),
    video_id      varchar(32),
    lease_id      uuid,
    leased_until  timestamptz,
    analyzed_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (track_id, analyzer),
    CHECK (status IN ('leased', 'ok', 'failed', 'unusable_source'))
);
-- The badge lookup: ok AI-flagged tracks (migration 39 moved it from ai_detect to ai_lofcz).
CREATE INDEX ix_track_analyses_ai_lofcz_detected ON track_analyses (track_id)
    WHERE analyzer = 'ai_lofcz' AND status = 'ok' AND (result->>'ai_detected')::boolean;

CREATE TABLE analysis_service_state (
    service           varchar(32) PRIMARY KEY,   -- 'analyzer'
    last_claim_at     timestamptz,
    last_result_at    timestamptz,
    claim_analyzers   text[] NOT NULL DEFAULT '{}'
);
```

**Claim, in one statement (Data API, no transaction):**
- Candidates are the `vendor_track_map` rows with `vendor = 'ytmusic'`, ordered by `clouder_tracks.created_at DESC`, that lack at least one requested analyzer.
- The statement inserts `(track, analyzer)` as `leased` with this `lease_id` and `leased_until`.
- On conflict it updates the row only `WHERE status = 'leased' AND leased_until < now()`.
- `RETURNING` reports what was actually leased. Two concurrent claimers therefore never lease the same pair.
- The candidate pick is a `MATERIALIZED` CTE with `LIMIT :limit` (see the YouTube sweep note on `IN (... LIMIT)` re-execution).

**Results:** `UPDATE … SET status, version, result, error, audio_sha256, video_id, analyzed_at = now(), lease_id = NULL, leased_until = NULL WHERE track_id, analyzer, status = 'leased', lease_id = :lease_id`. The affected row count tells accepted from `lease_lost`.

A later `ytmusic` re-match to another video does not invalidate a result. `video_id` in the row shows what was analyzed, and `requeue` redoes it.

## Admin

### `GET /admin/analysis/status` (admin JWT)

```json
{
  "last_claim_at": "…", "last_result_at": "…",
  "analyzers": [
    { "name": "ai_detect", "due": 120, "leased": 0, "ok": 3400, "ai_detected": 41,
      "failed": 12, "unusable_source": 3 }
  ]
}
```

- The `analyzers` list covers `claim_analyzers` plus every name present in the table.
- `due`: tracks with a `ytmusic` row and no row for that analyzer, plus expired leases.
- `ai_detected`: counted only for the AI analyzers (`ai_detect`, `ai_lofcz`).

### `POST /admin/analysis/requeue` (admin JWT)

```json
{ "analyzer": "ai_detect", "scope": "all", "days": null, "include_failed": false }
```

- `scope` is `all`, `categories` (tracks in a live category) or `recent` (tracks created in the last `days`, 1–365).
- The call deletes the matching rows that are `ok` or `unusable_source`, plus `failed` ones when `include_failed` is set. Live leases are never deleted.
- Response: `{ "requeued": n }`. The next claim picks those tracks up.

### Card

"AI analysis" sits on Admin → Coverage, below "YouTube search", in the same style. It shows:
- last claim and last result as relative times; it turns into a warning after 3 days without a claim, meaning the PC has not run;
- `due`, `ok`, `ai_detected`, `failed`, `unusable_source` per analyzer.

The card polls every 30 seconds, but only while the tab is visible. It must not keep Aurora awake (#322's lesson).

## Tracks in the product

- **API.** `GET /categories/{id}/tracks`, `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` (which Curate uses) and `GET /playlists/{id}/tracks` return `"ai_detected": boolean`. It comes from an `EXISTS` over `track_analyses` using the partial index. A track that has not been analyzed, or failed, is `false`.
- **Frontend.** One `AiBadge` component renders a small "AI" Mantine badge next to the title:
  - in the category, bucket and playlist track rows;
  - on the Curate card;
  - in the category, bucket and playlist player panels.

  `ai_detected` is carried into the playback track model so players get it.
- **Demo.** Mark a few demo tracks `ai_detected: true`.

## Service auth

- **Token.** `svc_` plus 32 random bytes in base64url. Only its SHA-256 is stored, in the SSM SecureString `/clouder/auth/analysis_service_token_sha256`.
  - Terraform does not create the parameter: like the JWT key (ADR-0028), it stays out of Terraform state, and the pull-request role is already denied `/clouder/auth/*`. A missing parameter means every service call gets 401.
  - The owner sets the real hash. Creating and rotating the token are owner steps: the token never passes through the agent or CI.
- **Authorizer resource.** A second authorizer, `analysis_service` (REQUEST, simple responses, identity source `Authorization`, cached), sits on the two `/v1/analysis/*` routes only.
  - It reuses the `auth_authorizer` Lambda.
  - It needs its own resource because API Gateway caches an authorizer's verdict by the header across all of that authorizer's routes. A shared authorizer would let a cached service-token allow reach user routes.
- **Lambda.** It branches on `routeKey`:
  - on a `/v1/analysis/` route it accepts only a `svc_` token whose SHA-256 matches, compared with `hmac.compare_digest`. The hash is cached with a TTL like the JWT key. The context is `{"service": "analyzer"}`;
  - on every other route nothing changes. A `svc_` token is not a JWT and fails verification.
  - Neither the token nor its hash is ever logged.
- **Defense in depth.** The `/v1/analysis/*` handlers require `service == "analyzer"` in the authorizer context. Every other route already requires `user_id`.
- **IAM.** The authorizer role gets `ssm:GetParameter` on that one parameter.

## Rollout

1. Migration 38, repository, routes, authorizer branch, infra, admin card, `ai_detected` in the three lists, and the badge, all in one PR. It deploys inert: there is no token hash yet, so every service call is 401, the card shows "never", and no badges appear.
2. **Owner step:** generate the token on the PC and put its hash into SSM (exact commands go in the plan).
3. The worker (separate spec) runs a small batch. Check the card, then the badges.

## Testing

- **Postgres tests** (`tests/db`, real PG):
  - claim leases only tracks with a `ytmusic` row, newest first, respecting `limit`;
  - a second claim gets nothing while the lease is live, and takes the track again after expiry;
  - partial analyzers: a track with `ai_detect` ok is claimed only for `embed`;
  - `failed` is never re-claimed;
  - results accept the leased row and reject `lease_lost` after a re-lease;
  - requeue scopes and `include_failed`; status counts;
  - the `ai_detected` EXISTS in the three list queries.
- **Unit:**
  - authorizer: a service token on an analysis route is allowed; a JWT on an analysis route is denied; a service token on a user route is denied; a wrong hash is denied; nothing is logged;
  - request validation (each field limit);
  - the `ai_detect` result shape.
- **Integration:** both service routes end to end through `handler.py` with an authorizer context, and both admin routes. Guard tests: README counts, OpenAPI regenerated, alarm routing, repository layout.
- **Frontend:** badge shown or hidden per row type and in players, the admin card states, the demo handler.

## Open risks

- **Detector quality.** Recall is 56% overall and 27–40% on modern Suno, so "no badge" does not mean the track is human-made. The owner reviews real results before adding filters.
- **Coverage.** Only tracks with a `ytmusic` match get a verdict. Tracks without one never show the badge.

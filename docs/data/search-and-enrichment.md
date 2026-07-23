# Search and enrichment

After canonicalization, two asynchronous workers enrich canonical tracks and labels with data from Spotify and Perplexity. A third worker (`vendor_match_handler`) maintains a per-vendor match cache.

---

## Spotify ISRC lookup

**Worker**: `clouder-prod-spotify-search-worker` Lambda, triggered by SQS message.
**Source**: `src/collector/spotify_handler.py`, `src/collector/spotify_client.py`.

The worker selects tracks that have an ISRC but no `spotify_searched_at`:

```sql
SELECT id, isrc, title, artists, length_ms
FROM clouder_tracks
WHERE isrc IS NOT NULL
  AND spotify_searched_at IS NULL
ORDER BY created_at DESC
LIMIT :batch_size
```

(`artists` is projected via a JOIN on `clouder_track_artists`/`clouder_artists`; `length_ms` is needed for the metadata fallback.)

For each track, it calls `GET https://api.spotify.com/v1/search?q=isrc:{ISRC}&type=track&limit=10`. When multiple results are returned, the one with the earliest `album.release_date` wins.

**Authentication**: Client Credentials flow. Token cached per Lambda instance; refreshed 60 s before expiry or on 401. Credential resolution precedence:
1. `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` (direct env)
2. `SPOTIFY_CLIENT_ID_SSM_PARAMETER` + `SPOTIFY_CLIENT_SECRET_SSM_PARAMETER` (both must be set)
3. `SPOTIFY_CREDENTIALS_SECRET_ARN` (Secrets Manager JSON `{client_id, client_secret}`)

**Retry**: transient codes `{408, 429, 500, 502, 503, 504}` → exponential backoff (base 0.5 s, max 4 retries). On `429`, respects `Retry-After` header capped at 120 s. Permanent errors skip the track.

**After search** (for all tracks — found and not found):
- `clouder_tracks.spotify_searched_at` is set to now.
- On hit: `clouder_tracks.spotify_id` is set; `source_entities(source='spotify')` + `identity_map(match_type='isrc_match', confidence=1.000)` are upserted; `release_type` and `spotify_release_date` are written.
- Results are also written to S3 under `raw/sp/tracks/date={YYYY-MM-DD}/{correlation_id}/`.

**Track states after search**:

| `spotify_searched_at` | `spotify_id` | Meaning |
|---|---|---|
| NULL | NULL | Not yet searched |
| NOT NULL | NOT NULL | Found |
| NOT NULL | NULL | Searched, not found |

**Follow-up chaining**: after each batch, if unsearched tracks remain and `auto_continue=true` in the SQS message, the worker enqueues another `SpotifySearchMessage`. This handles backlogs without a scheduler. Maximum follow-up batch size: 200 (rate-limit headroom).

---

## Metadata fallback

When an ISRC lookup returns 0 items and `SPOTIFY_METADATA_FALLBACK_ENABLED=true`, the worker runs two additional stages. See ADR-0006.

**Stage 1 — sibling ISRC neighbour matching** (see next section).

**Stage 2 — text search**: `GET /v1/search?q=track:{title} artist:{first_artist}&type=track&limit=10`.

The query uses only the first artist (split on `,` or `&`, country suffix like `(UK)` stripped). Spotify's `artist:` operator does literal substring matching; passing the full BP-shaped multi-artist string returns 0 results.

Both title and candidate name are normalized via `_normalize_title_for_match` before scoring. Normalization strips:
- `feat. X` / `ft. X` / `featuring X` (in brackets or bare)
- `(... Mix)` / `[... Mix]` variants: Remix, Radio Edit, Extended Mix, Original Mix, etc.

Scoring uses `string_sim` (Levenshtein-based ratio) and `best_artist_sim` (best match across a candidate's artist list). Each candidate is classified into a tier:

| Tier | Gate |
|---|---|
| **strict** | `title_sim >= SPOTIFY_FUZZY_TITLE_MIN` AND `artist_sim >= SPOTIFY_FUZZY_ARTIST_MIN` AND `\|dur_diff\| <= SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` (or either duration unknown) |
| **relaxed** | Passes title + artist min, fails duration, but `title_sim >= 0.95` AND `artist_sim >= 0.95` — near-perfect text match indicates same track in a different master/edit |
| **fail** | Below min thresholds, or fails duration without near-perfect text backup |

Strict candidates win over relaxed when both exist. On reject, `spotify_metadata_fallback_scores` is logged with the best `title_sim` / `artist_sim` observed, useful for tuning thresholds.

**Default thresholds** (configurable via env vars on `clouder-prod-spotify-search-worker`):

| Env var | Default | Meaning |
|---|---|---|
| `SPOTIFY_METADATA_FALLBACK_ENABLED` | `false` | Enable the fallback |
| `SPOTIFY_FUZZY_TITLE_MIN` | `0.90` | Minimum title similarity |
| `SPOTIFY_FUZZY_ARTIST_MIN` | `0.85` | Minimum artist similarity |
| `SPOTIFY_FUZZY_DURATION_TOLERANCE_MS` | `3000` | Duration match window |

**Log events**:

| Event | Meaning |
|---|---|
| `spotify_metadata_fallback_attempted` | Stage 2 started |
| `spotify_metadata_fallback_match` | Strict tier accepted |
| `spotify_metadata_fallback_match_relaxed` | Relaxed tier accepted |
| `spotify_metadata_fallback_rejected` | All candidates failed |
| `spotify_metadata_fallback_scores` | Best scores on reject (tuning aid) |

---

## Sibling ISRC neighbour matching

Source: `src/collector/spotify_client.py:_search_by_isrc_neighbours` and `_isrc_neighbours`.

When a primary ISRC lookup returns nothing, this stage (part of the metadata fallback, stage 1) tries ISRCs that differ from the query in the last digit only: `+1, -1, +2, -2` (closest-first). Out-of-range values (e.g. last digit = 9, delta = +2 → 11) are skipped to avoid carrying into the preceding digit.

Each sibling candidate is verified against `title_sim >= SPOTIFY_FUZZY_TITLE_MIN` and `artist_sim >= SPOTIFY_FUZZY_ARTIST_MIN`. Duration is not checked because radio edits and extended versions of the same track can differ significantly in length but are legitimately the same recording family.

The pattern addresses a common Beatport data quality issue: Beatport sometimes emits ISRCs that are off-by-one from Spotify's master.

Log event on hit: `spotify_isrc_neighbour_match` (includes `isrc`, `spotify_isrc` of the hit, `clouder_track_id`).

---

## Perplexity label and artist screening (superseded)

> **Superseded.** Neither the `ai-search-worker` Lambda nor `src/collector/search_handler.py` exists any more. Label and artist screening now run through the enrichment subsystems — see [ADR-0016](../adr/0016-label-enrichment.md) and [ADR-0017](../adr/0017-artist-enrichment.md), served by the `clouder-prod-label-enricher-worker` and `clouder-prod-artist-enricher-worker` Lambdas. The rest of this section is retained for the `ai_search_results` schema and history, and needs a refresh pass.

The worker receives `EntitySearchMessage` (entity type + entity ID + prompt slug + version), queries Perplexity, and saves the structured result to `ai_search_results`. It then calls `propagate_ai_flag` to update `is_ai_suspected` on the canonical entity.

`ai_search_results` schema:

| Column | Type | Notes |
|---|---|---|
| id | String(36) PK | UUID |
| entity_type | String(32) | `label`, `artist` |
| entity_id | String(36) | UUID of canonical entity |
| prompt_slug | String(64) | e.g. `label_info` |
| prompt_version | String(16) | e.g. `v1` |
| result | JSONB | Full `LabelSearchResult` as JSON |
| searched_at | TIMESTAMPTZ | |

Unique index: `(entity_type, entity_id, prompt_slug, prompt_version)`. Re-searching overwrites on conflict.

`result` is JSONB, not flat columns. To query inner fields:

```sql
-- Labels suspected of AI content with confidence
SELECT
    cl.id,
    cl.name,
    asr.result->>'ai_content'         AS ai_content,
    (asr.result->>'confidence')::float AS confidence
FROM ai_search_results asr
JOIN clouder_labels cl ON cl.id = asr.entity_id
WHERE asr.entity_type = 'label'
  AND asr.result->>'ai_content' IN ('suspected', 'confirmed')
ORDER BY confidence DESC
LIMIT 20;
```

**Propagation rules** (ADR-0008):

| `ai_content` | `confidence >= threshold` | Effect on `is_ai_suspected` |
|---|---|---|
| `suspected` or `confirmed` | yes | Set `TRUE` |
| `none_detected` | yes | Set `FALSE` (explicit clear) |
| `unknown` | any | No-op |
| any | no | No-op |

Default threshold: `0.6` (`AI_FLAG_CONFIDENCE_THRESHOLD` env var).

Credential resolution for Perplexity:
1. `PERPLEXITY_API_KEY` (direct)
2. `PERPLEXITY_API_KEY_SSM_PARAMETER` (SSM SecureString name)
3. `PERPLEXITY_API_KEY_SECRET_ARN` (Secrets Manager)

Secrets are `lru_cache`-cached per container. Rotated keys require a Lambda recycle.

**Known gap**: `GET /labels` does not project `is_ai_suspected`. Query Aurora directly to verify the flag.

---

## Vendor match cache

**Worker**: `clouder-prod-vendor-match-worker` Lambda, SQS-triggered.
**Source**: `src/collector/vendor_match_handler.py`.

Jobs are enqueued by the curation handler (playlist track-add, Spotify single-track import, Spotify whole-playlist import) and by one-off backfill scripts. A track with no artist rows is dropped before SQS — see [backend/gotchas.md](../backend/gotchas.md#empty-artist-silently-skips-vendor-match).

`vendor_track_map` — PK `(clouder_track_id, vendor)` — caches one match per track per vendor.

| Column | Notes |
|---|---|
| clouder_track_id FK → clouder_tracks | |
| vendor | e.g. `spotify` |
| vendor_track_id | String(128); Spotify track ID |
| match_type | `isrc`, `fuzzy`, `manual` |
| confidence | Numeric(4,3) |
| matched_at | TIMESTAMPTZ |
| payload | JSONB; full vendor track object |

**Upsert semantics**: `ON CONFLICT (clouder_track_id, vendor) DO UPDATE`. Re-processing the same track is idempotent. A higher-confidence subsequent match (e.g. a manual override) replaces the prior row.

**Low-confidence routing**: matches below `FUZZY_MATCH_THRESHOLD` (default `0.92`) are not written to `vendor_track_map`. Instead, the candidate set is sent to `match_review_queue` for manual approval.

`match_review_queue` has a partial unique index:

```sql
CREATE UNIQUE INDEX uq_review_pending
    ON match_review_queue (clouder_track_id, vendor)
    WHERE status = 'pending';
```

This prevents duplicate pending entries when the worker retries the same track. Repeated SQS deliveries are safe.

`status` values: `pending`, `approved`, `rejected`.

**Duration tolerance** for fuzzy scoring: `FUZZY_DURATION_TOLERANCE_MS` (default `3000` ms) — the window within which `duration_ms` must match for the `duration_ok` scoring component.

---

## Result schema

`ai_search_results.result` stores the full `LabelSearchResult` Pydantic model as JSONB.

Key inner fields (source: `src/collector/search/schemas.py`):

| Field | Type | Values |
|---|---|---|
| `ai_content` | string | `unknown`, `none_detected`, `suspected`, `confirmed` |
| `confidence` | float 0..1 | Model's self-assessed accuracy |
| `label_name` | string | |
| `size` | string | `micro`, `small`, `medium`, `large`, `major`, `unknown` |
| `age` | string | `new`, `young`, `established`, `veteran`, `unknown` |
| `founded_year` | int or null | |
| `sources` | array of strings | URLs used |

Example query — all labels where AI content was confirmed or suspected with high confidence:

```sql
SELECT
    cl.name,
    asr.result->>'ai_content'          AS ai_content,
    asr.result->>'ai_content_details'  AS details,
    (asr.result->>'confidence')::float AS confidence,
    asr.searched_at
FROM ai_search_results asr
JOIN clouder_labels cl ON cl.id = asr.entity_id
WHERE asr.entity_type = 'label'
  AND asr.prompt_slug = 'label_info'
  AND asr.result->>'ai_content' IN ('suspected', 'confirmed')
  AND (asr.result->>'confidence')::float >= 0.6
ORDER BY asr.searched_at DESC;
```

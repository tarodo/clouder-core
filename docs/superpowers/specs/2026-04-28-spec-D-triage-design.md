# spec-D — Triage (Layer 2 + promotion)

**Date:** 2026-04-28
**Status:** brainstorm stage
**Author:** @tarodo (via brainstorming session)
**Parent:** [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md) — this spec implements §4.5 R1–R8 and resolves the §7.6 mini-questions tagged "Decide in spec-D".
**Predecessors:**

- [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md) — provides JWT Lambda Authorizer and `users` table. Already merged.
- [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md) — provides `categories`, `category_tracks`, `categories_repository.add_tracks_bulk(...)` (the finalize-promotion contract), and the `curation_handler.py` Lambda this spec extends. Already merged.

**Successor blockers:** spec-G (Frontend) consumes the API surface defined here. spec-E (Release Playlists) does not depend on spec-D directly, but tracks added to release playlists in real-world flows will typically come from categories populated through triage.

## 1. Context and Goal

After spec-C, a user can manage permanent per-style **categories** and add tracks to them directly. spec-D adds the **triage layer**: a working session for sorting newly-ingested releases of a given style within a chosen date range. Triage is the natural source of truth for category membership in the everyday DJ workflow — the user creates a triage for "this week's releases", auto-classifies tracks into technical buckets (NEW / OLD / NOT / DISCARD / UNCLASSIFIED), drags tracks into staging buckets that mirror their existing categories, and on `finalize` the staging contents are promoted into `category_tracks`.

Triage and categories live **only in Aurora**. No Spotify playlists are created or written for these layers — the user listens via the frontend's Web Playback SDK. This is a deliberate simplification of the old code, where every triage created a Spotify playlist.

After this spec ships:

- A logged-in user can create a triage block for a `(style_id, date_from, date_to)` tuple. The backend auto-classifies all eligible tracks into the five technical buckets at create time.
- The user can move tracks between buckets within the active triage, transfer tracks across triage blocks, and finalize the triage to promote staging contents into permanent categories.
- Categories created or soft-deleted during an active triage are reflected in that triage's staging buckets eagerly (snapshot side-effect).
- Spotify enrichment is patched to populate a new `clouder_tracks.spotify_release_date` column, which drives the auto-classification.

## 2. Scope

**In scope:**

- New tables: `triage_blocks`, `triage_buckets`, `triage_bucket_tracks`.
- New column on existing table: `clouder_tracks.spotify_release_date Date NULL`, plus a partial index.
- Deferred FK from spec-C: `category_tracks.source_triage_block_id → triage_blocks.id ON DELETE SET NULL`.
- Patch to Spotify enrichment (`spotify_handler.py` + `repositories.py`) to record `album.release_date` per `release_date_precision`.
- 9 HTTP routes added to the existing `curation_handler.py` Lambda.
- New modules under `collector/curation/`: `triage_repository.py`, `triage_service.py`. `schemas.py` is extended.
- Patch to `categories_service.create` and `categories_service.soft_delete` for the eager-snapshot side-effect (D7) and inactive-staging mark (D8).
- Alembic migration `20260428_15_triage.py`.
- Terraform additions: 9 new API Gateway routes on the existing `aws_apigatewayv2_integration.curation`. No new Lambda function.
- Unit + integration tests covering classification, tenancy, idempotency, finalize transaction, transfer/move, snapshot side-effects.

**Out of scope:**

- Frontend code — spec-G.
- Release playlists (P1–P7) — spec-E.
- Hard-purge cron for soft-deleted triages — `FUTURE-D1`.
- Restore endpoint for soft-deleted triages — `FUTURE-D5`.
- Re-classification of an already-created triage block — `FUTURE-D2`.
- Async-finalize via Step Functions for very large promotions — `FUTURE-D3`.
- Backfill of `spotify_release_date` for historical tracks — handled by an operational script (`scripts/backfill_spotify_release_date.py`) outside this spec.
- Changing a triage's `style_id` post-create.
- Bulk-create of multiple triage blocks in one HTTP call.
- ETag / optimistic concurrency on triage blocks.
- Pagination/sort parameters on the bucket-track listing endpoint — fixed `added_at DESC, track_id ASC` for now (`FUTURE-D6`).

## 3. Architectural Decisions

| # | Decision | Rationale |
|---|----------|-----------|
| D1 | State machine `IN_PROGRESS → FINALIZED` (one directed transition via `finalize`). Soft-delete is an orthogonal `deleted_at` column, allowed in any status. No hard-delete API. | Minimal state. Finalized is read-only — no re-open, no CANCELLED status. |
| D2 | Block name is required (`name`, 1–128 chars), no UNIQUE constraint. | DJs name freely (`"Tech House W17 v2"`). Collisions are harmless. |
| D3 | Overlapping `[date_from, date_to]` windows allowed for the same `(user_id, style_id, IN_PROGRESS)`. No EXCLUSION constraint. | Users may explore alternative slices of the same week. The source-track query filters out tracks already in their categories, and `add_tracks_bulk` is idempotent — no double-promotion risk. |
| D4 | Source query for R1: `clouder_tracks.style_id = :style_id AND publish_date BETWEEN :df AND :dt AND NOT EXISTS (in user's alive categories for this style)`. | NULL `style_id` / NULL `publish_date` are excluded naturally. Already-categorized tracks are filtered out — re-triaging them adds no value. |
| D5 | R4 classification uses `clouder_tracks.spotify_release_date` (a new column populated by Spotify enrichment), not cross-ISRC comparison against `clouder_tracks`. | Beatport `publish_date` is "when it appeared in our pipeline"; Spotify `album.release_date` is "when the audio was originally released" — the global truth needed for re-release detection. One-pass query, no self-join. Trade-off: Spotify sometimes resets the release date when re-issuing audio under a new album, so a small fraction of re-releases may misclassify as NEW. Acceptable for the DJ use case. |
| D6 | Five technical bucket types: `NEW, OLD, NOT, DISCARD, UNCLASSIFIED`. Plus N staging buckets (one per alive category in the style). `bucket_type` stored on the bucket row; staging buckets carry a non-null `category_id`. | UNCLASSIFIED holds tracks where `spotify_release_date` is missing — they cannot be classified yet but should not be hidden. |
| D7 | **Eager snapshot of late-added categories.** `categories_service.create` (spec-C) is patched to call `triage_repository.snapshot_category_into_active_blocks(user_id, style_id, category_id)` inside the same TX. Idempotent via UPSERT on `(triage_block_id, category_id)`. | The user expects the new category to appear as a staging bucket in any active triage immediately. Eager + same-TX is deterministic; no write-on-read or async events needed. spec-C "does not emit events" is preserved — this is a direct module call, not an event. |
| D8 | Soft-deleting a category marks its staging buckets in active triages with `triage_buckets.inactive = true`. Tracks inside are not deleted. | The bucket and its tracks remain visible (marked inactive in UI) and block finalize until the user resolves them (D12). |
| D9 | `POST /triage/blocks/{id}/move` — batch within a single block. Body `{from_bucket_id, to_bucket_id, track_ids}`. Cap 1000. Any source/target bucket pair allowed except into `inactive` staging. Real move (DELETE+INSERT) in one TX. | Drag-and-drop UX; staging↔technical reclassification while user changes their mind. |
| D10 | `POST /triage/blocks/{src_id}/transfer` — cross-block snapshot. Body `{target_bucket_id, track_ids}`. Cap 1000. Source not mutated. Target must belong to an `IN_PROGRESS` block of the same `(user_id, style_id)` and not be `inactive`. User picks the target bucket explicitly. | Replaces the original R8 spillover. More flexible — user transfers any subset to any non-inactive bucket of any active triage of the same style. Preserves the source as a historical record. |
| D11 | Finalize promotes **only staging** buckets to `category_tracks`. NEW / OLD / NOT / DISCARD / UNCLASSIFIED stay as a read-only historical record after the block flips to FINALIZED. | The user's authored decisions live in staging; the technical buckets are the audit trail. |
| D12 | Finalize when an `inactive` staging bucket has tracks → 409 `inactive_buckets_have_tracks`, listing the offending buckets. The user must move the tracks out (or transfer them elsewhere) before finalize succeeds. | The category was the user's own creation; their tracks in it are valuable. We never silently drop them. |
| D13 | Finalize runs in one TX. For each active staging bucket, it calls `categories_repository.add_tracks_bulk(user_id, category_id, items, transaction_id=tx)` (spec-C contract D17). Caller chunks `items` at 500 entries per call; staging buckets above 500 tracks produce multiple `add_tracks_bulk` calls inside the same TX. | One TX = atomic. Chunking respects the Aurora Data API parameter limits. Staging buckets above ~5000 tracks may need async-finalize (`FUTURE-D3`). |
| D14 | R4 is fixed at create time. Move and transfer do **not** re-run R4 — `bucket_type` is a stable attribute set once. | Stable, predictable UX. Reclassification mid-session would surprise users and complicate idempotency. |
| D15 | The deferred FK `category_tracks.source_triage_block_id → triage_blocks.id ON DELETE SET NULL` is added in this spec's migration. | spec-C intentionally omitted this FK to ship without forward references (spec-C D16). |
| D16 | spec-D extends the existing `curation_handler.py` Lambda; it does not create a new Lambda. | Same auth shape, same env vars, same IAM. New routes attach to the existing API Gateway integration. |
| D17 | New modules under `collector/curation/`: `triage_repository.py`, `triage_service.py`. `schemas.py` is extended. | Per-spec module isolation, matching spec-C D9. |
| D18 | Spotify enrichment (`spotify_handler.py` + `repositories.py`) is patched to extract `album.release_date` and `album.release_date_precision`, parse per precision (`day` → exact, `month` → first of month, `year` → first of year), and persist into `clouder_tracks.spotify_release_date` via `COALESCE`. | Required by D5. Minimal patch to existing enrichment code — no new env vars, no IAM changes. |
| D19 | Tenancy enforced at the repository layer. Every method accepts `user_id` and includes it in `WHERE`. Cross-user access produces 0 rows → 404 (does not leak existence). | Defense-in-depth. Matches spec-C D15. |
| D20 | All 9 routes JWT-gated via the existing Lambda Authorizer from spec-A. No admin routes; no public routes. | Triage is per-user state. |

## 4. Data Model

### 4.1 `triage_blocks`

| Column | Type | Constraints |
|---|---|---|
| id | String(36) | PK (UUID) |
| user_id | String(36) | NOT NULL, FK → `users.id` |
| style_id | String(36) | NOT NULL, FK → `clouder_styles.id` |
| name | Text | NOT NULL |
| date_from | Date | NOT NULL |
| date_to | Date | NOT NULL, CHECK `date_to >= date_from` |
| status | String(16) | NOT NULL, CHECK `status IN ('IN_PROGRESS','FINALIZED')`, default `'IN_PROGRESS'` |
| created_at | DateTime(tz) | NOT NULL |
| updated_at | DateTime(tz) | NOT NULL |
| finalized_at | DateTime(tz) | nullable; set on transition to FINALIZED |
| deleted_at | DateTime(tz) | nullable |

**Indexes:**

- `idx_triage_blocks_user_style_status` `(user_id, style_id, status)` `WHERE deleted_at IS NULL` — frequent filter (active blocks for snapshot, list-by-style).
- `idx_triage_blocks_user_created` `(user_id, created_at DESC)` `WHERE deleted_at IS NULL` — cross-style list sort.

No UNIQUE constraint on name. Overlapping windows allowed (D3).

### 4.2 `triage_buckets`

| Column | Type | Constraints |
|---|---|---|
| id | String(36) | PK (UUID) |
| triage_block_id | String(36) | NOT NULL, FK → `triage_blocks.id` ON DELETE CASCADE |
| bucket_type | String(16) | NOT NULL, CHECK `bucket_type IN ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING')` |
| category_id | String(36) | nullable, FK → `categories.id` ON DELETE RESTRICT |
| inactive | Boolean | NOT NULL, default `false` |
| created_at | DateTime(tz) | NOT NULL |

**Constraints:**

- CHECK `(bucket_type = 'STAGING') = (category_id IS NOT NULL)` — staging is the only type that carries `category_id`.
- Partial UNIQUE `uq_triage_buckets_block_category` `(triage_block_id, category_id) WHERE category_id IS NOT NULL` — at most one staging bucket per `(block, category)`.
- Partial UNIQUE `uq_triage_buckets_block_type_tech` `(triage_block_id, bucket_type) WHERE bucket_type != 'STAGING'` — exactly one technical bucket of each type per block.

**Indexes:**

- `idx_triage_buckets_block` `(triage_block_id)` — fetch buckets for a block.
- `idx_triage_buckets_category` `(category_id) WHERE category_id IS NOT NULL` — used by D7 (snapshot for late-added category) and D8 (mark inactive on category soft-delete).

`ON DELETE CASCADE` on the FK to `triage_blocks` chains hard-deletes (which the API does not perform). Soft-delete via `triage_blocks.deleted_at` does not touch buckets — read paths apply the filter `WHERE triage_blocks.deleted_at IS NULL`. The FK to `categories` uses `ON DELETE RESTRICT` rather than `SET NULL`: setting `category_id` to NULL on a STAGING bucket would violate the `(bucket_type='STAGING') = (category_id IS NOT NULL)` CHECK. Hard-deleting a category that has any triage buckets is therefore prohibited at the SQL level — categories must remain referenced. spec-C's policy is soft-delete-only anyway (spec-C D6/D7), so this is purely defensive against future operator actions or a hypothetical hard-purge cron.

### 4.3 `triage_bucket_tracks`

| Column | Type | Constraints |
|---|---|---|
| triage_bucket_id | String(36) | PK (composite), FK → `triage_buckets.id` ON DELETE CASCADE |
| track_id | String(36) | PK (composite), FK → `clouder_tracks.id` |
| added_at | DateTime(tz) | NOT NULL |

**PK:** `(triage_bucket_id, track_id)` — UNIQUE makes move/transfer idempotent on conflict.

**Indexes:**

- `idx_triage_bucket_tracks_bucket_added` `(triage_bucket_id, added_at DESC, track_id)` — pagination of `GET .../buckets/{bucket_id}/tracks`.

### 4.4 Changes to existing tables

**`clouder_tracks`:**

- ADD COLUMN `spotify_release_date Date NULL`.
- Index: `idx_tracks_spotify_release_date (spotify_release_date) WHERE spotify_release_date IS NOT NULL`.

**`category_tracks`** (deferred from spec-C D16):

- ADD CONSTRAINT FK `(source_triage_block_id) → triage_blocks(id) ON DELETE SET NULL`.

### 4.5 Rationale notes

- `triage_buckets.inactive` is a flag, not a separate state machine. Avoids state-machine inflation; no transitions other than `false → true`.
- Buckets are created only at `POST /triage/blocks` time. The API does not allow ad-hoc bucket creation or deletion.
- Soft-deleted blocks remain readable in the database for audit; UI filters them out via `WHERE triage_blocks.deleted_at IS NULL`. Already-promoted `category_tracks` rows keep their `source_triage_block_id` audit pointer (the FK's `ON DELETE SET NULL` only fires on hard-delete).

## 5. API Surface

All routes JWT-gated. `user_id` is read from `event.requestContext.authorizer.lambda.user_id`. Cross-user access returns 404 (existence not leaked).

Error envelope (existing pattern from spec-C): `{error_code, message, correlation_id}`.

### 5.1 Response shapes

```json
// Bucket — embedded in TriageBlock detail
{
  "id": "uuid",
  "bucket_type": "NEW|OLD|NOT|DISCARD|UNCLASSIFIED|STAGING",
  "category_id": "uuid | null",
  "category_name": "string | null",
  "inactive": false,
  "track_count": 0
}

// TriageBlock — full form (detail)
{
  "id": "uuid",
  "style_id": "uuid",
  "style_name": "House",
  "name": "Tech House W17",
  "date_from": "2026-04-20",
  "date_to": "2026-04-26",
  "status": "IN_PROGRESS",
  "created_at": "...",
  "updated_at": "...",
  "finalized_at": null,
  "buckets": [Bucket, ...]
}

// TriageBlockSummary — light form (list)
{
  "id", "style_id", "style_name", "name",
  "date_from", "date_to", "status",
  "created_at", "updated_at", "finalized_at",
  "track_count": 123  // sum across all buckets
}
```

`category_name` is fetched via LEFT JOIN on `categories`. For inactive staging buckets, the name remains (the soft-deleted category row still exists) — frontend can display it with a "deleted" badge.

`buckets` in detail responses is sorted: technical buckets in fixed order `NEW, OLD, NOT, UNCLASSIFIED, DISCARD`, then staging buckets sorted by `categories.position ASC, categories.created_at DESC, categories.id ASC`.

### 5.2 `POST /triage/blocks` — create triage block

**Body:** `{style_id, name, date_from, date_to}`.

**Response 201:** full `TriageBlock` + `correlation_id`.

**Errors:**

- 422 `validation_error` — empty/whitespace-only name, name longer than 128, `date_to < date_from`, malformed dates.
- 404 `style_not_found`.

**Create flow (single TX):**

1. INSERT `triage_blocks` with `status='IN_PROGRESS'`.
2. INSERT 5 technical `triage_buckets` (NEW, OLD, NOT, DISCARD, UNCLASSIFIED).
3. SELECT alive categories for `(user_id, style_id)`; INSERT one staging bucket per category.
4. Build the bucket-type → bucket-id mapping in memory.
5. INSERT-FROM-SELECT into `triage_bucket_tracks`: source query (D4) JOINed with the R4 CASE expression (see §6.1). Tracks land in NEW / OLD / NOT / UNCLASSIFIED based on classification; staging buckets stay empty.
6. COMMIT.

**Known runtime risk:** for very large weekly windows (1000+ tracks) on a cold Aurora cluster, this single-shot create may approach the API Gateway 29s timeout. If the client receives the API Gateway `Service Unavailable` envelope, the Lambda may still complete the work in the background, and a retry could create a duplicate block (we do not enforce name/window uniqueness — D2/D3). Documented as a known limitation; UI should display a "creation may have succeeded — check the list" hint on 503. Async-create via Step Functions is deferred (`FUTURE-D3` covers the analogous concern on finalize).

### 5.3 `GET /styles/{style_id}/triage/blocks` — list by style

**Query:** `limit` (default 50, max 200), `offset` (default 0), `status` (optional, `IN_PROGRESS` or `FINALIZED`).

**Response 200:** `{items: [TriageBlockSummary], total, limit, offset, correlation_id}`.

**Sort:** `created_at DESC, id ASC`.

**Errors:** 404 `style_not_found`.

### 5.4 `GET /triage/blocks` — cross-style list

**Query:** `limit`, `offset`, `status` (optional).

**Response 200:** same shape, no style filter.

### 5.5 `GET /triage/blocks/{id}` — detail

**Response 200:** full `TriageBlock` + `correlation_id`. `track_count` per bucket is computed via a single aggregate query.

**Errors:** 404 `triage_block_not_found`.

### 5.6 `GET /triage/blocks/{id}/buckets/{bucket_id}/tracks` — list tracks in a bucket

**Query:** `limit` (default 50, max 200), `offset`, optional `search` (lowercased + trimmed; matched via `ILIKE %term%` on `clouder_tracks.normalized_title`).

**Response 200:** `{items: [BucketTrackRow], total, limit, offset, correlation_id}`.

`BucketTrackRow` has the same fields as the existing `GET /categories/{id}/tracks` row — id, title, mix_name, isrc, bpm, length_ms, publish_date, **`spotify_release_date`**, spotify_id, release_type, is_ai_suspected, artists list — plus `added_at` from the bucket.

**Sort:** `added_at DESC, track_id ASC` (fixed; sort param deferred — `FUTURE-D6`).

**Errors:** 404 `triage_block_not_found`, 404 `bucket_not_in_block`.

### 5.7 `POST /triage/blocks/{id}/move` — move tracks (intra-block batch)

**Body:** `{from_bucket_id, to_bucket_id, track_ids: [uuid]}`. Cap `len(track_ids) ≤ 1000`.

**Response 200:** `{moved: <int>, correlation_id}`. `moved` counts rows that were actually moved (already-in-target rows count as 0 movement).

**Errors:**

- 422 `validation_error` (cap exceeded, malformed UUID).
- 404 `triage_block_not_found`, 404 `bucket_not_in_block` (for either bucket).
- 422 `block_not_editable` (status != IN_PROGRESS or soft-deleted).
- 422 `target_bucket_inactive`.
- 422 `tracks_not_in_source` — body includes `{not_in_source: [uuid, ...]}`.

**TX shape:**

```sql
-- 1. validate buckets-in-block, status, target.inactive
-- 2. SELECT track_ids actually present in from_bucket
-- 3. validate full set match → 422 if any missing
-- 4. DELETE FROM triage_bucket_tracks WHERE triage_bucket_id = :from AND track_id = ANY(:ids)
-- 5. INSERT INTO triage_bucket_tracks (...) SELECT :to, unnest(:ids), :now
   ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
```

`from == to` short-circuits to a 200 with `moved: <existing_count>`.

### 5.8 `POST /triage/blocks/{src_id}/transfer` — transfer tracks (cross-block snapshot)

**Body:** `{target_bucket_id, track_ids: [uuid]}`. Cap 1000.

**Response 200:** `{transferred: <int>, correlation_id}` — newly-inserted rows. Conflicts are not counted.

**Errors:**

- 422 `validation_error`.
- 404 `triage_block_not_found` (src), 404 `target_bucket_not_found`.
- 422 `target_block_not_in_progress`.
- 422 `target_block_style_mismatch`.
- 422 `target_bucket_inactive`.
- 422 `tracks_not_in_source` (from any bucket of the src block).

**TX shape:**

```sql
-- 1. SELECT target_bucket → block.user_id, block.style_id, block.status, bucket.inactive
-- 2. validate same user, same style, status=IN_PROGRESS, not inactive
-- 3. SELECT track_ids actually present in any bucket of the src block
-- 4. INSERT INTO triage_bucket_tracks (...) SELECT :target, unnest(:ids), :now
   ON CONFLICT DO NOTHING
```

Source is not mutated.

### 5.9 `POST /triage/blocks/{id}/finalize` — finalize (promotion)

**Response 200:** `{block: TriageBlock, promoted: {<category_id>: <count>}, correlation_id}`.

**Errors:**

- 404 `triage_block_not_found`.
- 422 `block_not_editable` (already FINALIZED or soft-deleted).
- 409 `inactive_buckets_have_tracks` — body: `{inactive_buckets: [{id, category_id, track_count}, ...]}`.

**TX shape:**

```python
# 1. validate status=IN_PROGRESS, not soft-deleted
# 2. SELECT inactive staging buckets WITH track_count > 0 → 409 if any
# 3. for each active staging bucket:
#      categories_repository.add_tracks_bulk(
#          user_id, category_id,
#          items=[(track_id, source_triage_block_id=:block_id) for ...],
#          transaction_id=tx,
#      )
#    items chunked at 500 per call; multiple calls per staging bucket if needed
# 4. UPDATE triage_blocks SET status='FINALIZED', finalized_at=NOW(), updated_at=NOW()
#    WHERE id=:block_id
# 5. COMMIT
```

After finalize, no triage rows are deleted — the staging buckets and their tracks remain as a historical record, and the block is read-only.

### 5.10 `DELETE /triage/blocks/{id}` — soft-delete

**Response 204** (empty body).

**Errors:** 404 `triage_block_not_found` (including a repeated DELETE on an already-soft-deleted row).

UPDATE `triage_blocks SET deleted_at = NOW()`. Already-promoted `category_tracks` keep `source_triage_block_id` (the FK's `ON DELETE SET NULL` only fires on hard-delete).

## 6. R4 Classification + Spotify Enrichment Patch

### 6.1 R4 in code

The classification SQL runs once, inside the create-block TX (step 5 of §5.2):

```sql
INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)
SELECT
  CASE
    WHEN t.spotify_release_date IS NULL
      THEN :unclassified_bucket_id
    WHEN t.spotify_release_date < :date_from
      THEN :old_bucket_id
    WHEN t.release_type = 'compilation'
      THEN :not_bucket_id
    ELSE :new_bucket_id
  END AS triage_bucket_id,
  t.id,
  :now
FROM clouder_tracks t
WHERE t.style_id = :style_id
  AND t.publish_date BETWEEN :date_from AND :date_to
  AND NOT EXISTS (
    SELECT 1
    FROM category_tracks ct
    JOIN categories c ON ct.category_id = c.id
    WHERE c.user_id = :user_id
      AND c.style_id = :style_id
      AND c.deleted_at IS NULL
      AND ct.track_id = t.id
  );
```

The four bucket-id bind parameters are populated from the bucket-type → bucket-id map built in step 4 of §5.2.

Staging buckets are not populated by R4 — they start empty and the user moves tracks into them manually.

**Edge cases (worth a code comment):**

- `style_id IS NULL` on a track → excluded by the `=` predicate (NULL ≠ value).
- `publish_date IS NULL` → excluded by BETWEEN.
- `spotify_release_date == :date_from` → falls into NEW (`<`, not `<=`). A track released exactly on the window start is "fresh material".
- A track with both `release_type='compilation'` and `spotify_release_date < :date_from` → OLD. Date precedence is higher than compilation; if the audio existed before the window, re-release semantics dominate.
- A track without ISRC will typically have NULL `spotify_release_date` (Spotify lookup keys on ISRC) → UNCLASSIFIED.

### 6.2 Spotify enrichment patch

**Current behavior** (`spotify_handler.py`): on ISRC lookup hit, the worker writes `spotify_id`, `spotify_searched_at`, and `release_type` (= `album.album_type`) on `clouder_tracks`.

**This spec adds:** parsing `album.release_date` and `album.release_date_precision`, then writing `clouder_tracks.spotify_release_date`.

**Precision parsing:**

| Precision | Spotify value | Stored as |
|---|---|---|
| `day` | `"2024-03-15"` | `2024-03-15` |
| `month` | `"2024-03"` | `2024-03-01` |
| `year` | `"2024"` | `2024-01-01` |

**Concrete patch points:**

1. `src/collector/repositories.py` — `UpdateSpotifyResultCmd` gains a new field:

   ```python
   spotify_release_date: date | None = None
   ```

2. `src/collector/repositories.py` — `batch_update_spotify_results` SQL adds:

   ```sql
   spotify_release_date = COALESCE(:spotify_release_date, spotify_release_date),
   ```

   And the bind dict gains `"spotify_release_date": cmd.spotify_release_date`. `COALESCE` preserves prior values when Spotify returns no `release_date` for a particular track (consistent with how `release_type` is handled).

3. `src/collector/spotify_handler.py` — alongside `_extract_album_type`, add `_extract_release_date(spotify_track)` that returns `date | None`:

   ```python
   def _extract_release_date(spotify_track: Mapping[str, Any] | None) -> date | None:
       if not isinstance(spotify_track, Mapping):
           return None
       album = spotify_track.get("album")
       if not isinstance(album, Mapping):
           return None
       raw = album.get("release_date")
       precision = album.get("release_date_precision")
       if not isinstance(raw, str) or not isinstance(precision, str):
           return None
       try:
           if precision == "day":
               return date.fromisoformat(raw)
           if precision == "month":
               return date.fromisoformat(f"{raw}-01")
           if precision == "year":
               return date.fromisoformat(f"{raw}-01-01")
       except ValueError:
           return None
       return None
   ```

4. `src/collector/spotify_handler.py` — the `UpdateSpotifyResultCmd` constructor gains:

   ```python
   spotify_release_date=_extract_release_date(r.spotify_track),
   ```

5. `src/collector/db_models.py` — `ClouderTrack` SQLAlchemy model gains:

   ```python
   spotify_release_date: Mapped[date_type | None] = mapped_column(Date)
   ```

   Used for alembic autogen only; runtime uses Data API.

**Backfill:** existing `clouder_tracks` rows have `spotify_release_date IS NULL` after migration. UNCLASSIFIED bucket will catch them in any new triage. An operational script (`scripts/backfill_spotify_release_date.py`) can sweep `WHERE spotify_id IS NOT NULL AND spotify_release_date IS NULL` and re-fetch from Spotify; this script is out-of-scope for the spec deliverable.

### 6.3 UNCLASSIFIED is "data missing", not "rejected"

UNCLASSIFIED is a temporary bucket. As Spotify enrichment proceeds (either naturally on next ingest cycles or via the backfill script), tracks gain `spotify_release_date` and the next triage created for that style classifies them correctly. R4 does not re-run on existing triages (D14) — moving tracks out of UNCLASSIFIED inside an existing triage is the user's responsibility.

## 7. Code Layout

### 7.1 Lambda layout

The existing `curation_handler.py` Lambda from spec-C is extended. No new Lambda is created.

```
src/collector/
├── curation/
│   ├── __init__.py                     # spec-C, unchanged
│   ├── categories_repository.py        # spec-C, unchanged
│   ├── categories_service.py           # spec-C, +1 call in create, +1 call in soft_delete (D7, D8)
│   ├── triage_repository.py            # NEW
│   ├── triage_service.py               # NEW
│   └── schemas.py                      # spec-C, extended
├── curation_handler.py                 # spec-C, +9 handlers
├── spotify_handler.py                  # patch (D18) — +spotify_release_date
└── repositories.py                     # patch (D18) — +spotify_release_date
```

### 7.2 `triage_repository.py` — public surface

`TriageRepository` (Aurora Data API client, same pattern as existing `repositories.py`):

| Method | Notes |
|---|---|
| `create_block(user_id, style_id, name, date_from, date_to) -> TriageBlockRow` | Outer TX runs all 6 steps from §5.2. Returns the full block with embedded buckets and per-bucket `track_count`. |
| `get_block(user_id, block_id) -> TriageBlockRow \| None` | Filters `deleted_at IS NULL`. JOINs `categories` for `category_name`. Computes per-bucket `track_count`. |
| `list_blocks_by_style(user_id, style_id, *, limit, offset, status) -> tuple[list[BlockSummary], int]` | Lightweight summary (no buckets), with `total`. |
| `list_blocks_all(user_id, *, limit, offset, status) -> tuple[list[BlockSummary], int]` | Cross-style. |
| `list_bucket_tracks(user_id, block_id, bucket_id, *, limit, offset, search) -> tuple[list[TrackRow], int]` | Validates ownership + bucket-in-block. JOINs `clouder_tracks` + artists. Sorts `added_at DESC`. |
| `move_tracks(user_id, block_id, from_bucket_id, to_bucket_id, track_ids) -> MoveResult` | Validates buckets-in-block + status + target-not-inactive + tracks-in-source. TX: DELETE + INSERT ON CONFLICT DO NOTHING. |
| `transfer_tracks(user_id, src_block_id, target_bucket_id, track_ids) -> TransferResult` | Validates src-exists + target-bucket+block + same-user + same-style + target-IN_PROGRESS + target-not-inactive + tracks-in-src. INSERT ON CONFLICT DO NOTHING. |
| `finalize_block(user_id, block_id, *, categories_repository) -> FinalizeResult` | Outer TX. Validates IN_PROGRESS + checks inactive-staging-with-tracks → 409. For each active staging bucket, chunks items at 500 entries and calls `categories_repository.add_tracks_bulk(user_id, category_id, items, transaction_id=tx)` once per chunk. UPDATE `status='FINALIZED', finalized_at=NOW(), updated_at=NOW()`. Returns updated block + per-category promote counts. |
| `soft_delete_block(user_id, block_id) -> bool` | UPDATE `deleted_at` if NULL. |
| `snapshot_category_into_active_blocks(user_id, style_id, category_id, *, transaction_id) -> int` | Public. Called from `categories_service.create` (D7). INSERTs one staging bucket per IN_PROGRESS, non-soft-deleted block of `(user, style)`. UPSERT via `ON CONFLICT (triage_block_id, category_id) WHERE category_id IS NOT NULL DO NOTHING`. Returns inserted count. |
| `mark_staging_inactive_for_category(user_id, category_id, *, transaction_id) -> int` | Public. Called from `categories_service.soft_delete` (D8). UPDATE `triage_buckets SET inactive=true WHERE category_id=:c`. Returns affected count. |

### 7.3 `triage_service.py` — public surface

Thin layer above the repository:

- `validate_block_input(name, date_from, date_to)` — name length, ISO date validity, `date_to >= date_from`. Raises `ValidationError`.
- `validate_track_ids(ids)` — UUID format, length ≤ 1000.
- `validate_buckets_in_block(buckets, block_id)` — every `bucket_id` belongs to `block_id`.
- `validate_target_for_transfer(src_block, target_bucket, target_block)` — same user, same style, target IN_PROGRESS, target not inactive.

R4 classification logic itself lives in SQL (§6.1), not in Python.

### 7.4 `categories_repository.py` / `categories_service.py` — patches (spec-C)

**`categories_service.create`** — after the existing INSERT, in the same TX:

```python
inserted = triage_repository.snapshot_category_into_active_blocks(
    user_id=user_id,
    style_id=style_id,
    category_id=new_category.id,
    transaction_id=tx,
)
log.info("category_created", ..., snapshot_inserted_into_blocks=inserted)
```

**`categories_service.soft_delete`** — after the existing UPDATE:

```python
inactivated = triage_repository.mark_staging_inactive_for_category(
    user_id=user_id,
    category_id=category_id,
    transaction_id=tx,
)
log.info("category_soft_deleted", ..., inactive_buckets=inactivated)
```

`categories_service.rename` is unchanged — staging buckets reference `category_id`, no denormalized name.

### 7.5 `curation_handler.py` — adding 9 handlers

The existing `(method, route)` dispatcher is extended:

```python
ROUTES = {
    # spec-C (existing)
    ("POST", "/styles/{style_id}/categories"): _create_category,
    # ... 8 spec-C routes ...

    # spec-D (new)
    ("POST", "/triage/blocks"): _create_triage_block,
    ("GET", "/styles/{style_id}/triage/blocks"): _list_triage_blocks_by_style,
    ("GET", "/triage/blocks"): _list_triage_blocks_all,
    ("GET", "/triage/blocks/{id}"): _get_triage_block,
    ("GET", "/triage/blocks/{id}/buckets/{bucket_id}/tracks"): _list_bucket_tracks,
    ("POST", "/triage/blocks/{id}/move"): _move_tracks,
    ("POST", "/triage/blocks/{id}/transfer"): _transfer_tracks,
    ("POST", "/triage/blocks/{id}/finalize"): _finalize_triage_block,
    ("DELETE", "/triage/blocks/{id}"): _soft_delete_triage_block,
}
```

Each handler reads `user_id` from the authorizer context, parses path/body via Pydantic schemas, calls repository/service, maps domain exceptions to the error envelope, and emits a structlog event.

### 7.6 `schemas.py` — extensions

New Pydantic models:

- `CreateTriageBlockIn`, `TriageBlockSummary`, `TriageBlockDetail`, `BucketDetail`.
- `MoveTracksIn` (with `track_ids: list[UUID]` and `max_items=1000`), `MoveTracksOut`.
- `TransferTracksIn` (same cap), `TransferTracksOut`.
- `FinalizeTriageBlockOut` (with `promoted: dict[uuid, int]`).
- `BucketTrackRow` (TrackRow + `added_at`).

### 7.7 Logging

Structlog events emitted by handlers (each carries `correlation_id`, `user_id`):

- `triage_block_created` (with `style_id`, `name`, `date_from`, `date_to`, `bucket_counts_by_type`).
- `triage_block_listed`, `triage_block_detail_completed`, `triage_bucket_tracks_listed`.
- `triage_tracks_moved` (`from_bucket_type`, `to_bucket_type`, `count`).
- `triage_tracks_transferred` (`src_block_id`, `target_bucket_type`, `count`).
- `triage_block_finalized` (`promoted_per_category`).
- `triage_block_soft_deleted`.
- `category_snapshot_created` (D7 side-effect).
- `category_staging_inactive` (D8 side-effect).

### 7.8 Transactions and retry

Multi-statement TXs use `repository.transaction()` from existing `data_api.py`. Decorators: `retry_data_api` on read/write statements; `retry_data_api_pre_execution` on `commit_transaction` / `rollback_transaction`. The `create_block` and `finalize_block` flows fall under this pattern unchanged.

## 8. Migration & Infrastructure

### 8.1 Alembic migration `20260428_15_triage.py`

**Upgrade:**

1. CREATE TABLE `triage_blocks` (§4.1) with all CHECKs and indexes.
2. CREATE TABLE `triage_buckets` (§4.2) with CHECKs, partial UNIQUEs, FK to `triage_blocks` (`ON DELETE CASCADE`), FK to `categories` (`ON DELETE RESTRICT`).
3. CREATE TABLE `triage_bucket_tracks` (§4.3) with composite PK, FKs.
4. ALTER TABLE `clouder_tracks` ADD COLUMN `spotify_release_date Date NULL` + partial index.
5. ALTER TABLE `category_tracks` ADD CONSTRAINT FK `(source_triage_block_id) → triage_blocks(id) ON DELETE SET NULL` (deferred from spec-C D16).
6. GRANT SELECT, INSERT, UPDATE, DELETE on all three new tables to the `clouder_app` role.

**Downgrade (symmetric):** drop the FK, drop the column + index, drop the three tables in reverse FK order.

CI `alembic-check` (ephemeral postgres) validates the migration. The migration does not perform data backfill.

### 8.2 Terraform additions (`infra/curation.tf`)

No new Lambda function. The existing `aws_lambda_function.curation` from spec-C gets:

- 9 × `aws_apigatewayv2_route` for the new paths (§5), all attached to the existing `aws_apigatewayv2_integration.curation` and JWT authorizer.

The Spotify worker Lambda is not changed in Terraform — the code patch loads via the same `dist/collector.zip`.

IAM permissions on `curation` already include `rds-data:ExecuteStatement` and `secretsmanager:GetSecretValue`. No additions.

### 8.3 Packaging

`scripts/package_lambda.sh` already copies all of `src/collector/`. New modules are picked up automatically. No script change.

### 8.4 OpenAPI regen

After shipping the routes, regenerate `docs/openapi.yaml` per the CLAUDE.md gotcha:

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py
```

The 9 new paths must be added to the manual `ROUTES` table in `scripts/generate_openapi.py`. Commit the regenerated YAML alongside the spec-D code.

### 8.5 CI / deploy

`.github/workflows/pr.yml`: `alembic-check` runs the new migration; `tests` runs new pytest files; `terraform fmt/validate/plan` shows the new routes.

`.github/workflows/deploy.yml`: unchanged. Sequence — package → `terraform apply` → invoke migration Lambda — applies `20260428_15_triage.py` in prod.

### 8.6 Env vars

No new env vars. The `curation` Lambda and `spotify_worker` Lambda use the existing sets.

### 8.7 Known runtime risks (documented)

1. **Cold-start Aurora + large `POST /triage/blocks`.** A 1000+ track window on a cold cluster may exceed the API Gateway 29s timeout. Symptom: client gets `Service Unavailable` (API Gateway envelope) but the Lambda may finish in the background. Retry behavior is not idempotent — a successful first run plus a retry creates a duplicate block (D2/D3 allow duplicates). Mitigation: documented; UI displays a "creation may have succeeded — check the list" hint on 503.
2. **`add_tracks_bulk` chunking on finalize.** Staging buckets above ~5000 tracks may exceed 29s when issuing many 500-item `add_tracks_bulk` calls in one TX. `FUTURE-D3` covers async-finalize via Step Functions; not a blocker for MVP.
3. **`POST /transfer` cap = 1000.** Justified by Aurora Data API parameter-set limits.

## 9. Testing

### 9.1 Unit

`tests/unit/test_triage_service.py`:

- `validate_block_input` — empty/whitespace-only name, length > 128, `date_to < date_from`, malformed ISO → `ValidationError`.
- `validate_track_ids` — non-UUID elements, empty array, > 1000 → `ValidationError`.
- `validate_buckets_in_block` — bucket not belonging to block → error.
- `validate_target_for_transfer` — different style, target FINALIZED, target inactive — each raises.

`tests/unit/test_triage_repository.py` (mock `DataAPIClient`, assert SQL + bind params):

- `create_block` — all 6 steps in order; staging buckets created per alive category.
- R4 SQL (§6.1) — assert CASE expression and four bucket-id binds.
- `move_tracks` — source-validate SELECT, DELETE+INSERT in TX.
- `transfer_tracks` — no source mutation; INSERT ON CONFLICT DO NOTHING.
- `finalize_block` — 409 on inactive staging with tracks; chunking to 500 in `add_tracks_bulk` calls.
- `snapshot_category_into_active_blocks` — UPSERT idempotent on repeated call.
- `mark_staging_inactive_for_category` — only staging of that category updated; tracks untouched.
- Tenancy: every method places `user_id` in WHERE.

`tests/unit/test_curation_schemas.py` (extend):

- Pydantic round-trip for `CreateTriageBlockIn`, `MoveTracksIn` (cap 1000), `TransferTracksIn` (cap 1000).

`tests/unit/test_spotify_handler.py` (extend):

- `_extract_release_date` — precision `day`/`month`/`year` ✓; NULL `release_date_precision`; unknown precision; malformed date string; missing album.
- `UpdateSpotifyResultCmd` constructed with `spotify_release_date` correctly for each precision.

`tests/unit/test_repositories.py` (extend):

- `batch_update_spotify_results` SQL contains `spotify_release_date = COALESCE(:spotify_release_date, spotify_release_date)` and the bind key is forwarded.

### 9.2 Integration (`tests/integration/test_triage_handler.py`)

Ephemeral postgres + Lambda invoke (matching `tests/integration/test_curation_handler.py`). Each test seeds its own `clouder_tracks` / `categories` / users.

1. **Happy-path create.** 5 tracks in window (NEW/OLD/NOT/UNCLASSIFIED mix), 2 categories. POST triage → 201, full `TriageBlock` shape, all buckets present, tracks distributed correctly, staging buckets empty.
2. **R4 classification detail.**
   - Track A (`spotify_release_date='2025-01-01'`, `date_from='2026-04-01'`) → OLD.
   - Track B (`spotify_release_date='2026-04-15'`, in window, `release_type='single'`) → NEW.
   - Track C (`spotify_release_date='2026-04-15'`, `release_type='compilation'`) → NOT.
   - Track D (`spotify_release_date IS NULL`) → UNCLASSIFIED.
   - Track E (`spotify_release_date='2026-04-01'` exactly `date_from`) → NEW.
   - Track F (`spotify_release_date='2025-12-01'`, `release_type='compilation'`) → OLD (date wins).
3. **Source filter.** Track G in user's category for this style — excluded. Track H in *another* user's category — included. Track I in a soft-deleted category of the same user — included (filter is on alive categories only).
4. **Tenancy.** User A creates a block. User B does not see it in list/detail (404). User B's move/transfer/finalize/delete on it → 404.
5. **List + pagination.** Create 60 blocks → list-by-style with `limit=50` returns 50 + `total=60`. `?status=IN_PROGRESS` filters.
6. **Detail bucket sort.** `GET /triage/blocks/{id}` returns buckets in order `NEW, OLD, NOT, UNCLASSIFIED, DISCARD, staging[position ASC]`.
7. **Move within block.** Move 3 tracks NEW → staging-X; verify counts. Repeat → `moved=0`. Move staging-X → DISCARD → ok. Move into inactive staging → 422 `target_bucket_inactive`. Cap 1001 → 422.
8. **Transfer cross-block.** Two IN_PROGRESS blocks in the same style. Transfer 5 from `block1.NEW` → `block2.UNCLASSIFIED`. Source unchanged. Target has 5. Repeat → `transferred=0`. Transfer to FINALIZED block → 422. Cross-style transfer → 422.
9. **Late-category snapshot (D7).** Create triage → 5 buckets + 0 staging. Create a category → 1 staging appears. Create another → 2 staging. Detail confirms.
10. **Soft-delete category cascades inactive (D8).** Create category, triage → staging-X exists. Put 3 tracks in staging-X. Soft-delete category. `triage_buckets.inactive=true` for staging-X, tracks remain. Finalize → 409 `inactive_buckets_have_tracks` listing the bucket and `track_count=3`.
11. **Finalize happy path.** Triage with 2 staging (3 tracks each) and 5 in NEW. Finalize → 200, `promoted={cat1: 3, cat2: 3}`. `category_tracks` has 6 rows with `source_triage_block_id` pointing to this block. Block `status=FINALIZED`, `finalized_at` set. NEW tracks remain in their bucket. Repeat finalize → 422 `block_not_editable`.
12. **Finalize idempotent on `add_tracks_bulk`.** Track was added directly to category before triage; same track in staging-X. Finalize → no 409, `category_tracks` retains a single row, `source_triage_block_id` keeps the original (first-write-wins per spec-C D4).
13. **Soft-delete block.** DELETE → 204. GET → 404. List excludes. Already-promoted `category_tracks` keep `source_triage_block_id`.
14. **Move/transfer on FINALIZED block.** Finalize first. Move → 422 `block_not_editable`. Transfer **from** FINALIZED → ok (source can be any status). Transfer **to** FINALIZED → 422 `target_block_not_in_progress`.
15. **Cap 1000.** POST move/transfer with 1001 ids → 422 (Pydantic). With 1000 → ok.
16. **Spotify enrichment patch.** Spotify worker mock returns `release_date='2024-03'` + `release_date_precision='month'` → `clouder_tracks.spotify_release_date='2024-03-01'`. Subsequent run with `release_date_precision='day'` for the same ISRC overwrites.
17. **Overlapping windows (D3).** Two IN_PROGRESS blocks in the same style with overlapping `[date_from, date_to]` — both succeed. A track appears in both. Finalize first → track in category. Finalize second → `add_tracks_bulk` → ON CONFLICT DO NOTHING → no-op → finalize succeeds.

### 9.3 No load tests in scope

Realistic sizes: ≪ 100 categories per `(user, style)` → ≪ 100 staging buckets per block; weekly windows of 200–2000 tracks per style at p95; per-category staging contents rarely above a few hundred per session. Aurora Data API serves all queries in single-digit ms on warm clusters. If production data shows windows above ~5000 tracks, R4 SQL benchmarking lands in `FUTURE-D4`.

### 9.4 Coverage

No numeric gate. Every repository / service method has at least one unit test; all 9 routes have at least one happy-path and one error-path integration test.

## 10. Open Items, Edge Cases, Future Flags

### 10.1 Edge cases worth code comments

- **`spotify_release_date == date_from`** → NEW (`<`, not `<=`). Documented in the R4 SQL site.
- **R4 does not re-run.** `bucket_type` is fixed at create time. Spotify enrichment that arrives later does not reclassify — the user sees corrected classification in their next triage.
- **`source_triage_block_id` orphan after soft-delete.** The audit pointer remains; the `ON DELETE SET NULL` only fires on hard-delete, which the API does not perform.
- **`add_tracks_bulk` first-write-wins.** Direct-add (spec-C) may set `source_triage_block_id=NULL`; finalize later does not overwrite — guaranteed by spec-C D4.

### 10.2 Future flags

- **`FUTURE-D1`** — hard-purge cron for soft-deleted triage blocks. Analogous to spec-C `FUTURE-C4`.
- **`FUTURE-D2`** — `POST /triage/blocks/{id}/buckets/{bucket_id}/enrich` for UNCLASSIFIED — async per-track Spotify enrichment + reclassification within a block. Requires revisiting D14.
- **`FUTURE-D3`** — async-finalize via Step Functions for staging buckets above ~5000 tracks.
- **`FUTURE-D4`** — R4 SQL benchmarking and index tuning for very wide windows.
- **`FUTURE-D5`** — restore from soft-delete.
- **`FUTURE-D6`** — `?sort=` and richer filters on the bucket-track listing.

### 10.3 Cross-spec dependencies

- **spec-D consumes** `categories_repository.add_tracks_bulk(user_id, category_id, items, transaction_id)` (spec-C D17 contract). `items: list[tuple[track_id, source_triage_block_id]]`. Method runs inside the caller's TX when `transaction_id` is provided.
- **spec-D patches spec-C** `categories_service.create` and `categories_service.soft_delete` for the snapshot side-effects (D7, D8).
- **spec-D adds** the FK `category_tracks.source_triage_block_id → triage_blocks(id) ON DELETE SET NULL`.
- **spec-D patches** the Spotify worker (`spotify_handler.py`, `repositories.py`, SQLAlchemy model) to write `spotify_release_date`.
- **spec-E (release playlists)** has no direct dependency on spec-D, but tracks added to release playlists in real-world flows will typically come from categories populated through triage.

## 11. Acceptance Criteria

- All 9 routes return the documented status codes and response shapes (§5).
- Migration `20260428_15_triage.py` applies on the CI ephemeral postgres and on prod Aurora.
- Integration tests #1–#17 (§9.2) all green.
- Tenancy: integration test #4 confirms cross-user 404.
- R4: integration test #2 confirms all six classification rules including the date-vs-compilation precedence.
- Late-snapshot: integration test #9 confirms eager INSERT into active triage blocks on category create.
- Inactive cascade + finalize block: integration test #10 confirms 409 with the inactive-buckets payload.
- Promotion: integration test #11 confirms `category_tracks` insert + status flip + per-category counts.
- Spotify enrichment: integration test #16 confirms `spotify_release_date` is written from each precision and that COALESCE preserves prior values.

## 12. References

- Parent: [`2026-04-25-old-version-feature-parity-design.md`](./2026-04-25-old-version-feature-parity-design.md)
- spec-A (predecessor): [`2026-04-25-spec-A-user-auth-design.md`](./2026-04-25-spec-A-user-auth-design.md)
- spec-C (predecessor): [`2026-04-26-spec-C-categories-design.md`](./2026-04-26-spec-C-categories-design.md)
- Vendor-sync readiness (sibling): [`2026-04-18-vendor-sync-readiness-design.md`](./2026-04-18-vendor-sync-readiness-design.md)
- Data model: `docs/data-model.md`
- Project gotchas: root `CLAUDE.md`
- Tenancy memory: `project_clouder_tenancy.md`

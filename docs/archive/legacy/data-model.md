# Clouder Core - Data Model

> Current project data model. Date: 2026-04-18

## Overview

Music industry metadata aggregation and canonicalization system.
Data is collected from external sources (Beatport), normalized, canonicalized
into a unified model, and enriched via AI search.

---

## 1. Database Tables (PostgreSQL / Aurora Serverless v2)

Source: `src/collector/db_models.py` (SQLAlchemy)

### 1.1 ingest_runs

Data collection runs from external sources.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| run_id          | String(36)         | PK                       |
| source          | String(32)         | NOT NULL                 |
| style_id        | Integer            | NOT NULL                 |
| iso_year        | Integer            | NOT NULL                 |
| iso_week        | Integer            | NOT NULL                 |
| raw_s3_key      | Text               | NOT NULL                 |
| status          | String(32)         | NOT NULL                 |
| item_count      | Integer            | NOT NULL, default=0      |
| processed_count | Integer            | NOT NULL, default=0      |
| started_at      | DateTime(tz)       | NOT NULL                 |
| finished_at     | DateTime(tz)       | nullable                 |
| error_code      | String(64)         | nullable                 |
| error_message   | Text               | nullable                 |
| meta            | JSONB              | NOT NULL, default='{}'   |

### 1.2 source_entities

Raw entities from external sources before canonicalization.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| source          | String(32)         | PK (composite)           |
| entity_type     | String(32)         | PK (composite)           |
| external_id     | String(64)         | PK (composite)           |
| name            | Text               | nullable                 |
| normalized_name | Text               | nullable                 |
| payload         | JSONB              | NOT NULL                 |
| payload_hash    | String(64)         | NOT NULL                 |
| first_seen_at   | DateTime(tz)       | NOT NULL                 |
| last_seen_at    | DateTime(tz)       | NOT NULL                 |
| last_run_id     | String(36)         | NOT NULL, FK -> ingest_runs.run_id |

**PK:** (source, entity_type, external_id)
**Indexes:** idx_source_entities_run (last_run_id)

### 1.3 source_relations

Relationships between entities in the source system.

| Column            | Type             | Constraints              |
|-------------------|------------------|--------------------------|
| source            | String(32)       | PK (composite)           |
| from_entity_type  | String(32)       | PK (composite)           |
| from_external_id  | String(64)       | PK (composite)           |
| relation_type     | String(64)       | PK (composite)           |
| to_entity_type    | String(32)       | PK (composite)           |
| to_external_id    | String(64)       | PK (composite)           |
| last_run_id       | String(36)       | NOT NULL, FK -> ingest_runs.run_id |

**PK:** (source, from_entity_type, from_external_id, relation_type, to_entity_type, to_external_id)

### 1.4 clouder_artists

Canonicalized artists.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| id              | String(36)         | PK (UUID)                |
| name            | Text               | NOT NULL                 |
| normalized_name | Text               | NOT NULL                 |
| is_ai_suspected | Boolean            | NOT NULL, default=false  |
| created_at      | DateTime(tz)       | NOT NULL                 |
| updated_at      | DateTime(tz)       | NOT NULL                 |

### 1.5 clouder_labels

Canonicalized record labels.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| id              | String(36)         | PK (UUID)                |
| name            | Text               | NOT NULL                 |
| normalized_name | Text               | NOT NULL                 |
| is_ai_suspected | Boolean            | NOT NULL, default=false  |
| created_at      | DateTime(tz)       | NOT NULL                 |
| updated_at      | DateTime(tz)       | NOT NULL                 |

### 1.6 clouder_styles

Canonicalized music styles/genres.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| id              | String(36)         | PK (UUID)                |
| name            | Text               | NOT NULL                 |
| normalized_name | Text               | NOT NULL                 |
| created_at      | DateTime(tz)       | NOT NULL                 |
| updated_at      | DateTime(tz)       | NOT NULL                 |

### 1.8 clouder_albums

Canonicalized albums/releases.

| Column           | Type              | Constraints              |
|------------------|-------------------|--------------------------|
| id               | String(36)        | PK (UUID)                |
| title            | Text              | NOT NULL                 |
| normalized_title | Text              | NOT NULL                 |
| release_date     | Date              | nullable                 |
| label_id         | String(36)        | nullable, FK -> clouder_labels.id |
| release_type     | String(16)        | nullable                 |
| created_at       | DateTime(tz)      | NOT NULL                 |
| updated_at       | DateTime(tz)      | NOT NULL                 |

**Indexes:** idx_album_match (normalized_title, release_date, label_id)

`release_type` values: `album`, `single`, `compilation` (sourced from Spotify `album.album_type`; Beatport does not expose this).

### 1.9 clouder_tracks

Canonicalized tracks.

| Column              | Type              | Constraints              |
|---------------------|-------------------|--------------------------|
| id                  | String(36)        | PK (UUID)                |
| title               | Text              | NOT NULL                 |
| normalized_title    | Text              | NOT NULL                 |
| mix_name            | Text              | nullable                 |
| isrc                | String(64)        | nullable                 |
| bpm                 | Integer           | nullable                 |
| length_ms           | Integer           | nullable                 |
| publish_date        | Date              | nullable                 |
| album_id            | String(36)        | nullable, FK -> clouder_albums.id |
| style_id            | String(36)        | nullable, FK -> clouder_styles.id |
| spotify_id          | String(64)        | nullable                 |
| spotify_searched_at | DateTime(tz)      | nullable                 |
| spotify_release_date | Date             | nullable; populated by Spotify enrichment from `album.release_date` per `release_date_precision` |
| release_type        | String(16)        | nullable                 |
| is_ai_suspected     | Boolean           | NOT NULL, default=false  |
| created_at          | DateTime(tz)      | NOT NULL                 |
| updated_at          | DateTime(tz)      | NOT NULL                 |

**Indexes:** idx_tracks_isrc (isrc) WHERE isrc IS NOT NULL, idx_tracks_spotify_id (spotify_id) WHERE spotify_id IS NOT NULL, idx_tracks_spotify_release_date (spotify_release_date) WHERE spotify_release_date IS NOT NULL

`release_type` mirrors `clouder_albums.release_type` of the track's parent album (copied on Spotify enrichment). `is_ai_suspected` set via `ai_search_results` propagation.

`spotify_release_date` is added in `20260428_15_triage` and used by spec-D R4 classification at `POST /triage/blocks` time:
- NULL → UNCLASSIFIED
- < `date_from` → OLD
- otherwise + `release_type = 'compilation'` → NOT
- else → NEW

### 1.10 clouder_track_artists

Junction table for track-artist relationships with role.

| Column    | Type        | Constraints                         |
|-----------|-------------|-------------------------------------|
| track_id  | String(36)  | PK (composite), FK -> clouder_tracks.id  |
| artist_id | String(36)  | PK (composite), FK -> clouder_artists.id |
| role      | String(32)  | PK (composite), default='main'      |

**PK:** (track_id, artist_id, role)

### 1.11 identity_map

Maps external source entities to canonicalized Clouder entities.

| Column              | Type           | Constraints              |
|---------------------|----------------|--------------------------|
| source              | String(32)     | PK (composite)           |
| entity_type         | String(32)     | PK (composite)           |
| external_id         | String(64)     | PK (composite)           |
| clouder_entity_type | String(32)     | NOT NULL                 |
| clouder_id          | String(36)     | NOT NULL                 |
| match_type          | String(32)     | NOT NULL                 |
| confidence          | Numeric(4,3)   | NOT NULL                 |
| first_seen_at       | DateTime(tz)   | NOT NULL                 |
| last_seen_at        | DateTime(tz)   | NOT NULL                 |

**PK:** (source, entity_type, external_id)
**Indexes:** idx_identity_map_clouder (clouder_entity_type, clouder_id)

### 1.12 ai_search_results

AI-powered search results for entities.

| Column         | Type           | Constraints              |
|----------------|----------------|--------------------------|
| id             | String(36)     | PK (UUID)                |
| entity_type    | String(32)     | NOT NULL                 |
| entity_id      | String(36)     | NOT NULL                 |
| prompt_slug    | String(64)     | NOT NULL                 |
| prompt_version | String(16)     | NOT NULL                 |
| result         | JSONB          | NOT NULL                 |
| searched_at    | DateTime(tz)   | NOT NULL                 |

**Indexes:** uq_search_result (entity_type, entity_id, prompt_slug, prompt_version) UNIQUE

### 1.13 vendor_track_map

Per-vendor match cache for canonical tracks.

| Column           | Type         | Constraints                                |
|------------------|--------------|--------------------------------------------|
| clouder_track_id | String(36)   | PK (composite), FK `clouder_tracks.id`     |
| vendor           | String(32)   | PK (composite)                             |
| vendor_track_id  | String(128)  | NOT NULL                                   |
| match_type       | String(32)   | NOT NULL (`isrc` / `fuzzy` / `manual`)     |
| confidence       | Numeric(4,3) | NOT NULL                                   |
| matched_at       | DateTime(tz) | NOT NULL                                   |
| payload          | JSONB        | NOT NULL                                   |

**PK:** (clouder_track_id, vendor)
**Indexes:** idx_vtm_vendor_track (vendor, clouder_track_id)

### 1.14 match_review_queue

Low-confidence matches parked for manual approval.

| Column           | Type         | Constraints                                      |
|------------------|--------------|--------------------------------------------------|
| id               | String(36)   | PK (UUID)                                        |
| clouder_track_id | String(36)   | NOT NULL, FK `clouder_tracks.id`                 |
| vendor           | String(32)   | NOT NULL                                         |
| candidates       | JSONB        | NOT NULL                                         |
| status           | String(32)   | NOT NULL (`pending` / `approved` / `rejected`)   |
| created_at       | DateTime(tz) | NOT NULL                                         |
| resolved_at      | DateTime(tz) | nullable                                         |

**Indexes:** uq_review_pending (clouder_track_id, vendor) UNIQUE WHERE status='pending'

### 1.15 categories

User-curation Layer 1 — permanent per-(user, style) track libraries (spec-C).

| Column          | Type           | Constraints                                                |
|-----------------|----------------|------------------------------------------------------------|
| id              | String(36)     | PK (UUID)                                                  |
| user_id         | String(36)     | NOT NULL, FK -> users.id                                   |
| style_id        | String(36)     | NOT NULL, FK -> clouder_styles.id                          |
| name            | Text           | NOT NULL (display)                                         |
| normalized_name | Text           | NOT NULL (lower + trim + collapsed whitespace)             |
| position        | Integer        | NOT NULL, default=0                                        |
| created_at      | DateTime(tz)   | NOT NULL                                                   |
| updated_at      | DateTime(tz)   | NOT NULL                                                   |
| deleted_at      | DateTime(tz)   | nullable (soft-delete)                                     |

**Indexes:**
- `uq_categories_user_style_normname` UNIQUE (user_id, style_id, normalized_name) WHERE deleted_at IS NULL
- `idx_categories_user_style_position` (user_id, style_id, position) WHERE deleted_at IS NULL
- `idx_categories_user_created` (user_id, created_at DESC) WHERE deleted_at IS NULL

`position` is user-controlled via `PUT /styles/{style_id}/categories/order` (full-list replace). New categories are appended at `MAX(position) + 1` within `(user_id, style_id, deleted_at IS NULL)`.

### 1.16 category_tracks

Membership of canonical tracks in user categories.

| Column                  | Type         | Constraints                                                |
|-------------------------|--------------|------------------------------------------------------------|
| category_id             | String(36)   | PK (composite), FK -> categories.id                        |
| track_id                | String(36)   | PK (composite), FK -> clouder_tracks.id                    |
| added_at                | DateTime(tz) | NOT NULL                                                   |
| source_triage_block_id  | String(36)   | nullable; FK added by spec-D (ON DELETE SET NULL)          |

**PK:** (category_id, track_id) — UNIQUE makes add idempotent (`ON CONFLICT DO NOTHING`).

**Indexes:**
- `idx_category_tracks_category_added` (category_id, added_at DESC, track_id)

`source_triage_block_id` is NULL for direct adds via `POST /categories/{id}/tracks` and set by spec-D's triage finalize. The FK to `triage_blocks(id)` is added in spec-D's migration `20260428_15_triage` with `ON DELETE SET NULL`.

### 1.17 triage_blocks

User triage sessions. Per-(user, style, date-range) working space for
sorting newly-ingested releases before promoting them into categories.

| Column        | Type           | Constraints                                  |
|---------------|----------------|----------------------------------------------|
| id            | String(36)     | PK (UUID)                                    |
| user_id       | String(36)     | NOT NULL, FK -> users.id                     |
| style_id      | String(36)     | NOT NULL, FK -> clouder_styles.id            |
| name          | Text           | NOT NULL                                     |
| date_from     | Date           | NOT NULL                                     |
| date_to       | Date           | NOT NULL, CHECK date_to >= date_from         |
| status        | String(16)     | NOT NULL, default 'IN_PROGRESS', CHECK in (...)|
| created_at    | DateTime(tz)   | NOT NULL                                     |
| updated_at    | DateTime(tz)   | NOT NULL                                     |
| finalized_at  | DateTime(tz)   | nullable; set on flip to FINALIZED           |
| deleted_at    | DateTime(tz)   | nullable                                     |

**Indexes:**
- `idx_triage_blocks_user_style_status` (user_id, style_id, status) WHERE deleted_at IS NULL
- `idx_triage_blocks_user_created` (user_id, created_at DESC) WHERE deleted_at IS NULL

State: only `IN_PROGRESS → FINALIZED`. No re-open. Soft-delete via `deleted_at`
column orthogonal to status. Overlapping date windows allowed for the same
(user_id, style_id, IN_PROGRESS); no EXCLUSION constraint.

### 1.18 triage_buckets

Buckets within a triage block. Five technical bucket types per block plus
N staging buckets (one per alive category in the style at create time).

| Column           | Type        | Constraints                                                |
|------------------|-------------|------------------------------------------------------------|
| id               | String(36)  | PK (UUID)                                                  |
| triage_block_id  | String(36)  | NOT NULL, FK -> triage_blocks.id ON DELETE CASCADE         |
| bucket_type      | String(16)  | NOT NULL, CHECK in ('NEW','OLD','NOT','DISCARD','UNCLASSIFIED','STAGING') |
| category_id      | String(36)  | nullable, FK -> categories.id ON DELETE RESTRICT           |
| inactive         | Boolean     | NOT NULL, default FALSE                                    |
| created_at       | DateTime(tz)| NOT NULL                                                   |

**Indexes / constraints:**
- CHECK `(bucket_type = 'STAGING') = (category_id IS NOT NULL)`
- `uq_triage_buckets_block_category` UNIQUE (triage_block_id, category_id) WHERE category_id IS NOT NULL
- `uq_triage_buckets_block_type_tech` UNIQUE (triage_block_id, bucket_type) WHERE bucket_type <> 'STAGING'
- `idx_triage_buckets_block` (triage_block_id)
- `idx_triage_buckets_category` (category_id) WHERE category_id IS NOT NULL

`inactive=true` is set by spec-D D8 when the linked category is soft-deleted;
finalize blocks if any inactive STAGING bucket holds tracks. FK to categories
uses `ON DELETE RESTRICT` rather than `SET NULL` because nulling
`category_id` on a STAGING bucket would violate the staging-coupling CHECK.

### 1.19 triage_bucket_tracks

Track membership inside a triage bucket. Idempotent on conflict.

| Column            | Type        | Constraints                                            |
|-------------------|-------------|--------------------------------------------------------|
| triage_bucket_id  | String(36)  | PK (composite), FK -> triage_buckets.id ON DELETE CASCADE |
| track_id          | String(36)  | PK (composite), FK -> clouder_tracks.id                |
| added_at          | DateTime(tz)| NOT NULL                                               |

**PK:** (triage_bucket_id, track_id) — UNIQUE makes move/transfer idempotent.

**Indexes:**
- `idx_triage_bucket_tracks_bucket_added` (triage_bucket_id, added_at DESC, track_id)

---

## 2. Entity Relationships (ER)

```
clouder_labels                        clouder_styles
    |                                     |
    | 1:N (label_id)                      | 1:N (style_id)
    v                                     v
clouder_albums                        clouder_tracks ----N:M----> clouder_artists
    |                                     ^            (clouder_track_artists)
    | 1:N (album_id)                      |
    +-------------------------------------+

source_entities ----> ingest_runs  (last_run_id)
source_relations ---> ingest_runs  (last_run_id)

identity_map: (source, entity_type, external_id) --> (clouder_entity_type, clouder_id)
```

---

## 3. Domain Models (frozen dataclasses)

Source: `src/collector/models.py`

### Enums

| Enum              | Values                                           |
|-------------------|--------------------------------------------------|
| RunStatus         | RAW_SAVED, COMPLETED, FAILED                     |
| ProcessingStatus  | QUEUED, FAILED_TO_QUEUE                           |
| ProcessingOutcome | ENQUEUED, DISABLED, ENQUEUE_FAILED                |
| ProcessingReason  | config_disabled, queue_missing, enqueue_exception |
| EntityType        | track, artist, album, label, style                |
| RelationType      | track_artist, track_album, album_label, track_style |

### Normalized entities (from Beatport)

| Model            | Key Fields                                                          |
|------------------|---------------------------------------------------------------------|
| NormalizedArtist  | bp_artist_id: int, name, normalized_name, payload                  |
| NormalizedLabel   | bp_label_id: int, name, normalized_name, payload                   |
| NormalizedStyle   | bp_genre_id: int, name, normalized_name, payload                   |
| NormalizedAlbum   | bp_release_id: int, title, normalized_title, release_date, bp_label_id, payload |
| NormalizedTrack   | bp_track_id: int, title, normalized_title, mix_name, isrc, bpm, length_ms, publish_date, bp_release_id, bp_genre_id, bp_artist_ids: tuple[int, ...], payload |

### NormalizedBundle

Source: `src/collector/normalize.py`

| Field      | Type                          |
|------------|-------------------------------|
| artists    | tuple[NormalizedArtist, ...]   |
| labels     | tuple[NormalizedLabel, ...]    |
| styles     | tuple[NormalizedStyle, ...]    |
| albums     | tuple[NormalizedAlbum, ...]    |
| tracks     | tuple[NormalizedTrack, ...]    |
| relations  | tuple[NormalizedRelation, ...] |

### NormalizedRelation

| Field            | Type |
|------------------|------|
| from_entity_type | str  |
| from_external_id | str  |
| relation_type    | str  |
| to_entity_type   | str  |
| to_external_id   | str  |

### CanonicalizationResult

| Field            | Type |
|------------------|------|
| run_id           | str  |
| tracks_total     | int  |
| tracks_processed | int  |
| artists_total    | int  |
| labels_total     | int  |
| albums_total     | int  |
| styles_total     | int  |

---

## 4. API Schemas (Pydantic)

Source: `src/collector/schemas.py`

### CollectRequestIn (POST /collect_bp_releases)

| Field              | Type          | Constraints            |
|--------------------|---------------|------------------------|
| bp_token           | str           | min_length=1           |
| style_id           | StrictInt     | > 0                    |
| iso_year           | StrictInt     | 2000..2100             |
| iso_week           | StrictInt     | 1..53                  |
| search_label_count | StrictInt?    | 1..200, optional       |

### CanonicalizationMessage (SQS)

| Field      | Type     | Default     |
|------------|----------|-------------|
| run_id     | str      |             |
| source     | str      | "beatport"  |
| s3_key     | str      |             |
| style_id   | int?     | None        |
| iso_year   | int?     | None        |
| iso_week   | int?     | None        |
| attempt    | int      | 1           |

### MigrationCommand (SQS)

| Field    | Type | Default   |
|----------|------|-----------|
| action   | str  | "upgrade" |
| revision | str  | "head"    |

### LabelSearchMessage (SQS)

| Field          | Type | Default      |
|----------------|------|--------------|
| label_id       | str  |              |
| label_name     | str  |              |
| styles         | str  |              |
| prompt_slug    | str  | "label_info" |
| prompt_version | str  | "v1"         |

### SpotifySearchMessage (SQS)

| Field      | Type | Default |
|------------|------|---------|
| batch_size | int  | 2000    |

---

## 5. AI Search Schemas

Source: `src/collector/search/schemas.py`

### Enums

| Enum             | Values                                              |
|------------------|-----------------------------------------------------|
| LabelSize        | unknown, micro, small, medium, large, major          |
| LabelAge         | unknown, new, young, established, veteran            |
| AIContentStatus  | unknown, none_detected, suspected, confirmed         |

### LabelSearchResult (structured AI response)

| Field             | Type             | Description                        |
|-------------------|------------------|------------------------------------|
| label_name        | str              | Official label name                |
| style             | str              | Queried music genre                |
| size              | LabelSize        | Label size in the industry         |
| size_details      | str              | Details: release count, roster size|
| age               | LabelAge         | Label maturity                     |
| founded_year      | int?             | Year founded                       |
| age_details       | str              | Label history details              |
| ai_content        | AIContentStatus  | AI-generated content on label      |
| ai_content_details| str              | Details about AI content findings  |
| country           | str?             | Country of origin                  |
| website           | str?             | Official website                   |
| notable_artists   | list[str]        | Notable artists on the label       |
| summary           | str              | Overall summary                    |
| confidence        | float (0..1)     | Data accuracy confidence           |
| sources           | list[str]        | Source URLs/references              |

---

## 6. Repository Commands (frozen dataclasses)

Source: `src/collector/repositories.py`

| Command                     | Key Fields                                                    |
|-----------------------------|---------------------------------------------------------------|
| CreateIngestRunCmd          | run_id, source, style_id, iso_year, iso_week, raw_s3_key, status, item_count, meta, started_at |
| UpsertSourceEntityCmd       | source, entity_type, external_id, name, normalized_name, payload, payload_hash, last_run_id, observed_at |
| UpsertSourceRelationCmd     | source, from_entity_type, from_external_id, relation_type, to_entity_type, to_external_id, last_run_id |
| UpsertIdentityCmd           | source, entity_type, external_id, clouder_entity_type, clouder_id, match_type, confidence: Decimal, observed_at |
| CreateTrackCmd              | track_id, title, normalized_title, mix_name, isrc, bpm, length_ms, publish_date, album_id, style_id, at |
| ConservativeUpdateTrackCmd  | track_id, mix_name, isrc, bpm, length_ms, publish_date, album_id, style_id, at |
| UpsertTrackArtistCmd        | track_id, artist_id, role="main" |
| UpdateSpotifyResultCmd      | track_id, spotify_id (nullable), searched_at, release_type (nullable) |
| IdentityMapEntry (read)     | clouder_entity_type, clouder_id |

### EnqueueResult

Source: `src/collector/handler.py`

| Field              | Type              |
|--------------------|-------------------|
| processing_status  | ProcessingStatus  |
| processing_outcome | ProcessingOutcome |
| processing_reason  | ProcessingReason? |

---

## 7. Error Models

Source: `src/collector/errors.py`

| Error class              | status_code | error_code            |
|--------------------------|-------------|-----------------------|
| AppError (base)          | variable    | variable              |
| ValidationError          | 400         | validation_error      |
| UpstreamAuthError        | 403         | beatport_auth_failed  |
| UpstreamUnavailableError | 502        | beatport_unavailable  |
| SpotifyAuthError         | 403         | spotify_auth_failed   |
| SpotifyUnavailableError  | 502         | spotify_unavailable   |
| StorageError             | 500         | storage_error         |

---

## 8. Data Flow

```
Beatport API
    |
    v
[1] Collector Lambda (POST /collect_bp_releases)
    - Fetches releases for a given week/style
    - Saves raw JSON to S3
    - Creates IngestRun (status=RAW_SAVED)
    - Sends CanonicalizationMessage to SQS
    |
    v
[2] Canonicalization Worker (SQS consumer)
    - Reads raw JSON from S3
    - Normalizes into NormalizedBundle
    - Upserts into source_entities, source_relations
    - Canonicalizes into clouder_* tables
    - Creates identity_map entries
    - Updates IngestRun (status=COMPLETED)
    - Sends LabelSearchMessage to SQS (optional)
    - Sends SpotifySearchMessage to SQS (optional)
    |
    +---> [3] AI Search Worker (SQS consumer)
    |         - Searches for label information via Perplexity API
    |         - Saves LabelSearchResult into ai_search_results
    |         - Propagates ai_content → clouder_<entity>.is_ai_suspected
    |           (only when confidence ≥ AI_FLAG_CONFIDENCE_THRESHOLD)
    |
    +---> [4] Spotify Search Worker (SQS consumer)
              - Loads tracks with ISRC but without spotify_searched_at
              - Searches Spotify Web API by ISRC
              - Saves batch results to S3 (raw/sp/tracks/)
              - Upserts source_entities (source=spotify) + identity_map
              - Updates clouder_tracks: spotify_id + spotify_searched_at
                + release_type (from album.album_type)
              - Propagates release_type onto parent clouder_albums
    |
    v
[5] Read API
    - GET /tracks, /artists, /albums, /labels, /styles
    - GET /tracks/spotify-not-found (tracks searched but not matched)
```

---

## 9. Infrastructure

- **DB:** Aurora PostgreSQL 16.6 Serverless v2 (0-2 ACU), database: "clouder"
- **Storage:** S3 bucket, prefixes: raw/bp/releases, raw/sp/tracks
- **Compute:** AWS Lambda (collector, worker, migration, ai_search, spotify_search)
- **Queues:** SQS (canonicalization, ai_search, spotify_search)
- **API:** HTTP API Gateway
- **Migrations:** Alembic

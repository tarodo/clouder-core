# Clouder Core - Data Model

> Current project data model. Date: 2026-03-14

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
| created_at      | DateTime(tz)       | NOT NULL                 |
| updated_at      | DateTime(tz)       | NOT NULL                 |

### 1.5 clouder_labels

Canonicalized record labels.

| Column          | Type               | Constraints              |
|-----------------|--------------------|--------------------------|
| id              | String(36)         | PK (UUID)                |
| name            | Text               | NOT NULL                 |
| normalized_name | Text               | NOT NULL                 |
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
| created_at       | DateTime(tz)      | NOT NULL                 |
| updated_at       | DateTime(tz)      | NOT NULL                 |

**Indexes:** idx_album_match (normalized_title, release_date, label_id)

### 1.9 clouder_tracks

Canonicalized tracks.

| Column           | Type              | Constraints              |
|------------------|-------------------|--------------------------|
| id               | String(36)        | PK (UUID)                |
| title            | Text              | NOT NULL                 |
| normalized_title | Text              | NOT NULL                 |
| mix_name         | Text              | nullable                 |
| isrc             | String(64)        | nullable                 |
| bpm              | Integer           | nullable                 |
| length_ms        | Integer           | nullable                 |
| publish_date     | Date              | nullable                 |
| album_id         | String(36)        | nullable, FK -> clouder_albums.id |
| style_id         | String(36)        | nullable, FK -> clouder_styles.id |
| created_at       | DateTime(tz)      | NOT NULL                 |
| updated_at       | DateTime(tz)      | NOT NULL                 |

**Indexes:** idx_tracks_isrc (isrc) WHERE isrc IS NOT NULL

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

| Error class            | status_code | error_code            |
|------------------------|-------------|-----------------------|
| AppError (base)        | variable    | variable              |
| ValidationError        | 400         | validation_error      |
| UpstreamAuthError      | 403         | beatport_auth_failed  |
| UpstreamUnavailableError | 502       | beatport_unavailable  |
| StorageError           | 500         | storage_error         |

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
    |
    v
[3] AI Search Worker (SQS consumer)
    - Searches for label information via Perplexity API
    - Saves LabelSearchResult into ai_search_results
    |
    v
[4] Read API (GET /tracks, /artists, /albums, /labels, /styles)
    - Reads canonicalized data with joins
```

---

## 9. Infrastructure

- **DB:** Aurora PostgreSQL 16.6 Serverless v2 (0-2 ACU), database: "clouder"
- **Storage:** S3 bucket, prefix: raw/bp/releases
- **Compute:** AWS Lambda (collector, worker, migration, search)
- **Queues:** SQS (canonicalization, ai_search)
- **API:** HTTP API Gateway
- **Migrations:** Alembic

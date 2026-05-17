# Canonicalization

The canonicalization worker converts raw Beatport track objects (stored in S3) into vendor-neutral canonical entities in Aurora. It is triggered by an SQS message sent by the ingest handler after a successful S3 write.

Source files:
- `src/collector/worker_handler.py` — SQS entry point
- `src/collector/normalize.py` — raw JSON → typed `NormalizedBundle`
- `src/collector/canonicalize.py` — `NormalizedBundle` → `clouder_*` upserts

---

## From raw to canonical

### Phase 1 — normalize

`normalize.py:normalize_tracks(raw_tracks)` iterates raw Beatport track objects and extracts de-duplicated, typed entities.

Output: `NormalizedBundle`

```python
@dataclass(frozen=True)
class NormalizedBundle:
    artists: tuple[NormalizedArtist, ...]
    labels:  tuple[NormalizedLabel, ...]
    styles:  tuple[NormalizedStyle, ...]
    albums:  tuple[NormalizedAlbum, ...]
    tracks:  tuple[NormalizedTrack, ...]
    relations: tuple[NormalizedRelation, ...]
```

Each `Normalized*` dataclass carries the source ID (e.g. `bp_artist_id: int`), the display name, `normalized_name` (lower + trim + collapsed whitespace via `models.normalize_text`), and the original `payload` dict.

`NormalizedRelation` encodes entity-to-entity edges: `track_artist`, `track_album`, `album_label`, `track_style`. Relations are de-duplicated within the bundle.

Tracks with a missing or non-positive `id` or missing `name` are silently skipped.

### Phase 2 — canonicalize

`canonicalize.py:Canonicalizer.process_run(run_id, bundle)` executes six sequential phases, each in its own Data API transaction:

1. **labels** → upsert `source_entities` + resolve/create `clouder_labels` + upsert `identity_map`
2. **styles** → same pattern for `clouder_styles`
3. **artists** → same pattern for `clouder_artists`
4. **albums** → depends on `label_ids` map from phase 1
5. **relations** → bulk upsert `source_relations` (no canonical resolution needed)
6. **tracks** → depends on `artist_ids`, `album_ids`, `style_ids`; processed in chunks of 200

Each `_resolve_*` method follows the same pattern:
1. Call `find_identity(source, entity_type, external_id, transaction_id=...)`.
2. On hit → return existing `clouder_id`; for tracks, apply `ConservativeUpdateTrackCmd` to fill in any newly-present nullable fields without overwriting set values.
3. On miss → generate a new UUID, create the canonical row, queue an `UpsertIdentityCmd` (confidence=0.600, match_type=`auto_create`).

Track chunks are used to keep individual Data API payloads below the 1 MB limit. Each chunk is its own transaction.

---

## identity_map

The `identity_map` table is the translation layer between external source IDs and canonical CLOUDER UUIDs.

**Write path**: `Canonicalizer` calls `repository.batch_upsert_identities([UpsertIdentityCmd(...)])` inside the same transaction as the canonical row creation. The upsert is `ON CONFLICT DO UPDATE SET last_seen_at = ...`, so re-processing the same run is idempotent.

**Read path**: `repository.find_identity(source, entity_type, external_id, transaction_id=)`.

Critical: `transaction_id` must be passed when called inside an active `repository.transaction()` context. The RDS Data API does not share connection state across calls; without `transaction_id`, the read goes to a separate connection and misses rows written in the current in-flight transaction. This causes duplicated canonical entities on concurrent or re-processed runs. See `docs/backend/data-api.md` for the Data API transaction model.

Match types written by the canonicalizer:
- `auto_create` (confidence=0.600) — no prior identity found; new canonical entity created.
- `isrc_match` (confidence=1.000) — Spotify lookup matched via ISRC; written by `spotify_handler.py`.

---

## release_type propagation

`release_type` is absent from Beatport payloads. Values (`album`, `single`, `compilation`) are sourced exclusively from Spotify's `album.album_type` field during ISRC enrichment. See ADR-0007.

**Write path**:
1. `spotify_handler.py:_extract_album_type(spotify_track)` pulls `album.album_type` from the matched Spotify track object.
2. `UpdateSpotifyResultCmd(track_id, spotify_id, searched_at, release_type)` updates `clouder_tracks.release_type`.
3. After updating tracks, the handler calls `propagate_release_type_to_albums`, which copies the `release_type` value from `clouder_tracks` to the parent `clouder_albums` row.

A track's `release_type` is NULL until its ISRC lookup succeeds. A track that is searched but not found on Spotify has `spotify_searched_at IS NOT NULL` and `release_type` remains NULL.

---

## is_ai_suspected propagation

`is_ai_suspected` is a soft flag on `clouder_labels`, `clouder_artists`, and `clouder_tracks`. It is not authoritative — the source of truth is `ai_search_results.result`. See ADR-0008.

**Write path**: `search_handler.py:propagate_ai_flag` is called after saving an `ai_search_results` row.

Rules (source: `src/collector/search_handler.py:propagate_ai_flag`):

```python
def propagate_ai_flag(repository, *, entity_type, entity_id, result, threshold):
    if result.confidence < threshold:
        return                                                    # too weak → no-op
    if result.ai_content in (SUSPECTED, CONFIRMED):
        repository.update_entity_is_ai_suspected(entity_type, entity_id, True)
    elif result.ai_content == NONE_DETECTED:
        repository.update_entity_is_ai_suspected(entity_type, entity_id, False)  # explicit clear
    # ai_content == UNKNOWN → no-op
```

`threshold` defaults to `0.6` (`AI_FLAG_CONFIDENCE_THRESHOLD` env var on the `beatport-prod-ai-search-worker` Lambda).

`ai_content=unknown` is always a no-op regardless of confidence. `none_detected` with confidence ≥ threshold explicitly clears the flag (sets to `false`).

The flag can be set on labels, artists, or tracks depending on which entity type the Perplexity prompt targets. Current production prompts target labels (`entity_type='label'`). Artist and track-level propagation uses the same function but is triggered by artist-specific prompt slugs when enabled.

To verify the current flag status, query Aurora directly (the `GET /labels` API does not project `is_ai_suspected`):

```sql
SELECT COUNT(*) FROM clouder_labels WHERE is_ai_suspected = true;
SELECT id, name, is_ai_suspected FROM clouder_labels WHERE is_ai_suspected = true LIMIT 20;
```

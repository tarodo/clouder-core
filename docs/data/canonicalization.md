# Canonicalization

The canonicalization worker converts raw Beatport track objects (stored in S3) into vendor-neutral canonical entities in Aurora. It is triggered by an SQS message sent by the ingest handler after a successful S3 write.

Source files:
- `src/collector/worker_handler.py` — SQS entry point
- `src/collector/normalize.py` — raw JSON → typed `NormalizedBundle`
- `src/collector/canonicalize.py` — `NormalizedBundle` → `clouder_*` upserts

---

## From raw to canonical

### Phase 0 — screen

`contracts.screen_run` checks the run against the raw data contract ([`contracts.md`](contracts.md)): records without a positive `id` or a `name` are quarantined to `raw/bp/releases/_quarantine/run_id=<run_id>/` with their reasons, drift (unknown, missing, re-typed or emptied fields) is logged as `contract_drift`. Only the valid records reach normalize.

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

Each phase resolves identities set-based (ADR-0022):
1. `claim_identities` — one batch inserting a candidate UUID for every external id, `ON CONFLICT DO NOTHING`.
2. `find_identities` — one `IN (...)` lookup (500 ids per statement) returning the winning `clouder_id`s.
3. Candidates that won are new → one batch creates their canonical rows (confidence=0.600, match_type=`auto_create`). The rest already existed (or were claimed by a concurrent run) → for tracks, `read_track_state` reads the current mergeable columns, `track_update` decides what changes, and only changed tracks go into one batched `ConservativeUpdateTrackCmd` update (see "Replays and dry runs").

A phase therefore costs a handful of Data API calls regardless of entity count (`docs/benchmarks/canonicalization.md`).

Track chunks are used to keep individual Data API payloads below the 1 MB limit. Each chunk is its own transaction.

### Replays and dry runs

A run can be canonicalized again from its raw object (ADR-0024, [`docs/ops/backfill.md`](../ops/backfill.md)). Three rules make that safe:

- **Observation time.** `process_run(run_id, bundle, observed_at)` takes the time Beatport was read — `ingest_runs.started_at`, looked up by the worker and passed by the backfill. It stamps `source_entities` and `identity_map` (`first_seen_at`, `last_seen_at`); canonical rows' `created_at`/`updated_at` stay the processing time.
- **Guarded source upsert.** `batch_upsert_source_entities` updates a row only `WHERE source_entities.last_run_id = EXCLUDED.last_run_id OR source_entities.last_seen_at <= EXCLUDED.last_seen_at`: an older observation from another run never overwrites a newer one, and the same run always re-applies.
- **Stale tracks fill gaps only.** A track whose stored observation is newer and from another run is stale for this run (`read_track_state` computes the same condition). A canonical track fed by several Beatport ids — the canonicalizer of 2026-03-01..08 merged tracks by ISRC (`match_type = heuristic`), e.g. an EP track and the same recording on a compilation — takes its values from the newest observation among them (within one run the larger Beatport id wins); its other sources are stale for it. A fresh observation overwrites each field it carries; a stale one only fills NULLs. Unchanged tracks are not updated, so `updated_at` moves only on a real change.

`process_run` returns, besides totals, `labels_created`, `styles_created`, `artists_created`, `albums_created`, `tracks_created`, `tracks_changed`, `tracks_stale` and `track_field_changes`.

`Canonicalizer(repo, dry_run=True)` runs the same phases against a read-only view of the repository: `find_identities` and `read_track_state` pass through, every other call is dropped, no transaction is opened, and ids without an identity are counted as would-be creations.

---

## identity_map

The `identity_map` table is the translation layer between external source IDs and canonical CLOUDER UUIDs.

**Write path**: `Canonicalizer` calls `repository.claim_identities([UpsertIdentityCmd(...)])` at the start of each phase, inside the same transaction as the canonical row creation. The insert is `ON CONFLICT DO NOTHING`: an existing identity always wins, so re-processing a run is idempotent and a concurrent run that claimed an id first keeps it.

**Read path**: `repository.find_identities(source, entity_type, external_ids, transaction_id=)` → `{external_id: clouder_id}`.

Critical: `transaction_id` must be passed when called inside an active `repository.transaction()` context. The RDS Data API does not share connection state across calls; without `transaction_id`, the read goes to a separate connection and misses rows written in the current in-flight transaction — including the identities the phase just claimed — so the claimed ids do not resolve and the canonicalizer raises, rolling the phase back. See `docs/backend/data-api.md` for the Data API transaction model.

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

`threshold` defaults to `0.6` (`AI_FLAG_CONFIDENCE_THRESHOLD`, set on the `clouder-prod-label-enricher-worker` and `clouder-prod-artist-enricher-worker` Lambdas — see `infra/lambda.tf`).

`ai_content=unknown` is always a no-op regardless of confidence. `none_detected` with confidence ≥ threshold explicitly clears the flag (sets to `false`).

The flag can be set on labels, artists, or tracks depending on which entity type the Perplexity prompt targets. Current production prompts target labels (`entity_type='label'`). Artist and track-level propagation uses the same function but is triggered by artist-specific prompt slugs when enabled.

To verify the current flag status, query Aurora directly (the `GET /labels` API does not project `is_ai_suspected`):

```sql
SELECT COUNT(*) FROM clouder_labels WHERE is_ai_suspected = true;
SELECT id, name, is_ai_suspected FROM clouder_labels WHERE is_ai_suspected = true LIMIT 20;
```

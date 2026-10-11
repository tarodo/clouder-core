# Data

Canonical schema, raw ingestion, transforms, search and enrichment.

- [Data model](data-model.md) — canonical entities, triage tables, identity map.
- [Migrations](migrations.md) — alembic, packaging rename, migration Lambda.
- [Raw ingestion](raw-ingestion.md) — Beatport API → S3 layout, `ingest_runs` state machine, Saturday-week.
- [Auto-ingest](auto-ingest.md) — scheduled Beatport login + ingest: due weeks first, then an even backfill; admin-configured schedule.
- [Canonicalization](canonicalization.md) — normalize → canonical, identity map, propagation rules.
- [Data quality](data-quality.md) — nightly checks, SLOs, alarm.
- [Raw data contract](contracts.md) — the Beatport record contract, quarantine, drift alarms.
- [Lakehouse](lakehouse.md) — dbt + Iceberg silver/gold, SCD2 track history, nightly build.
- [Entity resolution](entity-resolution.md) — identity map, ISRC and fuzzy matching, review queue, measured matcher quality.
- [Search and enrichment](search-and-enrichment.md) — Spotify ISRC + metadata fallback, YouTube Music matching, vendor-match cache, LLM label/artist research.

## Lineage, Aurora side

```text
Beatport API
  │ auto-ingest / admin ingest            ingest_runs(run_id, style_id, week_year, week_number, raw_s3_key)
  ▼
s3 raw/bp/releases/style_id=/year=/week=/releases.json.gz   (raw_s3_key)
  │ contract screen (contracts.py) ──▶ raw/bp/releases/_quarantine/run_id=<run_id>/
  ▼
source_entities(source, entity_type, external_id, last_run_id)  ·  source_relations(from_*, to_*, last_run_id)
  │ canonicalize.py, set-based
  ▼
identity_map(source, entity_type, external_id → clouder_entity_type, clouder_id, match_type, confidence)
  ▼
clouder_tracks / clouder_artists / clouder_albums / clouder_labels / clouder_track_artists / clouder_styles   (id = clouder_id)
  ├─▶ vendor_track_map(clouder_track_id, vendor → vendor_track_id, match_type, confidence) · match_review_queue
  ├─▶ per-user overlay: categories → category_tracks(category_id, track_id), triage_*, playlists
  └─▶ catalog export (nightly) → bronze/catalog_export/snapshot_dt=/<table>/ → silver.dim_track_history(track_id, valid_from) → gold.fct_play
```

Every Beatport-origin canonical row traces back to the latest raw object that carried it: `identity_map` → `source_entities.last_run_id` → `ingest_runs.raw_s3_key` (rows imported from users' Spotify playlists have no raw object). The lake side is in the [dbt lineage](https://tarodo.github.io/clouder-core/lineage/).

See also [`docs/architecture.md`](../architecture.md), [`docs/adr/`](../adr/).

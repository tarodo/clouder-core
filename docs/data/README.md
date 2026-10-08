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

See also [`docs/architecture.md`](../architecture.md), [`docs/adr/`](../adr/).

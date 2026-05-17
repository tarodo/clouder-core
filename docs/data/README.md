# Data

Canonical schema, raw ingestion, transforms, search and enrichment.

- [Data model](data-model.md) — canonical entities, triage tables, identity map.
- [Migrations](migrations.md) — alembic, packaging rename, migration Lambda.
- [Raw ingestion](raw-ingestion.md) — Beatport API → S3 layout, `ingest_runs` state machine, Saturday-week.
- [Canonicalization](canonicalization.md) — normalize → canonical, identity map, propagation rules.
- [Search and enrichment](search-and-enrichment.md) — Spotify ISRC + metadata fallback, Perplexity label search, vendor-match cache, AI flag.

See also [`docs/architecture.md`](../architecture.md), [`docs/adr/`](../adr/).

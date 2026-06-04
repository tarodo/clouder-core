# ADR-0017: Artist enrichment mirrors label enrichment (parallel package, not shared engine)
Status: Accepted
Date: 2026-06-04

## Context

Once label enrichment (ADR-0016) shipped, artists needed the same treatment:
per-artist AI-researched info, auto-population on curation, and a full admin + read +
preference API. The `artist_v1` prompt and `ArtistInfo` schema were validated in the
`experiments/artists/` sandbox (PR #148/#149) and are ported into production.

The one structural difference from labels: labels are one-to-many with tracks
(`track.album_id → album.label_id`), while artists are **many-to-many** via
`clouder_track_artists(track_id, artist_id, role)`. All roles (main / feat /
producer / remixer) are enriched, so artist resolution returns a set per track.

## Decision

Approach **A**: a new `src/collector/artist_enrichment/` package that mirrors
`label_enrichment` module-for-module, swapping the entity (`artist_id`, M2M) and the
payload schema (`ArtistInfo`).

- **Rejected alternatives.** (B) Generalizing `label_enrichment` into a shared engine
  — too high a regression risk to working production code. (C) Extracting a thin
  shared base — modest DRY gain for real refactor cost. Generalization is revisited
  only if a third enrichable entity appears.
- **Reuse / port / new.** *Reuse* (import, no copy): `label_enrichment.vendors.*`
  adapters (schema-agnostic `run(system, user, schema, model)`) and `pricing`.
  *Port* from the sandbox: `ArtistInfo` schema/enums, the `artist_v1` prompt, the
  artist-tuned consensus aggregator. *New* (mirror with entity swap): repository,
  auto_repository, orchestrator, messages, routes, settings, handler, worker.
- **Data model** mirrors label: `clouder_artist_enrichment_runs` / `_cells` /
  `clouder_artist_info` (full `ArtistInfo` as JSONB + denormalized status,
  `primary_styles` GIN, artist_type, country, active_since, tagline). FK to
  `clouder_artists.id`, which already carries `is_ai_suspected`.
- **Full parity** with labels: admin backlog/enqueue/auto-config/runs, user
  preferences (like/dislike + "my artists"), AI-flag projection onto
  `clouder_artists.is_ai_suspected`, async SQS worker + auto-dispatch.
- **Frontend** (shipped as sub-project 2, PR #150): parallel artist-prefixed
  components reusing the entity-agnostic pieces (`EnrichConfigForm`, `EnqueueDrawer`,
  `BacklogTable`, the AI-badge markup, the `api<T>()` client, query patterns). The
  one genuinely new component is `ArtistsPanel` (main artist as a full `ArtistTile`
  card + every other artist as a chip) on all three players. A small backend touch
  adds `artists: [{id, name, role}]` to the bucket-tracks response so the triage
  player can resolve artist ids.

## Consequences

- Two near-identical enrichment packages now exist. The duplication is deliberate
  (isolation, zero risk to the working label path); a shared engine is the documented
  escape hatch if a third entity arrives.
- Many-to-many resolution means a track fans out to a set of artists, so artist
  enrichment costs more vendor calls per track than labels.
- Relates to ADR-0016 (the mirrored pattern) and ADR-0008.

**Cross-references:** `../data/search-and-enrichment.md`, `../data/data-model.md`,
`../frontend/features.md`. Source specs (now archived):
`../archive/specs/2026-05-26-artist-search-design.md`,
`../archive/specs/2026-05-27-artist-enrichment-backend-design.md`,
`../archive/specs/2026-05-27-artist-enrichment-frontend-design.md`,
`../archive/specs/2026-05-27-improve-artists-design.md`.

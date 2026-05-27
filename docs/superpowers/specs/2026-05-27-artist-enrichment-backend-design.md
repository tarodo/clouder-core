# Artist Enrichment — Backend + Auto-Dispatch (Design Spec)

**Date:** 2026-05-27
**Status:** Approved for planning
**Sub-project:** 1 of 2 (backend + auto-dispatch). Sub-project 2 = frontend (admin parity UI, Library artists view, player artist panel, preferences UI) — its own spec → plan → implementation cycle.

## Goal

Add production "artist enrichment" to CLOUDER, mirroring the existing label-enrichment subsystem end-to-end on the **server side**: persist per-artist AI-researched info (`ArtistInfo`), populate it automatically when tracks are curated, and expose the full admin + read + preference API surface. The artist prompt (`artist_v1`) and `ArtistInfo` schema were validated in the `experiments/artists/` sandbox (merged via PR #148/#149) and are ported into production here.

## Scope (this sub-project)

Everything server-side:
- DB migration: artist enrichment tables + preferences table.
- `src/collector/artist_enrichment/` package (mirrors `label_enrichment/`).
- Worker Lambda `artist_enrichment_handler` + SQS queue + Terraform infra.
- Auto-dispatch wiring into the existing curation trigger points.
- Full API parity routes + OpenAPI generation + handler dispatch.
- AI-flag projection onto `clouder_artists.is_ai_suspected`.
- User preference routes + table.
- Unit + integration tests.

## Non-goals (deferred to sub-project 2)

- All React/frontend work: enabling the "artists" tab in `AdminAutoEnrichPage`, the artist backlog/enqueue admin UI, the Library artists list (`EntityTabs`), the player `ArtistTile` panel, the AI badge, and the preference UI. Sub-project 2 consumes the endpoints this sub-project ships.

## Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Decomposition | 2 sub-projects (backend+auto, then frontend) | Backend is shippable/testable without UI |
| Architecture | Parallel `artist_enrichment` package mirroring `label_enrichment`; reuse schema-agnostic vendors | Proven pattern, isolation, no refactor of working label code |
| Which artists per track | **All roles** from `clouder_track_artists` (main/feat/producer/remixer) | Maximum coverage; user accepted the cost |
| Admin scope | **Full parity** with labels (backlog + enqueue + auto-config + runs/history) | User request |
| User preferences | **Yes**, mirror labels (like/dislike + "my artists") | User request; backend lives here, UI in sub-project 2 |
| Preference layer placement | Table + routes + OpenAPI in this sub-project | Clean server/client boundary; no orphan migration |

## Architecture

Approach **A**: a new `src/collector/artist_enrichment/` package that mirrors `src/collector/label_enrichment/` module-for-module, swapping the entity (`artist_id`, many-to-many) and the payload schema (`ArtistInfo`). Rejected alternatives: (B) generalizing label_enrichment into a shared engine — high regression risk to working production code; (C) extracting a thin shared base — modest DRY gain for real refactor cost. If a third enrichable entity appears later, revisit generalization.

**Reuse vs. port vs. new:**
- **Reuse (import, no copy):** `label_enrichment.vendors.*` adapters (gemini, openai, tavily_deepseek — schema-agnostic `run(system, user, schema, model)`) and `label_enrichment.vendors.pricing`.
- **Port from `experiments/artists/`:** `ArtistInfo` schema + enums, the `artist_v1` prompt, and the artist-adapted consensus aggregator (field categories already tuned for `ArtistInfo`).
- **New (mirror label module with entity swap):** repository, auto_repository, orchestrator, messages, auto_messages, routes, auto_routes, settings_provider, handler.

**Key artist-vs-label difference:** labels are one-to-many with tracks (`track.album_id → album.label_id`); artists are **many-to-many** via `clouder_track_artists(track_id, artist_id, role)`. So artist resolution returns a set per track. `clouder_artists` already exists (`id, name, normalized_name`) and already carries an `is_ai_suspected` flag.

## Data model (new alembic migration)

Mirror the label enrichment tables with `artist_id` instead of `label_id`. FK target is `clouder_artists.id`.

### `clouder_artist_enrichment_runs`
Columns identical to `clouder_label_enrichment_runs`: `id` (PK), `status` (queued|running|completed), `prompt_slug`, `prompt_version`, `vendors` JSONB, `models` JSONB, `merge_vendor`, `merge_model`, `requested_artists` INT, `cells_total/cells_ok/cells_error` INT, `cost_usd` NUMERIC(10,4), `created_by_user_id`, `created_at/started_at/finished_at`, `source` (manual|auto). Index on `created_at DESC`.

### `clouder_artist_enrichment_cells`
`id` (PK), `run_id` FK→runs, `artist_id` FK→`clouder_artists`, `vendor`, `model`, `status` (ok|error), `parsed` JSONB (the `ArtistInfo` dump), `citations` JSONB, `usage` JSONB, `latency_ms`, `error` JSONB, `created_at`. Unique `(run_id, artist_id, vendor)`. Index `(artist_id, created_at DESC)`.

### `clouder_artist_info`
`artist_id` (PK, FK→`clouder_artists`), `last_run_id` FK→runs, `prompt_slug`, `prompt_version`, `merged` JSONB (full `ArtistInfo`), `provenance` JSONB, `updated_at`.
Denormalized columns (filter/sort/list only — everything else lives in `merged`):
- `ai_content` TEXT, `ai_confidence` NUMERIC(3,2)
- `status` TEXT
- `primary_styles` TEXT[] (GIN index)
- `artist_type` TEXT
- `country` TEXT
- `active_since` INTEGER
- `tagline` TEXT

Indexes: `updated_at DESC`, `status`, GIN on `primary_styles`. (No `city` — available in `merged`; no `activity`/`last_release_date` — not in `ArtistInfo`.)

### `artist_auto_enrich_state`
`artist_id` (PK, FK→`clouder_artists` ON DELETE CASCADE), `attempts` INT, `status` (queued|completed|failed), `last_run_id` FK→runs ON DELETE SET NULL, `first_enqueued_at`, `updated_at`. Index on `status`.

### `auto_enrich_config` (existing table — no schema change)
Add a singleton row `kind="artists"` at runtime via the PUT route. Columns already support it (`kind` PK, `enabled`, `vendors`, `models`, `prompt_slug`, `prompt_version`, `merge_vendor`, `merge_model`, …).

### `user_artist_preferences` (mirror the label preference table)
`user_id`, `artist_id` (FK→`clouder_artists`), `status` (like|dislike), `created_at`, `updated_at`. PK `(user_id, artist_id)`. Mirror the exact column set/constraints of the existing label-preference table (the plan pins it from that migration).

## Package: `src/collector/artist_enrichment/`

Module-for-module mirror of `label_enrichment/`:

| Module | Responsibility |
|---|---|
| `schemas.py` | `ArtistInfo` + `ArtistType`/`AIContentStatus`/`AISignalKind`/`AISignal` (ported from the experiment). |
| `prompts/` | `artist_v1` (ported) + `get_prompt`/`load_builtin_prompts`/`list_prompt_versions`. |
| `aggregator.py` | `merge_cells()` — artist-adapted consensus (ported from the experiment's `aggregate.py`: artist field categories, `bio` in narrative). |
| `repository.py` | Aurora Data API CRUD: `create_run`, `get_run`, `list_runs`, `insert_cell`, `upsert_artist_info`, `increment_run_counters`, `mark_run_running`, `get_artist_by_id`, `upsert_artist_by_name`, `derive_artist_context` (see below), `list_backlog`, plus the artist read queries for `/artists` and `/artists/{id}`. |
| `auto_repository.py` | Config + state: `get_config`/`upsert_config` (`kind="artists"`), `claim_artists`, `attach_run`, `mark_auto_enrich_outcome`, and trigger discovery `artist_ids_for_track` / `artist_ids_for_triage_block` (all roles). |
| `orchestrator.py` | `enrich_artist_for_run()`: derive disambiguation context → mark running → run vendors parallel → insert cells → merge → upsert artist_info → project AI flag → increment counters → auto-state callback. |
| `messages.py` | `ArtistEnrichmentMessage` (SQS: run_id, artist_id, artist_name — the disambiguation context is derived at the worker, not carried in the message), `EnrichArtistsRequestIn`, `EnrichArtistInput`. |
| `auto_messages.py` | `AutoEnrichConfigIn` (artist variant). |
| `routes.py` | `handle_post_enrich`, `handle_get_run`, `handle_list_runs`, `handle_get_options`, `handle_get_backlog`, `handle_get_artist` (admin), `handle_get_history`, user `handle_list_artists`, `handle_get_artist_public`, `handle_put_preference`, `handle_list_my_preferences`. |
| `auto_routes.py` | `handle_get_auto_config`, `handle_put_auto_config`. |
| `settings_provider.py` | Secrets dataclass (reuse SSM env-var names from the label worker). |

`vendors/` and `pricing` are **imported from `label_enrichment.vendors`** — not copied.

`src/collector/artist_enrichment_handler.py` — the SQS worker `lambda_handler`, mirroring `label_enrichment_handler.py` with `ArtistEnrichmentMessage` and `enrich_artist_for_run`.

### Disambiguation context (artist-specific, critical)

Artist names collide heavily — the entire `artist_v1` prompt is built around disambiguation anchors (`sample_tracks` + `known_labels` + `style`), as validated in the experiment. So the worker must feed these into the prompt, not just a style.

Rather than carry them in the SQS message, the orchestrator derives them at enrichment time via `repository.derive_artist_context(artist_id)`, which queries the artist's tracks:
- `sample_tracks`: up to ~3 track titles from `clouder_track_artists → clouder_tracks` for this artist (most recent / representative).
- `known_labels`: the distinct label names of those tracks' albums (`clouder_tracks.album_id → clouder_albums.label_id → clouder_labels.name`).
- `style`: the dominant style across the artist's tracks (the artist analog of `derive_style_for_label`).

The orchestrator passes these to the ported `render_user(prompt, artist_name, style, sample_tracks, known_labels)`. If the artist has no tracks (e.g. a manual enqueue by bare name via `upsert_artist_by_name`), the context is empty and the prompt falls back to a name-only research request — the same no-context path the experiment's `render_user` already handles. Keeping the SQS message lean (`run_id`, `artist_id`, `artist_name`) and deriving context in the worker centralizes the logic and avoids stale/oversized messages.

## Auto-dispatch (requirement 2)

Add artist dispatch **alongside** the existing label dispatch at the same trigger points in `src/collector/curation_handler.py`:
- track added to a category (the `was_new` branch, ~line 574)
- triage block finalized (~line 1343)

A new `artist_enrichment/auto_dispatch.py` provides `try_dispatch_artists_for_track(track_id, user_id)` and `try_dispatch_artists_for_triage_block(block_id, user_id)`, best-effort (swallow exceptions, never block curation). Flow mirrors labels:
1. Read `auto_enrich_config` for `kind="artists"`; if disabled, skip. (Independent toggle from labels.)
2. Resolve artist ids — **all roles** from `clouder_track_artists` (`artist_ids_for_track` / `artist_ids_for_triage_block`).
3. `claim_artists()` atomically (skip artists already in `clouder_artist_info`; retry `failed`/stale-`queued` with `attempts < 2`).
4. Resolve the name per artist; create a run (`source="auto"`); `attach_run`; enqueue one SQS message per artist (`run_id`, `artist_id`, `artist_name`). The worker derives the disambiguation context (style + sample_tracks + known_labels) at enrichment time.

The curation call sites invoke both label and artist dispatch independently.

## AI-flag projection

`clouder_artists.is_ai_suspected` already exists. The orchestrator sets it true when `ai_confidence >= AI_FLAG_CONFIDENCE_THRESHOLD` and `ai_content` ∈ {suspected, confirmed}, mirroring the label `project_ai_suspected` behavior (reuse the same env threshold).

## API surface (full parity)

New routes (registered in `scripts/generate_openapi.py:ROUTES`, declared in `infra/api_gateway.tf`, dispatched in `src/collector/handler.py`):

Admin: `POST /admin/artists/enrich`, `GET /admin/artists/enrich-runs`, `GET /admin/artists/enrich-runs/{run_id}`, `GET /admin/artists/enrich/options`, `GET /admin/artists/backlog`, `GET /admin/artists/{artist_id}`, `GET /admin/artists/{artist_id}/history`, `GET|PUT /admin/auto-enrich/artists`.
User: `GET /artists`, `GET /artists/{artist_id}`, `PUT /artists/{artist_id}/preference`, `GET /me/artist-preferences`.

All use the existing JWT custom authorizer; admin routes require the admin claim (same `ADMIN` auth marker as label routes). Request/response pydantic schemas mirror the label equivalents with the `ArtistInfo`/artist field set. Regenerate `docs/api/openapi.yaml` + `frontend/src/api/schema.d.ts` (`PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`); the frontend CI diff-check must pass.

## Infra (Terraform)

Mirror the label worker wiring:
- `infra/sqs.tf`: `aws_sqs_queue.artist_enrichment` + `.artist_enrichment_dlq` with redrive (mirror retention/visibility/max-receive vars).
- `infra/main.tf`: name locals `${name_prefix}-artist-enrichment[-dlq]`, `${name_prefix}-artist-enricher-worker`.
- `infra/lambda.tf`: `aws_lambda_function.artist_enricher_worker` (handler `collector.artist_enrichment_handler.lambda_handler`, same IAM role + SSM API-key env vars + Aurora env + `ARTIST_ENRICHMENT_QUEUE_URL` + `AI_FLAG_CONFIDENCE_THRESHOLD`), `aws_lambda_event_source_mapping.artist_enrichment_queue` with `scaling_config.maximum_concurrency`.
- Producer env: add `ARTIST_ENRICHMENT_QUEUE_URL` to the curation lambda (`infra/curation.tf`) and the collector lambda (`infra/lambda.tf`) so both can enqueue.
- New tunable variables mirroring the label `*_queue_*` / `*_worker_*` set.
- Migration applied via the existing `db_migration` Lambda (`{"action":"upgrade","revision":"head"}`) — no infra change.

## Testing

- **Unit:** `schemas` (port test), `prompts` (artist_v1 registered + directives), `aggregator` (port the experiment's merge tests), `auto_repository` (`claim_artists` dedup/attempts; `artist_ids_for_track` returns all roles), `routes` (request validation, id-or-name resolution, admin gating), `auto_dispatch` (disabled→skip; all-roles fan-out; idempotent claim).
- **Integration:** `artist_enrichment_handler` end-to-end with mocked vendor adapters → asserts cells inserted, `clouder_artist_info` upserted, `is_ai_suspected` projected, run counters incremented, auto-state flipped.
- All vendor calls mocked — no live API calls in tests (mirror the label test posture).

## Sequencing within this sub-project (for the plan)

1. DB migration (all tables + prefs).
2. Port schema + prompt + aggregator into the package.
3. Repository + auto_repository.
4. Orchestrator + handler.
5. Routes + auto_routes + OpenAPI + handler dispatch.
6. Auto-dispatch wiring into curation.
7. Infra (SQS + worker + env wiring).
8. Tests throughout (TDD per module).

## Future (sub-project 2 — frontend)

Enable the "artists" tab in `AdminAutoEnrichPage`; build the artist backlog + `EnqueueDrawer`; add the Library artists list via `EntityTabs` + `ArtistsTable`/`ArtistCard`; add the player `ArtistTile` panel (name, country, active_since, description, collaborators, AI badge) below label info on every player surface (`BucketPlayerPanel`, library detail, etc.); reuse the AI-badge pattern; add `useArtistInfo`/`useArtistsList`/artist auto-enrich + enqueue + preference hooks. All consume the endpoints shipped here.

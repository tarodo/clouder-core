# Similar Tracks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two lists, both in the seed's style, AI-free, keeps first, then by similarity:

- "similar tracks" for any playing track;
- "similar to this artist" on the artist page.

Both play in the entity player.

**Architecture:**

- **Vectors.** A 256-dim pgvector embedding per profiled video, built from MuLan + EffNet by a frozen PCA
  artifact (`sim-1`).
  - The ML worker writes it on every `score` job.
  - A one-off fit → embed chain backfills the existing profiles.
- **API.** The collector API ranks inside one SQL statement and returns entity-track rows plus `discarded`.
- **SPA.** It reuses the entity section, player and list for a `/similar/:trackId` page and an artist
  "Similar" view.

**Tech Stack:** Python 3.12, numpy (ML zip only), Aurora PostgreSQL 16 + pgvector 0.8.0 via the RDS Data
API, Alembic, Terraform; React 19 + Mantine 9 + TanStack Query, MSW demo.

**Spec:** `docs/superpowers/specs/2026-11-01-similar-tracks-design.md`

## Global Constraints

- **Vector recipe.**
  1. Take two arrays of the light-1 profile: `mulan/mix.clips` (1680, 512) and `effnet/embedding` (400,
     1280).
  2. Centre each array by the artifact mean, then unit-normalise it.
  3. Concatenate the two (1792 dims), unit-normalise, subtract the PCA mean.
  4. Project onto 256 components, unit-normalise.
  5. Compare with cosine distance `<=>`.
- **Artifact.** `VERSION = "sim-1"`, key `models/similarity/sim-1.npz` in the audio-features bucket.
  - **Write-once:** a fit that finds the object stops.
  - **Fit sample:** the first 10 000 profiled videos ordered by `video_id`.
- **Version filter.** Every embedding read and write filters `version = 'sim-1'`.
- **Results.**
  - At most 50, from the same style, never AI-flagged (`AI_FLAGGED_SQL`).
  - One row per video. The pick: a user placement first, then the earliest release, then id.
- **Order.**
  - Keep group first, then distance ascending.
  - Keep group = (keep placement) OR (no DISCARD placement AND `track_predictions.keep`).
  - `discarded` = DISCARD placement and no keep placement.
  - Placements come from `repositories/ml._PLACEMENTS`.
- **What each seed excludes.**
  - A track seed excludes the seed track and every track on the seed's video. Same-artist tracks stay.
  - An artist seed excludes every track that credits the artist (any role). Its centroid is the `avg()` of
    the artist's non-AI profiled videos in the style.
- **API.** `GET /tracks/{track_id}/similar` and `GET /artists/{artist_id}/similar?style_id=`.
  - CUSTOM JWT auth.
  - Register each in three places: `handler._ROUTE_TABLE`, `scripts/generate_openapi.py` ROUTES, and
    `infra/api_gateway.tf`.
- **ADR-0030.** No code, comment or doc says how the analyzer gets audio.
- **No psycopg under `src/collector`** (ADR-0001); the Data API is used everywhere at runtime.
- **UI copy** is English, in `frontend/src/i18n/en.json`.
- **Local Postgres for tests/db.** Use a new container `canon-pgv` (`pgvector/pgvector:pg16`, port 55433).
  Never touch the running `canon-pg`.
- **Commits.**
  - Through `caveman:caveman-commit`, heredoc bodies.
  - No AI attribution; author tarodo.
  - Never commit the pre-existing `graphify-out/` working-tree changes or `.impeccable/`.

## Review Focus

1. **Bad profile.** A profile whose used arrays are all zeros or non-finite must give no row: pgvector
   rejects NaN, and a zero vector makes `<=>` NaN. Expected: the row is skipped and the rest of the page is
   upserted (Task 2 test `test_embed_drops_degenerate_rows`).
2. **Empty centroid.** An artist whose tracks in the style are all AI-flagged or unprofiled makes the
   centroid `avg()` over no rows, which is NULL. Expected: `profiled: false`, no SQL error (Task 4 test
   `test_artist_all_ai_is_unprofiled`).
3. **Similarity must not block predictions.** If the embedding upsert fails inside `score`, keep
   predictions are still stored first. Expected: predictions upserted, then the job raises for a redrive
   (Task 3 test `test_score_upserts_predictions_before_embeddings`).
4. **Unknown style id.** The artist route gets a `style_id` the artist has no profiled tracks in. Expected:
   `profiled: false`, with `styles` still listed so the picker can switch (Task 4 test
   `test_artist_unknown_style_lists_styles`).
5. **Phone layout.** The curate player on a phone carries 🔥 + similar + Spotify in its top row. Expected:
   no overflow at 390 px (Task 6 browser test).

---

### Task 1: Migration 49 + pgvector test images

**Files:**
- Create: `alembic/versions/20261101_49_audio_embeddings.py`
- Modify: `.github/workflows/pr.yml` (alembic-check service image), `docker-compose.yml`,
  `tests/db/conftest.py` (docstring: the local container line)
- Test: `tests/db/test_similarity_pg.py` (created here, grown in Tasks 2 and 4)

**Interfaces:**
- Produces: table `audio_embeddings(video_id varchar(32), version varchar(16), embedding vector(256),
  created_at timestamptz default now(), PK (video_id, version))`.
- Read-only role: migration 41's `ALTER DEFAULT PRIVILEGES … GRANT SELECT ON TABLES TO clouder_agent_ro`
  already covers a table the migrator creates, so there is nothing to add.

- [ ] **Step 1: Write the failing test** `test_audio_embeddings_holds_a_256_vector`.
  - Insert `('v1', 'sim-1', CAST(:v AS vector))` with a 256-long text vector.
  - Select `embedding <=> embedding` and expect `0`.
  - Inserting a 255-long vector raises.
- [ ] **Step 2: Start the local DB.**
  - Run `docker run -d --rm --name canon-pgv -p 55433:5432 -e POSTGRES_PASSWORD=postgres
    pgvector/pgvector:pg16`.
  - Then `ALEMBIC_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55433/postgres
    PYTHONPATH=src .venv/bin/alembic upgrade head`.
  - Run the test with `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55433/postgres`.
  - Expected: FAIL (relation `audio_embeddings` does not exist).
- [ ] **Step 3: Write migration `20261101_49`** (down_revision `20261029_48`).
  - Upgrade: `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`, then `op.execute` the CREATE TABLE.
    Alembic has no vector type.
  - The docstring says prod needs the master-user step first.
  - Downgrade drops the table, not the extension: the owner created it.
  - Move the CI and compose images to `pgvector/pgvector:pg16`.
- [ ] **Step 4: Run** `alembic upgrade head` on canon-pgv, then the test.
  - Expected: PASS.
  - Also `alembic downgrade -1 && alembic upgrade head` runs clean.
- [ ] **Step 5: Add the runbook note** to `docs/ops/aurora.md`: one paragraph with the exact master-user
  command from spec Ops step 0.
- [ ] **Step 6: Commit** the migration, CI, compose, conftest, aurora.md and the test.

### Task 2: Embedding math and the embeddings repository

**Files:**
- Create: `src/collector/ml/similarity.py`, `src/collector/repositories/similarity.py`
- Modify: `src/collector/repositories/__init__.py` (add `SimilarityMixin`)
- Test: `tests/unit/test_ml_similarity.py`, `tests/db/test_similarity_pg.py`

**Interfaces:**
- Produces, in `collector.ml.similarity`:
  - `VERSION = "sim-1"`, `ARTIFACT_KEY = f"models/similarity/{VERSION}.npz"`, `DIMS = 256`,
    `SAMPLE = 10_000`.
  - `@dataclass(frozen=True) class Artifact: mulan_mean, effnet_mean, mean (1792,), components (256, 1792)`,
    all float32 ndarrays.
  - `fit(X: np.ndarray) -> Artifact`. X has shape (n, audio_profile.DIMS) or (n, 1792): the `used(X)` slice
    is applied if the width is DIMS.
  - `used(X) -> np.ndarray`: (n, 1792) float32, mulan then effnet.
  - `embed(art: Artifact, X: np.ndarray) -> tuple[np.ndarray, np.ndarray]`: (keep mask (n,) bool, vectors
    (k, 256) float32). The mask drops rows that are non-finite or zero at any normalisation.
  - `to_npz(art) -> bytes`, `from_npz(blob: bytes) -> Artifact`.
  - `as_text(v: np.ndarray) -> str`: `'[x,y,…]'` with `%.4g` floats.
- Produces, in `SimilarityMixin` on `ClouderRepository`:
  - `similarity_videos(*, after_video_id: str | None, limit: int) -> list[str]`: profiled `audio_features`
    video ids, keyset by video_id.
  - `similarity_upsert(*, version: str, rows: list[tuple[str, str]]) -> None`: `(video_id, vector_text)`,
    chunked at 50 rows per statement, `ON CONFLICT (video_id, version) DO UPDATE SET embedding,
    created_at`.

- [ ] **Step 1: Write the failing unit tests.**
  - `test_used_takes_mulan_then_effnet_embedding`: columns 1680:2192 then 400:1680.
  - `test_embed_is_unit_256_and_deterministic`:
    - fit on 300 random rows;
    - `embed` gives shape (300, 256), norms ≈ 1 (1e-5);
    - a second call is equal.
  - `test_embed_ignores_unused_arrays`: overwrite columns 0:400 (discogs) and 2192:16528 (MuQ) of a row; its
    vector is unchanged.
  - `test_npz_round_trip`: `from_npz(to_npz(a))` equals `a` array-wise.
  - `test_embed_drops_degenerate_rows`: a row of zeros in the used columns and a row with NaN both get mask
    False; the other rows come out.
  - `test_as_text_parses_back`: `as_text` gives 256 comma-separated floats in brackets.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_ml_similarity.py -q`.
  Expected: FAIL (module missing).
- [ ] **Step 3: Implement `collector/ml/similarity.py`.**
  - Read the offsets from `audio_profile.ARRAYS` by name, never as literals.
  - PCA via `np.linalg.svd(Z - mean, full_matrices=False)`, top 256 rows of Vt. Fewer than 256 rows → the
    components are whatever SVD gives, padded with zeros. The unit tests fit on 300 rows.
  - Normalise with a norm floor: rows below 1e-9 count as degenerate.
- [ ] **Step 4: Run** the unit tests. Expected: PASS.
- [ ] **Step 5: Write the failing DB tests.**
  - `test_similarity_upsert_writes_and_replaces`: two upserts of v1 leave one row holding the second vector.
  - `test_similarity_videos_pages_by_video_id`: three audio_features rows; limit 2 and after work.
- [ ] **Step 6: Implement the mixin.**
  - The upsert uses `jsonb_to_recordset(CAST(:items AS jsonb)) AS x(video_id text, embedding text)` with
    `CAST(x.embedding AS vector)`, the `ml_upsert_predictions` pattern.
- [ ] **Step 7: Run** the DB tests against canon-pgv. Expected: PASS.
- [ ] **Step 8: Commit.**

### Task 3: ML worker — embed on `score`, fit and embed jobs

**Files:**
- Modify: `src/collector/ml_worker_handler.py`, `src/collector/ml_jobs.py`
- Test: `tests/unit/test_ml_worker_handler.py`

**Interfaces:**
- Consumes: Task 2's `similarity.*` and `SimilarityMixin`.
- Produces:
  - `ml_jobs.enqueue_similarity_embed(*, version: str, after_video_id: str | None) -> None`. It raises like
    `enqueue_score_style`.
  - Jobs `similarity_fit {version}` and `similarity_embed {version, after_video_id}` in `_JOBS`.
  - Module cache `_SIMILARITY: Artifact | None`.

- [ ] **Step 1: Write the failing tests**, extending FakeRepo with `similarity_videos` / `similarity_upsert`
  and FakeS3 with put/get of `ARTIFACT_KEY`.
  - `test_score_embeds_even_without_models`: style with no models; the artifact is present; the upsert has
    the present videos.
  - `test_score_skips_embeddings_without_artifact`: no upsert, no raise.
  - `test_score_upserts_predictions_before_embeddings`: `similarity_upsert` raises → predictions were
    already upserted, and the job raises.
  - `test_fit_writes_artifact_once_and_starts_chain`:
    - First call: puts the artifact and enqueues `similarity_embed` with after null.
    - Second call (object present): no second put, and still enqueues.
  - `test_embed_chain_pages_until_short_page`: PAGE-size page → enqueue with after = last id; a short page →
    no enqueue.
  - `test_artifact_cached_only_once_found`: missing then present → the second message loads it.
- [ ] **Step 2: Run** `.venv/bin/python -m pytest tests/unit/test_ml_worker_handler.py -q`.
  Expected: new tests FAIL.
- [ ] **Step 3: Implement.**
  - `_similarity(s3, bucket) -> Artifact | None`: GET, and on NoSuchKey return None; cache only a hit.
  - `_embed_rows(repo, art, present, X)` upserts the `as_text` rows of the kept mask.
  - `_score`: after the per-style prediction loop, call `_embed_rows` if the artifact is not None.
  - **`similarity_fit`:**
    1. A present object → just enqueue.
    2. Otherwise `similarity_videos(after=None, limit=SAMPLE)`.
    3. `vectors` → `used` → `fit` → put → reset the cache → enqueue.
    - Memory: `vectors` gives (n, 16778) f32, 671 MB at 10 k, which fits in 3008 MB. A ponytail note names
      that ceiling.
  - **`similarity_embed`:** a page of `PAGE` ids → vectors → `_embed_rows`. If `len == PAGE`, enqueue the
    next page.
  - The docstring adds both message types.
- [ ] **Step 4: Run** the ML worker tests plus `tests/unit/test_ml_*.py`. Expected: PASS.
- [ ] **Step 5: Commit.**

### Task 4: Similar-tracks read repository and handlers

**Files:**
- Create: `src/collector/similar_tracks.py`
- Modify: `src/collector/entity_tracks.py` (the `_PAGE` select becomes reusable over any `page` CTE with
  `(id, release_date[, extra columns])`)
- Test: `tests/db/test_similarity_pg.py`, `tests/unit/test_similar_tracks_route.py`

**Interfaces:**
- Consumes: `entity_tracks._track`, the shared select, `ml._PLACEMENTS`, `AI_FLAGGED_SQL`, and
  `similarity.VERSION`.
- Produces:
  - `SimilarTracksRepository(data_api)`.
  - `.for_track(*, track_id: str, user_id: str) -> dict`: `{"seed": row | None, "profiled": bool, "items":
    [row]}`.
  - `.for_artist(*, artist_id: str, user_id: str, style_id: str | None) -> dict`: `{"profiled": bool,
    "style": {"id", "name"} | None, "styles": [{"id", "name", "count"}], "items": [row]}`.
  - `row` is `entity_tracks._track(r) | {"discarded": bool}`.
  - Handlers `handle_track_similar(event)` and `handle_artist_similar(event)` return `(200, body)`. A
    missing path id raises ValidationError → 400.

- [ ] **Step 1: Write the failing DB tests.** The fixture holds two styles and tracks with videos and
  vectors. Vectors are hand-made 256-d unit text vectors with known cosine distances, e.g. the seed `e0`
  and `cos(e0, x)` = 0.9, 0.8, ….
  - `test_track_results_stay_in_style_and_skip_ai`.
  - `test_track_excludes_seed_and_its_video_keeps_same_artist`.
  - `test_one_row_per_video_prefers_placed_track_then_earliest_release`.
  - `test_keep_group_first_then_distance`:
    - a category track and a predicted keep come before nearer non-keeps;
    - a DISCARD-placed track with `keep = true` prediction is not in the keep group;
    - in a style with no model, the order is labelled keeps first, then distance.
  - `test_discarded_flag`: DISCARD-only → true; DISCARD + category → false.
  - `test_unprofiled_seed_or_styleless_seed_gives_profiled_false`.
  - `test_other_version_rows_are_ignored`: a `sim-0` row for a closer video never shows.
  - `test_limit_50`.
  - `test_artist_centroid_excludes_artists_tracks_and_ai`.
  - `test_artist_default_style_is_most_profiled`.
  - `test_artist_all_ai_is_unprofiled`.
  - `test_artist_unknown_style_lists_styles`.
- [ ] **Step 2: Run** them on canon-pgv. Expected: FAIL (module missing).
- [ ] **Step 3: Implement `similar_tracks.py`.**
  - One statement per call. CTEs: seed → candidates (style scope, version, NOT AI, exclusions) → nearest 50
    videos → one track per video → user placements (`_PLACEMENTS` on `:user_id` / `:style_id`, joined on
    the candidate ids) → the shared entity select plus `distance`, `keep_group`, `discarded` → ORDER BY
    `keep_group DESC, distance, id`.
  - For the artist call, first query `styles`, then the centroid statement.
  - Repository construction, `_user_id` and `_json` are reused from `entity_tracks`; do not copy them.
  - Add a `ponytail:` note on the exact scan (HNSW iterative scan past ~100 k vectors per style) and on the
    ISRC collapse.
- [ ] **Step 4: Run** the DB tests. Expected: PASS.
  - Also run `tests/db/test_entity_tracks_pg.py`: PASS, which shows the `_PAGE` refactor is safe.
- [ ] **Step 5: Unit route tests** (`test_similar_tracks_route.py`, after `test_entity_tracks_route.py`).
  - The handler passes the path id, the caller's user_id and `style_id`.
  - A blank id → 400.
- [ ] **Step 6: Commit.**

### Task 5: Route registration, OpenAPI, frontend schema

**Files:**
- Modify: `src/collector/handler.py`, `scripts/generate_openapi.py`, `infra/api_gateway.tf`
- Regenerate: `docs/api/openapi.yaml`, `frontend/src/api/schema.d.ts`

**Interfaces:**
- Produces: OpenAPI paths `/tracks/{track_id}/similar` and `/artists/{artist_id}/similar`. Their schemas are
  `SIMILAR_TRACK` (= ENTITY_TRACK + `discarded`), `TRACK_SIMILAR_RESPONSE` and `ARTIST_SIMILAR_RESPONSE`.
  The frontend imports them as `paths['/tracks/{track_id}/similar']['get']['responses'][200]…`.

- [ ] **Step 1: Run** the existing route-table / openapi consistency tests (`pytest -q tests/unit -k "route
  or openapi"`) after adding the two `_ROUTE_TABLE` entries only. Expected: FAIL (openapi missing them).
- [ ] **Step 2: Add the remaining pieces.**
  - The ROUTES entries and schemas.
  - Two `aws_apigatewayv2_route` resources (`track_similar_user`, `artist_similar_user`), CUSTOM + jwt
    authorizer, like `artist_tracks_user`.
  - Regenerate: `PYTHONPATH=src .venv/bin/python scripts/generate_openapi.py`, then `cd frontend && pnpm
    gen:api` (or the repo's schema script).
- [ ] **Step 3: Run** the unit suite (`.venv/bin/python -m pytest -q tests/unit`) and `cd infra &&
  terraform fmt -check && terraform validate`. Expected: PASS.
- [ ] **Step 4: Commit.**

### Task 6: The similar icon in every player

**Files:**
- Create: `frontend/src/features/similar/SimilarLink.tsx`
- Modify: `frontend/src/features/playback/TrackPlayer.tsx` (`ConnectedPlayerCard`),
  `frontend/src/i18n/en.json`
- Test: `frontend/src/features/playback/__tests__/PlayerCard.test.tsx` (or a new
  `SimilarLink.test.tsx`), `frontend/src/features/playback/__tests__/PlayerCard.browser.test.tsx`

**Interfaces:**
- Produces:
  - `SimilarLink({ trackId, title }: { trackId: string; title: string })`: a Mantine `ActionIcon` rendered
    as a router `Link` to `/similar/${trackId}`, aria `t('similar.open_aria', { title })`.
  - `ConnectedPlayerCard` passes `topActions={<>{props.topActions}<SimilarLink …/></>}` when `track` is set.

- [ ] **Step 1: Write the failing tests.**
  - `similar link sits left of the Spotify link`: render ConnectedPlayerCard with a track; the link's href
    ends `/similar/<id>`; in DOM order it comes before the Spotify anchor.
  - `curate keeps its fire button first`: given topActions, the fire button comes before the similar link.
- [ ] **Step 2: Run** `cd frontend && pnpm test -- src/features/playback`. Expected: FAIL.
- [ ] **Step 3: Implement.** Pick the Tabler icon (e.g. `IconArrowsShuffle2`, or another that reads as
  "similar"). Add the i18n keys `similar.open_aria`, `similar.title` and the rest used in Task 7.
- [ ] **Step 4: Run** the jsdom tests. Expected: PASS.
  - Browser test: the curate player at 390 px with 🔥 + similar + Spotify shows no horizontal overflow
    (`scrollWidth <= clientWidth` on the card).
  - `pnpm test:browser -- PlayerCard`: PASS.
- [ ] **Step 5: Commit.**

### Task 7: Similar page, artist "Similar" view, demo

**Files:**
- Create: `frontend/src/features/similar/useSimilarTracks.ts`,
  `frontend/src/features/similar/SimilarTracksPage.tsx`
- Modify: `frontend/src/features/library/components/EntityTracksSection.tsx`, `EntityPlayerPanel.tsx`,
  `EntityTrackList.tsx`, `frontend/src/features/library/hooks/useEntityTracks.ts`,
  `frontend/src/features/library/routes/ArtistDetailPage.tsx`, `frontend/src/routes/router.tsx`,
  `frontend/src/features/playback/lib/types.ts`, `frontend/src/demo/handlers.ts`,
  `frontend/src/demo/db.ts`, `frontend/src/i18n/en.json`
- Test: `frontend/src/features/similar/__tests__/SimilarTracksPage.test.tsx`,
  `frontend/src/features/library/__tests__/…` (artist switch), a browser test for the page layout

**Interfaces:**
- Consumes: Task 5 schema types.
- Produces:
  - **Queue source.** `QueueSource` entity kind widens to `'label' | 'artist' | 'similar'`; `PlaybackSource`
    adds `'similar_player'`.
  - **Track list query.** `useSimilarTracks(trackId)` is a `useInfiniteQuery` under `['library',
    'entityTracks', 'similar', 'track', trackId]`. It has one page, shaped `{ items, total, limit: 50,
    offset: 0 }`, with the seed row first, `seed` and `profiled` carried alongside, and
    `getNextPageParam: () => undefined`.
  - **Artist list query.** `useArtistSimilar(artistId, styleId | null)`, the same under `[…, 'similar',
    'artist', artistId, styleId]`.
  - **Row type.** `EntityTrack` gains optional `discarded?: boolean` and `seed?: boolean`, so
    `patchEntityTrack` covers both lists unchanged.
  - **Generalised section.** `EntityTracksSection` takes `{ source: QueueSource; query; showLabel: boolean;
    title: ReactNode; headerExtra?: ReactNode }` in place of `{kind, entityId}`. Label and artist pages pass
    `useEntityTracks`; the player panel's hotkey check compares `queue.source` to `source`.

- [ ] **Step 1: Write the failing tests** (MSW handlers in `frontend/src/test/handlers.ts`).
  - `similar page lists seed first then results with marks`:
    - the seed row carries a "Seed" badge;
    - a discarded row shows a DISCARD badge;
    - the label column is present.
  - `unprofiled seed shows the analyze message`: `profiled: false` → "This track has no sound profile yet…".
  - `profiled with no items shows the style message`.
  - `new trackId re-mounts and rebinds the queue`: navigate `/similar/a` → `/similar/b`; the bound queue
    source has entityId `track:b`.
  - `category toggle patches the similar row`: the toggle in the panel → the row shows the category at once.
  - `artist page switches to Similar and keeps view and style in the URL`:
    - `?view=similar&style=st2` renders the artist similar list for st2;
    - the style picker shows only when `styles.length > 1`.
- [ ] **Step 2: Run** `cd frontend && pnpm test -- src/features/similar src/features/library`.
  Expected: FAIL.
- [ ] **Step 3: Implement.**
  - The route `{ path: 'similar/:trackId', element: <SimilarTracksPage /> }`. The page renders a keyed child
    (`key={trackId}`).
  - **Header:** a back link (`useBackOrFallback('/library')`), `Title` "Similar tracks", and the seed
    title / mix / `EntityLink` artists / style.
  - **"Mine" column:** shows a gray DISCARD badge when `discarded`, and a "Seed" badge on the seed row.
  - **Artist page:** `SegmentedControl` "Tracks | Similar" in the section header. In the Similar view a
    style `SegmentedControl` (or `Select` past 4 styles) appears only if there is more than one style.
    `useSearchParams` holds `view` and `style`.
  - **Demo:** `db.similarTo(trackId)` and `db.artistSimilar(artistId, styleId)` return the same-style demo
    tracks minus the seed, in a fixed order, with `discarded` from the demo DISCARD buckets. Add handlers
    for both routes.
- [ ] **Step 4: Run** the frontend gates.
  - `pnpm typecheck && pnpm lint && pnpm test`: all PASS.
  - Then the full `pnpm test:browser`: PASS.
- [ ] **Step 5: Visual check.** Run the demo (`pnpm dev:demo --port 5287 --strictPort`) with a throwaway
  `frontend/.x.tmp.mjs` Playwright script. Take shots at 1440×900 and 390×844 of:
  - a bucket player's top row;
  - `/similar/<demo track>`;
  - the artist Similar view.
  Read the shots, then delete the script.
- [ ] **Step 6: Commit.**

### Task 8: Docs, graph, ship

**Files:**
- Create: `docs/data/similar-tracks.md`
- Modify: `docs/architecture.md` (one line + link), `graphify-out/` (only the files `graphify update .`
  writes for this change)

- [ ] **Step 1: Write the docs.**
  - `docs/data/similar-tracks.md` covers the vector recipe, artifact versioning, the jobs and the backfill
    kick, the ranking rules, and the speed note.
  - No analyzer audio wording.
  - The ADR-0030 hygiene test (`pytest -q -k hygiene`) passes.
- [ ] **Step 2: Run the full backend suite** `.venv/bin/python -m pytest -q`, plus tests/db against
  canon-pgv. Expected: PASS. Then stop canon-pgv.
- [ ] **Step 3: Refresh the graph.** `graphify update .`, then commit the docs and the graph files.
- [ ] **Step 4: Final whole-branch review** (executing-plans). Then the PR: title and body through
  caveman-commit. Watch the checks, `gh pr merge --merge`, and watch the deploy.
- [ ] **Step 5: Kick the backfill.**
  - `aws sqs send-message --queue-url "$(aws sqs get-queue-url --queue-name clouder-prod-ml-jobs --query
    QueueUrl --output text)" --message-body '{"type":"similarity_fit","version":"sim-1"}'`.
  - Watch the `clouder-prod-ml-worker` logs until a short page.
- [ ] **Step 6: Prod checks** (read-only role).
  - `SELECT count(*) FROM audio_embeddings WHERE version = 'sim-1'` ≈ `SELECT count(*) FROM
    audio_features`.
  - `EXPLAIN ANALYZE` of the track statement for a DnB seed, under ~300 ms. If it is over, open a
    follow-up with the missing index.
  - Open `/similar/<DnB keep>` on prod in the browser and check the order and marks.

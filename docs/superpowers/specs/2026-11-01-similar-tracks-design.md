# Similar tracks

Date: 2026-11-01. The owner set the direction in chat. Calls marked *(my call)* are mine and the owner
reviews them in this document.

## Why

The light-1 sound profile (`audio_profile`, analyzer `light_profile`) already sits in S3 for ~42 k videos.
An offline check on the owner's DnB labels (memory `project_clouder_similarity_eval`) showed that nearest
neighbours on it land in the same category of the owner's six about 61% of the time, against 19% at random.
The owner listened to the examples and called it a "killer feature": find tracks that sound like a given
track, or like an artist, and curate them in the player used on label and artist pages.

The owner's rules:

1. **Track.** Every player gets a "similar" icon next to the Spotify link. It opens the tracks similar to
   the playing track.
2. **Artist.** The artist page shows tracks similar to the artist.
3. **Style.** Results stay in the style: the track's style, or the artist style being viewed.
4. **AI.** AI-flagged tracks never show up.
5. **Marks.** Every track is shown. The ones the user already put in a category or in DISCARD say so.
6. **Same artist.** Track results include the seed artist's other tracks.
7. **Order.** Keeps first, then by similarity within each group.
8. **Player.** The same one as on label and artist pages. Only the set of tracks is new.

## Goals

- **Track result.** The ≤ 50 tracks of the seed's style whose sound is nearest to the seed track.
- **Artist result.** The ≤ 50 tracks nearest to the centroid of the artist's profiled tracks in one style.
- **Ordering.** Both lists use the owner's keep → similarity order.
- **Curating.** The page player puts the playing track into a category of its style or into a playlist,
  like the entity player (PR #410).
- **Freshness.** New profiles become searchable within minutes: the existing `score` job embeds them.

## Non-goals

- **Labels.** No similar-to-label (not asked).
- **Other surfaces.** Nothing for playlists, categories, or the whole catalog.
- **Cross-style results.** Never; the owner said style only.
- **Scores.** No similarity percentage or match score in the UI *(my call)*: the order already carries it.
- **Paging.** No "more" button. The list is the top 50 *(my call)*.
- **Analyzer.** No change; it keeps posting profiles exactly as today.
- **Index.** No HNSW / ANN index (see Constraints).

## Anti-goals

- A result list full of the seed itself or its duplicate releases.
- Two copies of the same recording.
- An AI track in a result list.
- Showing a "no similar tracks" list when the real reason is that the seed has no profile yet. That reads
  as "the feature is broken".
- Vectors from two artifact versions compared with each other. That gives silent garbage.
- Anything that says how the analyzer gets its audio (ADR-0030). Write only "the analyzer profiles the
  track".

## The vector (decided; validated offline)

From each light-1 profile (16 778 f16, layout in `audio_profile.ARRAYS`) take two arrays:

| Array | Offset | Width |
|---|---|---|
| `mulan/mix.clips` | 1680 | 512 |
| `effnet/embedding` | 400 | 1280 |

The model block `effnet` (0:1680) also holds `discogs400`. That part is **not** used.

To build the vector:

1. Subtract the artifact's per-array mean from each array, then scale it to unit length.
2. Concatenate the two arrays (1792 dims) and scale to unit length.
3. Subtract the artifact's PCA mean and project onto its 256 components.
4. Scale to unit length.

Cosine distance (`<=>`) on the result. Offline, the 256-dim PCA matched the full 1792 dims: same-category
top-10 0.613 against 0.614, and artist hold-out recall within noise.

**Artifact `sim-1`.**

- **Contents.** The two array means, the PCA mean, and the components (256 × 1792), f32, one `.npz`, about
  1.8 MB.
- **Location.** `s3://<audio-features bucket>/models/similarity/sim-1.npz`. The ML worker role already has
  `models/*` read/write.
- **Fit.**
  - Fit once on the first 10 000 profiled videos ordered by `video_id`. Video ids are random, so that is a
    random sample across all styles *(my call)*.
  - **Write-once:** a fit finds the object already there and stops. Re-fitting means a new version
    (`sim-2`), never an overwrite.
- **Version constant.** One constant names the live version. Every read and write filters on it.

## Data

Migration 49:

```sql
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector 0.8.0 is available on Aurora 16.11, not yet installed
CREATE TABLE audio_embeddings (
    video_id   text        NOT NULL,
    version    text        NOT NULL,      -- 'sim-1'
    embedding  vector(256) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (video_id, version)
);
```

**Rows and setup.**

- **One row per video, not per track.** That matches `audio_features`, and re-matching a track to another
  video needs no cleanup.
- **Migration rights.**
  - In prod the migration runs as `clouder_migrator` (IAM auth). That role cannot create the extension:
    on prod, pgvector 0.8.0 is `superuser = true, trusted = false`, and the migrator has no `CREATE` on the
    database (checked 2026-11-01).
  - So the owner creates the extension once as the master user `clouder_admin` before the deploy (Ops step
    0), like the read-only role before migration 41.
  - The migration still says `CREATE EXTENSION IF NOT EXISTS vector`. PostgreSQL checks for an existing
    extension before it checks privileges, so in prod this is a no-op after step 0. In CI and local runs a
    superuser creates the extension there and then.
  - Note the step in `docs/ops/aurora.md`.
- **Docker images.** CI (`pr.yml` alembic-check / tests/db) and `docker-compose.yml` move from
  `postgres:16` to `pgvector/pgvector:pg16`, the same major version.
- **Read-only role.** The agent role `clouder_agent_ro` must be able to read the new table. Check its
  default privileges; tests/db has `test_agent_reader_role_pg.py`.

**Prod numbers (2026-11-01).**

- **Videos.** 42 318 profiled videos for 50 261 tracks.
- **Duplicate releases.** 5 030 videos (12%) belong to more than one track, usually an original plus
  compilations.
- **Largest style.** DnB has 10 188 profiled videos; the whole catalog is about 2.5× that.
- **Size.** About 45 MB of vectors now, about 110 MB at full catalog.

## Writes (ML worker)

The ML worker's dependencies already include numpy. New module `collector/ml/similarity.py` holds the
artifact fit/load/save and `embed(X) -> (n, 256) float32`. It reuses `audio_profile` for the array offsets.

**`score` job** (existing, one per profiles POST).

- **When.** After `_profiles(...)`, it embeds the present videos and upserts their rows. It does this always,
  whether or not the style has a user model.
- **Artifact missing.** If the artifact does not exist yet, skip quietly. The backfill covers those videos.
- **Caching.** Cache the artifact in the container only once it is found. A container that saw it missing
  checks S3 again on its next message.

**New jobs**, in `_JOBS`, started once by hand after deploy:

- `similarity_fit {version}`:
  1. If the artifact already exists, skip to step 3.
  2. Otherwise fetch the sample's profiles, fit, and save. Keep only the 1792 used columns per profile: 10 k
     full f32 profiles would take ~670 MB of the 3008 MB cap.
  3. Enqueue `similarity_embed {version, after_video_id: null}`.
- `similarity_embed {version, after_video_id}`:
  - Takes one page of profiled videos (`audio_features`, keyset on `video_id`, about 2 000 per page).
  - Embeds the page, upserts it, and enqueues the next page until a short page. This is the
    `score_style` pattern.
  - Videos profiled mid-chain are covered by their own `score` job, because the artifact exists by then.

**Upsert.**

- Vectors go over the Data API as text, `CAST(:v AS vector)`. Use about 4 significant digits; that is plenty
  for ranking.
- Chunk the statements so each request stays well under the Data API limits (rows of ~1.8 KB of text).
  `ON CONFLICT (video_id, version) DO UPDATE`.

## Reads (collector API)

Two routes, `CUSTOM` JWT auth like `GET /artists/{artist_id}/tracks`. Register each in three places:
`handler._ROUTE_TABLE`, `scripts/generate_openapi.py` ROUTES, and the gateway route in
`infra/api_gateway.tf`. Then regenerate `docs/api/openapi.yaml` and `frontend/src/api/schema.d.ts`.

- `GET /tracks/{track_id}/similar` returns:
  - `seed`: the seed as an entity-track row, for the page header;
  - `profiled`: boolean;
  - `items`.
- `GET /artists/{artist_id}/similar?style_id=` returns:
  - `profiled`;
  - `style`: the one used;
  - `styles`: the artist's styles with profiled tracks, most profiled first;
  - `items`.

  Without `style_id`, the artist call uses the first style in `styles` *(my call)*.

Each `items` row is the existing entity-track row (`entity_tracks._track`: artists with AI rep, label,
style, bpm, key, length, release date, spotify id, AI verdict, the user's categories and playlists), plus
`discarded: bool`. Reuse the `entity_tracks._PAGE` select (per-track lookups for one page) rather than
writing a second copy.

**Candidates.** SQL, all inside one statement.

- **Style scope.** Tracks of the style with a profile row of the live version, joined through
  `vendor_track_map` (vendor `ytmusic`), and `NOT AI_FLAGGED_SQL`.
- **Track seed.**
  - Distance to the seed video's vector.
  - Exclude the seed track, every track on the seed's video, and every other track on that video.
  - Same-artist tracks stay in.
- **Artist seed.**
  - Distance to `avg(embedding)` over the artist's profiled, non-AI videos in the style. The pgvector `avg`
    aggregate gives the centroid; `<=>` normalises.
  - Exclude every track that credits the artist in any role *(my call)*: those are already in the page's own
    list.
- **One row per video.**
  - Rank videos by distance and keep the nearest 50.
  - Show one track per video: the one the user has a placement on first, else the earliest release, then
    by id *(my call)*.
  - Same recording on another video: no extra collapse (ISRC, title + mix) *(my call)*. On prod only 79 of
    44 248 profiled ISRCs sit on more than one video (2026-11-01). Leave a `ponytail:` note: collapse by
    ISRC if duplicates start showing.
- **No profile.** If the seed (or the artist in that style) has no vector, return `profiled: false` and no
  items. If the seed track has no style, return `profiled: false` too.

**Order.** Keep group first, then distance ascending within each group.

- **Keep group.** The user's own decision wins.
  - **Keep:** the track has a keep placement (as in `repositories/ml._PLACEMENTS`: any category track of the
    user's categories, or an active STAGING bucket).
  - **Not keep:** the track has only DISCARD placements.
  - **No decision:** the stored prediction `track_predictions.keep` for (user, style).
  - **No prediction:** a style with no trained model, or an unscored track, falls in the non-keep group.
    Such a list ends up ordered by labelled keeps, then similarity.
- **Unsure.** No unsure band; the bucket player's ordering ignores it too.
- **`discarded`.** Only DISCARD placements, no keep.

**Speed.**

- **Plan.** Exact scan of one style: at most ~10 k vectors today. There is no index on
  `clouder_tracks.style_id` or `vendor_track_map.vendor_track_id`.
- **After the backfill.** Run `EXPLAIN ANALYZE` on prod through the read-only role. If a DnB query is over
  ~300 ms, add the missing index in a follow-up migration.
- **HNSW later.** Only when a style passes ~100 k vectors. Then the filtered-kNN path is the HNSW iterative
  scan. Leave a `ponytail:` note.

## Frontend

**Icon.**

- `ConnectedPlayerCard` (`playback/TrackPlayer.tsx`) renders a "Similar tracks" icon link left of the
  Spotify link, after any caller `topActions` (curate's 🔥 stays first). Every player gets it this way:
  - bucket, category, playlist and entity players;
  - curate;
  - the similar page itself, which lets the user hop from track to track.
- The link goes to `/similar/:trackId`.
- It is always shown, even for unprofiled tracks; the page explains *(my call)*.
- Pick a Tabler icon that reads "similar sound"; aria / tooltip "Similar tracks". UI copy is English
  (`i18n/en.json`).

**`/similar/:trackId` page.**

- **Header.**
  - A back link, as on the artist page (`useBackOrFallback`).
  - The title "Similar tracks".
  - The seed's title, mix, linked artists and style.
- **Body.** The entity section unchanged: player beside the list on desktop, above it on a phone once
  something plays.
  - **Seed row.** The seed is the list's first row and the queue's first track, marked "Seed". It is not
    one of the 50, and it is left out when nothing is profiled *(my call)*.
  - **Clicking the icon stops playback.** The old page unmounts, and its queue clears exactly as when
    following an artist link from a player today. The seed is one tap away on the new page *(my call)*.
  - **Re-mount per track.** The page re-mounts for every `trackId` (key on it). Hopping from the similar
    page's own player rebinds the queue instead of leaving the new seed playing outside it.
  - The categories offered are those of the result style.
  - The list shows the label column (as `kind === 'artist'` does).
  - The "mine" column adds a DISCARD badge next to the category badges.
- **Empty states.**
  - `profiled: false`: "This track has no sound profile yet; similar tracks appear once it is analyzed."
  - Profiled but no items: "No similar tracks in this style yet."

**Artist page.**

- **Switch.** The tracks section gets "Tracks | Similar" in its header *(my call)*. That gives one player,
  one queue and one list on the page, with no second player.
- **Similar view.** It shows the similar-to-artist list. If `styles` has more than one entry, a style picker
  is added.
- **URL.** The view and style live in the URL (`?view=similar&style=<id>`), so back and refresh keep them.

**Reuse.**

- Generalise `EntityTracksSection` / `EntityPlayerPanel` / `EntityTrackList` over the data source instead of
  forking them.
- Similar lists sit under the `['library', 'entityTracks', …]` query key in the same infinite-query page
  shape (one page). That way `patchEntityTrack` updates their rows on a category / playlist toggle.
- The queue source and telemetry need a kind of their own, for example `{ type: 'entity', kind: 'similar',
  entityId }` → `similar_player`. Nothing on the backend enumerates player sources.

**Demo.** Add MSW handlers and seed rows for both routes in `frontend/src/demo`, so the demo build and the
screenshots keep working.

## Ops (after merge and deploy)

0. **Owner, before the merge: create the extension as the master user.** This is the one step the agent
   cannot do: it has prod reads only.

   ```bash
   aws rds-data execute-statement --database clouder \
     --resource-arn "$(aws rds describe-db-clusters --db-cluster-identifier clouder-prod-aurora --query 'DBClusters[0].DBClusterArn' --output text)" \
     --secret-arn "$(aws rds describe-db-clusters --db-cluster-identifier clouder-prod-aurora --query 'DBClusters[0].MasterUserSecret.SecretArn' --output text)" \
     --sql "CREATE EXTENSION IF NOT EXISTS vector"
   ```

   Then check it as the agent: `SELECT extversion FROM pg_extension WHERE extname = 'vector'` → `0.8.0`.
1. **Deploy.** The two-phase deploy applies migration 49 before the API Lambda update.
2. **Backfill.** Start it once:
   `aws sqs send-message --queue-url <clouder-prod-ml-jobs> --message-body '{"type":"similarity_fit","version":"sim-1"}'`.
   The chain runs about 21 pages for 42 k videos.
3. **Verify.**
   - `audio_embeddings` rows ≈ `audio_features` rows.
   - `EXPLAIN ANALYZE` for a DnB seed.
   - Open `/similar/<a DnB keep>` on prod and check the sound against the offline examples.
4. **Refresh the graph.** `graphify update .` after landing the code (memory: code-only update).

Cost: storage cents a month. Writes ride on the `score` job, which already wakes Aurora. The backfill is
about $0.02.

## Tests the build must leave behind

- **Python unit.**
  - `embed` on synthetic profiles: output is (n, 256), unit length, and deterministic. It uses only the two
    arrays: changing the `discogs400` or MuQ columns does not change the vector.
  - A fit/save/load round trip.
  - The write-once guard.
- **Python ML worker.**
  - `score` upserts embeddings even for a style without models.
  - `score` skips without an artifact.
  - The `similarity_embed` chain enqueues the next page and stops on a short page.
- **tests/db** (real Postgres + pgvector):
  - Style scope.
  - AI exclusion, both in results and in the artist centroid.
  - Seed and seed-video exclusion.
  - One row per video, with the placement-first pick.
  - Artist's own tracks excluded.
  - Keep group order, with the label beating the prediction.
  - `discarded`.
  - `profiled: false` cases.
  - Version filter: a `sim-0` row is never compared.
- **Frontend.**
  - The icon sits in `ConnectedPlayerCard`, left of Spotify.
  - The page's states.
  - The seed row comes first in the list and the queue, and the page re-mounts on a new `trackId`.
  - The DISCARD badge.
  - The artist switch and style picker.
  - A category toggle that patches a similar list row.
  - Browser test and demo screenshots (desktop 1440, phone 390) for the icon row and the page.
  - Full gates: typecheck, lint, `pnpm test`, the full `pnpm test:browser`.

## Left to the builder

- Exact SQL shape, CTE layout and parameter passing.
- Module and component names.
- The Tabler icon.
- Chunk sizes.
- How `EntityTracksSection` is generalised, as long as there is one implementation.
- Wording of empty states within the meaning above.
- The doc page (`docs/data/similar-tracks.md` or a section in an existing data doc) and the ADR-free note in
  `docs/architecture.md`.

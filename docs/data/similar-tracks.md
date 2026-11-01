# Similar tracks

"Tracks that sound like this one" and "tracks that sound like this artist", ranked for the caller. Spec: [`docs/superpowers/specs/2026-11-01-similar-tracks-design.md`](../superpowers/specs/2026-11-01-similar-tracks-design.md).

## The vector

From each light-1 profile (`audio_profile.ARRAYS`) the ML worker takes two arrays:

- `mulan/mix.clips` (512 dims);
- `effnet/embedding` (1280 dims).

It builds the vector in five steps:

1. Subtract the artifact's mean from each array.
2. Scale each array to unit length.
3. Concatenate the two and scale to unit length again.
4. Project onto the artifact's 256 PCA components (`collector/ml/similarity.py`).
5. Normalise the result.

Cosine distance (`<=>`) ranks the vectors.

The choice comes from an offline check on the owner's DnB labels:

| Measure | Score | At random |
|---|---|---|
| Top-10 neighbours in the same category | 0.61 | 0.19 |
| Neighbours in the same or a neighbouring category | 0.80 | — |

The 256-dim PCA matched the full 1792 dims.

### The artifact

The artifact is versioned. The live version is `repositories/similarity.VERSION`, now `sim-1`. It lives at `s3://<audio-features bucket>/models/similarity/sim-1.npz`.

- **Contents.** The two array means, the PCA mean, and the components.
- **Fit sample.** The first 10 000 profiled videos ordered by `video_id`. Ids are random, so that is a sample across all styles.
- **Write-once.** A fit that finds the object already there does nothing.
- **New fits get a new version.** Vectors of two fits are not comparable. To fit again, bump the version: a new constant, a new key, a new backfill. Then delete the old rows.

## Storage

`audio_embeddings(video_id, version, embedding vector(256))`, one row per video and version (migration 49).

- **Extension.** pgvector must be created by the master user once ([`docs/ops/aurora.md`](../ops/aurora.md#pgvector-extension)).
- **Index.** None: a query scans one style exactly. DnB has ~10 k vectors (2026-11).
- **When to add one.** Add HNSW with the iterative scan when a style passes ~100 k vectors.

## Writes

The ML worker (`ml-jobs` queue) writes the vectors:

- **`score {video_ids}`.** The job every profiles POST sends. After the keep predictions, it embeds the job's videos. Before the artifact exists it skips them, and the backfill covers them.
- **`similarity_fit {version}`.** Fits and saves the artifact once, then starts the backfill chain.
- **`similarity_embed {version, after_video_id}`.** Embeds one page of 2 000 profiled videos, then enqueues the next page.

A message for a version other than the live one raises, so SQS redrives it to the DLQ.

Kick the backfill once after a deploy that introduces a version:

```bash
aws sqs send-message \
  --queue-url "$(aws sqs get-queue-url --queue-name clouder-prod-ml-jobs --query QueueUrl --output text)" \
  --message-body '{"type":"similarity_fit","version":"sim-1"}'
```

## Reads

There are two routes. Both are per user and both use one ranked SQL statement (`collector/similar_tracks.py`):

- `GET /tracks/{track_id}/similar` returns the seed's row, `profiled` and items.
- `GET /artists/{artist_id}/similar?style_id=` returns `profiled`, the style used, the artist's styles with profiled tracks, and items.

**Which tracks come back:**

- Tracks of the same style that have a vector of the live version.
- AI-flagged tracks never come back (`AI_FLAGGED_SQL`).
- At most 50.
- One track per video, chosen in this order: one the caller placed, else the earliest release.

**Track seed:**

- The seed track and every track on the seed's video are left out.
- The same artist's other tracks stay in.

**Artist seed:**

- Results are ranked by the centroid (`avg`) of the artist's non-AI profiled videos in the style.
- Every track crediting the artist is left out, and so is every track on those videos.

**Order:**

- The keep group comes first, then distance.
- A track is in the keep group if the caller placed it as a keep (a category, or an active STAGING bucket).
- Failing that, it is in the group if the caller never put it in DISCARD and the caller's keep model of the style predicts keep.
- A style without a model orders the caller's keeps first, then distance.

`discarded` marks a track that is only in DISCARD.

## SPA

- **Every player.** The broadcast icon left of the Spotify link (`SimilarLink`, the `links` slot of `PlayerCard`) opens `/similar/:trackId`.
  - The page shows the seed first, then the results, in the entity player (categories of the style, playlists).
  - It re-mounts for every seed.
- **Artist page.** The tracks section has "Tracks | Similar". A style picker appears when the artist has several profiled styles. The view and style live in the URL (`?view=similar&style=`).

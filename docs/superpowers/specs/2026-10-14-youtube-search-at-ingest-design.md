# YouTube search at ingest — design

**Date:** 2026-10-14
**Status:** Approved (owner delegated spec approval; brainstormed in chat 2026-10-14)

## Problem

A track is looked up on YouTube twice, late, and for different reasons:

- **Comments** (`comments-collect-worker`): on triage finalize, every promoted
  track gets a `ytmusicapi.search("artist - title", filter="videos")` and a
  strict token match (`providers/youtube/video_match.py`) to find a regular
  video to read comments from.
- **YouTube Music match** (`vendor-match-worker`): only when a track is added
  to a playlist, `search(filter="songs")` (fallback `videos`) scored by
  `vendor_match/scorer.py`; ≥ 0.92 auto, below → top-5 review, none → no_match.

Neither result feeds the other. In the 30 days to 2026-10-14 the comment path
ran ~300 searches (3 finalizes); the YT Music match ran once. Matches and the
review queue are not ready when a playlist is built.

## Goal

Search every new track on YouTube once, right after ingest (in parallel with
the Spotify search), and store both results: the YT Music song match and the
regular video for comments. Later stages reuse them instead of searching again.

## Decisions (from the brainstorm)

| Topic | Decision |
|---|---|
| Which tracks | New tracks (`created_at >= YOUTUBE_SEARCH_SINCE`) **plus** older tracks that sit in a user category or an IN_PROGRESS triage block. The rest of the archive (~156k) is not searched. |
| Comments | Not collected at ingest. Finalize still collects them, seeded with the stored video (no second search). |
| Threshold | Stays 0.92 (measured: 0.90 → 94.7 % precision, 27 wrong of 565; `docs/data/entity-resolution.md`). |
| API | ytmusicapi only. YouTube Data API `search.list` is capped at 100 calls/day by default — unusable at ingest volume (~12k tracks/week, backfill days up to ~50k). |
| Architecture | Approach A: search state on `clouder_tracks` + a dedicated sweep worker, mirroring the Spotify search (`spotify_searched_at`, claim, release, follow-up, ban resume). |
| Concurrency | SQS trigger cap 2 (AWS minimum; reserved concurrency 1 is rejected under a cap of 2 — deploy 2026-10-14), each worker paced by a configurable minimum interval. Usually one chain runs; worst case twice the per-worker rate. |

## Data

Migration: `clouder_tracks.youtube_searched_at timestamptz NULL` and a partial
index `ix_clouder_tracks_youtube_unsearched ON clouder_tracks (created_at DESC)
WHERE youtube_searched_at IS NULL`.

A track **needs a YouTube search** when `youtube_searched_at IS NULL` and any of:

- `created_at >= :since` (`YOUTUBE_SEARCH_SINCE`, the launch date);
- it is in a non-deleted category (`category_tracks` ⨝ `categories.deleted_at IS NULL`);
- it is in a bucket of an IN_PROGRESS, non-deleted triage block.

Newest first (`created_at DESC`).

State machine, exactly like Spotify:

- **claim** — one statement stamps `youtube_searched_at = :claimed_at` on the
  next candidates (`FOR UPDATE SKIP LOCKED`, repeated `IS NULL` on the outer
  UPDATE) and returns their search inputs (title, artists, length, album);
- **done** — after each track is persisted, `youtube_searched_at = :now`
  (a timestamp different from the claim), whatever the outcome;
- **release** — `SET youtube_searched_at = NULL WHERE youtube_searched_at = :claimed_at`
  hands back only rows the batch never finished (ban, deadline, crash).

Results go to existing tables:

| Outcome | Where |
|---|---|
| Song match ≥ 0.92 | `vendor_track_map` vendor `ytmusic`, `match_type='fuzzy'` |
| Candidates below 0.92 | `match_review_queue` (top 5, `pending`) |
| No candidates | `match_review_queue` `no_match` |
| Video for comments | `vendor_track_map` vendor **`youtube`**, `match_type='token'`, `confidence=1.000`, payload = raw result |

`vendor` is a free `varchar(32)`; PK is `(clouder_track_id, vendor)`. A track
already present in `vendor_track_map`/`match_review_queue` for `ytmusic` keeps
its row (the worker does not re-score it): the song step is skipped and only
the video is looked for.

## Worker: `youtube-search-worker`

Message `YoutubeSearchMessage {batch_size: int = 100 (1..500), resume: bool = false}`.

Triggers:

1. **After canonicalization** — `worker_handler` sends `{batch_size: 100}` next
   to the Spotify sweep (best-effort, never fails the run).
2. **Follow-up** — when the batch finishes and candidates remain, an immediate
   `{batch_size}` message.
3. **Resume** — during a ban, one delayed `{resume: true}` message re-arms
   itself until `blocked_until` (SQS delay ≤ 900 s).
4. **Manual kick** after deploy (runbook command) for the one-time backlog.

Loop per message:

1. If `vendor_rate_limits['ytmusic'].blocked_until > now`: a resume message
   re-enqueues itself delayed; a plain trigger is dropped. Return.
2. Claim `batch_size` tracks. None → return.
3. For each track: stop early when the Lambda has < 60 s left (release the
   rest, follow-up picks them up); wait so that consecutive requests are at
   least `YOUTUBE_SEARCH_MIN_INTERVAL_MS` apart (start: 2000 ms = 0.5 req/s);
   search; persist; stamp done.
4. Ban (see below): release, `set_vendor_blocked_until('ytmusic', now + YOUTUBE_SEARCH_BAN_SECONDS)`
   (default 3600 — quotas observed to reset hourly), enqueue a delayed resume, return.
5. Candidates remain → follow-up.

### Search for one track

1. `search("{artists} - {title}")` without a filter (dash form: better
   `videos` recall per the 2026-06-21 video-aware match design). From the
   results take `resultType == "song"` and `resultType == "video"`.
2. **Video for comments:** the first video whose title passes
   `video_matches(artists, title, video_title)` → `vendor_track_map` `youtube`.
3. **Song match** (skipped if the track already has a `ytmusic` row in either
   table): score the songs with `score_candidate`. Best ≥ threshold → match.
   Otherwise a second request `search(build_query(artists, title), filter="songs")`;
   if it returns no songs, `filter="videos"` (today's vendor-match behaviour).
   Score all; best ≥ threshold → match; any candidates → top-5 review;
   none → `no_match`.

Requests per track: 1, or 2–3 when the song is ambiguous.

### Ban and errors

- **Ban:** `YTMusicServerError` whose message carries `HTTP 429` or `HTTP 403`,
  or `YTMusicGatedError` → ban handling above.
- **Any other exception for one track:** log `youtube_search_result`
  `outcome=error`, stamp done, continue. Such a track is still searched later
  by the playlist path (it has no `ytmusic` row).

## Downstream changes

- **Comment worker:** when a message has no `video_id`, use the stored
  `youtube` video before running its own fallback search
  (`CommentsRepository.fetch_track_meta` returns it). Covers finalize and every
  other dispatch path.
- **Review accept** (`routes_playlists.py`): re-collect comments only when the
  track has no collected comments yet (today it re-collects from the accepted
  song video, where comments are often disabled).
- **Playlist add:** unchanged — `fetch_unmatched_match_inputs` already skips
  tracks with a `ytmusic` row in either table, so it only searches tracks the
  sweep has not reached.

## Observability

- Per track: `youtube_search_result` with `track_id`, `outcome`
  (`auto|review|no_match|error|video_only`), `confidence` (best score),
  `request_count`, `video_found`.
- Per batch: `youtube_search_completed` (`total_tracks`, `auto`, `review`,
  `no_match`, `errors`, `videos_found`), `youtube_search_paused`
  (`reason`, `retry_after`).
- New field names go into `ALLOWED_LOG_FIELDS` (otherwise `log_event` drops them).

## Infrastructure

Mirrors the Spotify worker: `aws_lambda_function.youtube_search_worker`
(timeout 900 s, memory 512 MB, no reserved concurrency), log group, queue +
DLQ (`maxReceiveCount = 10`, visibility ≥ timeout), DLQ depth alarm, event
source mapping with `batch_size = 1` and `maximum_concurrency =
var.youtube_search_max_concurrency` (validated 2–1000, default 2), role under
`clouder-role-boundary` (data API, DB secret, consume + requeue own queue).
Canonicalization role: `sqs:SendMessage` to the new queue, env
`YOUTUBE_SEARCH_QUEUE_URL`. Worker env: Aurora, `YOUTUBE_SEARCH_QUEUE_URL`,
`YOUTUBE_SEARCH_SINCE`, `YOUTUBE_SEARCH_MIN_INTERVAL_MS`,
`YOUTUBE_SEARCH_BAN_SECONDS`, `FUZZY_MATCH_THRESHOLD`.

The migration lands before the Lambdas (two-phase apply). README and
`docs/architecture.md` counts are updated (guarded by `test_readme.py`).

## Testing

- Unit (fake YTMusic): auto match from the first request; second request path;
  videos fallback; review; no_match; video picked/not picked; existing `ytmusic`
  row → video only; ban → release + blocked_until + delayed resume; paused on
  entry (resume re-arms, trigger dropped); per-track error; deadline release;
  pacing waits; follow-up only when candidates remain.
- Real Postgres: candidate rule (new / in category / in active block / archive
  excluded / finalized-only excluded), claim with SKIP LOCKED, release leaves
  done rows.
- Comment worker uses the stored video; review accept skips re-collection when
  comments exist.
- Infra guard tests (ESM cap) and README counts.

## Rollout

1. Deploy with 0.5 req/s.
2. Kick once; the backlog of needed old tracks (~1–2k) is the controlled probe
   of YouTube's limit from AWS.
3. Watch `youtube_search_result`/`youtube_search_paused`: ban signals, request
   rate achieved, outcome shares (auto / review / no_match / error), videos found.
4. Tune `YOUTUBE_SEARCH_MIN_INTERVAL_MS` by env, no code change.

## Non-goals

Lowering the threshold, batch review UI, comments at ingest, the full archive,
UI changes, Data API search.

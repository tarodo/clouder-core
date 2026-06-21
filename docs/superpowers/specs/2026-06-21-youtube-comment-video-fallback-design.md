# YouTube comment-video fallback — design

**Date:** 2026-06-21
**Status:** Approved (design phase)
**Builds on:** `2026-06-21-youtube-comments-collection-design.md` (already shipped, PR #186)

## Problem

Comment collection uses the per-track YT Music match `video_id`. For most tracks
that id is an "Art Track" (auto-generated `… - Topic` upload), which has comments
**disabled** — so collection almost always lands in status `disabled` and the
panel shows nothing. We want comments from a *regular* YouTube video of the same
track (user/official uploads usually have comments enabled).

## Decisions (resolved during brainstorming)

| Topic | Decision |
|---|---|
| How to find the regular video | **ytmusicapi `search(query, filter="videos")`** — unauthenticated InnerTube, no API key, no quota. Already used in `providers/ytmusic/lookup.py`. (Reading comments still uses the Data API `commentThreads.list`, 1 unit.) |
| When to search | **Fallback**: collect from the Art Track first; only if it raises `CommentsDisabledError` do we resolve and collect from a regular video. |
| Candidate selection | Score candidates with the existing fuzzy scorer (`vendor_match/scorer.py`); keep those at/above `FUZZY_MATCH_THRESHOLD` (same threshold as matching); exclude the Art Track id; try the **top 3** by score in order until one yields comments. |
| Extensibility | Add an **optional** `resolve_alternate_videos(...)` to the `CommentProvider` protocol. YouTube implements it; other platforms don't (return `[]`). The worker stays platform-agnostic. |
| Storage | **No schema change.** `comment_collections.external_video_id` now stores the video we actually collected from (Art Track or resolved regular video). |

### What does NOT change

- The ytmusic match `video_id` in `vendor_track_map` is untouched. Playlist
  publishing to YouTube Music keeps using the Art Track (correct there).
- Comments get their own, independent `external_video_id`. The two may now
  differ: a track can show a YT Music match badge (→ `music.youtube.com` Art
  Track) and a comments block whose "Watch on YouTube" link points to a
  different regular `youtube.com` video.

## Architecture

### Resolver (YouTube-specific, reuses existing pieces)

Extend `YouTubeCommentProvider` (`src/collector/providers/youtube/comments.py`)
with:

```python
def resolve_alternate_videos(
    self, *, artist: str, title: str, duration_ms: int | None, exclude_video_id: str
) -> list[str]:
    """Ordered (best-first) regular-YouTube video ids that likely have comments.
    Empty list when nothing clears the score threshold."""
```

Implementation reuses the ytmusic stack:
- `build_query(artist, title)` (`providers/ytmusic/normalize.py`).
- An injectable ytmusicapi client (mirror `YTMusicLookup`'s `client_factory`
  pattern so the module imports without the package and tests inject a fake).
- `client.search(query, filter="videos", limit=N)` → raw results.
- `result_to_ref(raw)` (`providers/ytmusic/normalize.py`) → `VendorTrackRef`.
- `score_candidate(candidate=ref, artist=, title=, duration_ms=, album=None)`
  (`vendor_match/scorer.py`) → `FuzzyScore`.
- Keep refs with `score.total >= threshold` (threshold injected, default
  `get_vendor_match_settings().fuzzy_match_threshold`), drop any whose
  `vendor_track_id == exclude_video_id`, sort by score desc, return the top 3
  `vendor_track_id`s.

The provider now needs both the Data API session/key (for reads) and the
ytmusic client/threshold (for resolution). The registry builder
(`comments/registry.py` `_build_youtube`) constructs it with sensible defaults;
all collaborators stay injectable for tests.

### Protocol change

`src/collector/providers/base.py` — add to `CommentProvider`:
```python
def resolve_alternate_videos(
    self, *, artist: str, title: str, duration_ms: int | None, exclude_video_id: str
) -> list[str]: ...
```
Platforms without this capability return `[]`. (The worker guards with
`getattr`/capability check so a provider that doesn't implement it is fine.)

### Worker flow (`comments_collect_handler.py`)

Per record:
1. Fetch track metadata (artist, title, duration_ms) for `msg.track_id` (new
   repo read — see below).
2. `comments = provider.collect(msg.video_id, limit=100)` (Art Track).
3. On `CommentsDisabledError`:
   - `alts = provider.resolve_alternate_videos(artist=, title=, duration_ms=, exclude_video_id=msg.video_id)`.
   - For each `alt` in `alts` (≤3), `collect(alt)`:
     - non-empty → store as `collected`, set `external_video_id = alt`; stop.
     - `CommentsDisabledError` → try next.
     - empty list → remember "saw empty", try next.
   - After the loop with no comments found: `empty` if any candidate returned an
     empty (comments-enabled, zero) list, else `disabled`.
   - No candidates at all → `disabled`.
4. Other outcomes unchanged: primary non-empty → `collected`; primary empty →
   `empty`; `CommentPlatformDisabledError` / generic exception → `failed`
   (caught, never re-raised — one-request-budget invariant preserved per
   alternate attempt too; cap total commentThreads calls at 1 + 3).

`external_video_id` is updated only when we collect from an alternate; otherwise
it stays the primary (set at `start_collection`).

### Repository changes (`comments/repository.py`)

- New read: `fetch_track_meta(track_ids) -> dict[track_id, TrackMeta]` (artist
  string, title, duration_ms). NOTE: the existing
  `playlists_repository.fetch_unmatched_match_inputs` cannot be reused — it
  anti-joins already-matched tracks, and our tracks are matched. Add a plain
  metadata read (join `clouder_tracks` + artists, same column expressions as
  `fetch_unmatched_match_inputs` minus the anti-joins). Decide placement:
  comments repo vs a shared helper — keep it in the comments repo for cohesion
  unless an identical read already exists.
- Extend `store_comments(...)` with an optional `external_video_id: str | None`
  param; when provided, the UPDATE also sets `external_video_id`.

## Frontend

No change required. `external_video_id` now points at the watchable video, so the
existing "Watch on YouTube" link in `CommentsPanel` improves automatically.

## Quota / cost

- Search: 0 Data API units (ytmusicapi).
- Reads: 1 unit for the Art Track + up to 3 for alternates = ≤4 units per track
  in the worst case (only tracks whose Art Track is disabled incur the extra
  reads). Still well within 10000/day.

## Testing

- **Resolver** (`test_youtube_comment_provider` or a new file): fake ytmusic
  client returns videos results → maps + scores → returns top-3 ids in score
  order; excludes the art-track id; drops below-threshold; empty when nothing
  clears threshold; tolerates malformed results.
- **Worker** (`test_comments_collect_handler`): art-track `disabled` →
  resolver returns `[a, b]` → `a` disabled, `b` collected → status `collected`,
  `external_video_id == b`; resolver returns `[]` → `disabled`; all alternates
  disabled → `disabled`; an alternate returns empty while none have comments →
  `empty`. Primary-has-comments path unchanged (no resolver call).
- **Repository**: `fetch_track_meta` maps rows; `store_comments` updates
  `external_video_id` when passed.

## Non-goals (YAGNI)

- No new persisted column for the comment-video (reuse `external_video_id`).
- No re-collection/backfill of already-`disabled` collections from the previous
  release (they re-run only on a new match event; a one-off backfill, if wanted,
  is separate).
- No alternate-video resolution for non-YouTube platforms.
- No manual "pick the comment video" UI (could be added later, like the match
  review popover).

## Open items for the implementation plan

- Confirm `result_to_ref` populates `duration_ms` for `filter="videos"` results
  (videos may report duration differently than songs); if not, relax the
  duration component or parse it.
- Pin exact column expressions for `fetch_track_meta` from
  `fetch_unmatched_match_inputs`.
- Confirm the worker package includes `ytmusicapi` (it does — shared lambda zip,
  used by the vendor_match worker).

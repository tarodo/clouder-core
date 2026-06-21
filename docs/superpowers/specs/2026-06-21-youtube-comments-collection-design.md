# YouTube comments collection — design

**Date:** 2026-06-21
**Status:** Approved (design phase)
**Author:** brainstorming session

## Goal

When a playlist track is matched to a YouTube video, automatically collect up to
100 top-level comments from that video, store them in our database, and show the
first 5 on the track panel under the label and artist descriptions.

The comment-collection layer must be extensible: new platforms (e.g. SoundCloud,
TikTok) can be added later without reworking storage, dispatch, or the read API.

## Decisions (resolved during brainstorming)

| Topic | Decision |
|---|---|
| Source of the video | Reuse the existing per-track YT Music match `video_id`. We do **not** build a separate YouTube search/match flow — the match flow (auto-match + manual URL paste via `YtMusicReviewPopover`) already exists. |
| Trigger | Automatic when a track gains a `matched` status, processed **async** via a dedicated SQS worker. |
| Fetch mechanism | Official **YouTube Data API v3** `commentThreads.list`, using a shared server-side `YOUTUBE_API_KEY` (developer key). |
| Quota | One request per video: `maxResults=100`, single page, `part=snippet` = 1 quota unit. Default free quota 10000/day ≈ 10000 videos/day. |
| Collection cadence | Collect **once** per `(track_id, platform, video_id)`. Re-collect only if the resolved `video_id` changes. No manual refresh button (YAGNI). |
| Auth | A shared developer key, **not** user OAuth — collection runs in the background for any matched track and must not depend on a user having connected their Google account. |

### Why a shared developer key (not existing OAuth)

The existing `youtube_data_api_client.py` uses an **OAuth bearer token** and only
for write operations (playlist publish). The per-track *search* uses
unauthenticated `ytmusicapi` (no key, no quota). There is **no** developer key in
the project today. Reading public comments via `commentThreads.list` works with a
developer key and needs no user consent, which fits a background per-match job.
A new secret `YOUTUBE_API_KEY` is added following the existing `gemini_api_key` /
`tavily_api_key` pattern in `src/collector/settings.py` (env var or
`*_SSM_PARAMETER`).

## Extensibility architecture (core seam)

Comment collection is keyed by **platform** (`"youtube"`), which is a different
axis from the export-vendor `ProviderBundle` (where `vendor = "ytmusic"`).
Therefore comments get their **own provider registry keyed by platform**, kept
separate from `ProviderBundle`.

```python
# src/collector/providers/base.py
@dataclass(frozen=True)
class CollectedComment:        # platform-agnostic
    external_id: str
    author_name: str
    author_avatar_url: str | None
    text: str
    like_count: int
    published_at: datetime | None
    rank: int                  # 0..99, preserves API order

@runtime_checkable
class CommentProvider(Protocol):
    platform: str
    def collect(self, video_ref: str, *, limit: int = 100) -> list[CollectedComment]: ...
```

- `src/collector/providers/youtube/comments.py` → `YouTubeCommentProvider`:
  one page, `maxResults=100`, `part=snippet`, ordered by relevance. Injectable
  `requests` session for tests (mirrors `youtube_data_api_client.py`).
- A `comment_providers` registry: `dict[str, CommentProvider]` (platform → provider),
  gated by `VENDORS_ENABLED` like the existing registry.
- Adding a future platform = one new provider class + one registry entry. Storage,
  dispatch, worker, and read API are platform-agnostic (carry a `platform` column).

## Data model (Alembic migration)

Two tables. The collection row records state so we never re-fetch and never retry
videos that legitimately have zero comments.

### `comment_collections` — one row per (track, platform)

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `track_id` | uuid | FK → tracks |
| `platform` | text | `"youtube"` |
| `external_video_id` | text | the matched `video_id` collected from |
| `status` | text | `pending` \| `collected` \| `empty` \| `disabled` \| `failed` |
| `comment_count` | int | number stored (0 for empty/disabled) |
| `error` | text null | short message on `failed` |
| `collected_at` | timestamptz null | set when terminal |
| `created_at` / `updated_at` | timestamptz | |

UNIQUE `(track_id, platform)`.

### `external_comments` — the comments

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | |
| `collection_id` | uuid | FK → comment_collections (ON DELETE CASCADE) |
| `platform` | text | denormalized for query convenience |
| `external_comment_id` | text | platform comment id |
| `author_name` | text | |
| `author_avatar_url` | text null | |
| `text` | text | |
| `like_count` | int | |
| `published_at` | timestamptz null | |
| `rank` | int | 0..99, preserves API order |
| `created_at` | timestamptz | |

UNIQUE `(collection_id, external_comment_id)`.

Comments key off `track_id` (the matched video is a property of the track via the
YT Music match), **not** `playlist_track`. The same track in multiple playlists
shares one collection.

Migration follows the existing pattern in `alembic/versions/` (`upgrade()` /
`downgrade()` with `op.create_table` / `op.create_index`).

## Async flow

```
match becomes "matched"  ──►  try_dispatch_comment_collection(track_id, video_id, platform)
   (auto or manual)            │  best-effort, swallows exceptions
                               │  - skip if comment_collections row already
                               │    collected for this video_id
                               │  - insert pending row
                               │  - send SQS {track_id, platform, video_id, collection_id}
                               ▼
                     comments-collect SQS queue
                               ▼
                  comments_collect_handler (Lambda)
                     - provider.collect(video_id, limit=100)
                     - upsert external_comments
                     - update collection: collected | empty | disabled | failed
```

### Dispatch hook points

`try_dispatch_comment_collection(...)` is called inline (best-effort, never raises
— mirrors `_enqueue_ytmusic` at `curation_handler.py:383` and
`label_enrichment/auto_dispatch.py`) from **both** paths that transition a track
to `matched`:

1. **Manual accept** — `_handle_resolve_match` → `repo.resolve_review_accept(...)`
   (`curation_handler.py:349`). User pasted / picked a URL.
2. **Auto match** — the vendor_match worker, where a match row is written with
   status `matched` (`src/collector/vendor_match/`, `vendor_match_handler.py`).

The dispatcher reads the resolved `video_id` from the matched row (same source as
`fetch_ytmusic_status` in `curation/playlists_repository.py`).

### Worker semantics

`comments_collect_handler.py` (SQS-driven, batch of records — same shape as
`label_enrichment_handler.py`):

- `provider.collect(video_id, limit=100)` → list of `CollectedComment`.
- Upsert into `external_comments`; set `comment_collections.status`:
  - results → `collected`, `comment_count = n`
  - empty list → `empty`, `comment_count = 0`
  - YouTube `commentsDisabled` (HTTP 403) → `disabled`
  - any other error → `failed`, `error` set, logged
- Best-effort: a failure updates the collection row and is logged; it never
  cascades into the add/resolve request.

### New infrastructure (Terraform)

- SQS queue `comments-collect` (+ DLQ consistent with existing queues).
- Worker Lambda + ESM mapping to the queue.
- IAM: CloudWatch Logs write, RDS Data API, Secrets/SSM read (`YOUTUBE_API_KEY`).
- Grant the curation Lambda permission to send to the new queue.

## Read API (for the frontend)

`GET /tracks/{id}/comments?platform=youtube&limit=5`

Response:

```json
{
  "status": "collected",
  "comment_count": 42,
  "video_url": "https://www.youtube.com/watch?v=...",
  "comments": [
    {
      "author_name": "...",
      "author_avatar_url": "...",
      "text": "...",
      "like_count": 12,
      "published_at": "2025-..."
    }
  ]
}
```

Registered in the **three required places** (per the route-registration rule):

1. `_ROUTE_TABLE` in `curation_handler.py` (with a comments repo factory).
2. `scripts/generate_openapi.py` ROUTES, then regenerate `docs/api/openapi.yaml`
   and `frontend/src/api/schema.d.ts`.
3. `infra/curation_routes_*.tf`.

## Frontend

- `useTrackComments(trackId)` — TanStack Query GET hook (`limit=5`), pattern from
  `usePlaylistDetail.ts`.
- `<CommentsPanel>` rendered **after `<ArtistsPanel>`** in
  `PlaylistPlayerPanel.tsx` (~line 236), under label + artist descriptions.
- States:
  - `pending` → "Collecting comments…" placeholder
  - `empty` / `disabled` → "No comments" (quiet)
  - `collected` → up to 5 cards (avatar, author, text, like count, relative date)
    + a "Watch on YouTube (N)" link to `video_url`
  - `failed` → hidden (no error noise in the panel)
- i18n: new keys under `comments.*` in `frontend/src/i18n/en.json` (EN-only now;
  RU lands with the general iter-2b RU pass).

## Testing

**Backend (pytest):**
- `YouTubeCommentProvider`: parse `commentThreads.list` JSON → `CollectedComment`
  (fake injected session); empty result; `commentsDisabled` handling.
- Dispatcher: skip when already collected for the same `video_id`; re-dispatch when
  `video_id` changed; never raises.
- Worker: status transitions `collected` / `empty` / `disabled` / `failed`;
  comment upsert idempotency on UNIQUE `(collection_id, external_comment_id)`.
- Repository: read query for `GET /tracks/{id}/comments`.

**Frontend (vitest):**
- `CommentsPanel` renders each state (loading, pending, empty, collected list of 5,
  failed hidden).
- `useTrackComments` query hook.

## Non-goals (YAGNI)

- No separate YouTube search/match flow (reuse ytmusic match).
- No comment replies / threads (top-level comments only).
- No pagination beyond the first 100 / first 5 shown.
- No manual "refresh comments" button.
- No comment moderation, sentiment, or analytics.
- No other platforms implemented now — only the extensible seam is built.

## Open items for the implementation plan

- Pin the exact line in the vendor_match worker where a `matched` row is written
  (the auto-match dispatch hook).
- Confirm the matched-row table/columns read by the dispatcher to obtain `video_id`
  (shared with `fetch_ytmusic_status`).
- Confirm DLQ + alarm conventions used by the existing queues to mirror them.

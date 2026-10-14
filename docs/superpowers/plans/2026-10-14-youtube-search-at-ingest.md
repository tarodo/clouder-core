# YouTube search at ingest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Search every new (and every still-needed old) track on YouTube once, right after ingest, storing the YT Music song match and the comments video so later stages reuse them.

**Architecture:** A `youtube_searched_at` stamp on `clouder_tracks` drives a claim/done/release sweep (same shape as the Spotify search). A dedicated single-concurrency Lambda `youtube-search-worker` paces ytmusicapi requests, writes outcomes into the existing `vendor_track_map` / `match_review_queue`, pauses on bans via `vendor_rate_limits`, and chains follow-ups. Canonicalization triggers it; the comment worker and review accept reuse its results.

**Tech Stack:** Python 3.12, ytmusicapi, RDS Data API (Aurora PostgreSQL), Alembic, SQS + Lambda, Terraform, pytest (+ real-Postgres `tests/db`).

**Spec:** `docs/superpowers/specs/2026-10-14-youtube-search-at-ingest-design.md`

## Global Constraints

- Runtime DB access only through the RDS Data API (`self._data_api.execute`); never psycopg in `src/collector`.
- Threshold stays `FUZZY_MATCH_THRESHOLD` default `0.92`.
- Vendor strings: song match `ytmusic`, comments video `youtube`; video rows `match_type='token'`, `confidence=1.000`.
- Starting pace `YOUTUBE_SEARCH_MIN_INTERVAL_MS=2000`; ban pause `YOUTUBE_SEARCH_BAN_SECONDS=3600`; SQS delay ≤ 900 s; deadline margin 60 s.
- `YOUTUBE_SEARCH_SINCE` default `2026-10-15T00:00:00Z` (first run = only old needed tracks: the controlled probe).
- Message `YoutubeSearchMessage {batch_size: 1..500 = 100, resume: bool = false}`.
- Exactly one worker: `reserved_concurrent_executions = 1`; ESM `maximum_concurrency` via a validated variable (2–1000).
- New log field names must be added to `ALLOWED_LOG_FIELDS`.
- Commits: Conventional Commits via caveman style, no AI attribution. Tests: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest` (worktree has no venv); DB tests need `TEST_DATABASE_URL` on a throwaway `postgres:16` (port 55513) after `alembic upgrade head`.

## Review Focus

1. A claim racing a second worker (two triggers at once): rows must never be searched twice — the claim's `SKIP LOCKED` + repeated `IS NULL` (pinned by `test_second_claim_takes_nothing_already_claimed`).
2. A ban arriving mid-batch: already persisted tracks stay done, the rest return to NULL, exactly one delayed resume is sent (pinned by `test_ban_mid_batch_releases_rest_and_schedules_resume`).
3. Archive tracks (old, not in a category or active block) must never be claimed (pinned by `test_claim_skips_the_archive`).
4. A track that already has a `ytmusic` review/no_match row must not get a second review row (pinned by `test_existing_ytmusic_row_searches_video_only`).
5. An empty title/artist or odd unicode must not crash the batch — it becomes `outcome=error` or `no_match` and the sweep continues (pinned by `test_generic_error_marks_done_and_continues`).

---

## File Structure

- `alembic/versions/20261014_37_youtube_searched_at.py` — column + partial index.
- `src/collector/db_models.py` — mirror the column/index on `ClouderTrack`.
- `src/collector/repositories/youtube_search.py` — `YoutubeSearchMixin`: claim / mark done / release / has-candidates.
- `src/collector/repositories/__init__.py` — compose the mixin.
- `src/collector/youtube_search/__init__.py`, `src/collector/youtube_search/search.py` — pure per-track search (no DB, no SQS).
- `src/collector/youtube_search_handler.py` — the Lambda: sweep, pacing, persistence, ban, follow-up.
- `src/collector/schemas.py`, `src/collector/settings.py`, `src/collector/logging_utils.py` — message, settings, log fields.
- `src/collector/worker_handler.py` — trigger after canonicalization.
- `src/collector/comments/repository.py`, `src/collector/comments_collect_handler.py`, `src/collector/curation/routes_playlists.py` — reuse the stored video; no re-collect on accept.
- `infra/{main,variables,sqs,lambda,lambda_roles,logging}.tf` — Lambda, queue, DLQ, role, alarm, trigger permission.
- Docs: `README.md` counts, `docs/architecture.md`, `docs/data/entity-resolution.md`, `docs/ops/runbook.md`.
- Tests: `tests/db/test_youtube_search_pg.py`, `tests/unit/test_youtube_search.py`, `tests/unit/test_youtube_search_handler.py`, updates in comment/accept tests.

---

### Task 1: Search state column and repository

**Files:**
- Create: `alembic/versions/20261014_37_youtube_searched_at.py`
- Modify: `src/collector/db_models.py` (ClouderTrack)
- Create: `src/collector/repositories/youtube_search.py`
- Modify: `src/collector/repositories/__init__.py`
- Test: `tests/db/test_youtube_search_pg.py`

**Interfaces:**
- Produces on `ClouderRepository`:
  - `claim_tracks_for_youtube_search(limit: int, claimed_at: datetime, since: datetime) -> list[dict]` — rows `{id, title, length_ms, album_title, artists, has_ytmusic}`, newest first.
  - `mark_youtube_searched(track_id: str, at: datetime) -> None`
  - `release_youtube_search_claim(claimed_at: datetime) -> int`
  - `has_tracks_needing_youtube_search(since: datetime) -> bool`
  - existing: `get_vendor_blocked_until(vendor)`, `set_vendor_blocked_until(vendor, until, now)`, `upsert_vendor_match(cmd)`, `insert_review_candidate(...)`, `mark_no_match(...)`.

- [ ] **Step 1: Write the failing pg tests** — `tests/db/test_youtube_search_pg.py`:

```python
"""YouTube search state on real PostgreSQL: who is searched, claims, release."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from collector.repositories import ClouderRepository

SINCE = datetime(2026, 10, 15, tzinfo=UTC)
T0 = datetime(2026, 10, 16, 12, tzinfo=UTC)


def _seed(pg) -> None:
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('open', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now()), ('done', 'u1', 'st', 'B2', '2026-09-26', '2026-10-02',"
        " 'FINALIZED', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('b-open', 'open', 'NEW', now()), ('b-done', 'done', 'NEW', now())",
    ]:
        pg.execute(sql)


def _track(pg, tid: str, created: datetime) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " created_at, updated_at) VALUES (:id, :id, :id, 'st', 200000, :c, :c)",
        {"id": tid, "c": created},
    )


def _world(pg) -> ClouderRepository:
    _seed(pg)
    old = SINCE - timedelta(days=30)
    _track(pg, "new-1", SINCE + timedelta(hours=1))
    _track(pg, "new-2", SINCE + timedelta(hours=2))
    _track(pg, "in-cat", old)
    _track(pg, "in-open", old)
    _track(pg, "in-done", old)
    _track(pg, "archive", old)
    pg.execute("INSERT INTO category_tracks (category_id, track_id, added_at) VALUES ('cat', 'in-cat', now())")
    pg.execute(
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)"
        " VALUES ('b-open', 'in-open', now()), ('b-done', 'in-done', now())"
    )
    return ClouderRepository(pg)


def test_claim_takes_new_and_needed_old_newest_first(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    assert [r["id"] for r in rows][:2] == ["new-2", "new-1"]
    assert {r["id"] for r in rows} == {"new-1", "new-2", "in-cat", "in-open"}


def test_claim_skips_the_archive(pg) -> None:
    repo = _world(pg)
    ids = {r["id"] for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)}
    assert "archive" not in ids and "in-done" not in ids


def test_second_claim_takes_nothing_already_claimed(pg) -> None:
    repo = _world(pg)
    first = repo.claim_tracks_for_youtube_search(limit=2, claimed_at=T0, since=SINCE)
    second = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0 + timedelta(seconds=1), since=SINCE)
    assert not {r["id"] for r in first} & {r["id"] for r in second}


def test_release_hands_back_only_unfinished_rows(pg) -> None:
    repo = _world(pg)
    rows = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)
    repo.mark_youtube_searched(track_id=rows[0]["id"], at=T0 + timedelta(seconds=5))
    released = repo.release_youtube_search_claim(claimed_at=T0)
    assert released == len(rows) - 1
    again = repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0 + timedelta(minutes=1), since=SINCE)
    assert rows[0]["id"] not in {r["id"] for r in again}
    assert len(again) == len(rows) - 1


def test_has_tracks_and_ytmusic_flag(pg) -> None:
    repo = _world(pg)
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at)"
        " VALUES ('r1', 'new-1', 'ytmusic', '[]'::jsonb, 'no_match', now())"
    )
    assert repo.has_tracks_needing_youtube_search(since=SINCE)
    rows = {r["id"]: r for r in repo.claim_tracks_for_youtube_search(limit=10, claimed_at=T0, since=SINCE)}
    assert rows["new-1"]["has_ytmusic"] is True
    assert rows["new-2"]["has_ytmusic"] is False
    assert rows["new-1"]["artists"] == ""
    assert not repo.has_tracks_needing_youtube_search(since=SINCE)
```

- [ ] **Step 2: Run to verify it fails**

Run: `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55513/postgres $PYTEST -q tests/db/test_youtube_search_pg.py`
Expected: FAIL — `column "youtube_searched_at" does not exist` / `AttributeError: claim_tracks_for_youtube_search`.

- [ ] **Step 3: Migration** — `alembic/versions/20261014_37_youtube_searched_at.py`:

```python
"""track YouTube search state on clouder_tracks

The YouTube search worker stamps youtube_searched_at the way the Spotify
worker stamps spotify_searched_at: claim, done, release. The partial index
serves the sweep's "not searched yet, newest first" lookup.

Revision ID: 20261014_37
Revises: 20261010_36
Create Date: 2026-10-14 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261014_37"
down_revision = "20261010_36"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "clouder_tracks",
        sa.Column("youtube_searched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_clouder_tracks_youtube_unsearched",
        "clouder_tracks",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("youtube_searched_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_clouder_tracks_youtube_unsearched", table_name="clouder_tracks")
    op.drop_column("clouder_tracks", "youtube_searched_at")
```

Model (`db_models.py`, `ClouderTrack`): add after `spotify_searched_at`:

```python
    youtube_searched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```
and to `__table_args__`:
```python
        Index(
            "ix_clouder_tracks_youtube_unsearched",
            text("created_at DESC"),
            postgresql_where=text("youtube_searched_at IS NULL"),
        ),
```

- [ ] **Step 4: Repository** — `src/collector/repositories/youtube_search.py`:

```python
"""YouTube search state: which tracks to search, claims, done stamps, release."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import RepositoryBase

# Tracks worth a YouTube search: new since the launch, or older ones a user is
# working with (a category, or a triage block still in progress). The archive
# is left alone. A UNION of three small id sets keeps the lookup off a scan of
# every unsearched archive row.
_CANDIDATE_IDS = """
    SELECT id FROM clouder_tracks
    WHERE youtube_searched_at IS NULL AND created_at >= :since
    UNION
    SELECT ct.track_id FROM category_tracks ct
    JOIN categories c ON c.id = ct.category_id
    WHERE c.deleted_at IS NULL
    UNION
    SELECT tbt.track_id FROM triage_bucket_tracks tbt
    JOIN triage_buckets b ON b.id = tbt.triage_bucket_id
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
    WHERE tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL
"""


class YoutubeSearchMixin(RepositoryBase):
    def claim_tracks_for_youtube_search(
        self, limit: int, claimed_at: datetime, since: datetime
    ) -> list[dict[str, Any]]:
        """Stamp the next *limit* candidates with *claimed_at* and return their
        search inputs, in one statement (SKIP LOCKED + repeated IS NULL, as the
        Spotify claim). `has_ytmusic` marks tracks that already have a YT Music
        match, review or no_match row: only their video is still looked for."""
        return self._data_api.execute(
            f"""
            WITH claimed AS (
                UPDATE clouder_tracks
                SET youtube_searched_at = :claimed_at
                WHERE id IN (
                    SELECT id FROM clouder_tracks
                    WHERE id IN ({_CANDIDATE_IDS})
                      AND youtube_searched_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                )
                  AND youtube_searched_at IS NULL
                RETURNING id, title, length_ms, album_id, created_at
            )
            SELECT c.id, c.title, c.length_ms, alb.title AS album_title,
                   COALESCE(string_agg(DISTINCT a.name, ', '), '') AS artists,
                   (EXISTS (SELECT 1 FROM vendor_track_map v
                            WHERE v.clouder_track_id = c.id AND v.vendor = 'ytmusic')
                    OR EXISTS (SELECT 1 FROM match_review_queue q
                               WHERE q.clouder_track_id = c.id AND q.vendor = 'ytmusic'))
                       AS has_ytmusic
            FROM claimed c
            LEFT JOIN clouder_track_artists ta ON ta.track_id = c.id
            LEFT JOIN clouder_artists a ON a.id = ta.artist_id
            LEFT JOIN clouder_albums alb ON alb.id = c.album_id
            GROUP BY c.id, c.title, c.length_ms, alb.title, c.created_at
            ORDER BY c.created_at DESC
            """,
            {"limit": limit, "claimed_at": claimed_at, "since": since},
        )

    def mark_youtube_searched(self, track_id: str, at: datetime) -> None:
        """Done: replace the claim stamp so a release leaves this row alone."""
        self._data_api.execute(
            "UPDATE clouder_tracks SET youtube_searched_at = :at WHERE id = :id",
            {"id": track_id, "at": at},
        )

    def release_youtube_search_claim(self, claimed_at: datetime) -> int:
        """Hand back rows still carrying the claim stamp (ban, deadline, crash)."""
        rows = self._data_api.execute(
            """
            UPDATE clouder_tracks SET youtube_searched_at = NULL
            WHERE youtube_searched_at = :claimed_at
            RETURNING id
            """,
            {"claimed_at": claimed_at},
        )
        return len(rows)

    def has_tracks_needing_youtube_search(self, since: datetime) -> bool:
        rows = self._data_api.execute(
            f"""
            SELECT 1 FROM clouder_tracks
            WHERE id IN ({_CANDIDATE_IDS}) AND youtube_searched_at IS NULL
            LIMIT 1
            """,
            {"since": since},
        )
        return bool(rows)
```

`repositories/__init__.py`: `from .youtube_search import YoutubeSearchMixin` and add `YoutubeSearchMixin,` to the `ClouderRepository` bases after `SpotifySearchMixin`.

Note: `has_ytmusic` may come back from the Data API as a Python bool; the pg harness also returns bool.

- [ ] **Step 5: Run to verify pass**

Run: `alembic upgrade head` (PYTHONPATH=src, ALEMBIC_DATABASE_URL on port 55513) then the Step 2 command. Expected: 5 passed. Also `$PYTEST -q tests/unit/test_raw_sql_parses.py` → pass.

- [ ] **Step 6: Commit** — `feat(db): track YouTube search state on tracks`.

---

### Task 2: Per-track search (pure)

**Files:**
- Create: `src/collector/youtube_search/__init__.py` (empty docstring module), `src/collector/youtube_search/search.py`
- Test: `tests/unit/test_youtube_search.py`

**Interfaces:**
- Produces: `TrackQuery(artists: str, title: str, duration_ms: int | None, album: str | None, need_song: bool)`; `TrackSearchResult` with `video: VendorTrackRef | None`, `match: tuple[VendorTrackRef, FuzzyScore] | None`, `review: list[tuple[VendorTrackRef, FuzzyScore]]`, `request_count: int`, `song_searched: bool`, properties `outcome -> str` (`auto|review|no_match|video_only`) and `best_score -> float | None`; `search_track(client, q, *, threshold: float, pace: Callable[[], None]) -> TrackSearchResult`; `is_ban(exc: BaseException) -> bool`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_youtube_search.py`:

```python
from __future__ import annotations

import pytest
from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError

from collector.youtube_search.search import TrackQuery, is_ban, search_track


def song(vid, title="Lost Track", artist="Guri", seconds=200, album="Lost EP"):
    return {"resultType": "song", "videoId": vid, "title": title,
            "artists": [{"name": artist}], "duration_seconds": seconds, "album": {"name": album}}


def video(vid, title="Guri - Lost Track (Official Video)", channel="Some Label"):
    return {"resultType": "video", "videoId": vid, "title": title,
            "artists": [{"name": channel}], "duration_seconds": 205}


class FakeClient:
    def __init__(self, by_filter):
        self.by_filter = by_filter  # {None: [...], "songs": [...], "videos": [...]}
        self.calls = []

    def search(self, query, filter=None, limit=20):  # noqa: A002 - ytmusicapi signature
        self.calls.append((query, filter))
        return self.by_filter.get(filter, [])


Q = TrackQuery(artists="Guri", title="Lost Track", duration_ms=200_000, album="Lost EP", need_song=True)


def run(client, q=Q):
    paces = []
    res = search_track(client, q, threshold=0.92, pace=lambda: paces.append(1))
    return res, paces


def test_song_and_video_from_one_request() -> None:
    res, paces = run(FakeClient({None: [song("s1"), video("v1")]}))
    assert res.outcome == "auto" and res.match[0].vendor_track_id == "s1"
    assert res.video.vendor_track_id == "v1"
    assert res.request_count == 1 and len(paces) == 1


def test_ambiguous_first_answer_tries_songs_filter() -> None:
    client = FakeClient({None: [song("x", title="Other Thing")], "songs": [song("s2")]})
    res, paces = run(client)
    assert client.calls[1] == ("Guri Lost Track", "songs")
    assert res.outcome == "auto" and res.match[0].vendor_track_id == "s2"
    assert res.request_count == 2 and len(paces) == 2


def test_no_songs_falls_back_to_videos_and_reviews() -> None:
    client = FakeClient({None: [], "songs": [], "videos": [video("v9")]})
    res, _ = run(client)
    assert [c[1] for c in client.calls] == [None, "songs", "videos"]
    assert res.outcome == "review" and res.review[0][0].vendor_track_id == "v9"


def test_nothing_anywhere_is_no_match() -> None:
    res, _ = run(FakeClient({}))
    assert res.outcome == "no_match" and res.video is None and res.best_score is None


def test_existing_ytmusic_row_searches_video_only() -> None:
    q = TrackQuery("Guri", "Lost Track", 200_000, None, need_song=False)
    client = FakeClient({None: [song("x", title="Nope"), video("v1")]})
    res, _ = run(client, q)
    assert res.outcome == "video_only" and res.video.vendor_track_id == "v1"
    assert res.request_count == 1 and res.match is None and res.review == []


def test_remix_video_is_not_the_original() -> None:
    res, _ = run(FakeClient({None: [song("s1"), video("v1", title="Guri - Lost Track (Bob Remix)")]}))
    assert res.video is None


@pytest.mark.parametrize(
    ("exc", "ban"),
    [
        (YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n"), True),
        (YTMusicServerError("Server returned HTTP 403: Forbidden.\n"), True),
        (YTMusicGatedError("confirm you're not a bot"), True),
        (YTMusicServerError("Server returned HTTP 500: Internal Server Error.\n"), False),
        (ValueError("bad"), False),
    ],
)
def test_is_ban(exc, ban) -> None:
    assert is_ban(exc) is ban
```

- [ ] **Step 2: Run to verify it fails** — `$PYTEST -q tests/unit/test_youtube_search.py` → `ModuleNotFoundError: collector.youtube_search`.

- [ ] **Step 3: Implement** — `src/collector/youtube_search/__init__.py`: `"""YouTube search at ingest (see docs/superpowers/specs/2026-10-14-youtube-search-at-ingest-design.md)."""`

`src/collector/youtube_search/search.py`:

```python
"""One YouTube lookup per track: the YT Music song match and a regular video
for comments, from a single unfiltered ytmusicapi search where possible.

Pure: no DB, no SQS. The caller passes the client and a `pace` callable that
blocks until the next request may go out."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError

from ..providers.base import VendorTrackRef
from ..providers.youtube.video_match import video_matches
from ..providers.ytmusic.normalize import build_query, result_to_ref
from ..vendor_match.scorer import FuzzyScore, score_candidate

SEARCH_LIMIT = 10
REVIEW_TOP_N = 5

Scored = tuple[VendorTrackRef, FuzzyScore]


@dataclass(frozen=True)
class TrackQuery:
    artists: str
    title: str
    duration_ms: int | None
    album: str | None
    need_song: bool


@dataclass
class TrackSearchResult:
    song_searched: bool
    video: VendorTrackRef | None = None
    match: Scored | None = None
    review: list[Scored] = field(default_factory=list)
    request_count: int = 0

    @property
    def outcome(self) -> str:
        if not self.song_searched:
            return "video_only"
        if self.match is not None:
            return "auto"
        return "review" if self.review else "no_match"

    @property
    def best_score(self) -> float | None:
        if self.match is not None:
            return self.match[1].total
        return self.review[0][1].total if self.review else None


def is_ban(exc: BaseException) -> bool:
    """YouTube refusing us (rate limit, forbidden, "are you a bot" gate)."""
    if isinstance(exc, YTMusicGatedError):
        return True
    if isinstance(exc, YTMusicServerError):
        message = str(exc)
        return "HTTP 429" in message or "HTTP 403" in message
    return False


def _refs(raw_results: Any, result_type: str | None) -> list[VendorTrackRef]:
    out: list[VendorTrackRef] = []
    for raw in raw_results or []:
        if not isinstance(raw, dict):
            continue
        if result_type is not None and raw.get("resultType") != result_type:
            continue
        ref = result_to_ref(raw)
        if ref is not None:
            out.append(ref)
    return out


def _scored(refs: list[VendorTrackRef], q: TrackQuery) -> list[Scored]:
    scored = [
        (
            r,
            score_candidate(
                candidate=r,
                artist=q.artists,
                title=q.title,
                duration_ms=q.duration_ms,
                album=q.album,
            ),
        )
        for r in refs
    ]
    scored.sort(key=lambda p: p[1].total, reverse=True)
    return scored


def search_track(
    client: Any, q: TrackQuery, *, threshold: float, pace: Callable[[], None]
) -> TrackSearchResult:
    res = TrackSearchResult(song_searched=q.need_song)

    def call(query: str, filter_name: str | None) -> Any:
        pace()
        res.request_count += 1
        return client.search(query, filter=filter_name, limit=SEARCH_LIMIT)

    # Dash form: better `videos` recall (2026-06-21 video-aware match design).
    first = call(f"{q.artists} - {q.title}".strip(" -"), None)
    res.video = next(
        (v for v in _refs(first, "video") if video_matches(q.artists, q.title, v.title)),
        None,
    )
    if not q.need_song:
        return res

    scored = _scored(_refs(first, "song"), q)
    if not (scored and scored[0][1].total >= threshold):
        query = build_query(q.artists, q.title)
        refs = _refs(call(query, "songs"), None)
        if not refs:  # today's vendor-match fallback
            refs = _refs(call(query, "videos"), None)
        scored = _scored(refs, q)

    if scored and scored[0][1].total >= threshold:
        res.match = scored[0]
    else:
        res.review = scored[:REVIEW_TOP_N]
    return res
```

- [ ] **Step 4: Run to verify pass** — same command → 11 passed (6 + 5 params).

- [ ] **Step 5: Commit** — `feat(youtube): per-track song and video search`.

---

### Task 3: The worker Lambda

**Files:**
- Create: `src/collector/youtube_search_handler.py`
- Modify: `src/collector/schemas.py` (+ `YoutubeSearchMessage`), `src/collector/settings.py` (+ `YoutubeSearchWorkerSettings`, getter, cache reset), `src/collector/logging_utils.py` (+ fields `outcome`, `request_count`, `video_found`, `auto`, `review`, `no_match`, `errors`, `videos_found`)
- Test: `tests/unit/test_youtube_search_handler.py`

**Interfaces:**
- Consumes: Task 1 repository methods; Task 2 `TrackQuery`, `search_track`, `is_ban`.
- Produces: `collector.youtube_search_handler.lambda_handler(event, context, *, client_factory=..., sqs_factory=..., sleep=...)`; `Pacer(interval_s, clock=time.monotonic, sleep=time.sleep)`; settings getter `get_youtube_search_worker_settings()` with fields `youtube_search_queue_url`, `since`, `min_interval_ms`, `ban_seconds`, `fuzzy_match_threshold`.

- [ ] **Step 1: Write the failing tests** — `tests/unit/test_youtube_search_handler.py`:

```python
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from ytmusicapi.exceptions import YTMusicServerError

import collector.youtube_search_handler as h
from collector.settings import YoutubeSearchWorkerSettings

SETTINGS = YoutubeSearchWorkerSettings(
    YOUTUBE_SEARCH_QUEUE_URL="https://sqs/q",
    YOUTUBE_SEARCH_SINCE="2026-10-15T00:00:00Z",
    YOUTUBE_SEARCH_MIN_INTERVAL_MS=0,
)


def song(vid, title="T"):
    return {"resultType": "song", "videoId": vid, "title": title,
            "artists": [{"name": "A"}], "duration_seconds": 200}


def video(vid, title="A - T"):
    return {"resultType": "video", "videoId": vid, "title": title, "artists": [{"name": "Ch"}]}


class Repo:
    def __init__(self, tracks, *, blocked_until=None, more=False):
        self.tracks = tracks
        self.blocked_until = blocked_until
        self.more = more
        self.claimed_at = None
        self.done, self.released, self.matches, self.reviews, self.no_match = [], [], [], [], []
        self.blocks = []

    def get_vendor_blocked_until(self, vendor):
        return self.blocked_until

    def set_vendor_blocked_until(self, vendor, until, now):
        self.blocks.append((vendor, until))

    def claim_tracks_for_youtube_search(self, limit, claimed_at, since):
        self.claimed_at = claimed_at
        return self.tracks[:limit]

    def mark_youtube_searched(self, track_id, at):
        assert at != self.claimed_at
        self.done.append(track_id)

    def release_youtube_search_claim(self, claimed_at):
        self.released.append(claimed_at)
        return len(self.tracks) - len(self.done)

    def has_tracks_needing_youtube_search(self, since):
        return self.more

    def upsert_vendor_match(self, cmd):
        self.matches.append((cmd.clouder_track_id, cmd.vendor, cmd.vendor_track_id, cmd.match_type))

    def insert_review_candidate(self, *, review_id, clouder_track_id, vendor, candidates, created_at):
        self.reviews.append((clouder_track_id, len(candidates)))

    def mark_no_match(self, *, clouder_track_id, vendor, created_at):
        self.no_match.append(clouder_track_id)


class Client:
    def __init__(self, script):
        self.script = list(script)  # per call: list of results or an exception

    def search(self, query, filter=None, limit=20):  # noqa: A002
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Sqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kw):
        self.sent.append(kw)


def track(tid, has_ytmusic=False):
    return {"id": tid, "title": "T", "length_ms": 200000, "album_title": None,
            "artists": "A", "has_ytmusic": has_ytmusic}


def run(monkeypatch, repo, client, *, body=None, remaining_ms=900_000):
    sqs = Sqs()
    monkeypatch.setattr(h, "create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(h, "get_youtube_search_worker_settings", lambda: SETTINGS)
    ctx = type("Ctx", (), {"get_remaining_time_in_millis": lambda self: remaining_ms})()
    event = {"Records": [{"body": json.dumps(body or {"batch_size": 100})}]}
    out = h.lambda_handler(event, ctx, client_factory=lambda: client, sqs_factory=lambda: sqs,
                           sleep=lambda s: None)
    return out, sqs


def test_happy_batch_stores_outcomes_and_follows_up(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")], more=True)
    client = Client([[song("s1"), video("v1")], [], [], []])
    out, sqs = run(monkeypatch, repo, client)
    assert out == {"processed": 1}
    assert ("t1", "youtube", "v1", "token") in repo.matches
    assert ("t1", "ytmusic", "s1", "fuzzy") in repo.matches
    assert repo.no_match == ["t2"]
    assert repo.done == ["t1", "t2"]
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}
    assert "DelaySeconds" not in sqs.sent[0]


def test_no_follow_up_when_nothing_left(monkeypatch) -> None:
    repo = Repo([track("t1")], more=False)
    _, sqs = run(monkeypatch, repo, Client([[song("s1")]]))
    assert sqs.sent == []


def test_ban_mid_batch_releases_rest_and_schedules_resume(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2"), track("t3")], more=True)
    ban = YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n")
    _, sqs = run(monkeypatch, repo, Client([[song("s1")], ban]))
    assert repo.done == ["t1"]
    assert repo.released == [repo.claimed_at]
    assert repo.blocks and repo.blocks[0][0] == "ytmusic"
    assert len(sqs.sent) == 1
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100, "resume": True}
    assert sqs.sent[0]["DelaySeconds"] == 900


def test_paused_trigger_is_dropped_and_resume_rearms(monkeypatch) -> None:
    until = datetime.now(UTC) + timedelta(minutes=5)
    repo = Repo([track("t1")], blocked_until=until)
    _, sqs = run(monkeypatch, repo, Client([]))
    assert sqs.sent == [] and repo.claimed_at is None
    _, sqs = run(monkeypatch, repo, Client([]), body={"batch_size": 50, "resume": True})
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 50, "resume": True}
    assert 1 <= sqs.sent[0]["DelaySeconds"] <= 300


def test_generic_error_marks_done_and_continues(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    _, _ = run(monkeypatch, repo, Client([ValueError("weird unicode"), [song("s2")]]))
    assert repo.done == ["t1", "t2"]
    assert ("t2", "ytmusic", "s2", "fuzzy") in repo.matches


def test_existing_ytmusic_row_stores_only_the_video(monkeypatch) -> None:
    repo = Repo([track("t1", has_ytmusic=True)])
    run(monkeypatch, repo, Client([[song("s9", title="Other"), video("v1")]]))
    assert repo.matches == [("t1", "youtube", "v1", "token")]
    assert repo.reviews == [] and repo.no_match == []


def test_deadline_hands_tracks_back_and_follows_up(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")], more=True)
    _, sqs = run(monkeypatch, repo, Client([]), remaining_ms=30_000)
    assert repo.done == [] and repo.released == [repo.claimed_at]
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}


def test_db_failure_releases_and_reraises(monkeypatch) -> None:
    repo = Repo([track("t1")])

    def boom(cmd):
        raise RuntimeError("data api down")

    repo.upsert_vendor_match = boom
    with pytest.raises(RuntimeError):
        run(monkeypatch, repo, Client([[song("s1")]]))
    assert repo.released == [repo.claimed_at]


def test_invalid_message_is_skipped(monkeypatch) -> None:
    out, _ = run(monkeypatch, Repo([]), Client([]), body={"batch_size": 0})
    assert out == {"processed": 0}


def test_pacer_keeps_requests_apart() -> None:
    now = [0.0]
    slept = []
    pacer = h.Pacer(2.0, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    pacer()
    now[0] = 0.5
    pacer()
    assert slept == [1.5]
```

- [ ] **Step 2: Run to verify it fails** — `$PYTEST -q tests/unit/test_youtube_search_handler.py` → ImportError (`YoutubeSearchWorkerSettings`).

- [ ] **Step 3: Message, settings, log fields**

`schemas.py` after `SpotifySearchMessage`:
```python
class YoutubeSearchMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    batch_size: StrictInt = Field(default=100, ge=1, le=500)
    # The one delayed message that carries the sweep over a YouTube ban.
    resume: bool = Field(default=False)
```

`settings.py` after `VendorMatchSettings` (imports: add `from datetime import UTC, datetime` if absent):
```python
class YoutubeSearchWorkerSettings(_SettingsBase):
    youtube_search_queue_url: str = Field(default="", alias="YOUTUBE_SEARCH_QUEUE_URL")
    # Tracks created before this are searched only if a user works with them.
    since: datetime = Field(
        default=datetime(2026, 10, 15, tzinfo=UTC), alias="YOUTUBE_SEARCH_SINCE"
    )
    min_interval_ms: int = Field(default=2000, alias="YOUTUBE_SEARCH_MIN_INTERVAL_MS", ge=0)
    ban_seconds: int = Field(default=3600, alias="YOUTUBE_SEARCH_BAN_SECONDS", ge=60)
    fuzzy_match_threshold: float = Field(
        default=0.92, alias="FUZZY_MATCH_THRESHOLD", ge=0.0, le=1.0
    )
```
plus
```python
@functools.lru_cache
def get_youtube_search_worker_settings() -> YoutubeSearchWorkerSettings:
    return YoutubeSearchWorkerSettings()
```
and `get_youtube_search_worker_settings.cache_clear()` in `reset_settings_cache`.

`logging_utils.py` `ALLOWED_LOG_FIELDS`: add `"outcome"`, `"request_count"`, `"video_found"`, `"auto"`, `"review"`, `"no_match"`, `"errors"`, `"videos_found"`.

- [ ] **Step 4: The handler** — `src/collector/youtube_search_handler.py`:

```python
"""SQS worker: search tracks on YouTube once, right after ingest.

A sweep shaped like the Spotify search: claim a batch on clouder_tracks
(youtube_searched_at), search each track at a fixed pace, store the YT Music
match / review / no_match and the comments video, hand back what a ban or the
deadline cut off, and chain a follow-up while candidates remain. One worker
at a time (reserved concurrency 1): the pace is the whole request rate.
"""

from __future__ import annotations

import json
import math
import time
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as PydanticValidationError

from .logging_utils import log_event
from .repositories import (
    ClouderRepository,
    UpsertVendorMatchCmd,
    create_clouder_repository_from_env,
    utc_now,
)
from .schemas import YoutubeSearchMessage, validation_error_message
from .settings import YoutubeSearchWorkerSettings, get_youtube_search_worker_settings
from .youtube_search.search import TrackQuery, TrackSearchResult, is_ban, search_track

VENDOR_SONG = "ytmusic"
VENDOR_VIDEO = "youtube"
_MAX_SQS_DELAY_SECONDS = 900
_DEADLINE_MARGIN_MS = 60_000


def _default_client() -> Any:
    from ytmusicapi import YTMusic  # lazy: cold start pays only when a batch runs

    return YTMusic()


def _default_sqs() -> Any:
    import boto3

    return boto3.client("sqs")


class Pacer:
    """Blocks until at least *interval_s* passed since the previous call."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._interval = interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def __call__(self) -> None:
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()


def lambda_handler(
    event: Mapping[str, Any],
    context: Any,
    *,
    client_factory: Callable[[], Any] = _default_client,
    sqs_factory: Callable[[], Any] = _default_sqs,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    remaining_ms = getattr(context, "get_remaining_time_in_millis", None)
    records = event.get("Records")
    if not isinstance(records, list):
        return {"processed": 0}
    log_event("INFO", "youtube_search_worker_invoked", sqs_record_count=len(records))

    settings = get_youtube_search_worker_settings()
    repository = create_clouder_repository_from_env()
    if repository is None:
        raise RuntimeError("AURORA Data API configuration is required for the YouTube search worker")

    processed = 0
    for index, record in enumerate(records):
        body = record.get("body") if isinstance(record, Mapping) else None
        if not isinstance(body, str):
            continue
        try:
            message = YoutubeSearchMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event(
                "ERROR",
                "youtube_search_message_invalid",
                sqs_record_index=index,
                error_message=validation_error_message(exc),
            )
            continue
        correlation_id = _correlation_id(record)
        _sweep(
            repository,
            settings,
            message,
            correlation_id,
            remaining_ms=remaining_ms,
            client_factory=client_factory,
            sqs_factory=sqs_factory,
            sleep=sleep,
        )
        processed += 1
    return {"processed": processed}


def _sweep(
    repository: ClouderRepository,
    settings: YoutubeSearchWorkerSettings,
    message: YoutubeSearchMessage,
    correlation_id: str,
    *,
    remaining_ms: Callable[[], int] | None,
    client_factory: Callable[[], Any],
    sqs_factory: Callable[[], Any],
    sleep: Callable[[float], None],
) -> None:
    now = utc_now()
    blocked_until = repository.get_vendor_blocked_until(VENDOR_SONG)
    if blocked_until is not None and blocked_until > now:
        # YouTube refused us: leave it alone. Plain triggers end here; the one
        # resume message re-arms itself until the ban is over.
        log_event(
            "INFO",
            "youtube_search_paused",
            correlation_id=correlation_id,
            retry_after=round((blocked_until - now).total_seconds()),
            reason="resume" if message.resume else "trigger_dropped",
        )
        if message.resume:
            _send(settings, sqs_factory, correlation_id,
                  {"batch_size": message.batch_size, "resume": True}, delay=blocked_until - now)
        return

    claimed_at = utc_now()
    tracks = repository.claim_tracks_for_youtube_search(
        limit=message.batch_size, claimed_at=claimed_at, since=settings.since
    )
    if not tracks:
        log_event("INFO", "youtube_search_skipped", correlation_id=correlation_id,
                  reason="no_tracks_need_search")
        return

    batch_id = uuid4().hex[:12]
    log_event("INFO", "youtube_search_tracks_loaded", correlation_id=correlation_id,
              batch_id=batch_id, track_count=len(tracks))
    client = client_factory()
    pace = Pacer(settings.min_interval_ms / 1000, sleep=sleep)
    tally: Counter[str] = Counter()
    try:
        for track in tracks:
            if remaining_ms is not None and remaining_ms() < _DEADLINE_MARGIN_MS:
                repository.release_youtube_search_claim(claimed_at=claimed_at)
                break
            _search_one(repository, client, pace, track, settings, correlation_id, tally)
    except Exception as exc:
        repository.release_youtube_search_claim(claimed_at=claimed_at)
        if not is_ban(exc):
            raise
        until = utc_now() + timedelta(seconds=settings.ban_seconds)
        repository.set_vendor_blocked_until(VENDOR_SONG, until, utc_now())
        log_event("WARNING", "youtube_search_paused", correlation_id=correlation_id,
                  batch_id=batch_id, retry_after=settings.ban_seconds, reason="banned",
                  error_message=str(exc)[:300])
        _send(settings, sqs_factory, correlation_id,
              {"batch_size": message.batch_size, "resume": True},
              delay=timedelta(seconds=settings.ban_seconds))
        _log_summary(correlation_id, batch_id, tally)
        return

    _log_summary(correlation_id, batch_id, tally)
    if repository.has_tracks_needing_youtube_search(since=settings.since):
        _send(settings, sqs_factory, correlation_id, {"batch_size": message.batch_size})


def _search_one(
    repository: ClouderRepository,
    client: Any,
    pace: Pacer,
    track: Mapping[str, Any],
    settings: YoutubeSearchWorkerSettings,
    correlation_id: str,
    tally: Counter[str],
) -> None:
    track_id = str(track["id"])
    length = track.get("length_ms")
    query = TrackQuery(
        artists=str(track.get("artists") or ""),
        title=str(track.get("title") or ""),
        duration_ms=int(length) if length is not None else None,
        album=track.get("album_title"),
        need_song=not bool(track.get("has_ytmusic")),
    )
    try:
        result = search_track(client, query, threshold=settings.fuzzy_match_threshold, pace=pace)
    except Exception as exc:
        if is_ban(exc):
            raise
        tally["errors"] += 1
        log_event("WARNING", "youtube_search_result", correlation_id=correlation_id,
                  track_id=track_id, outcome="error", error_type=exc.__class__.__name__,
                  error_message=str(exc)[:300])
        repository.mark_youtube_searched(track_id=track_id, at=utc_now())
        return
    _persist(repository, track_id, result, utc_now())
    repository.mark_youtube_searched(track_id=track_id, at=utc_now())
    tally[result.outcome] += 1
    tally["total_tracks"] += 1
    if result.video is not None:
        tally["videos_found"] += 1
    log_event("INFO", "youtube_search_result", correlation_id=correlation_id, track_id=track_id,
              outcome=result.outcome, confidence=result.best_score,
              request_count=result.request_count, video_found=result.video is not None)


def _persist(repository: ClouderRepository, track_id: str, result: TrackSearchResult, now: Any) -> None:
    if result.video is not None:
        repository.upsert_vendor_match(UpsertVendorMatchCmd(
            clouder_track_id=track_id, vendor=VENDOR_VIDEO,
            vendor_track_id=result.video.vendor_track_id, match_type="token",
            confidence=Decimal("1.000"), matched_at=now, payload=result.video.raw_payload,
        ))
    if not result.song_searched:
        return
    if result.match is not None:
        ref, score = result.match
        repository.upsert_vendor_match(UpsertVendorMatchCmd(
            clouder_track_id=track_id, vendor=VENDOR_SONG, vendor_track_id=ref.vendor_track_id,
            match_type="fuzzy", confidence=Decimal(str(score.total)), matched_at=now,
            payload=ref.raw_payload,
        ))
    elif result.review:
        repository.insert_review_candidate(
            review_id=str(uuid4()), clouder_track_id=track_id, vendor=VENDOR_SONG,
            candidates=[
                {"ref": r.raw_payload, "score": s.total, "title_sim": s.title_sim,
                 "artist_sim": s.artist_sim, "duration_ok": s.duration_ok,
                 "album_bonus": s.album_bonus}
                for r, s in result.review
            ],
            created_at=now,
        )
    else:
        repository.mark_no_match(clouder_track_id=track_id, vendor=VENDOR_SONG, created_at=now)


def _log_summary(correlation_id: str, batch_id: str, tally: Counter[str]) -> None:
    log_event("INFO", "youtube_search_completed", correlation_id=correlation_id,
              batch_id=batch_id, total_tracks=tally["total_tracks"], auto=tally["auto"],
              review=tally["review"], no_match=tally["no_match"], errors=tally["errors"],
              videos_found=tally["videos_found"])


def _send(
    settings: YoutubeSearchWorkerSettings,
    sqs_factory: Callable[[], Any],
    correlation_id: str,
    body: dict[str, Any],
    *,
    delay: timedelta | None = None,
) -> None:
    url = settings.youtube_search_queue_url.strip()
    if not url:
        log_event("WARNING", "youtube_search_follow_up_skipped", correlation_id=correlation_id,
                  reason="no_queue_url")
        return
    kwargs: dict[str, Any] = {
        "QueueUrl": url,
        "MessageBody": json.dumps(body, separators=(",", ":")),
        "MessageAttributes": {"correlation_id": {"DataType": "String", "StringValue": correlation_id}},
    }
    if delay is not None:
        kwargs["DelaySeconds"] = min(_MAX_SQS_DELAY_SECONDS, max(1, math.ceil(delay.total_seconds())))
    sqs_factory().send_message(**kwargs)
    log_event("INFO", "youtube_search_follow_up_enqueued", correlation_id=correlation_id,
              batch_size=body["batch_size"], retry_after=kwargs.get("DelaySeconds"))


def _correlation_id(record: Mapping[str, Any]) -> str:
    attrs = record.get("messageAttributes")
    if isinstance(attrs, Mapping):
        value = attrs.get("correlation_id")
        if isinstance(value, Mapping) and isinstance(value.get("stringValue"), str):
            return value["stringValue"]
    return str(uuid4())
```

Format with `ruff format`; keep within line length (the snippets above may need wrapping).

- [ ] **Step 5: Run to verify pass** — `$PYTEST -q tests/unit/test_youtube_search_handler.py tests/unit/test_youtube_search.py` → all pass; `ruff check src tests && ruff format --check src tests`.

- [ ] **Step 6: Commit** — `feat(youtube): search worker with pacing and ban pause`.

---

### Task 4: Trigger after canonicalization

**Files:**
- Modify: `src/collector/settings.py` (`WorkerSettings.youtube_search_queue_url`), `src/collector/worker_handler.py`
- Test: `tests/unit/test_youtube_search_trigger.py`

**Interfaces:**
- Produces: `worker_handler._enqueue_youtube_search_after_canonicalization(settings, correlation_id, sqs=None) -> None`.

- [ ] **Step 1: Failing test** — `tests/unit/test_youtube_search_trigger.py`:

```python
from __future__ import annotations

import json
from types import SimpleNamespace

from collector.worker_handler import _enqueue_youtube_search_after_canonicalization


class Sqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kw):
        self.sent.append(kw)


def test_sends_one_sweep_message() -> None:
    sqs = Sqs()
    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url="https://sqs/yt"), "corr", sqs=sqs
    )
    assert sqs.sent[0]["QueueUrl"] == "https://sqs/yt"
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}


def test_no_queue_configured_sends_nothing() -> None:
    sqs = Sqs()
    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url=""), "corr", sqs=sqs
    )
    assert sqs.sent == []


def test_send_failure_never_breaks_the_run() -> None:
    class Broken:
        def send_message(self, **kw):
            raise RuntimeError("sqs down")

    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url="https://sqs/yt"), "corr", sqs=Broken()
    )
```

- [ ] **Step 2: Run → fail** (ImportError).

- [ ] **Step 3: Implement** — `WorkerSettings`: `youtube_search_queue_url: str = Field(default="", alias="YOUTUBE_SEARCH_QUEUE_URL")`. In `worker_handler.py` after `_enqueue_spotify_search_after_canonicalization(...)` in the handler: `_enqueue_youtube_search_after_canonicalization(settings=settings, correlation_id=correlation_id)`; and the function:

```python
def _enqueue_youtube_search_after_canonicalization(
    settings: Any, correlation_id: str, sqs: Any = None
) -> None:
    """Start the YouTube sweep after canonicalization (best-effort)."""
    queue_url = (getattr(settings, "youtube_search_queue_url", "") or "").strip()
    if not queue_url:
        return
    try:
        if sqs is None:
            import boto3

            sqs = boto3.client("sqs")
        sqs.send_message(
            QueueUrl=queue_url,
            MessageBody=json.dumps({"batch_size": 100}, separators=(",", ":")),
            MessageAttributes={
                "correlation_id": {"DataType": "String", "StringValue": correlation_id}
            },
        )
        log_event("INFO", "youtube_search_enqueued_after_canonicalization",
                  correlation_id=correlation_id)
    except Exception as exc:
        log_event("ERROR", "youtube_search_enqueue_failed", correlation_id=correlation_id,
                  error_type=exc.__class__.__name__, error_message=str(exc)[:500])
```

- [ ] **Step 4: Run → pass**; also `$PYTEST -q tests/unit/test_worker_handler.py tests/unit/test_backfill_handler.py`.

- [ ] **Step 5: Commit** — `feat(ingest): start YouTube sweep after canonicalization`.

---

### Task 5: Reuse the stored video for comments

**Files:**
- Modify: `src/collector/comments/repository.py` (`TrackMeta`, `fetch_track_meta`), `src/collector/comments_collect_handler.py`, `src/collector/curation/routes_playlists.py`
- Test: `tests/unit/test_comments_collect_handler.py`, `tests/unit/test_resolve_match_comment_dispatch.py`, `tests/db/test_youtube_search_pg.py` (meta query)

**Interfaces:**
- Produces: `TrackMeta.youtube_video_id: str | None = None` (last field, default keeps positional constructors valid).

- [ ] **Step 1: Failing tests**

In `tests/unit/test_comments_collect_handler.py` add:
```python
def test_no_seed_uses_the_stored_video_before_searching(monkeypatch):
    repo = _MetaRepo(TrackMeta("t1", "Artist", "Title", 1000, youtube_video_id="vidY"))
    provider = _ResolverProvider(
        alts=["vidX"],
        collect_by_id={"vidY": [CollectedComment("c1", "A", None, "hi", 1, None, 0)]},
    )
    _patch(monkeypatch, repo, provider)
    worker.lambda_handler(_event(_msg(video_id="")), None)
    assert repo.stored[0]["status"] == "collected"
    assert repo.stored[0]["external_video_id"] == "vidY"
    assert provider.resolve_calls == []
```
In `tests/unit/test_resolve_match_comment_dispatch.py` change the accept expectation to:
```python
    assert calls == [{"track_id": "t1", "platform": "youtube"}]
```
In `tests/db/test_youtube_search_pg.py` add:
```python
def test_comment_meta_carries_the_stored_video(pg) -> None:
    from collector.comments.repository import CommentsRepository

    _world(pg)
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES ('new-1', 'youtube', 'vidY', 'token', 1.0,"
        " now(), '{}'::jsonb)"
    )
    meta = CommentsRepository(pg).fetch_track_meta(["new-1", "new-2"])
    assert meta["new-1"].youtube_video_id == "vidY"
    assert meta["new-2"].youtube_video_id is None
```

- [ ] **Step 2: Run → fail** (`TypeError: unexpected keyword youtube_video_id`, accept dispatch mismatch).

- [ ] **Step 3: Implement**

`TrackMeta`: add `youtube_video_id: str | None = None`.
`fetch_track_meta` SQL: add `LEFT JOIN vendor_track_map yv ON yv.clouder_track_id = t.id AND yv.vendor = 'youtube'`, select `yv.vendor_track_id AS youtube_video_id`, add `yv.vendor_track_id` to `GROUP BY`; map `youtube_video_id=r.get("youtube_video_id") or None`.
`comments_collect_handler._resolve_and_collect`: at the top of the `if not primary_video_id:` branch:
```python
    if not primary_video_id and meta is not None and meta.youtube_video_id:
        # Found at ingest by the YouTube search worker — no second search.
        primary_video_id = meta.youtube_video_id
```
(placed before the existing `if not primary_video_id:` block). Update the docstring sentence about decoupled dispatch to mention the stored video.
`routes_playlists.py` accept: `try_dispatch_comment_collection(track_id=track_id, platform="youtube")` with a comment: the accepted song video is a poor comment source (comments often disabled) and `start_collection` skips tracks already collected.

- [ ] **Step 4: Run → pass** — `$PYTEST -q tests/unit/test_comments_collect_handler.py tests/unit/test_resolve_match_comment_dispatch.py tests/unit/test_comments_repository.py` and the pg file.

- [ ] **Step 5: Commit** — `feat(comments): reuse the video found at ingest`.

---

### Task 6: Infrastructure, counts and docs

**Files:**
- Modify: `infra/main.tf`, `infra/variables.tf`, `infra/sqs.tf`, `infra/lambda.tf`, `infra/lambda_roles.tf`, `infra/logging.tf`
- Modify: `README.md` (Lambda 18→19, SQS queues 7→8, Terraform resource definitions recount), `docs/architecture.md` (Lambda list), `docs/data/entity-resolution.md`, `docs/ops/runbook.md`
- Test: `tests/unit/test_concurrency_infra.py` (existing guard), `tests/unit/test_readme.py` (existing guard), new `tests/unit/test_youtube_search_infra.py`

- [ ] **Step 1: Failing guard test** — `tests/unit/test_youtube_search_infra.py`:
```python
from __future__ import annotations

import re
from pathlib import Path

TF = "\n".join(p.read_text() for p in Path("infra").glob("*.tf"))


def _block(kind: str, name: str) -> str:
    m = re.search(rf'resource "{kind}" "{name}" \{{(.*?)\n\}}', TF, re.S)
    assert m, f"{kind}.{name} missing"
    return m.group(1)


def test_one_worker_at_a_time() -> None:
    assert "reserved_concurrent_executions = 1" in _block("aws_lambda_function", "youtube_search_worker")


def test_worker_gets_its_pace_and_queue() -> None:
    body = _block("aws_lambda_function", "youtube_search_worker")
    for env in ("YOUTUBE_SEARCH_QUEUE_URL", "YOUTUBE_SEARCH_SINCE", "YOUTUBE_SEARCH_MIN_INTERVAL_MS",
                "YOUTUBE_SEARCH_BAN_SECONDS", "FUZZY_MATCH_THRESHOLD"):
        assert env in body


def test_canonicalization_can_start_the_sweep() -> None:
    assert "YOUTUBE_SEARCH_QUEUE_URL" in _block("aws_lambda_function", "canonicalization_worker")
    assert "aws_sqs_queue.youtube_search.arn" in TF.split('module "role_canonicalization_worker"')[1].split("module ")[0]


def test_dlq_is_alarmed() -> None:
    assert "youtube_search_dlq.name" in TF
```
Run (from the worktree root): `$PYTEST -q tests/unit/test_youtube_search_infra.py` → FAIL.

- [ ] **Step 2: Terraform**

`main.tf` locals (next to the Spotify names):
```hcl
  youtube_search_worker_lambda_name = "${local.name_prefix}-youtube-search-worker"
  youtube_search_queue_name         = "${local.name_prefix}-youtube-search"
  youtube_search_dlq_name           = "${local.name_prefix}-youtube-search-dlq"
```
`variables.tf`:
```hcl
variable "youtube_search_max_concurrency" {
  description = "SQS trigger cap for the YouTube search worker (AWS minimum 2); reserved concurrency 1 keeps it to one worker."
  type        = number
  default     = 2

  validation {
    condition     = var.youtube_search_max_concurrency >= 2 && var.youtube_search_max_concurrency <= 1000
    error_message = "maximum_concurrency must be between 2 and 1000 (AWS SQS event-source limit)."
  }
}

variable "youtube_search_min_interval_ms" {
  description = "Pause between ytmusicapi requests of the one YouTube search worker (2000 = 0.5 req/s)."
  type        = number
  default     = 2000
}

variable "youtube_search_ban_seconds" {
  description = "How long the YouTube search waits after a 429/403/bot gate."
  type        = number
  default     = 3600
}

variable "youtube_search_since" {
  description = "Tracks created before this are searched on YouTube only when a user works with them."
  type        = string
  default     = "2026-10-15T00:00:00Z"
}
```
`sqs.tf`:
```hcl
# ── YouTube Search queue ─────────────────────────────────────────

resource "aws_sqs_queue" "youtube_search_dlq" {
  name                      = local.youtube_search_dlq_name
  message_retention_seconds = var.spotify_search_queue_retention_seconds
}

resource "aws_sqs_queue" "youtube_search" {
  name                       = local.youtube_search_queue_name
  visibility_timeout_seconds = 960
  message_retention_seconds  = var.spotify_search_queue_retention_seconds

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.youtube_search_dlq.arn
    maxReceiveCount     = 3
  })
}
```
`logging.tf`: log group
```hcl
resource "aws_cloudwatch_log_group" "youtube_search_worker" {
  name              = "/aws/lambda/${local.youtube_search_worker_lambda_name}"
  retention_in_days = var.log_retention_days
}
```
and `youtube_search = aws_sqs_queue.youtube_search_dlq.name` in `local.dlq_queues`.
`lambda_roles.tf`:
```hcl
module "role_youtube_search_worker" {
  source               = "./modules/lambda_role"
  permissions_boundary = local.role_boundary_arn
  name                 = "${local.name_prefix}-youtube-search-worker-role"
  assume_role_policy   = data.aws_iam_policy_document.lambda_assume.json
  log_group_arn        = aws_cloudwatch_log_group.youtube_search_worker.arn
  statements = [
    local.st_data_api,
    local.st_db_secret,
    local.st_ssm_kms,
    { sid = "ConsumeYoutubeSearch", actions = local.sqs_consume, resources = [aws_sqs_queue.youtube_search.arn] },
    { sid = "RequeueYoutubeSearch", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.youtube_search.arn] },
  ]
}
```
and in `role_canonicalization_worker` statements: `{ sid = "EnqueueYoutubeSearch", actions = ["sqs:SendMessage"], resources = [aws_sqs_queue.youtube_search.arn] },`.
`lambda.tf`: canonicalization env `YOUTUBE_SEARCH_QUEUE_URL = aws_sqs_queue.youtube_search.url`; new function + ESM after the Spotify block:
```hcl
# ── YouTube Search worker ────────────────────────────────────────

resource "aws_lambda_function" "youtube_search_worker" {
  function_name = local.youtube_search_worker_lambda_name
  role          = module.role_youtube_search_worker.arn
  runtime       = "python3.12"
  handler       = "collector.youtube_search_handler.lambda_handler"
  filename      = local.lambda_zip_file
  timeout       = 900
  memory_size   = 512

  # One worker at a time: the pace below is then the whole request rate to
  # YouTube's unofficial API (no published limits; datacenter IPs get gated).
  reserved_concurrent_executions = 1

  source_code_hash = filebase64sha256(local.lambda_zip_file)

  environment {
    variables = {
      AURORA_CLUSTER_ARN             = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN              = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE                = var.aurora_database_name
      LOG_LEVEL                      = "INFO"
      YOUTUBE_SEARCH_QUEUE_URL       = aws_sqs_queue.youtube_search.url
      YOUTUBE_SEARCH_SINCE           = var.youtube_search_since
      YOUTUBE_SEARCH_MIN_INTERVAL_MS = var.youtube_search_min_interval_ms
      YOUTUBE_SEARCH_BAN_SECONDS     = var.youtube_search_ban_seconds
      FUZZY_MATCH_THRESHOLD          = "0.92"
    }
  }

  depends_on = [aws_cloudwatch_log_group.youtube_search_worker]
}

resource "aws_lambda_event_source_mapping" "youtube_search_queue" {
  event_source_arn = aws_sqs_queue.youtube_search.arn
  function_name    = aws_lambda_function.youtube_search_worker.arn
  batch_size       = 1

  scaling_config {
    maximum_concurrency = var.youtube_search_max_concurrency
  }
}
```
Run `terraform fmt -recursive infra` (fixes alignment).

- [ ] **Step 3: Docs and counts** — README: `18 Lambda functions` → `19` (both places), `7 SQS queues + DLQs` → `8`, `N Terraform resource definitions` → the count `grep -c '^resource "' infra/*.tf | awk -F: '{s+=$2} END {print s}'`. `docs/architecture.md`: add `youtube-search-worker` to the Lambda list with one line ("searches new tracks on YouTube after ingest: YT Music match + comments video"). `docs/data/entity-resolution.md`: YouTube Music row — matching now runs at ingest via `youtube-search-worker` (playlist add remains the fallback). `docs/ops/runbook.md`: a "YouTube search" section with the kick command
```bash
aws sqs send-message --queue-url "$(aws sqs get-queue-url --queue-name clouder-prod-youtube-search --query QueueUrl --output text)" --message-body '{"batch_size":100}'
```
and how to pause (`INSERT/UPDATE vendor_rate_limits` for vendor `ytmusic` via the owner) and tune the pace (`youtube_search_min_interval_ms`).

- [ ] **Step 4: Run guards** — `$PYTEST -q tests/unit/test_youtube_search_infra.py tests/unit/test_concurrency_infra.py tests/unit/test_readme.py tests/unit/test_docs_freshness.py` → pass; `terraform fmt -check -recursive infra`.

- [ ] **Step 5: Commit** — `feat(infra): YouTube search worker and queue`.

---

### Task 7: Rollout (after merge — operations, no code)

- [ ] Full suite before PR: `pytest -q` (+ `tests/db` against the throwaway DB), `ruff check`, `ruff format --check`, `mypy` per CI.
- [ ] PR (caveman text), wait for checks, merge.
- [ ] Watch the Deploy run; confirm `clouder-prod-youtube-search-worker` exists with reserved concurrency 1 and the migration applied (`alembic` phase in the deploy log).
- [ ] Kick once (runbook command). First batches = old needed tracks (categories + active blocks).
- [ ] Monitor with Logs Insights on `/aws/lambda/clouder-prod-youtube-search-worker`: `stats count(*) by outcome` on `youtube_search_result`; any `youtube_search_paused reason=banned`; achieved rate (results per minute); `videos_found` share. Report to the owner.

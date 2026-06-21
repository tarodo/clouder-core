# YouTube Comment-Video Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a track's YouTube Music "Art Track" has comments disabled, fall back to an ytmusicapi videos-search to find a regular YouTube video and collect comments from it instead.

**Architecture:** The comment worker collects from the Art Track first; on `CommentsDisabledError` it asks the YouTube comment provider for alternate regular-video ids (ytmusicapi `filter="videos"` + the existing fuzzy scorer), then tries up to 3 in score order until one yields comments. The collected-from video id is recorded in `comment_collections.external_video_id`. No schema, infra, OpenAPI, or frontend changes.

**Tech Stack:** Python 3 Lambda, RDS Data API, ytmusicapi (unauthenticated, already a dependency), YouTube Data API v3 (reads only).

---

## Conventions for every task

- **Worktree venv:** `.venv` lives at the MAIN repo root. Run pytest by absolute path:
  `WT=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/add_comments_collect`
  `PYTEST=/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`
  Run from `$WT`. `pytest.ini` sets `PYTHONPATH=src`.
- Branch is already `feat/youtube-comment-video-fallback` (off `origin/main`).
- Commit with plain `git commit -m "..."` (Conventional Commits). NO `Co-Authored-By`/AI trailer (a hook blocks it). ACTUALLY RUN `git commit` and report the SHA — do not just print the message.

## File Structure

**Modify only (backend):**
- `src/collector/providers/base.py` — add `resolve_alternate_videos` to the `CommentProvider` protocol.
- `src/collector/providers/youtube/comments.py` — inject an ytmusicapi client + threshold; implement `resolve_alternate_videos`.
- `src/collector/comments/repository.py` — add `TrackMeta` + `fetch_track_meta`; extend `store_comments` with `external_video_id`.
- `src/collector/comments_collect_handler.py` — primary→fallback collection flow.

**Tests:**
- `tests/unit/test_youtube_comment_provider.py` (extend)
- `tests/unit/test_comments_repository.py` (extend)
- `tests/unit/test_comments_collect_handler.py` (extend)

No migration, no terraform, no OpenAPI, no frontend.

---

## Task 1: Add `resolve_alternate_videos` to the `CommentProvider` protocol

**Files:**
- Modify: `src/collector/providers/base.py`
- Test: `tests/unit/test_providers_comments_base.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_providers_comments_base.py`:
```python
def test_comment_provider_protocol_includes_resolver() -> None:
    from collector.providers.base import CommentProvider

    class Full:
        platform = "youtube"

        def collect(self, video_ref, *, limit=100):
            return []

        def resolve_alternate_videos(self, *, artist, title, duration_ms, exclude_video_id):
            return []

    assert isinstance(Full(), CommentProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_providers_comments_base.py -q`
Expected: PASS for existing tests, and the new test PASSES too (runtime_checkable only checks method *names*, and `Full` already declares the method). To make this a real TDD red, instead assert the method is part of the documented protocol by checking a provider WITHOUT it is still structurally accepted — skip that nuance: the meaningful red comes in Task 2. Treat Task 1 as a doc/interface change verified by Task 2. Proceed to Step 3.

- [ ] **Step 3: Add the method to the protocol**

In `src/collector/providers/base.py`, the `CommentProvider` protocol currently is:
```python
@runtime_checkable
class CommentProvider(Protocol):
    platform: str

    def collect(self, video_ref: str, *, limit: int = 100) -> list[CollectedComment]:
        """Return up to `limit` top-level comments for `video_ref`."""
        ...
```
Add the resolver method after `collect`:
```python
    def resolve_alternate_videos(
        self,
        *,
        artist: str,
        title: str,
        duration_ms: int | None,
        exclude_video_id: str,
    ) -> list[str]:
        """Best-first regular-video ids likely to have comments enabled, when
        the primary video's comments are disabled. Empty when none/unsupported."""
        ...
```

- [ ] **Step 4: Run tests**

Run: `cd $WT && $PYTEST tests/unit/test_providers_comments_base.py -q`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/providers/base.py tests/unit/test_providers_comments_base.py
git commit -m "feat(providers): add resolve_alternate_videos to CommentProvider"
git rev-parse --short HEAD
```

---

## Task 2: Implement `YouTubeCommentProvider.resolve_alternate_videos`

**Files:**
- Modify: `src/collector/providers/youtube/comments.py`
- Test: `tests/unit/test_youtube_comment_provider.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_youtube_comment_provider.py`:
```python
class FakeYtClient:
    def __init__(self, results):
        self._results = results
        self.calls = []

    def search(self, query, filter=None, limit=None):
        self.calls.append((query, filter, limit))
        return self._results


def _video(video_id, title, artist, seconds=200):
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "duration_seconds": seconds,
    }


def _provider_with(results, threshold=0.5):
    # session is unused by the resolver; pass a dummy.
    return YouTubeCommentProvider(
        api_key="K",
        session=object(),
        ytmusic_client=FakeYtClient(results),
        threshold=threshold,
    )


def test_resolve_returns_scored_videos_best_first():
    results = [
        _video("good1", "Lost Track", "Guri"),     # strong match
        _video("weakX", "Totally Different", "Nobody"),  # below threshold
        _video("good2", "Lost Track (Extended)", "Guri"),
    ]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=200_000, exclude_video_id="art1"
    )
    assert "good1" in out and "good2" in out
    assert "weakX" not in out
    assert out[0] == "good1"  # exact title ranks first
    # request shape
    q, flt, _ = provider._ytmusic_client.calls[-1]
    assert flt == "videos"
    assert "Guri" in q and "Lost Track" in q


def test_resolve_excludes_the_art_track_id():
    results = [_video("art1", "Lost Track", "Guri"), _video("good1", "Lost Track", "Guri")]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=200_000, exclude_video_id="art1"
    )
    assert out == ["good1"]


def test_resolve_caps_at_three():
    results = [_video(f"v{i}", "Lost Track", "Guri") for i in range(6)]
    provider = _provider_with(results, threshold=0.5)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert len(out) == 3


def test_resolve_empty_when_nothing_clears_threshold():
    results = [_video("v1", "Totally Different", "Nobody")]
    provider = _provider_with(results, threshold=0.9)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []


def test_resolve_tolerates_malformed_results():
    provider = _provider_with(["junk", {}, {"title": "no id"}], threshold=0.1)
    out = provider.resolve_alternate_videos(
        artist="Guri", title="Lost Track", duration_ms=None, exclude_video_id="art1"
    )
    assert out == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: FAIL — `__init__` doesn't accept `ytmusic_client`/`threshold`; no `resolve_alternate_videos`.

- [ ] **Step 3: Implement**

In `src/collector/providers/youtube/comments.py`:

Add a default ytmusic factory near the top (after `_BASE`):
```python
def _default_ytmusic_factory() -> Any:
    from ytmusicapi import YTMusic  # lazy: only when a fallback search runs

    return YTMusic()
```

Replace the `__init__` with:
```python
    def __init__(
        self,
        *,
        api_key: str,
        session: Any,
        ytmusic_client: Any | None = None,
        ytmusic_client_factory: Any = _default_ytmusic_factory,
        search_limit: int = 10,
        threshold: float | None = None,
    ) -> None:
        self._api_key = api_key
        self._session = session
        self._ytmusic_client = ytmusic_client
        self._ytmusic_client_factory = ytmusic_client_factory
        self._search_limit = search_limit
        self._threshold = threshold
```

Add these methods to the class (after `collect`):
```python
    def _get_ytmusic(self) -> Any:
        if self._ytmusic_client is None:
            self._ytmusic_client = self._ytmusic_client_factory()
        return self._ytmusic_client

    def resolve_alternate_videos(
        self,
        *,
        artist: str,
        title: str,
        duration_ms: int | None,
        exclude_video_id: str,
    ) -> list[str]:
        from ..ytmusic.normalize import build_query, result_to_ref
        from ...vendor_match.scorer import score_candidate
        from ...settings import get_vendor_match_settings

        threshold = (
            self._threshold
            if self._threshold is not None
            else get_vendor_match_settings().fuzzy_match_threshold
        )
        query = build_query(artist, title)
        raw_results = self._get_ytmusic().search(
            query, filter="videos", limit=self._search_limit
        )
        scored: list[tuple[float, str]] = []
        for raw in raw_results or []:
            if not isinstance(raw, dict):
                continue
            ref = result_to_ref(raw)
            if ref is None or ref.vendor_track_id == exclude_video_id:
                continue
            score = score_candidate(
                candidate=ref, artist=artist, title=title,
                duration_ms=duration_ms, album=None,
            )
            if score.total >= threshold:
                scored.append((score.total, ref.vendor_track_id))
        scored.sort(key=lambda t: t[0], reverse=True)
        return [vid for _, vid in scored[:3]]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: PASS (existing collect tests + 5 new resolver tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/providers/youtube/comments.py tests/unit/test_youtube_comment_provider.py
git commit -m "feat(providers): resolve regular YouTube videos for comments fallback"
git rev-parse --short HEAD
```

---

## Task 3: Repository `fetch_track_meta`

**Files:**
- Modify: `src/collector/comments/repository.py`
- Test: `tests/unit/test_comments_repository.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_comments_repository.py`:
```python
def test_fetch_track_meta_maps_rows():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Lost Track",
             "length_ms": 225000, "artist_names": "Guri, Eider"},
        ]),
    ])
    repo = CommentsRepository(api)
    meta = repo.fetch_track_meta(["t1"])
    assert "t1" in meta
    assert meta["t1"].title == "Lost Track"
    assert meta["t1"].artist == "Guri, Eider"
    assert meta["t1"].duration_ms == 225000


def test_fetch_track_meta_empty_input():
    repo = CommentsRepository(FakeDataAPI([]))
    assert repo.fetch_track_meta([]) == {}


def test_fetch_track_meta_maps_null_duration():
    api = FakeDataAPI([
        ("FROM clouder_tracks t", [
            {"track_id": "t1", "title": "Solo", "length_ms": None, "artist_names": ""},
        ]),
    ])
    repo = CommentsRepository(api)
    meta = repo.fetch_track_meta(["t1"])["t1"]
    assert meta.duration_ms is None and meta.artist == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: FAIL — `fetch_track_meta`/`TrackMeta` don't exist.

- [ ] **Step 3: Implement**

In `src/collector/comments/repository.py`, add a dataclass after `CommentRow`:
```python
@dataclass(frozen=True)
class TrackMeta:
    track_id: str
    artist: str
    title: str
    duration_ms: int | None
```

Add this method to `CommentsRepository` (e.g. after `list_comments_for_tracks`):
```python
    def fetch_track_meta(self, track_ids: list[str]) -> dict[str, "TrackMeta"]:
        """artist/title/duration for the given tracks (for fallback search).

        Unlike playlists_repository.fetch_unmatched_match_inputs, this does NOT
        anti-join vendor_track_map/match_review_queue — our tracks are already
        matched."""
        if not track_ids:
            return {}
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {}
        for i, tid in enumerate(track_ids):
            params[f"t{i}"] = tid
        rows = self._data_api.execute(
            f"""
            SELECT
                t.id AS track_id,
                t.title,
                t.length_ms,
                COALESCE(STRING_AGG(DISTINCT a.name, ', ' ORDER BY a.name), '') AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists cta ON cta.track_id = t.id
            LEFT JOIN clouder_artists       a   ON a.id = cta.artist_id
            WHERE t.id IN ({placeholders})
            GROUP BY t.id, t.title, t.length_ms
            """,
            params,
        )
        out: dict[str, TrackMeta] = {}
        for r in rows:
            length = r.get("length_ms")
            out[r["track_id"]] = TrackMeta(
                track_id=r["track_id"],
                artist=r.get("artist_names") or "",
                title=r.get("title") or "",
                duration_ms=int(length) if length is not None else None,
            )
        return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/repository.py tests/unit/test_comments_repository.py
git commit -m "feat(comments): add fetch_track_meta for fallback search"
git rev-parse --short HEAD
```

---

## Task 4: `store_comments` accepts `external_video_id`

**Files:**
- Modify: `src/collector/comments/repository.py`
- Test: `tests/unit/test_comments_repository.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_comments_repository.py`:
```python
def test_store_comments_updates_external_video_id_when_provided():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(
        collection_id="col1", platform="youtube", comments=[],
        status="collected", now=NOW, external_video_id="alt-vid",
    )
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][:1][0][:2]
    assert "external_video_id = :evid" in update_sql
    assert params["evid"] == "alt-vid"


def test_store_comments_omits_external_video_id_when_not_provided():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(
        collection_id="col1", platform="youtube", comments=[],
        status="empty", now=NOW,
    )
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][:1][0][:2]
    assert "external_video_id" not in update_sql
    assert "evid" not in params
```
(Note: `FakeDataAPI.execute` records `(sql, params, transaction_id)` — adjust the unpacking above if needed so `update_sql`/`params` are the first two elements of the recorded tuple.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: FAIL — `store_comments` has no `external_video_id` param.

- [ ] **Step 3: Implement**

In `src/collector/comments/repository.py`, change `store_comments`'s signature to add the param:
```python
    def store_comments(
        self,
        *,
        collection_id: str,
        platform: str,
        comments: list[CollectedComment],
        status: str,
        now: datetime,
        error: str | None = None,
        external_video_id: str | None = None,
    ) -> None:
```
Replace the final UPDATE block (the `self._data_api.execute("UPDATE comment_collections ...")` call) with a version that conditionally sets `external_video_id`:
```python
            set_evid = ", external_video_id = :evid" if external_video_id is not None else ""
            update_params: dict[str, Any] = {
                "s": status, "n": len(comments), "e": error, "now": now, "c": collection_id,
            }
            if external_video_id is not None:
                update_params["evid"] = external_video_id
            self._data_api.execute(
                f"""
                UPDATE comment_collections
                SET status = :s, comment_count = :n, error = :e,
                    collected_at = :now, updated_at = :now{set_evid}
                WHERE id = :c
                """,
                update_params,
                transaction_id=tx,
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: PASS (all, including the existing transactional/store tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/repository.py tests/unit/test_comments_repository.py
git commit -m "feat(comments): let store_comments update external_video_id"
git rev-parse --short HEAD
```

---

## Task 5: Worker primary→fallback flow

**Files:**
- Modify: `src/collector/comments_collect_handler.py`
- Test: `tests/unit/test_comments_collect_handler.py`

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_comments_collect_handler.py`, extend the fakes and add cases. The existing file has `FakeRepo`, `FakeProvider`, `_event`, `_msg`, `_patch`. Update/add:

```python
from collector.comments.repository import TrackMeta  # add to imports


# Extend FakeRepo with metadata + capture external_video_id.
# (If FakeRepo already exists, add these to it.)
class FallbackFakeRepo:
    def __init__(self, meta=None):
        self.stored = []
        self._meta = meta or {"t1": TrackMeta("t1", "Guri", "Lost Track", 200_000)}

    def fetch_track_meta(self, track_ids):
        return {k: v for k, v in self._meta.items() if k in track_ids}

    def store_comments(self, *, collection_id, platform, comments, status, now,
                       error=None, external_video_id=None):
        self.stored.append({
            "status": status, "count": len(comments),
            "external_video_id": external_video_id, "error": error,
        })


class FallbackProvider:
    """Primary collect raises/returns per script; resolver returns alts; each
    alt's collect behavior is scripted by id."""
    def __init__(self, *, primary, alts, alt_behavior):
        self._primary = primary            # callable() -> list or raises
        self._alts = alts                  # list[str]
        self._alt_behavior = alt_behavior  # dict[id] -> list or Exception
        self.resolve_calls = []

    def collect(self, video_ref, *, limit=100):
        if video_ref == "art1":
            if isinstance(self._primary, Exception):
                raise self._primary
            return self._primary
        beh = self._alt_behavior[video_ref]
        if isinstance(beh, Exception):
            raise beh
        return beh

    def resolve_alternate_videos(self, *, artist, title, duration_ms, exclude_video_id):
        self.resolve_calls.append((artist, title, duration_ms, exclude_video_id))
        return self._alts


def _fb_event():
    import json
    return {"Records": [{"body": json.dumps(
        {"track_id": "t1", "platform": "youtube", "video_id": "art1", "collection_id": "col1"}
    )}]}


def _patch_fb(monkeypatch, repo, provider):
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setattr(worker, "get_comment_provider", lambda *a, **k: provider)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")


def test_primary_has_comments_does_not_call_resolver(monkeypatch):
    from collector.providers.base import CollectedComment
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=[CollectedComment("c1", "A", None, "hi", 1, None, 0)],
        alts=["x"], alt_behavior={},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert provider.resolve_calls == []
    assert repo.stored[0]["status"] == "collected"
    assert repo.stored[0]["external_video_id"] == "art1"


def test_disabled_primary_falls_back_to_alternate(monkeypatch):
    from collector.providers.base import CollectedComment
    from collector.providers.youtube.comments import CommentsDisabledError
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"),
        alts=["alt_disabled", "alt_good"],
        alt_behavior={
            "alt_disabled": CommentsDisabledError("alt_disabled"),
            "alt_good": [CollectedComment("c1", "A", None, "hi", 2, None, 0)],
        },
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "collected"
    assert repo.stored[0]["external_video_id"] == "alt_good"


def test_disabled_primary_no_alternates_marks_disabled(monkeypatch):
    from collector.providers.youtube.comments import CommentsDisabledError
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"), alts=[], alt_behavior={},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "disabled"


def test_disabled_primary_all_alternates_disabled(monkeypatch):
    from collector.providers.youtube.comments import CommentsDisabledError
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"),
        alts=["a", "b"],
        alt_behavior={"a": CommentsDisabledError("a"), "b": CommentsDisabledError("b")},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "disabled"


def test_disabled_primary_alternate_empty_marks_empty(monkeypatch):
    from collector.providers.youtube.comments import CommentsDisabledError
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"),
        alts=["a"], alt_behavior={"a": []},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "empty"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comments_collect_handler.py -q`
Expected: FAIL — worker doesn't fetch meta / call resolver / pass `external_video_id`.

- [ ] **Step 3: Implement**

In `src/collector/comments_collect_handler.py`, add a module-level helper (after `_build_repository`):
```python
def _resolve_and_collect(provider: Any, *, primary_video_id: str, meta: Any) -> tuple[str, list, str]:
    """Collect from the primary video; on commentsDisabled, fall back to up to
    3 resolver-provided regular videos. Returns (status, comments, video_id).

    Raises are left to the caller (generic/platform errors -> 'failed')."""
    try:
        comments = provider.collect(primary_video_id, limit=100)
        return ("collected" if comments else "empty", comments, primary_video_id)
    except CommentsDisabledError:
        pass

    resolver = getattr(provider, "resolve_alternate_videos", None)
    if meta is None or resolver is None:
        return ("disabled", [], primary_video_id)

    alts = resolver(
        artist=meta.artist, title=meta.title,
        duration_ms=meta.duration_ms, exclude_video_id=primary_video_id,
    )
    saw_empty = False
    for alt in (alts or [])[:3]:
        try:
            comments = provider.collect(alt, limit=100)
        except CommentsDisabledError:
            continue
        if comments:
            return ("collected", comments, alt)
        saw_empty = True
    return ("empty" if saw_empty else "disabled", [], primary_video_id)
```

Replace the per-record `try:` body (the block that builds the provider, calls `collect`, and the `except CommentsDisabledError` handler) so it fetches meta and uses the helper. The new body of the `try` and the disabled-handler become:
```python
        now = _utc_now()
        try:
            provider = get_comment_provider(
                msg.platform, api_key=settings.youtube_api_key, session=session
            )
            meta = repo.fetch_track_meta([msg.track_id]).get(msg.track_id)
            status, comments, video_id = _resolve_and_collect(
                provider, primary_video_id=msg.video_id, meta=meta
            )
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=comments, status=status, now=now, external_video_id=video_id,
            )
        # Platform not enabled is an ops/config gate (not per-video state); store
        # as "failed" so it is visible in the DB and not silently dropped.
        except CommentPlatformDisabledError as exc:
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="failed", now=now, error=str(exc)[:500],
            )
        except Exception as exc:  # noqa: BLE001 — never retry: 1-request budget
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="failed", now=now, error=str(exc)[:500],
            )
```
(The standalone `except CommentsDisabledError:` handler that previously wrapped the collect is now removed — disabled is handled inside `_resolve_and_collect`. Keep the import of `CommentsDisabledError` at module top; the helper uses it.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comments_collect_handler.py -q`
Expected: PASS (existing worker tests + 5 new fallback tests).

REQUIRED updates to the EXISTING fakes in this file so the prior tests keep passing (the worker now always fetches meta and always passes `external_video_id` to `store_comments`):
- Add a no-op `fetch_track_meta(self, track_ids)` returning `{}` to the existing `FakeRepo`.
- Add `external_video_id=None` to the existing `FakeRepo.store_comments` signature (it currently omits it) so the worker's `external_video_id=` kwarg doesn't raise `TypeError`. (Optionally record it like the new `FallbackFakeRepo` does.)
- The existing `FakeProvider` lacks `resolve_alternate_videos`; that's fine — `getattr(provider, "resolve_alternate_videos", None)` returns None, so a disabled primary still yields `disabled` (matching the existing `test_comments_disabled_path`).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments_collect_handler.py tests/unit/test_comments_collect_handler.py
git commit -m "feat(comments): fall back to regular video when art track comments disabled"
git rev-parse --short HEAD
```

---

## Task 6: Full verification

- [ ] **Step 1: Backend suite**

Run: `cd $WT && /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: all pass (no migration/infra/frontend touched).

- [ ] **Step 2: Confirm no unintended changes**

Run: `cd $WT && git status --porcelain` (expect clean) and `git diff --stat origin/main` (only the 4 backend modules + their tests + the two docs).

- [ ] **Step 3: Finish the branch**

Use `superpowers:finishing-a-development-branch`. PR title/body via `caveman:caveman-commit`. (Deploy is via merge → CI, same as the prior feature; no new secrets/infra needed — ytmusicapi is unauthenticated and already in the lambda package.)

---

## Notes / decisions baked in

- `result_to_ref` already populates `duration_ms` from `duration_seconds` for `videos` results, so duration scoring works (open item resolved).
- No new env/IAM/quota: ytmusicapi is unauthenticated (no key), the worker already reaches Google/YouTube egress, and reads stay on the Data API key (≤4 units/track only when the art track is disabled).
- `external_video_id` becomes the collected-from video; the frontend "Watch on YouTube" link improves automatically with no frontend change.
- Terminal status when no commentable video is found stays within the existing enum (`disabled`/`empty`) — no migration.
```

# YouTube Comments Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a playlist track gains a YouTube (ytmusic) match, automatically collect up to 100 top-level comments from that video into our DB and show the first 5 on the track panel, with a platform-extensible backend.

**Architecture:** Reuse the existing per-track ytmusic match `video_id` (table `vendor_track_map`). On match (auto in the vendor-match worker, manual in the resolve handler) a best-effort dispatcher enqueues an SQS job. A new SQS worker calls a platform-keyed `CommentProvider` (YouTube Data API v3 `commentThreads.list`, shared `YOUTUBE_API_KEY`), stores comments in two new tables (`comment_collections` state + `external_comments` rows), and a `GET /tracks/{track_id}/comments` route serves the first N to the SPA.

**Tech Stack:** Python 3 Lambdas, AWS RDS Data API (no psycopg at runtime), SQS, Alembic, Terraform; React 19 + Mantine 9 + TanStack Query frontend.

---

## Conventions for every task

- **Worktree venv:** `.venv` lives at the MAIN repo root. Run pytest by absolute path:
  `WT=/Users/roman/Projects/clouder-projects/clouder-core/.claude/worktrees/add_comments_collect`
  `PYTEST=/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`
  Run from `$WT`. `pytest.ini` sets `PYTHONPATH=src` for the runner.
- **Commit messages** go through the `caveman:caveman-commit` skill, then `git commit -m "..."`. Conventional Commits. No `Co-Authored-By`. Multi-line bodies use heredoc form.
- Branch is already `feat/youtube-comments-collection`.
- New platform-agnostic domain code lives under `src/collector/comments/`. The YouTube-specific fetch implementation lives under `src/collector/providers/youtube/`.

---

## File Structure

**Backend — create:**
- `alembic/versions/20260621_31_comment_collections.py` — tables `comment_collections`, `external_comments`.
- `src/collector/providers/youtube/__init__.py` — new package.
- `src/collector/providers/youtube/comments.py` — `YouTubeCommentProvider`, `CommentsDisabledError`, JSON parsing.
- `src/collector/comments/__init__.py` — new package.
- `src/collector/comments/registry.py` — `get_comment_provider(platform, ...)`, `CommentPlatformDisabledError`.
- `src/collector/comments/repository.py` — `CommentsRepository`, row dataclasses, `create_default_comments_repository`.
- `src/collector/comments/messages.py` — `CommentCollectMessage` (pydantic).
- `src/collector/comments/dispatch.py` — `try_dispatch_comment_collection`.
- `src/collector/comments_collect_handler.py` — SQS worker lambda.

**Backend — modify:**
- `src/collector/providers/base.py` — add `CollectedComment` dataclass + `CommentProvider` protocol.
- `src/collector/settings.py` — add `CommentCollectionWorkerSettings` + getter + cache reset.
- `src/collector/vendor_match_handler.py` — dispatch hook after a ytmusic match is written.
- `src/collector/curation_handler.py` — dispatch hook in `_handle_resolve_match`; read handler `_handle_list_track_comments`; `_comments_factory`; `_ROUTE_TABLE` entry.
- `scripts/generate_openapi.py` — ROUTES entry + response schema; regenerate `docs/api/openapi.yaml`.

**Infra — modify:**
- `infra/sqs.tf`, `infra/lambda.tf`, `infra/variables.tf`, `infra/locals.tf` (names), `infra/curation.tf`/new `infra/curation_routes_comments.tf` — queue + DLQ + worker lambda + ESM + IAM + env + SSM param + route.

**Frontend — create:**
- `frontend/src/features/playlists/hooks/useTrackComments.ts`
- `frontend/src/features/playlists/components/CommentsPanel.tsx`

**Frontend — modify:**
- `frontend/src/features/playlists/lib/playlistTypes.ts` — comment types.
- `frontend/src/features/playlists/lib/queryKeys.ts` — `trackCommentsKey`.
- `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx` — render `<CommentsPanel>` after `<ArtistsPanel>`.
- `frontend/src/i18n/en.json` — `comments.*` keys.
- `frontend/src/api/schema.d.ts` — regenerated.

---

# Phase A — Provider seam + YouTube provider

## Task 1: Add `CollectedComment` + `CommentProvider` to provider base

**Files:**
- Modify: `src/collector/providers/base.py`
- Test: `tests/unit/test_providers_comments_base.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_providers_comments_base.py`:

```python
"""Unit tests for the comment-provider Protocol surface and shared type."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector.providers.base import CollectedComment, CommentProvider


def test_collected_comment_is_frozen() -> None:
    c = CollectedComment(
        external_id="c1",
        author_name="Foo",
        author_avatar_url=None,
        text="hi",
        like_count=3,
        published_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        rank=0,
    )
    assert c.external_id == "c1"
    assert c.rank == 0
    with pytest.raises(Exception):
        c.text = "other"  # frozen dataclass


def test_comment_provider_is_runtime_checkable() -> None:
    assert not isinstance(object(), CommentProvider)

    class Dummy:
        platform = "youtube"

        def collect(self, video_ref, *, limit=100):
            return []

    assert isinstance(Dummy(), CommentProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_providers_comments_base.py -q`
Expected: FAIL with `ImportError: cannot import name 'CollectedComment'`.

- [ ] **Step 3: Implement**

Append to `src/collector/providers/base.py` (after `EnrichResult`, keep `from datetime import datetime` at top — add the import):

At the top imports, change:
```python
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable
```
to add datetime:
```python
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable
```

Append at end of file:
```python
@dataclass(frozen=True)
class CollectedComment:
    """Platform-agnostic comment captured from an external video/track."""

    external_id: str
    author_name: str
    author_avatar_url: str | None
    text: str
    like_count: int
    published_at: datetime | None
    rank: int  # 0-based position in the provider's returned order


@runtime_checkable
class CommentProvider(Protocol):
    platform: str

    def collect(self, video_ref: str, *, limit: int = 100) -> list["CollectedComment"]:
        """Return up to `limit` top-level comments for `video_ref`."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_providers_comments_base.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/providers/base.py tests/unit/test_providers_comments_base.py
git commit -m "feat(providers): add CollectedComment + CommentProvider seam"
```

---

## Task 2: Implement `YouTubeCommentProvider`

**Files:**
- Create: `src/collector/providers/youtube/__init__.py`
- Create: `src/collector/providers/youtube/comments.py`
- Test: `tests/unit/test_youtube_comment_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_youtube_comment_provider.py`:

```python
from __future__ import annotations

import pytest

from collector.providers.youtube.comments import (
    CommentsDisabledError,
    YouTubeCommentProvider,
)


class FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class FakeSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return self._resp


def _thread(cid, author, text, likes, when, avatar="http://a/x.jpg"):
    return {
        "snippet": {
            "topLevelComment": {
                "id": cid,
                "snippet": {
                    "authorDisplayName": author,
                    "authorProfileImageUrl": avatar,
                    "textDisplay": text,
                    "likeCount": likes,
                    "publishedAt": when,
                },
            }
        }
    }


def test_collect_parses_threads_in_order():
    payload = {"items": [
        _thread("c1", "Alice", "first", 5, "2025-01-02T10:00:00Z"),
        _thread("c2", "Bob", "second", 0, "2025-01-03T11:30:00Z"),
    ]}
    session = FakeSession(FakeResp(200, payload))
    provider = YouTubeCommentProvider(api_key="KEY", session=session)

    out = provider.collect("vid123", limit=100)

    assert provider.platform == "youtube"
    assert [c.external_id for c in out] == ["c1", "c2"]
    assert [c.rank for c in out] == [0, 1]
    assert out[0].author_name == "Alice"
    assert out[0].like_count == 5
    assert out[0].author_avatar_url == "http://a/x.jpg"
    assert out[0].published_at is not None and out[0].published_at.year == 2025
    # request shape
    _, params = session.calls[-1]
    assert params["videoId"] == "vid123"
    assert params["maxResults"] == 100
    assert params["part"] == "snippet"
    assert params["key"] == "KEY"


def test_collect_caps_at_limit():
    payload = {"items": [
        _thread(f"c{i}", "A", "t", 0, "2025-01-02T10:00:00Z") for i in range(10)
    ]}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(200, payload)))
    out = provider.collect("v", limit=3)
    assert len(out) == 3


def test_collect_empty_items_returns_empty():
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(200, {"items": []})))
    assert provider.collect("v") == []


def test_collect_raises_comments_disabled_on_403():
    payload = {"error": {"errors": [{"reason": "commentsDisabled"}]}}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(403, payload)))
    with pytest.raises(CommentsDisabledError):
        provider.collect("v")


def test_collect_other_403_raises_generic():
    payload = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    provider = YouTubeCommentProvider(api_key="K", session=FakeSession(FakeResp(403, payload)))
    with pytest.raises(RuntimeError):
        provider.collect("v")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.providers.youtube.comments`.

- [ ] **Step 3: Implement**

Create `src/collector/providers/youtube/__init__.py`:
```python
"""YouTube Data API v3 providers (comments). Distinct from the ytmusic package."""
```

Create `src/collector/providers/youtube/comments.py`:
```python
"""YouTube Data API v3 comment provider.

Reads public top-level comments via commentThreads.list with a shared
developer key. One request per video (maxResults<=100, single page) = 1
quota unit. The requests session is injected so tests can stub HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..base import CollectedComment

_BASE = "https://www.googleapis.com/youtube/v3/commentThreads"


class CommentsDisabledError(Exception):
    """Raised when the video has comments disabled (HTTP 403 commentsDisabled)."""


class YouTubeCommentProvider:
    platform = "youtube"

    def __init__(self, *, api_key: str, session: Any) -> None:
        self._api_key = api_key
        self._session = session

    def collect(self, video_ref: str, *, limit: int = 100) -> list[CollectedComment]:
        resp = self._session.get(
            _BASE,
            params={
                "part": "snippet",
                "videoId": video_ref,
                "maxResults": min(int(limit), 100),
                "order": "relevance",
                "textFormat": "plainText",
                "key": self._api_key,
            },
            timeout=20,
        )
        if getattr(resp, "status_code", 200) == 403:
            if _first_error_reason(_safe_json(resp)) == "commentsDisabled":
                raise CommentsDisabledError(video_ref)
            resp.raise_for_status()
        resp.raise_for_status()

        data = resp.json() or {}
        out: list[CollectedComment] = []
        for rank, item in enumerate((data.get("items") or [])[:limit]):
            top = ((item.get("snippet") or {}).get("topLevelComment") or {})
            sn = top.get("snippet") or {}
            out.append(
                CollectedComment(
                    external_id=str(top.get("id") or item.get("id") or ""),
                    author_name=str(sn.get("authorDisplayName") or ""),
                    author_avatar_url=sn.get("authorProfileImageUrl"),
                    text=str(sn.get("textDisplay") or ""),
                    like_count=int(sn.get("likeCount") or 0),
                    published_at=_parse_iso(sn.get("publishedAt")),
                    rank=rank,
                )
            )
        return out


def _safe_json(resp: Any) -> dict:
    try:
        return resp.json() or {}
    except Exception:  # noqa: BLE001 — defensive on error bodies
        return {}


def _first_error_reason(data: dict) -> str | None:
    errors = ((data.get("error") or {}).get("errors") or [])
    if errors and isinstance(errors[0], dict):
        return errors[0].get("reason")
    return None


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_youtube_comment_provider.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/providers/youtube tests/unit/test_youtube_comment_provider.py
git commit -m "feat(providers): add YouTube Data API comment provider"
```

---

## Task 3: Comment-provider registry

**Files:**
- Create: `src/collector/comments/__init__.py`
- Create: `src/collector/comments/registry.py`
- Test: `tests/unit/test_comment_registry.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comment_registry.py`:
```python
from __future__ import annotations

import pytest

from collector.comments.registry import (
    CommentPlatformDisabledError,
    get_comment_provider,
)
from collector.providers.youtube.comments import YouTubeCommentProvider


def test_returns_youtube_provider_when_enabled(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "youtube")
    provider = get_comment_provider("youtube", api_key="K", session=object())
    assert isinstance(provider, YouTubeCommentProvider)
    assert provider.platform == "youtube"


def test_disabled_platform_raises(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "")
    with pytest.raises(CommentPlatformDisabledError):
        get_comment_provider("youtube", api_key="K", session=object())


def test_unknown_platform_raises(monkeypatch):
    monkeypatch.setenv("COMMENT_PLATFORMS_ENABLED", "youtube,tiktok")
    with pytest.raises(CommentPlatformDisabledError):
        get_comment_provider("tiktok", api_key="K", session=object())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comment_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.comments.registry`.

- [ ] **Step 3: Implement**

Create `src/collector/comments/__init__.py`:
```python
"""Platform-agnostic comment collection domain (registry, repo, dispatch)."""
```

Create `src/collector/comments/registry.py`:
```python
"""Comment-provider registry, keyed by platform.

Separate from providers.registry (which is keyed by export vendor). Adding a
new platform = one builder entry. Gated by COMMENT_PLATFORMS_ENABLED
(comma-separated, e.g. "youtube").
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from ..providers.base import CommentProvider


class CommentPlatformDisabledError(Exception):
    def __init__(self, platform: str) -> None:
        super().__init__(f"comment platform disabled or unknown: {platform}")
        self.platform = platform


def _build_youtube(*, api_key: str, session: Any) -> CommentProvider:
    from ..providers.youtube.comments import YouTubeCommentProvider

    return YouTubeCommentProvider(api_key=api_key, session=session)


_BUILDERS: dict[str, Callable[..., CommentProvider]] = {
    "youtube": _build_youtube,
}


def _enabled_platforms() -> set[str]:
    raw = os.environ.get("COMMENT_PLATFORMS_ENABLED", "youtube").strip()
    return {p.strip() for p in raw.split(",") if p.strip()}


def get_comment_provider(platform: str, *, api_key: str, session: Any) -> CommentProvider:
    if platform not in _enabled_platforms():
        raise CommentPlatformDisabledError(platform)
    builder = _BUILDERS.get(platform)
    if builder is None:
        raise CommentPlatformDisabledError(platform)
    return builder(api_key=api_key, session=session)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comment_registry.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/__init__.py src/collector/comments/registry.py tests/unit/test_comment_registry.py
git commit -m "feat(comments): add platform-keyed comment provider registry"
```

---

# Phase B — Data model + repository

## Task 4: Alembic migration for comment tables

**Files:**
- Create: `alembic/versions/20260621_31_comment_collections.py`

Migrations aren't unit-tested here; verify with a local Postgres round-trip.

- [ ] **Step 1: Write the migration**

Create `alembic/versions/20260621_31_comment_collections.py`:
```python
"""comment_collections + external_comments

Revision ID: 20260621_31
Revises: 20260531_30
Create Date: 2026-06-21 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260621_31"
down_revision = "20260531_30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "comment_collections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("track_id", sa.String(36), sa.ForeignKey("clouder_tracks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("external_video_id", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'pending'")),
        sa.Column("comment_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("error", sa.Text),
        sa.Column("collected_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("track_id", "platform", name="uq_comment_collections_track_platform"),
        sa.CheckConstraint(
            "status IN ('pending', 'collected', 'empty', 'disabled', 'failed')",
            name="ck_comment_collections_status",
        ),
    )

    op.create_table(
        "external_comments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("comment_collections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.Text, nullable=False),
        sa.Column("external_comment_id", sa.Text, nullable=False),
        sa.Column("author_name", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("author_avatar_url", sa.Text),
        sa.Column("text", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column("like_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("rank", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("collection_id", "external_comment_id", name="uq_external_comments_collection_extid"),
    )
    op.create_index(
        "idx_external_comments_collection_rank",
        "external_comments",
        ["collection_id", "rank"],
    )


def downgrade() -> None:
    op.drop_index("idx_external_comments_collection_rank", table_name="external_comments")
    op.drop_table("external_comments")
    op.drop_table("comment_collections")
```

- [ ] **Step 2: Verify upgrade/downgrade against local Postgres**

```bash
cd $WT
export PYTHONPATH=src
export ALEMBIC_DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5432/postgres'
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic upgrade head
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic downgrade -1
/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/alembic upgrade head
```
Expected: no errors; head ends at `20260621_31`. (If no local Postgres is running, start it per `docs/`; do not skip this verification.)

- [ ] **Step 3: Commit**

```bash
cd $WT && git add alembic/versions/20260621_31_comment_collections.py
git commit -m "feat(db): add comment_collections + external_comments tables"
```

---

## Task 5: `CommentsRepository`

**Files:**
- Create: `src/collector/comments/repository.py`
- Test: `tests/unit/test_comments_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comments_repository.py`:
```python
from __future__ import annotations

from datetime import datetime, timezone

from collector.comments.repository import CommentsRepository
from collector.providers.base import CollectedComment


class FakeDataAPI:
    """Returns canned rows by SQL substring; records calls; fakes a transaction."""

    def __init__(self, rows_by_marker=None):
        self.rows_by_marker = rows_by_marker or []
        self.calls = []
        self.batch_calls = []

    def execute(self, sql, params=None, transaction_id=None):
        self.calls.append((sql, params))
        for marker, rows in self.rows_by_marker:
            if marker in sql:
                return rows
        return []

    def batch_execute(self, sql, parameter_sets, transaction_id=None):
        sets = list(parameter_sets)
        self.batch_calls.append((sql, sets))

    class _Tx:
        def __enter__(self_inner):
            return "tx-1"

        def __exit__(self_inner, *a):
            return False

    def transaction(self):
        return FakeDataAPI._Tx()


NOW = datetime(2026, 6, 21, tzinfo=timezone.utc)


def test_start_collection_skips_when_already_collected_same_video():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "col1", "external_video_id": "vidA", "status": "collected"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="vidA", now=NOW)
    assert result is None
    # no INSERT issued
    assert all("INSERT INTO comment_collections" not in sql for sql, _ in api.calls)


def test_start_collection_inserts_when_new():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections", []),
        ("INSERT INTO comment_collections", [{"id": "colNEW"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="vidA", now=NOW)
    assert result == "colNEW"
    insert_sql, params = [c for c in api.calls if "INSERT INTO comment_collections" in c[0]][0]
    assert params["t"] == "t1" and params["p"] == "youtube" and params["v"] == "vidA"


def test_start_collection_reinserts_when_video_changed():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "col1", "external_video_id": "OLD", "status": "collected"}]),
        ("INSERT INTO comment_collections", [{"id": "col1"}]),
    ])
    repo = CommentsRepository(api)
    assert repo.start_collection(track_id="t1", platform="youtube", video_id="NEW", now=NOW) == "col1"


def test_store_comments_deletes_then_batch_inserts_and_marks_collected():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    comments = [
        CollectedComment("c1", "A", None, "hi", 2, NOW, 0),
        CollectedComment("c2", "B", "http://x", "yo", 0, None, 1),
    ]
    repo.store_comments(collection_id="col1", platform="youtube", comments=comments,
                        status="collected", now=NOW)
    assert any("DELETE FROM external_comments" in sql for sql, _ in api.calls)
    assert len(api.batch_calls) == 1
    _, sets = api.batch_calls[0]
    assert [s["eid"] for s in sets] == ["c1", "c2"]
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][0]
    assert params["s"] == "collected" and params["n"] == 2


def test_store_comments_empty_skips_batch_and_marks_status():
    api = FakeDataAPI()
    repo = CommentsRepository(api)
    repo.store_comments(collection_id="col1", platform="youtube", comments=[],
                        status="empty", now=NOW)
    assert api.batch_calls == []
    update_sql, params = [c for c in api.calls if "UPDATE comment_collections" in c[0]][0]
    assert params["s"] == "empty" and params["n"] == 0


def test_list_comments_returns_collection_and_rows():
    api = FakeDataAPI([
        ("SELECT id, track_id, platform, external_video_id, status, comment_count, collected_at",
         [{"id": "col1", "track_id": "t1", "platform": "youtube",
           "external_video_id": "vidA", "status": "collected", "comment_count": 2,
           "collected_at": None}]),
        ("FROM external_comments",
         [{"author_name": "A", "author_avatar_url": None, "text": "hi",
           "like_count": 2, "published_at": None, "rank": 0}]),
    ])
    repo = CommentsRepository(api)
    collection, comments = repo.list_comments(track_id="t1", platform="youtube", limit=5)
    assert collection is not None and collection.status == "collected"
    assert collection.external_video_id == "vidA"
    assert len(comments) == 1 and comments[0].author_name == "A"


def test_list_comments_none_when_no_collection():
    api = FakeDataAPI([])
    repo = CommentsRepository(api)
    collection, comments = repo.list_comments(track_id="t1", platform="youtube", limit=5)
    assert collection is None and comments == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.comments.repository`.

- [ ] **Step 3: Implement**

Create `src/collector/comments/repository.py`:
```python
"""Data-access for comment collections (RDS Data API, no psycopg)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..data_api import DataAPIClient, create_default_data_api_client
from ..providers.base import CollectedComment
from ..settings import get_data_api_settings


@dataclass(frozen=True)
class CollectionRow:
    id: str
    track_id: str
    platform: str
    external_video_id: str
    status: str
    comment_count: int
    collected_at: datetime | None


@dataclass(frozen=True)
class CommentRow:
    author_name: str
    author_avatar_url: str | None
    text: str
    like_count: int
    published_at: Any  # str|datetime from Data API; serialized as-is by the handler
    rank: int


class CommentsRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def start_collection(
        self, *, track_id: str, platform: str, video_id: str, now: datetime
    ) -> str | None:
        """Insert/refresh a pending collection. Returns the collection id, or
        None if a completed collection for the same video already exists."""
        existing = self._data_api.execute(
            "SELECT id, external_video_id, status FROM comment_collections "
            "WHERE track_id = :t AND platform = :p",
            {"t": track_id, "p": platform},
        )
        if existing:
            row = existing[0]
            if row["status"] == "collected" and row["external_video_id"] == video_id:
                return None

        rows = self._data_api.execute(
            """
            INSERT INTO comment_collections
                (id, track_id, platform, external_video_id, status, comment_count, created_at, updated_at)
            VALUES (:id, :t, :p, :v, 'pending', 0, :now, :now)
            ON CONFLICT (track_id, platform) DO UPDATE SET
                external_video_id = EXCLUDED.external_video_id,
                status = 'pending',
                comment_count = 0,
                error = NULL,
                collected_at = NULL,
                updated_at = EXCLUDED.updated_at
            RETURNING id
            """,
            {"id": str(uuid4()), "t": track_id, "p": platform, "v": video_id, "now": now},
        )
        return rows[0]["id"] if rows else None

    def store_comments(
        self,
        *,
        collection_id: str,
        platform: str,
        comments: list[CollectedComment],
        status: str,
        now: datetime,
        error: str | None = None,
    ) -> None:
        with self._data_api.transaction() as tx:
            self._data_api.execute(
                "DELETE FROM external_comments WHERE collection_id = :c",
                {"c": collection_id},
                transaction_id=tx,
            )
            if comments:
                self._data_api.batch_execute(
                    """
                    INSERT INTO external_comments
                        (id, collection_id, platform, external_comment_id, author_name,
                         author_avatar_url, text, like_count, published_at, rank, created_at)
                    VALUES (:id, :c, :p, :eid, :an, :av, :txt, :lk, :pub, :rk, :now)
                    """,
                    [
                        {
                            "id": str(uuid4()),
                            "c": collection_id,
                            "p": platform,
                            "eid": cm.external_id,
                            "an": cm.author_name,
                            "av": cm.author_avatar_url,
                            "txt": cm.text,
                            "lk": cm.like_count,
                            "pub": cm.published_at,
                            "rk": cm.rank,
                            "now": now,
                        }
                        for cm in comments
                    ],
                    transaction_id=tx,
                )
            self._data_api.execute(
                """
                UPDATE comment_collections
                SET status = :s, comment_count = :n, error = :e,
                    collected_at = :now, updated_at = :now
                WHERE id = :c
                """,
                {"s": status, "n": len(comments), "e": error, "now": now, "c": collection_id},
                transaction_id=tx,
            )

    def list_comments(
        self, *, track_id: str, platform: str, limit: int
    ) -> tuple[CollectionRow | None, list[CommentRow]]:
        coll = self._data_api.execute(
            "SELECT id, track_id, platform, external_video_id, status, comment_count, collected_at "
            "FROM comment_collections WHERE track_id = :t AND platform = :p",
            {"t": track_id, "p": platform},
        )
        if not coll:
            return None, []
        c = coll[0]
        collection = CollectionRow(
            id=c["id"],
            track_id=c["track_id"],
            platform=c["platform"],
            external_video_id=c["external_video_id"],
            status=c["status"],
            comment_count=int(c["comment_count"]),
            collected_at=c["collected_at"],
        )
        rows = self._data_api.execute(
            "SELECT author_name, author_avatar_url, text, like_count, published_at, rank "
            "FROM external_comments WHERE collection_id = :c ORDER BY rank ASC LIMIT :lim",
            {"c": collection.id, "lim": int(limit)},
        )
        comments = [
            CommentRow(
                author_name=r["author_name"],
                author_avatar_url=r["author_avatar_url"],
                text=r["text"],
                like_count=int(r["like_count"]),
                published_at=r["published_at"],
                rank=int(r["rank"]),
            )
            for r in rows
        ]
        return collection, comments


def create_default_comments_repository() -> CommentsRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None
    client = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return CommentsRepository(data_api=client)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comments_repository.py -q`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/repository.py tests/unit/test_comments_repository.py
git commit -m "feat(comments): add CommentsRepository (Data API)"
```

---

# Phase C — Settings, message, dispatch, worker

## Task 6: Worker settings + `YOUTUBE_API_KEY`

**Files:**
- Modify: `src/collector/settings.py`
- Test: `tests/unit/test_comment_collection_settings.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comment_collection_settings.py`:
```python
from __future__ import annotations

from collector.settings import (
    get_comment_collection_worker_settings,
    reset_settings_cache,
)


def test_youtube_api_key_resolved_from_env(monkeypatch):
    reset_settings_cache()
    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key-123")
    s = get_comment_collection_worker_settings()
    assert s.youtube_api_key == "yt-key-123"
    reset_settings_cache()


def test_youtube_api_key_defaults_empty(monkeypatch):
    reset_settings_cache()
    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY_SSM_PARAMETER", raising=False)
    monkeypatch.delenv("YOUTUBE_API_KEY_SECRET_ARN", raising=False)
    s = get_comment_collection_worker_settings()
    assert s.youtube_api_key == ""
    reset_settings_cache()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comment_collection_settings.py -q`
Expected: FAIL with `ImportError: cannot import name 'get_comment_collection_worker_settings'`.

- [ ] **Step 3: Implement**

In `src/collector/settings.py`, add the settings class after `ArtistEnrichmentWorkerSettings` (around line 222):
```python
class CommentCollectionWorkerSettings(_SettingsBase):
    youtube_api_key: str = Field(default="")
    request_timeout_s: float = Field(
        default=30.0, alias="COMMENT_COLLECT_REQUEST_TIMEOUT_S", ge=1.0,
    )
```

Add the getter after `get_artist_enrichment_worker_settings` (around line 274):
```python
@functools.lru_cache
def get_comment_collection_worker_settings() -> CommentCollectionWorkerSettings:
    youtube = _resolve_simple_secret("YOUTUBE_API_KEY", "YOUTUBE_API_KEY_SECRET_ARN")
    return CommentCollectionWorkerSettings(youtube_api_key=youtube)
```

In `reset_settings_cache()` (line 291), add this line alongside the others:
```python
    get_comment_collection_worker_settings.cache_clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comment_collection_settings.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/settings.py tests/unit/test_comment_collection_settings.py
git commit -m "feat(settings): add comment-collection worker settings (YOUTUBE_API_KEY)"
```

---

## Task 7: SQS message schema

**Files:**
- Create: `src/collector/comments/messages.py`
- Test: `tests/unit/test_comment_message.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comment_message.py`:
```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from collector.comments.messages import CommentCollectMessage


def test_roundtrip_json():
    msg = CommentCollectMessage(
        track_id="t1", platform="youtube", video_id="vidA", collection_id="col1"
    )
    raw = msg.model_dump_json()
    again = CommentCollectMessage.model_validate_json(raw)
    assert again.track_id == "t1"
    assert again.platform == "youtube"
    assert again.video_id == "vidA"
    assert again.collection_id == "col1"


def test_missing_field_rejected():
    with pytest.raises(ValidationError):
        CommentCollectMessage.model_validate({"track_id": "t1", "platform": "youtube"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comment_message.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.comments.messages`.

- [ ] **Step 3: Implement**

Create `src/collector/comments/messages.py`:
```python
"""SQS message contract for the comment-collection worker."""

from __future__ import annotations

from pydantic import BaseModel


class CommentCollectMessage(BaseModel):
    track_id: str
    platform: str
    video_id: str
    collection_id: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comment_message.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/messages.py tests/unit/test_comment_message.py
git commit -m "feat(comments): add CommentCollectMessage schema"
```

---

## Task 8: Best-effort dispatcher

**Files:**
- Create: `src/collector/comments/dispatch.py`
- Test: `tests/unit/test_comment_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comment_dispatch.py`:
```python
from __future__ import annotations

import collector.comments.dispatch as dispatch


class FakeRepo:
    def __init__(self, start_result):
        self._start_result = start_result
        self.start_calls = []

    def start_collection(self, *, track_id, platform, video_id, now):
        self.start_calls.append((track_id, platform, video_id))
        return self._start_result


class FakeSqs:
    def __init__(self):
        self.sent = []

    def send_message(self, *, QueueUrl, MessageBody):
        self.sent.append((QueueUrl, MessageBody))


def _patch(monkeypatch, repo, sqs, queue="https://q"):
    monkeypatch.setattr(dispatch, "_build_repository", lambda: repo)
    monkeypatch.setattr(dispatch, "_build_sqs_client", lambda: sqs)
    monkeypatch.setenv("COMMENT_COLLECT_QUEUE_URL", queue)


def test_dispatch_sends_message_for_new_collection(monkeypatch):
    repo, sqs = FakeRepo("col1"), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")
    assert len(sqs.sent) == 1
    assert repo.start_calls == [("t1", "youtube", "vidA")]


def test_dispatch_skips_when_already_collected(monkeypatch):
    repo, sqs = FakeRepo(None), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")
    assert sqs.sent == []


def test_dispatch_noop_on_empty_video(monkeypatch):
    repo, sqs = FakeRepo("col1"), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="", platform="youtube")
    assert sqs.sent == [] and repo.start_calls == []


def test_dispatch_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(dispatch, "_build_repository", boom)
    monkeypatch.setenv("COMMENT_COLLECT_QUEUE_URL", "https://q")
    # must not raise
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="vidA", platform="youtube")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comment_dispatch.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.comments.dispatch`.

- [ ] **Step 3: Implement**

Create `src/collector/comments/dispatch.py`:
```python
"""Best-effort dispatch of comment-collection jobs from curation/match paths.

Called inline after a track gains a YouTube match. Never raises — collection
must never break the originating request. Mirrors label_enrichment.auto_dispatch.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ..logging_utils import log_event
from .messages import CommentCollectMessage
from .repository import CommentsRepository, create_default_comments_repository


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def _build_sqs_client():
    import boto3

    return boto3.client("sqs")


def _queue_url() -> str:
    url = os.environ.get("COMMENT_COLLECT_QUEUE_URL", "").strip()
    if not url:
        raise RuntimeError("COMMENT_COLLECT_QUEUE_URL is required")
    return url


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break caller
        log_event("ERROR", "comment_dispatch_error", error_message=str(exc)[:500])


def try_dispatch_comment_collection(
    *, track_id: str, video_id: str, platform: str = "youtube", user_id: str | None = None
) -> None:
    def _run() -> None:
        if not video_id:
            return
        repo = _build_repository()
        collection_id = repo.start_collection(
            track_id=track_id, platform=platform, video_id=video_id, now=_utc_now()
        )
        if collection_id is None:
            log_event(
                "INFO", "comment_dispatch_skipped_collected",
                track_id=track_id, platform=platform,
            )
            return
        msg = CommentCollectMessage(
            track_id=track_id, platform=platform, video_id=video_id, collection_id=collection_id
        )
        _build_sqs_client().send_message(
            QueueUrl=_queue_url(), MessageBody=msg.model_dump_json()
        )
        log_event(
            "INFO", "comment_dispatch_enqueued",
            track_id=track_id, platform=platform, collection_id=collection_id,
        )

    _safe(_run)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comment_dispatch.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments/dispatch.py tests/unit/test_comment_dispatch.py
git commit -m "feat(comments): add best-effort collection dispatcher"
```

---

## Task 9: Worker lambda

**Files:**
- Create: `src/collector/comments_collect_handler.py`
- Test: `tests/unit/test_comments_collect_handler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comments_collect_handler.py`:
```python
from __future__ import annotations

import json

import collector.comments_collect_handler as worker
from collector.providers.base import CollectedComment
from collector.providers.youtube.comments import CommentsDisabledError


class FakeRepo:
    def __init__(self):
        self.stored = []

    def store_comments(self, *, collection_id, platform, comments, status, now, error=None):
        self.stored.append({"collection_id": collection_id, "status": status,
                            "count": len(comments), "error": error})


class FakeProvider:
    def __init__(self, result=None, exc=None):
        self._result = result or []
        self._exc = exc

    def collect(self, video_ref, *, limit=100):
        if self._exc:
            raise self._exc
        return self._result


def _event(*msgs):
    return {"Records": [{"body": json.dumps(m)} for m in msgs]}


def _msg(collection_id="col1", video_id="vidA"):
    return {"track_id": "t1", "platform": "youtube",
            "video_id": video_id, "collection_id": collection_id}


def _patch(monkeypatch, repo, provider):
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setattr(worker, "get_comment_provider", lambda *a, **k: provider)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")


def test_collected_path(monkeypatch):
    repo = FakeRepo()
    provider = FakeProvider(result=[CollectedComment("c1", "A", None, "hi", 1, None, 0)])
    _patch(monkeypatch, repo, provider)
    out = worker.lambda_handler(_event(_msg()), None)
    assert out["processed"] == 1
    assert repo.stored[0]["status"] == "collected" and repo.stored[0]["count"] == 1


def test_empty_path(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(result=[]))
    worker.lambda_handler(_event(_msg()), None)
    assert repo.stored[0]["status"] == "empty"


def test_comments_disabled_path(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(exc=CommentsDisabledError("v")))
    worker.lambda_handler(_event(_msg()), None)
    assert repo.stored[0]["status"] == "disabled"


def test_generic_error_marks_failed_and_does_not_raise(monkeypatch):
    repo = FakeRepo()
    _patch(monkeypatch, repo, FakeProvider(exc=RuntimeError("network")))
    out = worker.lambda_handler(_event(_msg()), None)
    assert out["processed"] == 1
    assert repo.stored[0]["status"] == "failed"
    assert "network" in repo.stored[0]["error"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_comments_collect_handler.py -q`
Expected: FAIL with `ModuleNotFoundError: collector.comments_collect_handler`.

- [ ] **Step 3: Implement**

Create `src/collector/comments_collect_handler.py`:
```python
"""SQS-driven Lambda that collects comments for one video per record."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from pydantic import ValidationError as PydanticValidationError

from .comments.messages import CommentCollectMessage
from .comments.registry import CommentPlatformDisabledError, get_comment_provider
from .comments.repository import CommentsRepository, create_default_comments_repository
from .logging_utils import log_event
from .providers.youtube.comments import CommentsDisabledError
from .settings import get_comment_collection_worker_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    records = event.get("Records") or []
    if not isinstance(records, list):
        return {"processed": 0}

    log_event("INFO", "comments_collect_worker_invoked", sqs_record_count=len(records))

    import requests

    repo = _build_repository()
    settings = get_comment_collection_worker_settings()
    session = requests.Session()

    processed = 0
    for record in records:
        if not isinstance(record, Mapping):
            continue
        body = record.get("body")
        if not isinstance(body, str):
            continue
        try:
            msg = CommentCollectMessage.model_validate_json(body)
        except PydanticValidationError as exc:
            log_event("ERROR", "comments_collect_message_invalid", error_message=str(exc)[:500])
            continue

        now = _utc_now()
        try:
            provider = get_comment_provider(
                msg.platform, api_key=settings.youtube_api_key, session=session
            )
            comments = provider.collect(msg.video_id, limit=100)
            status = "collected" if comments else "empty"
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=comments, status=status, now=now,
            )
        except CommentsDisabledError:
            repo.store_comments(
                collection_id=msg.collection_id, platform=msg.platform,
                comments=[], status="disabled", now=now,
            )
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
        processed += 1
        log_event(
            "INFO", "comments_collect_completed",
            collection_id=msg.collection_id, platform=msg.platform,
        )

    return {"processed": processed}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_comments_collect_handler.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/comments_collect_handler.py tests/unit/test_comments_collect_handler.py
git commit -m "feat(comments): add SQS worker handler"
```

---

# Phase D — Wire dispatch hooks

## Task 10: Auto-match hook in the vendor-match worker

**Files:**
- Modify: `src/collector/vendor_match_handler.py`
- Test: `tests/unit/test_vendor_match_comment_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vendor_match_comment_dispatch.py`:
```python
from __future__ import annotations

from decimal import Decimal

import collector.vendor_match_handler as vmh
from collector.providers.base import VendorTrackRef
from collector.schemas import VendorMatchMessage


class FakeRepo:
    def __init__(self):
        self.upserts = []

    def get_vendor_match(self, track_id, vendor):
        return None

    def upsert_vendor_match(self, cmd):
        self.upserts.append(cmd)


class FakeLookup:
    def __init__(self, ref):
        self._ref = ref
        self.vendor_name = "ytmusic"

    def lookup_by_isrc(self, isrc):
        return self._ref

    def lookup_by_metadata(self, *a, **k):
        return []


def _ref():
    return VendorTrackRef(
        vendor="ytmusic", vendor_track_id="vidYT", isrc="GB1",
        artist_names=("A",), title="T", duration_ms=1000,
        album_name=None, raw_payload={"videoId": "vidYT"},
    )


def test_isrc_match_dispatches_comments(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vmh, "try_dispatch_comment_collection",
        lambda **kw: calls.append(kw),
    )
    monkeypatch.setattr(vmh.registry, "get_lookup", lambda v: FakeLookup(_ref()))

    msg = VendorMatchMessage(
        clouder_track_id="t1", vendor="ytmusic", isrc="GB1",
        artist="A", title="T", duration_ms=1000, album=None,
    )
    assert vmh._process_one(msg, FakeRepo()) is True
    assert calls == [{"track_id": "t1", "video_id": "vidYT", "platform": "youtube"}]


def test_non_ytmusic_match_does_not_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        vmh, "try_dispatch_comment_collection",
        lambda **kw: calls.append(kw),
    )
    ref = _ref()
    monkeypatch.setattr(vmh.registry, "get_lookup", lambda v: FakeLookup(ref))

    msg = VendorMatchMessage(
        clouder_track_id="t1", vendor="spotify", isrc="GB1",
        artist="A", title="T", duration_ms=1000, album=None,
    )
    vmh._process_one(msg, FakeRepo())
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_vendor_match_comment_dispatch.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'try_dispatch_comment_collection'`.

- [ ] **Step 3: Implement**

In `src/collector/vendor_match_handler.py`, add the import near the other `from .` imports (after line 15 `from .providers import registry`):
```python
from .comments.dispatch import try_dispatch_comment_collection
```

In `_process_one`, after the **ISRC** upsert block — i.e. immediately after the `repository.upsert_vendor_match(...)` call that ends at line 115 and before its `log_event` — leave the log, then after the `return True` for ISRC, instead dispatch first. Concretely, change the ISRC success block so the dispatch happens before `return True`:

Find:
```python
        if ref is not None:
            repository.upsert_vendor_match(
                UpsertVendorMatchCmd(
                    clouder_track_id=message.clouder_track_id,
                    vendor=message.vendor,
                    vendor_track_id=ref.vendor_track_id,
                    match_type="isrc",
                    confidence=Decimal("1.000"),
                    matched_at=now,
                    payload=ref.raw_payload,
                )
            )
            log_event(
                "INFO",
                "vendor_match_cached",
                track_id=message.clouder_track_id,
                vendor=message.vendor,
                match_type="isrc",
                confidence=1.0,
            )
            return True
```
Replace the `return True` line with:
```python
            _maybe_dispatch_comments(message.vendor, message.clouder_track_id, ref.vendor_track_id)
            return True
```

Find the **fuzzy** success block:
```python
        log_event(
            "INFO",
            "vendor_match_cached",
            track_id=message.clouder_track_id,
            vendor=message.vendor,
            match_type="fuzzy",
            confidence=float(best_score.total),
        )
        return True
```
Replace its `return True` with:
```python
        _maybe_dispatch_comments(message.vendor, message.clouder_track_id, best_cand.vendor_track_id)
        return True
```

Add this helper at module level (e.g. just below `lambda_handler`):
```python
def _maybe_dispatch_comments(vendor: str, track_id: str, video_id: str) -> None:
    """Trigger comment collection only for the YouTube (ytmusic) vendor."""
    from .vendor_match.enqueue import YTMUSIC_VENDOR

    if vendor != YTMUSIC_VENDOR:
        return
    try_dispatch_comment_collection(
        track_id=track_id, video_id=video_id, platform="youtube"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_vendor_match_comment_dispatch.py tests/unit/test_vendor_match_handler.py -q`
Expected: PASS (new 2 + existing suite green).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/vendor_match_handler.py tests/unit/test_vendor_match_comment_dispatch.py
git commit -m "feat(comments): dispatch collection on auto ytmusic match"
```

---

## Task 11: Manual-accept hook in the resolve handler

**Files:**
- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_resolve_match_comment_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_resolve_match_comment_dispatch.py`:
```python
from __future__ import annotations

import json

import collector.curation_handler as ch


class FakeRepo:
    def get_open_review(self, *, track_id, vendor):
        return None

    def resolve_review_accept(self, **kwargs):
        self.accepted = kwargs

    def resolve_review_reject(self, **kwargs):
        self.rejected = kwargs

    # _scope_check uses these — keep permissive
    def assert_track_in_user_scope(self, *a, **k):
        return None


def _event(action, vendor="ytmusic", vendor_track_id="dQw4w9WgXcQ"):
    # vendor_track_id is exactly 11 chars to satisfy YT_VIDEO_ID_RE.
    return {
        "pathParameters": {"id": "p1", "track_id": "t1"},
        "body": json.dumps({
            "action": action, "vendor": vendor, "vendor_track_id": vendor_track_id,
        }),
    }


def test_accept_ytmusic_dispatches(monkeypatch):
    calls = []
    monkeypatch.setattr(ch, "try_dispatch_comment_collection", lambda **kw: calls.append(kw))
    monkeypatch.setattr(ch, "_scope_check", lambda *a, **k: None)
    ch._handle_resolve_match(_event("accept"), FakeRepo(), "u1", "corr")
    assert calls == [{"track_id": "t1", "video_id": "dQw4w9WgXcQ", "platform": "youtube"}]


def test_reject_does_not_dispatch(monkeypatch):
    calls = []
    monkeypatch.setattr(ch, "try_dispatch_comment_collection", lambda **kw: calls.append(kw))
    monkeypatch.setattr(ch, "_scope_check", lambda *a, **k: None)
    ch._handle_resolve_match(_event("reject"), FakeRepo(), "u1", "corr")
    assert calls == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_resolve_match_comment_dispatch.py -q`
Expected: FAIL with `AttributeError: ... has no attribute 'try_dispatch_comment_collection'`.

- [ ] **Step 3: Implement**

In `src/collector/curation_handler.py`, add the import alongside other top-level `from collector...`/`from .` imports:
```python
from .comments.dispatch import try_dispatch_comment_collection
```
(If the file imports via `from collector.comments.dispatch import ...` style elsewhere, match that style. Use the same relative/absolute convention as neighbouring imports in the file.)

In `_handle_resolve_match` (line 349), at the end of the `if body.action == "accept":` branch — after the `repo.resolve_review_accept(...)` call (ends ~line 372) — add:
```python
        if body.vendor == "ytmusic":
            try_dispatch_comment_collection(
                track_id=track_id, video_id=body.vendor_track_id, platform="youtube"
            )
```
Keep the existing `else:` reject branch unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_resolve_match_comment_dispatch.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/curation_handler.py tests/unit/test_resolve_match_comment_dispatch.py
git commit -m "feat(comments): dispatch collection on manual match accept"
```

---

# Phase E — Read API

## Task 12: `GET /tracks/{track_id}/comments` handler + route

**Files:**
- Modify: `src/collector/curation_handler.py`
- Test: `tests/unit/test_curation_handler_comments.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_curation_handler_comments.py`:
```python
from __future__ import annotations

import json

import collector.curation_handler as ch
from collector.comments.repository import CollectionRow, CommentRow


class FakeCommentsRepo:
    def __init__(self, collection, comments):
        self._collection = collection
        self._comments = comments
        self.calls = []

    def list_comments(self, *, track_id, platform, limit):
        self.calls.append((track_id, platform, limit))
        return self._collection, self._comments


def _event(track_id="t1", qs=None):
    return {"pathParameters": {"track_id": track_id}, "queryStringParameters": qs}


def test_returns_collected_comments():
    collection = CollectionRow("col1", "t1", "youtube", "vidA", "collected", 2, None)
    comments = [CommentRow("Alice", None, "hi", 3, None, 0)]
    repo = FakeCommentsRepo(collection, comments)
    resp = ch._handle_list_track_comments(_event(qs={"limit": "5"}), repo, "u1", "corr")
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["status"] == "collected"
    assert body["comment_count"] == 2
    assert body["video_url"] == "https://www.youtube.com/watch?v=vidA"
    assert body["comments"][0]["author_name"] == "Alice"
    assert repo.calls == [("t1", "youtube", 5)]


def test_no_collection_returns_pending_envelope():
    repo = FakeCommentsRepo(None, [])
    resp = ch._handle_list_track_comments(_event(), repo, "u1", "corr")
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["status"] == "pending"
    assert body["comments"] == [] and body["video_url"] is None


def test_limit_defaults_and_caps():
    collection = CollectionRow("col1", "t1", "youtube", "vidA", "collected", 0, None)
    repo = FakeCommentsRepo(collection, [])
    ch._handle_list_track_comments(_event(qs={"limit": "999"}), repo, "u1", "corr")
    assert repo.calls[-1][2] == 100
    ch._handle_list_track_comments(_event(qs=None), repo, "u1", "corr")
    assert repo.calls[-1][2] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && $PYTEST tests/unit/test_curation_handler_comments.py -q`
Expected: FAIL with `AttributeError: ... has no attribute '_handle_list_track_comments'`.

- [ ] **Step 3: Implement**

In `src/collector/curation_handler.py`, add the factory near the other factories (after `_tags_factory`, line 1779):
```python
def _comments_factory() -> Any:
    from collector.comments.repository import create_default_comments_repository

    return create_default_comments_repository()
```

Add the handler (place it near the other track read handlers, e.g. after `_handle_list_track_tags` at line 1707):
```python
def _handle_list_track_comments(event, repo, user_id, correlation_id):
    pp = event.get("pathParameters") or {}
    track_id = pp.get("track_id")
    if not track_id:
        raise ValidationError("track_id is required in path")

    qs = event.get("queryStringParameters") or {}
    platform = (qs.get("platform") or "youtube").strip() or "youtube"
    try:
        limit = int(qs.get("limit") or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 100))

    collection, comments = repo.list_comments(
        track_id=track_id, platform=platform, limit=limit
    )
    if collection is None:
        return _json_response(
            200,
            {"status": "pending", "comment_count": 0, "video_url": None, "comments": []},
            correlation_id,
        )

    video_url = (
        f"https://www.youtube.com/watch?v={collection.external_video_id}"
        if platform == "youtube"
        else None
    )
    return _json_response(
        200,
        {
            "status": collection.status,
            "comment_count": collection.comment_count,
            "video_url": video_url,
            "comments": [
                {
                    "author_name": c.author_name,
                    "author_avatar_url": c.author_avatar_url,
                    "text": c.text,
                    "like_count": c.like_count,
                    "published_at": (
                        c.published_at.isoformat()
                        if hasattr(c.published_at, "isoformat")
                        else c.published_at
                    ),
                }
                for c in comments
            ],
        },
        correlation_id,
    )
```

Add the route to `_ROUTE_TABLE` (after the `GET /tracks/{track_id}/tags` entry, line 1919):
```python
    "GET /tracks/{track_id}/comments": (_handle_list_track_comments, _comments_factory),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && $PYTEST tests/unit/test_curation_handler_comments.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add src/collector/curation_handler.py tests/unit/test_curation_handler_comments.py
git commit -m "feat(api): add GET /tracks/{track_id}/comments"
```

---

## Task 13: OpenAPI route + regeneration

**Files:**
- Modify: `scripts/generate_openapi.py`
- Regenerate: `docs/api/openapi.yaml`

- [ ] **Step 1: Add the response schema + route to `scripts/generate_openapi.py`**

Near the other shared schemas (top of file, alongside `TAG_RESPONSE`, ~line 137), add:
```python
COMMENT_RESPONSE: dict[str, Any] = {
    "type": "object",
    "required": ["author_name", "text", "like_count"],
    "properties": {
        "author_name": {"type": "string"},
        "author_avatar_url": {"type": "string", "nullable": True},
        "text": {"type": "string"},
        "like_count": {"type": "integer"},
        "published_at": {"type": "string", "format": "date-time", "nullable": True},
    },
}

TRACK_COMMENTS_RESPONSE: dict[str, Any] = {
    "type": "object",
    "required": ["status", "comment_count", "comments"],
    "properties": {
        "status": {
            "type": "string",
            "enum": ["pending", "collected", "empty", "disabled", "failed"],
        },
        "comment_count": {"type": "integer"},
        "video_url": {"type": "string", "nullable": True},
        "comments": {"type": "array", "items": COMMENT_RESPONSE},
    },
}
```

In the `ROUTES` list (the per-track tags block, ~line 2509), add an entry mirroring the tags GET shape:
```python
    {
        "method": "get",
        "path": "/tracks/{track_id}/comments",
        "summary": "List collected external comments for a track (first N).",
        "description": (
            "Returns YouTube comments collected for the track's matched video. "
            "`status` is pending until collection completes. Query: `platform` "
            "(default youtube), `limit` (default 5, max 100)."
        ),
        "tags": ["tracks"],
        "parameters": [
            {"name": "track_id", "in": "path", "required": True, "schema": {"type": "string"}},
            {"name": "platform", "in": "query", "required": False, "schema": {"type": "string"}},
            {"name": "limit", "in": "query", "required": False, "schema": {"type": "integer"}},
        ],
        "responses": {
            "200": _make_response(200, "Track comments.", TRACK_COMMENTS_RESPONSE),
        },
    },
```
(Match the exact key names/helpers used by neighbouring entries — e.g. if other routes use `_make_response`, `_error`, or a `"security"` key, copy that shape from the adjacent `/tracks/{track_id}/tags` GET entry. Read that entry first and mirror it precisely.)

- [ ] **Step 2: Regenerate the spec and confirm it changed**

```bash
cd $WT
PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py
git diff --stat docs/api/openapi.yaml
grep -n "/tracks/{track_id}/comments" docs/api/openapi.yaml
```
Expected: `openapi.yaml` shows the new path.

- [ ] **Step 3: Commit**

```bash
cd $WT && git add scripts/generate_openapi.py docs/api/openapi.yaml
git commit -m "docs(api): add /tracks/{track_id}/comments to OpenAPI"
```

---

# Phase F — Infrastructure (Terraform)

> Read the existing `vendor_match` and `label_enrichment` blocks first; mirror their exact variable and resource names. Each step says what to add. `terraform validate` is the gate (no apply in this plan unless the user asks).

## Task 14: Queue + DLQ

**Files:** `infra/sqs.tf`, `infra/locals.tf` (queue name locals), `infra/variables.tf`

- [ ] **Step 1: Add variables** (mirror the `label_enrichment_*` queue vars in `infra/variables.tf`):
```hcl
variable "comments_collect_queue_visibility_timeout_seconds" { type = number  default = 120 }
variable "comments_collect_queue_retention_seconds"          { type = number  default = 1209600 }
variable "comments_collect_queue_max_receive_count"          { type = number  default = 3 }
variable "comments_collect_worker_lambda_timeout_seconds"    { type = number  default = 60 }
```

- [ ] **Step 2: Add name locals** in `infra/locals.tf` next to `label_enrichment_queue_name` / `*_dlq_name` (use the same `${local.name_prefix}`/`beatport-prod-*` convention you find there):
```hcl
  comments_collect_queue_name = "${local.name_prefix}-comments-collect"
  comments_collect_dlq_name   = "${local.name_prefix}-comments-collect-dlq"
```

- [ ] **Step 3: Add queues** in `infra/sqs.tf` (mirror the `label_enrichment` pair, lines 64-83):
```hcl
resource "aws_sqs_queue" "comments_collect_dlq" {
  name                      = local.comments_collect_dlq_name
  message_retention_seconds = var.comments_collect_queue_retention_seconds
}

resource "aws_sqs_queue" "comments_collect" {
  name = local.comments_collect_queue_name
  visibility_timeout_seconds = max(
    var.comments_collect_queue_visibility_timeout_seconds,
    var.comments_collect_worker_lambda_timeout_seconds
  )
  message_retention_seconds = var.comments_collect_queue_retention_seconds
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.comments_collect_dlq.arn
    maxReceiveCount     = var.comments_collect_queue_max_receive_count
  })
}
```

- [ ] **Step 4: Verify**
```bash
cd $WT/infra && terraform fmt && terraform validate
```
Expected: `Success! The configuration is valid.` (run `terraform init` first if needed).

- [ ] **Step 5: Commit**
```bash
cd $WT && git add infra/sqs.tf infra/locals.tf infra/variables.tf
git commit -m "feat(infra): add comments-collect queue + dlq"
```

## Task 15: Worker Lambda + event-source mapping + IAM + SSM key

**Files:** `infra/lambda.tf` (or the file where the `label_enrichment`/`vendor_match` worker lambdas live), plus SSM param resource.

- [ ] **Step 1: Add the SSM parameter** for the key (placeholder value; real key set out-of-band) — mirror how `GEMINI_API_KEY` SSM is declared, or add:
```hcl
resource "aws_ssm_parameter" "youtube_api_key" {
  name  = "/${local.name_prefix}/youtube-api-key"
  type  = "SecureString"
  value = "REPLACE_ME"   # set the real key via console/CLI; ignored on drift below
  lifecycle { ignore_changes = [value] }
}
```

- [ ] **Step 2: Add the worker Lambda** mirroring the `vendor_match` worker function block (handler module `collector.comments_collect_handler.lambda_handler`, same runtime/layer/role pattern). Env vars must include:
```hcl
      AURORA_CLUSTER_ARN          = <same as other workers>
      AURORA_SECRET_ARN           = <same as other workers>
      AURORA_DATABASE             = <same as other workers>
      COMMENT_PLATFORMS_ENABLED   = "youtube"
      YOUTUBE_API_KEY_SSM_PARAMETER = aws_ssm_parameter.youtube_api_key.name
      LOG_LEVEL                   = var.log_level
```

- [ ] **Step 3: Add the event-source mapping** from `aws_sqs_queue.comments_collect.arn` to the new function (mirror the vendor_match ESM resource).

- [ ] **Step 4: IAM** — grant the worker role: `sqs:ReceiveMessage/DeleteMessage/GetQueueAttributes` on the comments_collect queue, `rds-data:*` + `secretsmanager:GetSecretValue` (Aurora) as other workers have, `ssm:GetParameter` on the youtube key param, and CloudWatch Logs write. Mirror the vendor_match worker policy statements.

- [ ] **Step 5: Producer grant + env** — the **curation** Lambda and the **vendor_match** worker both call the dispatcher, so both need:
  - IAM `sqs:SendMessage` on `aws_sqs_queue.comments_collect.arn`.
  - Env var `COMMENT_COLLECT_QUEUE_URL = aws_sqs_queue.comments_collect.url`.
  Add these to both functions' role policies and `environment` blocks (mirror how `VENDOR_MATCH_QUEUE_URL` is wired to the curation Lambda).

- [ ] **Step 6: Verify**
```bash
cd $WT/infra && terraform fmt && terraform validate
```
Expected: valid.

- [ ] **Step 7: Commit**
```bash
cd $WT && git add infra/
git commit -m "feat(infra): add comments-collect worker lambda + wiring"
```

## Task 16: API Gateway route

**Files:** Create `infra/curation_routes_comments.tf`

- [ ] **Step 1: Add the route** (mirror `infra/curation_routes_tags.tf`):
```hcl
# ── curation Lambda track-comments route ───────────────────────────
# Append-only: reuses the curation Lambda integration + JWT authorizer.

locals {
  curation_comments_routes = [
    "GET /tracks/{track_id}/comments",
  ]
}

resource "aws_apigatewayv2_route" "curation_comments" {
  for_each = toset(local.curation_comments_routes)

  api_id    = aws_apigatewayv2_api.collector.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.curation.id}"

  authorization_type = "CUSTOM"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}
```

- [ ] **Step 2: Verify**
```bash
cd $WT/infra && terraform fmt && terraform validate
```
Expected: valid.

- [ ] **Step 3: Commit**
```bash
cd $WT && git add infra/curation_routes_comments.tf
git commit -m "feat(infra): register GET /tracks/{track_id}/comments route"
```

---

# Phase G — Frontend

## Task 17: Types, query key, and data hook

**Files:**
- Modify: `frontend/src/features/playlists/lib/playlistTypes.ts`
- Modify: `frontend/src/features/playlists/lib/queryKeys.ts`
- Regenerate: `frontend/src/api/schema.d.ts`
- Create: `frontend/src/features/playlists/hooks/useTrackComments.ts`
- Test: `frontend/src/features/playlists/hooks/useTrackComments.test.tsx`

- [ ] **Step 1: Regenerate the API schema types** (CI diff-checks this against `openapi.yaml`):
```bash
cd $WT/frontend && pnpm run api:types
git diff --stat src/api/schema.d.ts
```
Expected: schema.d.ts updates with the new path.

- [ ] **Step 2: Add types** to `frontend/src/features/playlists/lib/playlistTypes.ts` (append near the other response interfaces):
```ts
export interface TrackComment {
  author_name: string;
  author_avatar_url: string | null;
  text: string;
  like_count: number;
  published_at: string | null;
}

export type TrackCommentsStatus =
  | 'pending'
  | 'collected'
  | 'empty'
  | 'disabled'
  | 'failed';

export interface TrackCommentsResponse {
  status: TrackCommentsStatus;
  comment_count: number;
  video_url: string | null;
  comments: TrackComment[];
}
```

- [ ] **Step 3: Add the query key** to `frontend/src/features/playlists/lib/queryKeys.ts`:
```ts
export const trackCommentsKey = (trackId: string, limit: number) =>
  ['tracks', 'comments', trackId, limit] as const;
```

- [ ] **Step 4: Write the failing hook test**

Create `frontend/src/features/playlists/hooks/useTrackComments.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { useTrackComments } from './useTrackComments';
import * as client from '../../../api/client';
import type { TrackCommentsResponse } from '../lib/playlistTypes';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const RESP: TrackCommentsResponse = {
  status: 'collected',
  comment_count: 1,
  video_url: 'https://youtube.com/watch?v=v',
  comments: [
    { author_name: 'A', author_avatar_url: null, text: 'hi', like_count: 2, published_at: null },
  ],
};

describe('useTrackComments', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches comments for a track', async () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue(RESP);
    const { result } = renderHook(() => useTrackComments('t1', 5), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.comments[0].author_name).toBe('A');
    expect(spy).toHaveBeenCalledWith('/tracks/t1/comments?platform=youtube&limit=5');
  });

  it('is disabled without a track id', () => {
    const spy = vi.spyOn(client, 'api').mockResolvedValue(RESP);
    renderHook(() => useTrackComments(undefined, 5), { wrapper });
    expect(spy).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd $WT/frontend && pnpm test useTrackComments -- --run`
Expected: FAIL (module `./useTrackComments` not found).

- [ ] **Step 6: Implement the hook**

Create `frontend/src/features/playlists/hooks/useTrackComments.ts`:
```ts
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import { api } from '../../../api/client';
import type { TrackCommentsResponse } from '../lib/playlistTypes';
import { trackCommentsKey } from '../lib/queryKeys';

export function useTrackComments(
  trackId: string | undefined,
  limit = 5,
): UseQueryResult<TrackCommentsResponse> {
  return useQuery({
    queryKey: trackCommentsKey(trackId ?? '', limit),
    queryFn: () =>
      api<TrackCommentsResponse>(
        `/tracks/${trackId}/comments?platform=youtube&limit=${limit}`,
      ),
    enabled: !!trackId,
  });
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd $WT/frontend && pnpm test useTrackComments -- --run`
Expected: PASS (2 tests).

- [ ] **Step 8: Commit**

```bash
cd $WT && git add frontend/src/features/playlists/lib/playlistTypes.ts frontend/src/features/playlists/lib/queryKeys.ts frontend/src/api/schema.d.ts frontend/src/features/playlists/hooks/useTrackComments.ts frontend/src/features/playlists/hooks/useTrackComments.test.tsx
git commit -m "feat(frontend): add useTrackComments hook + types"
```

---

## Task 18: `CommentsPanel` component + i18n

**Files:**
- Create: `frontend/src/features/playlists/components/CommentsPanel.tsx`
- Modify: `frontend/src/i18n/en.json`
- Test: `frontend/src/features/playlists/components/CommentsPanel.test.tsx`

- [ ] **Step 1: Add i18n keys** — in `frontend/src/i18n/en.json`, add a top-level `"comments"` object (sibling of `"playlists"`):
```json
  "comments": {
    "title": "Comments",
    "pending": "Collecting comments…",
    "empty": "No comments yet",
    "watch_on_youtube": "Watch on YouTube ({{count}})"
  },
```

- [ ] **Step 2: Write the failing component test**

Create `frontend/src/features/playlists/components/CommentsPanel.test.tsx`:
```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MantineProvider } from '@mantine/core';
import { CommentsPanel } from './CommentsPanel';
import * as hook from '../hooks/useTrackComments';
import type { TrackCommentsResponse } from '../lib/playlistTypes';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

function renderPanel() {
  return render(
    <MantineProvider>
      <CommentsPanel trackId="t1" />
    </MantineProvider>,
  );
}

function mockHook(data: Partial<TrackCommentsResponse> | undefined, opts: Partial<{ isLoading: boolean }> = {}) {
  vi.spyOn(hook, 'useTrackComments').mockReturnValue({
    data: data as TrackCommentsResponse | undefined,
    isLoading: opts.isLoading ?? false,
  } as ReturnType<typeof hook.useTrackComments>);
}

describe('CommentsPanel', () => {
  it('renders up to 5 collected comments', () => {
    mockHook({
      status: 'collected',
      comment_count: 2,
      video_url: 'https://youtube.com/watch?v=v',
      comments: [
        { author_name: 'Alice', author_avatar_url: null, text: 'hello', like_count: 3, published_at: null },
        { author_name: 'Bob', author_avatar_url: null, text: 'world', like_count: 0, published_at: null },
      ],
    });
    renderPanel();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.getByText('hello')).toBeInTheDocument();
  });

  it('shows pending state', () => {
    mockHook({ status: 'pending', comment_count: 0, video_url: null, comments: [] });
    renderPanel();
    expect(screen.getByText('comments.pending')).toBeInTheDocument();
  });

  it('shows empty state for empty/disabled', () => {
    mockHook({ status: 'empty', comment_count: 0, video_url: null, comments: [] });
    renderPanel();
    expect(screen.getByText('comments.empty')).toBeInTheDocument();
  });

  it('renders nothing on failed', () => {
    mockHook({ status: 'failed', comment_count: 0, video_url: null, comments: [] });
    const { container } = renderPanel();
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `cd $WT/frontend && pnpm test CommentsPanel -- --run`
Expected: FAIL (module `./CommentsPanel` not found).

- [ ] **Step 3: Implement the component**

Create `frontend/src/features/playlists/components/CommentsPanel.tsx`:
```tsx
import { Anchor, Avatar, Group, Stack, Text } from '@mantine/core';
import { useTranslation } from 'react-i18next';
import { useTrackComments } from '../hooks/useTrackComments';

interface Props {
  trackId: string;
}

const MAX_SHOWN = 5;

export function CommentsPanel({ trackId }: Props) {
  const { t } = useTranslation();
  const { data, isLoading } = useTrackComments(trackId, MAX_SHOWN);

  if (isLoading || data?.status === 'pending') {
    return (
      <Stack gap={4}>
        <Text fw={500} size="sm">{t('comments.title')}</Text>
        <Text size="sm" c="dimmed">{t('comments.pending')}</Text>
      </Stack>
    );
  }

  // failed → render nothing (no error noise in the panel)
  if (!data || data.status === 'failed') return null;

  if (data.status === 'empty' || data.status === 'disabled' || data.comments.length === 0) {
    return (
      <Stack gap={4}>
        <Text fw={500} size="sm">{t('comments.title')}</Text>
        <Text size="sm" c="dimmed">{t('comments.empty')}</Text>
      </Stack>
    );
  }

  return (
    <Stack gap="xs">
      <Text fw={500} size="sm">{t('comments.title')}</Text>
      {data.comments.slice(0, MAX_SHOWN).map((c, i) => (
        <Group key={i} gap="xs" align="flex-start" wrap="nowrap">
          <Avatar src={c.author_avatar_url ?? undefined} size="sm" radius="xl" />
          <Stack gap={0} style={{ minWidth: 0 }}>
            <Group gap={6} wrap="nowrap">
              <Text size="xs" fw={600} truncate>{c.author_name}</Text>
              {c.like_count > 0 ? (
                <Text size="xs" c="dimmed">♥ {c.like_count}</Text>
              ) : null}
            </Group>
            <Text size="sm" style={{ wordBreak: 'break-word' }}>{c.text}</Text>
          </Stack>
        </Group>
      ))}
      {data.video_url ? (
        <Anchor href={data.video_url} target="_blank" rel="noopener noreferrer" size="xs">
          {t('comments.watch_on_youtube', { count: data.comment_count })}
        </Anchor>
      ) : null}
    </Stack>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT/frontend && pnpm test CommentsPanel -- --run`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
cd $WT && git add frontend/src/features/playlists/components/CommentsPanel.tsx frontend/src/features/playlists/components/CommentsPanel.test.tsx frontend/src/i18n/en.json
git commit -m "feat(frontend): add CommentsPanel component + i18n"
```

---

## Task 19: Render `CommentsPanel` in the player panel

**Files:**
- Modify: `frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx`

- [ ] **Step 1: Add the import** at the top of `PlaylistPlayerPanel.tsx` (with the other component imports):
```tsx
import { CommentsPanel } from './CommentsPanel';
```

- [ ] **Step 2: Render it after `<ArtistsPanel>`** — change the block at lines 232-237:
```tsx
      <LabelTile
        labelId={effectiveRich?.label?.id ?? null}
        labelName={effectiveRich?.label?.name ?? null}
      />
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
```
to:
```tsx
      <LabelTile
        labelId={effectiveRich?.label?.id ?? null}
        labelName={effectiveRich?.label?.name ?? null}
      />
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
      <CommentsPanel trackId={current.id} />
```

- [ ] **Step 3: Verify the frontend builds and types pass**

```bash
cd $WT/frontend && pnpm typecheck && pnpm lint && pnpm test -- --run
```
Expected: all green (typecheck + eslint + vitest). (Per project gotcha, run all three — vitest alone misses tsc/eslint, and deploy's vite build runs tsc.)

- [ ] **Step 4: Commit**

```bash
cd $WT && git add frontend/src/features/playlists/components/PlaylistPlayerPanel.tsx
git commit -m "feat(frontend): show comments under artists in player panel"
```

---

# Phase H — Full verification

## Task 20: Whole-suite green + manual browser check

- [ ] **Step 1: Backend suite**
```bash
cd $WT && /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q
```
Expected: all pass.

- [ ] **Step 2: Frontend gates**
```bash
cd $WT/frontend && pnpm typecheck && pnpm lint && pnpm test -- --run
```
Expected: all pass.

- [ ] **Step 3: OpenAPI/schema drift check** (frontend CI diff-checks `schema.d.ts` against generated `openapi.yaml`)
```bash
cd $WT
PYTHONPATH=src /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/python scripts/generate_openapi.py
cd frontend && pnpm run api:types
cd $WT && git status --porcelain docs/api/openapi.yaml frontend/src/api/schema.d.ts
```
Expected: no uncommitted changes (already committed); if any appear, commit them.

- [ ] **Step 4: Browser smoke (visual gate)** — per project gotcha #11, verify the comments section visually:
```bash
cd $WT/frontend && pnpm test:browser
```
If no browser test exists for this panel, manually run the SPA against a deployed/staging API, open a playlist, select a track with a matched YouTube video, and confirm comments render under the artists block with the "Watch on YouTube" link. Do not claim the UI works on jsdom-only evidence.

- [ ] **Step 5: Finish the branch** — use the `superpowers:finishing-a-development-branch` skill to decide merge/PR. PR title + body via `caveman:caveman-commit`.

---

## Notes / decisions baked in

- Comments are public per-track data; the read route does **not** scope-check by user (consistent with comment data being non-sensitive and the same video shared across users).
- The worker catches all errors and marks `failed` rather than re-raising — by design we spend **one** request per video and never auto-retry, to conserve quota.
- `COMMENT_PLATFORMS_ENABLED` defaults to `youtube`; future platforms (TikTok, SoundCloud) add one `_BUILDERS` entry + one provider class implementing `CommentProvider`, with no change to storage, dispatch, worker, or read API.
- The real `YOUTUBE_API_KEY` is provisioned out-of-band into the SSM SecureString param (Task 15); Terraform ignores its value on drift.
```

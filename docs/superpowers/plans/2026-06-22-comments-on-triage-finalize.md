# Comments on Triage Finalize Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move YouTube-comment collection so it is triggered at triage finalization (for tracks promoted into categories) with the comment worker resolving the video itself from track metadata, remove the vendor-match auto-trigger, and show the existing `CommentsPanel` in the category player.

**Architecture:** Finalize already fans out per-block work through the async `auto_enrich_dispatch` worker. We add a third dispatch there that enumerates the block's promoted tracks and enqueues a comment-collection job per track **without a seed video id**. The comment worker, when given no seed, resolves the primary video via the provider's existing YT-Music metadata search (`resolve_alternate_videos`) and then collects. Comment dispatch is removed from the vendor-match worker; manual match-accept keeps seeding a specific video id.

**Tech Stack:** Python 3.12 Lambdas (Aurora via RDS Data API), pytest; React 19 + Mantine 9 + Vitest; Terraform.

---

## Conventions for every task

- **This is a git worktree.** The Python venv lives at the MAIN repo root and `pytest` is NOT on `PATH`. Run tests with the absolute binary path, from the worktree directory (the current working directory):

  `PYTEST = /Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest`

  Example: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comment_dispatch.py -q`

- Frontend commands run from `frontend/` with `pnpm` (deps already installed in this worktree; if a fresh checkout, run `pnpm install` first).
- Commit messages are Conventional Commits (a PreToolUse hook enforces the subject and strips any AI-attribution trailer). No `Co-Authored-By`.
- Tests use `monkeypatch` and small hand-written fakes — follow the existing patterns shown in each task.

## Deviations from the spec (intentional simplifications)

- **No new `"no_video"` status.** When the worker resolves no video (no metadata, or search returns nothing) it stores the existing status `"disabled"` — the function's existing "no commentable video reached" terminal status. This avoids touching the OpenAPI enum, `frontend/src/api/schema.d.ts`, `playlistTypes.ts`, and `CommentsPanel.tsx`. YAGNI.
- **No IAM change.** `infra/iam.tf` already grants `sqs:SendMessage` on `aws_sqs_queue.comments_collect.arn` to the collector role (verified). Only the Lambda env var is added.

## File overview

| File | Change |
|---|---|
| `src/collector/comments/messages.py` | `video_id` gets a default `""` (optional) |
| `src/collector/comments/dispatch.py` | drop the `if not video_id: return` guard |
| `src/collector/comments/repository.py` | `start_collection` idempotency for empty seed; new `promoted_track_ids_for_block` |
| `src/collector/comments_collect_handler.py` | `_resolve_and_collect` resolves primary by metadata when no seed |
| `src/collector/comments/auto_dispatch.py` | NEW — `try_dispatch_comments_for_triage_block` |
| `src/collector/auto_enrich_dispatch_handler.py` | call the new dispatch |
| `src/collector/vendor_match_handler.py` | remove `_maybe_dispatch_comments` + import + call sites |
| `tests/unit/test_comment_message.py` | cover optional `video_id` |
| `tests/unit/test_comment_dispatch.py` | rewrite the empty-video test |
| `tests/unit/test_comments_repository.py` | idempotency + `promoted_track_ids_for_block` |
| `tests/unit/test_comments_collect_handler.py` | no-seed resolution tests |
| `tests/unit/test_comments_auto_dispatch.py` | NEW |
| `tests/unit/test_auto_enrich_dispatch_handler.py` | assert comments dispatch is called |
| `tests/unit/test_vendor_match_comment_dispatch.py` | DELETE (behavior removed) |
| `infra/lambda.tf` | add `COMMENT_COLLECT_QUEUE_URL` to `auto_enrich_dispatch_worker` |
| `frontend/.../CategoryPlayerPanel.tsx` | render `<CommentsPanel>` |
| `frontend/.../__tests__/CategoryPlayerPanel.test.tsx` | mock + assert `CommentsPanel` |

---

### Task 1: Make `CommentCollectMessage.video_id` optional

**Files:**
- Modify: `src/collector/comments/messages.py`
- Test: `tests/unit/test_comment_message.py`

- [ ] **Step 1: Add a failing test for the default**

Append to `tests/unit/test_comment_message.py`:

```python
def test_video_id_defaults_to_empty_when_omitted():
    from collector.comments.messages import CommentCollectMessage

    msg = CommentCollectMessage.model_validate_json(
        '{"track_id": "t1", "platform": "youtube", "collection_id": "col1"}'
    )
    assert msg.video_id == ""


def test_video_id_still_parses_when_present():
    from collector.comments.messages import CommentCollectMessage

    msg = CommentCollectMessage.model_validate_json(
        '{"track_id": "t1", "platform": "youtube", "video_id": "vidA", "collection_id": "col1"}'
    )
    assert msg.video_id == "vidA"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comment_message.py -q`
Expected: FAIL — `test_video_id_defaults_to_empty_when_omitted` raises a pydantic `ValidationError` (field required).

- [ ] **Step 3: Make `video_id` optional**

In `src/collector/comments/messages.py`, change the field:

```python
class CommentCollectMessage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    track_id: str
    platform: str
    video_id: str = ""
    collection_id: str
```

- [ ] **Step 4: Run it to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comment_message.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments/messages.py tests/unit/test_comment_message.py
git commit -m "feat(comments): make CommentCollectMessage.video_id optional"
```

---

### Task 2: Dispatch allows an empty seed video

**Files:**
- Modify: `src/collector/comments/dispatch.py:48-75`
- Test: `tests/unit/test_comment_dispatch.py`

- [ ] **Step 1: Rewrite the empty-video test to the new behavior**

In `tests/unit/test_comment_dispatch.py`, REPLACE the existing `test_dispatch_noop_on_empty_video` with:

```python
def test_dispatch_sends_for_empty_video(monkeypatch):
    repo, sqs = FakeRepo("col1"), FakeSqs()
    _patch(monkeypatch, repo, sqs)
    dispatch.try_dispatch_comment_collection(track_id="t1", video_id="", platform="youtube")
    assert len(sqs.sent) == 1
    assert repo.start_calls == [("t1", "youtube", "")]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comment_dispatch.py::test_dispatch_sends_for_empty_video -q`
Expected: FAIL — nothing is sent (current code returns early on empty `video_id`); `assert len(sqs.sent) == 1` fails.

- [ ] **Step 3: Remove the early-return guard**

In `src/collector/comments/dispatch.py`, inside `try_dispatch_comment_collection._run`, delete these two lines (currently the first statement of `_run`):

```python
        if not video_id:
            return
```

The function body becomes:

```python
def try_dispatch_comment_collection(
    *, track_id: str, video_id: str = "", platform: str = "youtube", user_id: str | None = None
) -> None:
    def _run() -> None:
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

(Note the signature default `video_id: str = ""` so callers may omit it.)

- [ ] **Step 4: Run the whole dispatch test file**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comment_dispatch.py -q`
Expected: PASS (all tests, including the rewritten one).

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments/dispatch.py tests/unit/test_comment_dispatch.py
git commit -m "feat(comments): dispatch comment collection without a seed video"
```

---

### Task 3: `start_collection` idempotency for an empty seed

When dispatched with no seed, re-finalizing a block must NOT re-collect a track that was already collected (any video).

**Files:**
- Modify: `src/collector/comments/repository.py:48-66`
- Test: `tests/unit/test_comments_repository.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/unit/test_comments_repository.py`:

```python
def test_start_collection_empty_seed_skips_when_already_collected():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections",
         [{"id": "colOLD", "external_video_id": "vidOLD", "status": "collected"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="", now=NOW)
    assert result is None


def test_start_collection_empty_seed_inserts_when_not_collected():
    api = FakeDataAPI([
        ("SELECT id, external_video_id, status FROM comment_collections", []),
        ("INSERT INTO comment_collections", [{"id": "colNEW"}]),
    ])
    repo = CommentsRepository(api)
    result = repo.start_collection(track_id="t1", platform="youtube", video_id="", now=NOW)
    assert result == "colNEW"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_repository.py -q -k start_collection_empty_seed`
Expected: FAIL — `test_start_collection_empty_seed_skips_when_already_collected` returns `"colNEW"` instead of `None` (current guard compares `external_video_id == video_id`, i.e. `"vidOLD" == ""`, which is False so it does not skip).

- [ ] **Step 3: Update the idempotency guard**

In `src/collector/comments/repository.py`, in `start_collection`, change the skip condition:

```python
        if existing:
            row = existing[0]
            if row["status"] == "collected" and (
                not video_id or row["external_video_id"] == video_id
            ):
                return None
```

(When `video_id` is empty, skip if a collected row exists for any video; otherwise keep the per-video behavior.)

- [ ] **Step 4: Run the repository tests**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_repository.py -q`
Expected: PASS (new tests plus the existing ones).

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments/repository.py tests/unit/test_comments_repository.py
git commit -m "fix(comments): idempotent start_collection for empty seed"
```

---

### Task 4: Worker resolves the primary video from metadata when no seed

**Files:**
- Modify: `src/collector/comments_collect_handler.py:35-72`
- Test: `tests/unit/test_comments_collect_handler.py`

- [ ] **Step 1: Add failing tests for the no-seed path**

Append to `tests/unit/test_comments_collect_handler.py`:

```python
class _MetaRepo(FakeRepo):
    def __init__(self, meta):
        super().__init__()
        self._meta = meta

    def fetch_track_meta(self, track_ids):
        return {"t1": self._meta} if self._meta is not None else {}


class _ResolverProvider:
    """No-seed provider: resolve_alternate_videos returns ids; collect scripted by id."""
    def __init__(self, *, alts, collect_by_id):
        self._alts = alts
        self._collect_by_id = collect_by_id
        self.resolve_calls = []

    def resolve_alternate_videos(self, *, artist, title, duration_ms, exclude_video_id):
        self.resolve_calls.append(exclude_video_id)
        return self._alts

    def collect(self, video_ref, *, limit=100):
        beh = self._collect_by_id[video_ref]
        if isinstance(beh, Exception):
            raise beh
        return beh


def test_no_seed_resolves_primary_via_search(monkeypatch):
    repo = _MetaRepo(TrackMeta("t1", "Artist", "Title", 1000))
    provider = _ResolverProvider(
        alts=["vidX"],
        collect_by_id={"vidX": [CollectedComment("c1", "A", None, "hi", 1, None, 0)]},
    )
    _patch(monkeypatch, repo, provider)
    worker.lambda_handler(_event(_msg(video_id="")), None)
    assert repo.stored[0]["status"] == "collected"
    assert repo.stored[0]["external_video_id"] == "vidX"
    assert provider.resolve_calls[0] == ""  # primary resolution excludes nothing


def test_no_seed_no_search_result_marks_disabled(monkeypatch):
    repo = _MetaRepo(TrackMeta("t1", "A", "T", None))
    provider = _ResolverProvider(alts=[], collect_by_id={})
    _patch(monkeypatch, repo, provider)
    worker.lambda_handler(_event(_msg(video_id="")), None)
    assert repo.stored[0]["status"] == "disabled"


def test_no_seed_no_meta_marks_disabled(monkeypatch):
    repo = _MetaRepo(None)  # fetch_track_meta -> {}
    provider = _ResolverProvider(alts=["vidX"], collect_by_id={})
    _patch(monkeypatch, repo, provider)
    worker.lambda_handler(_event(_msg(video_id="")), None)
    assert repo.stored[0]["status"] == "disabled"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_collect_handler.py -q -k no_seed`
Expected: FAIL — with no seed, current code calls `provider.collect("")` first. For `test_no_seed_resolves_primary_via_search` that raises `KeyError("")` → handler stores `"failed"`, not `"collected"`.

- [ ] **Step 3: Add the no-seed resolution to `_resolve_and_collect`**

In `src/collector/comments_collect_handler.py`, replace the whole `_resolve_and_collect` function with:

```python
def _resolve_and_collect(
    provider: CommentProvider, *, primary_video_id: str, meta: TrackMeta | None
) -> tuple[str, list[CollectedComment], str]:
    """Collect from the primary video; on CommentsDisabledError, fall back to up to
    3 resolver-provided regular videos. Returns (status, comments, video_id), where
    video_id is the video actually reached (the collected-from one, or the first
    real alternate even when it had no comments).

    When primary_video_id is empty (decoupled dispatch from triage finalize), the
    primary is resolved first from track metadata via the same YT-Music search used
    for the disabled-comments fallback. If nothing is resolvable, status is
    "disabled" (no commentable video reached).

    Raises are left to the caller (generic/platform errors -> 'failed')."""
    if not primary_video_id:
        if meta is None:
            return ("disabled", [], "")
        resolved = provider.resolve_alternate_videos(
            artist=meta.artist, title=meta.title,
            duration_ms=meta.duration_ms, exclude_video_id="",
        )
        if not resolved:
            return ("disabled", [], "")
        primary_video_id = resolved[0]

    try:
        comments = provider.collect(primary_video_id, limit=100)
        return ("collected" if comments else "empty", comments, primary_video_id)
    except CommentsDisabledError:
        pass

    # Need track metadata to build the fallback search query.
    if meta is None:
        return ("disabled", [], primary_video_id)

    alts = provider.resolve_alternate_videos(
        artist=meta.artist, title=meta.title,
        duration_ms=meta.duration_ms, exclude_video_id=primary_video_id,
    )
    first_empty_alt: str | None = None
    # belt-and-suspenders: the resolver already caps at 3 best-scored ids.
    for alt in (alts or [])[:3]:
        try:
            comments = provider.collect(alt, limit=100)
        except CommentsDisabledError:
            continue
        if comments:
            return ("collected", comments, alt)
        if first_empty_alt is None:
            first_empty_alt = alt
    # A real video was reached but had no comments -> point at it; else disabled.
    if first_empty_alt is not None:
        return ("empty", [], first_empty_alt)
    return ("disabled", [], primary_video_id)
```

- [ ] **Step 4: Run the worker tests**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_collect_handler.py -q`
Expected: PASS (new no-seed tests plus all existing seeded tests).

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments_collect_handler.py tests/unit/test_comments_collect_handler.py
git commit -m "feat(comments): resolve video from metadata when no seed given"
```

---

### Task 5: `promoted_track_ids_for_block` repository method

**Files:**
- Modify: `src/collector/comments/repository.py`
- Test: `tests/unit/test_comments_repository.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/unit/test_comments_repository.py`:

```python
def test_promoted_track_ids_for_block():
    api = FakeDataAPI([
        ("FROM category_tracks ct", [{"track_id": "t1"}, {"track_id": "t2"}]),
    ])
    repo = CommentsRepository(api)
    out = repo.promoted_track_ids_for_block(block_id="blk-1", user_id="u1")
    assert out == ["t1", "t2"]
    sql, params, _ = api.calls[0]
    assert "source_triage_block_id = :block_id" in sql
    assert params == {"block_id": "blk-1", "user_id": "u1"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_repository.py::test_promoted_track_ids_for_block -q`
Expected: FAIL — `AttributeError: 'CommentsRepository' object has no attribute 'promoted_track_ids_for_block'`.

- [ ] **Step 3: Add the method**

In `src/collector/comments/repository.py`, add this method to `CommentsRepository` (place it after `fetch_track_meta`):

```python
    def promoted_track_ids_for_block(self, *, block_id: str, user_id: str) -> list[str]:
        """Track ids promoted into the user's categories by finalizing this block."""
        rows = self._data_api.execute(
            """
            SELECT ct.track_id
            FROM category_tracks ct
            JOIN categories c ON c.id = ct.category_id
            WHERE ct.source_triage_block_id = :block_id AND c.user_id = :user_id
            ORDER BY ct.track_id
            """,
            {"block_id": block_id, "user_id": user_id},
        )
        return [r["track_id"] for r in rows]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_repository.py::test_promoted_track_ids_for_block -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments/repository.py tests/unit/test_comments_repository.py
git commit -m "feat(comments): enumerate promoted tracks for a finalized block"
```

---

### Task 6: New `comments/auto_dispatch.py` — per-block fan-out

**Files:**
- Create: `src/collector/comments/auto_dispatch.py`
- Test: `tests/unit/test_comments_auto_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_comments_auto_dispatch.py`:

```python
from __future__ import annotations

import pytest

import collector.comments.auto_dispatch as ad


class FakeRepo:
    def __init__(self, ids):
        self._ids = ids
        self.seen = None

    def promoted_track_ids_for_block(self, *, block_id, user_id):
        self.seen = (block_id, user_id)
        return self._ids


def test_dispatches_for_each_promoted_track(monkeypatch):
    repo = FakeRepo(["t1", "t2"])
    dispatched = []
    monkeypatch.setattr(ad, "_build_repository", lambda: repo)
    monkeypatch.setattr(
        ad, "try_dispatch_comment_collection", lambda **kw: dispatched.append(kw)
    )
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")
    assert repo.seen == ("blk-1", "u1")
    assert dispatched == [
        {"track_id": "t1", "platform": "youtube"},
        {"track_id": "t2", "platform": "youtube"},
    ]


def test_no_user_id_is_noop(monkeypatch):
    called = []
    monkeypatch.setattr(
        ad, "_build_repository",
        lambda: pytest.fail("should not build repository without user_id"),
    )
    monkeypatch.setattr(
        ad, "try_dispatch_comment_collection", lambda **kw: called.append(kw)
    )
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id=None)
    assert called == []


def test_never_raises(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(ad, "_build_repository", boom)
    # must not raise
    ad.try_dispatch_comments_for_triage_block(block_id="blk-1", user_id="u1")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_auto_dispatch.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'collector.comments.auto_dispatch'`.

- [ ] **Step 3: Create the module**

Create `src/collector/comments/auto_dispatch.py`:

```python
"""Best-effort fan-out of comment-collection jobs for a finalized triage block.

Runs in the auto-enrich-dispatch worker (off the finalize request path), mirroring
label_enrichment.auto_dispatch.try_dispatch_for_triage_block. For each track the
block promoted into the user's categories, enqueue a comment-collection job with no
seed video — the comment worker resolves the video from track metadata. Best-effort:
never breaks the worker.
"""

from __future__ import annotations

from ..logging_utils import log_event
from .dispatch import try_dispatch_comment_collection
from .repository import CommentsRepository, create_default_comments_repository


def _build_repository() -> CommentsRepository:
    repo = create_default_comments_repository()
    if repo is None:
        raise RuntimeError("Aurora Data API not configured")
    return repo


def _safe(fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 — best-effort, never break the worker
        log_event(
            "ERROR", "comments_auto_dispatch_error", error_message=str(exc)[:500]
        )


def try_dispatch_comments_for_triage_block(
    *, block_id: str, user_id: str | None
) -> None:
    def _run() -> None:
        if not user_id:
            return
        repo = _build_repository()
        track_ids = repo.promoted_track_ids_for_block(
            block_id=block_id, user_id=user_id
        )
        for track_id in track_ids:
            try_dispatch_comment_collection(track_id=track_id, platform="youtube")

    _safe(_run)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_comments_auto_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/comments/auto_dispatch.py tests/unit/test_comments_auto_dispatch.py
git commit -m "feat(comments): per-block comment dispatch for finalized triage"
```

---

### Task 7: Wire the comment dispatch into the auto-enrich worker

**Files:**
- Modify: `src/collector/auto_enrich_dispatch_handler.py`
- Test: `tests/unit/test_auto_enrich_dispatch_handler.py`

- [ ] **Step 1: Replace the test file to also assert the comments dispatch**

Replace the entire contents of `tests/unit/test_auto_enrich_dispatch_handler.py` with:

```python
import json
import collector.auto_enrich_dispatch_handler as h


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(b)} for b in bodies]}


def _patch_all(monkeypatch, calls):
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: calls.append(("labels", kw)))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block",
                        lambda **kw: calls.append(("artists", kw)))
    monkeypatch.setattr(h, "try_dispatch_comments_for_triage_block",
                        lambda **kw: calls.append(("comments", kw)))


def test_worker_runs_all_three_dispatches_per_block(monkeypatch):
    calls = []
    _patch_all(monkeypatch, calls)
    h.lambda_handler(_sqs_event({"block_id": "blk-1", "user_id": "u1"}), None)
    assert ("labels", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("artists", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("comments", {"block_id": "blk-1", "user_id": "u1"}) in calls


def test_worker_processes_each_record(monkeypatch):
    calls = []
    _patch_all(monkeypatch, calls)
    h.lambda_handler(
        _sqs_event({"block_id": "b1", "user_id": "u"}, {"block_id": "b2", "user_id": "u"}),
        None,
    )
    comment_blocks = [kw["block_id"] for tag, kw in calls if tag == "comments"]
    assert comment_blocks == ["b1", "b2"]


def test_worker_raises_on_unparseable_record(monkeypatch):
    _patch_all(monkeypatch, [])
    import pytest
    with pytest.raises(Exception):
        h.lambda_handler({"Records": [{"body": "not json"}]}, None)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_dispatch_handler.py -q`
Expected: FAIL — `AttributeError: <module 'collector.auto_enrich_dispatch_handler'> does not have the attribute 'try_dispatch_comments_for_triage_block'`.

- [ ] **Step 3: Add the import and the call**

In `src/collector/auto_enrich_dispatch_handler.py`:

Add the import (after the existing label import, line 15):

```python
from .comments.auto_dispatch import try_dispatch_comments_for_triage_block
```

Add the call in `lambda_handler`, after `try_dispatch_artists_for_triage_block(...)`:

```python
        try_dispatch_for_triage_block(block_id=block_id, user_id=user_id)
        try_dispatch_artists_for_triage_block(block_id=block_id, user_id=user_id)
        try_dispatch_comments_for_triage_block(block_id=block_id, user_id=user_id)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_auto_enrich_dispatch_handler.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/collector/auto_enrich_dispatch_handler.py tests/unit/test_auto_enrich_dispatch_handler.py
git commit -m "feat(comments): dispatch comments from auto-enrich worker"
```

---

### Task 8: Remove comment dispatch from the vendor-match worker

**Files:**
- Modify: `src/collector/vendor_match_handler.py` (remove import line 13, function lines 70-78, call sites lines 136 and 177)
- Delete: `tests/unit/test_vendor_match_comment_dispatch.py`

- [ ] **Step 1: Delete the obsolete test (its behavior is being removed)**

```bash
git rm tests/unit/test_vendor_match_comment_dispatch.py
```

- [ ] **Step 2: Remove the code**

In `src/collector/vendor_match_handler.py`:

1. Delete the import (line 13):

```python
from .comments.dispatch import try_dispatch_comment_collection
```

2. Delete the `_maybe_dispatch_comments` function (lines 70-78):

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

3. Delete the ISRC-match call site (currently line 136):

```python
            _maybe_dispatch_comments(message.vendor, message.clouder_track_id, ref.vendor_track_id)
```

4. Delete the fuzzy-match call site (currently line 177):

```python
        _maybe_dispatch_comments(message.vendor, message.clouder_track_id, best_cand.vendor_track_id)
```

- [ ] **Step 3: Verify no dangling references**

Run: `grep -rn "_maybe_dispatch_comments\|comments.dispatch" src/collector/vendor_match_handler.py`
Expected: no output (empty).

- [ ] **Step 4: Run the vendor-match suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest tests/unit/test_vendor_match_handler.py tests/unit/test_resolve_match_comment_dispatch.py -q`
Expected: PASS — `test_vendor_match_handler.py` still green (it never asserted comment dispatch), and `test_resolve_match_comment_dispatch.py` (manual accept path, unchanged) still green.

- [ ] **Step 5: Commit**

```bash
git add src/collector/vendor_match_handler.py tests/unit/test_vendor_match_comment_dispatch.py
git commit -m "refactor(comments): drop auto comment dispatch from vendor-match"
```

---

### Task 9: Infra — give the auto-enrich worker the comment queue URL

**Files:**
- Modify: `infra/lambda.tf:300-309`

(No IAM change: `infra/iam.tf` already grants `sqs:SendMessage` on `aws_sqs_queue.comments_collect.arn`.)

- [ ] **Step 1: Add the env var**

In `infra/lambda.tf`, in the `aws_lambda_function "auto_enrich_dispatch_worker"` resource, change the `environment.variables` block (the one with `LABEL_ENRICHMENT_QUEUE_URL`/`ARTIST_ENRICHMENT_QUEUE_URL` near line 300) to add `COMMENT_COLLECT_QUEUE_URL`:

```hcl
  environment {
    variables = {
      AURORA_CLUSTER_ARN          = aws_rds_cluster.aurora.arn
      AURORA_SECRET_ARN           = try(aws_rds_cluster.aurora.master_user_secret[0].secret_arn, "")
      AURORA_DATABASE             = var.aurora_database_name
      LABEL_ENRICHMENT_QUEUE_URL  = aws_sqs_queue.label_enrichment.url
      ARTIST_ENRICHMENT_QUEUE_URL = aws_sqs_queue.artist_enrichment.url
      COMMENT_COLLECT_QUEUE_URL   = aws_sqs_queue.comments_collect.url
      LOG_LEVEL                   = "INFO"
    }
  }
```

- [ ] **Step 2: Format and validate**

Run: `cd infra && terraform fmt && terraform validate`
Expected: `terraform fmt` reports the file (or nothing if already formatted); `terraform validate` prints `Success! The configuration is valid.` (If `validate` requires `terraform init`, run `terraform init -backend=false` first.)

- [ ] **Step 3: Commit**

```bash
git add infra/lambda.tf
git commit -m "chore(infra): pass comment queue url to auto-enrich worker"
```

---

### Task 10: Show `CommentsPanel` in the category player

**Files:**
- Modify: `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`
- Test: `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`

- [ ] **Step 1: Add a failing test (mock `CommentsPanel`, assert it renders)**

In `frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`, add this mock next to the existing `ArtistsPanel`/`LabelTile` mocks (the block around lines 95-100):

```tsx
vi.mock('../../../playlists/components/CommentsPanel', () => ({
  CommentsPanel: ({ trackId }: { trackId: string }) => (
    <div data-testid="comments-panel">{trackId}</div>
  ),
}));
```

And add this test inside the `describe('CategoryPlayerPanel', ...)` block:

```tsx
  it('renders the comments panel for the current track', () => {
    render(ui());
    const panel = screen.getByTestId('comments-panel');
    expect(panel).toBeInTheDocument();
    expect(panel).toHaveTextContent('t1');
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run (from `frontend/`): `pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: FAIL — `Unable to find an element by: [data-testid="comments-panel"]` (the panel is not rendered yet).

- [ ] **Step 3: Render `CommentsPanel` in the panel**

In `frontend/src/features/categories/components/CategoryPlayerPanel.tsx`:

1. Add the import next to the other library imports (after the `ArtistsPanel` import, around line 20):

```tsx
import { CommentsPanel } from '../../playlists/components/CommentsPanel';
```

2. Render it right after `<ArtistsPanel .../>` (currently line 289), before the closing `</Stack>`:

```tsx
      <ArtistsPanel artists={effectiveRich?.artists ?? []} />
      <CommentsPanel trackId={current.id} />
    </Stack>
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`): `pnpm test src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/categories/components/CategoryPlayerPanel.tsx \
        frontend/src/features/categories/components/__tests__/CategoryPlayerPanel.test.tsx
git commit -m "feat(categories): show comments panel in the category player"
```

---

### Task 11: Full verification

- [ ] **Step 1: Run the whole backend suite**

Run: `/Users/roman/Projects/clouder-projects/clouder-core/.venv/bin/pytest -q`
Expected: PASS (no failures, no errors).

- [ ] **Step 2: Run the frontend gates**

Run (from `frontend/`): `pnpm typecheck && pnpm lint && pnpm test`
Expected: typecheck clean; lint 0 errors (pre-existing warnings in untouched files are acceptable); all vitest tests pass.

- [ ] **Step 3: Final sanity grep — vendor-match no longer references comments**

Run: `grep -rn "try_dispatch_comment_collection" src/collector`
Expected: references only in `comments/dispatch.py` (definition), `comments/auto_dispatch.py`, and `curation_handler.py` (manual accept). NOT in `vendor_match_handler.py`.

- [ ] **Step 4: No commit needed if everything is green** (all work already committed per task).

---

## Self-review checklist (completed by plan author)

- **Spec coverage:** trigger at finalize for promoted tracks (Tasks 5–7), decoupled video resolution (Tasks 1–4), remove vendor-match auto-trigger keep manual accept (Task 8), infra env (Task 9), category-player display (Task 10). All spec sections map to a task.
- **Placeholder scan:** every code/test step shows complete code and exact commands; no TBD/TODO.
- **Type/name consistency:** `try_dispatch_comments_for_triage_block(block_id, user_id)`, `promoted_track_ids_for_block(block_id=, user_id=)`, `_build_repository`, `try_dispatch_comment_collection(track_id=, platform=)`, status `"disabled"` for no-video, `CommentsPanel({ trackId })` — names match across tasks.
- **Deviation noted:** reuse status `"disabled"` instead of a new `"no_video"`; no IAM change (already present).

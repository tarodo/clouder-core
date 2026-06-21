from __future__ import annotations

import json

import collector.comments_collect_handler as worker
from collector.comments.registry import CommentPlatformDisabledError
from collector.comments.repository import TrackMeta
from collector.providers.base import CollectedComment
from collector.providers.youtube.comments import CommentsDisabledError


class FakeRepo:
    def __init__(self):
        self.stored = []

    def fetch_track_meta(self, track_ids):
        return {}

    def store_comments(self, *, collection_id, platform, comments, status, now,
                       error=None, external_video_id=None):
        self.stored.append({"collection_id": collection_id, "status": status,
                            "count": len(comments), "error": error,
                            "external_video_id": external_video_id})


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


# T1 — CommentPlatformDisabledError is stored as "failed", not silently dropped
def test_platform_disabled_marks_failed(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setattr(
        worker, "get_comment_provider",
        lambda *a, **k: (_ for _ in ()).throw(CommentPlatformDisabledError("youtube")),
    )
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")
    out = worker.lambda_handler(_event(_msg()), None)
    assert out["processed"] == 1
    assert repo.stored[0]["status"] == "failed"


# T2 — malformed / invalid SQS bodies are skipped; nothing is stored
def test_invalid_body_skipped(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")
    # not-JSON body
    event_not_json = {"Records": [{"body": "not json"}]}
    out = worker.lambda_handler(event_not_json, None)
    assert out == {"processed": 0}
    assert repo.stored == []

    # JSON but missing required fields
    event_missing_fields = {"Records": [{"body": json.dumps({"track_id": "t1"})}]}
    out2 = worker.lambda_handler(event_missing_fields, None)
    assert out2 == {"processed": 0}
    assert repo.stored == []


# T3 — two records; first raises generic Exception (→ "failed"), second succeeds (→ "collected")
def test_two_records_first_fails_second_succeeds(monkeypatch):
    repo = FakeRepo()
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")

    good_comment = CollectedComment("c1", "A", None, "hi", 1, None, 0)
    call_count = {"n": 0}

    class VaryingProvider:
        def collect(self, video_ref, *, limit=100):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient error")
            return [good_comment]

    monkeypatch.setattr(worker, "get_comment_provider", lambda *a, **k: VaryingProvider())

    event = _event(_msg(collection_id="col1", video_id="vid1"),
                   _msg(collection_id="col2", video_id="vid2"))
    out = worker.lambda_handler(event, None)

    assert out["processed"] == 2
    assert len(repo.stored) == 2
    assert repo.stored[0]["status"] == "failed"
    assert repo.stored[1]["status"] == "collected"


# ---------------------------------------------------------------------------
# Fallback tests (Task 5)
# ---------------------------------------------------------------------------

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
        self._primary = primary            # list or Exception
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
    return {"Records": [{"body": json.dumps(
        {"track_id": "t1", "platform": "youtube", "video_id": "art1", "collection_id": "col1"}
    )}]}


def _patch_fb(monkeypatch, repo, provider):
    monkeypatch.setattr(worker, "_build_repository", lambda: repo)
    monkeypatch.setattr(worker, "get_comment_provider", lambda *a, **k: provider)
    monkeypatch.setenv("YOUTUBE_API_KEY", "K")


def test_primary_has_comments_does_not_call_resolver(monkeypatch):
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
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"), alts=[], alt_behavior={},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "disabled"


def test_disabled_primary_all_alternates_disabled(monkeypatch):
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
    repo = FallbackFakeRepo()
    provider = FallbackProvider(
        primary=CommentsDisabledError("art1"),
        alts=["a"], alt_behavior={"a": []},
    )
    _patch_fb(monkeypatch, repo, provider)
    worker.lambda_handler(_fb_event(), None)
    assert repo.stored[0]["status"] == "empty"

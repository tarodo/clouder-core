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

    def fetch_ytmusic_status(self, track_ids):
        return {}


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

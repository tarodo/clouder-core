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

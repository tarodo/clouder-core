import json

import pytest

from collector.curation import (
    YtmusicApiError,
    YtmusicNotAuthorizedError,
    YtmusicNotFoundError,
)
from collector.curation.youtube_data_api_client import YoutubeDataApiClient


class FakeResp:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    """Records requests; returns queued responses in order (or a default 200)."""

    def __init__(self, responses=None):
        self._responses = list(responses or [])
        self.calls = []

    def request(self, *, method, url, params=None, data=None, headers=None):
        parsed = None
        if isinstance(data, (str, bytes, bytearray)):
            try:
                parsed = json.loads(data)
            except Exception:
                parsed = None
        self.calls.append(
            {
                "method": method, "url": url, "params": params,
                "data": data, "json": parsed, "headers": headers,
            }
        )
        if self._responses:
            return self._responses.pop(0)
        return FakeResp(200, {})


def _client(session):
    return YoutubeDataApiClient(access_token="AT", session=session)


def test_create_playlist_posts_and_returns_id():
    s = FakeSession([FakeResp(200, {"id": "PLnew"})])
    pid = _client(s).create_playlist(name="N", description="D", privacy="PRIVATE")
    assert pid == "PLnew"
    call = s.calls[0]
    assert call["method"] == "POST"
    assert call["url"].endswith("/youtube/v3/playlists")
    assert call["params"] == {"part": "snippet,status"}
    assert call["json"]["snippet"] == {"title": "N", "description": "D"}
    assert call["json"]["status"] == {"privacyStatus": "private"}
    assert call["headers"]["Authorization"] == "Bearer AT"


def test_create_playlist_public_maps_privacy():
    s = FakeSession([FakeResp(200, {"id": "PL"})])
    _client(s).create_playlist(name="N", description=None, privacy="PUBLIC")
    assert s.calls[0]["json"]["status"] == {"privacyStatus": "public"}
    assert s.calls[0]["json"]["snippet"]["description"] == ""


def test_create_playlist_no_id_raises():
    s = FakeSession([FakeResp(200, {})])
    with pytest.raises(YtmusicApiError):
        _client(s).create_playlist(name="N", description="D", privacy="PRIVATE")


def test_add_items_one_insert_per_video():
    s = FakeSession()
    _client(s).add_items("PL", ["v1", "v2", "v3"])
    assert len(s.calls) == 3
    for call, vid in zip(s.calls, ["v1", "v2", "v3"]):
        assert call["method"] == "POST"
        assert call["url"].endswith("/youtube/v3/playlistItems")
        assert call["json"]["snippet"]["playlistId"] == "PL"
        assert call["json"]["snippet"]["resourceId"] == {
            "kind": "youtube#video", "videoId": vid,
        }


def _pi(item_id, video_id):
    return {"id": item_id, "snippet": {"resourceId": {"videoId": video_id}}}


def test_get_existing_items_paginates_returning_video_and_item_ids():
    s = FakeSession([
        FakeResp(200, {"items": [_pi("i1", "v1"), _pi("i2", "v2")], "nextPageToken": "p2"}),
        FakeResp(200, {"items": [_pi("i3", "v3")]}),
    ])
    items = _client(s).get_existing_items("PL")
    assert items == [
        {"videoId": "v1", "itemId": "i1"},
        {"videoId": "v2", "itemId": "i2"},
        {"videoId": "v3", "itemId": "i3"},
    ]
    assert s.calls[0]["params"]["part"] == "snippet"
    assert s.calls[1]["params"]["pageToken"] == "p2"


def test_remove_items_deletes_each_and_noop_when_empty():
    s = FakeSession()
    _client(s).remove_items("PL", [])
    assert s.calls == []
    _client(s).remove_items("PL", ["i1", "i2"])
    assert [c["method"] for c in s.calls] == ["DELETE", "DELETE"]
    assert s.calls[0]["params"] == {"id": "i1"}


def test_edit_meta_puts_playlist():
    s = FakeSession([FakeResp(200, {"id": "PL"})])
    _client(s).edit_meta(playlist_id="PL", name="N2", description="D2", privacy="PUBLIC")
    call = s.calls[0]
    assert call["method"] == "PUT"
    assert call["json"]["id"] == "PL"
    assert call["json"]["snippet"]["title"] == "N2"
    assert call["json"]["status"] == {"privacyStatus": "public"}


def test_set_cover_multipart_upload():
    s = FakeSession([FakeResp(200, {"id": "img1"})])
    _client(s).set_cover("PL", b"\xff\xd8\xffJPEGDATA")
    call = s.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://www.googleapis.com/upload/youtube/v3/playlistImages"
    assert call["params"] == {"part": "snippet", "uploadType": "multipart"}
    assert call["headers"]["Content-Type"].startswith("multipart/related; boundary=")
    body = call["data"]
    assert b'"playlistId": "PL"' in body
    assert b'"type": "hero"' in body
    assert b"image/jpeg" in body
    assert b"JPEGDATA" in body


def test_set_cover_detects_png():
    s = FakeSession([FakeResp(200, {})])
    _client(s).set_cover("PL", b"\x89PNG\r\n\x1a\nDATA")
    assert b"image/png" in s.calls[0]["data"]


def test_set_cover_insert_succeeds_no_update():
    s = FakeSession([FakeResp(200, {"id": "img1"})])
    _client(s).set_cover("PL", b"\xff\xd8\xffJPEG")
    # Insert succeeded -> the update (PUT) fallback must NOT be attempted.
    assert [c["method"] for c in s.calls] == ["POST"]
    assert len(s.calls) == 1


def test_set_cover_insert_conflict_falls_back_to_update():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "image already exists"}}),
        FakeResp(200, {"id": "img1"}),
    ])
    _client(s).set_cover("PL", b"\xff\xd8\xffJPEG")
    assert [c["method"] for c in s.calls] == ["POST", "PUT"]
    # Both hit the same media-upload endpoint with the same multipart body.
    assert s.calls[1]["url"] == "https://www.googleapis.com/upload/youtube/v3/playlistImages"
    assert b'"playlistId": "PL"' in s.calls[1]["data"]


def test_set_cover_both_fail_raises():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "bad type"}}),
        FakeResp(400, {"error": {"message": "still bad"}}),
    ])
    with pytest.raises(YtmusicApiError):
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert [c["method"] for c in s.calls] == ["POST", "PUT"]


def test_set_cover_401_does_not_retry():
    s = FakeSession([FakeResp(401, {})])
    with pytest.raises(YtmusicNotAuthorizedError):
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert [c["method"] for c in s.calls] == ["POST"]


def test_move_item_puts_with_position():
    s = FakeSession([FakeResp(200, {"id": "i1"})])
    _client(s).move_item("PL", "i1", "v1", 2)
    call = s.calls[0]
    assert call["method"] == "PUT"
    assert call["url"].endswith("/youtube/v3/playlistItems")
    assert call["params"] == {"part": "snippet"}
    assert call["json"]["id"] == "i1"
    assert call["json"]["snippet"]["playlistId"] == "PL"
    assert call["json"]["snippet"]["resourceId"] == {"kind": "youtube#video", "videoId": "v1"}
    assert call["json"]["snippet"]["position"] == 2


def test_error_mapping():
    with pytest.raises(YtmusicNotFoundError):
        _client(FakeSession([FakeResp(404, {})])).edit_meta(
            playlist_id="PL", name="N", description=None, privacy="PRIVATE"
        )
    with pytest.raises(YtmusicNotAuthorizedError):
        _client(FakeSession([FakeResp(401, {})])).get_existing_items("PL")
    with pytest.raises(YtmusicApiError):
        _client(
            FakeSession([FakeResp(403, {"error": {"message": "quotaExceeded"}})])
        ).create_playlist(name="N", description="D", privacy="PRIVATE")

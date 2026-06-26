import json
from unittest.mock import patch

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


def _client(session, **kwargs):
    # No-op sleep so retry tests run instantly.
    kwargs.setdefault("sleep", lambda _s: None)
    return YoutubeDataApiClient(access_token="AT", session=session, **kwargs)


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


def test_request_error_enriches_message_with_reason_and_operation():
    # The real prod 409: surface status, machine reason, AND which operation
    # (method + endpoint) so the failing call is unambiguous in CloudWatch.
    body = {
        "error": {
            "message": "The operation was aborted.",
            "errors": [{"reason": "SERVICE_UNAVAILABLE", "domain": "youtube.playlistItem"}],
        }
    }
    # SERVICE_UNAVAILABLE is retryable: queue enough failures to exhaust retries.
    s = FakeSession([FakeResp(409, body)] * 4)
    with pytest.raises(YtmusicApiError) as ei:
        _client(s).move_item("PL", "i1", "v1", 2)
    msg = str(ei.value)
    assert "409" in msg
    assert "SERVICE_UNAVAILABLE" in msg
    assert "PUT" in msg
    assert "playlistItems" in msg
    assert "The operation was aborted." in msg
    assert ei.value.status_code == 409
    assert ei.value.reason == "SERVICE_UNAVAILABLE"


def test_request_error_reason_falls_back_to_status_field():
    body = {"error": {"message": "boom", "status": "ABORTED"}}
    s = FakeSession([FakeResp(409, body)] * 4)
    with pytest.raises(YtmusicApiError) as ei:
        _client(s).add_items("PL", ["v1"])
    assert ei.value.reason == "ABORTED"


def test_request_error_logs_breadcrumb_with_correlation_id():
    body = {"error": {"message": "boom", "errors": [{"reason": "rateLimitExceeded"}]}}
    s = FakeSession([FakeResp(409, body)])
    client = YoutubeDataApiClient(access_token="AT", session=s, correlation_id="corr-1")
    with patch("collector.curation.youtube_data_api_client.log_event") as le:
        with pytest.raises(YtmusicApiError):
            client.add_items("PL", ["v1"])
    assert le.call_count == 1
    args, kwargs = le.call_args
    assert args[0] == "WARNING"
    assert args[1] == "ytmusic_api_call_failed"
    assert kwargs["correlation_id"] == "corr-1"
    assert kwargs["status_code"] == 409
    assert kwargs["reason"] == "rateLimitExceeded"
    # 'phase' is the structured, CloudWatch-queryable "which operation" field.
    assert kwargs["phase"] == "POST playlistItems"
    assert kwargs["error_message"] == "boom"
    # No access token must ever reach the logs.
    assert "AT" not in json.dumps(kwargs)


def test_not_found_error_carries_status_and_reason():
    body = {"error": {"message": "gone", "errors": [{"reason": "playlistNotFound"}]}}
    with pytest.raises(YtmusicNotFoundError) as ei:
        _client(FakeSession([FakeResp(404, body)])).get_existing_items("PL")
    assert ei.value.status_code == 404
    assert ei.value.reason == "playlistNotFound"


def test_request_error_message_omits_reason_bracket_when_absent():
    # No errors[] and no status field -> reason is None: the message must not
    # render a literal "[None]" bracket.
    s = FakeSession([FakeResp(403, {"error": {"message": "quotaExceeded"}})])
    with pytest.raises(YtmusicApiError) as ei:
        _client(s).add_items("PL", ["v1"])
    msg = str(ei.value)
    assert msg == "YouTube 403 on POST playlistItems: quotaExceeded"
    assert "[" not in msg
    assert ei.value.reason is None


def test_set_cover_both_fail_carries_status_reason_and_message():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "bad type"}}),
        FakeResp(409, {"error": {"message": "conflict",
                                 "errors": [{"reason": "SERVICE_UNAVAILABLE"}]}}),
    ])
    with pytest.raises(YtmusicApiError) as ei:
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert ei.value.status_code == 409
    assert ei.value.reason == "SERVICE_UNAVAILABLE"
    assert "SERVICE_UNAVAILABLE" in str(ei.value)


def test_set_cover_both_fail_omits_reason_bracket_when_absent():
    s = FakeSession([
        FakeResp(400, {"error": {"message": "bad type"}}),
        FakeResp(400, {"error": {"message": "still bad"}}),
    ])
    with pytest.raises(YtmusicApiError) as ei:
        _client(s).set_cover("PL", b"\xff\xd8\xffX")
    assert "[None]" not in str(ei.value)
    assert ei.value.reason is None


# ---------- retry on transient failures -------------------------------------

_ABORTED = {"error": {"message": "The operation was aborted.",
                      "errors": [{"reason": "SERVICE_UNAVAILABLE"}]}}


def test_request_retries_transient_409_then_succeeds():
    # The exact prod failure: first insert 409s SERVICE_UNAVAILABLE, retry wins.
    s = FakeSession([FakeResp(409, _ABORTED), FakeResp(200, {})])
    _client(s).add_items("PL", ["v1"])  # must not raise
    assert len(s.calls) == 2


def test_request_retries_then_gives_up_after_max_attempts():
    s = FakeSession([FakeResp(409, _ABORTED)] * 6)  # more than enough
    with patch("collector.curation.youtube_data_api_client.log_event") as le:
        with pytest.raises(YtmusicApiError) as ei:
            _client(s).add_items("PL", ["v1"])
    # 4 attempts total (1 initial + 3 retries), then terminal failure.
    assert len(s.calls) == 4
    assert ei.value.status_code == 409
    events = [c.args[1] for c in le.call_args_list]
    assert events.count("ytmusic_api_call_retried") == 3
    assert events.count("ytmusic_api_call_failed") == 1
    # Retry breadcrumb carries the queryable structured fields.
    retried = [c for c in le.call_args_list if c.args[1] == "ytmusic_api_call_retried"]
    assert [c.kwargs["attempt"] for c in retried] == [1, 2, 3]
    assert [c.kwargs["sleep_seconds"] for c in retried] == [0.5, 1.0, 2.0]
    assert all(c.kwargs["phase"] == "POST playlistItems" for c in retried)
    assert all(c.kwargs["reason"] == "SERVICE_UNAVAILABLE" for c in retried)


def test_request_backoff_schedule_is_half_one_two():
    slept: list[float] = []
    s = FakeSession([FakeResp(409, _ABORTED)] * 6)
    client = YoutubeDataApiClient(
        access_token="AT", session=s, sleep=lambda secs: slept.append(secs)
    )
    with pytest.raises(YtmusicApiError):
        client.add_items("PL", ["v1"])
    assert slept == [0.5, 1.0, 2.0]


def test_request_retries_5xx_on_idempotent_method_then_succeeds():
    # PUT (move_item) is idempotent -> 5xx is retried.
    s = FakeSession([FakeResp(503, {"error": {"message": "unavailable"}}), FakeResp(200, {})])
    _client(s).move_item("PL", "i1", "v1", 2)
    assert len(s.calls) == 2


def test_request_retries_429_on_idempotent_method():
    s = FakeSession([FakeResp(429, {"error": {"message": "slow down"}}), FakeResp(200, {})])
    _client(s).move_item("PL", "i1", "v1", 2)
    assert len(s.calls) == 2


def test_request_does_not_retry_5xx_on_post():
    # POST (add_items / create_playlist) is NOT idempotent: a 5xx may have
    # committed, so retrying could duplicate. Must fail on the first try.
    s = FakeSession([FakeResp(503, {"error": {"message": "unavailable"}}), FakeResp(200, {})])
    with pytest.raises(YtmusicApiError):
        _client(s).add_items("PL", ["v1"])
    assert len(s.calls) == 1


def test_request_retries_409_with_no_reason():
    # A 409 with no machine reason is treated as a transient abort (safe to retry
    # on any method, since an aborted write never applied).
    s = FakeSession([FakeResp(409, {"error": {"message": "aborted"}}), FakeResp(200, {})])
    _client(s).add_items("PL", ["v1"])
    assert len(s.calls) == 2


def test_request_delete_404_on_retry_is_treated_as_success():
    # DELETE 503 (committed?) -> retry hits 404 (already gone) -> success, no raise.
    s = FakeSession([FakeResp(503, {"error": {"message": "unavailable"}}), FakeResp(404, {})])
    _client(s).remove_items("PL", ["i1"])
    assert len(s.calls) == 2


def test_request_delete_404_on_first_attempt_still_raises():
    s = FakeSession([FakeResp(404, {})])
    with pytest.raises(YtmusicNotFoundError):
        _client(s).remove_items("PL", ["i1"])
    assert len(s.calls) == 1


def test_request_does_not_retry_hard_409():
    # A 409 whose reason is not transient must fail on the first try.
    body = {"error": {"message": "nope", "errors": [{"reason": "INVALID_VALUE"}]}}
    s = FakeSession([FakeResp(409, body), FakeResp(200, {})])
    with pytest.raises(YtmusicApiError):
        _client(s).add_items("PL", ["v1"])
    assert len(s.calls) == 1


def test_request_does_not_retry_4xx_client_errors():
    s = FakeSession([FakeResp(400, {"error": {"message": "bad"}}), FakeResp(200, {})])
    with pytest.raises(YtmusicApiError):
        _client(s).add_items("PL", ["v1"])
    assert len(s.calls) == 1

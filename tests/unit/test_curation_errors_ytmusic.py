from collector.curation import (
    CurationError,
    YtmusicApiError,
    YtmusicNotAuthorizedError,
    YtmusicNotFoundError,
)


def test_not_authorized_is_412():
    exc = YtmusicNotAuthorizedError("no token")
    assert exc.http_status == 412
    assert exc.error_code == "ytmusic_not_authorized"
    assert isinstance(exc, CurationError)


def test_api_error_is_502():
    exc = YtmusicApiError("boom")
    assert exc.http_status == 502
    assert exc.error_code == "ytmusic_api_error"


def test_not_found_subclasses_api_error():
    exc = YtmusicNotFoundError("gone")
    assert isinstance(exc, YtmusicApiError)
    assert exc.http_status == 502
    assert exc.error_code == "ytmusic_not_found"


def test_api_error_carries_status_and_reason():
    exc = YtmusicApiError("YouTube 409 ...", status_code=409, reason="SERVICE_UNAVAILABLE")
    assert exc.status_code == 409
    assert exc.reason == "SERVICE_UNAVAILABLE"
    assert exc.http_status == 502  # client-facing envelope unchanged


def test_api_error_defaults_status_reason_to_none():
    exc = YtmusicApiError("boom")
    assert exc.status_code is None
    assert exc.reason is None


def test_not_found_carries_status_and_reason():
    exc = YtmusicNotFoundError("gone", status_code=404, reason="playlistNotFound")
    assert exc.status_code == 404
    assert exc.reason == "playlistNotFound"
    assert exc.error_code == "ytmusic_not_found"

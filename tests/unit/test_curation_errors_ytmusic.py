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

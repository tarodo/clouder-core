"""The handler maps CurationError -> HTTP envelope. Upstream/server failures
(http_status >= 500, e.g. ytmusic_api_error=502) were returned to the client
but never logged, leaving CloudWatch blind to the real YouTube reason. Assert
they are now logged with structured status_code + reason, and that expected
client errors (4xx) stay quiet."""

import json
from unittest.mock import patch

from collector import curation_handler
from collector.curation import CurationError, ValidationError, YtmusicApiError


def test_curation_error_response_logs_5xx_with_status_and_reason():
    exc = YtmusicApiError(
        "YouTube 409 [SERVICE_UNAVAILABLE] on PUT playlistItems: The operation was aborted.",
        status_code=409,
        reason="SERVICE_UNAVAILABLE",
    )
    with patch.object(curation_handler, "log_event") as le:
        resp = curation_handler._curation_error_response(exc, "corr-9")

    assert resp["statusCode"] == 502
    assert json.loads(resp["body"])["error_code"] == "ytmusic_api_error"
    assert le.call_count == 1
    args, kwargs = le.call_args
    assert args[0] == "ERROR"
    assert args[1] == "curation_error_returned"
    assert kwargs["correlation_id"] == "corr-9"
    assert kwargs["error_code"] == "ytmusic_api_error"
    assert kwargs["status_code"] == 409
    assert kwargs["reason"] == "SERVICE_UNAVAILABLE"


def test_curation_error_response_does_not_log_4xx():
    with patch.object(curation_handler, "log_event") as le:
        resp = curation_handler._curation_error_response(ValidationError("bad"), "corr-9")

    assert resp["statusCode"] == 422
    assert le.call_count == 0


def test_curation_error_response_logs_5xx_without_status_reason_attrs():
    # Bare CurationError (http_status 500, e.g. SpotifyApiError siblings) has no
    # status_code/reason attrs; the getattr(..., None) default must keep logging.
    exc = CurationError("kaboom")  # default http_status = 500
    with patch.object(curation_handler, "log_event") as le:
        resp = curation_handler._curation_error_response(exc, "corr-x")

    assert resp["statusCode"] == 500
    assert le.call_count == 1
    _args, kwargs = le.call_args
    assert kwargs["status_code"] is None
    assert kwargs["reason"] is None

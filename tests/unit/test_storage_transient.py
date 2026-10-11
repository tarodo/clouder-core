"""S3 failures that can heal (throttling, 5xx, network) are retried; the rest fail the run."""

from __future__ import annotations

from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError

from collector.errors import StorageError, TransientStorageError
from collector.storage import S3Storage


def _client_error(code: str, status: int) -> ClientError:
    return ClientError(
        {"Error": {"Code": code, "Message": "x"}, "ResponseMetadata": {"HTTPStatusCode": status}},
        "GetObject",
    )


class FailingS3:
    def __init__(self, exc: Exception) -> None:
        self.exc = exc

    def get_object(self, **kwargs: Any) -> Any:
        raise self.exc

    def put_object(self, **kwargs: Any) -> Any:
        raise self.exc


def _storage(exc: Exception) -> S3Storage:
    return S3Storage(s3_client=FailingS3(exc), bucket_name="b", raw_prefix="raw/bp/releases")


@pytest.mark.parametrize(
    "exc",
    [
        _client_error("SlowDown", 503),
        _client_error("InternalError", 500),
        _client_error("ServiceUnavailable", 503),
        _client_error("RequestTimeout", 400),
        EndpointConnectionError(endpoint_url="https://s3.amazonaws.com"),
    ],
)
def test_transient_s3_failures_are_marked_transient(exc: Exception) -> None:
    with pytest.raises(TransientStorageError):
        _storage(exc).read_releases("raw/bp/releases/x.json.gz")


@pytest.mark.parametrize(
    "exc", [_client_error("NoSuchKey", 404), _client_error("AccessDenied", 403)]
)
def test_permanent_s3_failures_stay_permanent(exc: Exception) -> None:
    with pytest.raises(StorageError) as caught:
        _storage(exc).read_releases("raw/bp/releases/x.json.gz")
    assert not isinstance(caught.value, TransientStorageError)


def test_transient_errors_are_still_storage_errors() -> None:
    # Existing `except StorageError` call sites keep catching them.
    assert issubclass(TransientStorageError, StorageError)

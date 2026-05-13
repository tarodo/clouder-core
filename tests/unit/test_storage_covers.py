from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from collector.errors import StorageError
from collector.storage import S3Storage


def _storage(client: MagicMock) -> S3Storage:
    return S3Storage(s3_client=client, bucket_name="b", raw_prefix="raw/bp/releases")


def test_cover_put_key_uses_user_playlist_epoch() -> None:
    s = _storage(MagicMock())
    key = s.cover_key(user_id="u-1", playlist_id="p-1", epoch_ms=1234567890)
    assert key == "covers/u-1/p-1/1234567890.jpg"


def test_presigned_put_url_calls_s3_generate() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed-put"
    s = _storage(client)
    url = s.presigned_cover_put_url(
        s3_key="covers/u/p/1.jpg",
        content_type="image/jpeg",
        expires_in=300,
    )
    assert url == "https://signed-put"
    args, kwargs = client.generate_presigned_url.call_args
    # operation name is first positional arg
    assert args[0] == "put_object"
    params = kwargs.get("Params") or {}
    assert params["Bucket"] == "b"
    assert params["Key"] == "covers/u/p/1.jpg"
    assert params["ContentType"] == "image/jpeg"
    # ContentLength must NOT be signed — see the regression note in
    # storage.presigned_cover_put_url. Browser cannot pre-declare exact
    # Content-Length and the signature would not match the actual file.
    assert "ContentLength" not in params


def test_presigned_put_url_signs_png_content_type() -> None:
    """Browser may upload PNG instead of JPEG; the presign must reflect
    whatever content_type the caller asks for so the browser PUT (which
    sends matching Content-Type) does not break the signature."""
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed-put-png"
    s = _storage(client)
    s.presigned_cover_put_url(
        s3_key="covers/u/p/1.png",
        content_type="image/png",
        expires_in=300,
    )
    _, kwargs = client.generate_presigned_url.call_args
    params = kwargs.get("Params") or {}
    assert params["ContentType"] == "image/png"


def test_presigned_get_url() -> None:
    client = MagicMock()
    client.generate_presigned_url.return_value = "https://signed-get"
    s = _storage(client)
    url = s.presigned_cover_get_url(
        s3_key="covers/u/p/1.jpg", expires_in=3600,
    )
    assert url == "https://signed-get"


def test_head_cover_returns_size_when_present() -> None:
    client = MagicMock()
    client.head_object.return_value = {
        "ContentLength": 12345, "ContentType": "image/jpeg",
    }
    s = _storage(client)
    info = s.head_cover("covers/u/p/1.jpg")
    assert info == {"size": 12345, "content_type": "image/jpeg"}


def test_head_cover_returns_none_when_404() -> None:
    client = MagicMock()

    class _NoSuch(Exception):
        pass

    err = _NoSuch("NoSuchKey")
    setattr(err, "response", {"Error": {"Code": "NoSuchKey"}})
    client.head_object.side_effect = err
    s = _storage(client)
    assert s.head_cover("covers/u/p/1.jpg") is None


def test_read_cover_bytes_returns_payload() -> None:
    client = MagicMock()
    stream = MagicMock()
    stream.read.return_value = b"jpeg-bytes"
    client.get_object.return_value = {"Body": stream}
    s = _storage(client)
    out = s.read_cover_bytes("covers/u/p/1.jpg")
    assert out == b"jpeg-bytes"


def test_read_cover_bytes_raises_storage_error_on_failure() -> None:
    client = MagicMock()
    client.get_object.side_effect = RuntimeError("S3 boom")
    s = _storage(client)
    with pytest.raises(StorageError):
        s.read_cover_bytes("covers/u/p/1.jpg")

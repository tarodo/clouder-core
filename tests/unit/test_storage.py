"""Tests for S3Storage: write_run_artifacts and read_releases."""

from __future__ import annotations

import gzip
import json
from io import BytesIO
from typing import Any, Dict

import pytest

from collector.errors import StorageError
from collector.storage import S3Storage


class FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.objects: dict[str, bytes] = {}
        self.fail_on_put = False
        self.fail_on_get = False

    def put_object(self, **kwargs: Any) -> None:
        if self.fail_on_put:
            raise RuntimeError("S3 put failed")
        self.calls.append(kwargs)
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        if self.fail_on_get:
            raise RuntimeError("S3 get failed")
        key = kwargs["Key"]
        body = self.objects.get(key)
        if body is None:
            raise RuntimeError(f"NoSuchKey: {key}")
        return {"Body": BytesIO(body)}


def _meta(style_id: int = 5, iso_year: int = 2026, iso_week: int = 9) -> Dict[str, Any]:
    return {
        "style_id": style_id,
        "iso_year": iso_year,
        "iso_week": iso_week,
    }


def test_write_run_artifacts_creates_releases_and_meta() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")

    releases_key, meta_key = storage.write_run_artifacts(
        releases=[{"id": 1}], meta=_meta()
    )

    assert releases_key.endswith("/releases.json.gz")
    assert meta_key.endswith("/meta.json")
    assert "style_id=5" in releases_key
    assert "year=2026" in releases_key
    assert "week=09" in releases_key
    assert len(s3.calls) == 2

    # Verify releases is gzip-compressed valid JSON
    raw = gzip.decompress(s3.objects[releases_key])
    parsed = json.loads(raw)
    assert parsed == [{"id": 1}]

    # Verify meta is plain JSON
    meta_parsed = json.loads(s3.objects[meta_key])
    assert meta_parsed["style_id"] == 5


def test_write_run_artifacts_raises_storage_error_on_s3_failure() -> None:
    s3 = FakeS3Client()
    s3.fail_on_put = True
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")

    with pytest.raises(StorageError):
        storage.write_run_artifacts(releases=[{"id": 1}], meta=_meta())


def test_read_releases_decompresses_and_parses() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")

    data = [{"id": 1, "name": "Track"}, {"id": 2, "name": "Track 2"}]
    compressed = gzip.compress(json.dumps(data).encode("utf-8"))
    s3.objects["test-key"] = compressed

    result = storage.read_releases("test-key")

    assert result == data


def test_read_releases_filters_non_dict_items() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")

    data = [{"id": 1}, "invalid_string", {"id": 2}, 42]
    compressed = gzip.compress(json.dumps(data).encode("utf-8"))
    s3.objects["test-key"] = compressed

    result = storage.read_releases("test-key")

    assert len(result) == 2
    assert result[0] == {"id": 1}
    assert result[1] == {"id": 2}


def test_read_releases_raises_storage_error_on_s3_failure() -> None:
    s3 = FakeS3Client()
    s3.fail_on_get = True
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")

    with pytest.raises(StorageError, match="Failed to read"):
        storage.read_releases("missing-key")


def test_read_releases_raises_on_non_gzip_data() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")
    s3.objects["bad-key"] = b"not gzip data"

    with pytest.raises(StorageError, match="Failed to decode"):
        storage.read_releases("bad-key")


def test_read_releases_raises_on_non_list_payload() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="test-bucket")
    s3.objects["obj-key"] = gzip.compress(json.dumps({"not": "a list"}).encode("utf-8"))

    with pytest.raises(StorageError, match="Unexpected releases payload"):
        storage.read_releases("obj-key")


def test_base_key_pads_week_number() -> None:
    s3 = FakeS3Client()
    storage = S3Storage(s3_client=s3, bucket_name="b", raw_prefix="pfx")

    releases_key, _ = storage.write_run_artifacts(
        releases=[], meta={"style_id": 1, "iso_year": 2026, "iso_week": 3}
    )

    assert "week=03" in releases_key

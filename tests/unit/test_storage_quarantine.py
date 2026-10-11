from __future__ import annotations

import gzip
import json

from collector.storage import S3Storage


class Capture:
    def __init__(self) -> None:
        self.puts: list[dict] = []

    def put_object(self, **kwargs) -> None:
        self.puts.append(kwargs)


def test_write_quarantine_stores_records_with_reasons() -> None:
    s3 = Capture()
    storage = S3Storage(s3_client=s3, bucket_name="b", raw_prefix="raw/bp/releases")
    rows = [{"reasons": ["name: empty"], "record": {"id": 1, "name": ""}}]

    key = storage.write_quarantine("r1", rows)

    assert key == "raw/bp/releases/_quarantine/run_id=r1/records.json.gz"
    put = s3.puts[0]
    assert (put["Bucket"], put["Key"], put["ContentEncoding"]) == ("b", key, "gzip")
    assert json.loads(gzip.decompress(put["Body"])) == rows


class Reader:
    def __init__(self, payload) -> None:
        self.payload = payload

    def get_object(self, **kwargs):
        from io import BytesIO

        return {"Body": BytesIO(gzip.compress(json.dumps(self.payload).encode()))}


def test_read_releases_keeps_records_that_are_not_objects() -> None:
    # They reach the contract and are quarantined, instead of vanishing here.
    storage = S3Storage(
        s3_client=Reader(["x", {"id": 1}]), bucket_name="b", raw_prefix="raw/bp/releases"
    )
    assert storage.read_releases("k") == ["x", {"id": 1}]

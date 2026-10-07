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

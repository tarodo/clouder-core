"""S3 persistence for weekly snapshots and run archives."""

from __future__ import annotations

import gzip
import json
from typing import Any, Dict, List, Tuple

from .errors import StorageError


def create_default_s3_client() -> Any:
    import boto3  # Imported lazily to keep local test environment lightweight.

    return boto3.client("s3")


class S3Storage:
    def __init__(self, s3_client: Any, bucket_name: str, raw_prefix: str = "raw/bp/releases") -> None:
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        self.raw_prefix = raw_prefix.rstrip("/")

    def write_run_artifacts(
        self,
        releases: List[Dict[str, Any]],
        meta: Dict[str, Any],
    ) -> Tuple[str, str, str]:
        style_id = int(meta["style_id"])
        iso_year = int(meta["iso_year"])
        iso_week = int(meta["iso_week"])
        run_id = str(meta["run_id"])

        base_key = self._base_key(style_id=style_id, iso_year=iso_year, iso_week=iso_week)
        releases_key = f"{base_key}/releases.json.gz"
        meta_key = f"{base_key}/meta.json"
        run_key = f"{base_key}/runs/run_id={run_id}.json.gz"

        releases_bytes = gzip.compress(json.dumps(releases, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

        try:
            self._put_object(
                key=releases_key,
                body=releases_bytes,
                content_type="application/json",
                content_encoding="gzip",
            )
            self._put_object(
                key=meta_key,
                body=json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                content_type="application/json",
            )
            self._put_object(
                key=run_key,
                body=releases_bytes,
                content_type="application/json",
                content_encoding="gzip",
            )
        except Exception as exc:
            raise StorageError() from exc

        return releases_key, meta_key, run_key

    def _base_key(self, style_id: int, iso_year: int, iso_week: int) -> str:
        return f"{self.raw_prefix}/style_id={style_id}/year={iso_year}/week={iso_week:02d}"

    def _put_object(self, key: str, body: bytes, content_type: str, content_encoding: str | None = None) -> None:
        kwargs: Dict[str, Any] = {
            "Bucket": self.bucket_name,
            "Key": key,
            "Body": body,
            "ContentType": content_type,
        }
        if content_encoding:
            kwargs["ContentEncoding"] = content_encoding
        self.s3_client.put_object(**kwargs)

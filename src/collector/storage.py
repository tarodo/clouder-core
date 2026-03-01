"""S3 persistence for weekly snapshots."""

from __future__ import annotations

import gzip
import json
from typing import Any, Dict, List, Tuple

from .errors import StorageError
from .logging_utils import log_event


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
    ) -> Tuple[str, str]:
        style_id = int(meta["style_id"])
        iso_year = int(meta["iso_year"])
        iso_week = int(meta["iso_week"])

        base_key = self._base_key(style_id=style_id, iso_year=iso_year, iso_week=iso_week)
        releases_key = f"{base_key}/releases.json.gz"
        meta_key = f"{base_key}/meta.json"

        releases_bytes = gzip.compress(json.dumps(releases, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        meta_bytes = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

        try:
            self._put_object(
                key=releases_key,
                body=releases_bytes,
                content_type="application/json",
                content_encoding="gzip",
            )
            log_event(
                "INFO",
                "s3_object_written",
                s3_bucket=self.bucket_name,
                s3_key=releases_key,
                s3_size_bytes=len(releases_bytes),
            )
            self._put_object(
                key=meta_key,
                body=meta_bytes,
                content_type="application/json",
            )
            log_event(
                "INFO",
                "s3_object_written",
                s3_bucket=self.bucket_name,
                s3_key=meta_key,
                s3_size_bytes=len(meta_bytes),
            )
        except Exception as exc:
            raise StorageError() from exc

        log_event(
            "INFO",
            "s3_write_completed",
            s3_bucket=self.bucket_name,
            s3_key=releases_key,
        )
        return releases_key, meta_key

    def read_releases(self, key: str) -> List[Dict[str, Any]]:
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            raw_bytes = response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Failed to read object from S3: {key}") from exc

        try:
            decoded = gzip.decompress(raw_bytes).decode("utf-8")
            parsed = json.loads(decoded)
        except Exception as exc:
            raise StorageError(f"Failed to decode releases payload: {key}") from exc

        if not isinstance(parsed, list):
            raise StorageError(f"Unexpected releases payload type in {key}")
        return [item for item in parsed if isinstance(item, dict)]

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

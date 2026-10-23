"""Light-1 profiles from S3 as a float32 matrix."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from collector import audio_profile


def vectors(
    video_ids: list[str], fetch: Callable[[str], bytes | None], workers: int = 32
) -> tuple[list[str], np.ndarray]:
    """The ids that have a profile, and their rows (n, DIMS) float32, in input order."""
    # ponytail: one GET per video; a consolidated per-style matrix only if fetch time dominates
    X = np.empty((len(video_ids), audio_profile.DIMS), dtype=np.float32)
    present: list[str] = []
    with ThreadPoolExecutor(workers) as pool:
        for video_id, blob in zip(video_ids, pool.map(fetch, video_ids), strict=True):
            if blob is not None:
                X[len(present)] = np.frombuffer(blob, "<f2")
                present.append(video_id)
    return present, X[: len(present)]


def s3_fetcher(s3: Any, bucket: str) -> Callable[[str], bytes | None]:
    """A fetch for `vectors`: the profile's bytes, None when the object is missing. A missing key reads as
    NoSuchKey only with s3:ListBucket; without it S3 answers AccessDenied, which raises."""

    def fetch(video_id: str) -> bytes | None:
        try:
            response = s3.get_object(Bucket=bucket, Key=audio_profile.s3_key(video_id))
        except s3.exceptions.NoSuchKey:
            return None
        return response["Body"].read()

    return fetch

from __future__ import annotations

import io

import boto3
import numpy as np
from botocore.response import StreamingBody
from botocore.stub import Stubber

from collector import audio_profile
from collector.ml import features


def test_vectors_skips_missing() -> None:
    rng = np.random.default_rng(0)
    a, b = (rng.normal(size=audio_profile.DIMS).astype("<f2") for _ in range(2))
    blobs = {"v1": a.tobytes(), "v3": b.tobytes()}
    ids, X = features.vectors(["v1", "v2", "v3"], blobs.get, workers=2)
    assert ids == ["v1", "v3"]
    assert X.dtype == np.float32
    assert X.shape == (2, audio_profile.DIMS)
    np.testing.assert_array_equal(X[0], a.astype(np.float32))
    np.testing.assert_array_equal(X[1], b.astype(np.float32))


def test_s3_fetcher_none_for_missing_key() -> None:
    s3 = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x"
    )
    with Stubber(s3) as stub:
        stub.add_response(
            "get_object",
            {"Body": StreamingBody(io.BytesIO(b"abc"), 3)},
            {"Bucket": "bkt", "Key": audio_profile.s3_key("v1")},
        )
        stub.add_client_error("get_object", "NoSuchKey", http_status_code=404)
        fetch = features.s3_fetcher(s3, "bkt")
        assert fetch("v1") == b"abc"
        assert fetch("v2") is None

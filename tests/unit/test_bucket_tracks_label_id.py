"""Triage bucket tracks must expose label_id (FE label tile prerequisite)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from collector import curation_handler
from collector.curation.triage_repository import BucketTrackRowOut


def _event() -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-unit",
            "routeKey": "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks",
            "authorizer": {
                "lambda": {
                    "user_id": "u-1",
                    "session_id": "s",
                    "is_admin": False,
                }
            },
        },
        "headers": {"x-correlation-id": "cid-label-id-1"},
        "pathParameters": {"id": "b-1", "bucket_id": "bk-1"},
        "queryStringParameters": {"limit": "50", "offset": "0"},
        "body": None,
    }


def test_bucket_tracks_response_includes_label_id(monkeypatch) -> None:
    """GET /triage/blocks/{}/buckets/{}/tracks rows must include label_id."""
    row = BucketTrackRowOut(
        track_id="t-1",
        title="Drift",
        mix_name=None,
        isrc=None,
        bpm=174,
        length_ms=360_000,
        publish_date="2026-04-01",
        spotify_release_date="2026-04-01",
        spotify_id=None,
        release_type="single",
        is_ai_suspected=False,
        artists=("Artist A",),
        label_name="Cool Label",
        label_id="lbl-1",
        added_at="2026-04-01T08:00:00Z",
    )

    class FakeRepo:
        def list_bucket_tracks(
            self,
            *,
            user_id: str,
            block_id: str,
            bucket_id: str,
            limit: int,
            offset: int,
            search: Any = None,
        ):
            return [row], 1

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )

    context = SimpleNamespace(aws_request_id="lambda-req-label-id-1")
    resp = curation_handler.lambda_handler(_event(), context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"][0]["label_id"] == "lbl-1"
    assert body["items"][0]["label_name"] == "Cool Label"

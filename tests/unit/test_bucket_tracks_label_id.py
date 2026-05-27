"""Triage bucket tracks must expose label_id and artist id/name/role objects."""

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
        artists=[{"id": "a-10", "name": "Artist A", "role": "artist"}],
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


def test_bucket_tracks_response_includes_artist_objects(monkeypatch) -> None:
    """GET bucket tracks must return artists as {id, name, role} dicts, not plain strings."""
    row = BucketTrackRowOut(
        track_id="t-2",
        title="Orbit",
        mix_name=None,
        isrc=None,
        bpm=128,
        length_ms=420_000,
        publish_date="2026-05-01",
        spotify_release_date="2026-05-01",
        spotify_id=None,
        release_type="single",
        is_ai_suspected=False,
        artists=[{"id": "a-1", "name": "Raabe", "role": "artist"}, {"id": "a-2", "name": "Zander", "role": "remixer"}],
        label_name="Deep Label",
        label_id="lbl-2",
        added_at="2026-05-01T08:00:00Z",
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

    context = SimpleNamespace(aws_request_id="lambda-req-artist-obj-1")
    resp = curation_handler.lambda_handler(_event(), context)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    artists = body["items"][0]["artists"]
    assert isinstance(artists, list)
    assert len(artists) == 2
    assert artists[0] == {"id": "a-1", "name": "Raabe", "role": "artist"}
    assert artists[1] == {"id": "a-2", "name": "Zander", "role": "remixer"}

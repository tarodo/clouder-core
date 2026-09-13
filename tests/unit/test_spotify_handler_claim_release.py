"""A batch that dies after claiming must hand its rows back.

Claiming stamps `spotify_searched_at` up front, which is what stops a second
worker re-searching the same tracks. The flip side is that a crashed batch
would leave its rows looking permanently "searched, not found" — so the worker
releases whatever it never resolved before letting the error reach SQS.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from collector.errors import SpotifyUnavailableError
from collector.providers import registry
from collector.settings import reset_settings_cache
from collector.spotify_handler import lambda_handler

TRACKS = [
    {"id": "ct1", "isrc": "ISRC001", "title": "T1", "normalized_title": "t1"},
    {"id": "ct2", "isrc": "ISRC002", "title": "T2", "normalized_title": "t2"},
]


class ClaimingRepo:
    def __init__(self) -> None:
        self.claimed_at: Any = None
        self.released: list[Any] = []
        self.updated_spotify: list[dict] = []

    def claim_tracks_for_spotify_search(self, limit, claimed_at):
        self.claimed_at = claimed_at
        return TRACKS[:limit]

    def find_tracks_needing_spotify_search(self, limit):
        return []

    def release_spotify_search_claim(self, claimed_at, now):
        self.released.append(claimed_at)
        return 2

    def batch_upsert_source_entities(self, commands, transaction_id=None):
        pass

    def batch_upsert_identities(self, commands, transaction_id=None):
        pass

    def batch_update_spotify_results(self, commands, transaction_id=None):
        self.updated_spotify.extend(commands)

    def propagate_release_type_to_albums(self, track_ids, transaction_id=None):
        pass


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]


def _setup(monkeypatch) -> tuple[ClaimingRepo, FakeS3Client]:
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_RAW_PREFIX", "raw/sp/tracks")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "")
    repo = ClaimingRepo()
    s3 = FakeS3Client()
    monkeypatch.setattr(
        "collector.spotify_handler.create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        "collector.spotify_handler.create_default_s3_client", lambda: s3
    )
    return repo, s3


def _event() -> dict[str, Any]:
    return {
        "Records": [
            {
                "body": json.dumps({"batch_size": 2000}),
                "messageAttributes": {
                    "correlation_id": {
                        "stringValue": "cid-1",
                        "dataType": "String",
                    }
                },
            }
        ]
    }


def test_transient_failure_releases_the_claim_and_reraises(monkeypatch) -> None:
    repo, _ = _setup(monkeypatch)

    def boom(self, tracks, correlation_id, **_kwargs):
        raise SpotifyUnavailableError()

    monkeypatch.setattr(
        "collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc", boom
    )

    with pytest.raises(SpotifyUnavailableError):
        lambda_handler(_event(), context=None)

    # Released exactly the batch we claimed, so the SQS redelivery re-searches it.
    assert repo.released == [repo.claimed_at]
    reset_settings_cache()


def test_successful_batch_does_not_release(monkeypatch) -> None:
    repo, _ = _setup(monkeypatch)

    from collector.spotify_client import SpotifySearchResult

    def ok(self, tracks, correlation_id, **_kwargs):
        return [
            SpotifySearchResult(
                isrc=t["isrc"],
                clouder_track_id=t["clouder_track_id"],
                spotify_track={"id": "sp1", "name": "n"},
                spotify_id="sp1",
            )
            for t in tracks
        ]

    monkeypatch.setattr(
        "collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc", ok
    )

    lambda_handler(_event(), context=None)

    assert repo.released == []
    assert len(repo.updated_spotify) == 2
    reset_settings_cache()


def test_claim_is_stamped_before_the_upstream_call(monkeypatch) -> None:
    """The stamp has to land before the search, not after it."""
    repo, _ = _setup(monkeypatch)
    seen: dict[str, Any] = {}

    def capture(self, tracks, correlation_id, **_kwargs):
        seen["claimed_at_during_search"] = repo.claimed_at
        raise SpotifyUnavailableError()

    monkeypatch.setattr(
        "collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc", capture
    )

    with pytest.raises(SpotifyUnavailableError):
        lambda_handler(_event(), context=None)

    assert seen["claimed_at_during_search"] is not None
    reset_settings_cache()

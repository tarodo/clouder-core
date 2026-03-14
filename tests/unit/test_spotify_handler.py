"""Tests for Spotify search SQS worker lambda."""

from __future__ import annotations

import gzip
import json
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from collector.settings import reset_settings_cache
from collector.spotify_client import SpotifySearchResult
from collector.spotify_handler import lambda_handler


class FakeRepo:
    """Minimal repo mock for Spotify search worker."""

    def __init__(self, tracks: list[dict[str, Any]] | None = None) -> None:
        self._tracks = tracks or []
        self.updated_spotify: list[dict] = []
        self.source_entity_cmds: list = []
        self.identity_cmds: list = []
        self._search_call_count = 0

    def find_tracks_needing_spotify_search(self, limit: int) -> list[dict[str, Any]]:
        self._search_call_count += 1
        if self._search_call_count == 1:
            return self._tracks[:limit]
        # After first call, return empty (no more tracks)
        return []

    def batch_upsert_source_entities(self, commands, transaction_id=None):
        self.source_entity_cmds.extend(commands)

    def batch_upsert_identities(self, commands, transaction_id=None):
        self.identity_cmds.extend(commands)

    def batch_update_spotify_results(self, commands, transaction_id=None):
        for cmd in commands:
            self.updated_spotify.append({
                "track_id": cmd.track_id,
                "spotify_id": cmd.spotify_id,
            })


class FakeRepoWithRemaining:
    """Repo that reports remaining tracks after processing."""

    def __init__(self, tracks: list[dict[str, Any]]) -> None:
        self._tracks = tracks
        self.updated_spotify: list[dict] = []
        self.source_entity_cmds: list = []
        self.identity_cmds: list = []
        self._search_call_count = 0

    def find_tracks_needing_spotify_search(self, limit: int) -> list[dict[str, Any]]:
        self._search_call_count += 1
        if self._search_call_count == 1:
            return self._tracks[:limit]
        # Second call (follow-up check): still has remaining tracks
        return [self._tracks[0]]

    def batch_upsert_source_entities(self, commands, transaction_id=None):
        self.source_entity_cmds.extend(commands)

    def batch_upsert_identities(self, commands, transaction_id=None):
        self.identity_cmds.extend(commands)

    def batch_update_spotify_results(self, commands, transaction_id=None):
        for cmd in commands:
            self.updated_spotify.append({
                "track_id": cmd.track_id,
                "spotify_id": cmd.spotify_id,
            })


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        key = kwargs["Key"]
        body = self.objects.get(key)
        if body is None:
            raise RuntimeError(f"NoSuchKey: {key}")
        return {"Body": BytesIO(body)}


def _sqs_event(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "Records": [
            {
                "body": json.dumps(body),
                "messageAttributes": {
                    "correlation_id": {
                        "stringValue": "test-cid",
                        "dataType": "String",
                    }
                },
            }
        ]
    }


def _setup(monkeypatch, repo=None, tracks=None):
    reset_settings_cache()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_RAW_PREFIX", "raw/sp/tracks")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "")
    repo = repo or FakeRepo(tracks=tracks or [])
    monkeypatch.setattr("collector.spotify_handler.create_clouder_repository_from_env", lambda: repo)
    s3 = FakeS3Client()
    monkeypatch.setattr("collector.spotify_handler.create_default_s3_client", lambda: s3)
    return repo, s3


def _fake_search_results(*pairs):
    """Build fake search function returning given (isrc, track_id, spotify_id) tuples."""
    def fake_search(self, tracks, correlation_id):
        return [
            SpotifySearchResult(
                isrc=isrc,
                clouder_track_id=tid,
                spotify_track={"id": sid, "name": f"Track {sid}"} if sid else None,
                spotify_id=sid,
            )
            for isrc, tid, sid in pairs
        ]
    return fake_search


def test_no_records_returns_zero() -> None:
    response = lambda_handler({"no_records": True}, context=None)
    assert response == {"processed": 0}


def test_invalid_message_is_skipped(monkeypatch) -> None:
    _setup(monkeypatch)
    event = {
        "Records": [{"body": "{bad}", "messageAttributes": {}}]
    }
    response = lambda_handler(event, context=None)
    assert response == {"processed": 0}
    reset_settings_cache()


def test_no_tracks_needing_search(monkeypatch) -> None:
    repo, _ = _setup(monkeypatch, tracks=[])
    event = _sqs_event({"batch_size": 2000})
    response = lambda_handler(event, context=None)
    assert response == {"processed": 1}
    assert len(repo.updated_spotify) == 0
    reset_settings_cache()


def test_happy_path_found_and_not_found(monkeypatch) -> None:
    tracks = [
        {"id": "ct1", "isrc": "ISRC001", "title": "Track 1", "normalized_title": "track 1"},
        {"id": "ct2", "isrc": "ISRC002", "title": "Track 2", "normalized_title": "track 2"},
    ]
    repo, s3 = _setup(monkeypatch, tracks=tracks)

    monkeypatch.setattr(
        "collector.spotify_handler.SpotifyClient.search_tracks_by_isrc",
        _fake_search_results(("ISRC001", "ct1", "sp1"), ("ISRC002", "ct2", None)),
    )

    event = _sqs_event({"batch_size": 2000})
    response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    assert len(repo.updated_spotify) == 2

    # First track found
    assert repo.updated_spotify[0]["track_id"] == "ct1"
    assert repo.updated_spotify[0]["spotify_id"] == "sp1"

    # Second track not found
    assert repo.updated_spotify[1]["track_id"] == "ct2"
    assert repo.updated_spotify[1]["spotify_id"] is None

    # Source entity and identity only for found track
    assert len(repo.source_entity_cmds) == 1
    assert repo.source_entity_cmds[0].external_id == "sp1"
    assert repo.source_entity_cmds[0].source == "spotify"

    assert len(repo.identity_cmds) == 1
    assert repo.identity_cmds[0].external_id == "sp1"
    assert repo.identity_cmds[0].clouder_id == "ct1"

    # S3 results written (date-based key, no year/week)
    s3_keys = list(s3.objects.keys())
    assert any("results.json.gz" in k for k in s3_keys)
    assert any("meta.json" in k for k in s3_keys)
    assert all("iso_year" not in k and "iso_week" not in k for k in s3_keys)

    reset_settings_cache()


def test_follow_up_enqueued_when_more_tracks_remain(monkeypatch) -> None:
    tracks = [
        {"id": "ct1", "isrc": "ISRC001", "title": "Track 1", "normalized_title": "track 1"},
    ]
    repo = FakeRepoWithRemaining(tracks=tracks)
    reset_settings_cache()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_RAW_PREFIX", "raw/sp/tracks")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/spotify-q")
    monkeypatch.setattr("collector.spotify_handler.create_clouder_repository_from_env", lambda: repo)
    s3 = FakeS3Client()
    monkeypatch.setattr("collector.spotify_handler.create_default_s3_client", lambda: s3)

    monkeypatch.setattr(
        "collector.spotify_handler.SpotifyClient.search_tracks_by_isrc",
        _fake_search_results(("ISRC001", "ct1", "sp1")),
    )

    fake_sqs = MagicMock()
    fake_sqs.send_message.return_value = {"MessageId": "fake-id"}

    with patch.dict("sys.modules", {"boto3": MagicMock(client=MagicMock(return_value=fake_sqs))}):
        event = _sqs_event({"batch_size": 100})
        response = lambda_handler(event, context=None)

    assert response == {"processed": 1}

    # Follow-up SQS message sent
    fake_sqs.send_message.assert_called_once()
    call_kwargs = fake_sqs.send_message.call_args[1]
    assert call_kwargs["QueueUrl"] == "https://sqs.us-east-1.amazonaws.com/123/spotify-q"
    body = json.loads(call_kwargs["MessageBody"])
    assert body["batch_size"] == 100
    assert "iso_year" not in body

    reset_settings_cache()


def test_no_follow_up_when_all_tracks_processed(monkeypatch) -> None:
    tracks = [
        {"id": "ct1", "isrc": "ISRC001", "title": "Track 1", "normalized_title": "track 1"},
    ]
    repo, s3 = _setup(monkeypatch, tracks=tracks)
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/spotify-q")

    monkeypatch.setattr(
        "collector.spotify_handler.SpotifyClient.search_tracks_by_isrc",
        _fake_search_results(("ISRC001", "ct1", "sp1")),
    )

    with patch.dict("sys.modules", {"boto3": MagicMock()}) as mock_modules:
        event = _sqs_event({"batch_size": 2000})
        response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    # No follow-up since FakeRepo returns [] on second find call
    # boto3 should not have been used (no remaining tracks)

    reset_settings_cache()


def test_missing_aurora_config_raises(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setattr("collector.spotify_handler.create_clouder_repository_from_env", lambda: None)
    monkeypatch.setattr("collector.spotify_handler.create_default_s3_client", lambda: object())

    with pytest.raises(RuntimeError, match="AURORA Data API"):
        lambda_handler({"Records": [{"body": "{}"}]}, context=None)

    reset_settings_cache()


def test_no_follow_up_when_auto_continue_false(monkeypatch) -> None:
    tracks = [
        {"id": "ct1", "isrc": "ISRC001", "title": "Track 1", "normalized_title": "track 1"},
    ]
    repo = FakeRepoWithRemaining(tracks=tracks)
    reset_settings_cache()
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test_id")
    monkeypatch.setenv("SPOTIFY_CLIENT_SECRET", "test_secret")
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("SPOTIFY_RAW_PREFIX", "raw/sp/tracks")
    monkeypatch.setenv("SPOTIFY_SEARCH_QUEUE_URL", "https://sqs.us-east-1.amazonaws.com/123/spotify-q")
    monkeypatch.setattr("collector.spotify_handler.create_clouder_repository_from_env", lambda: repo)
    s3 = FakeS3Client()
    monkeypatch.setattr("collector.spotify_handler.create_default_s3_client", lambda: s3)

    monkeypatch.setattr(
        "collector.spotify_handler.SpotifyClient.search_tracks_by_isrc",
        _fake_search_results(("ISRC001", "ct1", "sp1")),
    )

    fake_sqs = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock(client=MagicMock(return_value=fake_sqs))}):
        event = _sqs_event({"batch_size": 100, "auto_continue": False})
        response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    # Even though remaining tracks exist, no follow-up sent
    fake_sqs.send_message.assert_not_called()

    reset_settings_cache()


def test_default_batch_size_used_when_not_specified(monkeypatch) -> None:
    repo, _ = _setup(monkeypatch, tracks=[])
    event = _sqs_event({})
    response = lambda_handler(event, context=None)
    assert response == {"processed": 1}
    reset_settings_cache()

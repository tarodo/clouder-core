"""Spotify rate limits: pace requests, and treat a long ban as a pause, not an error.

On 2026-10-10 three parallel workers made Spotify answer 429 with a five-hour
Retry-After; the worker raised, the errors alarm fired and the SQS retries hit
the ban again. A ban is now stored in the database: every invocation until it
ends leaves Spotify alone, and one delayed "resume" message carries the search
over the ban.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

import pytest

from collector.errors import SpotifyRateLimitedError, SpotifyUnavailableError
from collector.providers import registry
from collector.settings import reset_settings_cache
from collector.spotify_client import SpotifyClient
from collector.spotify_handler import lambda_handler

QUEUE = "https://sqs.us-east-1.amazonaws.com/000000000000/spotify-q"
TRACKS = [{"id": "ct1", "isrc": "ISRC001", "title": "T1", "normalized_title": "t1"}]


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _client(**kwargs) -> SpotifyClient:
    client = SpotifyClient(client_id="id", client_secret="secret", **kwargs)
    client._access_token = "tok"
    return client


def test_requests_are_spaced_by_the_minimum_interval(monkeypatch) -> None:
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response(b"{}"))
    client = _client(min_request_interval_s=0.5, sleep_fn=sleep, clock=lambda: now[0])

    client._request(url="https://api.spotify.com/v1/a", correlation_id="c")
    now[0] += 0.1  # the caller spends 0.1 s between requests
    client._request(url="https://api.spotify.com/v1/b", correlation_id="c")

    assert slept == [pytest.approx(0.4)]


def test_no_pacing_by_default(monkeypatch) -> None:
    slept: list[float] = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Response(b"{}"))
    client = _client(sleep_fn=slept.append)

    client._request(url="https://api.spotify.com/v1/a", correlation_id="c")
    client._request(url="https://api.spotify.com/v1/b", correlation_id="c")

    assert slept == []


def test_a_long_retry_after_raises_a_rate_limit_error_with_the_wait(monkeypatch) -> None:
    def banned(*a, **k):
        raise HTTPError("u", 429, "Too Many Requests", {"Retry-After": "18053"}, None)

    monkeypatch.setattr("urllib.request.urlopen", banned)

    with pytest.raises(SpotifyRateLimitedError) as info:
        _client(sleep_fn=lambda s: None)._request(url="https://api.spotify.com/v1/a", correlation_id="c")

    assert info.value.retry_after == 18053.0
    assert isinstance(info.value, SpotifyUnavailableError)  # existing handlers keep working


class PausableRepo:
    def __init__(self, blocked_until: datetime | None = None) -> None:
        self.blocked_until = blocked_until
        self.claims = 0
        self.released: list[Any] = []

    def get_vendor_blocked_until(self, vendor: str) -> datetime | None:
        assert vendor == "spotify"
        return self.blocked_until

    def set_vendor_blocked_until(self, vendor: str, until: datetime, now: datetime) -> None:
        assert vendor == "spotify"
        self.blocked_until = until

    def claim_tracks_for_spotify_search(self, limit, claimed_at):
        self.claims += 1
        return TRACKS[:limit]

    def find_tracks_needing_spotify_search(self, limit):
        return []

    def release_spotify_search_claim(self, claimed_at, now):
        self.released.append(claimed_at)
        return 1


def _setup(monkeypatch, repo: PausableRepo) -> MagicMock:
    reset_settings_cache()
    registry.reset_cache()
    for key, value in {"VENDORS_ENABLED": "spotify", "SPOTIFY_CLIENT_ID": "id",
                       "SPOTIFY_CLIENT_SECRET": "secret", "RAW_BUCKET_NAME": "b",
                       "SPOTIFY_RAW_PREFIX": "raw/sp/tracks", "SPOTIFY_SEARCH_QUEUE_URL": QUEUE}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr("collector.spotify_handler.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr("collector.spotify_handler.create_default_s3_client", lambda: MagicMock())
    return MagicMock()


def _event(body: dict[str, Any]) -> dict[str, Any]:
    return {"Records": [{"body": json.dumps(body),
                         "messageAttributes": {"correlation_id": {"stringValue": "cid", "dataType": "String"}}}]}


def _run(sqs: MagicMock, body: dict[str, Any]) -> dict[str, Any]:
    with patch.dict("sys.modules", {"boto3": MagicMock(client=MagicMock(return_value=sqs))}):
        return lambda_handler(_event(body), context=None)


def test_a_long_ban_pauses_the_search_instead_of_failing(monkeypatch) -> None:
    repo = PausableRepo()
    sqs = _setup(monkeypatch, repo)

    def banned(self, tracks, correlation_id, **kwargs):
        raise SpotifyRateLimitedError(retry_after=18053.0)

    monkeypatch.setattr("collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc", banned)
    before = datetime.now(timezone.utc)

    assert _run(sqs, {"batch_size": 100}) == {"processed": 1}  # no Lambda error, no alarm

    assert repo.blocked_until - before >= timedelta(seconds=18053)
    assert len(repo.released) == 1  # the claimed rows go back to the pool
    (call,) = sqs.send_message.call_args_list
    assert call.kwargs["DelaySeconds"] == 900  # SQS maximum; the chain re-arms until the ban ends
    assert json.loads(call.kwargs["MessageBody"])["resume"] is True


def test_while_paused_a_trigger_leaves_spotify_alone(monkeypatch) -> None:
    repo = PausableRepo(blocked_until=datetime.now(timezone.utc) + timedelta(hours=2))
    sqs = _setup(monkeypatch, repo)
    monkeypatch.setattr("collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc",
                        lambda *a, **k: pytest.fail("called Spotify during a ban"))

    assert _run(sqs, {"batch_size": 100}) == {"processed": 1}

    assert repo.claims == 0
    sqs.send_message.assert_not_called()  # only the resume chain re-arms


def test_while_paused_the_resume_message_re_arms_itself(monkeypatch) -> None:
    repo = PausableRepo(blocked_until=datetime.now(timezone.utc) + timedelta(seconds=300))
    sqs = _setup(monkeypatch, repo)

    _run(sqs, {"batch_size": 100, "resume": True})

    assert repo.claims == 0
    (call,) = sqs.send_message.call_args_list
    assert 290 <= call.kwargs["DelaySeconds"] <= 301  # lands just after the ban ends
    assert json.loads(call.kwargs["MessageBody"]) == {"batch_size": 100, "resume": True}


def test_after_the_ban_the_search_runs_again(monkeypatch) -> None:
    repo = PausableRepo(blocked_until=datetime.now(timezone.utc) - timedelta(seconds=1))
    sqs = _setup(monkeypatch, repo)
    monkeypatch.setattr("collector.providers.spotify.lookup.SpotifyLookup.lookup_batch_by_isrc",
                        lambda self, tracks, correlation_id, **k: [])
    monkeypatch.setattr("collector.spotify_handler.S3Storage.write_spotify_results",
                        lambda self, **k: ("key", None))

    _run(sqs, {"batch_size": 100, "resume": True})

    assert repo.claims == 1


def test_the_worker_client_is_paced_from_the_environment(monkeypatch) -> None:
    reset_settings_cache()
    registry.reset_cache()
    for key, value in {"VENDORS_ENABLED": "spotify", "SPOTIFY_CLIENT_ID": "id",
                       "SPOTIFY_CLIENT_SECRET": "secret", "RAW_BUCKET_NAME": "b",
                       "SPOTIFY_MIN_REQUEST_INTERVAL_MS": "650"}.items():
        monkeypatch.setenv(key, value)

    assert registry.get_lookup("spotify")._client.min_request_interval_s == pytest.approx(0.65)
    registry.reset_cache()

"""Tests for SQS worker lambda: message parsing, error classification, happy path."""

from __future__ import annotations

import gzip
import json
from io import BytesIO
from typing import Any

import pytest

from collector.errors import StorageError
from collector.settings import reset_settings_cache
from collector.worker_handler import lambda_handler


class FakeRepo:
    """Minimal repo mock supporting both worker lifecycle AND canonicalization."""

    def __init__(self) -> None:
        self.completed_runs: list[str] = []
        self.failed_runs: list[tuple[str, str]] = []
        self.identities: dict = {}

    # ── worker lifecycle ──

    def set_run_completed(self, run_id: str, processed_count: int, finished_at) -> None:
        del processed_count, finished_at
        self.completed_runs.append(run_id)

    def set_run_failed(self, run_id: str, error_code: str, error_message: str, finished_at) -> None:
        del error_message, finished_at
        self.failed_runs.append((run_id, error_code))

    # ── canonicalization stubs ──

    def batch_upsert_source_entities(self, commands, transaction_id=None):
        pass

    def batch_upsert_source_relations(self, commands, transaction_id=None):
        pass

    def find_identity(self, source, entity_type, external_id):
        return self.identities.get((source, entity_type, external_id))

    def batch_upsert_identities(self, commands, transaction_id=None):
        pass

    def create_label(self, label_id, name, normalized_name, at, transaction_id=None):
        pass

    def create_artist(self, artist_id, name, normalized_name, at, transaction_id=None):
        pass

    def create_album(self, album_id, title, normalized_title, release_date, label_id, at, transaction_id=None):
        pass

    def create_track(self, cmd, transaction_id=None):
        pass

    def conservative_update_track(self, cmd, transaction_id=None):
        pass

    def batch_upsert_track_artists(self, commands, transaction_id=None):
        pass

    class _FakeTransaction:
        def __enter__(self):
            return "tx"
        def __exit__(self, *args):
            pass

    def transaction(self):
        return self._FakeTransaction()


class FakeS3Client:
    def __init__(self, data: list[dict[str, Any]] | None = None, fail: bool = False) -> None:
        self._data = data or []
        self._fail = fail

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        if self._fail:
            raise RuntimeError("S3 down")
        compressed = gzip.compress(json.dumps(self._data).encode("utf-8"))
        return {"Body": BytesIO(compressed)}


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


def _setup_worker(monkeypatch, repo=None, s3_data=None, s3_fail=False):
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")
    repo = repo or FakeRepo()
    monkeypatch.setattr("collector.worker_handler.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(
        "collector.worker_handler.create_default_s3_client",
        lambda: FakeS3Client(data=s3_data, fail=s3_fail),
    )
    return repo


def test_invalid_sqs_json_payload_is_skipped(monkeypatch) -> None:
    _setup_worker(monkeypatch)

    event = {
        "Records": [
            {
                "body": "{bad-json}",
                "messageAttributes": {},
            }
        ]
    }

    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()


def test_no_records_returns_zero(monkeypatch) -> None:
    _setup_worker(monkeypatch)

    response = lambda_handler({"Records": []}, context=None)

    assert response == {"processed": 0}
    reset_settings_cache()


def test_non_list_records_returns_zero() -> None:
    response = lambda_handler({"no_records": True}, context=None)

    assert response == {"processed": 0}


def test_happy_path_processes_tracks(monkeypatch) -> None:
    raw_tracks = [
        {
            "id": 1,
            "name": "Test Track",
            "mix_name": "Original Mix",
            "isrc": "ISRC001",
            "bpm": 128,
            "length_ms": 300000,
            "publish_date": "2026-01-01",
            "artists": [{"id": 100, "name": "Artist A"}],
            "release": {
                "id": 9001,
                "name": "Album A",
                "label": {"id": 500, "name": "Label A"},
            },
        }
    ]
    repo = _setup_worker(monkeypatch, s3_data=raw_tracks)

    event = _sqs_event({
        "run_id": "run-42",
        "source": "beatport",
        "s3_key": "raw/bp/releases/style_id=5/year=2026/week=09/releases.json.gz",
    })
    response = lambda_handler(event, context=None)

    assert response == {"processed": 1}
    assert "run-42" in repo.completed_runs
    reset_settings_cache()


def test_permanent_error_does_not_reraise(monkeypatch) -> None:
    """StorageError (permanent) should NOT re-raise → SQS deletes the message."""
    repo = _setup_worker(monkeypatch, s3_fail=True)

    event = _sqs_event({
        "run_id": "run-fail",
        "source": "beatport",
        "s3_key": "raw/missing-key",
    })

    # Should NOT raise — permanent errors are swallowed
    response = lambda_handler(event, context=None)

    assert response == {"processed": 0}
    assert len(repo.failed_runs) == 1
    run_id, error_code = repo.failed_runs[0]
    assert run_id == "run-fail"
    assert error_code == "canonicalization_permanent_failure"
    reset_settings_cache()


def test_transient_error_reraises_for_sqs_retry(monkeypatch) -> None:
    """RuntimeError (transient) should re-raise → SQS retries the message."""
    raw_tracks = [{"id": 1, "name": "T", "artists": [{"id": 1, "name": "A"}],
                   "release": {"id": 1, "name": "R", "label": {"id": 1, "name": "L"}}}]
    repo = _setup_worker(monkeypatch, s3_data=raw_tracks)

    # Make the canonicalizer's DB call fail with a transient error
    def exploding_set_run_completed(run_id, processed_count, finished_at):
        raise RuntimeError("DB connection lost")

    repo.set_run_completed = exploding_set_run_completed

    event = _sqs_event({
        "run_id": "run-transient",
        "source": "beatport",
        "s3_key": "raw/key",
    })

    with pytest.raises(RuntimeError, match="DB connection lost"):
        lambda_handler(event, context=None)

    reset_settings_cache()


def test_missing_aurora_config_raises(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")
    monkeypatch.setattr("collector.worker_handler.create_clouder_repository_from_env", lambda: None)
    monkeypatch.setattr("collector.worker_handler.create_default_s3_client", lambda: object())

    with pytest.raises(RuntimeError, match="AURORA Data API"):
        lambda_handler({"Records": [{"body": "{}"}]}, context=None)

    reset_settings_cache()

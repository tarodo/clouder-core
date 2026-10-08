"""Tests for SQS worker lambda: message parsing, error classification, happy path."""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pytest

from collector.settings import reset_settings_cache
from collector.worker_handler import lambda_handler


class FakeRepo:
    """Minimal repo mock supporting both worker lifecycle AND canonicalization."""

    def __init__(self) -> None:
        self.completed_runs: list[str] = []
        self.failed_runs: list[tuple[str, str]] = []
        self.identities: dict = {}
        self.source_commands: list = []
        self.run_started_at: str | None = "2026-10-01 10:00:00.250"

    # ── worker lifecycle ──

    def set_run_completed(self, run_id: str, processed_count: int, finished_at) -> None:
        del processed_count, finished_at
        self.completed_runs.append(run_id)

    def set_run_failed(
        self, run_id: str, error_code: str, error_message: str, finished_at,
        phase: str | None = None,
    ) -> None:
        del error_message, finished_at, phase
        self.failed_runs.append((run_id, error_code))

    # ── canonicalization stubs ──

    def get_run(self, run_id):
        if not self.run_started_at:
            return None
        return {"run_id": run_id, "started_at": self.run_started_at}

    def batch_upsert_source_entities(self, commands, transaction_id=None):
        self.source_commands.extend(commands)

    def batch_upsert_source_relations(self, commands, transaction_id=None):
        pass

    def batch_upsert_identities(self, commands, transaction_id=None):
        pass

    def claim_identities(self, commands, transaction_id=None):
        for cmd in commands:
            self.identities.setdefault(
                (cmd.source, cmd.entity_type, cmd.external_id), cmd.clouder_id
            )

    def read_track_state(self, external_ids, *, run_id, observed_at, transaction_id=None):
        return {}

    def find_identities(self, source, entity_type, external_ids, transaction_id=None):
        return {
            ext: self.identities[(source, entity_type, ext)]
            for ext in external_ids
            if (source, entity_type, ext) in self.identities
        }

    def batch_create_labels(self, commands, transaction_id=None):
        pass

    def batch_create_styles(self, commands, transaction_id=None):
        pass

    def batch_create_artists(self, commands, transaction_id=None):
        pass

    def batch_create_albums(self, commands, transaction_id=None):
        pass

    def batch_create_tracks(self, commands, transaction_id=None):
        pass

    def batch_conservative_update_tracks(self, commands, transaction_id=None):
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
    def __init__(
        self,
        data: list[dict[str, Any]] | None = None,
        fail: bool = False,
        fail_put: bool = False,
    ) -> None:
        self._data = data or []
        self._fail = fail
        self._fail_put = fail_put
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        if self._fail_put:
            raise RuntimeError("S3 write down")
        self.puts.append(kwargs)
        return {}

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


def _setup_worker(monkeypatch, repo=None, s3_data=None, s3_fail=False, s3_put_fail=False):
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")
    repo = repo or FakeRepo()
    s3 = FakeS3Client(data=s3_data, fail=s3_fail, fail_put=s3_put_fail)
    repo.s3 = s3
    monkeypatch.setattr(
        "collector.worker_handler.create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr("collector.worker_handler.create_default_s3_client", lambda: s3)
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


def _happy_s3_data() -> list[dict[str, Any]]:
    return [
        {
            "id": 1,
            "name": "Test Track",
            "mix_name": "Original Mix",
            "isrc": "ISRC001",
            "bpm": 128,
            "length_ms": 300000,
            "publish_date": "2026-01-01",
            "artists": [{"id": 100, "name": "Artist A"}],
            "genre": {"id": 1, "name": "House"},
            "release": {
                "id": 9001,
                "name": "Album A",
                "label": {"id": 500, "name": "Label A"},
            },
        }
    ]


def _happy_event() -> dict[str, Any]:
    return _sqs_event(
        {
            "run_id": "run-42",
            "source": "beatport",
            "s3_key": "raw/bp/releases/style_id=5/year=2026/week=09/releases.json.gz",
        }
    )


def test_happy_path_processes_tracks(monkeypatch) -> None:
    repo = _setup_worker(monkeypatch, s3_data=_happy_s3_data())

    response = lambda_handler(_happy_event(), context=None)

    assert response == {"processed": 1}
    assert "run-42" in repo.completed_runs
    reset_settings_cache()


def test_permanent_error_does_not_reraise(monkeypatch) -> None:
    """StorageError (permanent) should NOT re-raise → SQS deletes the message."""
    repo = _setup_worker(monkeypatch, s3_fail=True)

    event = _sqs_event(
        {
            "run_id": "run-fail",
            "source": "beatport",
            "s3_key": "raw/missing-key",
        }
    )

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
    raw_tracks = [
        {
            "id": 1,
            "name": "T",
            "artists": [{"id": 1, "name": "A"}],
            "release": {"id": 1, "name": "R", "label": {"id": 1, "name": "L"}},
        }
    ]
    repo = _setup_worker(monkeypatch, s3_data=raw_tracks)

    # Make the canonicalizer's DB call fail with a transient error
    def exploding_set_run_completed(run_id, processed_count, finished_at):
        raise RuntimeError("DB connection lost")

    repo.set_run_completed = exploding_set_run_completed

    event = _sqs_event(
        {
            "run_id": "run-transient",
            "source": "beatport",
            "s3_key": "raw/key",
        }
    )

    with pytest.raises(RuntimeError, match="DB connection lost"):
        lambda_handler(event, context=None)

    reset_settings_cache()


def test_missing_aurora_config_raises(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")
    monkeypatch.setattr(
        "collector.worker_handler.create_clouder_repository_from_env", lambda: None
    )
    monkeypatch.setattr(
        "collector.worker_handler.create_default_s3_client", lambda: object()
    )

    with pytest.raises(RuntimeError, match="AURORA Data API"):
        lambda_handler({"Records": [{"body": "{}"}]}, context=None)

    reset_settings_cache()


def test_worker_stamps_sources_with_the_run_start(monkeypatch) -> None:
    repo = _setup_worker(monkeypatch, s3_data=_happy_s3_data())

    lambda_handler(_happy_event(), None)

    stamps = {cmd.observed_at for cmd in repo.source_commands}
    assert stamps == {datetime(2026, 10, 1, 10, 0, 0, 250000, tzinfo=timezone.utc)}
    reset_settings_cache()


def test_worker_falls_back_to_now_without_a_run_row(monkeypatch) -> None:
    repo = FakeRepo()
    repo.run_started_at = None
    _setup_worker(monkeypatch, repo=repo, s3_data=_happy_s3_data())

    assert lambda_handler(_happy_event(), None) == {"processed": 1}
    reset_settings_cache()


def test_worker_quarantines_records_it_cannot_canonicalize(monkeypatch) -> None:
    repo = _setup_worker(monkeypatch, s3_data=_happy_s3_data() + [{"id": 2, "name": ""}])

    assert lambda_handler(_happy_event(), None) == {"processed": 1}

    assert [p["Key"] for p in repo.s3.puts] == [
        "raw/bp/releases/_quarantine/run_id=run-42/records.json.gz"
    ]
    reset_settings_cache()


def test_worker_logs_contract_drift(monkeypatch) -> None:
    data = _happy_s3_data()
    data[0]["is_new"] = True
    events: list = []
    monkeypatch.setattr(
        "collector.contracts.log_event",
        lambda level, message, **fields: events.append((message, fields)),
    )
    _setup_worker(monkeypatch, s3_data=data)

    lambda_handler(_happy_event(), None)

    drift = [fields for message, fields in events if message == "contract_drift"]
    assert drift and "is_new" in drift[0]["unknown_fields"].split(",")
    reset_settings_cache()


def test_quarantine_write_failure_fails_the_run(monkeypatch) -> None:
    repo = _setup_worker(
        monkeypatch, s3_data=_happy_s3_data() + [{"id": 2, "name": ""}], s3_put_fail=True
    )

    with pytest.raises(RuntimeError):
        lambda_handler(_happy_event(), None)

    assert repo.failed_runs == [("run-42", "canonicalization_transient_failure")]
    reset_settings_cache()


def test_transient_storage_error_reraises_for_sqs_retry(monkeypatch) -> None:
    """A throttled or unavailable S3 read must be retried, not fail the run for good."""
    from collector.errors import TransientStorageError
    from collector.storage import S3Storage

    repo = _setup_worker(monkeypatch)

    def throttled(self, key):
        raise TransientStorageError("S3 SlowDown")

    monkeypatch.setattr(S3Storage, "read_releases", throttled)
    event = _sqs_event({"run_id": "run-throttled", "source": "beatport", "s3_key": "raw/k"})

    with pytest.raises(TransientStorageError):
        lambda_handler(event, context=None)
    assert repo.failed_runs[0] == ("run-throttled", "canonicalization_transient_failure")
    reset_settings_cache()

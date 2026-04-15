"""Verify phase-level failure handling in canonicalization worker."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sqs_event() -> dict:
    return {
        "Records": [
            {
                "body": json.dumps({"run_id": "r1", "s3_key": "raw/r1.json.gz"}),
                "messageAttributes": {
                    "correlation_id": {"stringValue": "corr-1", "dataType": "String"}
                },
            }
        ]
    }


def _patch_worker_deps(monkeypatch, *, normalize_side_effect=None, canonicalizer=None,
                       read_releases_return=None):
    from collector.settings import reset_settings_cache

    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")

    repo = MagicMock()
    storage = MagicMock()
    storage.read_releases.return_value = read_releases_return or [{"id": 1}]

    monkeypatch.setattr(
        "collector.worker_handler.create_clouder_repository_from_env",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.worker_handler.S3Storage", lambda **kw: storage
    )
    monkeypatch.setattr(
        "collector.worker_handler.create_default_s3_client", lambda: object()
    )

    if normalize_side_effect is not None:
        monkeypatch.setattr(
            "collector.worker_handler.normalize_tracks",
            normalize_side_effect,
        )
    if canonicalizer is not None:
        monkeypatch.setattr(
            "collector.worker_handler.Canonicalizer", lambda _repo: canonicalizer
        )
    return repo


def test_normalize_phase_failure_records_phase(sqs_event, monkeypatch):
    def boom(_): raise ValueError("bad data")
    repo = _patch_worker_deps(monkeypatch, normalize_side_effect=boom)

    from collector import worker_handler
    result = worker_handler.lambda_handler(sqs_event, None)
    assert result == {"processed": 0}

    repo.set_run_failed.assert_called_once()
    kwargs = repo.set_run_failed.call_args.kwargs
    assert kwargs["run_id"] == "r1"
    assert kwargs.get("phase") == "normalize"
    assert kwargs["error_code"] == "canonicalization_permanent_failure"


def test_canonicalize_phase_failure_records_phase(sqs_event, monkeypatch):
    def ok_normalize(_):
        return MagicMock(
            tracks=[], artists=[], labels=[], albums=[], relations=[], styles=[]
        )
    canonicalizer = MagicMock()
    canonicalizer.process_run.side_effect = RuntimeError("db down")
    repo = _patch_worker_deps(
        monkeypatch,
        normalize_side_effect=ok_normalize,
        canonicalizer=canonicalizer,
    )

    from collector import worker_handler
    with pytest.raises(RuntimeError):
        worker_handler.lambda_handler(sqs_event, None)

    kwargs = repo.set_run_failed.call_args.kwargs
    assert kwargs.get("phase") == "canonicalize"
    assert kwargs["error_code"] == "canonicalization_transient_failure"


def test_read_s3_phase_failure_records_phase(sqs_event, monkeypatch):
    from collector.errors import StorageError
    from collector.settings import reset_settings_cache

    reset_settings_cache()
    monkeypatch.setenv("RAW_BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("RAW_PREFIX", "raw/bp/releases")

    repo = MagicMock()
    storage = MagicMock()
    storage.read_releases.side_effect = StorageError("s3 down")

    monkeypatch.setattr(
        "collector.worker_handler.create_clouder_repository_from_env",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.worker_handler.S3Storage", lambda **kw: storage
    )
    monkeypatch.setattr(
        "collector.worker_handler.create_default_s3_client", lambda: object()
    )

    from collector import worker_handler
    worker_handler.lambda_handler(sqs_event, None)

    kwargs = repo.set_run_failed.call_args.kwargs
    assert kwargs.get("phase") == "read_s3"


def test_message_truncated_but_phase_preserved(sqs_event, monkeypatch):
    long_msg = "x" * 5000

    def boom(_):
        raise ValueError(long_msg)

    repo = _patch_worker_deps(monkeypatch, normalize_side_effect=boom)

    from collector import worker_handler

    worker_handler.lambda_handler(sqs_event, None)

    kwargs = repo.set_run_failed.call_args.kwargs
    assert kwargs["phase"] == "normalize"


def test_phase_prefix_stripped_from_api_response():
    from collector.handler import _split_phase_prefix

    phase, msg = _split_phase_prefix("[phase=normalize] boom")
    assert phase == "normalize"
    assert msg == "boom"


def test_no_phase_prefix_returns_none():
    from collector.handler import _split_phase_prefix

    phase, msg = _split_phase_prefix("boom")
    assert phase is None
    assert msg == "boom"


def test_empty_message_returns_none():
    from collector.handler import _split_phase_prefix

    phase, msg = _split_phase_prefix(None)
    assert phase is None
    assert msg is None

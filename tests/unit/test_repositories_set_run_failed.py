"""Unit tests for set_run_failed phase prefix and truncation."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from collector.repositories import ClouderRepository


def _make_repo() -> tuple[ClouderRepository, MagicMock]:
    data_api = MagicMock()
    repo = ClouderRepository(data_api=data_api)
    return repo, data_api


def _params_from_call(data_api: MagicMock) -> dict:
    call = data_api.execute.call_args
    if len(call.args) >= 2:
        return call.args[1]
    return call.kwargs.get("params") or call.kwargs


def test_set_run_failed_prepends_phase():
    repo, data_api = _make_repo()
    repo.set_run_failed(
        run_id="r1",
        error_code="e",
        error_message="boom",
        finished_at=datetime.now(timezone.utc),
        phase="normalize",
    )
    params = _params_from_call(data_api)
    assert params["error_message"].startswith("[phase=normalize] ")
    assert params["error_message"].endswith("boom")


def test_set_run_failed_truncates_long_message_keeping_prefix():
    repo, data_api = _make_repo()
    repo.set_run_failed(
        run_id="r1",
        error_code="e",
        error_message="x" * 5000,
        finished_at=datetime.now(timezone.utc),
        phase="canonicalize",
    )
    params = _params_from_call(data_api)
    msg = params["error_message"]
    assert msg.startswith("[phase=canonicalize] ")
    assert len(msg) <= 2000


def test_set_run_failed_without_phase_unchanged():
    repo, data_api = _make_repo()
    repo.set_run_failed(
        run_id="r1",
        error_code="e",
        error_message="boom",
        finished_at=datetime.now(timezone.utc),
    )
    params = _params_from_call(data_api)
    assert params["error_message"] == "boom"

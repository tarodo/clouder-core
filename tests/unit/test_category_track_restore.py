"""POST /categories/{id}/tracks restoring a removed row in place (undo)."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

from collector.curation import NotFoundError
from collector.curation.routes_categories import _handle_add_track

NOW = datetime(2026, 10, 12, 18, 0, tzinfo=UTC)


def _event(body: dict) -> dict:
    return {
        "routeKey": "POST /categories/{id}/tracks",
        "pathParameters": {"id": "cat-1"},
        "body": json.dumps(body),
    }


def _repo(owns_block: bool = True) -> MagicMock:
    repo = MagicMock()
    repo.add_track.return_value = ({"added_at": "x", "source_triage_block_id": None}, True)
    repo.owns_triage_block.return_value = owns_block
    return repo


def _call(body: dict, repo: MagicMock):
    with (
        patch("collector.curation.routes_categories.utc_now", return_value=NOW),
        patch("collector.curation.routes_categories.try_dispatch_for_track"),
        patch("collector.curation.routes_categories.try_dispatch_artists_for_track"),
    ):
        return _handle_add_track(_event(body), repo, "u1", "corr")


def test_plain_add_stamps_now_without_source() -> None:
    repo = _repo()
    _call({"track_id": "t1"}, repo)
    kw = repo.add_track.call_args.kwargs
    assert kw["now"] == NOW
    assert kw["source_triage_block_id"] is None
    repo.owns_triage_block.assert_not_called()


def test_restore_keeps_original_added_at_and_source() -> None:
    repo = _repo()
    # The list returns added_at as the Data API string (UTC, no zone).
    _call(
        {"track_id": "t1", "added_at": "2026-10-02 10:15:00.5", "source_triage_block_id": "blk-1"},
        repo,
    )
    kw = repo.add_track.call_args.kwargs
    assert kw["now"] == datetime(2026, 10, 2, 10, 15, 0, 500000, tzinfo=UTC)
    assert kw["source_triage_block_id"] == "blk-1"
    repo.owns_triage_block.assert_called_once_with(user_id="u1", block_id="blk-1")


def test_restore_clamps_a_future_added_at_to_now() -> None:
    repo = _repo()
    _call({"track_id": "t1", "added_at": "2030-01-01T00:00:00Z"}, repo)
    assert repo.add_track.call_args.kwargs["now"] == NOW


def test_restore_rejects_someone_elses_triage_block() -> None:
    repo = _repo(owns_block=False)
    with pytest.raises(NotFoundError) as exc:
        _call({"track_id": "t1", "source_triage_block_id": "blk-x"}, repo)
    assert exc.value.error_code == "triage_block_not_found"
    repo.add_track.assert_not_called()


def test_restore_rejects_a_malformed_added_at() -> None:
    with pytest.raises(PydanticValidationError):
        _call({"track_id": "t1", "added_at": "yesterday"}, _repo())

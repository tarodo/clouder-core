"""Handler parses ?fresh=1/0 and threads it into repo.list_tracks."""
from __future__ import annotations
from unittest.mock import MagicMock
from collector.curation_handler import _handle_list_tracks
from collector.curation import PaginatedResult


def _make_event(fresh: str | None) -> dict:
    qp: dict[str, str] = {}
    if fresh is not None:
        qp["fresh"] = fresh
    return {
        "pathParameters": {"id": "cat-1"},
        "queryStringParameters": qp,
    }


def _fake_repo():
    repo = MagicMock()
    repo.list_tracks.return_value = PaginatedResult(items=[], total=0, limit=50, offset=0)
    return repo


def test_handler_fresh_1_passes_true(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event("1"), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is True


def test_handler_fresh_0_passes_false(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event("0"), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is False


def test_handler_fresh_absent_passes_false(monkeypatch):
    repo = _fake_repo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    _handle_list_tracks(_make_event(None), repo, "u-1", "corr-1")
    assert repo.list_tracks.call_args.kwargs["fresh"] is False

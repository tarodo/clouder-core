"""Repository tests for vendor_match_map + match_review_queue (Plan 4 Task 5)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

from collector.repositories import (
    ClouderRepository,
    UpsertVendorMatchCmd,
    VendorTrackMatch,
)


def _make_repo() -> tuple[ClouderRepository, MagicMock]:
    data_api = MagicMock()
    repo = ClouderRepository(data_api=data_api)
    return repo, data_api


def test_get_vendor_match_miss_returns_none() -> None:
    repo, data_api = _make_repo()
    data_api.execute.return_value = []

    result = repo.get_vendor_match("track-1", "spotify")

    assert result is None
    call = data_api.execute.call_args
    sql = call.args[0]
    params = call.args[1]
    assert "FROM vendor_track_map" in sql
    assert params == {"clouder_track_id": "track-1", "vendor": "spotify"}


def test_get_vendor_match_hit_builds_dataclass() -> None:
    repo, data_api = _make_repo()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    data_api.execute.return_value = [
        {
            "vendor_track_id": "sp123",
            "match_type": "isrc",
            "confidence": "1.000",
            "matched_at": now.isoformat(),
            "payload": {"a": 1},
        }
    ]

    result = repo.get_vendor_match("track-1", "spotify")

    assert isinstance(result, VendorTrackMatch)
    assert result.vendor_track_id == "sp123"
    assert result.match_type == "isrc"
    assert result.confidence == Decimal("1.000")
    assert result.matched_at == now
    assert result.payload == {"a": 1}


def test_upsert_vendor_match_writes_expected_sql_and_params() -> None:
    repo, data_api = _make_repo()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    cmd = UpsertVendorMatchCmd(
        clouder_track_id="track-1",
        vendor="spotify",
        vendor_track_id="sp123",
        match_type="isrc",
        confidence=Decimal("1.000"),
        matched_at=now,
        payload={"a": 1},
    )

    repo.upsert_vendor_match(cmd)

    call = data_api.execute.call_args
    sql = call.args[0]
    params = call.args[1]
    assert "INSERT INTO vendor_track_map" in sql
    assert "ON CONFLICT (clouder_track_id, vendor) DO UPDATE" in sql
    assert params["clouder_track_id"] == "track-1"
    assert params["vendor"] == "spotify"
    assert params["vendor_track_id"] == "sp123"
    assert params["match_type"] == "isrc"
    assert params["confidence"] == Decimal("1.000")
    assert params["matched_at"] == now
    assert params["payload"] == {"a": 1}


def test_insert_review_candidate_writes_pending_row() -> None:
    repo, data_api = _make_repo()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)

    repo.insert_review_candidate(
        review_id="rev-1",
        clouder_track_id="track-1",
        vendor="ytmusic",
        candidates=[{"score": 0.8}],
        created_at=now,
    )

    call = data_api.execute.call_args
    sql = call.args[0]
    params = call.args[1]
    assert "INSERT INTO match_review_queue" in sql
    assert "'pending'" in sql
    assert params == {
        "id": "rev-1",
        "clouder_track_id": "track-1",
        "vendor": "ytmusic",
        "candidates": [{"score": 0.8}],
        "created_at": now,
    }


def test_upsert_vendor_match_forwards_transaction_id() -> None:
    repo, data_api = _make_repo()
    now = datetime(2026, 4, 21, 12, 0, tzinfo=timezone.utc)
    cmd = UpsertVendorMatchCmd(
        clouder_track_id="track-1",
        vendor="spotify",
        vendor_track_id="sp123",
        match_type="isrc",
        confidence=Decimal("1.000"),
        matched_at=now,
        payload={},
    )

    repo.upsert_vendor_match(cmd, transaction_id="tx-1")

    assert data_api.execute.call_args.kwargs == {"transaction_id": "tx-1"}

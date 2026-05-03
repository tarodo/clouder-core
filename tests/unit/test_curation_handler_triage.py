"""Unit tests for `collector.curation_handler` (spec-D triage routes).

The spec-C handler surface is exercised end-to-end by
`tests/integration/test_curation_handler.py`. This module focuses on
the spec-D handlers and the cross-cutting helpers added alongside them.
"""

from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from collector import curation_handler
from collector.curation import (
    InactiveBucketError,
    InactiveStagingFinalizeError,
    InvalidStateError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
)
from collector.curation.triage_repository import (
    BucketTrackRowOut,
    FinalizeResult,
    MoveResult,
    TransferResult,
    TriageBlockRow,
    TriageBlockSummaryRow,
    TriageBucketRow,
)


# ---------- Helpers ---------------------------------------------------------


def _event(
    *,
    method: str,
    route: str,
    user_id: str = "u1",
    path_params: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    correlation_id: str = "cid-unit-1",
) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-unit",
            "routeKey": f"{method} {route}",
            "authorizer": {
                "lambda": {
                    "user_id": user_id,
                    "session_id": "s",
                    "is_admin": False,
                }
            },
        },
        "headers": {"x-correlation-id": correlation_id},
        "pathParameters": dict(path_params) if path_params else None,
        "queryStringParameters": dict(query) if query else None,
        "body": json.dumps(body) if body is not None else None,
    }


def _read(resp: dict) -> tuple[int, dict]:
    return resp["statusCode"], json.loads(resp["body"])


@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-unit-1")


# ---------- Route registration ---------------------------------------------


def test_create_triage_block_route_registered() -> None:
    assert "POST /triage/blocks" in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE["POST /triage/blocks"]
    assert handler is curation_handler._create_triage_block
    # The factory wraps `create_default_triage_repository`; calling it must
    # delegate so monkeypatching the module attribute swaps the repo source.
    assert factory is curation_handler._triage_factory


# ---------- Handler invocation ---------------------------------------------


def _fake_block_row() -> TriageBlockRow:
    return TriageBlockRow(
        id="11111111-1111-1111-1111-111111111111",
        user_id="u1",
        style_id="22222222-2222-2222-2222-222222222222",
        style_name="House",
        name="Week 17",
        date_from="2026-04-20",
        date_to="2026-04-26",
        status="IN_PROGRESS",
        created_at="2026-04-28T12:00:00+00:00",
        updated_at="2026-04-28T12:00:00+00:00",
        finalized_at=None,
        buckets=(
            TriageBucketRow(
                id="b-new",
                bucket_type="NEW",
                category_id=None,
                category_name=None,
                inactive=False,
                track_count=42,
            ),
            TriageBucketRow(
                id="b-stg",
                bucket_type="STAGING",
                category_id="cat-1",
                category_name="Tech House",
                inactive=False,
                track_count=0,
            ),
        ),
    )


def test_create_triage_block_invokes_repo(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}

    fake_row = _fake_block_row()

    class FakeTriageRepo:
        def create_block(
            self, *, user_id, style_id, name, date_from, date_to
        ):
            captured.update(
                user_id=user_id,
                style_id=style_id,
                name=name,
                date_from=date_from,
                date_to=date_to,
            )
            return fake_row

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeTriageRepo(),
    )

    style_id = "22222222-2222-2222-2222-222222222222"
    body = {
        "style_id": style_id,
        "name": "Week 17",
        "date_from": "2026-04-20",
        "date_to": "2026-04-26",
    }
    resp = curation_handler.lambda_handler(
        _event(method="POST", route="/triage/blocks", body=body), context
    )
    status, payload = _read(resp)

    assert status == 201
    assert payload["id"] == fake_row.id
    assert payload["style_id"] == style_id
    assert payload["style_name"] == "House"
    assert payload["name"] == "Week 17"
    assert payload["date_from"] == "2026-04-20"
    assert payload["date_to"] == "2026-04-26"
    assert payload["status"] == "IN_PROGRESS"
    assert payload["finalized_at"] is None
    assert payload["correlation_id"] == "cid-unit-1"
    assert len(payload["buckets"]) == 2
    assert payload["buckets"][0] == {
        "id": "b-new",
        "bucket_type": "NEW",
        "category_id": None,
        "category_name": None,
        "inactive": False,
        "track_count": 42,
    }
    assert payload["buckets"][1]["category_name"] == "Tech House"

    # Repo received the parsed pydantic schema args.
    assert captured["user_id"] == "u1"
    assert captured["style_id"] == style_id
    assert captured["name"] == "Week 17"
    assert captured["date_from"] == date(2026, 4, 20)
    assert captured["date_to"] == date(2026, 4, 26)


def test_create_triage_block_returns_503_when_db_not_configured(
    monkeypatch, context
) -> None:
    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: None,
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": "22222222-2222-2222-2222-222222222222",
                "name": "Week 17",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 503
    assert payload["error_code"] == "db_not_configured"


def test_create_triage_block_validation_error_on_bad_dates(
    monkeypatch, context
) -> None:
    # Don't even hit the repo; pydantic should reject date_to < date_from.
    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: object(),  # repo never invoked
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": "22222222-2222-2222-2222-222222222222",
                "name": "Week 17",
                "date_from": "2026-04-26",
                "date_to": "2026-04-20",
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "validation_error"


# ---------- Error envelope mapping for new triage error types --------------


def test_inactive_staging_error_attaches_inactive_buckets(
    monkeypatch, context
) -> None:
    inactive = [
        {"id": "buck-1", "category_id": "cat-1", "track_count": 3},
        {"id": "buck-2", "category_id": "cat-2", "track_count": 1},
    ]

    class RaisingRepo:
        def create_block(self, **_kw):
            raise InactiveStagingFinalizeError(
                "2 inactive staging bucket(s) hold tracks", inactive
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: RaisingRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": "22222222-2222-2222-2222-222222222222",
                "name": "W",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 409
    assert payload["error_code"] == "inactive_buckets_have_tracks"
    assert payload["inactive_buckets"] == inactive
    assert payload["correlation_id"] == "cid-unit-1"


def test_tracks_not_in_source_error_attaches_payload(
    monkeypatch, context
) -> None:
    missing = ["t-aaa", "t-bbb"]

    class RaisingRepo:
        def create_block(self, **_kw):
            raise TracksNotInSourceError(
                "2 track(s) not present in source bucket", missing
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: RaisingRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": "22222222-2222-2222-2222-222222222222",
                "name": "W",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "tracks_not_in_source"
    assert payload["not_in_source"] == missing


# ---------- T18: list/detail/bucket-tracks read routes ----------------------


def _fake_summary_row(block_id: str = "blk-1") -> TriageBlockSummaryRow:
    return TriageBlockSummaryRow(
        id=block_id,
        user_id="u1",
        style_id="22222222-2222-2222-2222-222222222222",
        style_name="House",
        name="Week 17",
        date_from="2026-04-20",
        date_to="2026-04-26",
        status="IN_PROGRESS",
        created_at="2026-04-28T12:00:00+00:00",
        updated_at="2026-04-28T12:00:00+00:00",
        finalized_at=None,
        track_count=7,
    )


def _fake_bucket_track_row(track_id: str = "trk-1") -> BucketTrackRowOut:
    return BucketTrackRowOut(
        track_id=track_id,
        title="Mover",
        mix_name="Original Mix",
        isrc="GBABC1234567",
        bpm=128,
        length_ms=360000,
        publish_date="2026-04-22",
        spotify_release_date="2026-04-22",
        spotify_id="spot-1",
        release_type="single",
        is_ai_suspected=False,
        artists=("Alice", "Bob"),
        label_name="Anjunadeep",
        added_at="2026-04-28T12:05:00+00:00",
    )


# Route registration ---------------------------------------------------------


def test_list_blocks_by_style_route_registered() -> None:
    key = "GET /styles/{style_id}/triage/blocks"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._list_triage_blocks_by_style
    assert factory is curation_handler._triage_factory


def test_list_blocks_all_route_registered() -> None:
    key = "GET /triage/blocks"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._list_triage_blocks_all
    assert factory is curation_handler._triage_factory


def test_get_triage_block_route_registered() -> None:
    key = "GET /triage/blocks/{id}"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._get_triage_block
    assert factory is curation_handler._triage_factory


def test_list_bucket_tracks_route_registered() -> None:
    key = "GET /triage/blocks/{id}/buckets/{bucket_id}/tracks"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._list_bucket_tracks
    assert factory is curation_handler._triage_factory


# Happy paths ----------------------------------------------------------------


def test_list_blocks_by_style_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    rows = [_fake_summary_row("blk-1"), _fake_summary_row("blk-2")]

    class FakeRepo:
        def list_blocks_by_style(
            self, *, user_id, style_id, limit, offset, status
        ):
            captured.update(
                user_id=user_id,
                style_id=style_id,
                limit=limit,
                offset=offset,
                status=status,
            )
            return rows, 12

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    style_id = "22222222-2222-2222-2222-222222222222"
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/triage/blocks",
            path_params={"style_id": style_id},
            query={"limit": "10", "offset": "0", "status": "IN_PROGRESS"},
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload["total"] == 12
    assert payload["limit"] == 10
    assert payload["offset"] == 0
    assert payload["correlation_id"] == "cid-unit-1"
    assert len(payload["items"]) == 2
    item = payload["items"][0]
    assert item["id"] == "blk-1"
    assert item["style_id"] == style_id
    assert item["style_name"] == "House"
    assert item["track_count"] == 7
    assert item["status"] == "IN_PROGRESS"
    assert "buckets" not in item  # summary form, not detail

    assert captured == {
        "user_id": "u1",
        "style_id": style_id,
        "limit": 10,
        "offset": 0,
        "status": "IN_PROGRESS",
    }


def test_list_blocks_all_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    rows = [_fake_summary_row("blk-9")]

    class FakeRepo:
        def list_blocks_all(self, *, user_id, limit, offset, status):
            captured.update(
                user_id=user_id, limit=limit, offset=offset, status=status,
            )
            return rows, 1

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(method="GET", route="/triage/blocks"),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload["total"] == 1
    assert payload["limit"] == 50  # default
    assert payload["offset"] == 0
    assert len(payload["items"]) == 1
    assert payload["items"][0]["id"] == "blk-9"
    # No status filter passed.
    assert captured["status"] is None
    assert captured["limit"] == 50


def test_get_triage_block_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    fake = _fake_block_row()

    class FakeRepo:
        def get_block(self, *, user_id, block_id):
            captured.update(user_id=user_id, block_id=block_id)
            return fake

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks/{id}",
            path_params={"id": fake.id},
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload["id"] == fake.id
    assert payload["style_name"] == "House"
    assert len(payload["buckets"]) == 2
    assert payload["correlation_id"] == "cid-unit-1"
    assert captured == {"user_id": "u1", "block_id": fake.id}


def test_get_triage_block_returns_404_when_missing(
    monkeypatch, context
) -> None:
    class FakeRepo:
        def get_block(self, *, user_id, block_id):
            return None

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks/{id}",
            path_params={"id": "missing-id"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 404
    assert payload["error_code"] == "triage_block_not_found"


def test_list_bucket_tracks_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    rows = [
        _fake_bucket_track_row("trk-1"),
        _fake_bucket_track_row("trk-2"),
    ]

    class FakeRepo:
        def list_bucket_tracks(
            self, *, user_id, block_id, bucket_id, limit, offset, search
        ):
            captured.update(
                user_id=user_id,
                block_id=block_id,
                bucket_id=bucket_id,
                limit=limit,
                offset=offset,
                search=search,
            )
            return rows, 5

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks/{id}/buckets/{bucket_id}/tracks",
            path_params={"id": "blk-1", "bucket_id": "buck-1"},
            query={"limit": "20", "offset": "5", "search": "mover"},
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload["total"] == 5
    assert payload["limit"] == 20
    assert payload["offset"] == 5
    assert len(payload["items"]) == 2
    item = payload["items"][0]
    assert item["track_id"] == "trk-1"
    assert item["title"] == "Mover"
    assert item["isrc"] == "GBABC1234567"
    assert item["bpm"] == 128
    assert item["release_type"] == "single"
    assert item["is_ai_suspected"] is False
    assert item["artists"] == ["Alice", "Bob"]
    assert item["label_name"] == "Anjunadeep"
    assert item["added_at"] == "2026-04-28T12:05:00+00:00"

    assert captured == {
        "user_id": "u1",
        "block_id": "blk-1",
        "bucket_id": "buck-1",
        "limit": 20,
        "offset": 5,
        "search": "mover",
    }


# Validation -----------------------------------------------------------------


def test_list_blocks_rejects_bad_limit(monkeypatch, context) -> None:
    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: object(),  # repo never invoked
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks",
            query={"limit": "0"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "validation_error"


def test_list_blocks_rejects_bad_offset(monkeypatch, context) -> None:
    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: object(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks",
            query={"offset": "-1"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "validation_error"


def test_list_blocks_rejects_unknown_status(monkeypatch, context) -> None:
    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: object(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks",
            query={"status": "DRAFT"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "validation_error"


# ---------- T19: move + transfer mutating routes ----------------------------


def _uuid(suffix: str) -> str:
    """Pad a short tag to a 36-char UUID-shaped string for schema validation."""

    base = "00000000-0000-0000-0000-"
    rest = (suffix + "0" * 12)[:12]
    return base + rest


def test_move_tracks_route_registered() -> None:
    key = "POST /triage/blocks/{id}/move"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._move_tracks
    assert factory is curation_handler._triage_factory


def test_transfer_tracks_route_registered() -> None:
    key = "POST /triage/blocks/{src_id}/transfer"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._transfer_tracks
    assert factory is curation_handler._triage_factory


def test_move_tracks_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    from_id = _uuid("from")
    to_id = _uuid("to")
    track_ids = [_uuid("trk1"), _uuid("trk2")]

    class FakeRepo:
        def move_tracks(
            self, *, user_id, block_id, from_bucket_id, to_bucket_id, track_ids
        ):
            captured.update(
                user_id=user_id,
                block_id=block_id,
                from_bucket_id=from_bucket_id,
                to_bucket_id=to_bucket_id,
                track_ids=list(track_ids),
            )
            return MoveResult(moved=2)

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/move",
            path_params={"id": "blk-1"},
            body={
                "from_bucket_id": from_id,
                "to_bucket_id": to_id,
                "track_ids": track_ids,
            },
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload == {
        "moved": 2,
        "correlation_id": "cid-unit-1",
    }
    assert captured == {
        "user_id": "u1",
        "block_id": "blk-1",
        "from_bucket_id": from_id,
        "to_bucket_id": to_id,
        "track_ids": track_ids,
    }


def test_move_tracks_inactive_bucket_returns_422(
    monkeypatch, context
) -> None:
    class FakeRepo:
        def move_tracks(self, **_kw):
            raise InactiveBucketError(
                "target bucket is inactive (its category was soft-deleted)"
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/move",
            path_params={"id": "blk-1"},
            body={
                "from_bucket_id": _uuid("from"),
                "to_bucket_id": _uuid("to"),
                "track_ids": [_uuid("trk1")],
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "target_bucket_inactive"
    assert payload["correlation_id"] == "cid-unit-1"


def test_move_tracks_invalid_state_returns_422(monkeypatch, context) -> None:
    class FakeRepo:
        def move_tracks(self, **_kw):
            raise InvalidStateError(
                "triage block is not editable (status != IN_PROGRESS)"
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/move",
            path_params={"id": "blk-1"},
            body={
                "from_bucket_id": _uuid("from"),
                "to_bucket_id": _uuid("to"),
                "track_ids": [_uuid("trk1")],
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "invalid_state"


def test_transfer_tracks_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    target_id = _uuid("tgt")
    track_ids = [_uuid("trk1"), _uuid("trk2"), _uuid("trk3")]

    class FakeRepo:
        def transfer_tracks(
            self, *, user_id, src_block_id, target_bucket_id, track_ids
        ):
            captured.update(
                user_id=user_id,
                src_block_id=src_block_id,
                target_bucket_id=target_bucket_id,
                track_ids=list(track_ids),
            )
            return TransferResult(transferred=3)

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{src_id}/transfer",
            path_params={"src_id": "blk-src"},
            body={
                "target_bucket_id": target_id,
                "track_ids": track_ids,
            },
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload == {
        "transferred": 3,
        "correlation_id": "cid-unit-1",
    }
    assert captured == {
        "user_id": "u1",
        "src_block_id": "blk-src",
        "target_bucket_id": target_id,
        "track_ids": track_ids,
    }


def test_transfer_tracks_style_mismatch_returns_422(
    monkeypatch, context
) -> None:
    class FakeRepo:
        def transfer_tracks(self, **_kw):
            raise StyleMismatchError(
                "source and target triage blocks belong to different styles"
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{src_id}/transfer",
            path_params={"src_id": "blk-src"},
            body={
                "target_bucket_id": _uuid("tgt"),
                "track_ids": [_uuid("trk1")],
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "target_block_style_mismatch"


def test_transfer_tracks_not_in_source_returns_422(
    monkeypatch, context
) -> None:
    missing = ["trk-x", "trk-y"]

    class FakeRepo:
        def transfer_tracks(self, **_kw):
            raise TracksNotInSourceError(
                "2 track(s) not present in source block", missing
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{src_id}/transfer",
            path_params={"src_id": "blk-src"},
            body={
                "target_bucket_id": _uuid("tgt"),
                "track_ids": [_uuid("trk1")],
            },
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 422
    assert payload["error_code"] == "tracks_not_in_source"
    assert payload["not_in_source"] == missing


# ---------- T20: finalize + soft-delete routes -----------------------------


def test_finalize_triage_block_route_registered() -> None:
    key = "POST /triage/blocks/{id}/finalize"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._finalize_triage_block
    assert factory is curation_handler._triage_factory


def test_soft_delete_triage_block_route_registered() -> None:
    key = "DELETE /triage/blocks/{id}"
    assert key in curation_handler._ROUTE_TABLE
    handler, factory = curation_handler._ROUTE_TABLE[key]
    assert handler is curation_handler._soft_delete_triage_block
    assert factory is curation_handler._triage_factory


def test_finalize_triage_block_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}
    fake_block = _fake_block_row()
    promoted = {"cat-1": 5, "cat-2": 3}

    sentinel_cat_repo = object()

    class FakeRepo:
        def finalize_block(
            self, *, user_id, block_id, categories_repository
        ):
            captured.update(
                user_id=user_id,
                block_id=block_id,
                categories_repository=categories_repository,
            )
            return FinalizeResult(block=fake_block, promoted=promoted)

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    monkeypatch.setattr(
        curation_handler,
        "create_default_categories_repository",
        lambda: sentinel_cat_repo,
    )

    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/finalize",
            path_params={"id": fake_block.id},
        ),
        context,
    )
    status, payload = _read(resp)

    assert status == 200
    assert payload["promoted"] == promoted
    assert payload["correlation_id"] == "cid-unit-1"
    block_payload = payload["block"]
    assert block_payload["id"] == fake_block.id
    assert block_payload["style_name"] == "House"
    assert len(block_payload["buckets"]) == 2

    # Repo received the categories repo instance from the categories factory.
    assert captured["user_id"] == "u1"
    assert captured["block_id"] == fake_block.id
    assert captured["categories_repository"] is sentinel_cat_repo


def test_finalize_triage_block_inactive_buckets_returns_409(
    monkeypatch, context
) -> None:
    inactive = [
        {"id": "buck-1", "category_id": "cat-1", "track_count": 4},
    ]

    class FakeRepo:
        def finalize_block(self, **_kw):
            raise InactiveStagingFinalizeError(
                "1 inactive staging bucket(s) hold tracks", inactive
            )

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    monkeypatch.setattr(
        curation_handler,
        "create_default_categories_repository",
        lambda: object(),
    )

    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/finalize",
            path_params={"id": "blk-1"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 409
    assert payload["error_code"] == "inactive_buckets_have_tracks"
    assert payload["inactive_buckets"] == inactive
    assert payload["correlation_id"] == "cid-unit-1"


def test_finalize_triage_block_returns_503_when_categories_factory_none(
    monkeypatch, context
) -> None:
    class FakeRepo:
        def finalize_block(self, **_kw):  # pragma: no cover - unreachable
            raise AssertionError("repo.finalize_block should not be invoked")

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    monkeypatch.setattr(
        curation_handler,
        "create_default_categories_repository",
        lambda: None,
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/finalize",
            path_params={"id": "blk-1"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 503
    assert payload["error_code"] == "db_not_configured"


def test_soft_delete_triage_block_happy_path(monkeypatch, context) -> None:
    captured: dict[str, Any] = {}

    class FakeRepo:
        def soft_delete_block(self, *, user_id, block_id):
            captured.update(user_id=user_id, block_id=block_id)
            return True

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="DELETE",
            route="/triage/blocks/{id}",
            path_params={"id": "blk-1"},
        ),
        context,
    )

    assert resp["statusCode"] == 204
    assert resp["body"] == ""
    assert resp["headers"]["x-correlation-id"] == "cid-unit-1"
    assert captured == {"user_id": "u1", "block_id": "blk-1"}


def test_soft_delete_triage_block_returns_404_when_missing(
    monkeypatch, context
) -> None:
    class FakeRepo:
        def soft_delete_block(self, *, user_id, block_id):
            return False

    monkeypatch.setattr(
        curation_handler,
        "create_default_triage_repository",
        lambda: FakeRepo(),
    )
    resp = curation_handler.lambda_handler(
        _event(
            method="DELETE",
            route="/triage/blocks/{id}",
            path_params={"id": "missing-id"},
        ),
        context,
    )
    status, payload = _read(resp)
    assert status == 404
    assert payload["error_code"] == "triage_block_not_found"

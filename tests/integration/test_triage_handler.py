"""Integration tests for spec-D triage handler.

Adapted from the original real-Postgres plan (T21-T23) to the FakeRepo
pattern already established in `test_curation_handler.py`. We do not have
a `psycopg`-backed Aurora fixture in this repo; the existing convention
is to monkeypatch the repository factory with an in-memory fake.

Coverage:
  - Route dispatcher -> handler -> repo contract for every spec-D route.
  - JSON request/response shape.
  - Error envelope serialization, including the structured payloads on
    `InactiveStagingFinalizeError.inactive_buckets` and
    `TracksNotInSourceError.not_in_source`.
  - Cross-spec D7/D8 hand-off: spec-C category create/soft-delete must
    invoke `TriageRepository.snapshot_category_into_active_blocks` /
    `mark_staging_inactive_for_category`. We patch those methods on the
    real `TriageRepository` class (the call site instantiates one
    against the same `data_api` inside `CategoriesRepository`) and assert
    they fire.

SQL-level R4 classification + source-filter (Plan §6.1) is *not*
verified here -- those are already covered by:
  - T8 unit test `test_create_block_classify_sql_includes_filters_and_case`
    (asserts SQL string content).
  - T6 unit tests for `classify_bucket_type` (Python mirror of the CASE).
A future task ("T28 - real-DB integration tests") could add psycopg-backed
end-to-end verification.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from collector.curation import (
    InactiveStagingFinalizeError,
    NotFoundError,
    StyleMismatchError,
    TracksNotInSourceError,
)
from collector.curation.triage_repository import (
    FinalizeResult,
    MoveResult,
    TransferResult,
    TriageBlockRow,
    TriageBlockSummaryRow,
    TriageBucketRow,
)
from collector.curation.triage_service import (
    BUCKET_TYPE_DISCARD,
    BUCKET_TYPE_NEW,
    BUCKET_TYPE_NOT,
    BUCKET_TYPE_OLD,
    BUCKET_TYPE_UNCLASSIFIED,
    TECHNICAL_BUCKET_TYPES,
)
from collector.curation_handler import lambda_handler


# ---------- Fake triage repository ------------------------------------------


class FakeTriageRepo:
    """In-memory TriageRepository for handler-level integration tests."""

    def __init__(self) -> None:
        # block_id -> dict
        self.blocks: dict[str, dict] = {}
        # bucket_id -> dict (with parent_block_id, bucket_type, ...)
        self.buckets: dict[str, dict] = {}
        # (bucket_id, track_id) -> True
        self.bucket_tracks: dict[tuple[str, str], bool] = {}
        # style_id -> name
        self.styles: dict[str, str] = {
            # 36-char UUID-shaped style ids to satisfy schema.
            "11111111-1111-1111-1111-111111111111": "House",
            "22222222-2222-2222-2222-222222222222": "Techno",
        }
        # Tracking spies for cross-spec D7/D8.
        self.snapshot_calls: list[dict] = []
        self.inactive_calls: list[dict] = []
        # Toggleable error-injection for negative tests.
        self.move_error: Exception | None = None
        self.transfer_error: Exception | None = None
        self.finalize_error: Exception | None = None

    # ---- helpers -----------------------------------------------------

    def _block_to_row(self, b: dict) -> TriageBlockRow:
        bucket_rows = []
        for bk_id, bk in self.buckets.items():
            if bk["block_id"] != b["id"]:
                continue
            bucket_rows.append(
                TriageBucketRow(
                    id=bk_id,
                    bucket_type=bk["bucket_type"],
                    category_id=bk.get("category_id"),
                    category_name=bk.get("category_name"),
                    inactive=bk.get("inactive", False),
                    track_count=sum(
                        1 for (b_id, _t) in self.bucket_tracks
                        if b_id == bk_id
                    ),
                )
            )
        return TriageBlockRow(
            id=b["id"],
            user_id=b["user_id"],
            style_id=b["style_id"],
            style_name=self.styles[b["style_id"]],
            name=b["name"],
            date_from=str(b["date_from"]),
            date_to=str(b["date_to"]),
            status=b["status"],
            created_at=b["created_at"],
            updated_at=b["updated_at"],
            finalized_at=b.get("finalized_at"),
            buckets=tuple(bucket_rows),
        )

    def _block_to_summary(self, b: dict) -> TriageBlockSummaryRow:
        track_count = sum(
            1 for (bid, _t) in self.bucket_tracks
            if self.buckets[bid]["block_id"] == b["id"]
        )
        return TriageBlockSummaryRow(
            id=b["id"],
            user_id=b["user_id"],
            style_id=b["style_id"],
            style_name=self.styles[b["style_id"]],
            name=b["name"],
            date_from=str(b["date_from"]),
            date_to=str(b["date_to"]),
            status=b["status"],
            created_at=b["created_at"],
            updated_at=b["updated_at"],
            finalized_at=b.get("finalized_at"),
            track_count=track_count,
        )

    # ---- writes ------------------------------------------------------

    def create_block(
        self, *, user_id: str, style_id: str, name: str,
        date_from: date, date_to: date,
    ) -> TriageBlockRow:
        if style_id not in self.styles:
            raise NotFoundError(
                "style_not_found",
                f"clouder_styles row not found: {style_id}",
            )
        now = datetime.now(timezone.utc).isoformat()
        block_id = str(uuid4())
        self.blocks[block_id] = {
            "id": block_id,
            "user_id": user_id,
            "style_id": style_id,
            "name": name,
            "date_from": date_from,
            "date_to": date_to,
            "status": "IN_PROGRESS",
            "created_at": now,
            "updated_at": now,
            "finalized_at": None,
            "deleted_at": None,
        }
        # Insert the 5 technical buckets.
        for btype in TECHNICAL_BUCKET_TYPES:
            bk_id = str(uuid4())
            self.buckets[bk_id] = {
                "block_id": block_id,
                "bucket_type": btype,
                "category_id": None,
                "category_name": None,
                "inactive": False,
            }
        return self._block_to_row(self.blocks[block_id])

    def get_block(self, *, user_id, block_id):
        b = self.blocks.get(block_id)
        if (
            b is None
            or b["user_id"] != user_id
            or b.get("deleted_at") is not None
        ):
            return None
        return self._block_to_row(b)

    def list_blocks_by_style(
        self, *, user_id, style_id, limit, offset, status=None,
    ):
        if style_id not in self.styles:
            raise NotFoundError(
                "style_not_found",
                f"clouder_styles row not found: {style_id}",
            )
        items = [
            self._block_to_summary(b)
            for b in self.blocks.values()
            if b["user_id"] == user_id
            and b["style_id"] == style_id
            and b.get("deleted_at") is None
            and (status is None or b["status"] == status)
        ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        return items[offset:offset + limit], total

    def list_blocks_all(
        self, *, user_id, limit, offset, status=None,
    ):
        items = [
            self._block_to_summary(b)
            for b in self.blocks.values()
            if b["user_id"] == user_id
            and b.get("deleted_at") is None
            and (status is None or b["status"] == status)
        ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        return items[offset:offset + limit], total

    def list_bucket_tracks(
        self, *, user_id, block_id, bucket_id, limit, offset, search=None,
    ):
        b = self.blocks.get(block_id)
        if (
            b is None
            or b["user_id"] != user_id
            or b.get("deleted_at") is not None
        ):
            raise NotFoundError(
                "bucket_not_in_block",
                f"bucket {bucket_id} not found in triage block {block_id}",
            )
        bk = self.buckets.get(bucket_id)
        if bk is None or bk["block_id"] != block_id:
            raise NotFoundError(
                "bucket_not_in_block",
                f"bucket {bucket_id} not found in triage block {block_id}",
            )
        # Empty payload is fine for these tests; concrete rows are not
        # exercised here.
        return [], 0

    def move_tracks(
        self, *, user_id, block_id, from_bucket_id, to_bucket_id, track_ids,
    ):
        if self.move_error is not None:
            raise self.move_error
        return MoveResult(moved=len(track_ids))

    def transfer_tracks(
        self, *, user_id, src_block_id, target_bucket_id, track_ids,
    ):
        if self.transfer_error is not None:
            raise self.transfer_error
        return TransferResult(transferred=len(track_ids))

    def finalize_block(
        self, *, user_id, block_id, categories_repository,
    ):
        if self.finalize_error is not None:
            raise self.finalize_error
        b = self.blocks.get(block_id)
        if (
            b is None
            or b["user_id"] != user_id
            or b.get("deleted_at") is not None
        ):
            raise NotFoundError(
                "triage_block_not_found",
                f"triage block not found: {block_id}",
            )
        b["status"] = "FINALIZED"
        b["finalized_at"] = datetime.now(timezone.utc).isoformat()
        return FinalizeResult(
            block=self._block_to_row(b),
            promoted={"cat-1": 3},
        )

    def soft_delete_block(self, *, user_id, block_id):
        b = self.blocks.get(block_id)
        if (
            b is None
            or b["user_id"] != user_id
            or b.get("deleted_at") is not None
        ):
            return False
        b["deleted_at"] = datetime.now(timezone.utc).isoformat()
        return True

    # ---- spec-D D7/D8 cross-spec hooks (instance methods) -----------

    def snapshot_category_into_active_blocks(
        self, *, user_id, style_id, category_id, transaction_id=None,
    ):
        self.snapshot_calls.append({
            "user_id": user_id,
            "style_id": style_id,
            "category_id": category_id,
            "transaction_id": transaction_id,
        })
        return 0

    def mark_staging_inactive_for_category(
        self, *, user_id, category_id, transaction_id=None,
    ):
        self.inactive_calls.append({
            "user_id": user_id,
            "category_id": category_id,
            "transaction_id": transaction_id,
        })
        return 0


# ---------- Test helpers ----------------------------------------------------


@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-1")


@pytest.fixture
def fake_triage_repo(monkeypatch) -> FakeTriageRepo:
    repo = FakeTriageRepo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_triage_repository",
        lambda: repo,
    )
    return repo


def _event(
    *,
    method: str,
    route: str,
    user_id: str = "u1",
    is_admin: bool = False,
    path_params: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    correlation_id: str = "cid-1",
) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-1",
            "routeKey": f"{method} {route}",
            "authorizer": {
                "lambda": {
                    "user_id": user_id,
                    "session_id": "s",
                    "is_admin": is_admin,
                }
            },
        },
        "headers": {"x-correlation-id": correlation_id},
        "pathParameters": dict(path_params) if path_params else None,
        "queryStringParameters": dict(query) if query else None,
        "body": json.dumps(body, default=str) if body is not None else None,
    }


def _read(resp: dict) -> tuple[int, dict]:
    return resp["statusCode"], json.loads(resp["body"])


# Common ids used in handler tests.
STYLE_HOUSE = "11111111-1111-1111-1111-111111111111"
STYLE_TECHNO = "22222222-2222-2222-2222-222222222222"


def _create_block(
    repo: FakeTriageRepo,
    *,
    user_id: str = "u1",
    style_id: str = STYLE_HOUSE,
    name: str = "Tech House W17",
) -> str:
    row = repo.create_block(
        user_id=user_id,
        style_id=style_id,
        name=name,
        date_from=date(2026, 4, 20),
        date_to=date(2026, 4, 26),
    )
    return row.id


# ---------- Auth + routing smoke -------------------------------------------


def test_unauthorized_401(fake_triage_repo, context):
    event = _event(method="GET", route="/triage/blocks/{id}",
                   path_params={"id": "x"})
    event["requestContext"].pop("authorizer", None)
    resp = lambda_handler(event, context)
    status, body = _read(resp)
    assert status == 401
    assert body["error_code"] == "unauthorized"


# ---------- POST /triage/blocks --------------------------------------------


def test_create_triage_block_201(fake_triage_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": STYLE_HOUSE,
                "name": "Tech House W17",
                "date_from": "2026-04-20",
                "date_to": "2026-04-26",
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["status"] == "IN_PROGRESS"
    assert body["style_id"] == STYLE_HOUSE
    assert body["style_name"] == "House"
    assert body["correlation_id"] == "cid-1"
    # All five technical bucket types must be present.
    bucket_types = {b["bucket_type"] for b in body["buckets"]}
    assert bucket_types == {
        BUCKET_TYPE_NEW, BUCKET_TYPE_OLD, BUCKET_TYPE_NOT,
        BUCKET_TYPE_DISCARD, BUCKET_TYPE_UNCLASSIFIED,
    }


def test_create_triage_block_validation_422(fake_triage_repo, context):
    # date_to < date_from -> Pydantic model validator raises.
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks",
            body={
                "style_id": STYLE_HOUSE,
                "name": "Bad",
                "date_from": "2026-04-26",
                "date_to": "2026-04-20",
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "validation_error"


# ---------- GET /triage/blocks/{id} ----------------------------------------


def test_get_triage_block_404(fake_triage_repo, context):
    resp = lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks/{id}",
            path_params={"id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "triage_block_not_found"


# ---------- GET /triage/blocks (list) ---------------------------------------


def test_list_triage_blocks_paginated(fake_triage_repo, context):
    for i in range(60):
        _create_block(fake_triage_repo, name=f"W{i:02}")
    resp = lambda_handler(
        _event(method="GET", route="/triage/blocks"),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 60
    assert len(body["items"]) == 50  # default limit
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_triage_blocks_status_filter(fake_triage_repo, context):
    bid_a = _create_block(fake_triage_repo, name="A")
    bid_b = _create_block(fake_triage_repo, name="B")
    # Finalize one so we can filter.
    fake_triage_repo.finalize_block(
        user_id="u1", block_id=bid_b, categories_repository=None,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks",
            query={"status": "FINALIZED"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["status"] == "FINALIZED"
    assert body["items"][0]["id"] == bid_b


# ---------- POST /triage/blocks/{id}/move ----------------------------------


def test_move_tracks_happy(fake_triage_repo, context):
    bid = _create_block(fake_triage_repo)
    bucket_ids = [
        bk_id for bk_id, bk in fake_triage_repo.buckets.items()
        if bk["block_id"] == bid
    ]
    from_id, to_id = bucket_ids[0], bucket_ids[1]
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/move",
            path_params={"id": bid},
            body={
                "from_bucket_id": from_id,
                "to_bucket_id": to_id,
                "track_ids": [
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                ],
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["moved"] == 2
    assert body["correlation_id"] == "cid-1"


def test_move_tracks_not_in_source_422(fake_triage_repo, context):
    bid = _create_block(fake_triage_repo)
    bucket_ids = [
        bk_id for bk_id, bk in fake_triage_repo.buckets.items()
        if bk["block_id"] == bid
    ]
    missing = ["cccccccc-cccc-cccc-cccc-cccccccccccc"]
    fake_triage_repo.move_error = TracksNotInSourceError(
        "1 track(s) not present in source bucket", missing,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/move",
            path_params={"id": bid},
            body={
                "from_bucket_id": bucket_ids[0],
                "to_bucket_id": bucket_ids[1],
                "track_ids": missing,
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "tracks_not_in_source"
    assert body["not_in_source"] == missing


# ---------- POST /triage/blocks/{src_id}/transfer --------------------------


def test_transfer_tracks_happy(fake_triage_repo, context):
    src_id = _create_block(fake_triage_repo, name="src")
    tgt_id = _create_block(fake_triage_repo, name="tgt")
    target_bucket_id = next(
        bk_id for bk_id, bk in fake_triage_repo.buckets.items()
        if bk["block_id"] == tgt_id
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{src_id}/transfer",
            path_params={"src_id": src_id},
            body={
                "target_bucket_id": target_bucket_id,
                "track_ids": [
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                ],
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["transferred"] == 1


def test_transfer_tracks_style_mismatch_422(fake_triage_repo, context):
    src_id = _create_block(fake_triage_repo)
    tgt_id = _create_block(fake_triage_repo, style_id=STYLE_TECHNO)
    target_bucket_id = next(
        bk_id for bk_id, bk in fake_triage_repo.buckets.items()
        if bk["block_id"] == tgt_id
    )
    fake_triage_repo.transfer_error = StyleMismatchError(
        "source and target triage blocks belong to different styles"
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{src_id}/transfer",
            path_params={"src_id": src_id},
            body={
                "target_bucket_id": target_bucket_id,
                "track_ids": [
                    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                ],
            },
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "target_block_style_mismatch"


# ---------- POST /triage/blocks/{id}/finalize ------------------------------


def test_finalize_block_happy(fake_triage_repo, context, monkeypatch):
    bid = _create_block(fake_triage_repo)
    # finalize handler also requires the categories_repo factory; satisfy
    # it with a MagicMock so the flow reaches the triage repo.
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: MagicMock(),
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/finalize",
            path_params={"id": bid},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["block"]["status"] == "FINALIZED"
    assert body["block"]["finalized_at"] is not None
    assert body["promoted"] == {"cat-1": 3}


def test_finalize_block_inactive_staging_409(
    fake_triage_repo, context, monkeypatch,
):
    bid = _create_block(fake_triage_repo)
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: MagicMock(),
    )
    inactive_payload = [
        {"id": "bk-1", "category_id": "cat-1", "track_count": 5},
    ]
    fake_triage_repo.finalize_error = InactiveStagingFinalizeError(
        "1 inactive staging bucket(s) hold tracks", inactive_payload,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/triage/blocks/{id}/finalize",
            path_params={"id": bid},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409
    assert body["error_code"] == "inactive_buckets_have_tracks"
    assert body["inactive_buckets"] == inactive_payload


# ---------- DELETE /triage/blocks/{id} -------------------------------------


def test_soft_delete_block_204(fake_triage_repo, context):
    bid = _create_block(fake_triage_repo)
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/triage/blocks/{id}",
            path_params={"id": bid},
        ),
        context,
    )
    assert resp["statusCode"] == 204
    assert resp["body"] in ("", "null")


def test_soft_delete_block_404(fake_triage_repo, context):
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/triage/blocks/{id}",
            path_params={"id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "triage_block_not_found"


# ---------- Tenancy isolation ----------------------------------------------


def test_tenancy_isolation(fake_triage_repo, context):
    # User A creates a block.
    bid = _create_block(fake_triage_repo, user_id="user-a")
    # User B tries to read it -> 404 (not 403 -- we do not leak existence).
    resp = lambda_handler(
        _event(
            method="GET",
            route="/triage/blocks/{id}",
            path_params={"id": bid},
            user_id="user-b",
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "triage_block_not_found"


# ---------- Cross-spec D7: category create -> snapshot ---------------------


def test_create_category_triggers_snapshot(monkeypatch, context):
    """Spec-D D7 hand-off: POST /styles/{id}/categories must invoke
    `TriageRepository.snapshot_category_into_active_blocks` inside the
    same TX as the INSERT. We patch the method on the real class so it
    fires regardless of which `data_api` the categories repo built.
    """

    snapshot_calls: list[dict] = []

    def fake_snapshot(self, **kwargs):
        snapshot_calls.append(kwargs)
        return 1

    from collector.curation.triage_repository import TriageRepository
    monkeypatch.setattr(
        TriageRepository,
        "snapshot_category_into_active_blocks",
        fake_snapshot,
    )

    # Build a CategoriesRepository with a MagicMock data_api that returns
    # plausible rows for the create flow.
    from collector.curation.categories_repository import CategoriesRepository

    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-d7"
    data_api.transaction.return_value.__exit__.return_value = False
    data_api.execute.side_effect = [
        # 1: style lookup
        [{"id": STYLE_HOUSE, "name": "House"}],
        # 2: max_pos
        [{"max_pos": -1}],
        # 3: INSERT RETURNING category row
        [
            {
                "id": "cat-new",
                "user_id": "u1",
                "style_id": STYLE_HOUSE,
                "style_name": "House",
                "name": "Tech House",
                "normalized_name": "tech house",
                "position": 0,
                "track_count": 0,
                "created_at": "2026-04-28T00:00:00+00:00",
                "updated_at": "2026-04-28T00:00:00+00:00",
            }
        ],
    ]
    repo = CategoriesRepository(data_api=data_api)

    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: repo,
    )
    # Triage factory is gated separately but is not exercised by the
    # category-create handler -- we still stub it so the gate passes.
    monkeypatch.setattr(
        "collector.curation_handler.create_default_triage_repository",
        lambda: MagicMock(),
    )

    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": STYLE_HOUSE},
            body={"name": "Tech House"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 201
    assert len(snapshot_calls) == 1
    call = snapshot_calls[0]
    assert call["user_id"] == "u1"
    assert call["style_id"] == STYLE_HOUSE
    assert call["category_id"] == "cat-new"
    assert call["transaction_id"] == "tx-d7"


# ---------- Cross-spec D8: category soft-delete -> mark inactive -----------


def test_soft_delete_category_triggers_inactive_mark(monkeypatch, context):
    """Spec-D D8 hand-off: DELETE /categories/{id} must invoke
    `TriageRepository.mark_staging_inactive_for_category` inside the same
    TX as the soft-delete UPDATE.
    """
    inactive_calls: list[dict] = []

    def fake_mark_inactive(self, **kwargs):
        inactive_calls.append(kwargs)
        return 2

    from collector.curation.triage_repository import TriageRepository
    monkeypatch.setattr(
        TriageRepository,
        "mark_staging_inactive_for_category",
        fake_mark_inactive,
    )

    from collector.curation.categories_repository import CategoriesRepository

    data_api = MagicMock()
    data_api.transaction.return_value.__enter__.return_value = "tx-d8"
    data_api.transaction.return_value.__exit__.return_value = False
    # UPDATE ... RETURNING -> one row (success).
    data_api.execute.side_effect = [[{"id": "cat-victim"}]]
    repo = CategoriesRepository(data_api=data_api)

    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: repo,
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_triage_repository",
        lambda: MagicMock(),
    )

    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}",
            path_params={"id": "cat-victim"},
        ),
        context,
    )
    assert resp["statusCode"] == 204
    assert len(inactive_calls) == 1
    call = inactive_calls[0]
    assert call["user_id"] == "u1"
    assert call["category_id"] == "cat-victim"
    assert call["transaction_id"] == "tx-d8"

"""Retrain triggers on the triage routes (spec §5): finalize, and the 150th label since training."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from collector import curation_handler, ml_jobs
from collector.curation import deps
from collector.curation.triage_repository import (
    FinalizeResult,
    MoveResult,
    TransferResult,
    TriageBlockRow,
)

TRACK = "00000000-0000-0000-0000-00000000000a"
FROM = "00000000-0000-0000-0000-0000000000f0"
TO = "00000000-0000-0000-0000-0000000000f1"


class FakeMl:
    def __init__(self, *, bucket_type: str | None = "STAGING", since: int = 150, fail=False):
        self.bucket_type, self.since, self.fail = bucket_type, since, fail
        self.requests: list[tuple[str, str]] = []
        self.contexts: list[dict[str, Any]] = []

    def ml_trigger_context(self, *, user_id, block_id, bucket_id):
        if self.fail:
            raise RuntimeError("Aurora is resuming")
        self.contexts.append({"user_id": user_id, "block_id": block_id, "bucket_id": bucket_id})
        return {"style_id": "st", "bucket_type": None if bucket_id is None else self.bucket_type}

    def ml_labels_since_training(self, *, user_id, style_id):
        return self.since

    def ml_request_retrain(self, *, user_id, style_id, now):
        self.requests.append((user_id, style_id))
        return True


class FakeTriage:
    def move_tracks(self, **kw):
        return MoveResult(moved=1)

    def transfer_tracks(self, **kw):
        return TransferResult(transferred=1)

    def finalize_block(self, *, user_id, block_id, categories_repository):
        block = TriageBlockRow(
            id=block_id,
            user_id=user_id,
            style_id="st",
            style_name="DnB",
            name="W1",
            date_from="2026-10-17",
            date_to="2026-10-23",
            status="FINALIZED",
            old_offset_weeks=0,
            include_disliked_labels=False,
            include_disliked_artists=False,
            compilations_to_not=False,
            include_favorites=False,
            created_at="2026-10-24T00:00:00+00:00",
            updated_at="2026-10-24T00:00:00+00:00",
            finalized_at="2026-10-24T00:00:00+00:00",
        )
        return FinalizeResult(block=block, promoted={})


@pytest.fixture
def ml(monkeypatch):
    def install(fake: FakeMl) -> list[dict[str, str]]:
        sent: list[dict[str, str]] = []
        monkeypatch.setattr(deps, "create_default_triage_repository", FakeTriage)
        monkeypatch.setattr(deps, "create_default_categories_repository", object)
        monkeypatch.setattr(deps, "create_clouder_repository_from_env", lambda: fake)
        monkeypatch.setattr(ml_jobs, "enqueue_retrain", lambda **kw: sent.append(kw))
        monkeypatch.setattr(
            "collector.curation.routes_triage.enqueue_block_auto_enrich", lambda **kw: None
        )
        return sent

    return install


def _call(route: str, path: dict[str, str], body: dict | None = None) -> int:
    event = {
        "version": "2.0",
        "requestContext": {
            "requestId": "r",
            "routeKey": f"POST {route}",
            "authorizer": {"lambda": {"user_id": "u1", "session_id": "s", "is_admin": False}},
        },
        "headers": {"x-correlation-id": "cid"},
        "pathParameters": path,
        "body": json.dumps(body) if body is not None else None,
    }
    resp = curation_handler.lambda_handler(event, SimpleNamespace(aws_request_id="l"))
    return resp["statusCode"]


def _move(to: str = TO) -> int:
    body = {"from_bucket_id": FROM, "to_bucket_id": to, "track_ids": [TRACK]}
    return _call("/triage/blocks/{id}/move", {"id": "blk"}, body)


def _transfer() -> int:
    body = {"target_bucket_id": TO, "track_ids": [TRACK]}
    return _call("/triage/blocks/{src_id}/transfer", {"src_id": "blk"}, body)


def test_finalize_requests_retrain(ml) -> None:
    fake = FakeMl(since=0)  # a finalize retrains whatever the count
    sent = ml(fake)
    assert _call("/triage/blocks/{id}/finalize", {"id": "blk"}) == 200
    assert fake.contexts == [{"user_id": "u1", "block_id": "blk", "bucket_id": None}]
    assert fake.requests == [("u1", "st")]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


def test_move_into_staging_at_150_requests_retrain(ml) -> None:
    fake = FakeMl(since=150)
    sent = ml(fake)
    assert _move() == 200
    assert fake.contexts == [{"user_id": "u1", "block_id": "blk", "bucket_id": TO}]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


@pytest.mark.parametrize("bucket_type", ["DISCARD", "STAGING"])
def test_transfer_into_a_label_bucket_requests_retrain(ml, bucket_type) -> None:
    fake = FakeMl(bucket_type=bucket_type, since=151)
    sent = ml(fake)
    assert _transfer() == 200
    assert fake.contexts == [{"user_id": "u1", "block_id": "blk", "bucket_id": TO}]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


def test_move_below_150_does_not(ml) -> None:
    fake = FakeMl(since=149)
    sent = ml(fake)
    assert _move() == 200
    assert (fake.requests, sent) == ([], [])


@pytest.mark.parametrize("bucket_type", ["NEW", "OLD", "NOT", "UNCLASSIFIED", "FAV"])
def test_move_into_other_buckets_does_nothing(ml, bucket_type) -> None:
    fake = FakeMl(bucket_type=bucket_type, since=500)
    sent = ml(fake)
    assert _move() == 200
    assert (fake.requests, sent) == ([], [])


def test_pending_request_is_not_enqueued_again(ml, monkeypatch) -> None:
    fake = FakeMl(since=200)
    monkeypatch.setattr(fake, "ml_request_retrain", lambda **kw: False)
    sent = ml(fake)
    assert _move() == 200
    assert sent == []


def test_trigger_errors_never_break_move(ml, monkeypatch) -> None:
    logged: list[tuple] = []
    monkeypatch.setattr(
        "collector.curation.ml_triggers.log_event", lambda *a, **kw: logged.append((a, kw))
    )
    ml(FakeMl(fail=True))
    assert _move() == 200
    assert _transfer() == 200
    assert _call("/triage/blocks/{id}/finalize", {"id": "blk"}) == 200
    assert [a for a, _ in logged] == [("ERROR", "ml_retrain_trigger_error")] * 3


def test_no_database_means_no_trigger(ml, monkeypatch) -> None:
    sent = ml(FakeMl())
    monkeypatch.setattr(deps, "create_clouder_repository_from_env", lambda: None)
    assert _move() == 200
    assert sent == []

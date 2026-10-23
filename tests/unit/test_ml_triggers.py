"""Retrain triggers on the triage routes (spec §5): finalize, and the 150th label since training.

The move route's budget: no ML query unless the tap placed tracks in a STAGING / DISCARD bucket,
then one (the count), and the request only at 150. The queries run on the route's own client."""

from __future__ import annotations

import json
from types import SimpleNamespace

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
COUNT, REQUEST = "count", "request"


class FakeDataApi:
    """The route's Data API client: answers the ML count and the retrain request, records both."""

    def __init__(self, *, since: int = 150, pending: bool = False, fail: bool = False):
        self.since, self.pending, self.fail = since, pending, fail
        self.calls: list[str] = []

    def execute(self, sql, params=None, transaction_id=None):
        kind = COUNT if "count(*)" in sql else REQUEST if "INSERT INTO ml_models" in sql else sql
        self.calls.append(kind)
        if self.fail:
            raise RuntimeError("Aurora is resuming")
        if kind == COUNT:
            return [{"n": self.since}]
        if kind == REQUEST:
            return [] if self.pending else [{"?column?": 1}]
        raise AssertionError(f"unexpected query: {sql}")


class FakeTriage:
    def __init__(self, api: FakeDataApi, *, bucket_type: str = "STAGING", placed: int = 1):
        self._data_api, self.bucket_type, self.placed = api, bucket_type, placed

    def move_tracks(self, **kw):
        return MoveResult(moved=self.placed, style_id="st", bucket_type=self.bucket_type)

    def transfer_tracks(self, **kw):
        return TransferResult(transferred=self.placed, style_id="st", bucket_type=self.bucket_type)

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
    def install(triage: FakeTriage) -> list[dict[str, str]]:
        sent: list[dict[str, str]] = []
        monkeypatch.setattr(deps, "create_default_triage_repository", lambda: triage)
        monkeypatch.setattr(deps, "create_default_categories_repository", object)
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


def _move() -> int:
    body = {"from_bucket_id": FROM, "to_bucket_id": TO, "track_ids": [TRACK]}
    return _call("/triage/blocks/{id}/move", {"id": "blk"}, body)


def _transfer() -> int:
    body = {"target_bucket_id": TO, "track_ids": [TRACK]}
    return _call("/triage/blocks/{src_id}/transfer", {"src_id": "blk"}, body)


def _finalize() -> int:
    return _call("/triage/blocks/{id}/finalize", {"id": "blk"})


def test_finalize_requests_retrain(ml) -> None:
    api = FakeDataApi(since=0)  # a finalize retrains whatever the count
    sent = ml(FakeTriage(api))
    assert _finalize() == 200
    assert api.calls == [REQUEST]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


def test_move_into_staging_at_150_requests_retrain(ml) -> None:
    api = FakeDataApi(since=150)
    sent = ml(FakeTriage(api))
    assert _move() == 200
    assert api.calls == [COUNT, REQUEST]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


@pytest.mark.parametrize("bucket_type", ["DISCARD", "STAGING"])
def test_transfer_into_a_label_bucket_requests_retrain(ml, bucket_type) -> None:
    api = FakeDataApi(since=151)
    sent = ml(FakeTriage(api, bucket_type=bucket_type))
    assert _transfer() == 200
    assert api.calls == [COUNT, REQUEST]
    assert sent == [{"user_id": "u1", "style_id": "st"}]


@pytest.mark.parametrize("bucket_type", ["DISCARD", "STAGING"])
def test_move_below_150_does_not(ml, bucket_type) -> None:
    api = FakeDataApi(since=149)
    sent = ml(FakeTriage(api, bucket_type=bucket_type))
    assert _move() == 200
    assert api.calls == [COUNT]  # the one query a label tap costs
    assert sent == []


@pytest.mark.parametrize("bucket_type", ["NEW", "OLD", "NOT", "UNCLASSIFIED", "FAV"])
def test_moves_into_other_buckets_make_no_query(ml, bucket_type) -> None:
    api = FakeDataApi(since=500)
    sent = ml(FakeTriage(api, bucket_type=bucket_type))
    assert _move() == 200
    assert _transfer() == 200
    assert (api.calls, sent) == ([], [])


def test_noop_moves_make_no_query(ml) -> None:
    api = FakeDataApi(since=500)
    sent = ml(FakeTriage(api, placed=0))  # same bucket, or every track already there
    assert _move() == 200
    assert _transfer() == 200
    assert (api.calls, sent) == ([], [])


def test_pending_request_is_not_enqueued_again(ml) -> None:
    api = FakeDataApi(since=200, pending=True)
    sent = ml(FakeTriage(api))
    assert _move() == 200
    assert api.calls == [COUNT, REQUEST]
    assert sent == []


def test_trigger_errors_never_break_move(ml, monkeypatch) -> None:
    logged: list[tuple] = []
    monkeypatch.setattr(
        "collector.curation.ml_triggers.log_event", lambda *a, **kw: logged.append(a)
    )
    ml(FakeTriage(FakeDataApi(fail=True)))
    assert _move() == 200
    assert _transfer() == 200
    assert _finalize() == 200
    assert logged == [("ERROR", "ml_retrain_trigger_error")] * 3

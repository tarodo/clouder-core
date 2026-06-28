# tests/unit/test_telemetry_handler.py
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from collector import telemetry_handler


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("TELEMETRY_FIREHOSE_STREAM_NAME", "beatport-prod-telemetry")
    yield


def _ctx():
    return SimpleNamespace(aws_request_id="lambda-req-1")


def _event(events, *, user_id="u-1", body=None):
    payload = body if body is not None else json.dumps({"events": events})
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-1",
            "routeKey": "POST /v1/telemetry",
            "authorizer": {"lambda": {"user_id": user_id, "is_admin": False}},
        },
        "headers": {"x-correlation-id": "cid-1"},
        "body": payload,
    }


def _track_view(track="t1"):
    return {
        "event_name": "track_view",
        "event_id": f"ev-{track}",
        "session_id": "s1",
        "ts_client": "2026-06-27T10:00:00.000Z",
        "context": {"device": "desktop", "route": "/curate/:id"},
        "props": {"track_id": track, "dwell_ms": 900},
    }


def _ok_firehose():
    fh = MagicMock()
    fh.put_record_batch.return_value = {"FailedPutCount": 0, "RequestResponses": []}
    return fh


def test_happy_path_202_with_counts():
    fh = _ok_firehose()
    resp = telemetry_handler.lambda_handler(
        _event([_track_view("a"), _track_view("b")]), _ctx(), firehose_client=fh
    )
    assert resp["statusCode"] == 202
    assert json.loads(resp["body"]) == {"accepted": 2, "rejected": 0}
    assert fh.put_record_batch.call_count == 1


def test_firehose_records_are_ndjson_one_line_each():
    fh = _ok_firehose()
    telemetry_handler.lambda_handler(
        _event([_track_view("a"), _track_view("b")]), _ctx(), firehose_client=fh
    )
    records = fh.put_record_batch.call_args.kwargs["Records"]
    assert len(records) == 2
    for rec in records:
        data = rec["Data"].decode("utf-8")
        assert data.endswith("\n")
        assert data.count("\n") == 1
        json.loads(data)  # each line is standalone valid JSON


def test_props_serialized_as_json_string_for_glue_column():
    # The bronze Glue `props` column is type `string`; Firehose's JSON SerDe
    # will not coerce an object onto a string column (record would be routed to
    # bronze/_errors/). The handler must emit props as a JSON STRING, not a dict.
    fh = _ok_firehose()
    telemetry_handler.lambda_handler(_event([_track_view("a")]), _ctx(), firehose_client=fh)
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    record = json.loads(line)
    assert isinstance(record["props"], str)
    assert json.loads(record["props"]) == {"track_id": "a", "dwell_ms": 900}
    # context is also a `string`-typed bronze column — must be a JSON string too.
    assert isinstance(record["context"], str)
    assert "user_id" in json.loads(record["context"])
    # ts_server / event_name remain top-level scalars for partition extraction.
    assert isinstance(record["event_name"], str)
    assert isinstance(record["ts_server"], str)


def test_invalid_event_dropped_not_whole_batch():
    fh = _ok_firehose()
    bad = _track_view("bad")
    bad["event_name"] = "nope"
    resp = telemetry_handler.lambda_handler(
        _event([_track_view("a"), bad]), _ctx(), firehose_client=fh
    )
    assert json.loads(resp["body"]) == {"accepted": 1, "rejected": 1}
    assert len(fh.put_record_batch.call_args.kwargs["Records"]) == 1


def test_all_invalid_skips_firehose():
    fh = _ok_firehose()
    bad = _track_view("bad")
    bad["event_name"] = "nope"
    resp = telemetry_handler.lambda_handler(_event([bad]), _ctx(), firehose_client=fh)
    assert json.loads(resp["body"]) == {"accepted": 0, "rejected": 1}
    assert fh.put_record_batch.call_count == 0


def test_user_id_stamped_from_authorizer_not_client():
    fh = _ok_firehose()
    ev = _track_view("a")
    ev["context"]["user_id"] = "CLIENT_SPOOF"
    telemetry_handler.lambda_handler(
        _event([ev], user_id="u-real"), _ctx(), firehose_client=fh
    )
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    record = json.loads(line)
    assert json.loads(record["context"])["user_id"] == "u-real"
    assert "CLIENT_SPOOF" not in line


def test_unparseable_body_returns_400():
    fh = _ok_firehose()
    resp = telemetry_handler.lambda_handler(
        _event([], body="{not json"), _ctx(), firehose_client=fh
    )
    assert resp["statusCode"] == 400
    assert fh.put_record_batch.call_count == 0


def test_missing_events_key_returns_400():
    fh = _ok_firehose()
    resp = telemetry_handler.lambda_handler(
        _event([], body=json.dumps({"nope": []})), _ctx(), firehose_client=fh
    )
    assert resp["statusCode"] == 400


def test_batch_over_256_events_returns_400():
    fh = _ok_firehose()
    events = [_track_view(str(i)) for i in range(257)]
    resp = telemetry_handler.lambda_handler(_event(events), _ctx(), firehose_client=fh)
    assert resp["statusCode"] == 400
    assert fh.put_record_batch.call_count == 0


def test_body_over_256kb_returns_413():
    fh = _ok_firehose()
    big = "x" * (256 * 1024 + 1)
    resp = telemetry_handler.lambda_handler(
        _event([], body=big), _ctx(), firehose_client=fh
    )
    assert resp["statusCode"] == 413
    assert fh.put_record_batch.call_count == 0


def test_bp_token_never_reaches_firehose():
    fh = _ok_firehose()
    ev = _track_view("a")
    ev["props"]["bp_token"] = "SECRET"
    telemetry_handler.lambda_handler(_event([ev]), _ctx(), firehose_client=fh)
    line = fh.put_record_batch.call_args.kwargs["Records"][0]["Data"].decode("utf-8")
    assert "SECRET" not in line
    assert "bp_token" not in line

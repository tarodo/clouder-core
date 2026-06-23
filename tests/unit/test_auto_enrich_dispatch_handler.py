import json
import collector.auto_enrich_dispatch_handler as h


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(b)} for b in bodies]}


def _patch_all(monkeypatch, calls):
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: calls.append(("labels", kw)))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block",
                        lambda **kw: calls.append(("artists", kw)))
    monkeypatch.setattr(h, "try_dispatch_comments_for_triage_block",
                        lambda **kw: calls.append(("comments", kw)))


def test_worker_runs_all_three_dispatches_per_block(monkeypatch):
    calls = []
    _patch_all(monkeypatch, calls)
    h.lambda_handler(_sqs_event({"block_id": "blk-1", "user_id": "u1"}), None)
    assert ("labels", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("artists", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("comments", {"block_id": "blk-1", "user_id": "u1"}) in calls


def test_worker_processes_each_record(monkeypatch):
    calls = []
    _patch_all(monkeypatch, calls)
    h.lambda_handler(
        _sqs_event({"block_id": "b1", "user_id": "u"}, {"block_id": "b2", "user_id": "u"}),
        None,
    )
    comment_blocks = [kw["block_id"] for tag, kw in calls if tag == "comments"]
    assert comment_blocks == ["b1", "b2"]


def test_worker_raises_on_unparseable_record(monkeypatch):
    _patch_all(monkeypatch, [])
    import pytest
    with pytest.raises(Exception):
        h.lambda_handler({"Records": [{"body": "not json"}]}, None)

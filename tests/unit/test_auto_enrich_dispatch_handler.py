import json
import collector.auto_enrich_dispatch_handler as h


def _sqs_event(*bodies):
    return {"Records": [{"body": json.dumps(b)} for b in bodies]}


def test_worker_runs_both_dispatches_per_block(monkeypatch):
    calls = []
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: calls.append(("labels", kw)))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block",
                        lambda **kw: calls.append(("artists", kw)))
    h.lambda_handler(_sqs_event({"block_id": "blk-1", "user_id": "u1"}), None)
    assert ("labels", {"block_id": "blk-1", "user_id": "u1"}) in calls
    assert ("artists", {"block_id": "blk-1", "user_id": "u1"}) in calls


def test_worker_processes_each_record(monkeypatch):
    seen = []
    monkeypatch.setattr(h, "try_dispatch_for_triage_block",
                        lambda **kw: seen.append(kw["block_id"]))
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block", lambda **kw: None)
    h.lambda_handler(
        _sqs_event({"block_id": "b1", "user_id": "u"}, {"block_id": "b2", "user_id": "u"}),
        None,
    )
    assert seen == ["b1", "b2"]


def test_worker_raises_on_unparseable_record(monkeypatch):
    monkeypatch.setattr(h, "try_dispatch_for_triage_block", lambda **kw: None)
    monkeypatch.setattr(h, "try_dispatch_artists_for_triage_block", lambda **kw: None)
    import pytest
    with pytest.raises(Exception):
        h.lambda_handler({"Records": [{"body": "not json"}]}, None)

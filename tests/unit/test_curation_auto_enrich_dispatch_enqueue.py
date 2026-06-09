import json
import collector.curation.auto_enrich_dispatch as d


class FakeSQS:
    def __init__(self): self.sent = []
    def send_message(self, **kw): self.sent.append(kw)


def test_enqueue_sends_one_block_message(monkeypatch):
    sqs = FakeSQS()
    monkeypatch.setattr(d, "_build_sqs_client", lambda: sqs)
    monkeypatch.setattr(d, "_queue_url", lambda: "https://q/dispatch")
    d.enqueue_block_auto_enrich(block_id="blk-1", user_id="u1")
    assert len(sqs.sent) == 1
    body = json.loads(sqs.sent[0]["MessageBody"])
    assert body == {"block_id": "blk-1", "user_id": "u1"}


def test_enqueue_never_raises(monkeypatch):
    def boom(): raise RuntimeError("no queue")
    monkeypatch.setattr(d, "_build_sqs_client", boom)
    d.enqueue_block_auto_enrich(block_id="blk-1", user_id="u1")  # must not raise

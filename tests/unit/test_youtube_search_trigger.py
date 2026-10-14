from __future__ import annotations

import json
from types import SimpleNamespace

from collector.worker_handler import _enqueue_youtube_search_after_canonicalization


class Sqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kw):
        self.sent.append(kw)


def test_sends_one_sweep_message() -> None:
    sqs = Sqs()
    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url="https://sqs/yt"), "corr", sqs=sqs
    )
    assert sqs.sent[0]["QueueUrl"] == "https://sqs/yt"
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}


def test_no_queue_configured_sends_nothing() -> None:
    sqs = Sqs()
    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url=""), "corr", sqs=sqs
    )
    assert sqs.sent == []


def test_send_failure_never_breaks_the_run() -> None:
    class Broken:
        def send_message(self, **kw):
            raise RuntimeError("sqs down")

    _enqueue_youtube_search_after_canonicalization(
        SimpleNamespace(youtube_search_queue_url="https://sqs/yt"), "corr", sqs=Broken()
    )

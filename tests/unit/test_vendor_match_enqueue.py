from collector.curation.playlists_repository import MatchInput
from collector.vendor_match.enqueue import enqueue_vendor_matches


class FakeSqs:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    def send_message(self, *, QueueUrl, MessageBody):
        if self.fail:
            raise RuntimeError("sqs down")
        self.sent.append((QueueUrl, MessageBody))


def _inp(track_id="t1", artist="Guri", title="Lost Track"):
    return MatchInput(track_id=track_id, artist=artist, title=title,
                      isrc="GB1", duration_ms=225000, album="EP")


def test_enqueue_sends_one_message_per_input():
    sqs = FakeSqs()
    n = enqueue_vendor_matches(
        track_inputs=[_inp("t1"), _inp("t2")], vendor="ytmusic",
        queue_url="http://q", sqs=sqs,
    )
    assert n == 2
    assert len(sqs.sent) == 2
    assert '"vendor":"ytmusic"' in sqs.sent[0][1].replace(" ", "")


def test_enqueue_no_queue_url_is_noop():
    sqs = FakeSqs()
    assert enqueue_vendor_matches(track_inputs=[_inp()], vendor="ytmusic",
                                  queue_url="", sqs=sqs) == 0
    assert sqs.sent == []


def test_enqueue_skips_invalid_input():
    # empty artist fails VendorMatchMessage validation -> skipped, not raised
    sqs = FakeSqs()
    bad = MatchInput(track_id="t1", artist="", title="X", isrc=None,
                     duration_ms=None, album=None)
    assert enqueue_vendor_matches(track_inputs=[bad], vendor="ytmusic",
                                  queue_url="http://q", sqs=sqs) == 0


def test_enqueue_swallows_sqs_errors():
    sqs = FakeSqs(fail=True)
    assert enqueue_vendor_matches(track_inputs=[_inp()], vendor="ytmusic",
                                  queue_url="http://q", sqs=sqs) == 0

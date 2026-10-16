from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from ytmusicapi.exceptions import YTMusicServerError

import collector.youtube_search_handler as h
from collector.settings import YoutubeSearchWorkerSettings

SETTINGS = YoutubeSearchWorkerSettings(
    YOUTUBE_SEARCH_QUEUE_URL="https://sqs/q",
    YOUTUBE_SEARCH_SINCE="2026-10-15T00:00:00Z",
    YOUTUBE_SEARCH_PUBLISHED_SINCE="2026-10-03",
    YOUTUBE_SEARCH_MIN_INTERVAL_MS=0,
)


def song(vid, title="T"):
    return {
        "resultType": "song",
        "videoId": vid,
        "title": title,
        "artists": [{"name": "A"}],
        "duration_seconds": 200,
    }


def video(vid, title="A - T"):
    return {"resultType": "video", "videoId": vid, "title": title, "artists": [{"name": "Ch"}]}


class Repo:
    def __init__(self, tracks, *, blocked_until=None, more=False):
        self.tracks = tracks
        self.blocked_until = blocked_until
        self.more = more
        self.claimed_at = None
        self.done, self.released, self.matches, self.reviews, self.no_match = [], [], [], [], []
        self.blocks = []

    def get_vendor_blocked_until(self, vendor):
        return self.blocked_until

    def set_vendor_blocked_until(self, vendor, until, now):
        self.blocks.append((vendor, until))

    def claim_tracks_for_youtube_search(self, limit, claimed_at, since, published_since=None):
        self.claimed_at = claimed_at
        self.published_since = published_since
        return self.tracks[:limit]

    def mark_youtube_searched(self, track_id, at):
        assert at != self.claimed_at
        self.done.append(track_id)

    def release_youtube_search_claim(self, claimed_at):
        self.released.append(claimed_at)
        return len(self.tracks) - len(self.done)

    def has_tracks_needing_youtube_search(self, since, published_since=None):
        self.more_published_since = published_since
        return self.more

    def upsert_vendor_match(self, cmd):
        self.matches.append((cmd.clouder_track_id, cmd.vendor, cmd.vendor_track_id, cmd.match_type))

    def insert_review_candidate(
        self, *, review_id, clouder_track_id, vendor, candidates, created_at
    ):
        self.reviews.append((clouder_track_id, len(candidates)))

    def mark_no_match(self, *, clouder_track_id, vendor, created_at):
        self.no_match.append(clouder_track_id)


class Client:
    def __init__(self, script):
        self.script = list(script)  # per call: list of results or an exception

    def search(self, query, filter=None, limit=20):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class Sqs:
    def __init__(self):
        self.sent = []

    def send_message(self, **kw):
        self.sent.append(kw)


def track(tid, has_ytmusic=False):
    return {
        "id": tid,
        "title": "T",
        "length_ms": 200000,
        "album_title": None,
        "artists": "A",
        "has_ytmusic": has_ytmusic,
    }


def run(monkeypatch, repo, client, *, body=None, remaining_ms=900_000):
    sqs = Sqs()
    monkeypatch.setattr(h, "create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(h, "get_youtube_search_worker_settings", lambda: SETTINGS)
    ctx = type("Ctx", (), {"get_remaining_time_in_millis": lambda self: remaining_ms})()
    event = {"Records": [{"body": json.dumps(body or {"batch_size": 100})}]}
    out = h.lambda_handler(
        event, ctx, client_factory=lambda: client, sqs_factory=lambda: sqs, sleep=lambda s: None
    )
    return out, sqs


def test_happy_batch_stores_outcomes_and_follows_up(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")], more=True)
    client = Client([[song("s1"), video("v1")], [], [], []])
    out, sqs = run(monkeypatch, repo, client)
    assert out == {"processed": 1}
    assert ("t1", "youtube", "v1", "token") in repo.matches
    assert ("t1", "ytmusic", "s1", "fuzzy") in repo.matches
    assert repo.no_match == ["t2"]
    assert repo.done == ["t1", "t2"]
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}
    assert "DelaySeconds" not in sqs.sent[0]


def test_recent_releases_window_reaches_the_repository(monkeypatch) -> None:
    # Week 40 was ingested before the launch: publish date, not ingest date, picks it.
    repo = Repo([track("t1")], more=True)
    run(monkeypatch, repo, Client([[song("s1")]]))
    assert repo.published_since == date(2026, 10, 3)
    assert repo.more_published_since == date(2026, 10, 3)


def test_no_follow_up_when_nothing_left(monkeypatch) -> None:
    repo = Repo([track("t1")], more=False)
    _, sqs = run(monkeypatch, repo, Client([[song("s1")]]))
    assert sqs.sent == []


def test_ban_mid_batch_releases_rest_and_schedules_resume(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2"), track("t3")], more=True)
    ban = YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n")
    _, sqs = run(monkeypatch, repo, Client([[song("s1")], ban]))
    assert repo.done == ["t1"]
    assert repo.released == [repo.claimed_at]
    assert repo.blocks and repo.blocks[0][0] == "ytmusic"
    assert len(sqs.sent) == 1
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100, "resume": True}
    assert sqs.sent[0]["DelaySeconds"] == 900


def test_paused_trigger_is_dropped_and_resume_rearms(monkeypatch) -> None:
    until = datetime.now(UTC) + timedelta(minutes=5)
    repo = Repo([track("t1")], blocked_until=until)
    _, sqs = run(monkeypatch, repo, Client([]))
    assert sqs.sent == [] and repo.claimed_at is None
    _, sqs = run(monkeypatch, repo, Client([]), body={"batch_size": 50, "resume": True})
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 50, "resume": True}
    assert 1 <= sqs.sent[0]["DelaySeconds"] <= 300


def test_generic_error_marks_done_and_continues(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    _, _ = run(monkeypatch, repo, Client([ValueError("weird unicode"), [song("s2")]]))
    # t1 is confirmed as an isolated failure once t2 succeeds.
    assert sorted(repo.done) == ["t1", "t2"]
    assert ("t2", "ytmusic", "s2", "fuzzy") in repo.matches


def test_existing_ytmusic_row_stores_only_the_video(monkeypatch) -> None:
    repo = Repo([track("t1", has_ytmusic=True)])
    run(monkeypatch, repo, Client([[song("s9", title="Other"), video("v1")]]))
    assert repo.matches == [("t1", "youtube", "v1", "token")]
    assert repo.reviews == [] and repo.no_match == []


def test_deadline_hands_tracks_back_and_follows_up(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")], more=True)
    _, sqs = run(monkeypatch, repo, Client([]), remaining_ms=30_000)
    assert repo.done == [] and repo.released == [repo.claimed_at]
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100}


def test_db_outage_releases_and_reraises(monkeypatch) -> None:
    repo = Repo([track("t1")])

    def boom(*a, **k):
        raise RuntimeError("data api down")

    repo.upsert_vendor_match = boom
    repo.mark_youtube_searched = boom
    with pytest.raises(RuntimeError):
        run(monkeypatch, repo, Client([[song("s1")]]))
    assert repo.released == [repo.claimed_at]


def test_bad_result_data_is_skipped_per_track(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    real = repo.upsert_vendor_match

    def picky(cmd):
        if cmd.clouder_track_id == "t1":
            raise ValueError("unsupported Unicode escape sequence")
        real(cmd)

    repo.upsert_vendor_match = picky
    run(monkeypatch, repo, Client([[song("s1")], [song("s2")]]))
    assert repo.done == ["t1", "t2"]
    assert ("t2", "ytmusic", "s2", "fuzzy") in repo.matches


def test_an_unrecognised_block_pauses_like_a_ban(monkeypatch) -> None:
    # ytmusicapi parses JSON before checking the status: an HTML 429 page
    # surfaces as JSONDecodeError, not as a YTMusicServerError.
    import json as _json

    blocked = _json.JSONDecodeError("Expecting value", "<html>", 0)
    repo = Repo([track(f"t{i}") for i in range(8)], more=True)
    _, sqs = run(monkeypatch, repo, Client([blocked] * 8))
    assert repo.done == []
    assert repo.released == [repo.claimed_at]
    assert repo.blocks and repo.blocks[0][0] == "ytmusic"
    assert json.loads(sqs.sent[0]["MessageBody"]) == {"batch_size": 100, "resume": True}


def test_trailing_errors_at_batch_end_are_accepted(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    run(monkeypatch, repo, Client([[song("s1")], ValueError("odd")]))
    assert repo.done == ["t1", "t2"] and repo.released == []


def test_client_failure_after_claim_hands_the_batch_back(monkeypatch) -> None:
    repo = Repo([track("t1")])
    sqs = Sqs()
    monkeypatch.setattr(h, "create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(h, "get_youtube_search_worker_settings", lambda: SETTINGS)

    def no_client():
        raise RuntimeError("cannot build client")

    event = {"Records": [{"body": json.dumps({"batch_size": 100})}]}
    with pytest.raises(RuntimeError):
        h.lambda_handler(event, None, client_factory=no_client, sqs_factory=lambda: sqs)
    assert repo.released == [repo.claimed_at]


def test_requests_time_out_well_inside_the_deadline_margin() -> None:
    session = h._session()
    assert session.request.keywords["timeout"] <= 15


def test_invalid_message_is_skipped(monkeypatch) -> None:
    out, _ = run(monkeypatch, Repo([]), Client([]), body={"batch_size": 0})
    assert out == {"processed": 0}


def test_pacer_keeps_requests_apart() -> None:
    now = [0.0]
    slept = []
    pacer = h.Pacer(
        2.0, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s))
    )
    pacer()
    now[0] = 0.5
    pacer()
    assert slept == [1.5]


class _Resuming(Exception):
    """Shape of botocore's ClientError for a paused Aurora."""

    def __init__(self) -> None:
        super().__init__("resuming")
        self.response = {"Error": {"Code": "DatabaseResumingException"}}


def test_waits_for_a_paused_database_before_sweeping(monkeypatch) -> None:
    # A resume after a 1 h ban (or an SQS redelivery after 16 min) always finds
    # Aurora auto-paused; the Data API retry budget alone gives up too early.
    repo = Repo([track("t1")])
    calls = {"n": 0}
    real = repo.get_vendor_blocked_until

    def waking(vendor):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _Resuming()
        return real(vendor)

    repo.get_vendor_blocked_until = waking
    out, _ = run(monkeypatch, repo, Client([[song("s1")]]))
    assert out == {"processed": 1} and repo.done == ["t1"]


def test_other_database_errors_are_not_waited_out(monkeypatch) -> None:
    repo = Repo([track("t1")])

    def broken(vendor):
        raise RuntimeError("access denied")

    repo.get_vendor_blocked_until = broken
    with pytest.raises(RuntimeError):
        run(monkeypatch, repo, Client([]))

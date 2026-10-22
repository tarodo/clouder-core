from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from ytmusicapi.exceptions import YTMusicServerError

import collector.youtube_search_handler as h
from collector.settings import YoutubeSearchWorkerSettings

SETTINGS = YoutubeSearchWorkerSettings(YOUTUBE_SEARCH_MIN_INTERVAL_MS=0)


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
    def __init__(self, tracks, *, blocked_until=None):
        self.tracks = tracks
        self.blocked_until = blocked_until
        self.claimed_at = None
        self.done, self.released, self.matches, self.reviews, self.no_match = [], [], [], [], []
        self.blocks = []

    def get_vendor_blocked_until(self, vendor):
        return self.blocked_until

    def set_vendor_blocked_until(self, vendor, until, now):
        self.blocks.append((vendor, until))

    def claim_tracks_for_youtube_search(self, limit, claimed_at):
        self.claimed_at, self.limit = claimed_at, limit
        return self.tracks[:limit]

    def mark_youtube_searched(self, track_id, at):
        assert at != self.claimed_at
        self.done.append(track_id)

    def release_youtube_search_claim(self, claimed_at):
        self.released.append(claimed_at)
        return len(self.tracks) - len(self.done)

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
    monkeypatch.setattr(h, "create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(h, "get_youtube_search_worker_settings", lambda: SETTINGS)
    ctx = type("Ctx", (), {"get_remaining_time_in_millis": lambda self: remaining_ms})()
    event = {"Records": [{"body": json.dumps(body or {"batch_size": 250})}]}
    return h.lambda_handler(event, ctx, client_factory=lambda: client, sleep=lambda s: None)


def test_hourly_batch_stores_outcomes(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    client = Client([[song("s1"), video("v1")], [], [], []])
    out = run(monkeypatch, repo, client)
    assert out == {"processed": 1} and repo.limit == 250
    assert ("t1", "youtube", "v1", "token") in repo.matches
    assert ("t1", "ytmusic", "s1", "fuzzy") in repo.matches
    assert repo.no_match == ["t2"]
    assert repo.done == ["t1", "t2"]


def test_ban_mid_batch_releases_rest_and_pauses(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2"), track("t3")])
    ban = YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n")
    run(monkeypatch, repo, Client([[song("s1")], ban]))
    assert repo.done == ["t1"]
    assert repo.released == [repo.claimed_at]
    assert repo.blocks and repo.blocks[0][0] == "ytmusic"


def test_hourly_trigger_is_dropped_while_paused(monkeypatch) -> None:
    until = datetime.now(UTC) + timedelta(minutes=5)
    repo = Repo([track("t1")], blocked_until=until)
    assert run(monkeypatch, repo, Client([])) == {"processed": 1}
    assert repo.claimed_at is None


def test_generic_error_marks_done_and_continues(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    run(monkeypatch, repo, Client([ValueError("weird unicode"), [song("s2")]]))
    # t1 is confirmed as an isolated failure once t2 succeeds.
    assert sorted(repo.done) == ["t1", "t2"]
    assert ("t2", "ytmusic", "s2", "fuzzy") in repo.matches


def test_existing_ytmusic_row_stores_only_the_video(monkeypatch) -> None:
    repo = Repo([track("t1", has_ytmusic=True)])
    run(monkeypatch, repo, Client([[song("s9", title="Other"), video("v1")]]))
    assert repo.matches == [("t1", "youtube", "v1", "token")]
    assert repo.reviews == [] and repo.no_match == []


def test_deadline_hands_tracks_back_for_the_next_hour(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    run(monkeypatch, repo, Client([]), remaining_ms=30_000)
    assert repo.done == [] and repo.released == [repo.claimed_at]


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
    repo = Repo([track(f"t{i}") for i in range(8)])
    run(monkeypatch, repo, Client([blocked] * 8))
    assert repo.done == []
    assert repo.released == [repo.claimed_at]
    assert repo.blocks and repo.blocks[0][0] == "ytmusic"


def test_trailing_errors_at_batch_end_are_accepted(monkeypatch) -> None:
    repo = Repo([track("t1"), track("t2")])
    run(monkeypatch, repo, Client([[song("s1")], ValueError("odd")]))
    assert repo.done == ["t1", "t2"] and repo.released == []


def test_client_failure_after_claim_hands_the_batch_back(monkeypatch) -> None:
    repo = Repo([track("t1")])
    monkeypatch.setattr(h, "create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(h, "get_youtube_search_worker_settings", lambda: SETTINGS)

    def no_client():
        raise RuntimeError("cannot build client")

    event = {"Records": [{"body": json.dumps({"batch_size": 100})}]}
    with pytest.raises(RuntimeError):
        h.lambda_handler(event, None, client_factory=no_client)
    assert repo.released == [repo.claimed_at]


def test_requests_time_out_well_inside_the_deadline_margin() -> None:
    session = h._session()
    assert session.request.keywords["timeout"] <= 15


def test_invalid_message_is_skipped(monkeypatch) -> None:
    out = run(monkeypatch, Repo([]), Client([]), body={"batch_size": 0})
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
    out = run(monkeypatch, repo, Client([[song("s1")]]))
    assert out == {"processed": 1} and repo.done == ["t1"]


def test_other_database_errors_are_not_waited_out(monkeypatch) -> None:
    repo = Repo([track("t1")])

    def broken(vendor):
        raise RuntimeError("access denied")

    repo.get_vendor_blocked_until = broken
    with pytest.raises(RuntimeError):
        run(monkeypatch, repo, Client([]))


def test_version_rule_match_is_stored_as_fuzzy_version(monkeypatch) -> None:
    # Our Extended Mix is 2:10 longer than the single edit YT Music carries.
    repo = Repo([{**track("t1"), "mix_name": "Extended Mix", "length_ms": 330000}])
    run(monkeypatch, repo, Client([[song("s1")], [], []]))
    assert repo.matches == [("t1", "ytmusic", "s1", "fuzzy_version")]


def test_remix_does_not_take_the_original(monkeypatch) -> None:
    repo = Repo([{**track("t1"), "mix_name": "Guri Remix", "length_ms": 330000}])
    run(monkeypatch, repo, Client([[song("s1")], [], []]))
    assert repo.matches == [] and repo.reviews == [("t1", 1)]

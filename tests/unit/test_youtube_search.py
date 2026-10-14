from __future__ import annotations

import pytest
from ytmusicapi.exceptions import YTMusicGatedError, YTMusicServerError

from collector.youtube_search.search import TrackQuery, is_ban, search_track


def song(vid, title="Lost Track", artist="Guri", seconds=200, album="Lost EP"):
    return {
        "resultType": "song",
        "videoId": vid,
        "title": title,
        "artists": [{"name": artist}],
        "duration_seconds": seconds,
        "album": {"name": album},
    }


def video(vid, title="Guri - Lost Track (Official Video)", channel="Some Label"):
    return {
        "resultType": "video",
        "videoId": vid,
        "title": title,
        "artists": [{"name": channel}],
        "duration_seconds": 205,
    }


class FakeClient:
    def __init__(self, by_filter):
        self.by_filter = by_filter  # {None: [...], "songs": [...], "videos": [...]}
        self.calls = []

    def search(self, query, filter=None, limit=20):
        self.calls.append((query, filter))
        return self.by_filter.get(filter, [])


Q = TrackQuery(
    artists="Guri", title="Lost Track", duration_ms=200_000, album="Lost EP", need_song=True
)


def run(client, q=Q):
    paces = []
    res = search_track(client, q, threshold=0.92, pace=lambda: paces.append(1))
    return res, paces


def test_song_and_video_from_one_request() -> None:
    res, paces = run(FakeClient({None: [song("s1"), video("v1")]}))
    assert res.outcome == "auto" and res.match[0].vendor_track_id == "s1"
    assert res.video.vendor_track_id == "v1"
    assert res.request_count == 1 and len(paces) == 1


def test_ambiguous_first_answer_tries_songs_filter() -> None:
    client = FakeClient({None: [song("x", title="Other Thing")], "songs": [song("s2")]})
    res, paces = run(client)
    assert client.calls[1] == ("Guri Lost Track", "songs")
    assert res.outcome == "auto" and res.match[0].vendor_track_id == "s2"
    assert res.request_count == 2 and len(paces) == 2


def test_no_songs_falls_back_to_videos_and_reviews() -> None:
    client = FakeClient({None: [], "songs": [], "videos": [video("v9")]})
    res, _ = run(client)
    assert [c[1] for c in client.calls] == [None, "songs", "videos"]
    assert res.outcome == "review" and res.review[0][0].vendor_track_id == "v9"


def test_first_pass_candidates_survive_empty_retries() -> None:
    client = FakeClient(
        {None: [song("x", title="Lost Track (Club Mix)")], "songs": [], "videos": []}
    )
    res, _ = run(client)
    assert res.outcome == "review" and res.review[0][0].vendor_track_id == "x"


def test_empty_title_and_artist_do_not_crash() -> None:
    q = TrackQuery(artists="", title="", duration_ms=None, album=None, need_song=True)
    res, _ = run(FakeClient({None: [video("v1")]}), q)
    assert res.outcome == "no_match" and res.video is None


def test_nothing_anywhere_is_no_match() -> None:
    res, _ = run(FakeClient({}))
    assert res.outcome == "no_match" and res.video is None and res.best_score is None


def test_existing_ytmusic_row_searches_video_only() -> None:
    q = TrackQuery("Guri", "Lost Track", 200_000, None, need_song=False)
    client = FakeClient({None: [song("x", title="Nope"), video("v1")]})
    res, _ = run(client, q)
    assert res.outcome == "video_only" and res.video.vendor_track_id == "v1"
    assert res.request_count == 1 and res.match is None and res.review == []


def test_remix_video_is_not_the_original() -> None:
    res, _ = run(
        FakeClient({None: [song("s1"), video("v1", title="Guri - Lost Track (Bob Remix)")]})
    )
    assert res.video is None


@pytest.mark.parametrize(
    ("exc", "ban"),
    [
        (YTMusicServerError("Server returned HTTP 429: Too Many Requests.\n"), True),
        (YTMusicServerError("Server returned HTTP 403: Forbidden.\n"), True),
        (YTMusicGatedError("confirm you're not a bot"), True),
        (YTMusicServerError("Server returned HTTP 500: Internal Server Error.\n"), False),
        (ValueError("bad"), False),
    ],
)
def test_is_ban(exc, ban) -> None:
    assert is_ban(exc) is ban

"""Unit tests for GET /playlists/{id}/comments handler."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import collector.curation_handler as ch
from collector.comments.repository import CollectionRow, CommentRow
from collector.curation import ValidationError


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _track_row(track_id: str):
    return SimpleNamespace(track_id=track_id)


class FakePlaylistsRepo:
    def __init__(self, track_rows):
        self._rows = track_rows

    def list_tracks(self, *, user_id, playlist_id, limit, offset, **kwargs):
        return self._rows, len(self._rows)


class FakeCommentsRepo:
    def __init__(self, by_track: dict):
        self._by_track = by_track

    def list_comments_for_tracks(self, *, track_ids, platform, limit_per_track):
        return {k: v for k, v in self._by_track.items() if k in track_ids}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(playlist_id="pl-1", qs=None):
    return {
        "pathParameters": {"id": playlist_id},
        "queryStringParameters": qs or {},
    }


def _call(playlist_id="pl-1", qs=None, playlists_repo=None, comments_repo=None):
    event = _event(playlist_id=playlist_id, qs=qs)
    with patch("collector.curation_handler._comments_factory", return_value=comments_repo):
        return ch._handle_list_playlist_comments(event, playlists_repo, "u1", "corr")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_two_tracks_one_has_comments_one_absent():
    """Track order is preserved; absent track gets the pending envelope."""
    track_t1 = _track_row("t1")
    track_t2 = _track_row("t2")
    playlists_repo = FakePlaylistsRepo([track_t1, track_t2])

    collection = CollectionRow("col1", "t1", "youtube", "vidA", "collected", 3, None)
    comments_list = [
        CommentRow("Alice", None, "great track", 5, "2025-01-01T00:00:00", 0),
    ]
    comments_repo = FakeCommentsRepo({"t1": (collection, comments_list)})

    resp = _call(playlists_repo=playlists_repo, comments_repo=comments_repo)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    tracks = body["tracks"]
    assert len(tracks) == 2

    # First track (t1) has a collection
    t1 = tracks[0]
    assert t1["track_id"] == "t1"
    assert t1["status"] == "collected"
    assert t1["comment_count"] == 3
    assert t1["video_url"] == "https://www.youtube.com/watch?v=vidA"
    assert len(t1["comments"]) == 1
    assert t1["comments"][0]["author_name"] == "Alice"
    assert t1["comments"][0]["text"] == "great track"
    assert t1["comments"][0]["like_count"] == 5

    # Second track (t2) is absent from comments → pending envelope
    t2 = tracks[1]
    assert t2["track_id"] == "t2"
    assert t2["status"] == "pending"
    assert t2["comment_count"] == 0
    assert t2["video_url"] is None
    assert t2["comments"] == []

    assert body["correlation_id"] == "corr"


def test_missing_id_path_param_raises_validation_error():
    """Missing 'id' path parameter must raise ValidationError (→ 422 via the router)."""
    event = {"pathParameters": {}, "queryStringParameters": {}}
    playlists_repo = FakePlaylistsRepo([])
    comments_repo = FakeCommentsRepo({})
    with pytest.raises(ValidationError):
        with patch("collector.curation_handler._comments_factory", return_value=comments_repo):
            ch._handle_list_playlist_comments(event, playlists_repo, "u1", "corr")


def test_comments_factory_none_returns_503():
    """If _comments_factory() returns None, respond 503 db_not_configured."""
    playlists_repo = FakePlaylistsRepo([_track_row("t1")])
    resp = _call(playlists_repo=playlists_repo, comments_repo=None)
    assert resp["statusCode"] == 503
    body = json.loads(resp["body"])
    assert body["error_code"] == "db_not_configured"


def test_platform_param_non_youtube_gives_none_video_url():
    """For platform != 'youtube', video_url should be None even when collected."""
    playlists_repo = FakePlaylistsRepo([_track_row("t1")])
    collection = CollectionRow("col1", "t1", "spotify", "vidA", "collected", 1, None)
    comments_repo = FakeCommentsRepo({"t1": (collection, [])})
    resp = _call(qs={"platform": "spotify"}, playlists_repo=playlists_repo, comments_repo=comments_repo)
    body = json.loads(resp["body"])
    assert body["tracks"][0]["video_url"] is None


def test_empty_playlist_returns_empty_tracks():
    """Empty playlist → empty tracks list, 200."""
    playlists_repo = FakePlaylistsRepo([])
    comments_repo = FakeCommentsRepo({})
    resp = _call(playlists_repo=playlists_repo, comments_repo=comments_repo)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["tracks"] == []

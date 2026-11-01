"""GET /tracks/{track_id}/similar and GET /artists/{artist_id}/similar: the handlers' wiring."""

from __future__ import annotations

import pytest

from collector import similar_tracks
from collector.errors import ValidationError


class FakeRepo:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def for_track(self, **kw):
        self.calls.append(("track", kw))
        return {"seed": None, "profiled": False, "items": []}

    def for_artist(self, **kw):
        self.calls.append(("artist", kw))
        return {"profiled": False, "style": None, "styles": [], "items": []}


def _event(path: dict, qs: dict | None = None) -> dict:
    return {
        "requestContext": {"authorizer": {"lambda": {"user_id": "u1"}}},
        "pathParameters": path,
        "queryStringParameters": qs,
    }


@pytest.fixture
def repo(monkeypatch):
    fake = FakeRepo()
    monkeypatch.setattr(similar_tracks, "_build_repository", lambda: fake)
    return fake


def test_track_similar_passes_the_track_and_caller(repo) -> None:
    status, body = similar_tracks.handle_track_similar(_event({"track_id": " t1 "}))
    assert (status, body["profiled"]) == (200, False)
    assert repo.calls == [("track", {"track_id": "t1", "user_id": "u1"})]


def test_artist_similar_passes_style_or_none(repo) -> None:
    similar_tracks.handle_artist_similar(_event({"artist_id": "a1"}, {"style_id": "st"}))
    similar_tracks.handle_artist_similar(_event({"artist_id": "a1"}, {"style_id": " "}))
    assert [kw["style_id"] for _, kw in repo.calls] == ["st", None]
    assert repo.calls[0][1] == {"artist_id": "a1", "user_id": "u1", "style_id": "st"}


@pytest.mark.parametrize(
    ("handle", "param"),
    [
        (similar_tracks.handle_track_similar, "track_id"),
        (similar_tracks.handle_artist_similar, "artist_id"),
    ],
)
def test_blank_id_is_a_validation_error(repo, handle, param) -> None:
    with pytest.raises(ValidationError, match=param):
        handle(_event({param: " "}))

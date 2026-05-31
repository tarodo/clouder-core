import json

from collector import curation_handler as ch
from collector.curation.playlists_repository import ReviewRow, YtmusicStatus


def _candidate(vid="dQw4w9WgXcQ", score=0.9):
    return {"ref": {"videoId": vid, "title": "Hold Me", "artists": [{"name": "ARTYS"}],
                    "album": {"name": "EP"}, "duration_seconds": 418}, "score": score}


class Repo:
    def __init__(self, *, in_scope=True, owns=True, review=None, status=None):
        self._in_scope = in_scope
        self._owns = owns
        self._review = review
        self._status = status
        self.accepted = None
        self.rejected = None
    def get(self, *, user_id, playlist_id):
        return object() if self._owns else None
    def validate_tracks_in_scope(self, *, user_id, track_ids):
        return set(track_ids) if self._in_scope else set()
    def get_open_review(self, *, track_id, vendor):
        return self._review
    def resolve_review_accept(self, *, clouder_track_id, vendor, vendor_track_id, payload, now):
        self.accepted = (clouder_track_id, vendor, vendor_track_id, payload)
    def resolve_review_reject(self, *, clouder_track_id, vendor, now):
        self.rejected = (clouder_track_id, vendor)
    def fetch_ytmusic_status(self, track_ids):
        return {t: self._status for t in track_ids}


def _event(pid="pl1", tid="t1", body=None, qs=None):
    e = {"pathParameters": {"id": pid, "track_id": tid}}
    if body is not None:
        e["body"] = json.dumps(body)
    if qs is not None:
        e["queryStringParameters"] = qs
    return e


def test_candidates_projects_each():
    repo = Repo(review=ReviewRow(candidates=[_candidate()]))
    resp = ch._handle_match_candidates(_event(qs={"vendor": "ytmusic"}), repo, "u1", "c1")
    body = json.loads(resp["body"])
    assert body["vendor"] == "ytmusic"
    c = body["candidates"][0]
    assert c["vendor_track_id"] == "dQw4w9WgXcQ"
    assert c["title"] == "Hold Me"
    assert c["artists"] == ["ARTYS"]
    assert c["album"] == "EP"
    assert c["duration_ms"] == 418_000
    assert c["url"] == "https://music.youtube.com/watch?v=dQw4w9WgXcQ"
    assert c["score"] == 0.9


def test_candidates_404_when_no_open_review():
    repo = Repo(review=None)
    try:
        ch._handle_match_candidates(_event(qs={"vendor": "ytmusic"}), repo, "u1", "c1")
        assert False, "expected NotFoundError"
    except ch.NotFoundError:
        pass


def test_resolve_accept_writes_and_returns_status():
    repo = Repo(
        review=ReviewRow(candidates=[_candidate()]),
        status=YtmusicStatus(status="matched", video_id="dQw4w9WgXcQ",
                             url="https://music.youtube.com/watch?v=dQw4w9WgXcQ",
                             confidence=1.0),
    )
    body = {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "dQw4w9WgXcQ"}
    resp = ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    assert repo.accepted[0] == "t1" and repo.accepted[2] == "dQw4w9WgXcQ"
    assert repo.accepted[3]["videoId"] == "dQw4w9WgXcQ"
    assert json.loads(resp["body"])["ytmusic"]["status"] == "matched"


def test_resolve_accept_manual_url_payload():
    repo = Repo(review=ReviewRow(candidates=[_candidate(vid="aaaaaaaaaaa")]),
                status=YtmusicStatus(status="matched"))
    body = {"vendor": "ytmusic", "action": "accept", "vendor_track_id": "bbbbbbbbbbb"}
    ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    assert repo.accepted[3]["source"] == "manual_url"
    assert repo.accepted[3]["videoId"] == "bbbbbbbbbbb"


def test_resolve_reject_sets_status():
    repo = Repo(status=YtmusicStatus(status="not_found"))
    body = {"vendor": "ytmusic", "action": "reject"}
    resp = ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
    assert repo.rejected == ("t1", "ytmusic")
    assert json.loads(resp["body"])["ytmusic"]["status"] == "not_found"


def test_resolve_out_of_scope_raises():
    repo = Repo(in_scope=False, status=YtmusicStatus(status="pending"))
    body = {"vendor": "ytmusic", "action": "reject"}
    try:
        ch._handle_resolve_match(_event(body=body), repo, "u1", "c1")
        assert False, "expected TrackNotInUserScopeError"
    except ch.TrackNotInUserScopeError:
        pass


def test_candidates_skips_ref_without_video_id():
    bad = {"ref": {"title": "no id", "artists": []}, "score": 0.4}
    good = _candidate()
    repo = Repo(review=ReviewRow(candidates=[bad, good]))
    resp = ch._handle_match_candidates(_event(qs={"vendor": "ytmusic"}), repo, "u1", "c1")
    body = json.loads(resp["body"])
    assert [c["vendor_track_id"] for c in body["candidates"]] == ["dQw4w9WgXcQ"]

"""Re-score the open YT Music review queue with the version rule: no YouTube calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from collector.vendor_match.rescore import accept, decide, open_reviews

NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def _review(pg, tid: str, *, mix: str | None, cand_title: str, score: float, **sims) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, mix_name, length_ms,"
        " created_at, updated_at) VALUES (:id, 'Night Drive', 'night drive', :mix, 330000,"
        " now(), now())",
        {"id": tid, "mix": mix},
    )
    candidates = [  # deliberately not sorted: the top one is picked by score
        {"ref": {"videoId": f"low-{tid}", "title": "Other"}, "score": 0.5},
        {
            "ref": {"videoId": f"top-{tid}", "title": cand_title, "duration_seconds": 201},
            "score": score,
            "title_sim": sims.get("title_sim", 1.0),
            "artist_sim": sims.get("artist_sim", 1.0),
            "duration_ok": sims.get("duration_ok", False),
            "album_bonus": 0.0,
        },
    ]
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
        " created_at) VALUES (:id, :t, 'ytmusic', CAST(:c AS jsonb), 'pending', now())",
        {"id": f"q-{tid}", "t": tid, "c": json.dumps(candidates)},
    )


def _world(pg) -> None:
    _review(pg, "extended", mix="Extended Mix", cand_title="Night Drive", score=0.9)
    _review(pg, "remix", mix="Zeta Remix", cand_title="Night Drive", score=0.9)
    _review(
        pg,
        "other-artist",
        mix="Original Mix",
        cand_title="Night Drive",
        score=0.82,
        artist_sim=0.55,
    )


def test_open_reviews_bring_the_top_candidate_and_our_track(pg) -> None:
    _world(pg)
    rows = {r["track_id"]: r for r in open_reviews(pg, after="", limit=10)}
    assert set(rows) == {"extended", "remix", "other-artist"}
    cands = rows["extended"]["candidates"]
    assert [c["ref"]["videoId"] for c in cands] == ["top-extended", "low-extended"]  # best first
    assert cands[0]["score"] == 0.9
    assert (rows["extended"]["title"], rows["extended"]["mix_name"]) == (
        "Night Drive",
        "Extended Mix",
    )


def test_open_reviews_page_by_review_id(pg) -> None:
    _world(pg)
    first = open_reviews(pg, after="", limit=2)
    rest = open_reviews(pg, after=first[-1]["review_id"], limit=10)
    assert len(first) == 2 and len(rest) == 1
    assert not {r["track_id"] for r in first} & {r["track_id"] for r in rest}


def _picked(row) -> str | None:
    chosen = decide(row)
    return chosen["ref"]["videoId"] if chosen else None


def test_decide_follows_the_version_rule(pg) -> None:
    _world(pg)
    decided = {r["track_id"]: _picked(r) for r in open_reviews(pg, after="", limit=10)}
    assert decided == {"extended": "top-extended", "remix": None, "other-artist": None}


def test_decide_reaches_past_a_higher_scored_original(pg) -> None:
    # Don't Shut Up (ISHNLV Remix): the plain original tops the list and is refused.
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, mix_name, length_ms,"
        " created_at, updated_at) VALUES ('dsu', 'Don''t Shut Up', 'dont shut up',"
        " 'ISHNLV Remix', 201173, now(), now())"
    )
    candidates = [
        {
            "ref": {"videoId": "orig", "title": "Don't Shut Up", "duration_seconds": 197},
            "score": 0.9,
            "title_sim": 1.0,
            "artist_sim": 1.0,
            "duration_ok": False,
        },
        {
            "ref": {
                "videoId": "remix",
                "title": "Don't Shut Up (ISHNLV Remix)",
                "duration_seconds": 202,
            },
            "score": 0.817,
            "title_sim": 0.63,
            "artist_sim": 1.0,
            "duration_ok": True,
            "album_bonus": 0.05,
        },
    ]
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
        " created_at) VALUES ('q-dsu', 'dsu', 'ytmusic', CAST(:c AS jsonb), 'pending', now())",
        {"c": json.dumps(candidates)},
    )
    (row,) = open_reviews(pg, after="", limit=10)
    assert _picked(row) == "remix"


def test_accept_links_the_track_and_closes_its_review(pg) -> None:
    _world(pg)
    (row,) = [r for r in open_reviews(pg, after="", limit=10) if r["track_id"] == "extended"]
    row["candidate"] = decide(row)
    accept(pg, [row], NOW)
    (link,) = pg.execute(
        "SELECT vendor_track_id, match_type, confidence FROM vendor_track_map"
        " WHERE clouder_track_id = 'extended' AND vendor = 'ytmusic'"
    )
    assert (link["vendor_track_id"], link["match_type"]) == ("top-extended", "fuzzy_version")
    assert float(link["confidence"]) == 0.9
    (review,) = pg.execute(
        "SELECT status, resolved_at FROM match_review_queue WHERE id = 'q-extended'"
    )
    assert review["status"] == "resolved" and review["resolved_at"] is not None
    # The rest stays open, and a second pass finds nothing more to close here.
    assert {r["track_id"] for r in open_reviews(pg, after="", limit=10)} == {
        "remix",
        "other-artist",
    }

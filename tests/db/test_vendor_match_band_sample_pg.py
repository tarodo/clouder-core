"""Stratified sample of the open YT Music review queue, by the top candidate's score."""

from __future__ import annotations

import json

from collector.vendor_match.gold import review_band_sample

BANDS = [(0.90, 0.92), (0.85, 0.90), (0.70, 0.85)]


def _track(pg, tid: str, mix: str | None, length_ms: int) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, mix_name, length_ms, created_at, updated_at) "
        "VALUES (:id, 'Night Drive', 'night drive', :mix, :len, now(), now())",
        {"id": tid, "mix": mix, "len": length_ms},
    )
    pg.execute(
        "INSERT INTO clouder_track_artists (track_id, artist_id) VALUES (:id, 'ar1')", {"id": tid}
    )


def _review(pg, tid: str, top: float, status: str = "pending") -> None:
    candidates = [  # deliberately not sorted: the top one is picked by score
        {"ref": {"videoId": f"low-{tid}", "title": "Other"}, "score": 0.5},
        {
            "ref": {
                "videoId": f"top-{tid}",
                "title": "Night Drive (Radio Edit)",
                "artists": [{"name": "Zeta"}],
                "duration_seconds": 201,
            },
            "score": top,
            "title_sim": 1.0,
            "artist_sim": 1.0,
            "duration_ok": False,
        },
    ]
    pg.execute(
        "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
        "VALUES (:id, :tid, 'ytmusic', CAST(:c AS jsonb), :s, now())",
        {"id": f"q-{tid}", "tid": tid, "c": json.dumps(candidates), "s": status},
    )


def test_band_sample_buckets_open_reviews_by_top_score(pg) -> None:
    pg.execute(
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
        "VALUES ('ar1', 'Zeta', 'zeta', now(), now())"
    )
    for tid, mix, top in (
        ("a", "Extended Mix", 0.90),
        ("b", "XYZ Remix", 0.87),
        ("c", "Original Mix", 0.75),
        ("d", None, 0.40),
    ):
        _track(pg, tid, mix, 390_000)
        _review(pg, tid, top)
    _track(pg, "e", "Original Mix", 300_000)
    _review(pg, "e", 0.90, status="resolved")  # decided already: not in the sample

    rows = {r["track_id"]: r for r in review_band_sample(pg, BANDS, per_band=10)}

    assert {tid: r["band"] for tid, r in rows.items()} == {
        "a": "0.90-0.92",
        "b": "0.85-0.90",
        "c": "0.70-0.85",
    }
    a = rows["a"]
    assert (a["kind"], a["title"], a["mix_name"], a["artist"], a["duration_ms"]) == (
        "band_sample",
        "Night Drive",
        "Extended Mix",
        "Zeta",
        390_000,
    )
    assert a["score"] == 0.90 and a["duration_ok"] is False and a["title_sim"] == 1.0
    assert a["candidate"]["videoId"] == "top-a" and a["candidate_duration_ms"] == 201_000


def test_band_sample_caps_each_band(pg) -> None:
    pg.execute(
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
        "VALUES ('ar1', 'Zeta', 'zeta', now(), now())"
    )
    for i in range(5):
        _track(pg, f"t{i}", "Original Mix", 300_000)
        _review(pg, f"t{i}", 0.90)

    assert len(review_band_sample(pg, BANDS, per_band=3)) == 3

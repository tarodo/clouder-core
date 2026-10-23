"""ML repository on real PostgreSQL: labels (spec §4), models, predictions, retrain requests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from collector.repositories import ClouderRepository
from collector.user_deletion import delete_user

T0 = datetime(2026, 10, 1, tzinfo=UTC)
U, S = "u1", "st"
AUTO = ("NEW", "OLD", "NOT", "UNCLASSIFIED", "FAV")


def at(hours: float) -> datetime:
    return T0 + timedelta(hours=hours)


def _track(pg, tid: str, video: str | None = None, *, profiled=True, style="st") -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " VALUES (:id, :id, :id, :s, now(), now())",
        {"id": tid, "s": style},
    )
    if video:
        pg.execute(
            "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
            " confidence, matched_at, payload) VALUES (:id, 'ytmusic', :v, 'fuzzy', 0.950, now(),"
            " CAST('{}' AS jsonb))",
            {"id": tid, "v": video},
        )
    if video and profiled:
        _profile(pg, video)


def _profile(pg, video: str) -> None:
    pg.execute(
        "INSERT INTO audio_features (video_id, version, audio_sha256, created_at)"
        " VALUES (:v, 'light-1', repeat('a', 64), now()) ON CONFLICT DO NOTHING",
        {"v": video},
    )


def _block(pg, block: str, *, user=U, style=S, status="IN_PROGRESS", deleted=False, cats=()):
    pg.execute(
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at, deleted_at) VALUES (:b, :u, :s, :b, '2026-10-01', '2026-10-07',"
        " :st, now(), now(), CASE WHEN :d THEN now() END)",
        {"b": block, "u": user, "s": style, "st": status, "d": deleted},
    )
    for kind in ("DISCARD", *AUTO):
        pg.execute(
            "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
            " VALUES (:id, :b, :k, now())",
            {"id": f"{block}-{kind}", "b": block, "k": kind},
        )
    for cat, inactive in cats:
        pg.execute(
            "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, category_id, inactive,"
            " created_at) VALUES (:id, :b, 'STAGING', :c, :i, now())",
            {"id": f"{block}-{cat}", "b": block, "c": cat, "i": inactive},
        )


def _put(pg, bucket: str, track: str, when: datetime) -> None:
    pg.execute(
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES (:b, :t, :a)",
        {"b": bucket, "t": track, "a": when},
    )


def _cat(pg, category: str, track: str, when: datetime) -> None:
    pg.execute(
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES (:c, :t, :a)",
        {"c": category, "t": track, "a": when},
    )


@pytest.fixture
def repo(pg):
    pg.execute("TRUNCATE audio_features")
    for style in ("st", "st2"):
        pg.execute(
            "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
            " VALUES (:s, :s, :s, now(), now())",
            {"s": style},
        )
    for user in ("u1", "u2"):
        pg.execute(
            "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
            " VALUES (:u, :u, 'N', :e, now(), now())",
            {"u": user, "e": f"{user}@example.com"},
        )
    for cat, user, deleted in (
        ("ca", U, False),
        ("cb", U, False),
        ("cd", U, True),
        ("cx", "u2", False),
    ):
        pg.execute(
            "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
            " updated_at, deleted_at) VALUES (:c, :u, 'st', :c, :c, now(), now(),"
            " CASE WHEN :d THEN now() END)",
            {"c": cat, "u": user, "d": deleted},
        )
    _block(pg, "ob", cats=(("ca", False), ("cb", False), ("cd", True)))
    _block(pg, "fb", status="FINALIZED", cats=(("ca", False), ("cd", False)))
    _block(pg, "xb", deleted=True, cats=(("ca", False),))
    _block(pg, "s2", style="st2")
    _block(pg, "ub", user="u2", cats=(("cx", False),))
    yield ClouderRepository(pg)
    for user in ("u1", "u2"):
        delete_user(pg, user)
    pg.execute("TRUNCATE audio_features")


def _labels(repo, **kw) -> list[tuple]:
    return [
        (r["track_id"], r["video_id"], r["keep"], r["category_id"], r["added_at"])
        for r in repo.ml_labels(user_id=U, style_id=S, **kw)
    ]


def test_labels_keep_wins_and_latest_category(repo, pg) -> None:
    for t in ("d1", "k1", "k2", "k3", "k4", "k5"):
        _track(pg, t, f"v_{t}")
    _put(pg, "fb-DISCARD", "k1", at(0))
    _put(pg, "ob-ca", "k1", at(1))  # kept later in an open block: keep wins
    _cat(pg, "ca", "k2", at(0))
    _cat(pg, "cb", "k2", at(2))  # the latest category wins
    _put(pg, "fb-ca", "k3", at(0))
    _cat(pg, "ca", "k3", at(5))  # finalize copied it: the decision dates from the move
    _cat(pg, "cd", "k4", at(0))  # soft-deleted category: a keep, not a class
    _cat(pg, "cd", "k5", at(3))
    _cat(pg, "ca", "k5", at(1))  # a live category beats a later soft-deleted one
    _put(pg, "ob-DISCARD", "d1", at(2))
    _put(pg, "fb-DISCARD", "d1", at(1))
    assert _labels(repo) == [
        ("d1", "v_d1", False, None, at(1)),
        ("k1", "v_k1", True, "ca", at(1)),
        ("k2", "v_k2", True, "cb", at(2)),
        ("k3", "v_k3", True, "ca", at(0)),
        ("k4", "v_k4", True, None, at(0)),
        ("k5", "v_k5", True, "ca", at(1)),
    ]


def test_labels_exclude_ai_and_auto_buckets(repo, pg) -> None:
    for t in ("ok", "auto", "ai", "del", "ina", "oth", "sty", "nop"):
        _track(pg, t, f"v_{t}", profiled=t != "nop")
    _track(pg, "nov")
    _put(pg, "ob-DISCARD", "ok", at(0))
    for kind in AUTO:
        _put(pg, f"ob-{kind}", "auto", at(0))
    _put(pg, "ob-ca", "ai", at(0))
    pg.execute(
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result)"
        " VALUES ('ai', 'ai_lofcz', 'ok', 'v1', CAST('{\"ai_detected\": true}' AS jsonb))"
    )
    _put(pg, "xb-DISCARD", "del", at(0))  # deleted block
    _put(pg, "ob-cd", "ina", at(0))  # inactive staging bucket
    _put(pg, "ub-DISCARD", "oth", at(0))  # another user
    _put(pg, "s2-DISCARD", "sty", at(0))  # another style
    _put(pg, "ob-DISCARD", "nop", at(0))  # video without a profile
    _put(pg, "ob-DISCARD", "nov", at(0))  # no YouTube match
    assert [r[0] for r in _labels(repo)] == ["ok"]


def test_labels_use_current_video(repo, pg) -> None:
    _track(pg, "a", "vid_a")
    _put(pg, "ob-ca", "a", at(0))
    assert [r[:2] for r in _labels(repo)] == [("a", "vid_a")]
    pg.execute("UPDATE vendor_track_map SET vendor_track_id = 'vid_b' WHERE clouder_track_id = 'a'")
    assert _labels(repo) == []  # re-matched to an unprofiled video
    _profile(pg, "vid_b")
    assert [r[:2] for r in _labels(repo)] == [("a", "vid_b")]


def test_labels_paginate(repo, pg) -> None:
    for i in range(5):
        _track(pg, f"p{i}", f"v{i}")
        _put(pg, "ob-DISCARD", f"p{i}", at(i))
    pages, after = [], None
    while True:
        page = [r[0] for r in _labels(repo, after_track_id=after, limit=2)]
        pages.append(page)
        if len(page) < 2:
            break
        after = page[-1]
    assert pages == [["p0", "p1"], ["p2", "p3"], ["p4"]]


def _save(repo, expected: int, when: datetime, **over) -> bool:
    kw = {
        "n_labels": 140,
        "n_keep": 70,
        "keep_threshold": 0.5,
        "classes": ["ca", "cb"],
        "metrics": {"first_n": 0, "cv": {"keep_auc": 0.75}},
        "artifact_key": f"models/u1/st/v{expected + 1}.npz",
    }
    return repo.ml_save_model(
        user_id=U, style_id=S, expected_version=expected, now=when, **(kw | over)
    )


def test_save_model_optimistic(repo) -> None:
    assert repo.ml_model(user_id=U, style_id=S) is None
    assert _save(repo, 0, at(1))  # no row yet
    assert not _save(repo, 0, at(2))  # stale: another retrain saved v1 first
    assert repo.ml_model(user_id=U, style_id=S) == {
        "user_id": U,
        "version": 1,
        "trained_at": at(1),
        "retrain_requested_at": None,
        "n_labels": 140,
        "n_keep": 70,
        "keep_threshold": 0.5,
        "classes": ["ca", "cb"],
        "metrics": {"first_n": 0, "cv": {"keep_auc": 0.75}},
        "artifact_key": "models/u1/st/v1.npz",
    }
    repo.ml_request_retrain(user_id=U, style_id=S, now=at(3))
    assert _save(repo, 1, at(4), keep_threshold=None, classes=None)
    model = repo.ml_model(user_id=U, style_id=S)
    assert (model["version"], model["retrain_requested_at"]) == (2, None)
    assert (model["keep_threshold"], model["classes"]) == (None, None)
    repo.ml_request_retrain(user_id="u2", style_id=S, now=at(0))  # version 0: never trained
    assert [m["user_id"] for m in repo.ml_models_for_style(style_id=S)] == [U]


def _pred(score: float | None) -> dict:
    cats = None if score is None else [["ca", score], ["cb", 1 - score]]
    return {
        "track_id": "k1",
        "keep_score": score,
        "keep": None if score is None else score > 0.5,
        "categories": cats,
    }


def _upsert(repo, version: int, rows: list[dict], when: datetime) -> int:
    return repo.ml_upsert_predictions(
        user_id=U, style_id=S, model_version=version, rows=rows, now=when
    )


def test_upsert_never_downgrades_version(repo, pg) -> None:
    _track(pg, "k1", "v1")
    assert _upsert(repo, 2, [_pred(0.75)], at(1)) == 1
    assert _upsert(repo, 1, [_pred(0.25)], at(2)) == 0  # an older model's late page
    assert _upsert(repo, 2, [_pred(0.5)], at(2)) == 1  # a retried page of the same model
    assert repo.ml_predictions(user_id=U, style_id=S, track_ids=["k1"])["k1"]["keep_score"] == 0.5
    assert _upsert(repo, 2, [_pred(0.75)], at(2)) == 1
    stored = {
        "model_version": 2,
        "keep_score": 0.75,
        "keep": True,
        "categories": [["ca", 0.75], ["cb", 0.25]],
    }
    assert repo.ml_predictions(user_id=U, style_id=S, track_ids=["k1", "zz"]) == {"k1": stored}
    assert _upsert(repo, 3, [_pred(None)], at(3)) == 1
    assert repo.ml_predictions(user_id=U, style_id=S, track_ids=["k1"])["k1"] == {
        "model_version": 3,
        "keep_score": None,
        "keep": None,
        "categories": None,
    }


def test_upsert_predictions_in_chunks(repo, pg) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, created_at, updated_at)"
        " SELECT 'p' || i, 'p', 'p', 'st', now(), now() FROM generate_series(1, 250) i"
    )
    ids = [f"p{i}" for i in range(1, 251)]
    assert _upsert(repo, 1, [_pred(0.5) | {"track_id": t} for t in ids], at(0)) == 250
    assert len(repo.ml_predictions(user_id=U, style_id=S, track_ids=ids)) == 250


def test_request_retrain_dedupes_within_hour(repo, pg) -> None:
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(0))
    model = repo.ml_model(user_id=U, style_id=S)
    assert (model["version"], model["retrain_requested_at"]) == (0, at(0))
    assert not repo.ml_request_retrain(user_id=U, style_id=S, now=at(0.5))  # pending
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(1.5))  # an hour old: lost
    assert _save(repo, 0, at(1.6))  # the save clears the request
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(1.7))
    pg.execute("UPDATE ml_models SET trained_at = :t", {"t": at(1.9)})  # trained since
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(2))


def test_too_few_labels_restarts_the_count_of_a_new_pair(repo, pg) -> None:
    for t in ("a", "b"):
        _track(pg, t, f"v_{t}")
    _put(pg, "ob-DISCARD", "a", at(1))
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(2))
    assert repo.ml_labels_since_training(user_id=U, style_id=S) == 1
    repo.ml_mark_too_few_labels(user_id=U, style_id=S, now=at(2))  # labels read at 2
    model = repo.ml_model(user_id=U, style_id=S)
    assert (model["version"], model["trained_at"], model["retrain_requested_at"]) == (
        0,
        at(2),
        None,
    )
    assert repo.ml_labels_since_training(user_id=U, style_id=S) == 0
    _put(pg, "ob-DISCARD", "b", at(3))
    assert repo.ml_labels_since_training(user_id=U, style_id=S) == 1
    assert repo.ml_models_for_style(style_id=S) == []  # still no model
    repo.ml_mark_too_few_labels(user_id="u2", style_id=S, now=at(2))  # a hand-sent retrain
    assert repo.ml_model(user_id="u2", style_id=S)["trained_at"] == at(2)


def test_too_few_labels_never_touches_a_trained_model(repo) -> None:
    assert _save(repo, 0, at(1))
    assert repo.ml_request_retrain(user_id=U, style_id=S, now=at(2))
    repo.ml_mark_too_few_labels(user_id=U, style_id=S, now=at(3))
    model = repo.ml_model(user_id=U, style_id=S)
    assert (model["version"], model["trained_at"], model["retrain_requested_at"]) == (
        1,
        at(1),
        at(2),
    )


def test_labels_since_training_counts_moves(repo, pg) -> None:
    for t in ("a", "b", "c", "n", "ai", "del"):
        _track(pg, t, f"v_{t}")
    _put(pg, "fb-DISCARD", "a", at(1))
    _put(pg, "ob-ca", "b", at(2))
    _put(pg, "ob-DISCARD", "c", at(3))
    _put(pg, "ob-NEW", "n", at(3))
    _put(pg, "ob-DISCARD", "ai", at(3))
    pg.execute(
        "INSERT INTO track_analyses (track_id, analyzer, status, version, result)"
        " VALUES ('ai', 'ai_deezer', 'ok', 'v1', CAST('{\"ai_detected\": true}' AS jsonb))"
    )
    _put(pg, "xb-DISCARD", "del", at(3))
    _put(pg, "ub-DISCARD", "a", at(3))  # another user's block
    assert repo.ml_labels_since_training(user_id=U, style_id=S) == 3  # never trained
    _save(repo, 0, at(1.5))
    assert repo.ml_labels_since_training(user_id=U, style_id=S) == 2


def test_scoring_lookups(repo, pg) -> None:
    _track(pg, "s1", "vid1")
    _track(pg, "s2", "vid1")  # shares the video
    _track(pg, "s3", "vid3", profiled=False)
    _track(pg, "s4", "vid4", style="st2")
    _track(pg, "s5")
    assert repo.ml_style_tracks(style_id=S) == [
        {"track_id": "s1", "video_id": "vid1"},
        {"track_id": "s2", "video_id": "vid1"},
    ]
    assert repo.ml_style_tracks(style_id=S, after_track_id="s1", limit=1) == [
        {"track_id": "s2", "video_id": "vid1"}
    ]
    assert repo.ml_tracks_for_videos(video_ids=["vid1", "vid4", "nope"]) == [
        {"track_id": "s1", "video_id": "vid1", "style_id": "st"},
        {"track_id": "s2", "video_id": "vid1", "style_id": "st"},
        {"track_id": "s4", "video_id": "vid4", "style_id": "st2"},
    ]
    assert repo.ml_alive_categories(user_id=U, style_id=S) == ["ca", "cb"]


def test_trigger_context(repo) -> None:
    ctx = repo.ml_trigger_context
    assert ctx(user_id=U, block_id="ob", bucket_id="ob-DISCARD") == {
        "style_id": S,
        "bucket_type": "DISCARD",
    }
    assert ctx(user_id=U, block_id="ob", bucket_id="ob-ca")["bucket_type"] == "STAGING"
    assert ctx(user_id=U, block_id="ob", bucket_id="fb-NEW")["bucket_type"] == "NEW"  # a transfer
    assert ctx(user_id=U, block_id="s2", bucket_id=None) == {"style_id": "st2", "bucket_type": None}
    assert ctx(user_id="u2", block_id="ob", bucket_id=None) is None  # not hers

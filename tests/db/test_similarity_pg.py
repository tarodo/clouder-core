"""Similar tracks on real PostgreSQL + pgvector: the embeddings table, its writes, the ranked reads."""

from __future__ import annotations

import pytest


def _vec(*head: float, dims: int = 256) -> str:
    """A text vector: *head* then zeros."""
    return "[" + ",".join(str(x) for x in (*head, *[0.0] * (dims - len(head)))) + "]"


def test_audio_embeddings_holds_a_256_vector(pg) -> None:
    pg.execute("TRUNCATE audio_embeddings")
    pg.execute(
        "INSERT INTO audio_embeddings (video_id, version, embedding)"
        " VALUES ('v1', 'sim-1', CAST(:v AS vector))",
        {"v": _vec(1.0)},
    )
    (row,) = pg.execute("SELECT embedding <=> embedding AS d FROM audio_embeddings")
    assert row["d"] == 0
    with pytest.raises(Exception):
        pg.execute(
            "INSERT INTO audio_embeddings (video_id, version, embedding)"
            " VALUES ('v2', 'sim-1', CAST(:v AS vector))",
            {"v": _vec(1.0, dims=255)},
        )


@pytest.fixture
def repo(pg):
    from collector.repositories import ClouderRepository

    pg.execute("TRUNCATE audio_embeddings")
    pg.execute("TRUNCATE audio_features")
    yield ClouderRepository(pg)
    pg.execute("TRUNCATE audio_embeddings")
    pg.execute("TRUNCATE audio_features")


def test_similarity_upsert_writes_and_replaces(repo, pg) -> None:
    repo.similarity_upsert(version="sim-1", rows=[("v1", _vec(1.0)), ("v2", _vec(0.0, 1.0))])
    repo.similarity_upsert(version="sim-1", rows=[("v1", _vec(0.0, 0.0, 1.0))])
    rows = pg.execute(
        "SELECT video_id, embedding <=> CAST(:v AS vector) AS d FROM audio_embeddings"
        " WHERE version = 'sim-1' ORDER BY video_id",
        {"v": _vec(0.0, 0.0, 1.0)},
    )
    assert [(r["video_id"], round(r["d"], 6)) for r in rows] == [("v1", 0.0), ("v2", 1.0)]


def test_similarity_videos_pages_by_video_id(repo, pg) -> None:
    for v in ("vc", "va", "vb"):
        pg.execute(
            "INSERT INTO audio_features (video_id, version, audio_sha256, created_at)"
            " VALUES (:v, 'light-1', repeat('a', 64), now())",
            {"v": v},
        )
    assert repo.similarity_videos(after_video_id=None, limit=2) == ["va", "vb"]
    assert repo.similarity_videos(after_video_id="vb", limit=2) == ["vc"]


# ---- reads: GET /tracks/{id}/similar and GET /artists/{id}/similar ----

AUTO = ("NEW", "OLD", "NOT", "UNCLASSIFIED", "FAV")


def _planar(c: float) -> str:
    """A unit vector at cosine *c* from the seed axis [1, 0, …]: distance 1 - c."""
    return _vec(c, (1 - c * c) ** 0.5)


AXIS = _vec(0.0, 0.0, 1.0)  # orthogonal to the plane of the others

# track -> (style, video, vector, release date, artists); the seed is s, by artist a1
WORLD = {
    "s": ("st", "vs", _planar(1.0), "2024-01-01", ("a1",)),
    "s_dup": ("st", "vs", None, "2024-06-01", ()),  # the seed's video on a compilation
    "t_same": ("st", "v_same", _planar(0.95), "2024-01-01", ("a1",)),
    "t_ai": ("st", "v_ai", _planar(0.99), "2024-01-01", ("a2",)),
    "t_st2": ("st2", "v_st2", _planar(0.98), "2024-01-01", ("a2",)),
    "t_a": ("st", "v_a", _planar(0.9), "2024-01-01", ("a2",)),
    "t_disc": ("st", "v_disc", _planar(0.88), "2024-01-01", ("a2",)),
    "d_old": ("st", "vd", _planar(0.85), "2020-01-01", ("a3",)),
    "d_new": ("st", "vd", None, "2025-01-01", ("a3",)),
    "t_b": ("st", "v_b", _planar(0.8), "2024-01-01", ("a2",)),
    "t_both": ("st", "v_both", _planar(0.75), "2024-01-01", ("a2",)),
    "t_c": ("st", "v_c", _planar(0.7), "2024-01-01", ("a2",)),
    "t_far": ("st", "v_far", _planar(0.1), "2024-01-01", ("a2",)),
    "t_axis": ("st", "v_axis", AXIS, "2024-01-01", ("a2",)),
    "t_v0": ("st", "v_v0", None, "2024-01-01", ("a2",)),  # only a sim-0 vector
    "a1_ai": ("st", "v_a1_ai", AXIS, "2024-01-01", ("a1",)),  # flagged: not in the centroid
    "a1_st2": ("st2", "v_a1_st2", _planar(0.5), "2024-01-01", ("a1",)),
    "bot": ("st", "v_bot", _planar(0.6), "2024-01-01", ("abot",)),  # flagged, abot's only track
    "np": ("st", "v_np", None, "2024-01-01", ("a2",)),  # matched, never embedded
    "nostyle": (None, "v_nostyle", _planar(0.9), "2024-01-01", ("a2",)),
    # AI audio under an unchecked sibling: a flag on any track of a video drops the whole video
    "sib_ai": ("st", "v_sib", _planar(0.97), "2024-01-01", ("a2",)),
    "sib_ok": ("st", "v_sib", None, "2024-06-01", ("a2",)),
    "a1_sib": ("st", "v_a1_ai", None, "2024-06-01", ("a1",)),  # would pull a1's centroid off-plane
}
AI = ("t_ai", "a1_ai", "bot", "sib_ai")


@pytest.fixture
def similar(pg):
    from collector.similar_tracks import SimilarTracksRepository
    from collector.user_deletion import delete_user

    pg.execute("TRUNCATE audio_embeddings")
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at) VALUES"
        " ('st', 'DnB', 'dnb', now(), now()), ('st2', 'Techno', 'techno', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at) VALUES"
        " ('u1', 'sp1', 'N', 'u1@example.com', now(), now()),"
        " ('u2', 'sp2', 'M', 'u2@example.com', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) VALUES "
        + ", ".join(f"('{a}', '{a}', '{a}', now(), now())" for a in ("a1", "a2", "a3", "abot")),
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, position,"
        " created_at, updated_at) VALUES ('c1', 'u1', 'st', 'Rollers', 'rollers', 0, now(), now())",
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('b1', 'u1', 'st', 'W1', '2026-10-01', '2026-10-07',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at) VALUES "
        + ", ".join(f"('b1-{k}', 'b1', '{k}', now())" for k in ("DISCARD", *AUTO)),
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, category_id, inactive,"
        " created_at) VALUES ('b1-c1', 'b1', 'STAGING', 'c1', FALSE, now())",
    ]:
        pg.execute(sql)
    for t, (style, video, vector, released, artists) in WORLD.items():
        pg.execute(
            "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, publish_date,"
            " spotify_id, created_at, updated_at) VALUES (:t, :t, :t, :s, CAST(:d AS date),"
            " :sp, now(), now())",
            {"t": t, "s": style, "d": released, "sp": f"sp_{t}"},
        )
        pg.execute(
            "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
            " confidence, matched_at, payload) VALUES (:t, 'ytmusic', :v, 'fuzzy', 0.950, now(),"
            " CAST('{}' AS jsonb))",
            {"t": t, "v": video},
        )
        for a in artists:
            pg.execute(
                "INSERT INTO clouder_track_artists (track_id, artist_id, role)"
                " VALUES (:t, :a, 'main')",
                {"t": t, "a": a},
            )
        if vector:
            pg.execute(
                "INSERT INTO audio_embeddings (video_id, version, embedding)"
                " VALUES (:v, 'sim-1', CAST(:e AS vector))",
                {"v": video, "e": vector},
            )
    pg.execute(
        "INSERT INTO audio_embeddings (video_id, version, embedding)"
        " VALUES ('v_v0', 'sim-0', CAST(:e AS vector))",
        {"e": _planar(0.999)},
    )
    for t in AI:
        pg.execute(
            "INSERT INTO track_analyses (track_id, analyzer, status, version, result)"
            " VALUES (:t, 'ai_lofcz', 'ok', 'v1', CAST('{\"ai_detected\": true}' AS jsonb))",
            {"t": t},
        )
    # u1: d_new and t_both in the category, t_both and t_disc in DISCARD, t_c staged
    for sql in [
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES"
        " ('c1', 'd_new', now()), ('c1', 't_both', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES"
        " ('b1-DISCARD', 't_disc', now()), ('b1-DISCARD', 't_both', now()),"
        " ('b1-c1', 't_c', now())",
        # the model: t_b and the discarded t_disc predicted keeps, t_a not
        "INSERT INTO track_predictions (user_id, style_id, track_id, model_version, keep_score,"
        " keep, categories, scored_at) VALUES"
        " ('u1', 'st', 't_b', 1, 0.9, TRUE, NULL, now()),"
        " ('u1', 'st', 't_disc', 1, 0.9, TRUE, NULL, now()),"
        " ('u1', 'st', 't_a', 1, 0.1, FALSE, NULL, now())",
    ]:
        pg.execute(sql)
    yield SimilarTracksRepository(pg)
    pg.execute("TRUNCATE audio_embeddings")
    delete_user(pg, "u1")
    delete_user(pg, "u2")


def _ids(body) -> list[str]:
    return [t["id"] for t in body["items"]]


U1_ORDER = ["d_new", "t_b", "t_both", "t_c", "t_same", "t_a", "t_disc", "t_far", "t_axis"]


def test_keep_group_first_then_distance(similar) -> None:
    body = similar.for_track(track_id="s", user_id="u1")
    assert body["profiled"] is True and body["seed"]["id"] == "s"
    # keeps: placed in the category (d_new, t_both), staged (t_c), predicted (t_b);
    # t_disc is predicted keep but DISCARD-only: the user's call wins
    assert _ids(body) == U1_ORDER


def test_track_results_stay_in_style_and_skip_ai(similar) -> None:
    ids = _ids(similar.for_track(track_id="s", user_id="u2"))
    assert not {"t_ai", "t_st2", "a1_ai", "bot", "a1_st2", "nostyle"} & set(ids)


def test_track_excludes_seed_and_its_video_keeps_same_artist(similar) -> None:
    ids = _ids(similar.for_track(track_id="s", user_id="u2"))
    assert "s" not in ids and "s_dup" not in ids and "t_same" in ids


def test_one_row_per_video_prefers_placed_track_then_earliest_release(similar) -> None:
    assert "d_new" in _ids(similar.for_track(track_id="s", user_id="u1"))  # u1 placed it
    u2 = _ids(similar.for_track(track_id="s", user_id="u2"))
    assert "d_old" in u2 and "d_new" not in u2  # nobody's: the original release


def test_no_model_orders_by_distance(similar) -> None:
    # u2 has no decisions and no model: pure similarity
    assert _ids(similar.for_track(track_id="s", user_id="u2")) == [
        "t_same", "t_a", "t_disc", "d_old", "t_b", "t_both", "t_c", "t_far", "t_axis",
    ]  # fmt: skip


def test_discarded_flag(similar) -> None:
    by_id = {t["id"]: t for t in similar.for_track(track_id="s", user_id="u1")["items"]}
    assert by_id["t_disc"]["discarded"] is True  # DISCARD only
    assert by_id["t_both"]["discarded"] is False  # DISCARD + a category: kept
    assert by_id["t_both"]["categories"] == [{"id": "c1", "name": "Rollers"}]
    assert by_id["t_a"]["discarded"] is False


def test_unprofiled_seed_or_styleless_seed_gives_profiled_false(similar) -> None:
    for seed in ("np", "nostyle", "t_v0"):
        body = similar.for_track(track_id=seed, user_id="u1")
        assert (body["seed"]["id"], body["profiled"], body["items"]) == (seed, False, [])
    assert similar.for_track(track_id="nobody", user_id="u1") == {
        "seed": None,
        "profiled": False,
        "items": [],
    }


def test_other_version_rows_are_ignored(similar) -> None:
    assert "t_v0" not in _ids(similar.for_track(track_id="s", user_id="u2"))


def test_limit(similar) -> None:
    body = similar.for_track(track_id="s", user_id="u2", limit=3)
    assert _ids(body) == ["t_same", "t_a", "t_disc"]


def test_artist_centroid_excludes_artists_tracks_and_ai(similar) -> None:
    body = similar.for_artist(artist_id="a1", user_id="u1", style_id=None)
    assert body["profiled"] is True and body["style"] == {"id": "st", "name": "DnB"}
    # a1's own tracks (s, t_same, a1_ai) and the seed video's s_dup are out; an AI track in the
    # centroid would pull t_axis ahead of t_far
    assert _ids(body) == [t for t in U1_ORDER if t != "t_same"]


def test_artist_default_style_is_most_profiled(similar) -> None:
    body = similar.for_artist(artist_id="a1", user_id="u2", style_id=None)
    # the flagged a1_ai does not count
    assert body["styles"] == [
        {"id": "st", "name": "DnB", "count": 2},
        {"id": "st2", "name": "Techno", "count": 1},
    ]
    st2 = similar.for_artist(artist_id="a1", user_id="u2", style_id="st2")
    assert st2["style"] == {"id": "st2", "name": "Techno"} and _ids(st2) == ["t_st2"]


def test_artist_all_ai_is_unprofiled(similar) -> None:
    assert similar.for_artist(artist_id="abot", user_id="u1", style_id=None) == {
        "profiled": False,
        "style": None,
        "styles": [],
        "items": [],
    }


def test_artist_unknown_style_lists_styles(similar) -> None:
    body = similar.for_artist(artist_id="a1", user_id="u1", style_id="st3")
    assert (body["profiled"], body["style"], body["items"]) == (False, None, [])
    assert [s["id"] for s in body["styles"]] == ["st", "st2"]

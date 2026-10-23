"""Migration 45: feature store and model tables; per-user rows cascade with the user."""

from __future__ import annotations


def test_tables_exist_and_cascade(pg) -> None:
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())"
    )
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " created_at, updated_at) VALUES ('t1', 't', 't', 'st', 200000, now(), now())"
    )
    pg.execute(
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())"
    )
    pg.execute(
        "INSERT INTO audio_features (video_id, version, audio_sha256, created_at)"
        " VALUES ('v1', 'light-1', repeat('a', 64), now())"
    )
    pg.execute("INSERT INTO ml_models (user_id, style_id) VALUES ('u1', 'st')")
    pg.execute(
        "INSERT INTO track_predictions (user_id, style_id, track_id, model_version, scored_at)"
        " VALUES ('u1', 'st', 't1', 1, now())"
    )
    pg.execute("DELETE FROM users WHERE id = 'u1'")
    assert pg.execute("SELECT count(*) AS n FROM ml_models")[0]["n"] == 0
    assert pg.execute("SELECT count(*) AS n FROM track_predictions")[0]["n"] == 0

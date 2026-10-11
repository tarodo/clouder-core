"""Migration 36 hands back the rows a deadline-cut Spotify batch left stamped."""

from __future__ import annotations

import importlib.util
from pathlib import Path

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "20261010_36_release_aborted_spotify_batch.py"
)


def _sql() -> str:
    spec = importlib.util.spec_from_file_location("m36", MIGRATION)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RELEASE_SQL


def _track(pg, tid: str, searched_at: str, spotify_id: str | None) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, isrc, style_id, spotify_id,"
        " spotify_searched_at, created_at, updated_at)"
        " VALUES (:id, 'T', 't', :id, 'st', :sid, CAST(:at AS timestamptz), now(), now())",
        {"id": tid, "sid": spotify_id, "at": searched_at},
    )


def test_only_the_orphans_of_the_cut_batch_go_back(pg) -> None:
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())"
    )
    _track(pg, "orphan", "2026-10-10 13:56:57+00", None)  # claimed, never searched
    _track(pg, "found", "2026-10-10 13:56:57+00", "sp1")  # (defensive) linked rows stay
    _track(pg, "not-found", "2026-10-10 14:11:08+00", None)  # searched by the batch: stays
    _track(pg, "other-day", "2026-10-09 13:56:57+00", None)  # outside the window

    pg.execute(_sql())

    rows = {
        r["id"]: r["spotify_searched_at"]
        for r in pg.execute("SELECT id, spotify_searched_at FROM clouder_tracks ORDER BY id")
    }
    assert rows["orphan"] is None
    assert all(rows[t] is not None for t in ("found", "not-found", "other-day"))

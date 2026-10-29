"""AI reputation of labels and artists: the stored counts, the generated level (spec: 1 = at least one,
2 = 25-50%, 3 = over half of the checked tracks) and the backfill."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

MIGRATION = Path(__file__).parents[2] / "alembic/versions/20261029_46_ai_reputation.py"


def _migration():
    spec = importlib.util.spec_from_file_location("m46", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _label(pg, label_id: str = "lbl") -> None:
    pg.execute(
        "INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)"
        f" VALUES ('{label_id}', '{label_id}', '{label_id}', now(), now())"
    )


@pytest.mark.parametrize(
    ("ai", "checked", "level"),
    [(0, 4, None), (1, 5, 1), (1, 4, 2), (2, 4, 2), (3, 5, 3), (1, 1, 3)],
)
def test_level_boundaries(pg, ai, checked, level) -> None:
    _label(pg)
    pg.execute(
        "UPDATE clouder_labels SET ai_tracks = :ai, ai_checked = :checked WHERE id = 'lbl'",
        {"ai": ai, "checked": checked},
    )
    assert (
        pg.execute("SELECT ai_level FROM clouder_labels WHERE id = 'lbl'")[0]["ai_level"] == level
    )


def test_backfill_counts(pg) -> None:
    _label(pg)
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO clouder_albums (id, title, normalized_title, label_id, created_at, updated_at)"
        " VALUES ('alb', 'A', 'a', 'lbl', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) VALUES"
        " ('main', 'M', 'm', now(), now()), ('remixer', 'R', 'r', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, album_id, created_at,"
        " updated_at) VALUES "
        + ", ".join(f"('{t}', '{t}', '{t}', 'st', 'alb', now(), now())" for t in "abcd"),
        "INSERT INTO clouder_track_artists (track_id, artist_id, role) VALUES ('a', 'main', 'main'),"
        " ('b', 'main', 'main'), ('c', 'main', 'main'), ('d', 'main', 'main'), ('a', 'remixer', 'remixer')",
        # a: ok + flagged, b: ok clean, c: failed (not checked), d: never analysed
        "INSERT INTO track_analyses (track_id, analyzer, status, result, created_at, updated_at) VALUES"
        " ('a', 'ai_lofcz', 'ok', '{\"ai_detected\": true}', now(), now()),"
        " ('b', 'ai_lofcz', 'ok', '{\"ai_detected\": false}', now(), now()),"
        " ('c', 'ai_deezer', 'failed', NULL, now(), now())",
    ]:
        pg.execute(sql)
    m = _migration()
    pg.execute(m.BACKFILL_LABELS)
    pg.execute(m.BACKFILL_ARTISTS)

    def counts(table: str, entity: str) -> tuple:
        r = pg.execute(
            f"SELECT ai_total, ai_checked, ai_tracks, ai_level FROM {table} WHERE id = '{entity}'"
        )[0]
        return (r["ai_total"], r["ai_checked"], r["ai_tracks"], r["ai_level"])

    assert counts("clouder_labels", "lbl") == (4, 2, 1, 2)
    assert counts("clouder_artists", "main") == (4, 2, 1, 2)
    assert counts("clouder_artists", "remixer") == (1, 1, 1, 3)

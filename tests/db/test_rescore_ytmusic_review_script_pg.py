"""scripts/rescore_ytmusic_review.py: a dry run changes nothing, --apply closes."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "rescore_ytmusic_review.py"


def _main():
    spec = importlib.util.spec_from_file_location("rescore_ytmusic_review", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def _seed(pg) -> None:
    pg.execute(
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
        "VALUES ('ar1', 'Zeta', 'zeta', now(), now())"
    )
    for tid, mix in (("t1", "Extended Mix"), ("t2", "Zeta Remix")):
        pg.execute(
            "INSERT INTO clouder_tracks (id, title, normalized_title, mix_name, length_ms,"
            " created_at, updated_at) VALUES (:id, 'Night Drive', 'night drive', :mix, 390000,"
            " now(), now())",
            {"id": tid, "mix": mix},
        )
        pg.execute(
            "INSERT INTO clouder_track_artists (track_id, artist_id) VALUES (:id, 'ar1')",
            {"id": tid},
        )
        candidates = [
            {
                "ref": {
                    "videoId": f"v-{tid}",
                    "title": "Night Drive",
                    "artists": [{"name": "Zeta"}],
                    "duration_seconds": 201,
                },
                "score": 0.9,
                "title_sim": 1.0,
                "artist_sim": 1.0,
                "duration_ok": False,
            }
        ]
        pg.execute(
            "INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status,"
            " created_at) VALUES (:id, :t, 'ytmusic', CAST(:c AS jsonb), 'pending', now())",
            {"id": f"q-{tid}", "t": tid, "c": json.dumps(candidates)},
        )


def _links(pg) -> int:
    return pg.execute("SELECT count(*) AS n FROM vendor_track_map WHERE vendor = 'ytmusic'")[0]["n"]


def test_dry_run_lists_and_changes_nothing(pg, tmp_path) -> None:
    _seed(pg)
    out = tmp_path / "rescore.csv"
    summary = _main()(["--database-url", os.environ["TEST_DATABASE_URL"], "--csv", str(out)])
    assert summary == {"open_reviews": 2, "accepted": 1, "applied": 0}
    assert _links(pg) == 0
    (row,) = list(csv.DictReader(out.open(encoding="utf-8")))
    assert row["ours"] == "Zeta — Night Drive (Extended Mix) · 6:30"
    assert row["candidate"] == "Zeta — Night Drive · 3:21"
    assert row["url"] == "https://music.youtube.com/watch?v=v-t1"


def test_apply_closes_what_the_rule_accepts(pg) -> None:
    _seed(pg)
    summary = _main()(["--database-url", os.environ["TEST_DATABASE_URL"], "--apply"])
    assert summary == {"open_reviews": 2, "accepted": 1, "applied": 1}
    assert _links(pg) == 1
    statuses = {
        r["id"]: r["status"] for r in pg.execute("SELECT id, status FROM match_review_queue")
    }
    assert statuses == {"q-t1": "resolved", "q-t2": "pending"}

"""scripts/export_match_gold.py writes the band sample to the gold file and the labels CSV."""

from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "export_match_gold.py"


def _main():
    spec = importlib.util.spec_from_file_location("export_match_gold", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.main


def test_band_sample_lands_in_the_gold_file_and_the_labels(pg, tmp_path) -> None:
    pg.execute("INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at) "
               "VALUES ('ar1', 'Zeta', 'zeta', now(), now())")
    pg.execute("INSERT INTO clouder_tracks (id, title, normalized_title, mix_name, length_ms, created_at, updated_at) "
               "VALUES ('t1', 'Night Drive', 'night drive', 'Extended Mix', 390000, now(), now())")
    pg.execute("INSERT INTO clouder_track_artists (track_id, artist_id) VALUES ('t1', 'ar1')")
    candidates = [{"ref": {"videoId": "v1", "title": "Night Drive", "artists": [{"name": "Zeta"}],
                           "duration_seconds": 201}, "score": 0.9, "duration_ok": False}]
    pg.execute("INSERT INTO match_review_queue (id, clouder_track_id, vendor, candidates, status, created_at) "
               "VALUES ('q1', 't1', 'ytmusic', CAST(:c AS jsonb), 'pending', now())",
               {"c": json.dumps(candidates)})

    gold, labels = _main()(["--database-url", os.environ["TEST_DATABASE_URL"],
                            "--out-dir", str(tmp_path), "--band-sample", "5"])

    records = [json.loads(line) for line in gold.read_text().splitlines()]
    assert [r["band"] for r in records if r["kind"] == "band_sample"] == ["0.90-0.92"]
    (row,) = [r for r in csv.DictReader(labels.read_text().splitlines()) if r["band"]]
    assert row["track_id"] == "t1" and row["label"] == ""
    assert row["query"] == "Zeta — Night Drive (Extended Mix) · 6:30"
    assert row["candidate"] == "Zeta — Night Drive · 3:21"
    assert row["url"] == "https://music.youtube.com/watch?v=v1"

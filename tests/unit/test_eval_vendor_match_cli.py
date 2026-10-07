"""scripts/eval_vendor_match.py end to end on a tiny gold file."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_vendor_match.py"


def test_cli_prints_report_and_writes_it(tmp_path, monkeypatch, capsys) -> None:
    gold = tmp_path / "match_gold_test.jsonl"
    records = [
        {"kind": "review_accept", "track_id": "t1", "artist": "Artist A", "title": "Night Drive",
         "duration_ms": 300000, "album": None, "chosen_id": "v1",
         "candidates": [{"videoId": "v1", "title": "Night Drive", "artists": [{"name": "Artist A"}],
                         "duration_seconds": 300}]},
        {"kind": "duplicate_artists", "name_groups": 2, "artists_in_groups": 5,
         "groups_with_non_beatport_artist": 0},
    ]
    gold.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    out = tmp_path / "report.md"
    monkeypatch.setattr(sys, "argv", ["eval_vendor_match.py", str(gold), "--out", str(out)])

    runpy.run_path(str(SCRIPT), run_name="__main__")

    printed = capsys.readouterr().out
    assert "Gold items: 1" in printed
    assert "2 name groups (5 artists)" in printed
    assert out.read_text() == printed

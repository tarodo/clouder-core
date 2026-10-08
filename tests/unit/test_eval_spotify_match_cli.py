"""scripts/eval_spotify_match.py end to end on a tiny labelled gold file."""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "eval_spotify_match.py"


def test_cli_prints_precision_and_recall(tmp_path, monkeypatch, capsys) -> None:
    gold = tmp_path / "spotify_gold_test.jsonl"
    records = [
        {"kind": "match", "tier": "isrc", "track_id": "t1"},
        {"kind": "match", "tier": "metadata", "track_id": "t2"},
        {"kind": "not_found", "track_id": "t3"},
        {"kind": "population", "isrc": 90, "isrc_neighbour": 0, "metadata": 10, "no_payload": 0, "not_found": 10},
    ]
    gold.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    labels = tmp_path / "labels.csv"
    labels.write_text("track_id,kind,tier,query,candidate,url,label\nt1,,,,,,y\nt2,,,,,,n\nt3,,,,,,n\n")
    monkeypatch.setattr(sys, "argv", ["eval_spotify_match.py", str(gold), "--labels", str(labels)])

    runpy.run_path(str(SCRIPT), run_name="__main__")

    out = capsys.readouterr().out
    assert "| isrc | 90 | 1 | 1 | 100.0% |" in out
    assert "| metadata | 10 | 1 | 0 | 0.0% |" in out
    assert "recall ≈ 90.0%" in out  # 90 found / (90 + 10 missed)

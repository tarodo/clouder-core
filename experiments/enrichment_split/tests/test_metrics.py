import json
from pathlib import Path

from splitlab.metrics import summarize


def write_cell(run_dir: Path, name: str, payload: dict):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / name).write_text(json.dumps(payload))


def test_summarize_fill_and_instagram_rates(tmp_path: Path):
    run_dir = tmp_path / "r1"
    write_cell(run_dir, "label__l1.json", {
        "entity": {"stratum": "ig_missing", "baseline": {"tagline": "x", "instagram_url": None}},
        "merged": {"tagline": "t", "instagram_url": "https://www.instagram.com/a"},
        "provenance": {"instagram_url": "profiles_tier2"},
        "cost_usd": 0.03, "latency_ms": 1000, "kind": "label", "error": None,
    })
    write_cell(run_dir, "label__l2.json", {
        "entity": {"stratum": "random",
                   "baseline": {"tagline": "y", "instagram_url": "https://www.instagram.com/b"}},
        "merged": {"tagline": None, "instagram_url": None},
        "provenance": {},
        "cost_usd": 0.02, "latency_ms": 2000, "kind": "label", "error": None,
    })
    s = summarize(run_dir)
    lab = s["label"]
    assert lab["fill_rates"]["tagline"]["new"] == 0.5
    assert lab["fill_rates"]["tagline"]["baseline"] == 1.0
    assert lab["instagram"]["found_rate"] == 0.5
    assert lab["instagram"]["found_rate_ig_missing_stratum"] == 1.0
    assert lab["instagram"]["regression_lost"] == 1
    assert lab["instagram"]["tiers"] == {"tier2": 1}
    assert abs(lab["avg_cost_usd"] - 0.025) < 1e-9

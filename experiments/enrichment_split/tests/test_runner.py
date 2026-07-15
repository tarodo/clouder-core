import json
from pathlib import Path

from splitlab.config import Settings
from splitlab.facts_pass import FactsResult
from splitlab.narrative_pass import NarrativeResult
from splitlab.runner import run_experiment

SETTINGS = Settings(openai_api_key="x", tavily_api_key="y")

SAMPLE = {
    "labels": [
        {"id": "l1", "name": "Defiant", "style": "dnb", "stratum": "ig_missing",
         "baseline": {"instagram_url": None}, "sample_tracks": [], "known_labels": []},
    ],
    "artists": [],
}


def fake_narrative(entity, kind, llm, model, max_tool_calls):
    return NarrativeResult(narrative={"tagline": "t", "summary": "s"}, web_search_calls=2)


def fake_facts(entity, kind, tavily, llm, model):
    return FactsResult(facts={"founded_year": 2001},
                       profiles={"instagram_url": "https://www.instagram.com/d"},
                       instagram_tier=1, credits=1)


class FakeTavily:
    credits_used = 1


def test_run_experiment_writes_cells_and_manifest(tmp_path: Path):
    run_id = run_experiment(
        SAMPLE, SETTINGS, cap=2, kinds=["label", "artist"], limit=None,
        outputs_root=tmp_path, narrative_fn=fake_narrative, facts_fn=fake_facts,
        llm=object(), tavily_factory=lambda: FakeTavily(),
    )
    run_dir = tmp_path / run_id
    cell = json.loads((run_dir / "label__l1.json").read_text())
    assert cell["merged"]["tagline"] == "t"
    assert cell["merged"]["instagram_url"] == "https://www.instagram.com/d"
    assert abs(cell["cost_usd"] - (2 * 0.01 + 1 * 0.008)) < 1e-9
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["cap"] == 2
    assert manifest["totals"]["entities"] == 1
    assert manifest["totals"]["web_search_calls"] == 2
    assert manifest["totals"]["tavily_credits"] == 1

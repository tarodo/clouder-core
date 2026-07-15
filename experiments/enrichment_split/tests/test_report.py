from splitlab.report import render


def test_render_contains_gate_verdicts():
    summary = {
        "label": {
            "fill_rates": {"tagline": {"new": 0.98, "baseline": 0.99},
                           "notable_artists": {"new": 0.92, "baseline": 0.95},
                           "founded_year": {"new": 0.70, "baseline": 0.67},
                           "catalog_size_estimate": {"new": 0.55, "baseline": 0.52}},
            "instagram": {"found_rate": 0.7, "found_rate_ig_missing_stratum": 0.6,
                          "regression_lost": 0, "tiers": {"tier1": 10}},
            "avg_cost_usd": 0.021, "latency_p50_ms": 9000, "errors": 0, "entities": 50,
        },
        "artist": {
            "fill_rates": {"tagline": {"new": 0.99, "baseline": 0.99},
                           "notable_releases": {"new": 0.9, "baseline": 0.9}},
            "instagram": {"found_rate": 0.65, "found_rate_ig_missing_stratum": 0.5,
                          "regression_lost": 1, "tiers": {"tier3": 5}},
            "avg_cost_usd": 0.019, "latency_p50_ms": 8000, "errors": 0, "entities": 50,
        },
    }
    manifest = {"run_id": "r1", "cap": 2,
                "totals": {"cost_usd": 2.0, "web_search_calls": 100, "tavily_credits": 80}}
    md = render(summary, manifest)
    assert "PASS" in md and "gate" in md.lower()
    assert "0.70" in md or "70" in md   # ig found-rate visible
    assert "tier1" in md

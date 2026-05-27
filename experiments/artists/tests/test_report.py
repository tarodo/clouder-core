import json
from pathlib import Path


def _write_cell(run_dir: Path, prompt: str, vendor: str, fixture_id: str, parsed: dict, error: str | None = None) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_dir.name,
        "prompt": {"slug": prompt, "version": "v1"},
        "vendor": {"name": vendor, "model": f"{vendor}-model"},
        "fixture": {
            "id": fixture_id,
            "artist_name": parsed.get("artist_name", fixture_id),
            "style": "techno",
            "sample_tracks": [],
            "known_labels": [],
            "ground_truth": {"country": "Brazil", "active_since": 2010, "ai_content_expected": "none_detected"}
            if fixture_id == "anna"
            else None,
        },
        "rendered_user_prompt": "...",
        "response": {
            "parsed": None if error else parsed,
            "citations": ["https://example.com"],
            "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
            "latency_ms": 1234,
            "raw": {},
        },
        "error": error,
    }
    (run_dir / f"{prompt}__{vendor}__{fixture_id}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _write_manifest(run_dir: Path, ok: int, err: int, cost: float) -> None:
    manifest = {
        "run_id": run_dir.name,
        "started_at": "2026-05-26T10:00:00+00:00",
        "finished_at": "2026-05-26T10:01:00+00:00",
        "prompts": [{"slug": "artist_v1", "version": "v1"}],
        "vendors": [{"name": "openai", "model": "gpt-5.4-mini"}, {"name": "perplexity", "model": "sonar"}],
        "fixtures": ["anna"],
        "totals": {"cells": ok + err, "ok": ok, "error": err, "cost_usd": cost},
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def test_build_report_renders_sections(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-100000-abcd"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "Brazilian techno DJ.", "confidence": 0.9, "notable_releases": ["Hidden Beauties"],
    })
    _write_cell(run_dir, "artist_v1", "perplexity", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2008,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "DJ.", "confidence": 0.7, "notable_releases": [],
    })
    _write_manifest(run_dir, ok=2, err=0, cost=0.002)

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert out_path.name.startswith("20260526-100000-abcd")
    assert "## Summary" in text
    assert "ok: 2" in text
    assert "## Fixture: anna" in text
    assert "2010 ✓" in text
    assert "2008 ✗" in text
    assert "Brazil ✓" in text
    assert "<details>" in text
    assert "—" in text
    assert "openai-model" in text
    assert "perplexity-model" in text


def _write_merged(run_dir: Path, prompt: str, fixture_id: str, merged_payload: dict, source_cells: list[dict], meta: dict) -> None:
    merged_dir = run_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    (merged_dir / f"{prompt}__{fixture_id}.json").write_text(json.dumps({
        "run_id": run_dir.name,
        "merged_at": "2026-05-26T20:00:00+00:00",
        "prompt": {"slug": prompt, "version": "v1"},
        "fixture": {
            "id": fixture_id, "artist_name": merged_payload.get("artist_name", fixture_id),
            "style": "techno", "sample_tracks": [], "known_labels": [],
            "ground_truth": {"country": "Brazil", "active_since": 2010, "ai_content_expected": "none_detected"} if fixture_id == "anna" else None,
        },
        "source_cells": source_cells,
        "merged": merged_payload,
        "merge_meta": meta,
        "aggregate_cost_usd": meta.get("narrative_cost_usd", 0.0),
    }, indent=2, ensure_ascii=False), encoding="utf-8")


def test_build_report_renders_aggregated_section(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-200000-test"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "Techno DJ.", "confidence": 0.9, "notable_releases": ["Hidden Beauties"],
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    _write_merged(run_dir, "artist_v1", "anna",
        merged_payload={
            "artist_name": "ANNA",
            "tagline": "Brazilian techno force.",
            "country": "Brazil",
            "active_since": 2010,
            "ai_content": "none_detected",
            "confidence": 0.95,
            "notable_releases": ["Hidden Beauties", "Forsaken"],
            "spotify_url": "https://open.spotify.com/artist/abc",
            "summary": "Merged summary.",
            "ai_reasoning": "—",
        },
        source_cells=[
            {"vendor": "openai", "model": "gpt-5.4-mini", "confidence": 0.9},
            {"vendor": "perplexity", "model": "sonar", "confidence": 1.0},
        ],
        meta={
            "field_provenance": {
                "active_since": "median:2010",
                "country": "majority(2/2)",
                "tagline": "deepseek narrative",
            },
            "narrative_cost_usd": 0.0004,
            "narrative_latency_ms": 4200,
        },
    )

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert "## Aggregated (consensus)" in text
    assert "anna — artist_v1" in text
    assert "Brazilian techno force." in text
    assert "median:2010" in text
    assert "2010 ✓" in text
    assert "Brazil ✓" in text


def test_build_report_no_aggregated_section_when_merged_dir_absent(tmp_path):
    from artlab.report import build_report

    run_dir = tmp_path / "outputs" / "20260526-201000-test"
    reports_dir = tmp_path / "reports"
    _write_cell(run_dir, "artist_v1", "openai", "anna", {
        "artist_name": "ANNA", "country": "Brazil", "active_since": 2010,
        "ai_content": "none_detected", "ai_reasoning": "—",
        "summary": "x", "confidence": 0.9, "notable_releases": [],
    })
    _write_manifest(run_dir, ok=1, err=0, cost=0.001)

    text = build_report(run_dir, reports_dir).read_text()
    assert "## Aggregated" not in text

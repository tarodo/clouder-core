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
            "label_name": parsed.get("label_name", fixture_id),
            "style": "techno",
            "release_name": None,
            "ground_truth": {"founded_year": 1996, "country": "Sweden", "parent_label": None, "ai_content_expected": "none_detected"}
            if fixture_id == "drumcode"
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
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _write_manifest(run_dir: Path, ok: int, err: int, cost: float) -> None:
    manifest = {
        "run_id": run_dir.name,
        "started_at": "2026-05-17T10:00:00+00:00",
        "finished_at": "2026-05-17T10:01:00+00:00",
        "prompts": [{"slug": "label_v1_baseline", "version": "v1"}, {"slug": "label_v2_facts", "version": "v1"}],
        "vendors": [{"name": "anthropic", "model": "claude-sonnet-4-6"}, {"name": "xai", "model": "grok-4"}],
        "fixtures": ["drumcode"],
        "totals": {"cells": ok + err, "ok": ok, "error": err, "cost_usd": cost},
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def test_build_report_renders_sections(tmp_path):
    from lab.report import build_report

    run_dir = tmp_path / "outputs" / "20260517-100000-abcd"
    reports_dir = tmp_path / "reports"

    _write_cell(run_dir, "label_v1_baseline", "anthropic", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label.", "confidence": 0.9, "notable_artists": ["Adam Beyer"]})
    _write_cell(run_dir, "label_v1_baseline", "xai", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1995, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label.", "confidence": 0.7, "notable_artists": []})
    _write_cell(run_dir, "label_v2_facts", "anthropic", "drumcode",
                {"label_name": "Drumcode", "founded_year": 1996, "country": "Sweden",
                 "ai_content": "none_detected", "ai_reasoning": "—",
                 "summary": "Techno label, with sourced facts.", "confidence": 0.95,
                 "notable_artists": ["Adam Beyer", "Joel Mull"]})
    _write_cell(run_dir, "label_v2_facts", "xai", "drumcode",
                {}, error="simulated failure")

    _write_manifest(run_dir, ok=3, err=1, cost=0.0041)

    out_path = build_report(run_dir, reports_dir)
    text = out_path.read_text(encoding="utf-8")

    assert out_path.name.startswith("20260517-100000-abcd")
    assert "## Summary" in text
    assert "ok: 3" in text
    assert "error: 1" in text
    assert "## Fixture: drumcode" in text
    # ground truth check: 1996 matches → ✓; 1995 → ✗
    assert "1996 ✓" in text
    assert "1995 ✗" in text
    # error cell rendered with error
    assert "simulated failure" in text
    # details section present
    assert "<details>" in text
    # missing field renders as em dash
    assert "—" in text

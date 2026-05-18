import json
from pathlib import Path

from typer.testing import CliRunner

from lab.cli import app


runner = CliRunner()


def test_list_prompts():
    result = runner.invoke(app, ["list", "prompts"])
    assert result.exit_code == 0
    assert "label_v1_baseline" in result.stdout
    assert "label_v2_facts" in result.stdout
    assert "label_v3_app_fields" in result.stdout
    assert "label_v3_ai_focus" not in result.stdout


def test_list_fixtures():
    result = runner.invoke(app, ["list", "fixtures"])
    assert result.exit_code == 0
    assert "drumcode" in result.stdout
    assert "anjunadeep" in result.stdout


def test_run_with_stub_vendors(tmp_path, monkeypatch):
    """End-to-end CLI exercise. Replaces vendor builder with stubs so no API is hit."""
    from tests.conftest import StubVendor
    import lab.cli as cli_mod

    monkeypatch.setattr(
        cli_mod,
        "build_vendors",
        lambda settings, names: [StubVendor("anthropic")],
    )
    monkeypatch.setattr(cli_mod, "OUTPUTS_ROOT", tmp_path / "outputs")
    monkeypatch.setattr(cli_mod, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")

    result = runner.invoke(app, [
        "run",
        "--prompts", "label_v1_baseline",
        "--vendors", "anthropic",
        "--fixtures", "drumcode",
        "--concurrency", "1",
    ])
    assert result.exit_code == 0, result.stdout

    run_dirs = list((tmp_path / "outputs").iterdir())
    assert len(run_dirs) == 1
    manifest = json.loads((run_dirs[0] / "manifest.json").read_text())
    assert manifest["totals"]["ok"] == 1
    assert manifest["totals"]["error"] == 0

    report_files = list((tmp_path / "reports").glob("*.md"))
    assert len(report_files) == 1
    assert "label_v1_baseline" in report_files[0].read_text()


def test_aggregate_writes_merged_and_updates_manifest(tmp_path, monkeypatch):
    """End-to-end: lab aggregate reads cells, calls DeepSeek (stubbed),
    writes merged/<file>, updates manifest, regenerates report."""
    import json as _json
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    import lab.cli as cli_mod

    monkeypatch.setattr(cli_mod, "OUTPUTS_ROOT", tmp_path / "outputs")
    monkeypatch.setattr(cli_mod, "REPORTS_ROOT", tmp_path / "reports")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key")

    # Stub the DeepSeek client builder
    def fake_build(settings):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=_json.dumps({
                    "tagline": "Test tagline.",
                    "summary": "Merged summary.",
                    "ai_reasoning": "Merged reasoning.",
                    "notes": None,
                })),
                finish_reason="stop",
            )],
            usage=SimpleNamespace(prompt_tokens=500, completion_tokens=200, total_tokens=700),
            model="deepseek-v4-flash",
        )
        return client, "deepseek-v4-flash"

    monkeypatch.setattr(cli_mod, "build_deepseek_client", fake_build)

    # Set up a fake run dir with 2 cell JSONs and a manifest
    run_id = "20260518-200000-test"
    run_dir = tmp_path / "outputs" / run_id
    run_dir.mkdir(parents=True)
    manifest = {
        "run_id": run_id,
        "started_at": "2026-05-18T20:00:00+00:00",
        "finished_at": "2026-05-18T20:01:00+00:00",
        "prompts": [{"slug": "label_v3_app_fields", "version": "v1"}],
        "vendors": [
            {"name": "gemini", "model": "gemini-2.5-flash"},
            {"name": "tavily_deepseek", "model": "deepseek-v4-flash"},
        ],
        "fixtures": ["drumcode"],
        "totals": {"cells": 2, "ok": 2, "error": 0, "cost_usd": 0.01},
    }
    (run_dir / "manifest.json").write_text(_json.dumps(manifest), encoding="utf-8")

    base_parsed = {
        "label_name": "Drumcode",
        "aliases": [], "parent_label": None, "sublabels": [],
        "country": "Sweden", "founded_year": 1996, "status": "active",
        "tagline": "Swedish techno.",
        "catalog_size_estimate": None, "roster_size_estimate": None,
        "releases_last_12_months": None, "last_release_date": None,
        "activity": "unknown",
        "website": None, "bandcamp_url": None, "residentadvisor_url": None,
        "discogs_url": None, "beatport_url": None, "soundcloud_url": None,
        "instagram_url": None, "twitter_url": None,
        "notable_artists": ["Adam Beyer"], "primary_styles": [],
        "distribution": None, "ai_content": "none_detected",
        "ai_signals": [], "ai_reasoning": "n/a",
        "summary": "Swedish techno label.", "confidence": 0.9,
        "sources": [], "notes": None,
    }
    for vendor, model in [("gemini", "gemini-2.5-flash"), ("tavily_deepseek", "deepseek-v4-flash")]:
        cell_path = run_dir / f"label_v3_app_fields__{vendor}__drumcode.json"
        cell_path.write_text(_json.dumps({
            "run_id": run_id,
            "prompt": {"slug": "label_v3_app_fields", "version": "v1"},
            "vendor": {"name": vendor, "model": model},
            "fixture": {"id": "drumcode", "label_name": "Drumcode", "style": "techno", "release_name": None},
            "rendered_user_prompt": "...",
            "response": {
                "parsed": base_parsed,
                "citations": [],
                "usage": {"input_tokens": 100, "output_tokens": 200, "cost_usd": 0.001},
                "latency_ms": 1500,
                "raw": {},
            },
            "error": None,
        }), encoding="utf-8")

    result = runner.invoke(app, ["aggregate", run_id])
    assert result.exit_code == 0, result.stdout

    # Verify merged JSON written
    merged_files = list((run_dir / "merged").glob("*.json"))
    assert len(merged_files) == 1
    merged_payload = _json.loads(merged_files[0].read_text())
    assert merged_payload["merged"]["tagline"] == "Test tagline."
    assert merged_payload["merged"]["founded_year"] == 1996
    assert len(merged_payload["source_cells"]) == 2

    # Manifest updated
    new_manifest = _json.loads((run_dir / "manifest.json").read_text())
    assert "aggregates" in new_manifest
    assert new_manifest["aggregates"]["groups"] == 1
    assert new_manifest["aggregates"]["total_aggregate_cost_usd"] >= 0

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
    assert "label_v3_ai_focus" in result.stdout


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

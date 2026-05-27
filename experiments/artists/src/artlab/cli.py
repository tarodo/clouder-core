"""`lab` CLI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import typer

from .aggregate import merge_cells
from .config import Settings, available_vendor_names
from .fixtures import load_fixtures
from .prompts import PROMPTS, load_builtin_prompts
from .report import build_report
from .runner import RunSpec, run_matrix
from .vendors.anthropic_claude import AnthropicClaudeAdapter
from .vendors.base import VendorAdapter
from .vendors.gemini_flash import GeminiFlashAdapter
from .vendors.kimi_k2 import KimiAdapter
from .vendors.openai_gpt import OpenAIGPTAdapter
from .vendors.perplexity_sonar import PerplexitySonarAdapter
from .vendors.tavily_deepseek import TavilyDeepSeekAdapter
from .vendors.xai_grok import XAIGrokAdapter

ROOT = Path(__file__).resolve().parents[2]  # experiments/artists/
FIXTURES_PATH = ROOT / "fixtures.yaml"
OUTPUTS_ROOT = ROOT / "outputs"
REPORTS_ROOT = ROOT / "reports"

app = typer.Typer(help="Local sandbox for artist AI experiments.")
list_app = typer.Typer(help="List registered prompts, vendors, or fixtures.")
app.add_typer(list_app, name="list")


def build_vendors(settings: Settings, names: list[str]) -> list[VendorAdapter]:
    adapters: list[VendorAdapter] = []
    if "anthropic" in names and settings.anthropic_api_key:
        adapters.append(AnthropicClaudeAdapter(
            api_key=settings.anthropic_api_key,
            default_model=settings.anthropic_model,
            timeout_s=settings.request_timeout,
        ))
    if "xai" in names and settings.xai_api_key:
        adapters.append(XAIGrokAdapter(
            api_key=settings.xai_api_key,
            default_model=settings.xai_model,
            timeout_s=settings.request_timeout,
        ))
    if "gemini" in names and settings.gemini_api_key:
        adapters.append(GeminiFlashAdapter(
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            timeout_s=settings.request_timeout,
        ))
    if "openai" in names and settings.openai_api_key:
        adapters.append(OpenAIGPTAdapter(
            api_key=settings.openai_api_key,
            default_model=settings.openai_model,
            timeout_s=settings.request_timeout,
        ))
    if "tavily_deepseek" in names and settings.tavily_api_key and settings.deepseek_api_key:
        adapters.append(TavilyDeepSeekAdapter(
            tavily_api_key=settings.tavily_api_key,
            deepseek_api_key=settings.deepseek_api_key,
            default_model=settings.deepseek_model,
            timeout_s=settings.request_timeout,
        ))
    if "perplexity" in names and settings.perplexity_api_key:
        adapters.append(PerplexitySonarAdapter(
            api_key=settings.perplexity_api_key,
            default_model=settings.perplexity_model,
            timeout_s=settings.request_timeout,
        ))
    if "kimi" in names and settings.kimi_api_key:
        adapters.append(KimiAdapter(
            api_key=settings.kimi_api_key,
            default_model=settings.kimi_model,
            timeout_s=settings.request_timeout,
        ))
    return adapters


def _parse_csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def build_deepseek_client(settings: Settings) -> tuple[Any, str]:
    """Build a DeepSeek-pointed OpenAI client + return chosen model."""
    if not settings.deepseek_api_key:
        typer.echo("DEEPSEEK_API_KEY required for aggregation", err=True)
        raise typer.Exit(2)
    from openai import OpenAI
    client = OpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com",
        timeout=settings.request_timeout,
    )
    return client, settings.deepseek_model


@app.command()
def aggregate(
    run_id: str,
    prompts: str = typer.Option(None, "--prompts"),
    vendors: str = typer.Option(None, "--vendors"),
    fixtures: str = typer.Option(None, "--fixtures"),
) -> None:
    """Merge per-vendor cells in a run into consensus ArtistInfo per fixture."""
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists():
        typer.echo(f"no such run: {run_id}", err=True)
        raise typer.Exit(2)

    settings = Settings()
    client, model = build_deepseek_client(settings)

    # Load cells
    cells: list[dict] = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        cells.append(json.loads(path.read_text(encoding="utf-8")))

    # Filter
    sel_prompts = _parse_csv(prompts)
    sel_vendors = _parse_csv(vendors)
    sel_fixtures = _parse_csv(fixtures)
    if sel_prompts:
        cells = [c for c in cells if c["prompt"]["slug"] in sel_prompts]
    if sel_vendors:
        cells = [c for c in cells if c["vendor"]["name"] in sel_vendors]
    if sel_fixtures:
        cells = [c for c in cells if c["fixture"]["id"] in sel_fixtures]

    if not cells:
        typer.echo("no cells match filters", err=True)
        raise typer.Exit(2)

    # Group by (prompt, fixture)
    from collections import defaultdict as _dd
    groups: dict[tuple[str, str], list[dict]] = _dd(list)
    for c in cells:
        groups[(c["prompt"]["slug"], c["fixture"]["id"])].append(c)

    merged_dir = run_dir / "merged"
    merged_dir.mkdir(exist_ok=True)
    total_cost = 0.0

    for (prompt_slug, fixture_id), group in groups.items():
        merged_artist, meta = merge_cells(group, client, model)
        first = group[0]
        payload = {
            "run_id": run_id,
            "merged_at": datetime.now(timezone.utc).isoformat(),
            "prompt": first["prompt"],
            "fixture": first["fixture"],
            "source_cells": [
                {
                    "vendor": c["vendor"]["name"],
                    "model": c["vendor"]["model"],
                    "file": f"{prompt_slug}__{c['vendor']['name']}__{fixture_id}.json",
                    "confidence": c["response"]["parsed"].get("confidence") if c["response"]["parsed"] else None,
                }
                for c in group
            ],
            "merged": merged_artist.model_dump(),
            "merge_meta": meta,
            "aggregate_cost_usd": meta.get("narrative_cost_usd", 0.0),
        }
        out_path = merged_dir / f"{prompt_slug}__{fixture_id}.json"
        out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        total_cost += meta.get("narrative_cost_usd", 0.0)
        typer.echo(f"merged {prompt_slug} × {fixture_id} ({len(group)} sources)")

    # Update manifest
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["aggregates"] = {
        "merged_at": datetime.now(timezone.utc).isoformat(),
        "groups": len(groups),
        "filters_applied": {"vendors": sel_vendors, "prompts": sel_prompts, "fixtures": sel_fixtures},
        "total_aggregate_cost_usd": round(total_cost, 6),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Regenerate report
    out_path = build_report(run_dir, REPORTS_ROOT)
    typer.echo(f"groups: {len(groups)}, cost: ${total_cost:.6f}")
    typer.echo(f"report: {out_path}")


@app.command()
def run(
    prompts: str = typer.Option(None, "--prompts", help="Comma-separated prompt slugs"),
    vendors: str = typer.Option(None, "--vendors", help="Comma-separated vendor names"),
    fixtures: str = typer.Option(None, "--fixtures", help="Comma-separated fixture ids"),
    concurrency: int = typer.Option(None, "--concurrency", help="Override concurrency"),
) -> None:
    """Run the prompts × vendors × fixtures matrix."""
    load_builtin_prompts()
    settings = Settings()

    selected_prompts = _parse_csv(prompts) or sorted(PROMPTS)
    for slug in selected_prompts:
        if slug not in PROMPTS:
            typer.echo(f"unknown prompt: {slug}", err=True)
            raise typer.Exit(2)

    all_vendor_names = available_vendor_names(settings)
    if not all_vendor_names:
        typer.echo("no API keys configured; nothing to do", err=True)
        raise typer.Exit(2)
    selected_vendor_names = _parse_csv(vendors) or all_vendor_names
    missing = [n for n in selected_vendor_names if n not in all_vendor_names]
    if missing:
        typer.echo(f"vendors without API keys: {', '.join(missing)} (skipping)")
    selected_vendor_names = [n for n in selected_vendor_names if n in all_vendor_names]
    vendor_adapters = build_vendors(settings, selected_vendor_names)
    if not vendor_adapters:
        typer.echo("no usable vendors after filtering", err=True)
        raise typer.Exit(2)

    all_fixtures = load_fixtures(FIXTURES_PATH)
    selected_fixture_ids = _parse_csv(fixtures)
    selected_fixtures = (
        [f for f in all_fixtures if f.id in selected_fixture_ids]
        if selected_fixture_ids
        else all_fixtures
    )
    if not selected_fixtures:
        typer.echo("no fixtures selected", err=True)
        raise typer.Exit(2)

    spec = RunSpec(
        prompts=selected_prompts,
        vendors=vendor_adapters,
        fixtures=selected_fixtures,
        outputs_root=OUTPUTS_ROOT,
        concurrency=concurrency or settings.concurrency,
    )
    result = run_matrix(spec)
    out_path = build_report(OUTPUTS_ROOT / result.run_id, REPORTS_ROOT)
    typer.echo(f"run_id: {result.run_id}")
    typer.echo(f"report: {out_path}")


@app.command()
def report(run_id: str) -> None:
    """Regenerate the report from an existing run directory."""
    run_dir = OUTPUTS_ROOT / run_id
    if not run_dir.exists():
        typer.echo(f"no such run: {run_id}", err=True)
        raise typer.Exit(2)
    out_path = build_report(run_dir, REPORTS_ROOT)
    typer.echo(str(out_path))


@list_app.command("prompts")
def list_prompts() -> None:
    load_builtin_prompts()
    for slug in sorted(PROMPTS):
        cfg = PROMPTS[slug]
        typer.echo(f"{slug}/{cfg.version} — {cfg.description}")


@list_app.command("vendors")
def list_vendors() -> None:
    settings = Settings()
    names = available_vendor_names(settings)
    if not names:
        typer.echo("no vendors configured (no API keys in .env)")
        return
    for name in names:
        typer.echo(name)


@list_app.command("fixtures")
def list_fixtures() -> None:
    for f in load_fixtures(FIXTURES_PATH):
        gt = "with ground_truth" if f.ground_truth else "no ground_truth"
        anchors = []
        if f.sample_tracks:
            anchors.append(f"tracks={'; '.join(f.sample_tracks)}")
        if f.known_labels:
            anchors.append(f"labels={', '.join(f.known_labels)}")
        suffix = f" [{' | '.join(anchors)}]" if anchors else ""
        typer.echo(f"{f.id} — {f.artist_name} / {f.style} ({gt}){suffix}")


if __name__ == "__main__":
    app()

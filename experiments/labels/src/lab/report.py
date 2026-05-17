"""Markdown report generator."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

# Fields shown in the per-fixture side-by-side table, in order
TABLE_FIELDS: list[str] = [
    "founded_year",
    "country",
    "parent_label",
    "catalog_size_estimate",
    "releases_last_12_months",
    "activity",
    "ai_content",
    "confidence",
    "notable_artists",
]

EMPTY = "—"


def build_report(run_dir: Path, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_dir.name
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))

    cells = _load_cells(run_dir)
    cells_by_fixture = defaultdict(list)
    for cell in cells:
        cells_by_fixture[cell["fixture"]["id"]].append(cell)

    lines: list[str] = []
    lines.append(f"# Run report — `{run_id}`")
    lines.append("")
    lines.extend(_summary_section(manifest, cells))
    for fixture_id in sorted(cells_by_fixture):
        lines.extend(_fixture_section(fixture_id, cells_by_fixture[fixture_id]))
    lines.extend(_details_section(cells))

    out_path = reports_dir / f"{run_id}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _load_cells(run_dir: Path) -> list[dict]:
    cells = []
    for path in sorted(run_dir.glob("*.json")):
        if path.name == "manifest.json":
            continue
        cells.append(json.loads(path.read_text(encoding="utf-8")))
    return cells


def _summary_section(manifest: dict, cells: list[dict]) -> list[str]:
    totals = manifest["totals"]
    by_vendor_latency: dict[str, list[int]] = defaultdict(list)
    by_vendor_cost: dict[str, float] = defaultdict(float)
    for cell in cells:
        v = cell["vendor"]["name"]
        by_vendor_latency[v].append(int(cell["response"]["latency_ms"]))
        by_vendor_cost[v] += float(cell["response"]["usage"].get("cost_usd") or 0.0)
    rows = []
    rows.append("## Summary")
    rows.append("")
    rows.append(f"- cells: {totals['cells']}")
    rows.append(f"- ok: {totals['ok']}")
    rows.append(f"- error: {totals['error']}")
    rows.append(f"- total cost: ${totals['cost_usd']:.4f}")
    rows.append("")
    rows.append("| Vendor | Mean latency (ms) | Total cost (USD) |")
    rows.append("| --- | --- | --- |")
    for v in sorted(by_vendor_latency):
        mean = sum(by_vendor_latency[v]) / len(by_vendor_latency[v])
        rows.append(f"| {v} | {mean:.0f} | {by_vendor_cost[v]:.4f} |")
    rows.append("")
    return rows


def _fixture_section(fixture_id: str, cells: list[dict]) -> list[str]:
    if not cells:
        return []
    first = cells[0]
    label_name = first["fixture"]["label_name"]
    style = first["fixture"]["style"]
    truth = first["fixture"].get("ground_truth") or {}

    rows = []
    rows.append(f"## Fixture: {fixture_id}")
    rows.append("")
    rows.append(f"**{label_name}** — {style}")
    if truth:
        bits = [f"{k}={v}" for k, v in truth.items() if v is not None]
        if bits:
            rows.append(f"_Ground truth:_ {', '.join(bits)}")
    rows.append("")

    headers = ["field"] + [f"{c['prompt']['slug']} / {c['vendor']['name']}" for c in cells]
    rows.append("| " + " | ".join(headers) + " |")
    rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for field in TABLE_FIELDS:
        row_cells = [field]
        for cell in cells:
            row_cells.append(_render_cell_field(cell, field, truth))
        rows.append("| " + " | ".join(row_cells) + " |")
    rows.append("")
    return rows


def _render_cell_field(cell: dict, field: str, truth: dict) -> str:
    if cell["error"] or cell["response"]["parsed"] is None:
        return f"error: {cell['error'] or 'no parse'}"
    parsed = cell["response"]["parsed"]
    raw_value = parsed.get(field, None)
    if raw_value is None or raw_value == [] or raw_value == "":
        rendered = EMPTY
    elif isinstance(raw_value, list):
        rendered = ", ".join(str(v) for v in raw_value)
    else:
        rendered = str(raw_value)

    # Ground-truth annotation
    expected = None
    if field == "founded_year":
        expected = truth.get("founded_year")
    elif field == "country":
        expected = truth.get("country")
    elif field == "parent_label":
        expected = truth.get("parent_label")
    elif field == "ai_content":
        expected = truth.get("ai_content_expected")
    if expected is not None and rendered != EMPTY:
        rendered += " ✓" if str(raw_value) == str(expected) else " ✗"
    return rendered


def _details_section(cells: list[dict]) -> list[str]:
    rows: list[str] = ["## Full responses", ""]
    for cell in cells:
        title = (
            f"{cell['fixture']['id']} — {cell['prompt']['slug']} / "
            f"{cell['vendor']['name']} ({cell['vendor']['model']})"
        )
        rows.append("<details>")
        rows.append(f"<summary>{title}</summary>")
        rows.append("")
        if cell["error"] or cell["response"]["parsed"] is None:
            rows.append(f"**error:** {cell['error'] or 'no parse'}")
        else:
            parsed = cell["response"]["parsed"]
            summary = parsed.get("summary") or EMPTY
            artists = parsed.get("notable_artists") or []
            reasoning = parsed.get("ai_reasoning") or EMPTY
            rows.append(f"**summary:** {summary}")
            rows.append("")
            rows.append(f"**notable artists:** {', '.join(artists) if artists else EMPTY}")
            rows.append("")
            rows.append(f"**ai_reasoning:** {reasoning}")
        rows.append("")
        rows.append("</details>")
        rows.append("")
    return rows

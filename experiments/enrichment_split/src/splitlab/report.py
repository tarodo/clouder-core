"""Markdown report with the spec §5 gate table."""

from __future__ import annotations

GATES = [
    ("tagline fill", lambda s: min(k["fill_rates"]["tagline"]["new"] for k in s.values()), 0.95, ">="),
    ("notable fill", lambda s: min(
        s["label"]["fill_rates"]["notable_artists"]["new"] if "label" in s else 1.0,
        s["artist"]["fill_rates"]["notable_releases"]["new"] if "artist" in s else 1.0,
    ), 0.90, ">="),
    ("instagram found", lambda s: min(k["instagram"]["found_rate"] for k in s.values()), 0.60, ">="),
    ("avg cost/run", lambda s: max(k["avg_cost_usd"] for k in s.values()), 0.025, "<="),
]


def render(summary: dict, manifest: dict) -> str:
    lines = [
        f"# Enrichment split experiment — run {manifest['run_id']} (cap={manifest['cap']})",
        "",
        f"Totals: {manifest['totals']}",
        "",
        "## Gate (spec §5)",
        "",
        "| criterion | measured | threshold | verdict |",
        "|---|---:|---:|---|",
    ]
    for name, fn, threshold, op in GATES:
        try:
            value = fn(summary)
        except (ValueError, KeyError):
            lines.append(f"| {name} | n/a | {op} {threshold} | FAIL |")
            continue
        ok = value >= threshold if op == ">=" else value <= threshold
        lines.append(f"| {name} | {value:.3f} | {op} {threshold} | {'PASS' if ok else 'FAIL'} |")
    if not summary:
        lines.append("")
        lines.append("No cells produced — run failed.")

    for kind, s in summary.items():
        lines += [
            "",
            f"## {kind} ({s['entities']} entities, {s['errors']} errors)",
            "",
            f"instagram: found={s['instagram']['found_rate']:.0%}, "
            f"ig-missing stratum={s['instagram']['found_rate_ig_missing_stratum']}, "
            f"lost vs baseline={s['instagram']['regression_lost']}, "
            f"tiers={s['instagram']['tiers']}",
            f"avg cost=${s['avg_cost_usd']}, latency p50={s['latency_p50_ms']}ms",
            "",
            "| field | new | baseline |",
            "|---|---:|---:|",
        ]
        for field, v in s["fill_rates"].items():
            lines.append(f"| {field} | {v['new']:.0%} | {v['baseline']:.0%} |")

    lines += ["", "## Instagram handles for manual spot-check", ""]
    return "\n".join(lines)

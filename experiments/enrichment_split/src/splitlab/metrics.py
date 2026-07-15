"""Fill-rates, instagram coverage/tiers, cost/latency per kind vs baseline."""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path

TRACKED_FIELDS = {
    "label": ["tagline", "summary", "country", "status", "primary_styles",
              "notable_artists", "founded_year", "catalog_size_estimate",
              "releases_last_12_months", "distribution",
              "bandcamp_url", "discogs_url", "instagram_url"],
    "artist": ["tagline", "summary", "bio", "country", "primary_styles",
               "notable_collaborators", "notable_releases", "active_since",
               "labels", "soundcloud_url", "instagram_url"],
}


def _filled(value) -> bool:
    return value not in (None, "", [], {})


def summarize(run_dir: Path) -> dict:
    cells = defaultdict(list)
    for path in sorted(run_dir.glob("*__*.json")):
        cell = json.loads(path.read_text())
        cells[cell["kind"]].append(cell)

    out: dict = {}
    for kind, rows in cells.items():
        n = len(rows)
        fill: dict = {}
        for field in TRACKED_FIELDS[kind]:
            new = sum(_filled(c["merged"].get(field)) for c in rows) / n
            base = sum(_filled(c["entity"]["baseline"].get(field)) for c in rows) / n
            fill[field] = {"new": round(new, 4), "baseline": round(base, 4)}

        ig_found = [c for c in rows if _filled(c["merged"].get("instagram_url"))]
        missing_stratum = [c for c in rows if c["entity"].get("stratum") == "ig_missing"]
        found_in_missing = [c for c in missing_stratum
                            if _filled(c["merged"].get("instagram_url"))]
        lost = sum(
            1 for c in rows
            if _filled(c["entity"]["baseline"].get("instagram_url"))
            and not _filled(c["merged"].get("instagram_url"))
        )
        tiers = Counter(
            c["provenance"].get("instagram_url", "").replace("profiles_", "")
            for c in ig_found if c["provenance"].get("instagram_url")
        )
        out[kind] = {
            "entities": n,
            "errors": sum(1 for c in rows if c.get("error")),
            "fill_rates": fill,
            "instagram": {
                "found_rate": round(len(ig_found) / n, 4),
                "found_rate_ig_missing_stratum": (
                    round(len(found_in_missing) / len(missing_stratum), 4)
                    if missing_stratum else None
                ),
                "regression_lost": lost,
                "tiers": dict(tiers),
            },
            "avg_cost_usd": round(sum(c["cost_usd"] for c in rows) / n, 5),
            "latency_p50_ms": int(statistics.median(c["latency_ms"] for c in rows)),
        }
    return out

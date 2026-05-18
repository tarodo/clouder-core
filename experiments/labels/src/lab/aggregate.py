"""Multi-vendor consensus aggregator for LabelInfo cells.

The single public entry point is `merge_cells`. Private helpers (`_filter_parseable`,
`_merge_deterministic`, `_merge_narrative`) are exposed for tests.
"""

from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from statistics import median
from typing import Any

from pydantic import BaseModel, ValidationError

from .schemas import LabelInfo
from .vendors.pricing import estimate_cost

NARRATIVE_FIELDS = ("tagline", "summary", "ai_reasoning", "notes")
URL_FIELDS = (
    "logo_url",
    "website",
    "bandcamp_url",
    "residentadvisor_url",
    "discogs_url",
    "beatport_url",
    "soundcloud_url",
    "instagram_url",
    "twitter_url",
)
NUMERIC_FIELDS = (
    "founded_year",
    "catalog_size_estimate",
    "roster_size_estimate",
    "releases_last_12_months",
)
ENUM_FIELDS = ("activity", "ai_content", "status")
LIST_FIELDS = (
    "aliases",
    "sublabels",
    "notable_artists",
    "primary_styles",
    "sources",
)
STRING_FIELDS = ("parent_label", "distribution", "last_release_date", "country")


def _filter_parseable(cells: list[dict]) -> list[dict]:
    """Return cells whose response.parsed is a non-null dict and error is None."""
    out = []
    for cell in cells:
        if cell.get("error"):
            continue
        parsed = cell.get("response", {}).get("parsed")
        if isinstance(parsed, dict) and parsed:
            out.append(cell)
    return out


def _merge_deterministic(cells: list[dict]) -> tuple[dict, dict]:
    """Apply deterministic merge rules to all non-narrative fields.

    Returns (merged_payload, field_provenance). Narrative fields
    (tagline, summary, ai_reasoning, notes) are left absent from
    merged_payload — they're filled by _merge_narrative.
    """
    parseds = [c["response"]["parsed"] for c in cells]
    confidences = [(c, c["response"]["parsed"].get("confidence", 0.0) or 0.0) for c in cells]
    confidences.sort(key=lambda x: (-x[1], x[0]["vendor"]["name"]))  # desc by conf, asc by vendor

    merged: dict = {}
    prov: dict = {}

    # label_name: highest confidence
    for cell, _conf in confidences:
        v = cell["response"]["parsed"].get("label_name")
        if v:
            merged["label_name"] = v
            prov["label_name"] = f"highest confidence({cell['vendor']['name']})"
            break
    if "label_name" not in merged:
        merged["label_name"] = parseds[0].get("label_name", "")
        prov["label_name"] = "fallback first"

    # Numeric fields: median of non-null
    for field in NUMERIC_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field) is not None]
        if vals:
            m = median(vals)
            merged[field] = int(m) if isinstance(m, float) and m.is_integer() else (int(m) if field == "founded_year" else m)
            prov[field] = f"median:{merged[field]}"
        else:
            merged[field] = None
            prov[field] = "all null"

    # Enum fields: majority vote, tie → highest confidence
    for field in ENUM_FIELDS:
        vals = [p.get(field) for p in parseds if p.get(field) is not None]
        if not vals:
            merged[field] = None if field == "status" else "unknown"
            prov[field] = "all null"
            continue
        counts = Counter(vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(vals)})"
        else:
            # Tie — pick value from highest-confidence cell whose value is in top_vals
            chosen = None
            for cell, _conf in confidences:
                v = cell["response"]["parsed"].get(field)
                if v in top_vals:
                    chosen = v
                    break
            merged[field] = chosen if chosen is not None else top_vals[0]
            prov[field] = f"tie → highest confidence({merged[field]})"

    # country: majority, tie → shortest
    country_vals = [p.get("country") for p in parseds if p.get("country")]
    if country_vals:
        counts = Counter(country_vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged["country"] = top_vals[0]
            prov["country"] = f"majority({top_count}/{len(country_vals)})"
        else:
            merged["country"] = min(top_vals, key=len)
            prov["country"] = f"tie → shortest({merged['country']})"
    else:
        merged["country"] = None
        prov["country"] = "all null"

    # Other string fields: majority, tie → highest confidence
    for field in ("parent_label", "distribution", "last_release_date"):
        vals = [p.get(field) for p in parseds if p.get(field)]
        if not vals:
            merged[field] = None
            prov[field] = "all null"
            continue
        counts = Counter(vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(vals)})"
        else:
            chosen = None
            for cell, _conf in confidences:
                v = cell["response"]["parsed"].get(field)
                if v in top_vals:
                    chosen = v
                    break
            merged[field] = chosen if chosen else top_vals[0]
            prov[field] = f"tie → highest confidence({merged[field]})"

    # URL fields: pick from highest-confidence cell with non-null value
    for field in URL_FIELDS:
        chosen = None
        chosen_vendor = None
        for cell, _conf in confidences:
            v = cell["response"]["parsed"].get(field)
            if v:
                chosen = v
                chosen_vendor = cell["vendor"]["name"]
                break
        merged[field] = chosen
        prov[field] = f"highest confidence({chosen_vendor})" if chosen else "all null"

    # List fields: union + dedup; notable_artists capped top-5 by freq
    for field in LIST_FIELDS:
        all_items: list[str] = []
        for p in parseds:
            for item in p.get(field, []) or []:
                if isinstance(item, str) and item.strip():
                    all_items.append(item.strip())
        seen: dict[str, str] = {}  # lowercase → first-cased value
        counts: Counter[str] = Counter()
        for item in all_items:
            key = item.lower()
            if key not in seen:
                seen[key] = item
            counts[key] += 1
        if field == "notable_artists":
            ranked = sorted(seen.keys(), key=lambda k: (-counts[k], k))[:5]
            merged[field] = [seen[k] for k in ranked]
            prov[field] = f"union top-5 by freq({len(seen)} unique)"
        else:
            merged[field] = [seen[k] for k in sorted(seen.keys(), key=lambda k: -counts[k])]
            prov[field] = f"union({len(seen)})"

    # ai_signals: list of dicts, dedup by (kind, description normalized)
    seen_signals: dict[tuple[str, str], dict] = {}
    for p in parseds:
        for sig in p.get("ai_signals", []) or []:
            if not isinstance(sig, dict):
                continue
            kind = sig.get("kind") or ""
            desc = (sig.get("description") or "").strip().lower()
            key = (kind, desc)
            if key not in seen_signals and desc:
                seen_signals[key] = sig
    merged["ai_signals"] = list(seen_signals.values())
    prov["ai_signals"] = f"union({len(seen_signals)})"

    # confidence: mean of non-null
    confs = [p.get("confidence") for p in parseds if isinstance(p.get("confidence"), (int, float))]
    if confs:
        mean = sum(confs) / len(confs)
        merged["confidence"] = round(mean, 4)
        prov["confidence"] = f"mean({len(confs)})"
    else:
        merged["confidence"] = 0.0
        prov["confidence"] = "all null"

    return merged, prov


def merge_cells(cells, deepseek_client, deepseek_model="deepseek-v4-flash"):
    """Placeholder — implemented in Task 4."""
    raise NotImplementedError("merge_cells lands in Task 4")

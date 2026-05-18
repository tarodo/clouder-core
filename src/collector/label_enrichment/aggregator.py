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


def _rank_list_round_robin(per_cell_items: list[list[str]], cap: int) -> tuple[list[str], int, int]:
    """Rank list items: shared first (freq desc), then round-robin from each cell.

    Returns (ranked_items, total_unique, shared_count).
    """
    counts: Counter[str] = Counter()
    seen_original: dict[str, str] = {}
    for items in per_cell_items:
        for item in items:
            if not isinstance(item, str) or not item.strip():
                continue
            k = item.strip().lower()
            if k not in seen_original:
                seen_original[k] = item.strip()
            counts[k] += 1

    # Shared first (freq > 1), sorted by freq desc then alphabetic
    ranked = [k for k, _c in sorted(counts.items(), key=lambda x: (-x[1], x[0])) if counts[k] > 1]
    seen_in_ranked = set(ranked)

    # Round-robin through remaining items by position
    max_len = max((len(items) for items in per_cell_items), default=0)
    for i in range(max_len):
        if len(ranked) >= cap:
            break
        for items in per_cell_items:
            if i < len(items):
                k = items[i].strip().lower() if isinstance(items[i], str) else ""
                if k and k not in seen_in_ranked:
                    ranked.append(k)
                    seen_in_ranked.add(k)
                    if len(ranked) >= cap:
                        break

    shared_count = sum(1 for c in counts.values() if c > 1)
    return [seen_original[k] for k in ranked[:cap]], len(seen_original), shared_count


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
            merged[field] = int(round(m))
            prov[field] = f"median:{merged[field]}"
        else:
            merged[field] = None
            prov[field] = "all null"

    # Enum fields: majority vote, tie → highest confidence; "unknown" is abstention
    for field in ENUM_FIELDS:
        raw_vals = [p.get(field) for p in parseds if p.get(field) is not None]
        voting_vals = [v for v in raw_vals if v != "unknown"]
        if not voting_vals:
            # Either all unknown or all null → unknown
            merged[field] = "unknown"
            prov[field] = "all unknown" if raw_vals else "all null"
            continue
        if len(voting_vals) == 1:
            merged[field] = voting_vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get(field) == voting_vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov[field] = f"only definitive source({contributing})"
            continue
        counts = Counter(voting_vals)
        top_count = max(counts.values())
        top_vals = [v for v, c in counts.items() if c == top_count]
        if len(top_vals) == 1:
            merged[field] = top_vals[0]
            prov[field] = f"majority({top_count}/{len(voting_vals)} definitive)"
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
        if len(country_vals) == 1:
            merged["country"] = country_vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get("country") == country_vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov["country"] = f"only source({contributing})"
        else:
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
        if len(vals) == 1:
            merged[field] = vals[0]
            contributing = None
            for c in cells:
                if c["response"]["parsed"].get(field) == vals[0]:
                    contributing = c["vendor"]["name"]
                    break
            prov[field] = f"only source({contributing})"
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

    # List fields: union + dedup; notable_artists capped top-5 by round-robin
    # `confidences` is sorted desc by confidence (already computed earlier in the function).
    cells_by_conf = [c for c, _ in confidences]

    for field in LIST_FIELDS:
        if field == "notable_artists":
            per_cell = [
                (c["response"]["parsed"].get(field, []) or [])
                for c in cells_by_conf
            ]
            ranked_items, unique_count, shared_count = _rank_list_round_robin(per_cell, cap=5)
            merged[field] = ranked_items
            prov[field] = f"union top-5 round-robin({unique_count} unique, {shared_count} shared)"
            continue
        # Other lists: union all, freq desc, alpha tie-break (existing logic)
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


NARRATIVE_SYSTEM = (
    "You are a music-industry data editor. You will receive multiple vendor-sourced JSON descriptions "
    "of a record label. Synthesise them into a single, accurate, well-written set of narrative fields. "
    "Return a JSON object with exactly these keys: tagline, summary, ai_reasoning, notes. "
    "tagline: one punchy sentence (≤ 120 chars). "
    "summary: 2-4 sentences, factual, no superlatives. "
    "ai_reasoning: concise explanation of any AI-content signals found, or 'No AI signals detected.' "
    "notes: any caveats about data quality or conflicts, or null. "
    "Output ONLY valid JSON, no markdown fences."
)


def _build_narrative_prompt(label_name: str, cells: list[dict]) -> str:
    """Assemble the user message from all parseable cells' narrative fields."""
    parts = [f"Label: {label_name}\n"]
    for i, cell in enumerate(cells, 1):
        vendor = cell["vendor"]["name"]
        p = cell["response"]["parsed"]
        conf = p.get("confidence", 0.0)
        parts.append(
            f"--- Source {i} ({vendor}, confidence={conf}) ---\n"
            f"tagline: {p.get('tagline')}\n"
            f"summary: {p.get('summary')}\n"
            f"ai_reasoning: {p.get('ai_reasoning')}\n"
            f"notes: {p.get('notes')}\n"
        )
    parts.append("\nSynthesize the above into the required JSON.")
    return "\n".join(parts)


def _highest_confidence_cell(cells: list[dict]) -> dict:
    """Return the cell with the highest confidence score."""
    return max(cells, key=lambda c: c["response"]["parsed"].get("confidence", 0.0) or 0.0)


def _merge_narrative(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str,
    label_name: str,
) -> tuple[dict, dict]:
    """Call DeepSeek to produce narrative fields; fall back to max-confidence cell on any error.

    Returns (narrative_fields_dict, meta_dict).
    meta_dict keys: narrative_cost_usd, narrative_latency_ms, and optionally narrative_fallback.
    """
    t0 = time.monotonic()
    try:
        user_msg = _build_narrative_prompt(label_name, cells)
        resp = deepseek_client.chat.completions.create(
            model=deepseek_model,
            messages=[
                {"role": "system", "content": NARRATIVE_SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        latency_ms = (time.monotonic() - t0) * 1000
        raw_content = resp.choices[0].message.content
        parsed_narrative = json.loads(raw_content)
        # Validate required keys present
        for key in ("tagline", "summary", "ai_reasoning", "notes"):
            if key not in parsed_narrative:
                raise KeyError(f"Missing narrative key: {key}")
        usage = resp.usage
        cost = estimate_cost(deepseek_model, usage.prompt_tokens, usage.completion_tokens)
        meta = {
            "narrative_cost_usd": cost,
            "narrative_latency_ms": latency_ms,
        }
        return {k: parsed_narrative[k] for k in ("tagline", "summary", "ai_reasoning", "notes")}, meta
    except Exception:
        latency_ms = (time.monotonic() - t0) * 1000
        best = _highest_confidence_cell(cells)
        p = best["response"]["parsed"]
        fallback_fields = {k: p.get(k) for k in ("tagline", "summary", "ai_reasoning", "notes")}
        meta = {
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": latency_ms,
            "narrative_fallback": "max_confidence",
        }
        return fallback_fields, meta


def merge_cells(
    cells: list[dict],
    deepseek_client: Any,
    deepseek_model: str = "deepseek-v4-flash",
) -> tuple[LabelInfo, dict]:
    """Merge vendor cells into a single LabelInfo with DeepSeek narrative synthesis.

    Returns (LabelInfo, meta).
    """
    parseable = _filter_parseable(cells)

    # Case 1: no parseable cells
    if not parseable:
        # Derive label_name from first cell fixture if possible
        label_name = ""
        if cells:
            label_name = cells[0].get("fixture", {}).get("label_name", "")
        info = LabelInfo(
            label_name=label_name or "unknown",
            summary="All vendor sources failed.",
            ai_reasoning="n/a",
            confidence=0.0,
        )
        meta: dict[str, Any] = {
            "all_failed": True,
            "source_count": 0,
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0.0,
            "field_provenance": {},
        }
        return info, meta

    # Case 2: single parseable cell — skip merge
    if len(parseable) == 1:
        p = parseable[0]["response"]["parsed"]
        info = LabelInfo.model_validate(p)
        meta = {
            "single_source": True,
            "source_count": 1,
            "narrative_cost_usd": 0.0,
            "narrative_latency_ms": 0.0,
            "field_provenance": {"tagline": "single source", "summary": "single source"},
        }
        return info, meta

    # Case 3: multiple cells — deterministic + narrative merge
    label_name = parseable[0].get("fixture", {}).get("label_name", "")
    if not label_name:
        label_name = parseable[0]["response"]["parsed"].get("label_name", "unknown")

    det_payload, det_prov = _merge_deterministic(parseable)
    narr_fields, narr_meta = _merge_narrative(parseable, deepseek_client, deepseek_model, label_name)

    # Combine: start with deterministic result, overlay narrative fields
    final: dict[str, Any] = {**det_payload}
    for key in ("tagline", "summary", "ai_reasoning", "notes"):
        final[key] = narr_fields.get(key)

    # Build provenance for narrative fields
    narr_prov_label = "max_confidence fallback" if "narrative_fallback" in narr_meta else "deepseek narrative"
    narr_prov = {k: narr_prov_label for k in ("tagline", "summary", "ai_reasoning", "notes")}

    combined_prov = {**det_prov, **narr_prov}

    info = LabelInfo.model_validate(final)

    meta = {
        "source_count": len(parseable),
        "narrative_cost_usd": narr_meta["narrative_cost_usd"],
        "narrative_latency_ms": narr_meta["narrative_latency_ms"],
        "field_provenance": combined_prov,
    }
    if "narrative_fallback" in narr_meta:
        meta["narrative_fallback"] = narr_meta["narrative_fallback"]

    return info, meta

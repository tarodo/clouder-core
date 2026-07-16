"""Union-merge of the two passes. Fields are designed not to overlap;
on accidental overlap the narrative pass wins (it is the identity anchor)."""

from __future__ import annotations

from .facts_pass import FactsResult
from .narrative_pass import NarrativeResult


def merge_passes(narrative: NarrativeResult, facts: FactsResult) -> tuple[dict, dict]:
    merged: dict = {}
    prov: dict = {}

    for key, value in narrative.narrative.items():
        merged[key] = value
        if value not in (None, [], ""):
            prov[key] = "narrative"

    for key, value in facts.facts.items():
        if key in merged and prov.get(key):
            continue
        merged[key] = value
        if value not in (None, [], ""):
            prov[key] = "facts_llm"

    for key, value in facts.profiles.items():
        if key in merged and prov.get(key):
            continue
        merged[key] = value
        if value in (None, [], ""):
            continue
        if key == "instagram_url" and facts.instagram_tier is not None:
            prov[key] = f"profiles_tier{facts.instagram_tier}"
        else:
            prov[key] = "profiles_regex"

    return merged, prov

"""Narrative pass: OpenAI Responses API + web_search capped by max_tool_calls.
Request schema is narrative-only, so the model spends its searches on the
description instead of URLs/numbers/AI-detection."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .schemas import ArtistNarrative, LabelNarrative

LABEL_SYSTEM = (
    "You research music record labels. Output structured facts only.\n"
    "Rules:\n"
    "- tagline: ONE punchy sentence (<=100 chars) capturing the label's identity.\n"
    "- summary: 2-4 factual sentences, no superlatives.\n"
    "- primary_styles: 2-5 specific genre tags, lowercase, no umbrella terms.\n"
    "- notable_artists: at most 5 recognizable names, not the full roster.\n"
    "- status: active if there is visible activity in the last ~18 months; "
    "inactive if none for >2 years; unknown otherwise.\n"
    "- If the name is ambiguous, pick the entity matching the style and "
    "explain in `notes`.\n"
    "- List supporting source URLs in `sources`. Never invent facts."
)

ARTIST_SYSTEM = (
    "You research electronic-music artists. Output structured facts only.\n"
    "Rules:\n"
    "- Use the disambiguation context (tracks, labels, style) to lock onto the "
    "CORRECT artist; many share a name. If unresolved, set confidence <= 0.4 "
    "and explain in `notes`.\n"
    "- tagline: ONE punchy sentence (<=100 chars). summary: 2-4 factual "
    "sentences. bio: 1-3 additional factual sentences.\n"
    "- primary_styles: 2-5 specific genre tags, no umbrella terms.\n"
    "- notable_collaborators: frequent co-authors and remixers, not one-offs.\n"
    "- notable_releases: at most 5 anchor tracks/EPs that confirm identity.\n"
    "- List supporting source URLs in `sources`. Never invent facts."
)


@dataclass
class NarrativeResult:
    narrative: dict = field(default_factory=dict)
    web_search_calls: int = 0
    llm_usage: dict = field(default_factory=dict)
    latency_ms: int = 0
    error: str | None = None


def _user_message(entity: dict, kind: str) -> str:
    name = entity["name"]
    style = entity.get("style") or "music"
    if kind == "label":
        return (
            f'Research the record label "{name}" (style: {style}). '
            "Describe its identity, primary styles, notable artists, "
            "status, country, and known aliases."
        )
    tracks = ", ".join(entity.get("sample_tracks") or []) or "unknown"
    labels = ", ".join(entity.get("known_labels") or []) or "unknown"
    return (
        f'Research the electronic-music artist "{name}" (style: {style}).\n'
        f"Disambiguation context — sample tracks: {tracks}; known labels: {labels}.\n"
        "Describe identity (type, members, real name), origin, styles, "
        "collaborators, notable releases, and status."
    )


def run_narrative_pass(
    entity: dict, kind: str, llm, model: str, max_tool_calls: int
) -> NarrativeResult:
    schema = LabelNarrative if kind == "label" else ArtistNarrative
    system = LABEL_SYSTEM if kind == "label" else ARTIST_SYSTEM
    result = NarrativeResult()
    started = time.monotonic()
    try:
        resp = llm.responses.parse(
            model=model,
            instructions=system,
            input=[{"role": "user", "content": _user_message(entity, kind)}],
            tools=[{"type": "web_search"}],
            max_tool_calls=max_tool_calls,
            text_format=schema,
        )
        parsed = getattr(resp, "output_parsed", None)
        result.narrative = parsed.model_dump() if parsed is not None else {}
        result.web_search_calls = sum(
            1
            for item in (getattr(resp, "output", None) or [])
            if "search" in (getattr(item, "type", "") or "").lower()
        )
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.llm_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
        if not result.narrative:
            result.error = "no output_parsed in response"
    except Exception as exc:  # noqa: BLE001 — experiment must not crash the run
        result.error = f"{type(exc).__name__}: {exc}"
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result

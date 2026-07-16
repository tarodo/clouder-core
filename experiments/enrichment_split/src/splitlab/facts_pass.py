"""Facts pass: Tavily search -> regex profiles -> extract known pages ->
validated instagram top-up; numeric facts via LLM without tools."""

from __future__ import annotations

from dataclasses import dataclass, field

from .schemas import ArtistFacts, LabelFacts
from .social_regex import (
    extract_profiles,
    handle_of,
    validate_instagram_handle,
)
from .tavily_client import TavilyClient

_SNIPPET_CHARS = 4000
_TOP_RESULTS = 5

FACTS_SYSTEM = (
    "You extract verifiable facts about a music {kind} from the provided web "
    "search results. Use ONLY the provided text. Every non-null field must be "
    "supported by one of the result URLs listed in `sources`. If the text does "
    "not support a field, leave it null. Never guess."
)


@dataclass
class FactsResult:
    facts: dict = field(default_factory=dict)
    profiles: dict = field(default_factory=dict)
    instagram_tier: int | None = None
    credits: int = 0
    llm_usage: dict = field(default_factory=dict)
    error: str | None = None


def _results_text(results: list[dict]) -> str:
    parts = []
    for r in results:
        parts.append(
            f"URL: {r.get('url', '')}\n"
            f"{(r.get('content') or '')[:500]}\n"
            f"{(r.get('raw_content') or '')[:_SNIPPET_CHARS]}"
        )
    return "\n\n---\n\n".join(parts)


def _known_official_urls(entity: dict, profiles: dict) -> list[str]:
    urls = []
    baseline = entity.get("baseline") or {}
    for source in (profiles, baseline):
        for f in ("website", "bandcamp_url", "soundcloud_url"):
            v = source.get(f)
            if isinstance(v, str) and v.startswith("http") and v not in urls:
                urls.append(v)
    return urls[:5]


def run_facts_pass(
    entity: dict, kind: str, tavily: TavilyClient, llm, model: str
) -> FactsResult:
    name = entity["name"]
    style = entity.get("style") or "music"
    schema = LabelFacts if kind == "label" else ArtistFacts
    result = FactsResult()

    noun = "record label" if kind == "label" else "artist"
    search = tavily.search(
        f'"{name}" {style} {noun}', max_results=8, include_raw_content=True
    )
    results = search.get("results") or []
    all_text = _results_text(results)

    # profiles: regex over everything Tavily returned (tier 1)
    result.profiles = extract_profiles(all_text)
    if "instagram_url" in result.profiles:
        result.instagram_tier = 1

    # tier 2: extract known official pages
    if result.instagram_tier is None:
        known = _known_official_urls(entity, result.profiles)
        if known:
            extracted = tavily.extract(known)
            text2 = _results_text(extracted.get("results") or [])
            found = extract_profiles(text2)
            if "instagram_url" in found:
                result.profiles["instagram_url"] = found["instagram_url"]
                result.instagram_tier = 2
            for k, v in found.items():
                result.profiles.setdefault(k, v)

    # tier 3: targeted instagram search with validation
    if result.instagram_tier is None:
        topup = tavily.search(
            f"{name} {style}", max_results=5, include_domains=["instagram.com"]
        )
        for r in topup.get("results") or []:
            handle = handle_of(r.get("url") or "")
            if handle and validate_instagram_handle(handle, name, result.profiles):
                result.profiles["instagram_url"] = f"https://www.instagram.com/{handle}"
                result.instagram_tier = 3
                break

    result.credits = tavily.credits_used

    # numeric facts extraction — no tools, free tokens
    try:
        resp = llm.responses.parse(
            model=model,
            instructions=FACTS_SYSTEM.format(kind=kind),
            input=[{
                "role": "user",
                "content": (
                    f'Extract facts about the {noun} "{name}" (style: {style}) '
                    f"from these search results:\n\n{all_text}"
                ),
            }],
            text_format=schema,
        )
        parsed = getattr(resp, "output_parsed", None)
        result.facts = parsed.model_dump() if parsed is not None else {}
        usage = getattr(resp, "usage", None)
        if usage is not None:
            result.llm_usage = {
                "input_tokens": getattr(usage, "input_tokens", 0) or 0,
                "output_tokens": getattr(usage, "output_tokens", 0) or 0,
            }
    except Exception as exc:  # noqa: BLE001 — experiment must not crash the run
        result.error = f"{type(exc).__name__}: {exc}"
    return result

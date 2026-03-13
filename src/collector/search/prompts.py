"""Prompt registry with versioning for AI search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from .schemas import LabelSearchResult


@dataclass(frozen=True)
class PromptConfig:
    slug: str
    version: str
    system_prompt: str
    user_prompt_template: str
    result_schema: Type[BaseModel]
    model: str = "sonar"


_PROMPTS: dict[tuple[str, str], PromptConfig] = {}


def register(config: PromptConfig) -> None:
    _PROMPTS[(config.slug, config.version)] = config


def get_prompt(slug: str, version: str) -> PromptConfig:
    key = (slug, version)
    if key not in _PROMPTS:
        raise KeyError(f"Prompt {slug}/{version} not found")
    return _PROMPTS[key]


def get_latest(slug: str) -> PromptConfig:
    matching = sorted(
        [v for (s, v) in _PROMPTS if s == slug],
    )
    if not matching:
        raise KeyError(f"No prompts found for slug '{slug}'")
    return _PROMPTS[(slug, matching[-1])]


# ── Label prompts ────────────────────────────────────────────────────

register(
    PromptConfig(
        slug="label_info",
        version="v1",
        system_prompt=(
            "You are a music industry research assistant. Your task is to search "
            "for information about a specific music record label and provide a "
            "structured analysis.\n"
            "Rules:\n"
            "- Search the internet for real, factual information about the label.\n"
            "- For \"size\": estimate based on catalog size, market presence, and "
            "distribution reach.\n"
            "- For \"age\"/\"founded_year\": find when the label was established.\n"
            "- For \"ai_content\": look for evidence of AI-generated music in their "
            "catalog (e.g., releases by known AI music generators, suspiciously high "
            "release volumes from unknown artists, mentions of AI in reviews or "
            "discussions).\n"
            "- Set \"confidence\" based on how much verifiable info you found "
            "(0.0 = guessing, 1.0 = fully verified).\n"
            "- If you cannot find the label at all, return \"unknown\" statuses and "
            "confidence near 0."
        ),
        user_prompt_template=(
            'Research the music record label "{label_name}" that releases '
            '"{style}" music. Return structured information about:\n'
            "1. How big this label is (catalog size, number of artists, "
            "market presence)\n"
            "2. How old/mature this label is (founding year, history)\n"
            "3. Whether this label has AI-generated releases in its catalog"
        ),
        result_schema=LabelSearchResult,
    )
)

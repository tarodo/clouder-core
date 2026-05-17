"""Prompt registry."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}


def register(cfg: PromptConfig) -> None:
    if cfg.slug in PROMPTS:
        raise ValueError(f"prompt {cfg.slug!r} already registered")
    PROMPTS[cfg.slug] = cfg


def get_prompt(slug: str) -> PromptConfig:
    if slug not in PROMPTS:
        raise KeyError(f"prompt {slug!r} not found")
    return PROMPTS[slug]

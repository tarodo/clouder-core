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


def load_builtin_prompts() -> None:
    """Import the built-in prompt modules so they self-register."""
    from . import label_v1_baseline  # noqa: F401
    from . import label_v2_facts  # noqa: F401
    from . import label_v3_ai_focus  # noqa: F401

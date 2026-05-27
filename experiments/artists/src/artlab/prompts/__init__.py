"""Prompt registry."""

from __future__ import annotations

from .base import PromptConfig

PROMPTS: dict[str, PromptConfig] = {}

# Populated by load_builtin_prompts() on first call; used to re-register
# builtins if PROMPTS is cleared between test runs.
_BUILTIN_CONFIGS: list[PromptConfig] = []


def register(cfg: PromptConfig) -> None:
    if cfg.slug in PROMPTS:
        if PROMPTS[cfg.slug] is not cfg:
            raise ValueError(f"prompt {cfg.slug!r} already registered")
        return
    PROMPTS[cfg.slug] = cfg


def get_prompt(slug: str) -> PromptConfig:
    if slug not in PROMPTS:
        raise KeyError(f"prompt {slug!r} not found")
    return PROMPTS[slug]


def load_builtin_prompts() -> None:
    """Import the built-in prompt modules so they self-register."""
    global _BUILTIN_CONFIGS

    if not _BUILTIN_CONFIGS:
        before = set(PROMPTS)
        from . import artist_v1  # noqa: F401
        _BUILTIN_CONFIGS = [cfg for slug, cfg in PROMPTS.items() if slug not in before]

    for cfg in _BUILTIN_CONFIGS:
        register(cfg)

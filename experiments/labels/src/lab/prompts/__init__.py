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
    """Import the built-in prompt modules so they self-register.

    Safe to call multiple times: re-registers configs that may have been
    cleared from the PROMPTS dict between test runs.
    """
    global _BUILTIN_CONFIGS

    if not _BUILTIN_CONFIGS:
        # First call: snapshot PROMPTS before and after import so we capture
        # exactly which configs the builtin modules registered.
        before = set(PROMPTS)
        from . import label_v1_baseline  # noqa: F401
        from . import label_v2_facts  # noqa: F401
        from . import label_v3_app_fields  # noqa: F401
        _BUILTIN_CONFIGS = [cfg for slug, cfg in PROMPTS.items() if slug not in before]

    # Re-register any builtins that may have been evicted (e.g. PROMPTS.clear()).
    for cfg in _BUILTIN_CONFIGS:
        register(cfg)

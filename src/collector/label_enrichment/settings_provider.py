"""Lightweight container so the factory does not depend on settings.py at import time."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LabelEnrichmentSecrets:
    gemini_api_key: str
    openai_api_key: str
    tavily_api_key: str
    deepseek_api_key: str

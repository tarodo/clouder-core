"""Prompt configuration and rendering helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type

from pydantic import BaseModel


@dataclass(frozen=True)
class PromptConfig:
    slug: str
    version: str
    description: str
    system: str
    user_template: str
    schema: Type[BaseModel]
    vendor_overrides: dict[str, str] = field(default_factory=dict)


def render_user(
    cfg: PromptConfig,
    artist_name: str,
    style: str,
    sample_tracks: list[str] | None = None,
    known_labels: list[str] | None = None,
) -> str:
    tracks = ", ".join(sample_tracks) if sample_tracks else ""
    labels = ", ".join(known_labels) if known_labels else ""
    if tracks or labels:
        context_block = (
            "\nDisambiguation context — this is the artist who released: "
            f"{tracks or 'unknown'}; on labels: {labels or 'unknown'}; "
            f"genre hint: {style}."
        )
    else:
        context_block = ""
    return cfg.user_template.format(
        artist_name=artist_name,
        style=style,
        context_block=context_block,
    )

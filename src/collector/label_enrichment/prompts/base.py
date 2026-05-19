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
    label_name: str,
    style: str,
) -> str:
    return cfg.user_template.format(
        label_name=label_name,
        style=style,
    )

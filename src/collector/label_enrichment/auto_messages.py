"""PUT body schema for auto-enrichment config."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AutoEnrichConfigIn(BaseModel):
    """PUT /admin/auto-enrich/labels body.

    When `enabled` is False the model/prompt fields may be partial — the admin
    can switch the feature off without re-entering a full config. When True the
    same completeness rules as a manual enqueue apply.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    vendors: list[Literal["gemini", "openai", "tavily_deepseek"]] = Field(default_factory=list)
    models: dict[str, str] = Field(default_factory=dict)
    prompt_slug: str | None = None
    prompt_version: str | None = None
    merge_vendor: Literal["deepseek"] = "deepseek"
    merge_model: str | None = None

    @model_validator(mode="after")
    def _validate_when_enabled(self) -> "AutoEnrichConfigIn":
        if not self.enabled:
            return self
        if not self.vendors:
            raise ValueError("vendors required when enabled")
        for vendor in self.vendors:
            if vendor not in self.models or not self.models[vendor].strip():
                raise ValueError(f"model missing for vendor {vendor!r}")
        if not self.prompt_slug or not self.prompt_version:
            raise ValueError("prompt required when enabled")
        if not self.merge_model or not self.merge_model.strip():
            raise ValueError("merge_model required when enabled")
        return self

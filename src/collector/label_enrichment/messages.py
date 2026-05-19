"""SQS message + HTTP request schemas for label enrichment."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SUPPORTED_VENDORS = ("gemini", "openai", "tavily_deepseek")


class LabelEnrichmentMessage(BaseModel):
    """Body of one SQS message — one per label, one Lambda invocation."""

    model_config = ConfigDict(extra="ignore")

    run_id: str = Field(min_length=1)
    label_id: str = Field(min_length=1)
    label_name: str = Field(min_length=1)
    style: str = Field(min_length=1)


class EnrichLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_id: str | None = Field(default=None, min_length=1)
    label_name: str | None = Field(default=None, min_length=1, max_length=256)
    style: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def _id_or_name_required(self) -> "EnrichLabelInput":
        if not self.label_id and not self.label_name:
            raise ValueError("either label_id or label_name is required")
        if not self.label_id and not self.style:
            raise ValueError("style is required when using label_name")
        return self


class EnrichLabelsRequestIn(BaseModel):
    """POST /admin/labels/enrich body."""

    model_config = ConfigDict(extra="forbid")

    labels: list[EnrichLabelInput] = Field(min_length=1, max_length=100)
    vendors: list[Literal["gemini", "openai", "tavily_deepseek"]] = Field(min_length=1)
    models: dict[str, str]
    prompt_slug: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    merge_vendor: Literal["deepseek"]
    merge_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _every_vendor_has_a_model(self) -> "EnrichLabelsRequestIn":
        for vendor in self.vendors:
            if vendor not in self.models or not self.models[vendor].strip():
                raise ValueError(f"model missing for vendor {vendor!r}")
        return self

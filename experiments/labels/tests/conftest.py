"""Shared test helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Type

from pydantic import BaseModel

from lab.schemas import Fixture, LabelInfo
from lab.vendors.base import VendorResponse


@dataclass
class StubVendor:
    name: str
    default_model: str = "stub-model"
    supports_web_search: bool = True

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse:
        chosen = model or self.default_model
        self.calls.append((system, user, chosen))
        parsed = schema.model_validate(
            {
                "label_name": "Stubbed",
                "ai_reasoning": f"stub from {self.name}",
                "summary": f"stub summary from {self.name}",
                "confidence": 0.5,
            }
        )
        return VendorResponse(
            parsed=parsed,
            raw={"stub": True, "vendor": self.name},
            citations=["https://stub"],
            usage={"input_tokens": 10, "output_tokens": 20, "cost_usd": 0.0001},
            latency_ms=12,
            model=chosen,
            error=None,
        )


def make_fixture(id: str, label: str, style: str = "techno") -> Fixture:
    return Fixture(id=id, label_name=label, style=style)

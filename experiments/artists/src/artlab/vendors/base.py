"""Vendor adapter protocol and response container."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Type

from pydantic import BaseModel


@dataclass
class VendorResponse:
    parsed: BaseModel | None
    raw: dict
    citations: list[str]
    usage: dict          # {"input_tokens": int, "output_tokens": int, "cost_usd": float}
    latency_ms: int
    model: str
    error: str | None = None


class VendorAdapter(Protocol):
    name: str
    default_model: str
    supports_web_search: bool

    def run(
        self,
        system: str,
        user: str,
        schema: Type[BaseModel],
        model: str | None = None,
    ) -> VendorResponse: ...

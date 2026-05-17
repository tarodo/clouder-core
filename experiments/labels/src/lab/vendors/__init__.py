"""Vendor registry."""

from __future__ import annotations

from .base import VendorAdapter, VendorResponse

VENDORS: dict[str, VendorAdapter] = {}


def register(adapter: VendorAdapter) -> None:
    if adapter.name in VENDORS:
        raise ValueError(f"vendor {adapter.name!r} already registered")
    VENDORS[adapter.name] = adapter


def get_vendor(name: str) -> VendorAdapter:
    if name not in VENDORS:
        raise KeyError(f"vendor {name!r} not found")
    return VENDORS[name]

"""Matrix runner: prompts × vendors × fixtures → JSON cells + manifest."""

from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .prompts import get_prompt
from .prompts.base import render_user
from .schemas import Fixture
from .vendors.base import VendorAdapter, VendorResponse


@dataclass
class RunSpec:
    prompts: list[str]
    vendors: list[VendorAdapter]
    fixtures: list[Fixture]
    outputs_root: Path
    concurrency: int = 4


@dataclass
class RunResult:
    run_id: str
    totals: dict


def run_matrix(spec: RunSpec) -> RunResult:
    run_id = _new_run_id()
    run_dir = spec.outputs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    cells: list[_Cell] = []
    for prompt_slug in spec.prompts:
        for fixture in spec.fixtures:
            for vendor in spec.vendors:
                cells.append(_Cell(prompt_slug=prompt_slug, vendor=vendor, fixture=fixture))

    started = datetime.now(timezone.utc)
    ok = 0
    err = 0
    cost_total = 0.0

    with ThreadPoolExecutor(max_workers=max(1, spec.concurrency)) as pool:
        future_to_cell = {pool.submit(_execute_cell, c, run_id, run_dir): c for c in cells}
        total = len(cells)
        done = 0
        for fut in as_completed(future_to_cell):
            cell = future_to_cell[fut]
            done += 1
            try:
                resp: VendorResponse = fut.result()
            except Exception as exc:  # noqa: BLE001 — defensive
                err += 1
                print(f"[{done}/{total}] {cell.label()} ... crashed: {exc}")
                continue
            cost_total += float(resp.usage.get("cost_usd") or 0.0)
            if resp.error is None and resp.parsed is not None:
                ok += 1
                status = "ok"
            else:
                err += 1
                status = f"error: {resp.error}"
            print(
                f"[{done}/{total}] {cell.label()} ... {status} "
                f"({resp.latency_ms}ms, ${resp.usage.get('cost_usd', 0):.4f})"
            )

    finished = datetime.now(timezone.utc)
    manifest = {
        "run_id": run_id,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "prompts": [
            {"slug": p, "version": get_prompt(p).version} for p in spec.prompts
        ],
        "vendors": [
            {"name": v.name, "model": v.default_model} for v in spec.vendors
        ],
        "fixtures": [f.id for f in spec.fixtures],
        "totals": {
            "cells": len(cells),
            "ok": ok,
            "error": err,
            "cost_usd": round(cost_total, 4),
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return RunResult(run_id=run_id, totals=manifest["totals"])


@dataclass
class _Cell:
    prompt_slug: str
    vendor: VendorAdapter
    fixture: Fixture

    def label(self) -> str:
        return f"{self.prompt_slug} × {self.vendor.name} × {self.fixture.id}"

    def file_name(self) -> str:
        return f"{self.prompt_slug}__{self.vendor.name}__{self.fixture.id}.json"


def _execute_cell(cell: _Cell, run_id: str, run_dir: Path) -> VendorResponse:
    prompt = get_prompt(cell.prompt_slug)
    model = prompt.vendor_overrides.get(cell.vendor.name)
    user = render_user(
        prompt,
        label_name=cell.fixture.label_name,
        style=cell.fixture.style,
        release_name=cell.fixture.release_name,
    )
    resp = cell.vendor.run(system=prompt.system, user=user, schema=prompt.schema, model=model)
    payload = {
        "run_id": run_id,
        "prompt": {"slug": prompt.slug, "version": prompt.version},
        "vendor": {"name": cell.vendor.name, "model": resp.model},
        "fixture": cell.fixture.model_dump(),
        "rendered_user_prompt": user,
        "response": {
            "parsed": resp.parsed.model_dump() if resp.parsed is not None else None,
            "citations": resp.citations,
            "usage": resp.usage,
            "latency_ms": resp.latency_ms,
            "raw": _safe(resp.raw),
        },
        "error": resp.error,
    }
    (run_dir / cell.file_name()).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return resp


def _safe(obj):
    """Drop Authorization-like fields from raw responses before persisting."""
    if isinstance(obj, dict):
        return {
            k: "<masked>" if k.lower() in {"authorization", "api-key", "x-api-key"} else _safe(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_safe(v) for v in obj]
    return obj


def _new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]

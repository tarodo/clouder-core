"""Aurora Data API persistence for label enrichment."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping, TYPE_CHECKING

from ..data_api import DataAPIClient

if TYPE_CHECKING:
    from .schemas import LabelInfo
    from .vendors.base import VendorResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_NORM_RE = re.compile(r"\s+")


def _normalize_label(name: str) -> str:
    return _NORM_RE.sub(" ", name.strip().lower())


@dataclass(frozen=True)
class RunSpec:
    prompt_slug: str
    prompt_version: str
    vendors: list[str]
    models: dict[str, str]
    merge_vendor: str
    merge_model: str
    requested_labels: int
    created_by_user_id: str | None = None


class LabelEnrichmentRepository:
    def __init__(
        self,
        data_api: DataAPIClient,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._data_api = data_api
        self._now = now

    # ── labels ──────────────────────────────────────────────────────
    def upsert_label_by_name(self, name: str) -> str:
        normalized = _normalize_label(name)
        rows = self._data_api.execute(
            "SELECT id FROM clouder_labels WHERE normalized_name = :n LIMIT 1",
            {"n": normalized},
        )
        if rows:
            return rows[0]["id"]
        new_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_labels (
                id, name, normalized_name, is_ai_suspected,
                created_at, updated_at
            ) VALUES (
                :id, :name, :normalized_name, FALSE, :ts, :ts
            )
            """,
            {
                "id": new_id,
                "name": name.strip(),
                "normalized_name": normalized,
                "ts": ts,
            },
        )
        return new_id

    # ── runs ────────────────────────────────────────────────────────
    def create_run(self, spec: RunSpec) -> str:
        run_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_label_enrichment_runs (
                id, status, prompt_slug, prompt_version, vendors, models,
                merge_vendor, merge_model, requested_labels, cells_total,
                cells_ok, cells_error, cost_usd, created_by_user_id, created_at
            ) VALUES (
                :id, :status, :prompt_slug, :prompt_version, :vendors, :models,
                :merge_vendor, :merge_model, :requested_labels, :cells_total,
                0, 0, 0, :created_by_user_id, :created_at
            )
            """,
            {
                "id": run_id,
                "status": "queued",
                "prompt_slug": spec.prompt_slug,
                "prompt_version": spec.prompt_version,
                "vendors": json.dumps(spec.vendors),
                "models": json.dumps(spec.models),
                "merge_vendor": spec.merge_vendor,
                "merge_model": spec.merge_model,
                "requested_labels": spec.requested_labels,
                "cells_total": spec.requested_labels * len(spec.vendors),
                "created_by_user_id": spec.created_by_user_id,
                "created_at": ts,
            },
        )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT id, status, prompt_slug, prompt_version, vendors, models,
                   merge_vendor, merge_model, requested_labels, cells_total,
                   cells_ok, cells_error, cost_usd, created_by_user_id,
                   created_at, started_at, finished_at
            FROM clouder_label_enrichment_runs
            WHERE id = :id
            LIMIT 1
            """,
            {"id": run_id},
        )
        return rows[0] if rows else None

    # ── cells ───────────────────────────────────────────────────────
    def insert_cell(
        self,
        *,
        run_id: str,
        label_id: str,
        vendor: str,
        response: "VendorResponse",
    ) -> None:
        from .vendors.base import VendorResponse  # local — avoid cycle

        assert isinstance(response, VendorResponse)
        cell_id = str(uuid.uuid4())
        ts = self._now()
        status = "ok" if response.error is None and response.parsed is not None else "error"
        parsed_payload = (
            response.parsed.model_dump() if response.parsed is not None else None
        )
        error_payload = (
            json.dumps({"message": response.error}) if response.error is not None else None
        )
        self._data_api.execute(
            """
            INSERT INTO clouder_label_enrichment_cells (
                id, run_id, label_id, vendor, model, status,
                parsed, citations, usage, latency_ms, error, created_at
            ) VALUES (
                :id, :run_id, :label_id, :vendor, :model, :status,
                :parsed, :citations, :usage, :latency_ms, :error, :created_at
            )
            ON CONFLICT (run_id, label_id, vendor) DO NOTHING
            """,
            {
                "id": cell_id,
                "run_id": run_id,
                "label_id": label_id,
                "vendor": vendor,
                "model": response.model,
                "status": status,
                "parsed": json.dumps(parsed_payload) if parsed_payload is not None else None,
                "citations": json.dumps(response.citations),
                "usage": json.dumps(response.usage),
                "latency_ms": response.latency_ms,
                "error": error_payload,
                "created_at": ts,
            },
        )

    def mark_run_running(self, run_id: str) -> None:
        """Flip queued → running on first worker pickup. No-op when already running."""
        self._data_api.execute(
            """
            UPDATE clouder_label_enrichment_runs
            SET status = 'running', started_at = :ts
            WHERE id = :id AND status = 'queued'
            """,
            {"id": run_id, "ts": self._now()},
        )

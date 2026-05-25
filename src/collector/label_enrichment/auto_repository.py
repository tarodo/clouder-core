"""Aurora Data API persistence for auto-enrichment config + label claim state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..data_api import DataAPIClient

_MAX_ATTEMPTS = 2
_STALE_QUEUED_HOURS = 6


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json_col(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


class AutoEnrichRepository:
    def __init__(
        self,
        data_api: DataAPIClient,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._data_api = data_api
        self._now = now

    # ── config ──────────────────────────────────────────────────────
    def get_config(self, kind: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT kind, enabled, vendors, models, prompt_slug, prompt_version,
                   merge_vendor, merge_model
            FROM auto_enrich_config
            WHERE kind = :kind
            LIMIT 1
            """,
            {"kind": kind},
        )
        if not rows:
            return None
        row = dict(rows[0])
        row["vendors"] = _parse_json_col(row.get("vendors"), [])
        row["models"] = _parse_json_col(row.get("models"), {})
        row["enabled"] = bool(row.get("enabled"))
        return row

    def upsert_config(
        self,
        *,
        kind: str,
        enabled: bool,
        vendors: list[str],
        models: dict[str, str],
        prompt_slug: str | None,
        prompt_version: str | None,
        merge_vendor: str | None,
        merge_model: str | None,
        user_id: str | None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO auto_enrich_config (
                kind, enabled, vendors, models, prompt_slug, prompt_version,
                merge_vendor, merge_model, updated_at, updated_by_user_id
            ) VALUES (
                :kind, :enabled, :vendors, :models, :prompt_slug, :prompt_version,
                :merge_vendor, :merge_model, :updated_at, :updated_by_user_id
            )
            ON CONFLICT (kind) DO UPDATE SET
                enabled = EXCLUDED.enabled,
                vendors = EXCLUDED.vendors,
                models = EXCLUDED.models,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merge_vendor = EXCLUDED.merge_vendor,
                merge_model = EXCLUDED.merge_model,
                updated_at = EXCLUDED.updated_at,
                updated_by_user_id = EXCLUDED.updated_by_user_id
            """,
            {
                "kind": kind,
                "enabled": enabled,
                "vendors": list(vendors),
                "models": dict(models),
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merge_vendor": merge_vendor,
                "merge_model": merge_model,
                "updated_at": self._now(),
                "updated_by_user_id": user_id,
            },
        )

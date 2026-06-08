"""Aurora Data API persistence for auto-enrichment config + label claim state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..data_api import DataAPIClient

_MAX_ATTEMPTS = 2  # total attempts allowed per label: 1 initial + 1 retry
_STALE_QUEUED_HOURS = 6
_IN_CHUNK = 500


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

    # ── claim / state ───────────────────────────────────────────────
    def claim_labels(self, label_ids: list[str]) -> list[str]:
        """Atomically claim labels eligible for an auto-search.

        Per label, two independent statements:
          1. Reclaim an existing row that is `failed` (retry, capped at
             _MAX_ATTEMPTS) or a stale `queued` (worker likely died / enqueue
             failed). Returns the row when it claims it.
          2. Only if (1) claimed nothing: insert a brand-new row, but skip if a
             clouder_label_info row already exists (label was searched before,
             e.g. manually).
        `completed` rows and fresh `queued` rows match neither → skipped.
        ON CONFLICT DO NOTHING + the row-level UPDATE make concurrent adds of
        the same label race-safe: exactly one writer claims.
        """
        if not label_ids:
            return []
        now = self._now()
        stale_cutoff = now - timedelta(hours=_STALE_QUEUED_HOURS)
        unique = list(dict.fromkeys(label_ids))
        claimed: list[str] = []
        for start in range(0, len(unique), _IN_CHUNK):
            chunk = unique[start : start + _IN_CHUNK]
            placeholders = ", ".join(f":t{i}" for i in range(len(chunk)))
            id_params = {f"t{i}": v for i, v in enumerate(chunk)}

            reclaimed = self._data_api.execute(
                f"""
                UPDATE label_auto_enrich_state
                SET attempts = attempts + 1,
                    status = 'queued',
                    last_run_id = NULL,
                    updated_at = :ts
                WHERE label_id IN ({placeholders})
                  AND attempts < :max_attempts
                  AND (
                        status = 'failed'
                     OR (status = 'queued' AND updated_at < :stale_cutoff)
                  )
                RETURNING label_id
                """,
                {
                    **id_params,
                    "ts": now,
                    "max_attempts": _MAX_ATTEMPTS,
                    "stale_cutoff": stale_cutoff,
                },
            )

            values = ", ".join(f"(:t{i})" for i in range(len(chunk)))
            inserted = self._data_api.execute(
                f"""
                INSERT INTO label_auto_enrich_state (
                    label_id, attempts, status, first_enqueued_at, updated_at
                )
                SELECT v.label_id, 1, 'queued', :ts, :ts
                FROM (VALUES {values}) AS v(label_id)
                WHERE NOT EXISTS (
                    SELECT 1 FROM label_auto_enrich_state s
                    WHERE s.label_id = v.label_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM clouder_label_info i
                    WHERE i.label_id = v.label_id
                )
                ON CONFLICT (label_id) DO NOTHING
                RETURNING label_id
                """,
                {**id_params, "ts": now},
            )
            claimed.extend(r["label_id"] for r in reclaimed)
            claimed.extend(r["label_id"] for r in inserted)
        return claimed

    def attach_run(self, label_ids: list[str], run_id: str) -> None:
        """Stamp last_run_id on the given state rows.

        Intended to be called with the output of `claim_labels`; a label with
        no state row is silently skipped (no row matches the UPDATE).
        """
        ts = self._now()
        for label_id in label_ids:
            self._data_api.execute(
                """
                UPDATE label_auto_enrich_state
                SET last_run_id = :run_id, updated_at = :ts
                WHERE label_id = :label_id
                """,
                {"run_id": run_id, "label_id": label_id, "ts": ts},
            )

    def mark_auto_enrich_outcome(self, label_id: str, success: bool) -> None:
        """Worker touch: flip a queued auto-state row to completed/failed.

        No-op for labels with no auto-state row (manual runs) or already
        resolved rows — the `status = 'queued'` guard handles that.
        """
        new_status = "completed" if success else "failed"
        self._data_api.execute(
            """
            UPDATE label_auto_enrich_state
            SET status = :new_status, updated_at = :ts
            WHERE label_id = :label_id AND status = 'queued'
            """,
            {"new_status": new_status, "label_id": label_id, "ts": self._now()},
        )

    # ── label lookups ───────────────────────────────────────────────
    def label_id_for_track(self, track_id: str) -> str | None:
        rows = self._data_api.execute(
            """
            SELECT a.label_id
            FROM clouder_tracks t
            JOIN clouder_albums a ON a.id = t.album_id
            WHERE t.id = :track_id AND a.label_id IS NOT NULL
            LIMIT 1
            """,
            {"track_id": track_id},
        )
        return rows[0]["label_id"] if rows else None

    def label_ids_for_triage_block(self, block_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT a.label_id
            FROM category_tracks ct
            JOIN clouder_tracks t ON t.id = ct.track_id
            JOIN clouder_albums a ON a.id = t.album_id
            WHERE ct.source_triage_block_id = :block_id
              AND a.label_id IS NOT NULL
            """,
            {"block_id": block_id},
        )
        return [r["label_id"] for r in rows]

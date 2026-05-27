"""Aurora Data API persistence for auto-enrichment config + artist claim state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..data_api import DataAPIClient

_MAX_ATTEMPTS = 2  # total attempts allowed per artist: 1 initial + 1 retry
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

    # ── claim / state ───────────────────────────────────────────────
    def claim_artists(self, artist_ids: list[str]) -> list[str]:
        """Atomically claim artists eligible for an auto-search.

        Per artist, two independent statements:
          1. Reclaim an existing row that is `failed` (retry, capped at
             _MAX_ATTEMPTS) or a stale `queued` (worker likely died / enqueue
             failed). Returns the row when it claims it.
          2. Only if (1) claimed nothing: insert a brand-new row, but skip if a
             clouder_artist_info row already exists (artist was searched before,
             e.g. manually).
        `completed` rows and fresh `queued` rows match neither → skipped.
        ON CONFLICT DO NOTHING + the row-level UPDATE make concurrent adds of
        the same artist race-safe: exactly one writer claims.
        """
        if not artist_ids:
            return []
        now = self._now()
        stale_cutoff = now - timedelta(hours=_STALE_QUEUED_HOURS)
        claimed: list[str] = []
        for artist_id in artist_ids:
            params = {
                "artist_id": artist_id,
                "ts": now,
                "max_attempts": _MAX_ATTEMPTS,
                "stale_cutoff": stale_cutoff,
            }
            reclaimed = self._data_api.execute(
                """
                UPDATE artist_auto_enrich_state
                SET attempts = attempts + 1,
                    status = 'queued',
                    last_run_id = NULL,
                    updated_at = :ts
                WHERE artist_id = :artist_id
                  AND attempts < :max_attempts
                  AND (
                        status = 'failed'
                     OR (status = 'queued' AND updated_at < :stale_cutoff)
                  )
                RETURNING artist_id
                """,
                params,
            )
            if reclaimed:
                claimed.append(artist_id)
                continue
            inserted = self._data_api.execute(
                """
                INSERT INTO artist_auto_enrich_state (
                    artist_id, attempts, status, first_enqueued_at, updated_at
                )
                SELECT :artist_id, 1, 'queued', :ts, :ts
                WHERE NOT EXISTS (
                    SELECT 1 FROM artist_auto_enrich_state WHERE artist_id = :artist_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM clouder_artist_info WHERE artist_id = :artist_id
                )
                ON CONFLICT (artist_id) DO NOTHING
                RETURNING artist_id
                """,
                {"artist_id": artist_id, "ts": now},
            )
            if inserted:
                claimed.append(artist_id)
        return claimed

    def attach_run(self, artist_ids: list[str], run_id: str) -> None:
        """Stamp last_run_id on the given state rows.

        Intended to be called with the output of `claim_artists`; an artist with
        no state row is silently skipped (no row matches the UPDATE).
        """
        ts = self._now()
        for artist_id in artist_ids:
            self._data_api.execute(
                """
                UPDATE artist_auto_enrich_state
                SET last_run_id = :run_id, updated_at = :ts
                WHERE artist_id = :artist_id
                """,
                {"run_id": run_id, "artist_id": artist_id, "ts": ts},
            )

    def mark_auto_enrich_outcome(self, artist_id: str, success: bool) -> None:
        """Worker touch: flip a queued auto-state row to completed/failed.

        No-op for artists with no auto-state row (manual runs) or already
        resolved rows — the `status = 'queued'` guard handles that.
        """
        new_status = "completed" if success else "failed"
        self._data_api.execute(
            """
            UPDATE artist_auto_enrich_state
            SET status = :new_status, updated_at = :ts
            WHERE artist_id = :artist_id AND status = 'queued'
            """,
            {"new_status": new_status, "artist_id": artist_id, "ts": self._now()},
        )

    # ── artist lookups (all roles) ──────────────────────────────────
    def artist_ids_for_track(self, track_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT artist_id
            FROM clouder_track_artists
            WHERE track_id = :track_id
            """,
            {"track_id": track_id},
        )
        return [r["artist_id"] for r in rows]

    def artist_ids_for_triage_block(self, block_id: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT DISTINCT ta.artist_id
            FROM category_tracks ct
            JOIN clouder_track_artists ta ON ta.track_id = ct.track_id
            WHERE ct.source_triage_block_id = :block_id
            """,
            {"block_id": block_id},
        )
        return [r["artist_id"] for r in rows]

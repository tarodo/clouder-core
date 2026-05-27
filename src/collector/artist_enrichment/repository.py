"""Aurora Data API persistence for artist enrichment (core write path)."""

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
    from .schemas import ArtistInfo
    from ..label_enrichment.vendors.base import VendorResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_NORM_RE = re.compile(r"\s+")


def _normalize_name(name: str) -> str:
    return _NORM_RE.sub(" ", name.strip().lower())


def _pg_text_array(items: list[str]) -> str:
    parts = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        escaped = item.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{escaped}"')
    return "{" + ",".join(parts) + "}"


@dataclass(frozen=True)
class RunSpec:
    prompt_slug: str
    prompt_version: str
    vendors: list[str]
    models: dict[str, str]
    merge_vendor: str
    merge_model: str
    requested_artists: int
    created_by_user_id: str | None = None
    source: str = "manual"


@dataclass(frozen=True)
class ArtistContext:
    style: str
    sample_tracks: list[str]
    known_labels: list[str]


class ArtistEnrichmentRepository:
    def __init__(self, data_api: DataAPIClient, now: Callable[[], datetime] = _utc_now) -> None:
        self._data_api = data_api
        self._now = now

    # ── artists ─────────────────────────────────────────────────────
    def get_artist_by_id(self, artist_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            "SELECT id, name FROM clouder_artists WHERE id = :id LIMIT 1",
            {"id": artist_id},
        )
        return rows[0] if rows else None

    def upsert_artist_by_name(self, name: str) -> str:
        normalized = _normalize_name(name)
        rows = self._data_api.execute(
            "SELECT id FROM clouder_artists WHERE normalized_name = :n LIMIT 1",
            {"n": normalized},
        )
        if rows:
            return rows[0]["id"]
        new_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_artists (
                id, name, normalized_name, is_ai_suspected, created_at, updated_at
            ) VALUES (
                :id, :name, :normalized_name, FALSE, :ts, :ts
            )
            """,
            {"id": new_id, "name": name.strip(), "normalized_name": normalized, "ts": ts},
        )
        return new_id

    def derive_artist_context(self, artist_id: str) -> ArtistContext:
        """Disambiguation context from the artist's tracks: dominant style,
        up to 3 recent track titles, and the distinct labels of those tracks."""
        style_rows = self._data_api.execute(
            """
            SELECT s.name AS style_name, COUNT(*) AS cnt
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            JOIN clouder_styles s ON s.id = t.style_id
            WHERE ta.artist_id = :artist_id
            GROUP BY s.name
            ORDER BY cnt DESC
            LIMIT 1
            """,
            {"artist_id": artist_id},
        )
        style = (style_rows[0].get("style_name") if style_rows else None) or "music"

        track_rows = self._data_api.execute(
            """
            SELECT t.title AS title
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            WHERE ta.artist_id = :artist_id
            ORDER BY t.publish_date DESC NULLS LAST, t.id DESC
            LIMIT 3
            """,
            {"artist_id": artist_id},
        )
        sample_tracks = [r["title"] for r in track_rows if r.get("title")]

        label_rows = self._data_api.execute(
            """
            SELECT DISTINCT l.name AS label_name
            FROM clouder_track_artists ta
            JOIN clouder_tracks t ON t.id = ta.track_id
            JOIN clouder_albums a ON a.id = t.album_id
            JOIN clouder_labels l ON l.id = a.label_id
            WHERE ta.artist_id = :artist_id AND a.label_id IS NOT NULL
            LIMIT 5
            """,
            {"artist_id": artist_id},
        )
        known_labels = [r["label_name"] for r in label_rows if r.get("label_name")]
        return ArtistContext(style=style, sample_tracks=sample_tracks, known_labels=known_labels)

    # ── runs ────────────────────────────────────────────────────────
    def create_run(self, spec: RunSpec) -> str:
        run_id = str(uuid.uuid4())
        ts = self._now()
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_enrichment_runs (
                id, status, prompt_slug, prompt_version, vendors, models,
                merge_vendor, merge_model, requested_artists, cells_total,
                cells_ok, cells_error, cost_usd, created_by_user_id, created_at, source
            ) VALUES (
                :id, :status, :prompt_slug, :prompt_version, :vendors, :models,
                :merge_vendor, :merge_model, :requested_artists, :cells_total,
                0, 0, 0, :created_by_user_id, :created_at, :source
            )
            """,
            {
                "id": run_id,
                "status": "queued",
                "prompt_slug": spec.prompt_slug,
                "prompt_version": spec.prompt_version,
                "vendors": list(spec.vendors),
                "models": dict(spec.models),
                "merge_vendor": spec.merge_vendor,
                "merge_model": spec.merge_model,
                "requested_artists": spec.requested_artists,
                "cells_total": spec.requested_artists * len(spec.vendors),
                "created_by_user_id": spec.created_by_user_id,
                "created_at": ts,
                "source": spec.source,
            },
        )
        return run_id

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT id, status, prompt_slug, prompt_version, vendors, models,
                   merge_vendor, merge_model, requested_artists, cells_total,
                   cells_ok, cells_error, cost_usd, created_by_user_id,
                   created_at, started_at, finished_at, source
            FROM clouder_artist_enrichment_runs
            WHERE id = :id
            LIMIT 1
            """,
            {"id": run_id},
        )
        if not rows:
            return None
        row = dict(rows[0])
        vendors_raw = row.get("vendors")
        if isinstance(vendors_raw, str):
            row["vendors"] = json.loads(vendors_raw)
        models_raw = row.get("models")
        if isinstance(models_raw, str):
            row["models"] = json.loads(models_raw)
        cost_usd = row.get("cost_usd")
        if isinstance(cost_usd, Decimal):
            row["cost_usd"] = float(cost_usd)
        elif isinstance(cost_usd, str):
            try:
                row["cost_usd"] = float(cost_usd)
            except (TypeError, ValueError):
                pass
        return row

    def mark_run_running(self, run_id: str) -> None:
        self._data_api.execute(
            """
            UPDATE clouder_artist_enrichment_runs
            SET status = 'running', started_at = :ts
            WHERE id = :id AND status = 'queued'
            """,
            {"id": run_id, "ts": self._now()},
        )

    def increment_run_counters(
        self, *, run_id: str, ok_delta: int, error_delta: int, cost_delta: float
    ) -> None:
        self._data_api.execute(
            """
            UPDATE clouder_artist_enrichment_runs
            SET
                cells_ok = cells_ok + :ok,
                cells_error = cells_error + :err,
                cost_usd = cost_usd + :cost,
                status = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN 'completed' ELSE status END,
                finished_at = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN :ts ELSE finished_at END
            WHERE id = :id
            """,
            {
                "id": run_id,
                "ok": ok_delta,
                "err": error_delta,
                "cost": Decimal(str(round(cost_delta, 4))),
                "ts": self._now(),
            },
        )

    # ── cells ───────────────────────────────────────────────────────
    def insert_cell(
        self, *, run_id: str, artist_id: str, vendor: str, response: "VendorResponse"
    ) -> None:
        from ..label_enrichment.vendors.base import VendorResponse

        assert isinstance(response, VendorResponse)
        cell_id = str(uuid.uuid4())
        ts = self._now()
        status = "ok" if response.error is None and response.parsed is not None else "error"
        parsed_payload = response.parsed.model_dump() if response.parsed is not None else None
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_enrichment_cells (
                id, run_id, artist_id, vendor, model, status,
                parsed, citations, usage, latency_ms, error, created_at
            ) VALUES (
                :id, :run_id, :artist_id, :vendor, :model, :status,
                :parsed, :citations, :usage, :latency_ms, :error, :created_at
            )
            ON CONFLICT (run_id, artist_id, vendor) DO NOTHING
            """,
            {
                "id": cell_id,
                "run_id": run_id,
                "artist_id": artist_id,
                "vendor": vendor,
                "model": response.model,
                "status": status,
                "parsed": parsed_payload,
                "citations": list(response.citations),
                "usage": dict(response.usage),
                "latency_ms": response.latency_ms,
                "error": {"message": response.error} if response.error is not None else None,
                "created_at": ts,
            },
        )

    # ── artist_info ─────────────────────────────────────────────────
    def upsert_artist_info(
        self, *, artist_id: str, last_run_id: str, prompt_slug: str,
        prompt_version: str, merged: "ArtistInfo", provenance: Mapping[str, Any],
    ) -> None:
        ts = self._now()
        payload = merged.model_dump(mode="json")  # coerces enums to wire str
        self._data_api.execute(
            """
            INSERT INTO clouder_artist_info (
                artist_id, last_run_id, prompt_slug, prompt_version,
                merged, provenance,
                ai_content, ai_confidence, status, primary_styles,
                artist_type, country, active_since, tagline, updated_at
            ) VALUES (
                :artist_id, :last_run_id, :prompt_slug, :prompt_version,
                :merged, :provenance,
                :ai_content, :ai_confidence, :status, CAST(:primary_styles AS text[]),
                :artist_type, :country, :active_since, :tagline, :updated_at
            )
            ON CONFLICT (artist_id) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merged = EXCLUDED.merged,
                provenance = EXCLUDED.provenance,
                ai_content = EXCLUDED.ai_content,
                ai_confidence = EXCLUDED.ai_confidence,
                status = EXCLUDED.status,
                primary_styles = EXCLUDED.primary_styles,
                artist_type = EXCLUDED.artist_type,
                country = EXCLUDED.country,
                active_since = EXCLUDED.active_since,
                tagline = EXCLUDED.tagline,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "artist_id": artist_id,
                "last_run_id": last_run_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merged": payload,
                "provenance": dict(provenance),
                "ai_content": payload.get("ai_content", "unknown"),
                "ai_confidence": Decimal(str(round(payload.get("confidence", 0.0), 2))),
                "status": payload.get("status", "unknown"),
                "primary_styles": _pg_text_array(payload.get("primary_styles") or []),
                "artist_type": payload.get("artist_type"),
                "country": payload.get("country"),
                "active_since": payload.get("active_since"),
                "tagline": payload.get("tagline"),
                "updated_at": ts,
            },
        )

    def project_ai_suspected(self, artist_id: str, merged: "ArtistInfo", threshold: float) -> None:
        """Mirror merged.ai_content into clouder_artists.is_ai_suspected when confidence >= threshold."""
        from .schemas import AIContentStatus

        if merged.confidence < threshold:
            return
        if merged.ai_content in (AIContentStatus.SUSPECTED, AIContentStatus.CONFIRMED):
            value = True
        elif merged.ai_content == AIContentStatus.NONE_DETECTED:
            value = False
        else:
            return
        self._data_api.execute(
            """
            UPDATE clouder_artists
            SET is_ai_suspected = :value, updated_at = :ts
            WHERE id = :id
            """,
            {"value": value, "ts": self._now(), "id": artist_id},
        )

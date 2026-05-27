"""Aurora Data API persistence for artist enrichment (core write path)."""

from __future__ import annotations

import base64
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

# Postgres expression: slugify a style name for FE comparison.
# Example: "Drum & Bass" -> "drum-and-bass". Maps "&" -> "and" before stripping
# non-alphanumerics so the slug matches the form used by the frontend URLs.
_STYLE_SLUG_EXPR = (
    "TRIM(BOTH '-' FROM "
    "LOWER(REGEXP_REPLACE(REPLACE(s.name, '&', 'and'), '[^a-zA-Z0-9]+', '-', 'g'))"
    ")"
)

# Admin-only fields stripped from user-facing responses.
_USER_FACING_FORBIDDEN = frozenset({
    "run_id", "prompt_slug", "prompt_version",
    "vendors_used", "merged_at_run_id",
    "token_cost", "cost_usd", "provenance",
})


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

    # ── artist_info (read) ──────────────────────────────────────────
    def get_artist_info(self, artist_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT
                ai.artist_id, art.name AS artist_name, ai.last_run_id,
                ai.prompt_slug, ai.prompt_version,
                ai.merged, ai.provenance,
                ai.ai_content, ai.ai_confidence, ai.status, ai.primary_styles,
                ai.tagline, ai.country, ai.artist_type, ai.active_since,
                ai.updated_at
            FROM clouder_artist_info ai
            JOIN clouder_artists art ON art.id = ai.artist_id
            WHERE ai.artist_id = :id
            LIMIT 1
            """,
            {"id": artist_id},
        )
        if not rows:
            return None
        row = dict(rows[0])
        merged_raw = row.get("merged")
        if isinstance(merged_raw, str):
            row["merged"] = json.loads(merged_raw)
        provenance_raw = row.get("provenance")
        if isinstance(provenance_raw, str):
            row["provenance"] = json.loads(provenance_raw)
        ai_conf = row.get("ai_confidence")
        if isinstance(ai_conf, Decimal):
            row["ai_confidence"] = float(ai_conf)
        elif isinstance(ai_conf, str):
            try:
                row["ai_confidence"] = float(ai_conf)
            except (TypeError, ValueError):
                pass
        return row

    def get_artist_info_for_user(
        self,
        artist_id: str,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return decoded merged ArtistInfo for a user-facing detail page.

        When `clouder_artist_info` has a row, returns the decoded `merged`
        JSONB blob with admin-only fields stripped, plus `my_preference`.
        When the row is missing but the artist exists, returns a minimal
        `{artist_name, my_preference}` payload so preference buttons can
        still render on the detail page. Returns None only when the artist
        itself does not exist.
        """
        rows = self._data_api.execute(
            """
            SELECT ai.merged, uap.status AS my_preference
            FROM clouder_artist_info ai
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = ai.artist_id AND uap.user_id = :user_id
            WHERE ai.artist_id = :id
            LIMIT 1
            """,
            {"id": artist_id, "user_id": user_id or ""},
        )
        if rows:
            merged = rows[0].get("merged")
            if isinstance(merged, str):
                merged = json.loads(merged)
            if not isinstance(merged, dict):
                return None
            out = {k: v for k, v in merged.items() if k not in _USER_FACING_FORBIDDEN}
            out["my_preference"] = rows[0].get("my_preference")
            return out

        fallback = self._data_api.execute(
            """
            SELECT art.name AS artist_name, uap.status AS my_preference
            FROM clouder_artists art
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = art.id AND uap.user_id = :user_id
            WHERE art.id = :id
            LIMIT 1
            """,
            {"id": artist_id, "user_id": user_id or ""},
        )
        if not fallback:
            return None
        row = fallback[0]
        return {
            "artist_name": row.get("artist_name"),
            "my_preference": row.get("my_preference"),
        }

    # ── runs (read) ──────────────────────────────────────────────────
    def list_runs(
        self,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
        source: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Admin runs list, sorted by created_at DESC."""
        where = ["1=1"]
        params: dict[str, Any] = {"lim": limit + 1}
        if status:
            where.append("status = :status")
            params["status"] = status
        if source:
            where.append("source = :source")
            params["source"] = source
        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
                last_ts, last_id = decoded.rsplit("|", 1)
                where.append("(created_at, id) < (CAST(:cur_ts AS timestamptz), :cur_id)")
                params["cur_ts"] = last_ts
                params["cur_id"] = last_id
            except Exception:
                pass

        rows = self._data_api.execute(
            f"""
            SELECT id, status, prompt_slug, prompt_version, vendors, models,
                   merge_vendor, merge_model, requested_artists, cells_total,
                   cells_ok, cells_error, cost_usd, created_at, started_at, finished_at, source
            FROM clouder_artist_enrichment_runs
            WHERE {' AND '.join(where) if where else 'TRUE'}
            ORDER BY created_at DESC, id DESC
            LIMIT :lim
            """,
            params,
        )

        has_more = len(rows) > limit
        page = rows[:limit]

        items = []
        for r in page:
            row = dict(r)
            for json_col in ("vendors", "models"):
                v = row.get(json_col)
                if isinstance(v, str):
                    row[json_col] = json.loads(v)
            cost = row.get("cost_usd")
            if isinstance(cost, Decimal):
                row["cost_usd"] = float(cost)
            items.append(row)

        next_cursor = None
        if has_more and page:
            last = page[-1]
            created_at_val = last.get("created_at")
            if isinstance(created_at_val, datetime):
                ts_str = created_at_val.isoformat()
            else:
                ts_str = str(created_at_val)
            raw = f"{ts_str}|{last['id']}"
            next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()

        return items, next_cursor

    def list_cells_for_run(self, run_id: str) -> list[dict[str, Any]]:
        """Per-cell breakdown for a run. Joined with clouder_artists for artist_name."""
        rows = self._data_api.execute(
            """
            SELECT c.id AS cell_id, c.artist_id, art.name AS artist_name,
                   c.vendor, c.status, c.latency_ms,
                   (c.usage->>'cost_usd')::numeric AS cost_usd,
                   c.error->>'message' AS error_message
            FROM clouder_artist_enrichment_cells c
            JOIN clouder_artists art ON art.id = c.artist_id
            WHERE c.run_id = :run_id
            ORDER BY c.artist_id, c.vendor
            """,
            {"run_id": run_id},
        )
        items = []
        for r in rows:
            row = dict(r)
            cost = row.get("cost_usd")
            if isinstance(cost, Decimal):
                row["cost_usd"] = float(cost)
            elif isinstance(cost, str):
                try:
                    row["cost_usd"] = float(cost)
                except (TypeError, ValueError):
                    row["cost_usd"] = None
            items.append(row)
        return items

    def list_history_for_artist(self, artist_id: str) -> list[dict[str, Any]]:
        """Per-artist enrichment history."""
        rows = self._data_api.execute(
            """
            SELECT c.id AS cell_id,
                   c.run_id, r.status AS run_status, r.created_at AS run_created_at,
                   r.prompt_slug, r.prompt_version,
                   c.vendor, c.model, c.status, c.latency_ms,
                   (c.usage->>'cost_usd')::numeric AS cost_usd,
                   c.error->>'message' AS error_message,
                   c.parsed AS parsed,
                   c.citations AS citations
            FROM clouder_artist_enrichment_cells c
            JOIN clouder_artist_enrichment_runs r ON r.id = c.run_id
            WHERE c.artist_id = :artist_id
            ORDER BY r.created_at DESC, c.vendor ASC
            """,
            {"artist_id": artist_id},
        )
        items: list[dict[str, Any]] = []
        for r in rows:
            row = dict(r)
            cost = row.get("cost_usd")
            if isinstance(cost, Decimal):
                row["cost_usd"] = float(cost)
            elif isinstance(cost, str):
                try:
                    row["cost_usd"] = float(cost)
                except (TypeError, ValueError):
                    row["cost_usd"] = None
            for json_col in ("parsed", "citations"):
                v = row.get(json_col)
                if isinstance(v, str):
                    try:
                        row[json_col] = json.loads(v)
                    except json.JSONDecodeError:
                        pass
            items.append(row)
        return items

    # ── user artist preferences ─────────────────────────────────────
    def upsert_user_artist_pref(
        self,
        *,
        user_id: str,
        artist_id: str,
        status: str,
    ) -> None:
        if status not in ("liked", "disliked"):
            raise ValueError(f"status must be 'liked' or 'disliked', got {status!r}")
        self._data_api.execute(
            """
            INSERT INTO clouder_user_artist_prefs (user_id, artist_id, status, updated_at)
            VALUES (:user_id, :artist_id, :status, :ts)
            ON CONFLICT (user_id, artist_id) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "user_id": user_id,
                "artist_id": artist_id,
                "status": status,
                "ts": self._now(),
            },
        )

    def delete_user_artist_pref(self, *, user_id: str, artist_id: str) -> None:
        self._data_api.execute(
            "DELETE FROM clouder_user_artist_prefs WHERE user_id = :user_id AND artist_id = :artist_id",
            {"user_id": user_id, "artist_id": artist_id},
        )

    def list_user_artist_prefs(
        self,
        *,
        user_id: str,
        status: str,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        if status not in ("liked", "disliked"):
            raise ValueError(f"status must be 'liked' or 'disliked', got {status!r}")
        offset = max(page - 1, 0) * limit
        rows = self._data_api.execute(
            """
            SELECT art.id, art.name, p.status
            FROM clouder_user_artist_prefs p
            JOIN clouder_artists art ON art.id = p.artist_id
            WHERE p.user_id = :user_id AND p.status = :status
            ORDER BY p.updated_at DESC, art.id DESC
            LIMIT :lim OFFSET :off
            """,
            {"user_id": user_id, "status": status, "lim": limit, "off": offset},
        )
        items = [
            {"id": r["id"], "name": r["name"], "my_preference": r["status"]}
            for r in rows
        ]
        total_rows = self._data_api.execute(
            """
            SELECT COUNT(*) AS c
            FROM clouder_user_artist_prefs p
            WHERE p.user_id = :user_id AND p.status = :status
            """,
            {"user_id": user_id, "status": status},
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total

    # ── artist list (user-facing) ────────────────────────────────────
    def list_artists(
        self,
        *,
        style: str | None,
        q: str | None,
        sort: str,
        page: int,
        limit: int,
        user_id: str | None = None,
        my: str = "all",
    ) -> tuple[list[dict[str, Any]], int]:
        if my not in ("all", "liked", "disliked", "unrated"):
            raise ValueError(f"my must be one of all|liked|disliked|unrated, got {my!r}")

        where: list[str] = []
        params: dict[str, Any] = {"lim": limit, "off": max(page - 1, 0) * limit}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM artist_style_counts asc2 "
                "WHERE asc2.artist_id = art.id AND asc2.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if q:
            where.append("LOWER(art.name) LIKE :q")
            params["q"] = f"{q.lower()}%"
        params["pref_user_id"] = user_id or ""
        if my == "liked":
            where.append("uap.status = 'liked'")
        elif my == "disliked":
            where.append("uap.status = 'disliked'")
        elif my == "unrated":
            where.append("uap.user_id IS NULL")

        order_by = (
            "ai.updated_at DESC NULLS LAST, art.id DESC"
            if sort == "recent"
            else "art.name ASC, art.id ASC"
        )
        where_sql = " AND ".join(where) if where else "TRUE"

        ctes = f"""
            WITH artist_track_counts AS (
                SELECT ta.artist_id, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                GROUP BY ta.artist_id
            ),
            artist_style_counts AS (
                SELECT ta.artist_id, {_STYLE_SLUG_EXPR} AS style_slug, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                JOIN clouder_tracks t ON t.id = ta.track_id
                JOIN clouder_styles s ON s.id = t.style_id
                GROUP BY ta.artist_id, s.name
            ),
            artist_dominant_style AS (
                SELECT DISTINCT ON (artist_id) artist_id, style_slug
                FROM artist_style_counts
                ORDER BY artist_id, cnt DESC
            )
        """

        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT art.id, art.name,
                   CASE WHEN ai.artist_id IS NULL THEN 'none' ELSE 'completed' END AS status,
                   ai.tagline, ai.country, ai.active_since, ai.primary_styles,
                   ai.artist_type, ai.ai_content, ai.updated_at,
                   ads.style_slug AS dominant_style,
                   COALESCE(atc.cnt, 0) AS track_count,
                   uap.status AS my_preference
            FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN artist_dominant_style ads ON ads.artist_id = art.id
            LEFT JOIN artist_track_counts atc ON atc.artist_id = art.id
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = art.id AND uap.user_id = :pref_user_id
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT :lim OFFSET :off
            """,
            params,
        )

        items: list[dict[str, Any]] = []
        for r in rows:
            info = None
            if r.get("status") == "completed":
                info = {
                    "tagline": r.get("tagline"),
                    "country": r.get("country"),
                    "active_since": r.get("active_since"),
                    "primary_styles": r.get("primary_styles") or [],
                    "artist_type": r.get("artist_type"),
                    "ai_content": r.get("ai_content"),
                    "updated_at": r.get("updated_at"),
                }
            items.append({
                "id": r["id"],
                "name": r["name"],
                "style": r.get("dominant_style") or "",
                "status": r.get("status") or "none",
                "track_count": int(r.get("track_count") or 0),
                "info": info,
                "my_preference": r.get("my_preference"),
            })

        count_params = {k: v for k, v in params.items() if k not in ("lim", "off")}
        total_rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT COUNT(*) AS c
            FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN clouder_user_artist_prefs uap
                ON uap.artist_id = art.id AND uap.user_id = :pref_user_id
            WHERE {where_sql}
            """,
            count_params,
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total

    # ── backlog (admin) ──────────────────────────────────────────────
    def list_backlog(
        self,
        *,
        style: str | None,
        status: str | None,
        cursor: str | None,
        limit: int,
        staleness_days: int = 180,
    ) -> tuple[list[dict[str, Any]], str | None, int]:
        """Admin artist list with optional status filter.

        `status` accepts: `none`, `completed`, `outdated`, `all`.
        Per-artist stats (track_count, dominant style) are pre-aggregated in
        CTEs over `clouder_track_artists` (many-to-many).
        """
        stale_clause = (
            "ai.updated_at < NOW() - INTERVAL '" + str(int(staleness_days)) + " days'"
        )
        where: list[str] = []
        params: dict[str, Any] = {"lim": limit + 1}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM artist_style_counts asc2 "
                "WHERE asc2.artist_id = art.id AND asc2.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if status and status != "all":
            if status == "none":
                where.append("ai.artist_id IS NULL")
            elif status == "completed":
                where.append(f"ai.artist_id IS NOT NULL AND NOT ({stale_clause})")
            elif status == "outdated":
                where.append(f"ai.artist_id IS NOT NULL AND {stale_clause}")

        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
                last_count, last_id = decoded.rsplit("|", 1)
                params["cur_count"] = int(last_count)
                params["cur_id"] = last_id
                where.append("(COALESCE(atc.cnt, 0), art.id) < (:cur_count, :cur_id)")
            except Exception:
                pass

        ctes = f"""
            WITH artist_track_counts AS (
                SELECT ta.artist_id, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                GROUP BY ta.artist_id
            ),
            artist_style_counts AS (
                SELECT ta.artist_id, {_STYLE_SLUG_EXPR} AS style_slug, COUNT(*) AS cnt
                FROM clouder_track_artists ta
                JOIN clouder_tracks t ON t.id = ta.track_id
                JOIN clouder_styles s ON s.id = t.style_id
                GROUP BY ta.artist_id, s.name
            ),
            artist_dominant_style AS (
                SELECT DISTINCT ON (artist_id) artist_id, style_slug
                FROM artist_style_counts
                ORDER BY artist_id, cnt DESC
            )
        """
        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT art.id, art.name,
                   ads.style_slug AS style,
                   COALESCE(atc.cnt, 0) AS track_count,
                   CASE
                     WHEN ai.artist_id IS NULL THEN 'none'
                     WHEN {stale_clause} THEN 'outdated'
                     ELSE 'completed'
                   END AS status,
                   ai.updated_at AS last_attempted_at
            FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN artist_track_counts atc ON atc.artist_id = art.id
            LEFT JOIN artist_dominant_style ads ON ads.artist_id = art.id
            WHERE {' AND '.join(where) if where else 'TRUE'}
            ORDER BY COALESCE(atc.cnt, 0) DESC, art.id DESC
            LIMIT :lim
            """,
            params,
        )

        has_more = len(rows) > limit
        page = rows[:limit]

        items = [
            {
                "id": r["id"],
                "name": r["name"],
                "style": r.get("style") or "",
                "status": r["status"],
                "track_count": int(r.get("track_count") or 0),
                "last_attempted_at": r.get("last_attempted_at"),
            }
            for r in page
        ]

        next_cursor = None
        if has_more and page:
            last = page[-1]
            raw = f"{last['track_count']}|{last['id']}"
            next_cursor = base64.urlsafe_b64encode(raw.encode()).decode()

        # Total estimate: same predicate set MINUS the cursor clauses.
        total_where = [w for w in where if "cur_" not in w]
        total_params = {k: v for k, v in params.items() if not k.startswith("cur_") and k != "lim"}
        total_rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT COUNT(*) AS c FROM clouder_artists art
            LEFT JOIN clouder_artist_info ai ON ai.artist_id = art.id
            LEFT JOIN artist_track_counts atc ON atc.artist_id = art.id
            WHERE {' AND '.join(total_where) if total_where else 'TRUE'}
            """,
            total_params,
        )
        total_estimate = int(total_rows[0]["c"]) if total_rows else 0

        return items, next_cursor, total_estimate

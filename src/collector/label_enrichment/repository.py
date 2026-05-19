"""Aurora Data API persistence for label enrichment."""

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
    from .schemas import LabelInfo
    from .vendors.base import VendorResponse


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


_NORM_RE = re.compile(r"\s+")


def _normalize_label(name: str) -> str:
    return _NORM_RE.sub(" ", name.strip().lower())


# Postgres expression: slugify a style name for FE comparison.
# Example: "Drum & Bass" -> "drum-and-bass". Maps "&" -> "and" before stripping
# non-alphanumerics so the slug matches the form used by the frontend URLs.
_STYLE_SLUG_EXPR = (
    "TRIM(BOTH '-' FROM "
    "LOWER(REGEXP_REPLACE(REPLACE(s.name, '&', 'and'), '[^a-zA-Z0-9]+', '-', 'g'))"
    ")"
)


def _pg_text_array(items: list[str]) -> str:
    """Format a Python list as a PostgreSQL text[] array literal.

    Each element is double-quoted with backslashes and inner double-quotes escaped.
    """
    parts = []
    for item in items:
        if not isinstance(item, str):
            item = str(item)
        escaped = item.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{escaped}"')
    return "{" + ",".join(parts) + "}"


# Admin-only fields stripped from user-facing responses.
_USER_FACING_FORBIDDEN = frozenset({
    "run_id", "prompt_slug", "prompt_version",
    "vendors_used", "merged_at_run_id",
    "token_cost", "cost_usd", "provenance",
})


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
    def get_label_by_id(self, label_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            "SELECT id, name FROM clouder_labels WHERE id = :id LIMIT 1",
            {"id": label_id},
        )
        return rows[0] if rows else None

    def list_labels(
        self,
        *,
        style: str | None,
        q: str | None,
        sort: str,
        page: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """User-facing label list with page-based pagination.

        Returns (items, total). `page` is 1-indexed; offset = (page - 1) * limit.
        Per-label dominant_style is precomputed in a CTE so we don't fire
        a correlated subquery per row.
        """
        where: list[str] = []
        params: dict[str, Any] = {"lim": limit, "off": max(page - 1, 0) * limit}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM label_style_counts lsc "
                "WHERE lsc.label_id = lbl.id AND lsc.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if q:
            where.append("LOWER(lbl.name) LIKE :q")
            params["q"] = f"{q.lower()}%"

        order_by = (
            "li.updated_at DESC NULLS LAST, lbl.id DESC"
            if sort == "recent"
            else "lbl.name ASC, lbl.id ASC"
        )
        where_sql = " AND ".join(where) if where else "TRUE"

        ctes = f"""
            WITH label_track_counts AS (
                SELECT a.label_id, COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id
            ),
            label_style_counts AS (
                SELECT
                    a.label_id,
                    {_STYLE_SLUG_EXPR} AS style_slug,
                    COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                JOIN clouder_styles s ON s.id = t.style_id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id, s.name
            ),
            label_dominant_style AS (
                SELECT DISTINCT ON (label_id) label_id, style_slug
                FROM label_style_counts
                ORDER BY label_id, cnt DESC
            )
        """

        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT lbl.id, lbl.name,
                   CASE WHEN li.label_id IS NULL THEN 'none' ELSE 'completed' END AS status,
                   li.tagline, li.country, li.founded_year, li.primary_styles,
                   li.activity, li.ai_content, li.updated_at,
                   lds.style_slug AS dominant_style,
                   COALESCE(ltc.cnt, 0) AS track_count
            FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            LEFT JOIN label_dominant_style lds ON lds.label_id = lbl.id
            LEFT JOIN label_track_counts ltc ON ltc.label_id = lbl.id
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
                primary = r.get("primary_styles") or []
                info = {
                    "tagline": r.get("tagline"),
                    "country": r.get("country"),
                    "founded_year": r.get("founded_year"),
                    "primary_styles": primary,
                    "activity": r.get("activity") or "unknown",
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
            })

        count_params = {k: v for k, v in params.items() if k not in ("lim", "off")}
        total_rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT COUNT(*) AS c
            FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            WHERE {where_sql}
            """,
            count_params,
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total

    def list_backlog(
        self,
        *,
        style: str | None,
        status: str | None,
        cursor: str | None,
        limit: int,
        staleness_days: int = 180,
    ) -> tuple[list[dict[str, Any]], str | None, int]:
        """Admin label list with optional status filter.

        `status` accepts: `none`, `failed`, `outdated`, `completed`, `queued`,
        `running`. When omitted (or `all`) the response covers every label,
        which lets the admin browse already-enriched labels alongside the
        backlog. Per-label stats (track_count, dominant style) are
        pre-aggregated in CTEs so we don't fire correlated subqueries for
        each of the ~2.6k labels on every request.
        """
        stale_clause = (
            "li.updated_at < NOW() - INTERVAL '" + str(int(staleness_days)) + " days'"
        )
        where: list[str] = []
        params: dict[str, Any] = {"lim": limit + 1}
        if style:
            where.append(
                "EXISTS (SELECT 1 FROM label_style_counts lsc "
                "WHERE lsc.label_id = lbl.id AND lsc.style_slug = LOWER(:style))"
            )
            params["style"] = style
        if status and status != "all":
            if status == "none":
                # No clouder_label_info row at all.
                where.append("li.label_id IS NULL")
            elif status == "completed":
                where.append(f"li.label_id IS NOT NULL AND NOT ({stale_clause})")
            elif status == "outdated":
                where.append(f"li.label_id IS NOT NULL AND {stale_clause}")

        if cursor:
            try:
                decoded = base64.urlsafe_b64decode(cursor.encode()).decode()
                last_count, last_id = decoded.rsplit("|", 1)
                params["cur_count"] = int(last_count)
                params["cur_id"] = last_id
                where.append("(COALESCE(ltc.cnt, 0), lbl.id) < (:cur_count, :cur_id)")
            except Exception:
                pass

        ctes = f"""
            WITH label_track_counts AS (
                SELECT a.label_id, COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id
            ),
            label_style_counts AS (
                SELECT
                    a.label_id,
                    {_STYLE_SLUG_EXPR} AS style_slug,
                    COUNT(*) AS cnt
                FROM clouder_albums a
                JOIN clouder_tracks t ON t.album_id = a.id
                JOIN clouder_styles s ON s.id = t.style_id
                WHERE a.label_id IS NOT NULL
                GROUP BY a.label_id, s.name
            ),
            label_dominant_style AS (
                SELECT DISTINCT ON (label_id) label_id, style_slug
                FROM label_style_counts
                ORDER BY label_id, cnt DESC
            )
        """
        rows = self._data_api.execute(
            f"""
            {ctes}
            SELECT lbl.id, lbl.name,
                   lds.style_slug AS style,
                   COALESCE(ltc.cnt, 0) AS track_count,
                   CASE
                     WHEN li.label_id IS NULL THEN 'none'
                     WHEN {stale_clause} THEN 'outdated'
                     ELSE 'completed'
                   END AS status,
                   li.updated_at AS last_attempted_at
            FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            LEFT JOIN label_track_counts ltc ON ltc.label_id = lbl.id
            LEFT JOIN label_dominant_style lds ON lds.label_id = lbl.id
            WHERE {' AND '.join(where) if where else 'TRUE'}
            ORDER BY COALESCE(ltc.cnt, 0) DESC, lbl.id DESC
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
            SELECT COUNT(*) AS c FROM clouder_labels lbl
            LEFT JOIN clouder_label_info li ON li.label_id = lbl.id
            LEFT JOIN label_track_counts ltc ON ltc.label_id = lbl.id
            WHERE {' AND '.join(total_where) if total_where else 'TRUE'}
            """,
            total_params,
        )
        total_estimate = int(total_rows[0]["c"]) if total_rows else 0

        return items, next_cursor, total_estimate

    def list_runs(
        self,
        *,
        status: str | None,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Admin runs list, sorted by created_at DESC."""
        where = ["1=1"]
        params: dict[str, Any] = {"lim": limit + 1}
        if status:
            where.append("status = :status")
            params["status"] = status
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
                   merge_vendor, merge_model, requested_labels, cells_total,
                   cells_ok, cells_error, cost_usd, created_at, started_at, finished_at
            FROM clouder_label_enrichment_runs
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
        """Per-cell breakdown for a run. Joined with clouder_labels for label_name.

        Schema notes:
        - clouder_label_enrichment_cells stores `error` as JSONB ({"message": ...}),
          not a flat text column — surface it as `error_message`.
        - Per-cell cost is not a column; vendors report it inside `usage.cost_usd`,
          so we project that as `cost_usd` for the frontend.
        """
        rows = self._data_api.execute(
            """
            SELECT c.id AS cell_id, c.label_id, lbl.name AS label_name,
                   c.vendor, c.status, c.latency_ms,
                   (c.usage->>'cost_usd')::numeric AS cost_usd,
                   c.error->>'message' AS error_message
            FROM clouder_label_enrichment_cells c
            JOIN clouder_labels lbl ON lbl.id = c.label_id
            WHERE c.run_id = :run_id
            ORDER BY c.label_id, c.vendor
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

    def list_history_for_label(self, label_id: str) -> list[dict[str, Any]]:
        """Per-label enrichment history.

        Returns a list of cells joined with their parent run, ordered by run
        created_at DESC. Each cell row carries enough context for the admin
        to inspect what was tried, what came back, and what failed:
        run_id, run_status, run_created_at, prompt_slug, prompt_version,
        vendor, model, status, latency_ms, cost_usd, error_message, parsed.
        """
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
            FROM clouder_label_enrichment_cells c
            JOIN clouder_label_enrichment_runs r ON r.id = c.run_id
            WHERE c.label_id = :label_id
            ORDER BY r.created_at DESC, c.vendor ASC
            """,
            {"label_id": label_id},
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

    def derive_style_for_label(self, label_id: str) -> str | None:
        """Most common style across the label's tracks. None if no tracks."""
        rows = self._data_api.execute(
            """
            SELECT s.name AS style_name, COUNT(*) AS cnt
            FROM clouder_styles s
            JOIN clouder_tracks t ON t.style_id = s.id
            JOIN clouder_albums a ON a.id = t.album_id
            WHERE a.label_id = :label_id
            GROUP BY s.name
            ORDER BY cnt DESC
            LIMIT 1
            """,
            {"label_id": label_id},
        )
        if not rows:
            return None
        return rows[0].get("style_name")

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
                "vendors": list(spec.vendors),
                "models": dict(spec.models),
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
        if not rows:
            return None
        row = dict(rows[0])
        # Data API returns JSONB columns as JSON-encoded strings; tests
        # pass Python objects directly — handle both shapes.
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
                "parsed": parsed_payload,
                "citations": list(response.citations),
                "usage": dict(response.usage),
                "latency_ms": response.latency_ms,
                "error": {"message": response.error} if response.error is not None else None,
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

    # ── label_info ──────────────────────────────────────────────────
    def upsert_label_info(
        self,
        *,
        label_id: str,
        last_run_id: str,
        prompt_slug: str,
        prompt_version: str,
        merged: "LabelInfo",
        provenance: Mapping[str, Any],
    ) -> None:
        ts = self._now()
        # mode="json" coerces enums (ai_content, activity) to their wire str
        # values. Without it, Python 3.12's str(enum_member) returns
        # "ClassName.MEMBER" (PEP 663), which leaks into denormalized columns
        # via data_api._to_field's generic str() fallback.
        payload = merged.model_dump(mode="json")
        self._data_api.execute(
            """
            INSERT INTO clouder_label_info (
                label_id, last_run_id, prompt_slug, prompt_version,
                merged, provenance,
                ai_content, ai_confidence, status, primary_styles,
                tagline, country, founded_year, activity, last_release_date,
                updated_at
            ) VALUES (
                :label_id, :last_run_id, :prompt_slug, :prompt_version,
                :merged, :provenance,
                :ai_content, :ai_confidence, :status, CAST(:primary_styles AS text[]),
                :tagline, :country, :founded_year, :activity, CAST(:last_release_date AS date),
                :updated_at
            )
            ON CONFLICT (label_id) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id,
                prompt_slug = EXCLUDED.prompt_slug,
                prompt_version = EXCLUDED.prompt_version,
                merged = EXCLUDED.merged,
                provenance = EXCLUDED.provenance,
                ai_content = EXCLUDED.ai_content,
                ai_confidence = EXCLUDED.ai_confidence,
                status = EXCLUDED.status,
                primary_styles = EXCLUDED.primary_styles,
                tagline = EXCLUDED.tagline,
                country = EXCLUDED.country,
                founded_year = EXCLUDED.founded_year,
                activity = EXCLUDED.activity,
                last_release_date = EXCLUDED.last_release_date,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "label_id": label_id,
                "last_run_id": last_run_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "merged": payload,
                "provenance": dict(provenance),
                "ai_content": payload.get("ai_content", "unknown"),
                "ai_confidence": Decimal(str(round(payload.get("confidence", 0.0), 2))),
                "status": payload.get("status", "unknown"),
                "primary_styles": _pg_text_array(payload.get("primary_styles") or []),
                "tagline": payload.get("tagline"),
                "country": payload.get("country"),
                "founded_year": payload.get("founded_year"),
                "activity": payload.get("activity"),
                "last_release_date": payload.get("last_release_date"),
                "updated_at": ts,
            },
        )

    def project_ai_suspected(
        self,
        label_id: str,
        merged: "LabelInfo",
        threshold: float,
    ) -> None:
        """Mirror merged.ai_content into clouder_labels.is_ai_suspected when confidence >= threshold."""
        from .schemas import AIContentStatus  # local — avoid cycle at module load

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
            UPDATE clouder_labels
            SET is_ai_suspected = :value, updated_at = :ts
            WHERE id = :id
            """,
            {"value": value, "ts": self._now(), "id": label_id},
        )

    def get_label_info(self, label_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT
                li.label_id, cl.name AS label_name, li.last_run_id,
                li.prompt_slug, li.prompt_version,
                li.merged, li.provenance,
                li.ai_content, li.ai_confidence, li.status, li.primary_styles,
                li.tagline, li.country, li.founded_year, li.activity,
                li.last_release_date, li.updated_at
            FROM clouder_label_info li
            JOIN clouder_labels cl ON cl.id = li.label_id
            WHERE li.label_id = :id
            LIMIT 1
            """,
            {"id": label_id},
        )
        if not rows:
            return None
        row = dict(rows[0])
        # Data API returns JSONB columns as JSON-encoded strings; tests
        # pass Python objects directly — handle both shapes.
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

    # ── user label preferences ──────────────────────────────────────
    def upsert_user_label_pref(
        self,
        *,
        user_id: str,
        label_id: str,
        status: str,
    ) -> None:
        if status not in ("liked", "disliked"):
            raise ValueError(f"status must be 'liked' or 'disliked', got {status!r}")
        self._data_api.execute(
            """
            INSERT INTO clouder_user_label_prefs (user_id, label_id, status, updated_at)
            VALUES (:user_id, :label_id, :status, :ts)
            ON CONFLICT (user_id, label_id) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """,
            {
                "user_id": user_id,
                "label_id": label_id,
                "status": status,
                "ts": self._now(),
            },
        )

    def delete_user_label_pref(self, *, user_id: str, label_id: str) -> None:
        self._data_api.execute(
            "DELETE FROM clouder_user_label_prefs WHERE user_id = :user_id AND label_id = :label_id",
            {"user_id": user_id, "label_id": label_id},
        )

    def list_user_label_prefs(
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
            SELECT lbl.id, lbl.name, p.status
            FROM clouder_user_label_prefs p
            JOIN clouder_labels lbl ON lbl.id = p.label_id
            WHERE p.user_id = :user_id AND p.status = :status
            ORDER BY p.updated_at DESC, lbl.id DESC
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
            FROM clouder_user_label_prefs p
            WHERE p.user_id = :user_id AND p.status = :status
            """,
            {"user_id": user_id, "status": status},
        )
        total = int(total_rows[0]["c"]) if total_rows else 0
        return items, total

    def get_label_info_for_user(self, label_id: str) -> dict[str, Any] | None:
        """Return decoded merged LabelInfo for a user-facing detail page.

        Returns the decoded `merged` JSONB blob (the full LabelInfo schema:
        label_name, country, tagline, summary, notable_artists, URL channels,
        primary/secondary_styles, ai_content, ai_reasoning, etc.) with
        admin-only fields stripped. Returns None when no clouder_label_info
        row exists for the label.

        Note: clouder_label_info.status holds the LabelInfo schema's
        operational status ("active"/"inactive"/"unknown"), not the
        enrichment job state, so the mere existence of a row signals a
        completed run.
        """
        rows = self._data_api.execute(
            """
            SELECT li.merged
            FROM clouder_label_info li
            WHERE li.label_id = :id
            LIMIT 1
            """,
            {"id": label_id},
        )
        if not rows:
            return None
        merged = rows[0].get("merged")
        if isinstance(merged, str):
            merged = json.loads(merged)
        if not isinstance(merged, dict):
            return None
        return {k: v for k, v in merged.items() if k not in _USER_FACING_FORBIDDEN}

    def increment_run_counters(
        self,
        *,
        run_id: str,
        ok_delta: int,
        error_delta: int,
        cost_delta: float,
    ) -> None:
        """Atomically bump counters and flip to 'completed' once cells_total is reached.

        Single UPDATE so the (cells_ok + cells_error) check and the status
        flip happen inside one transaction — race-safe across concurrent
        worker invocations.
        """
        ts = self._now()
        self._data_api.execute(
            """
            UPDATE clouder_label_enrichment_runs
            SET
                cells_ok = cells_ok + :ok,
                cells_error = cells_error + :err,
                cost_usd = cost_usd + :cost,
                status = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN 'completed'
                    ELSE status
                END,
                finished_at = CASE WHEN cells_ok + cells_error + :ok + :err >= cells_total
                    THEN :ts
                    ELSE finished_at
                END
            WHERE id = :id
            """,
            {
                "id": run_id,
                "ok": ok_delta,
                "err": error_delta,
                "cost": Decimal(str(round(cost_delta, 4))),
                "ts": ts,
            },
        )

"""Auto-ingest settings, run lease, attempts and planning state (docs/data/auto-ingest.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping

# A RAW_SAVED run younger than this is still being canonicalized: do not re-ingest it.
PENDING_WINDOW = timedelta(hours=6)

Pair = tuple[int, int, int]  # (Beatport style id, week_year, week_number)


@dataclass(frozen=True)
class PlanningState:
    styles: tuple[int, ...]
    loaded: frozenset[Pair]
    stuck: frozenset[Pair]


def _json(value: Any) -> Any:
    # The Data API returns jsonb as text; the test driver returns Python objects.
    return json.loads(value) if isinstance(value, str) else value


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class AutoIngestRepository:
    def __init__(self, data_api: Any) -> None:
        self._data_api = data_api

    def get_settings(self) -> dict[str, Any]:
        (row,) = self._data_api.execute(
            """
            SELECT enabled, mode, fixed_times, runs_per_day, timezone, periods_per_run,
                   backfill_floor, planned_runs, last_run, updated_at
            FROM auto_ingest_settings WHERE id = 1
            """
        )
        return {
            "enabled": bool(row["enabled"]),
            "mode": row["mode"],
            "fixed_times": list(_json(row["fixed_times"]) or []),
            "runs_per_day": int(row["runs_per_day"]),
            "timezone": row["timezone"],
            "periods_per_run": int(row["periods_per_run"]),
            "backfill_floor": _iso(row["backfill_floor"])[:10],
            "planned_runs": list(_json(row["planned_runs"]) or []),
            "last_run": _json(row["last_run"]),
            "updated_at": _iso(row["updated_at"]),
        }

    def save_settings(
        self, values: Mapping[str, Any], *, user_id: str | None, now: datetime
    ) -> dict[str, Any]:
        floor = values["backfill_floor"]
        self._data_api.execute(
            """
            UPDATE auto_ingest_settings
            SET enabled = :enabled, mode = :mode,
                fixed_times = CAST(:fixed_times AS JSONB), runs_per_day = :runs_per_day,
                timezone = :timezone, periods_per_run = :periods_per_run,
                backfill_floor = CAST(:backfill_floor AS DATE),
                updated_at = :now, updated_by_user_id = :user_id
            WHERE id = 1
            """,
            {
                "enabled": bool(values["enabled"]),
                "mode": values["mode"],
                "fixed_times": json.dumps(list(values["fixed_times"])),
                "runs_per_day": int(values["runs_per_day"]),
                "timezone": values["timezone"],
                "periods_per_run": int(values["periods_per_run"]),
                "backfill_floor": floor.isoformat() if isinstance(floor, date) else str(floor),
                "now": now,
                "user_id": user_id,
            },
        )
        return self.get_settings()

    def set_plan(self, planned: list[str], now: datetime) -> None:
        del now  # planned times carry their own timestamps
        self._data_api.execute(
            "UPDATE auto_ingest_settings SET planned_runs = CAST(:p AS JSONB) WHERE id = 1",
            {"p": json.dumps(planned)},
        )

    def set_last_run(self, summary: Mapping[str, Any]) -> None:
        self._data_api.execute(
            "UPDATE auto_ingest_settings SET last_run = CAST(:s AS JSONB) WHERE id = 1",
            {"s": json.dumps(summary, default=str)},
        )

    def acquire_lease(self, now: datetime, minutes: int = 15) -> bool:
        """One run at a time (the account's Lambda quota rules out reserved concurrency)."""
        rows = self._data_api.execute(
            """
            UPDATE auto_ingest_settings SET running_until = :until
            WHERE id = 1 AND (running_until IS NULL OR running_until < :now)
            RETURNING id
            """,
            {"until": now + timedelta(minutes=minutes), "now": now},
        )
        return bool(rows)

    def release_lease(self) -> None:
        self._data_api.execute("UPDATE auto_ingest_settings SET running_until = NULL WHERE id = 1")

    def record_attempt(
        self, style_id: int, week_year: int, week_number: int, *,
        ok: bool, run_id: str | None, error: str | None, at: datetime,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO auto_ingest_attempts
                (style_id, week_year, week_number, attempted_at, ok, run_id, error)
            VALUES (:style_id, :week_year, :week_number, :at, :ok, :run_id, :error)
            """,
            {"style_id": style_id, "week_year": week_year, "week_number": week_number,
             "at": at, "ok": ok, "run_id": run_id, "error": error},
        )

    def stuck_pairs(self) -> list[dict[str, Any]]:
        """Pairs whose last three attempts all failed."""
        rows = self._data_api.execute(
            """
            WITH ranked AS (
                SELECT style_id, week_year, week_number, ok, error, attempted_at,
                       row_number() OVER (
                           PARTITION BY style_id, week_year, week_number
                           ORDER BY attempted_at DESC
                       ) AS rn
                FROM auto_ingest_attempts
            )
            SELECT style_id, week_year, week_number,
                   max(attempted_at) AS last_attempt_at,
                   max(CASE WHEN rn = 1 THEN error END) AS last_error
            FROM ranked
            WHERE rn <= 3
            GROUP BY style_id, week_year, week_number
            HAVING count(*) = 3 AND bool_and(NOT ok)
            ORDER BY week_year DESC, week_number DESC, style_id
            """
        )
        return [
            {"style_id": int(r["style_id"]), "week_year": int(r["week_year"]),
             "week_number": int(r["week_number"]), "last_attempt_at": _iso(r["last_attempt_at"]),
             "last_error": r["last_error"]}
            for r in rows
        ]

    def planning_state(self, now: datetime) -> PlanningState:
        styles = self._data_api.execute(
            """
            SELECT DISTINCT CAST(im.external_id AS INTEGER) AS style_id
            FROM clouder_styles cs
            JOIN identity_map im
              ON im.source = 'beatport' AND im.entity_type = 'style'
             AND im.clouder_entity_type = 'style' AND im.clouder_id = cs.id
            WHERE NOT COALESCE(cs.is_hidden, false)
            ORDER BY 1
            """
        )
        loaded = self._data_api.execute(
            """
            SELECT DISTINCT style_id, week_year, week_number
            FROM ingest_runs
            WHERE source = 'beatport'
              AND week_year IS NOT NULL AND week_number IS NOT NULL
              AND NOT COALESCE(is_custom_range, false)
              AND (status = 'COMPLETED' OR (status = 'RAW_SAVED' AND started_at > :pending_since))
            """,
            {"pending_since": now - PENDING_WINDOW},
        )
        return PlanningState(
            styles=tuple(int(r["style_id"]) for r in styles),
            loaded=frozenset(
                (int(r["style_id"]), int(r["week_year"]), int(r["week_number"])) for r in loaded
            ),
            stuck=frozenset(
                (p["style_id"], p["week_year"], p["week_number"]) for p in self.stuck_pairs()
            ),
        )

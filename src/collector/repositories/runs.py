"""Ingest runs: create, finish, read, list."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

from ..models import RunStatus
from ._base import RepositoryBase
from .commands import CreateIngestRunCmd


class IngestRunsMixin(RepositoryBase):
    def create_ingest_run(self, cmd: CreateIngestRunCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO ingest_runs (
                run_id, source, style_id,
                iso_year, iso_week,
                week_year, week_number,
                period_start, period_end, is_custom_range,
                raw_s3_key,
                status, item_count, processed_count, started_at, meta
            ) VALUES (
                :run_id, :source, :style_id,
                :iso_year, :iso_week,
                :week_year, :week_number,
                :period_start, :period_end, :is_custom_range,
                :raw_s3_key,
                :status, :item_count, 0, :started_at, :meta
            )
            ON CONFLICT (run_id) DO UPDATE SET
                source = EXCLUDED.source,
                style_id = EXCLUDED.style_id,
                iso_year = EXCLUDED.iso_year,
                iso_week = EXCLUDED.iso_week,
                week_year = EXCLUDED.week_year,
                week_number = EXCLUDED.week_number,
                period_start = EXCLUDED.period_start,
                period_end = EXCLUDED.period_end,
                is_custom_range = EXCLUDED.is_custom_range,
                raw_s3_key = EXCLUDED.raw_s3_key,
                status = EXCLUDED.status,
                item_count = EXCLUDED.item_count,
                meta = EXCLUDED.meta,
                error_code = NULL,
                error_message = NULL,
                finished_at = NULL
            """,
            {
                "run_id": cmd.run_id,
                "source": cmd.source,
                "style_id": cmd.style_id,
                "iso_year": cmd.iso_year,
                "iso_week": cmd.iso_week,
                "week_year": cmd.week_year,
                "week_number": cmd.week_number,
                "period_start": cmd.period_start,
                "period_end": cmd.period_end,
                "is_custom_range": cmd.is_custom_range,
                "raw_s3_key": cmd.raw_s3_key,
                "status": cmd.status.value,
                "item_count": cmd.item_count,
                "started_at": cmd.started_at,
                "meta": dict(cmd.meta),
            },
        )

    def set_run_completed(self, run_id: str, processed_count: int, finished_at: datetime) -> None:
        self._data_api.execute(
            """
            UPDATE ingest_runs
            SET status = :status,
                processed_count = :processed_count,
                finished_at = :finished_at,
                error_code = NULL,
                error_message = NULL
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "status": RunStatus.COMPLETED.value,
                "processed_count": processed_count,
                "finished_at": finished_at,
            },
        )

    def set_run_failed(
        self,
        run_id: str,
        error_code: str,
        error_message: str,
        finished_at: datetime,
        phase: str | None = None,
    ) -> None:
        if phase:
            prefix = f"[phase={phase}] "
            truncated = error_message[: 2000 - len(prefix)]
            final_error_message = f"{prefix}{truncated}"
        else:
            final_error_message = error_message[:2000]
        self._data_api.execute(
            """
            UPDATE ingest_runs
            SET status = :status,
                finished_at = :finished_at,
                error_code = :error_code,
                error_message = :error_message
            WHERE run_id = :run_id
            """,
            {
                "run_id": run_id,
                "status": RunStatus.FAILED.value,
                "finished_at": finished_at,
                "error_code": error_code,
                "error_message": final_error_message,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            """
            SELECT run_id, status, processed_count, item_count, error_code, error_message,
                   started_at, finished_at
            FROM ingest_runs
            WHERE run_id = :run_id
            """,
            {"run_id": run_id},
        )
        return rows[0] if rows else None

    def list_replayable_runs(
        self,
        *,
        style_ids: Sequence[int] | None = None,
        since: date | None = None,
        until: date | None = None,
    ) -> list[dict[str, Any]]:
        """The run behind each raw object — the latest one written to its key.

        Re-ingesting a week overwrites its raw object, so older runs of the same
        key no longer have data of their own to replay. Filters apply to the
        latest run, by style and by the period's end date. Ordered by observation
        time: replaying in that order converges in one pass, also over rows stamped
        with processing time before event time existed.
        """
        filters: list[str] = []
        params: dict[str, Any] = {}
        if style_ids:
            filters.append(
                "style_id IN (" + ", ".join(f":style{i}" for i in range(len(style_ids))) + ")"
            )
            params.update({f"style{i}": int(s) for i, s in enumerate(style_ids)})
        if since:
            filters.append("period_end >= :since")
            params["since"] = since
        if until:
            filters.append("period_end <= :until")
            params["until"] = until
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        return self._data_api.execute(
            f"""
            SELECT run_id, raw_s3_key, started_at, status, style_id, period_end
            FROM (
                SELECT DISTINCT ON (raw_s3_key)
                       run_id, raw_s3_key, started_at, status, style_id, period_end
                FROM ingest_runs
                WHERE source = 'beatport' AND raw_s3_key IS NOT NULL
                ORDER BY raw_s3_key, started_at DESC
            ) latest
            {where}
            ORDER BY started_at, run_id
            """,
            params,
        )

    def list_runs_for_cell(
        self, style_id: int, week_year: int, week_number: int
    ) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT
                run_id, status, started_at, finished_at,
                item_count, processed_count,
                error_code, error_message,
                is_custom_range, period_start, period_end
            FROM ingest_runs
            WHERE style_id = :style_id
              AND week_year = :week_year
              AND week_number = :week_number
            ORDER BY started_at DESC
            """,
            {
                "style_id": style_id,
                "week_year": week_year,
                "week_number": week_number,
            },
        )

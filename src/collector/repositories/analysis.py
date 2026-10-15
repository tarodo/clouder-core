"""Audio analysis state: leases for the external analyzer, its results, status, requeue."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ._base import RepositoryBase, as_utc_datetime

SERVICE = "analyzer"

# The badge in the track lists (`t` = clouder_tracks); served by ix_track_analyses_ai_detected.
AI_DETECTED_SQL = """EXISTS (
    SELECT 1 FROM track_analyses ta
    WHERE ta.track_id = t.id AND ta.analyzer = 'ai_detect' AND ta.status = 'ok'
      AND (ta.result->>'ai_detected')::boolean) AS ai_detected"""
LEASE_SECONDS = 1800

# A row blocks a (track, analyzer) pair unless it is a lease that ran out.
_HELD = "NOT (a.status = 'leased' AND a.leased_until < :now)"

_COUNTED = ("leased", "ok", "failed", "unusable_source")

# Arrays travel as comma-joined text: analyzer names never hold a comma
# (^[a-z][a-z0-9_]+$) and the Data API has no clean text[] round trip.
_WANTED = "SELECT unnest(string_to_array(:analyzers, ',')) AS analyzer"


class AnalysisMixin(RepositoryBase):
    def claim_analysis(
        self,
        *,
        limit: int,
        analyzers: list[str],
        lease_id: str,
        now: datetime,
        lease_seconds: int = LEASE_SECONDS,
    ) -> list[dict[str, Any]]:
        """Lease up to *limit* tracks with a YT Music match that miss any of
        *analyzers*, newest first. One statement: the ON CONFLICT guard lets only
        an expired lease be taken over, so two claimers never share a pair."""
        names = ",".join(analyzers)
        rows = self._data_api.execute(
            f"""
            WITH wanted AS ({_WANTED}),
            picked AS MATERIALIZED (
                SELECT t.id, t.length_ms, t.created_at, v.vendor_track_id AS video_id
                FROM vendor_track_map v
                JOIN clouder_tracks t ON t.id = v.clouder_track_id
                WHERE v.vendor = 'ytmusic'
                  AND EXISTS (
                      SELECT 1 FROM wanted w WHERE NOT EXISTS (
                          SELECT 1 FROM track_analyses a
                          WHERE a.track_id = t.id AND a.analyzer = w.analyzer AND {_HELD}))
                ORDER BY t.created_at DESC, t.id
                LIMIT :limit
            ),
            leased AS (
                INSERT INTO track_analyses
                    (track_id, analyzer, status, lease_id, leased_until, created_at, updated_at)
                SELECT p.id, w.analyzer, 'leased', CAST(:lease_id AS uuid), :leased_until, :now, :now
                FROM picked p CROSS JOIN wanted w
                WHERE NOT EXISTS (
                    SELECT 1 FROM track_analyses a
                    WHERE a.track_id = p.id AND a.analyzer = w.analyzer AND {_HELD})
                ON CONFLICT (track_id, analyzer) DO UPDATE
                    SET lease_id = EXCLUDED.lease_id,
                        leased_until = EXCLUDED.leased_until,
                        updated_at = EXCLUDED.updated_at
                    WHERE track_analyses.status = 'leased'
                      AND track_analyses.leased_until < :now
                RETURNING track_id, analyzer
            )
            SELECT p.id AS track_id, p.video_id, p.length_ms,
                   string_agg(l.analyzer, ',' ORDER BY l.analyzer) AS analyzers
            FROM leased l JOIN picked p ON p.id = l.track_id
            GROUP BY p.id, p.video_id, p.length_ms, p.created_at
            ORDER BY p.created_at DESC, p.id
            """,
            {
                "analyzers": names,
                "limit": limit,
                "lease_id": lease_id,
                "leased_until": now + timedelta(seconds=lease_seconds),
                "now": now,
            },
        )
        self._data_api.execute(
            """
            INSERT INTO analysis_service_state (service, last_claim_at, claim_analyzers)
            VALUES (:service, :now, string_to_array(:analyzers, ','))
            ON CONFLICT (service) DO UPDATE
                SET last_claim_at = EXCLUDED.last_claim_at,
                    claim_analyzers = EXCLUDED.claim_analyzers
            """,
            {"service": SERVICE, "now": now, "analyzers": names},
        )
        return [
            {
                "track_id": r["track_id"],
                "video_id": r["video_id"],
                "length_ms": r["length_ms"],
                "analyzers": r["analyzers"].split(","),
            }
            for r in rows
        ]

    def record_analysis_results(
        self, *, lease_id: str, items: list[dict[str, Any]], now: datetime
    ) -> list[dict[str, str]]:
        """Store results still held under *lease_id*; return the rest as lease_lost."""
        rows = self._data_api.execute(
            """
            UPDATE track_analyses a
            SET status = x.status, version = x.version, result = x.result, error = x.error,
                audio_sha256 = x.audio_sha256, video_id = x.video_id, analyzed_at = :now,
                lease_id = NULL, leased_until = NULL, updated_at = :now
            FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS x(
                track_id text, analyzer text, version text, status text, result jsonb,
                error text, audio_sha256 text, video_id text)
            WHERE a.track_id = x.track_id AND a.analyzer = x.analyzer
              AND a.status = 'leased' AND a.lease_id = CAST(:lease_id AS uuid)
            RETURNING a.track_id, a.analyzer
            """,
            {"items": items, "lease_id": lease_id, "now": now},
        )
        accepted = {(r["track_id"], r["analyzer"]) for r in rows}
        if accepted:
            self._data_api.execute(
                """
                INSERT INTO analysis_service_state (service, last_result_at) VALUES (:service, :now)
                ON CONFLICT (service) DO UPDATE SET last_result_at = EXCLUDED.last_result_at
                """,
                {"service": SERVICE, "now": now},
            )
        return [
            {"track_id": i["track_id"], "analyzer": i["analyzer"], "reason": "lease_lost"}
            for i in items
            if (i["track_id"], i["analyzer"]) not in accepted
        ]

    def analysis_status(self, *, now: datetime) -> dict[str, Any]:
        state = self._data_api.execute(
            """
            SELECT last_claim_at, last_result_at,
                   array_to_string(claim_analyzers, ',') AS claim_analyzers
            FROM analysis_service_state WHERE service = :service
            """,
            {"service": SERVICE},
        )
        counts = self._data_api.execute(
            """
            SELECT analyzer,
                   CASE WHEN status = 'leased' AND leased_until < :now THEN 'expired'
                        ELSE status END AS status,
                   count(*) AS n,
                   count(*) FILTER (WHERE status = 'ok' AND analyzer = 'ai_detect'
                                    AND (result->>'ai_detected')::boolean) AS ai_detected
            FROM track_analyses GROUP BY 1, 2
            """,
            {"now": now},
        )
        names = {r["analyzer"] for r in counts}
        if state and state[0]["claim_analyzers"]:
            names |= set(state[0]["claim_analyzers"].split(","))
        due = {}
        if names:
            due_rows = self._data_api.execute(
                f"""
                SELECT w.analyzer, count(*) AS n
                FROM ({_WANTED}) w
                JOIN vendor_track_map v ON v.vendor = 'ytmusic'
                WHERE NOT EXISTS (
                    SELECT 1 FROM track_analyses a
                    WHERE a.track_id = v.clouder_track_id AND a.analyzer = w.analyzer AND {_HELD})
                GROUP BY w.analyzer
                """,
                {"analyzers": ",".join(sorted(names)), "now": now},
            )
            due = {r["analyzer"]: int(r["n"]) for r in due_rows}
        analyzers = []
        for name in sorted(names):
            by = {r["status"]: r for r in counts if r["analyzer"] == name}
            n = {s: int(by[s]["n"]) if s in by else 0 for s in _COUNTED}
            analyzers.append(
                {
                    "name": name,
                    "due": due.get(name, 0),
                    **n,
                    "ai_detected": int(by["ok"]["ai_detected"]) if "ok" in by else 0,
                }
            )
        return {
            "last_claim_at": as_utc_datetime(state[0]["last_claim_at"]) if state else None,
            "last_result_at": as_utc_datetime(state[0]["last_result_at"]) if state else None,
            "analyzers": analyzers,
        }

    def requeue_analysis(
        self,
        *,
        analyzer: str,
        scope: str,
        days: int | None,
        include_failed: bool,
        now: datetime,
    ) -> int:
        """Delete finished rows in *scope* so the next claim hands the tracks out
        again. Live leases are never touched; failed only on request."""
        statuses = ["ok", "unusable_source"] + (["failed"] if include_failed else [])
        where = {
            "all": "",
            "categories": """AND track_id IN (
                SELECT ct.track_id FROM category_tracks ct
                JOIN categories c ON c.id = ct.category_id WHERE c.deleted_at IS NULL)""",
            "recent": """AND track_id IN (
                SELECT id FROM clouder_tracks WHERE created_at >= :cutoff)""",
        }[scope]
        params: dict[str, Any] = {"analyzer": analyzer, "statuses": ",".join(statuses)}
        if scope == "recent":
            # Python-side cutoff: the Data API binds ints as bigint and Postgres has
            # no make_interval(days => bigint).
            params["cutoff"] = now - timedelta(days=days or 0)
        rows = self._data_api.execute(
            f"""
            WITH deleted AS (
                DELETE FROM track_analyses
                WHERE analyzer = :analyzer
                  AND status = ANY (string_to_array(:statuses, ','))
                  {where}
                RETURNING 1
            )
            SELECT count(*) AS n FROM deleted
            """,
            params,
        )
        # One count row, not one row per deletion: a requeue of tens of thousands
        # of rows would overrun the Data API's 1 MiB response cap.
        return int(rows[0]["n"])

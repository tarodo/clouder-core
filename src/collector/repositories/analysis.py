"""Audio analysis state: leases for the external analyzer, its results, status, requeue."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ..saturday_week import first_saturday, weeks_in_year
from ..schemas import AI_ANALYZERS
from ._base import RepositoryBase, as_utc_datetime

SERVICE = "analyzer"

# The badge level comes from lofcz/ai-music-detector and Deezer's detector:
# both flag -> "high", only lofcz -> "medium", only Deezer -> "low", else null.
# ai_detect (ArtifactNet) rows stay as a second opinion and drive nothing.
PAIR_ANALYZERS = ("ai_lofcz", "ai_deezer")

# The level in the track lists (`t` = clouder_tracks); served by
# ix_track_analyses_ai_flag. Each EXISTS runs once per row.
_LOFCZ, _DEEZER = (
    f"""EXISTS (
    SELECT 1 FROM track_analyses ta
    WHERE ta.track_id = t.id AND ta.analyzer = '{a}' AND ta.status = 'ok'
      AND (ta.result->>'ai_detected')::boolean)"""
    for a in PAIR_ANALYZERS
)
AI_VERDICT_SQL = f"""CASE WHEN {_LOFCZ} THEN CASE WHEN {_DEEZER} THEN 'high' ELSE 'medium' END
    WHEN {_DEEZER} THEN 'low' END AS ai_verdict"""
# Any badge level: the owner's rule sends such a track to DISCARD.
AI_FLAGGED_SQL = f"({_LOFCZ} OR {_DEEZER})"

# AI reputation (spec 2026-10-29): a label / artist counts its tracks, the ones the pair checked (an ok
# row) and the flagged ones; the generated ai_level reads the share. Migration 46 backfills with the
# same counting; a results POST recounts the labels and artists of its tracks ({ids}: placeholders).
_PER_TRACK = """
    CROSS JOIN LATERAL (
        SELECT bool_or(ta.status = 'ok') AS checked,
               bool_or(ta.status = 'ok' AND (ta.result->>'ai_detected')::boolean) AS ai
        FROM track_analyses ta
        WHERE ta.track_id = t.id AND ta.analyzer IN ('ai_lofcz', 'ai_deezer')
    ) x"""
_RECOUNT_LABELS = f"""
UPDATE clouder_labels l
SET ai_total = c.total, ai_checked = c.checked, ai_tracks = c.ai
FROM (
    SELECT a.label_id, count(*) AS total, count(*) FILTER (WHERE x.checked) AS checked,
           count(*) FILTER (WHERE x.ai) AS ai
    FROM clouder_albums a
    JOIN clouder_tracks t ON t.album_id = a.id
    {_PER_TRACK}
    WHERE a.label_id IN (
        SELECT a2.label_id FROM clouder_tracks t2 JOIN clouder_albums a2 ON a2.id = t2.album_id
        WHERE t2.id IN ({{ids}}))
    GROUP BY a.label_id
) c
WHERE l.id = c.label_id
"""
_RECOUNT_ARTISTS = f"""
UPDATE clouder_artists ar
SET ai_total = c.total, ai_checked = c.checked, ai_tracks = c.ai
FROM (
    SELECT p.artist_id, count(*) AS total, count(*) FILTER (WHERE x.checked) AS checked,
           count(*) FILTER (WHERE x.ai) AS ai
    FROM (SELECT DISTINCT artist_id, track_id FROM clouder_track_artists
          WHERE artist_id IN (SELECT artist_id FROM clouder_track_artists WHERE track_id IN ({{ids}}))) p
    JOIN clouder_tracks t ON t.id = p.track_id
    {_PER_TRACK}
    GROUP BY p.artist_id
) c
WHERE ar.id = c.artist_id
"""


def parse_ai_rep(value: Any) -> dict[str, int] | None:
    """An ai_rep_sql column as returned by the Data API (JSON text) or psycopg (already decoded)."""
    if value is None:
        return None
    return json.loads(value) if isinstance(value, str) else value


def ai_rep_sql(alias: str) -> str:
    """The AI reputation of a clouder_labels / clouder_artists row as a JSON object, NULL without a level."""
    return (
        f"CASE WHEN {alias}.ai_level IS NULL THEN NULL ELSE json_build_object("
        f"'level', {alias}.ai_level, 'ai', {alias}.ai_tracks, 'checked', {alias}.ai_checked, "
        f"'total', {alias}.ai_total) END"
    )


LEASE_SECONDS = 1800

# The owner's rule (2026-10-23): an AI-flagged track never stays in play. In every open block that keeps
# ai_to_discard (the default; the user may untick it at creation) it moves to DISCARD from whatever bucket
# holds it (STAGING too); kept in a category, it leaves the category for the DISCARD bucket of the block it
# came from, unless that block opted out (nowhere when it was added by hand). Finalized blocks stay as they
# were. One statement: the CTEs see one snapshot, so the moves cannot chase each other.
_DISCARD_AI = f"""
WITH flagged AS (
    SELECT t.id FROM clouder_tracks t WHERE t.id IN ({{ids}}) AND {AI_FLAGGED_SQL}
), open_rows AS (
    SELECT x.triage_bucket_id, x.track_id, d.id AS discard_id
    FROM triage_bucket_tracks x
    JOIN flagged f ON f.id = x.track_id
    JOIN triage_buckets b ON b.id = x.triage_bucket_id AND b.bucket_type <> 'DISCARD'
    JOIN triage_blocks tb ON tb.id = b.triage_block_id
     AND tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL AND tb.ai_to_discard
    JOIN triage_buckets d ON d.triage_block_id = tb.id AND d.bucket_type = 'DISCARD'
), unbucketed AS (
    DELETE FROM triage_bucket_tracks x USING open_rows o
    WHERE x.triage_bucket_id = o.triage_bucket_id AND x.track_id = o.track_id
    RETURNING o.discard_id, x.track_id
), uncategorized AS (
    DELETE FROM category_tracks ct USING flagged f
    WHERE ct.track_id = f.id
      AND NOT EXISTS (
          SELECT 1 FROM triage_blocks sb
          WHERE sb.id = ct.source_triage_block_id AND NOT sb.ai_to_discard)
    RETURNING ct.track_id, ct.source_triage_block_id
), discarded AS (
    INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at)
    SELECT s.discard_id, s.track_id, :now FROM (
        SELECT discard_id, track_id FROM unbucketed
        UNION
        SELECT d.id, u.track_id FROM uncategorized u
        JOIN triage_buckets d
          ON d.triage_block_id = u.source_triage_block_id AND d.bucket_type = 'DISCARD'
    ) s
    ON CONFLICT (triage_bucket_id, track_id) DO NOTHING
    RETURNING 1
)
SELECT (SELECT count(*) FROM unbucketed) AS moved,
       (SELECT count(*) FROM uncategorized) AS uncategorized,
       (SELECT string_agg(DISTINCT track_id, ',') FROM uncategorized) AS uncategorized_ids
"""

# Tags live with category membership (see TagsRepository.cleanup_orphaned_track_tags): a track that left
# every alive category of a user loses that user's tags.
_UNTAG = """
DELETE FROM track_tags tt
WHERE tt.track_id IN ({ids})
  AND NOT EXISTS (
      SELECT 1 FROM category_tracks ct JOIN categories c ON c.id = ct.category_id
      WHERE ct.track_id = tt.track_id AND c.user_id = tt.user_id AND c.deleted_at IS NULL)
RETURNING 1
"""

# A row blocks a (track, analyzer) pair unless it is a lease that ran out.
_HELD = "NOT (a.status = 'leased' AND a.leased_until < :now)"
# An ok row of track_analyses `a` that flags AI.
_FLAG = "a.status = 'ok' AND coalesce((a.result->>'ai_detected')::boolean, false)"
# A track (`t`) misses one of the wanted analyzers (`wanted` CTE).
_MISSING = f"""EXISTS (
    SELECT 1 FROM wanted w WHERE NOT EXISTS (
        SELECT 1 FROM track_analyses a
        WHERE a.track_id = t.id AND a.analyzer = w.analyzer AND {_HELD}))"""

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
        *analyzers*: first the tracks waiting in an open triage block (any bucket
        but DISCARD, any user: the owner's target number one), then the rest of
        the catalog; newest release first within each (the order the YouTube
        sweep finds them in). One statement: the ON CONFLICT guard lets only an
        expired lease be taken over, so two claimers never share a pair."""
        names = ",".join(analyzers)
        rows = self._data_api.execute(
            f"""
            WITH wanted AS ({_WANTED}),
            open_tracks AS (
                SELECT DISTINCT x.track_id
                FROM triage_bucket_tracks x
                JOIN triage_buckets b ON b.id = x.triage_bucket_id AND b.bucket_type <> 'DISCARD'
                JOIN triage_blocks tb ON tb.id = b.triage_block_id
                WHERE tb.status = 'IN_PROGRESS' AND tb.deleted_at IS NULL
            ),
            candidates AS (
                (SELECT t.id, t.length_ms, t.created_at, t.publish_date,
                        v.vendor_track_id AS video_id, 0 AS prio
                 FROM open_tracks o
                 JOIN clouder_tracks t ON t.id = o.track_id
                 JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
                 WHERE {_MISSING}
                 ORDER BY t.publish_date DESC NULLS LAST, t.created_at DESC, t.id
                 LIMIT :limit)
                UNION ALL
                (SELECT t.id, t.length_ms, t.created_at, t.publish_date,
                        v.vendor_track_id AS video_id, 1 AS prio
                 FROM vendor_track_map v
                 JOIN clouder_tracks t ON t.id = v.clouder_track_id
                 WHERE v.vendor = 'ytmusic' AND {_MISSING}
                 ORDER BY t.publish_date DESC NULLS LAST, t.created_at DESC, t.id
                 LIMIT :limit)
            ),
            picked AS MATERIALIZED (
                SELECT id, length_ms, created_at, publish_date, video_id, min(prio) AS prio
                FROM candidates
                GROUP BY id, length_ms, created_at, publish_date, video_id
                ORDER BY min(prio), publish_date DESC NULLS LAST, created_at DESC, id
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
            GROUP BY p.id, p.video_id, p.length_ms, p.created_at, p.publish_date, p.prio
            ORDER BY p.prio, p.publish_date DESC NULLS LAST, p.created_at DESC, p.id
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
        flagged = sorted(
            {
                i["track_id"]
                for i in items
                if (i["track_id"], i["analyzer"]) in accepted
                and i["analyzer"] in PAIR_ANALYZERS
                and i.get("status") == "ok"
                and (i.get("result") or {}).get("ai_detected") is True
            }
        )
        if flagged:
            self.discard_ai_tracks(track_ids=flagged, now=now)
        # Any stored pair result recounts, ok or not: after an admin requeue a failed re-run must
        # still clear the deleted ok row from its label's / artists' counts.
        recount = sorted(
            {
                i["track_id"]
                for i in items
                if (i["track_id"], i["analyzer"]) in accepted and i["analyzer"] in PAIR_ANALYZERS
            }
        )
        if recount:
            self.recount_ai_reputation(track_ids=recount)
        return [
            {"track_id": i["track_id"], "analyzer": i["analyzer"], "reason": "lease_lost"}
            for i in items
            if (i["track_id"], i["analyzer"]) not in accepted
        ]

    def recount_ai_reputation(self, *, track_ids: list[str]) -> None:
        """Recount the AI reputation of every label and artist of *track_ids* from all their tracks."""
        if not track_ids:
            return
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        ids = {f"t{i}": t for i, t in enumerate(track_ids)}
        self._data_api.execute(_RECOUNT_LABELS.format(ids=placeholders), ids)
        self._data_api.execute(_RECOUNT_ARTISTS.format(ids=placeholders), ids)

    def discard_ai_tracks(self, *, track_ids: list[str], now: datetime) -> dict[str, int]:
        """Apply the AI rule (_DISCARD_AI) to those of *track_ids* that a detector flags, then drop
        the tags of tracks that left every category of their user. Returns the counts."""
        if not track_ids:
            return {"moved": 0, "uncategorized": 0, "untagged": 0}
        # Data API lists bind as JSON, not text[]: one placeholder per id (see playlists_repository).
        placeholders = ", ".join(f":t{i}" for i in range(len(track_ids)))
        ids = {f"t{i}": t for i, t in enumerate(track_ids)}
        with self._data_api.transaction() as tx_id:
            (row,) = self._data_api.execute(
                _DISCARD_AI.format(ids=placeholders), {**ids, "now": now}, transaction_id=tx_id
            )
            untagged = 0
            if row["uncategorized_ids"]:
                left = row["uncategorized_ids"].split(",")
                marks = ", ".join(f":u{i}" for i in range(len(left)))
                untagged = len(
                    self._data_api.execute(
                        _UNTAG.format(ids=marks),
                        {f"u{i}": t for i, t in enumerate(left)},
                        transaction_id=tx_id,
                    )
                )
        return {
            "moved": int(row["moved"]),
            "uncategorized": int(row["uncategorized"]),
            "untagged": untagged,
        }

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
                   count(*) FILTER (WHERE status = 'ok'
                                    AND analyzer = ANY (string_to_array(:ai, ','))
                                    AND (result->>'ai_detected')::boolean) AS ai_detected,
                   max(analyzed_at) AS last_result_at
            FROM track_analyses GROUP BY 1, 2
            """,
            {"now": now, "ai": ",".join(AI_ANALYZERS)},
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
            stamps = [as_utc_datetime(r["last_result_at"]) for r in by.values()]
            last = max((t for t in stamps if t is not None), default=None)
            analyzers.append(
                {
                    "name": name,
                    "due": due.get(name, 0),
                    **n,
                    "ai_detected": int(by["ok"]["ai_detected"]) if "ok" in by else 0,
                    "last_result_at": last,
                }
            )
        lofcz, deezer = PAIR_ANALYZERS
        # Both funnels split the YT Music matches: every match lands in exactly one
        # bucket, so the buckets sum to total. For the pair a flag wins (it is what
        # the badge shows), then clean (both ok), failed, unusable, a live lease.
        (pair,) = self._data_api.execute(
            f"""
            WITH per_track AS (
                SELECT coalesce(bool_or(a.analyzer = :lofcz AND {_FLAG}), false) AS lofcz,
                       coalesce(bool_or(a.analyzer = :deezer AND {_FLAG}), false) AS deezer,
                       count(*) FILTER (WHERE a.status = 'ok') = 2 AS both_ok,
                       coalesce(bool_or(a.status = 'failed'), false) AS failed,
                       coalesce(bool_or(a.status = 'unusable_source'), false) AS unusable,
                       coalesce(bool_or(a.status = 'leased' AND {_HELD}), false) AS live
                FROM vendor_track_map v
                LEFT JOIN track_analyses a
                  ON a.track_id = v.clouder_track_id AND a.analyzer IN (:lofcz, :deezer)
                WHERE v.vendor = 'ytmusic'
                GROUP BY v.clouder_track_id
            ), t AS (
                SELECT *, NOT (lofcz OR deezer OR both_ok) AS unflagged FROM per_track
            )
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE lofcz AND deezer) AS high,
                   count(*) FILTER (WHERE lofcz AND NOT deezer) AS medium,
                   count(*) FILTER (WHERE deezer AND NOT lofcz) AS low,
                   count(*) FILTER (WHERE both_ok AND NOT (lofcz OR deezer)) AS clean,
                   count(*) FILTER (WHERE unflagged AND failed) AS failed,
                   count(*) FILTER (WHERE unflagged AND NOT failed AND unusable) AS unusable,
                   count(*) FILTER (WHERE unflagged AND NOT failed AND NOT unusable AND live)
                       AS in_progress,
                   count(*) FILTER (WHERE unflagged AND NOT (failed OR unusable OR live))
                       AS waiting
            FROM t
            """,
            {"lofcz": lofcz, "deezer": deezer, "now": now},
        )
        (prof,) = self._data_api.execute(
            f"""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE a.status = 'ok') AS profiled,
                   count(*) FILTER (WHERE a.status = 'failed') AS failed,
                   count(*) FILTER (WHERE a.status = 'unusable_source') AS unusable,
                   count(*) FILTER (WHERE a.status = 'leased' AND {_HELD}) AS in_progress,
                   count(*) FILTER (WHERE a.status IS NULL OR NOT ({_HELD})) AS waiting
            FROM vendor_track_map v
            LEFT JOIN track_analyses a
              ON a.track_id = v.clouder_track_id AND a.analyzer = 'light_profile'
            WHERE v.vendor = 'ytmusic'
            """,
            {"now": now},
        )
        (models,) = self._data_api.execute(
            "SELECT count(*) AS n, max(trained_at) AS last FROM ml_models WHERE version > 0"
        )
        return {
            "last_claim_at": as_utc_datetime(state[0]["last_claim_at"]) if state else None,
            "last_result_at": as_utc_datetime(state[0]["last_result_at"]) if state else None,
            "analyzers": analyzers,
            "pair": {k: int(pair[k]) for k in ("high", "medium", "low", "clean")},
            "queue": {
                k: int(pair[k]) for k in ("total", "waiting", "in_progress", "failed", "unusable")
            },
            "profile": {
                k: int(prof[k])
                for k in ("total", "waiting", "in_progress", "profiled", "failed", "unusable")
            },
            "models": {
                "count": int(models["n"]),
                "last_trained_at": as_utc_datetime(models["last"]) if models["last"] else None,
            },
        }

    def analysis_stats_for_year(self, week_year: int) -> list[dict[str, Any]]:
        """Per (beatport style, Saturday week of publish_date) the YT Music matches (total),
        those the AI pair checked (a flag, both ok, or a final failure: the pipeline block's
        done), the AI-flagged ones, and those with a final light_profile state."""
        year_start = first_saturday(week_year)
        year_end = year_start + timedelta(days=weeks_in_year(week_year) * 7 - 1)
        lofcz, deezer = PAIR_ANALYZERS
        return self._data_api.execute(
            f"""
            WITH per_track AS (
                SELECT t.style_id, t.publish_date,
                       coalesce(bool_or(a.analyzer IN (:lofcz, :deezer) AND {_FLAG}), false)
                           AS ai,
                       count(*) FILTER (WHERE a.analyzer IN (:lofcz, :deezer)
                                          AND a.status = 'ok') = 2 AS both_ok,
                       coalesce(bool_or(a.analyzer IN (:lofcz, :deezer)
                                        AND a.status IN ('failed', 'unusable_source')), false)
                           AS dead,
                       coalesce(bool_or(a.analyzer = 'light_profile'
                                        AND a.status IN ('ok', 'failed', 'unusable_source')),
                                false) AS profiled
                FROM clouder_tracks t
                JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
                LEFT JOIN track_analyses a
                  ON a.track_id = t.id AND a.analyzer IN (:lofcz, :deezer, 'light_profile')
                WHERE t.publish_date BETWEEN :year_start AND :year_end
                GROUP BY t.id, t.style_id, t.publish_date
            )
            SELECT im.external_id AS beatport_style_id,
                   (p.publish_date - :year_start) / 7 + 1 AS week_number,
                   count(*) AS total,
                   count(*) FILTER (WHERE p.ai OR p.both_ok OR p.dead) AS checked,
                   count(*) FILTER (WHERE p.ai) AS ai,
                   count(*) FILTER (WHERE p.profiled) AS profiled
            FROM per_track p
            JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = p.style_id
            GROUP BY 1, 2
            """,
            {
                "lofcz": lofcz,
                "deezer": deezer,
                "year_start": year_start,
                "year_end": year_end,
            },
        )

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

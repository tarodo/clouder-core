"""Triage suggestions (spec §4-5): the ML worker's labels, models and predictions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from ._base import _LOOKUP_CHUNK, RepositoryBase, as_utc_datetime
from .analysis import AI_FLAGGED_SQL

PAGE = 2000  # rows per page: far under the Data API's 1 MiB response cap
UPSERT_CHUNK = 200
RETRAIN_PENDING = timedelta(hours=1)

# Every decision of U in S, one row per placement. Keeps: active STAGING buckets of U's non-deleted blocks
# (open or finalized) and every category_tracks row of U's categories (a soft-deleted category's tracks stay
# keeps without a class). Discards: the DISCARD buckets of those blocks. Auto buckets are not decisions.
_PLACEMENTS = """
    SELECT x.track_id, b.bucket_type = 'STAGING' AS keep,
           CASE WHEN c.deleted_at IS NULL THEN c.id END AS category_id, x.added_at
    FROM triage_blocks tb
    JOIN triage_buckets b ON b.triage_block_id = tb.id
     AND (b.bucket_type = 'DISCARD' OR (b.bucket_type = 'STAGING' AND NOT b.inactive))
    LEFT JOIN categories c ON c.id = b.category_id
    JOIN triage_bucket_tracks x ON x.triage_bucket_id = b.id
    WHERE tb.user_id = :user_id AND tb.style_id = :style_id AND tb.deleted_at IS NULL
    UNION ALL
    SELECT ct.track_id, TRUE, CASE WHEN c.deleted_at IS NULL THEN c.id END, ct.added_at
    FROM categories c JOIN category_tracks ct ON ct.category_id = c.id
    WHERE c.user_id = :user_id AND c.style_id = :style_id
"""

# One label per track: keep wins, then a live category, then the decision made last. added_at is when that
# decision was first made (a finalize re-adds staged tracks to the category: the label dates from the move,
# so the since-training metrics never score a label the previous model trained on).
_LABELS = f"""
WITH decisions AS (
    SELECT track_id, keep, category_id, min(added_at) AS added_at, max(added_at) AS last_at
    FROM ({_PLACEMENTS}) p
    WHERE track_id > :after
    GROUP BY track_id, keep, category_id
), labels AS (
    SELECT DISTINCT ON (track_id) track_id, keep, category_id, added_at
    FROM decisions
    ORDER BY track_id, keep DESC, category_id IS NULL, last_at DESC, category_id
)
SELECT l.track_id, v.vendor_track_id AS video_id, l.keep, l.category_id, l.added_at
FROM labels l
JOIN clouder_tracks t ON t.id = l.track_id
JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
JOIN audio_features af ON af.video_id = v.vendor_track_id
WHERE NOT {AI_FLAGGED_SQL}
ORDER BY l.track_id
LIMIT :limit
"""

_MODEL_COLUMNS = """user_id, version, trained_at, retrain_requested_at, n_labels, n_keep,
    keep_threshold, classes, metrics, artifact_key"""


def _json(value: Any) -> Any:
    """A jsonb column: text from the Data API, already parsed by a driver."""
    return json.loads(value) if isinstance(value, str) else value


def _model(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **row,
        "trained_at": as_utc_datetime(row["trained_at"]),
        "retrain_requested_at": as_utc_datetime(row["retrain_requested_at"]),
        "classes": _json(row["classes"]),
        "metrics": _json(row["metrics"]),
    }


class MlMixin(RepositoryBase):
    def ml_labels(
        self,
        *,
        user_id: str,
        style_id: str,
        after_track_id: str | None = None,
        limit: int = PAGE,
    ) -> list[dict[str, Any]]:
        """One page of U's labels in S (spec §4), keyset on track_id: {track_id, video_id, keep,
        category_id, added_at}, through the track's current matched video to its profile."""
        rows = self._data_api.execute(
            _LABELS,
            {
                "user_id": user_id,
                "style_id": style_id,
                "after": after_track_id or "",
                "limit": limit,
            },
        )
        return [{**r, "added_at": as_utc_datetime(r["added_at"])} for r in rows]

    def ml_labels_since_training(self, *, user_id: str, style_id: str) -> int:
        """STAGING / DISCARD placements in U's blocks of S since the model trained (all if never)."""
        (row,) = self._data_api.execute(
            f"""
            SELECT count(*) AS n
            FROM triage_blocks tb
            JOIN triage_buckets b ON b.triage_block_id = tb.id
             AND b.bucket_type IN ('STAGING', 'DISCARD')
            JOIN triage_bucket_tracks x ON x.triage_bucket_id = b.id
            JOIN clouder_tracks t ON t.id = x.track_id
            WHERE tb.user_id = :user_id AND tb.style_id = :style_id AND tb.deleted_at IS NULL
              AND x.added_at > coalesce(
                  (SELECT m.trained_at FROM ml_models m
                   WHERE m.user_id = :user_id AND m.style_id = :style_id), '-infinity')
              AND NOT {AI_FLAGGED_SQL}
            """,
            {"user_id": user_id, "style_id": style_id},
        )
        return int(row["n"])

    def ml_style_tracks(
        self, *, style_id: str, after_track_id: str | None = None, limit: int = PAGE
    ) -> list[dict[str, Any]]:
        """One page of the style's profiled tracks {track_id, video_id}, keyset on track_id."""
        return self._data_api.execute(
            """
            SELECT t.id AS track_id, v.vendor_track_id AS video_id
            FROM clouder_tracks t
            JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
            JOIN audio_features af ON af.video_id = v.vendor_track_id
            WHERE t.style_id = :style_id AND t.id > :after
            ORDER BY t.id
            LIMIT :limit
            """,
            {"style_id": style_id, "after": after_track_id or "", "limit": limit},
        )

    def ml_tracks_for_videos(self, *, video_ids: list[str]) -> list[dict[str, Any]]:
        """{track_id, video_id, style_id} of the tracks whose YouTube match is one of *video_ids*."""
        if not video_ids:
            return []
        # Video ids are ^[A-Za-z0-9_-]+$: comma-joined text is safe.
        return self._data_api.execute(
            """
            SELECT v.clouder_track_id AS track_id, v.vendor_track_id AS video_id, t.style_id
            FROM vendor_track_map v JOIN clouder_tracks t ON t.id = v.clouder_track_id
            WHERE v.vendor = 'ytmusic' AND v.vendor_track_id = ANY(string_to_array(:ids, ','))
              AND t.style_id IS NOT NULL
            ORDER BY v.clouder_track_id
            """,
            {"ids": ",".join(video_ids)},
        )

    def ml_model(self, *, user_id: str, style_id: str) -> dict[str, Any] | None:
        rows = self._data_api.execute(
            f"SELECT {_MODEL_COLUMNS} FROM ml_models"
            " WHERE user_id = :user_id AND style_id = :style_id",
            {"user_id": user_id, "style_id": style_id},
        )
        return _model(rows[0]) if rows else None

    def ml_models_for_style(self, *, style_id: str) -> list[dict[str, Any]]:
        """Every trained model of the style (version > 0)."""
        rows = self._data_api.execute(
            f"SELECT {_MODEL_COLUMNS} FROM ml_models"
            " WHERE style_id = :style_id AND version > 0 ORDER BY user_id",
            {"style_id": style_id},
        )
        return [_model(r) for r in rows]

    def ml_models_overview(self, *, now: datetime) -> list[dict[str, Any]]:
        """The admin table: a row per (user, style) with an ml_models row or a live block, the
        model's metrics flattened; labels_since_training only for pairs without a model. One query:
        the admin page polls it every 30 s."""
        rows = self._data_api.execute(
            f"""
            WITH pairs AS (
                SELECT user_id, style_id FROM ml_models
                UNION
                SELECT user_id, style_id FROM triage_blocks WHERE deleted_at IS NULL
            ), predictions AS (
                SELECT p.user_id, p.style_id, count(*) AS n
                FROM pairs p
                JOIN track_predictions tp ON tp.user_id = p.user_id AND tp.style_id = p.style_id
                GROUP BY 1, 2
            ), since AS (
                -- ml_labels_since_training, grouped over the model-less pairs
                SELECT tb.user_id, tb.style_id, count(*) AS n
                FROM triage_blocks tb
                LEFT JOIN ml_models m ON m.user_id = tb.user_id AND m.style_id = tb.style_id
                JOIN triage_buckets b ON b.triage_block_id = tb.id
                 AND b.bucket_type IN ('STAGING', 'DISCARD')
                JOIN triage_bucket_tracks x ON x.triage_bucket_id = b.id
                JOIN clouder_tracks t ON t.id = x.track_id
                WHERE tb.deleted_at IS NULL AND coalesce(m.version, 0) = 0
                  AND x.added_at > coalesce(m.trained_at, '-infinity')
                  AND NOT {AI_FLAGGED_SQL}
                GROUP BY tb.user_id, tb.style_id
            )
            SELECT p.user_id,
                   coalesce(nullif(u.display_name, ''), nullif(u.email, ''), left(p.user_id, 8))
                       AS user_name,
                   p.style_id, s.name AS style_name, coalesce(m.version, 0) AS version,
                   m.trained_at,
                   coalesce(m.retrain_requested_at > coalesce(m.trained_at, '-infinity')
                            AND m.retrain_requested_at > :cutoff, false) AS retrain_pending,
                   m.n_labels, m.n_keep,
                   (m.metrics->>'rows_total')::int AS rows_total,
                   (m.metrics->'cv'->>'keep_auc')::float8 AS keep_auc,
                   (m.metrics->'cv'->>'category_bacc')::float8 AS category_bacc,
                   CASE WHEN jsonb_typeof(m.classes) = 'array'
                        THEN jsonb_array_length(m.classes) END AS n_classes,
                   (m.metrics->>'first_hit')::float8 AS first_hit,
                   (m.metrics->>'first_n')::int AS first_n,
                   (m.metrics->>'max_rss_mb')::int AS max_rss_mb,
                   coalesce(pr.n, 0) AS predictions,
                   CASE WHEN coalesce(m.version, 0) = 0 THEN coalesce(sc.n, 0) END
                       AS labels_since_training
            FROM pairs p
            JOIN users u ON u.id = p.user_id
            JOIN clouder_styles s ON s.id = p.style_id
            LEFT JOIN ml_models m ON m.user_id = p.user_id AND m.style_id = p.style_id
            LEFT JOIN predictions pr ON pr.user_id = p.user_id AND pr.style_id = p.style_id
            LEFT JOIN since sc ON sc.user_id = p.user_id AND sc.style_id = p.style_id
            ORDER BY user_name, style_name, p.user_id, p.style_id
            """,
            {"cutoff": now - RETRAIN_PENDING},
        )
        return [{**r, "trained_at": as_utc_datetime(r["trained_at"])} for r in rows]

    def ml_alive_categories(self, *, user_id: str, style_id: str) -> list[str]:
        rows = self._data_api.execute(
            "SELECT id FROM categories WHERE user_id = :user_id AND style_id = :style_id"
            " AND deleted_at IS NULL ORDER BY id",
            {"user_id": user_id, "style_id": style_id},
        )
        return [r["id"] for r in rows]

    def ml_predictions(
        self, *, user_id: str, style_id: str, track_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """track_id -> {model_version, keep_score, keep, categories} of the stored predictions."""
        out: dict[str, dict[str, Any]] = {}
        # 500 ids per call: a row carries every class, so 2 000 could pass the 1 MiB response cap.
        for start in range(0, len(track_ids), _LOOKUP_CHUNK):
            rows = self._data_api.execute(
                """
                SELECT track_id, model_version, keep_score, keep, categories
                FROM track_predictions
                WHERE user_id = :user_id AND style_id = :style_id
                  AND track_id = ANY(string_to_array(:ids, ','))
                """,
                {
                    "user_id": user_id,
                    "style_id": style_id,
                    "ids": ",".join(track_ids[start : start + _LOOKUP_CHUNK]),
                },
            )
            for r in rows:
                track_id = r.pop("track_id")
                out[track_id] = {**r, "categories": _json(r["categories"])}
        return out

    def ml_save_model(
        self,
        *,
        user_id: str,
        style_id: str,
        expected_version: int,
        n_labels: int,
        n_keep: int,
        keep_threshold: float | None,
        classes: list[str] | None,
        metrics: dict[str, Any],
        artifact_key: str,
        now: datetime,
    ) -> bool:
        """Store version expected_version + 1 unless another save moved the row past expected_version
        (optimistic). Inserts the row when none exists yet; clears the retrain request."""
        rows = self._data_api.execute(
            """
            INSERT INTO ml_models (user_id, style_id, version, trained_at, retrain_requested_at,
                n_labels, n_keep, keep_threshold, classes, metrics, artifact_key)
            VALUES (:user_id, :style_id, :version, :now, NULL, :n_labels, :n_keep,
                :keep_threshold, CAST(:classes AS jsonb), CAST(:metrics AS jsonb), :artifact_key)
            ON CONFLICT (user_id, style_id) DO UPDATE SET
                version = EXCLUDED.version, trained_at = EXCLUDED.trained_at,
                retrain_requested_at = NULL, n_labels = EXCLUDED.n_labels,
                n_keep = EXCLUDED.n_keep, keep_threshold = EXCLUDED.keep_threshold,
                classes = EXCLUDED.classes, metrics = EXCLUDED.metrics,
                artifact_key = EXCLUDED.artifact_key
            WHERE ml_models.version = :expected_version
            RETURNING 1
            """,
            {
                "user_id": user_id,
                "style_id": style_id,
                "version": expected_version + 1,
                "expected_version": expected_version,
                "now": now,
                "n_labels": n_labels,
                "n_keep": n_keep,
                "keep_threshold": keep_threshold,
                "classes": classes,
                "metrics": metrics,
                "artifact_key": artifact_key,
            },
        )
        return bool(rows)

    def ml_upsert_predictions(
        self,
        *,
        user_id: str,
        style_id: str,
        model_version: int,
        rows: list[dict[str, Any]],
        now: datetime,
    ) -> int:
        """Upsert *rows* ({track_id, keep_score, keep, categories}); a row of a newer model version
        stays. Returns the rows written."""
        written = 0
        for start in range(0, len(rows), UPSERT_CHUNK):
            written += len(
                self._data_api.execute(
                    """
                    INSERT INTO track_predictions (user_id, style_id, track_id, model_version,
                        keep_score, keep, categories, scored_at)
                    SELECT :user_id, :style_id, x.track_id, :model_version, x.keep_score, x.keep,
                           x.categories, :now
                    FROM jsonb_to_recordset(CAST(:items AS jsonb))
                        AS x(track_id text, keep_score real, keep boolean, categories jsonb)
                    ON CONFLICT (user_id, style_id, track_id) DO UPDATE SET
                        model_version = EXCLUDED.model_version, keep_score = EXCLUDED.keep_score,
                        keep = EXCLUDED.keep, categories = EXCLUDED.categories,
                        scored_at = EXCLUDED.scored_at
                    WHERE track_predictions.model_version <= EXCLUDED.model_version
                    RETURNING 1
                    """,
                    {
                        "user_id": user_id,
                        "style_id": style_id,
                        "model_version": model_version,
                        "items": rows[start : start + UPSERT_CHUNK],
                        "now": now,
                    },
                )
            )
        return written

    def ml_request_retrain(self, *, user_id: str, style_id: str, now: datetime) -> bool:
        """Mark a retrain requested unless one is pending (newer than trained_at and under an hour
        old, which also bounds a lost message). True: the caller should enqueue it."""
        rows = self._data_api.execute(
            """
            INSERT INTO ml_models (user_id, style_id, retrain_requested_at)
            VALUES (:user_id, :style_id, :now)
            ON CONFLICT (user_id, style_id) DO UPDATE
                SET retrain_requested_at = EXCLUDED.retrain_requested_at
            WHERE ml_models.retrain_requested_at IS NULL
               OR ml_models.retrain_requested_at <= coalesce(ml_models.trained_at, '-infinity')
               OR ml_models.retrain_requested_at <= :cutoff
            RETURNING 1
            """,
            {
                "user_id": user_id,
                "style_id": style_id,
                "now": now,
                "cutoff": now - RETRAIN_PENDING,
            },
        )
        return bool(rows)

    def ml_mark_too_few_labels(self, *, user_id: str, style_id: str, now: datetime) -> None:
        """A never-trained pair (version 0) that found too few labels at *now*, the labels' snapshot:
        trained_at = now restarts the 150-label count and the request clears; version stays 0 (no
        model). A trained model is left alone: its request stays pending for the hour."""
        self._data_api.execute(
            """
            INSERT INTO ml_models (user_id, style_id, trained_at) VALUES (:user_id, :style_id, :now)
            ON CONFLICT (user_id, style_id) DO UPDATE
                SET trained_at = EXCLUDED.trained_at, retrain_requested_at = NULL
            WHERE ml_models.version = 0
            """,
            {"user_id": user_id, "style_id": style_id, "now": now},
        )

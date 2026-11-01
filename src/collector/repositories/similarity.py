"""Similar tracks (spec 2026-11-01): the per-video embeddings the ML worker writes."""

from __future__ import annotations

from ._base import RepositoryBase

# The live artifact version (collector.ml.similarity fits it). Here, not there: the API zip has no
# numpy, and its reads filter on this too.
VERSION = "sim-1"
UPSERT_CHUNK = 50  # rows of ~1.8 KB vector text per statement


class SimilarityMixin(RepositoryBase):
    def similarity_videos(self, *, after_video_id: str | None, limit: int) -> list[str]:
        """Profiled video ids (`audio_features`), keyset on video_id."""
        rows = self._data_api.execute(
            "SELECT video_id FROM audio_features WHERE video_id > :after"
            " ORDER BY video_id LIMIT :limit",
            {"after": after_video_id or "", "limit": limit},
        )
        return [r["video_id"] for r in rows]

    def similarity_upsert(self, *, version: str, rows: list[tuple[str, str]]) -> None:
        """Store (video_id, vector text) rows of *version*, replacing a video's earlier vector."""
        for start in range(0, len(rows), UPSERT_CHUNK):
            items = [{"video_id": v, "embedding": e} for v, e in rows[start : start + UPSERT_CHUNK]]
            self._data_api.execute(
                """
                INSERT INTO audio_embeddings (video_id, version, embedding, created_at)
                SELECT x.video_id, :version, CAST(x.embedding AS vector), now()
                FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS x(video_id text, embedding text)
                ON CONFLICT (video_id, version) DO UPDATE SET
                    embedding = EXCLUDED.embedding, created_at = EXCLUDED.created_at
                """,
                {"version": version, "items": items},
            )

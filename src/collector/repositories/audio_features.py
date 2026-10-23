"""Feature store: which YouTube videos have a light-1 profile in S3, and the claim gate it opens."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import RepositoryBase

LIGHT_PROFILE = "light_profile"

# Turns a track's light_profile row into `ok` for EXCLUDED's video, overriding a lease.
OK_ON_CONFLICT = """
ON CONFLICT (track_id, analyzer) DO UPDATE SET
    status = 'ok', version = EXCLUDED.version, result = NULL, error = NULL,
    audio_sha256 = EXCLUDED.audio_sha256, video_id = EXCLUDED.video_id,
    analyzed_at = EXCLUDED.analyzed_at, lease_id = NULL, leased_until = NULL,
    updated_at = EXCLUDED.updated_at
"""

_ITEMS = """jsonb_to_recordset(CAST(:items AS jsonb))
    AS x(video_id text, version text, audio_sha256 text)"""


class AudioFeaturesMixin(RepositoryBase):
    def known_audio_features(self, *, video_ids: list[str]) -> dict[str, tuple[str, str]]:
        """video_id -> (version, audio_sha256) of the stored profiles among *video_ids*."""
        if not video_ids:
            return {}
        # Video ids are ^[A-Za-z0-9_-]+$: comma-joined text is safe.
        rows = self._data_api.execute(
            """
            SELECT video_id, version, audio_sha256 FROM audio_features
            WHERE video_id = ANY(string_to_array(:ids, ','))
            """,
            {"ids": ",".join(video_ids)},
        )
        return {r["video_id"]: (r["version"], r["audio_sha256"]) for r in rows}

    def record_audio_features(self, *, items: list[dict[str, Any]], now: datetime) -> int:
        """Upsert the profiles of *items* ({video_id, version, audio_sha256}), then mark every
        track whose ytmusic match is one of those videos `light_profile ok`. Returns the
        number of track rows written."""
        self._data_api.execute(
            f"""
            INSERT INTO audio_features (video_id, version, audio_sha256, created_at)
            SELECT x.video_id, x.version, x.audio_sha256, :now FROM {_ITEMS}
            ON CONFLICT (video_id) DO UPDATE SET
                version = EXCLUDED.version, audio_sha256 = EXCLUDED.audio_sha256,
                created_at = EXCLUDED.created_at
            WHERE (audio_features.version, audio_features.audio_sha256)
                IS DISTINCT FROM (EXCLUDED.version, EXCLUDED.audio_sha256)
            """,
            {"items": items, "now": now},
        )
        # ponytail: vendor_track_map has no (vendor, vendor_track_id) index, so this join
        # scans it; add one if the upload batches get slow.
        rows = self._data_api.execute(
            f"""
            INSERT INTO track_analyses
                (track_id, analyzer, status, version, video_id, audio_sha256,
                 analyzed_at, created_at, updated_at)
            SELECT v.clouder_track_id, '{LIGHT_PROFILE}', 'ok', x.version, x.video_id,
                   x.audio_sha256, :now, :now, :now
            FROM {_ITEMS}
            JOIN vendor_track_map v ON v.vendor = 'ytmusic' AND v.vendor_track_id = x.video_id
            {OK_ON_CONFLICT}
            RETURNING track_id
            """,
            {"items": items, "now": now},
        )
        return len(rows)

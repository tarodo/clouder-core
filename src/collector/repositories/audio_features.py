"""Per-video audio artifacts: which videos have a light-1 profile in S3 or a waveform,
and the claim gates they open."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ._base import RepositoryBase

LIGHT_PROFILE = "light_profile"
WAVEFORM = "waveform"
# The player draws a waveform only over a Spotify track this close to the decoded length:
# another edit (radio vs extended) would put every break in the wrong place.
WAVEFORM_TOLERANCE_MS = 3000

# Turns a track's light_profile / waveform row into `ok` for EXCLUDED's video, overriding a lease.
OK_ON_CONFLICT = """
ON CONFLICT (track_id, analyzer) DO UPDATE SET
    status = 'ok', version = EXCLUDED.version, result = NULL, error = NULL,
    audio_sha256 = EXCLUDED.audio_sha256, video_id = EXCLUDED.video_id,
    analyzed_at = EXCLUDED.analyzed_at, lease_id = NULL, leased_until = NULL,
    updated_at = EXCLUDED.updated_at
"""

_ITEMS = """jsonb_to_recordset(CAST(:items AS jsonb))
    AS x(video_id text, version text, audio_sha256 text)"""


def _mark_ok(analyzer: str) -> str:
    """Marks every track whose matched video is one of :items' videos `<analyzer> ok`."""
    # ponytail: vendor_track_map has no (vendor, vendor_track_id) index, so this join
    # scans it; add one if the upload batches get slow.
    return f"""
    INSERT INTO track_analyses
        (track_id, analyzer, status, version, video_id, audio_sha256,
         analyzed_at, created_at, updated_at)
    SELECT v.clouder_track_id, '{analyzer}', 'ok', x.version, x.video_id,
           x.audio_sha256, :now, :now, :now
    FROM {_ITEMS}
    JOIN vendor_track_map v ON v.vendor = 'ytmusic' AND v.vendor_track_id = x.video_id
    {OK_ON_CONFLICT}
    RETURNING track_id
    """


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
        track whose matched video is one of those videos `light_profile ok`. Returns the
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
        rows = self._data_api.execute(_mark_ok(LIGHT_PROFILE), {"items": items, "now": now})
        return len(rows)

    def record_audio_waveforms(self, *, items: list[dict[str, Any]], now: datetime) -> int:
        """Upsert the waveforms of *items* ({video_id, version, audio_sha256, duration_ms,
        data_b64}), then mark every track on those videos `waveform ok`. Returns the number
        of track rows written."""
        self._data_api.execute(
            """
            INSERT INTO audio_waveforms
                (video_id, version, audio_sha256, duration_ms, data, created_at)
            SELECT x.video_id, x.version, x.audio_sha256, x.duration_ms, x.data_b64, :now
            FROM jsonb_to_recordset(CAST(:items AS jsonb)) AS x(
                video_id text, version text, audio_sha256 text, duration_ms int, data_b64 text)
            ON CONFLICT (video_id) DO UPDATE SET
                version = EXCLUDED.version, audio_sha256 = EXCLUDED.audio_sha256,
                duration_ms = EXCLUDED.duration_ms, data = EXCLUDED.data,
                created_at = EXCLUDED.created_at
            WHERE (audio_waveforms.version, audio_waveforms.audio_sha256)
                IS DISTINCT FROM (EXCLUDED.version, EXCLUDED.audio_sha256)
            """,
            {"items": items, "now": now},
        )
        rows = self._data_api.execute(_mark_ok(WAVEFORM), {"items": items, "now": now})
        return len(rows)

    def track_waveform(self, *, track_id: str) -> dict[str, Any] | None:
        """{duration_ms, data} of the track's current video, or None: no waveform yet, or
        the Spotify track (what the player plays) differs in length by more than
        WAVEFORM_TOLERANCE_MS."""
        rows = self._data_api.execute(
            """
            SELECT w.duration_ms, w.data
            FROM clouder_tracks t
            JOIN vendor_track_map v ON v.clouder_track_id = t.id AND v.vendor = 'ytmusic'
            JOIN audio_waveforms w ON w.video_id = v.vendor_track_id
            JOIN source_entities se
              ON se.source = 'spotify' AND se.entity_type = 'track'
             AND se.external_id = t.spotify_id
            WHERE t.id = :track_id
              AND abs((se.payload->>'duration_ms')::int - w.duration_ms) <= :tolerance_ms
            """,
            {"track_id": track_id, "tolerance_ms": WAVEFORM_TOLERANCE_MS},
        )
        if not rows:
            return None
        return {"duration_ms": int(rows[0]["duration_ms"]), "data": rows[0]["data"]}

"""Vendor matches and the review queue."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from ._base import RepositoryBase
from .audio_features import LIGHT_PROFILE, OK_ON_CONFLICT, WAVEFORM
from .commands import UpsertVendorMatchCmd, VendorTrackMatch


class VendorMatchMixin(RepositoryBase):
    def get_vendor_match(
        self,
        clouder_track_id: str,
        vendor: str,
        transaction_id: str | None = None,
    ) -> VendorTrackMatch | None:
        rows = self._data_api.execute(
            """
            SELECT vendor_track_id, match_type, confidence, matched_at, payload
            FROM vendor_track_map
            WHERE clouder_track_id = :clouder_track_id AND vendor = :vendor
            """,
            {"clouder_track_id": clouder_track_id, "vendor": vendor},
            transaction_id=transaction_id,
        )
        if not rows:
            return None
        row = rows[0]
        matched_at = row["matched_at"]
        if isinstance(matched_at, str):
            matched_at = datetime.fromisoformat(matched_at)
        payload = row.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        return VendorTrackMatch(
            clouder_track_id=clouder_track_id,
            vendor=vendor,
            vendor_track_id=row["vendor_track_id"],
            match_type=row["match_type"],
            confidence=Decimal(str(row["confidence"])),
            matched_at=matched_at,
            payload=payload,
        )

    def upsert_vendor_match(
        self,
        cmd: UpsertVendorMatchCmd,
        transaction_id: str | None = None,
    ) -> None:
        if cmd.vendor == "ytmusic" and transaction_id is None:
            # The map row and its light_profile row move together: a timeout between the
            # statements must not leave an `ok` row for a video the track no longer has.
            with self._data_api.transaction() as tx:
                self.upsert_vendor_match(cmd, transaction_id=tx)
            return
        self._data_api.execute(
            """
            INSERT INTO vendor_track_map (
                clouder_track_id, vendor, vendor_track_id, match_type,
                confidence, matched_at, payload
            ) VALUES (
                :clouder_track_id, :vendor, :vendor_track_id, :match_type,
                :confidence, :matched_at, :payload
            )
            ON CONFLICT (clouder_track_id, vendor) DO UPDATE SET
                vendor_track_id = EXCLUDED.vendor_track_id,
                match_type      = EXCLUDED.match_type,
                confidence      = EXCLUDED.confidence,
                matched_at      = EXCLUDED.matched_at,
                payload         = EXCLUDED.payload
            """,
            {
                "clouder_track_id": cmd.clouder_track_id,
                "vendor": cmd.vendor,
                "vendor_track_id": cmd.vendor_track_id,
                "match_type": cmd.match_type,
                "confidence": cmd.confidence,
                "matched_at": cmd.matched_at,
                "payload": dict(cmd.payload),
            },
            transaction_id=transaction_id,
        )
        if cmd.vendor != "ytmusic":
            return
        # A profile and a waveform follow the track's current video: drop the claim gate of
        # the old one, then reopen it as ok when the new video has one already. A live lease
        # (video_id NULL) stays: deleting it would let a second claim download the track
        # again; if the video changed, the lease just runs out and the next claim sends
        # the new one.
        params = {
            "clouder_track_id": cmd.clouder_track_id,
            "video": cmd.vendor_track_id,
            "now": cmd.matched_at,
        }
        for analyzer, table in ((LIGHT_PROFILE, "audio_features"), (WAVEFORM, "audio_waveforms")):
            self._data_api.execute(
                f"""
                DELETE FROM track_analyses
                WHERE track_id = :clouder_track_id AND analyzer = '{analyzer}'
                  AND status <> 'leased' AND video_id IS DISTINCT FROM :video
                """,
                params,
                transaction_id=transaction_id,
            )
            self._data_api.execute(
                f"""
                INSERT INTO track_analyses
                    (track_id, analyzer, status, version, video_id, audio_sha256,
                     analyzed_at, created_at, updated_at)
                SELECT :clouder_track_id, '{analyzer}', 'ok', f.version, f.video_id,
                       f.audio_sha256, f.created_at, :now, :now
                FROM {table} f WHERE f.video_id = :video
                {OK_ON_CONFLICT}
                """,
                params,
                transaction_id=transaction_id,
            )

    def insert_review_candidate(
        self,
        *,
        review_id: str,
        clouder_track_id: str,
        vendor: str,
        candidates: list[dict[str, Any]],
        created_at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO match_review_queue (
                id, clouder_track_id, vendor, candidates, status, created_at
            ) VALUES (
                :id, :clouder_track_id, :vendor, :candidates, 'pending', :created_at
            )
            ON CONFLICT (clouder_track_id, vendor)
                WHERE status = 'pending'
                DO NOTHING
            """,
            {
                "id": review_id,
                "clouder_track_id": clouder_track_id,
                "vendor": vendor,
                "candidates": candidates,
                "created_at": created_at,
            },
            transaction_id=transaction_id,
        )

    def mark_no_match(
        self,
        *,
        clouder_track_id: str,
        vendor: str,
        created_at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        """Record a terminal 'no match found' outcome so the read surface can
        return not_found (distinct from pending). Idempotent via the partial
        unique index uq_review_no_match."""
        self._data_api.execute(
            """
            INSERT INTO match_review_queue (
                id, clouder_track_id, vendor, candidates, status, created_at
            ) VALUES (
                :id, :clouder_track_id, :vendor, :candidates, 'no_match', :created_at
            )
            ON CONFLICT (clouder_track_id, vendor)
                WHERE status = 'no_match'
                DO NOTHING
            """,
            {
                "id": str(uuid4()),
                "clouder_track_id": clouder_track_id,
                "vendor": vendor,
                "candidates": [],
                "created_at": created_at,
            },
            transaction_id=transaction_id,
        )

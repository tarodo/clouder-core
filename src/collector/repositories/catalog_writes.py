"""Canonical catalog writes: labels, styles, artists, albums, tracks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from ._base import _LOOKUP_CHUNK, RepositoryBase
from .commands import (
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateNamedEntityCmd,
    CreateTrackCmd,
    TrackState,
    UpsertTrackArtistCmd,
)

# Track columns a Beatport observation may set after creation (conservative merge).
TRACK_MERGE_FIELDS = (
    "mix_name",
    "isrc",
    "bpm",
    "length_ms",
    "key_name",
    "key_camelot",
    "publish_date",
    "album_id",
    "style_id",
)


class CatalogWritesMixin(RepositoryBase):
    def read_track_state(
        self,
        external_ids: Sequence[str],
        *,
        run_id: str,
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> dict[str, TrackState]:
        """Mergeable columns of existing Beatport tracks, keyed by external id.

        `stale` is the negation of the guarded source upsert's condition, so it
        reads the same before and after this run's upsert. Called after the
        upsert inside the chunk transaction: the upsert locks the source rows
        (also when its WHERE rejects the update), so no concurrent run can change
        these tracks between this read and the update.

        A canonical track can be fed by several Beatport ids (the early ISRC
        heuristic merged them). It takes its values from the newest observation
        among them; within one run the larger Beatport id wins. Any other source
        is stale for it, so replays converge instead of alternating between the
        releases.
        """
        unique = list(dict.fromkeys(external_ids))
        states: dict[str, TrackState] = {}
        for start in range(0, len(unique), _LOOKUP_CHUNK):
            chunk = unique[start : start + _LOOKUP_CHUNK]
            params: dict[str, Any] = {"run_id": run_id, "observed_at": observed_at}
            params.update({f"id{i}": ext for i, ext in enumerate(chunk)})
            placeholders = ", ".join(f":id{i}" for i in range(len(chunk)))
            rows = self._data_api.execute(
                f"""
                SELECT im.external_id,
                       COALESCE(
                           (se.last_run_id <> :run_id AND se.last_seen_at > :observed_at)
                           OR EXISTS (
                               SELECT 1
                               FROM identity_map im2
                               JOIN source_entities se2
                                 ON se2.source = im2.source
                                AND se2.entity_type = im2.entity_type
                                AND se2.external_id = im2.external_id
                               WHERE im2.clouder_entity_type = 'track'  -- idx_identity_map_clouder
                                 AND im2.clouder_id = im.clouder_id
                                 AND im2.source = 'beatport'
                                 AND im2.entity_type = 'track'
                                 AND im2.external_id <> im.external_id
                                 AND (
                                     (se2.last_run_id <> :run_id AND se2.last_seen_at > :observed_at)
                                     OR (se2.last_run_id = :run_id
                                         AND CAST(im2.external_id AS BIGINT) > CAST(im.external_id AS BIGINT))
                                 )
                           ),
                           FALSE
                       ) AS stale,
                       t.mix_name, t.isrc, t.bpm, t.length_ms, t.key_name, t.key_camelot,
                       t.publish_date, t.album_id, t.style_id
                FROM identity_map im
                JOIN clouder_tracks t ON t.id = im.clouder_id
                LEFT JOIN source_entities se
                  ON se.source = im.source
                 AND se.entity_type = im.entity_type
                 AND se.external_id = im.external_id
                WHERE im.source = 'beatport'
                  AND im.entity_type = 'track'
                  AND im.external_id IN ({placeholders})
                """,
                params,
                transaction_id=transaction_id,
            )
            for row in rows:
                states[str(row["external_id"])] = TrackState(
                    stale=bool(row["stale"]),
                    values={f: row[f] for f in TRACK_MERGE_FIELDS},
                )
        return states

    def batch_create_labels(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_styles(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_artists(
        self, commands: list[CreateNamedEntityCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            [_named_entity_params(cmd) for cmd in commands],
            transaction_id=transaction_id,
        )

    def batch_create_albums(
        self, commands: list[CreateAlbumCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_albums (
                id, title, normalized_title, release_date, label_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :release_date, :label_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                {
                    "id": cmd.album_id,
                    "title": cmd.title,
                    "normalized_title": cmd.normalized_title,
                    "release_date": cmd.release_date,
                    "label_id": cmd.label_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def batch_create_tracks(
        self, commands: list[CreateTrackCmd], transaction_id: str | None = None
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_tracks (
                id, title, normalized_title, mix_name, isrc, bpm, length_ms,
                key_name, key_camelot,
                publish_date, album_id, style_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :mix_name, :isrc, :bpm, :length_ms,
                :key_name, :key_camelot,
                :publish_date, :album_id, :style_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            [
                {
                    "id": cmd.track_id,
                    "title": cmd.title,
                    "normalized_title": cmd.normalized_title,
                    "mix_name": cmd.mix_name,
                    "isrc": cmd.isrc,
                    "bpm": cmd.bpm,
                    "length_ms": cmd.length_ms,
                    "key_name": cmd.key_name,
                    "key_camelot": cmd.key_camelot,
                    "publish_date": cmd.publish_date,
                    "album_id": cmd.album_id,
                    "style_id": cmd.style_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def batch_conservative_update_tracks(
        self,
        commands: list[ConservativeUpdateTrackCmd],
        transaction_id: str | None = None,
    ) -> None:
        """Fill newly present values without blanking existing ones (one round-trip).

        The CASE parameters are cast to their column types: an untyped NULL makes
        `:p IS NULL` (text) and `col <> :p` (column type) disagree, which fails the
        statement as soon as a track arrives without ISRC/BPM/length.
        """
        if not commands:
            return
        self._data_api.batch_execute(
            """
            UPDATE clouder_tracks
            SET mix_name = COALESCE(:mix_name, mix_name),
                isrc = CASE
                    WHEN CAST(:isrc AS VARCHAR) IS NULL THEN isrc
                    WHEN isrc IS NULL THEN CAST(:isrc AS VARCHAR)
                    WHEN isrc <> CAST(:isrc AS VARCHAR) THEN CAST(:isrc AS VARCHAR)
                    ELSE isrc
                END,
                bpm = CASE
                    WHEN CAST(:bpm AS INTEGER) IS NULL THEN bpm
                    WHEN bpm IS NULL THEN CAST(:bpm AS INTEGER)
                    WHEN bpm <> CAST(:bpm AS INTEGER) THEN CAST(:bpm AS INTEGER)
                    ELSE bpm
                END,
                length_ms = CASE
                    WHEN CAST(:length_ms AS INTEGER) IS NULL THEN length_ms
                    WHEN length_ms IS NULL THEN CAST(:length_ms AS INTEGER)
                    WHEN length_ms <> CAST(:length_ms AS INTEGER) THEN CAST(:length_ms AS INTEGER)
                    ELSE length_ms
                END,
                key_name = COALESCE(:key_name, key_name),
                key_camelot = COALESCE(:key_camelot, key_camelot),
                publish_date = COALESCE(:publish_date, publish_date),
                album_id = COALESCE(:album_id, album_id),
                style_id = COALESCE(:style_id, style_id),
                updated_at = :at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "mix_name": cmd.mix_name,
                    "isrc": cmd.isrc,
                    "bpm": cmd.bpm,
                    "length_ms": cmd.length_ms,
                    "key_name": cmd.key_name,
                    "key_camelot": cmd.key_camelot,
                    "publish_date": cmd.publish_date,
                    "album_id": cmd.album_id,
                    "style_id": cmd.style_id,
                    "at": cmd.at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def upsert_track_artist(
        self, cmd: UpsertTrackArtistCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_track_artists (track_id, artist_id, role)
            VALUES (:track_id, :artist_id, :role)
            ON CONFLICT (track_id, artist_id, role) DO NOTHING
            """,
            {
                "track_id": cmd.track_id,
                "artist_id": cmd.artist_id,
                "role": cmd.role,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_track_artists(
        self,
        commands: list[UpsertTrackArtistCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_track_artists (track_id, artist_id, role)
            VALUES (:track_id, :artist_id, :role)
            ON CONFLICT (track_id, artist_id, role) DO NOTHING
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "artist_id": cmd.artist_id,
                    "role": cmd.role,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def propagate_release_type_to_albums(
        self,
        track_ids: list[str],
        transaction_id: str | None = None,
    ) -> None:
        """Copy release_type from tracks onto their parent albums.

        Runs a single UPDATE that joins clouder_tracks → clouder_albums via
        album_id, for each track in *track_ids* whose release_type is set.
        """
        if not track_ids:
            return
        placeholders = ", ".join(f":id_{i}" for i in range(len(track_ids)))
        params: dict[str, Any] = {f"id_{i}": tid for i, tid in enumerate(track_ids)}
        self._data_api.execute(
            f"""
            UPDATE clouder_albums a
            SET release_type = t.release_type,
                updated_at = t.updated_at
            FROM clouder_tracks t
            WHERE t.album_id = a.id
              AND t.release_type IS NOT NULL
              AND t.id IN ({placeholders})
            """,
            params,
            transaction_id=transaction_id,
        )


def _named_entity_params(cmd: CreateNamedEntityCmd) -> dict[str, Any]:
    return {
        "id": cmd.entity_id,
        "name": cmd.name,
        "normalized_name": cmd.normalized_name,
        "at": cmd.at,
    }

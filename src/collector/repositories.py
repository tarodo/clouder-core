"""Repositories backed by Aurora Data API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .data_api import DataAPIClient, create_default_data_api_client
from .models import RunStatus
from .settings import get_data_api_settings


@dataclass(frozen=True)
class IdentityMapEntry:
    clouder_entity_type: str
    clouder_id: str


@dataclass(frozen=True)
class CreateIngestRunCmd:
    run_id: str
    source: str
    style_id: int
    raw_s3_key: str
    status: RunStatus
    item_count: int
    meta: Mapping[str, Any]
    started_at: datetime
    iso_year: int | None = None
    iso_week: int | None = None
    week_year: int | None = None
    week_number: int | None = None
    period_start: date | None = None
    period_end: date | None = None
    is_custom_range: bool = False


@dataclass(frozen=True)
class UpsertSourceEntityCmd:
    source: str
    entity_type: str
    external_id: str
    name: str | None
    normalized_name: str | None
    payload: Mapping[str, Any]
    payload_hash: str
    last_run_id: str | None
    observed_at: datetime


@dataclass(frozen=True)
class UpsertSourceRelationCmd:
    source: str
    from_entity_type: str
    from_external_id: str
    relation_type: str
    to_entity_type: str
    to_external_id: str
    last_run_id: str


@dataclass(frozen=True)
class UpsertIdentityCmd:
    source: str
    entity_type: str
    external_id: str
    clouder_entity_type: str
    clouder_id: str
    match_type: str
    confidence: Decimal
    observed_at: datetime


@dataclass(frozen=True)
class CreateTrackCmd:
    track_id: str
    title: str
    normalized_title: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: date | None
    album_id: str | None
    style_id: str | None
    at: datetime


@dataclass(frozen=True)
class ConservativeUpdateTrackCmd:
    track_id: str
    mix_name: str | None
    isrc: str | None
    bpm: int | None
    length_ms: int | None
    publish_date: date | None
    album_id: str | None
    style_id: str | None
    at: datetime


@dataclass(frozen=True)
class UpdateSpotifyResultCmd:
    track_id: str
    spotify_id: str | None
    searched_at: datetime
    release_type: str | None = None
    spotify_release_date: date | None = None


@dataclass(frozen=True)
class UpsertTrackArtistCmd:
    track_id: str
    artist_id: str
    role: str = "main"


@dataclass(frozen=True)
class VendorTrackMatch:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str
    confidence: Decimal
    matched_at: datetime
    payload: dict[str, Any]


@dataclass(frozen=True)
class UpsertVendorMatchCmd:
    clouder_track_id: str
    vendor: str
    vendor_track_id: str
    match_type: str
    confidence: Decimal
    matched_at: datetime
    payload: Mapping[str, Any]


class ClouderRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

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

    def set_run_completed(
        self, run_id: str, processed_count: int, finished_at: datetime
    ) -> None:
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

    def upsert_source_entity(
        self, cmd: UpsertSourceEntityCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO source_entities (
                source, entity_type, external_id, name, normalized_name,
                payload, payload_hash, first_seen_at, last_seen_at, last_run_id
            ) VALUES (
                :source, :entity_type, :external_id, :name, :normalized_name,
                :payload, :payload_hash, :observed_at, :observed_at, :last_run_id
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                name = EXCLUDED.name,
                normalized_name = EXCLUDED.normalized_name,
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                last_run_id = EXCLUDED.last_run_id
            """,
            {
                "source": cmd.source,
                "entity_type": cmd.entity_type,
                "external_id": cmd.external_id,
                "name": cmd.name,
                "normalized_name": cmd.normalized_name,
                "payload": dict(cmd.payload),
                "payload_hash": cmd.payload_hash,
                "observed_at": cmd.observed_at,
                "last_run_id": cmd.last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_entities(
        self,
        commands: list[UpsertSourceEntityCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO source_entities (
                source, entity_type, external_id, name, normalized_name,
                payload, payload_hash, first_seen_at, last_seen_at, last_run_id
            ) VALUES (
                :source, :entity_type, :external_id, :name, :normalized_name,
                :payload, :payload_hash, :observed_at, :observed_at, :last_run_id
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                name = EXCLUDED.name,
                normalized_name = EXCLUDED.normalized_name,
                payload = EXCLUDED.payload,
                payload_hash = EXCLUDED.payload_hash,
                last_seen_at = EXCLUDED.last_seen_at,
                last_run_id = EXCLUDED.last_run_id
            """,
            [
                {
                    "source": cmd.source,
                    "entity_type": cmd.entity_type,
                    "external_id": cmd.external_id,
                    "name": cmd.name,
                    "normalized_name": cmd.normalized_name,
                    "payload": dict(cmd.payload),
                    "payload_hash": cmd.payload_hash,
                    "observed_at": cmd.observed_at,
                    "last_run_id": cmd.last_run_id,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def upsert_source_relation(
        self, cmd: UpsertSourceRelationCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO source_relations (
                source, from_entity_type, from_external_id, relation_type,
                to_entity_type, to_external_id, last_run_id
            ) VALUES (
                :source, :from_entity_type, :from_external_id, :relation_type,
                :to_entity_type, :to_external_id, :last_run_id
            )
            ON CONFLICT (
                source, from_entity_type, from_external_id,
                relation_type, to_entity_type, to_external_id
            ) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id
            """,
            {
                "source": cmd.source,
                "from_entity_type": cmd.from_entity_type,
                "from_external_id": cmd.from_external_id,
                "relation_type": cmd.relation_type,
                "to_entity_type": cmd.to_entity_type,
                "to_external_id": cmd.to_external_id,
                "last_run_id": cmd.last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_relations(
        self,
        commands: list[UpsertSourceRelationCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO source_relations (
                source, from_entity_type, from_external_id, relation_type,
                to_entity_type, to_external_id, last_run_id
            ) VALUES (
                :source, :from_entity_type, :from_external_id, :relation_type,
                :to_entity_type, :to_external_id, :last_run_id
            )
            ON CONFLICT (
                source, from_entity_type, from_external_id,
                relation_type, to_entity_type, to_external_id
            ) DO UPDATE SET
                last_run_id = EXCLUDED.last_run_id
            """,
            [
                {
                    "source": cmd.source,
                    "from_entity_type": cmd.from_entity_type,
                    "from_external_id": cmd.from_external_id,
                    "relation_type": cmd.relation_type,
                    "to_entity_type": cmd.to_entity_type,
                    "to_external_id": cmd.to_external_id,
                    "last_run_id": cmd.last_run_id,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def find_identity(
        self,
        source: str,
        entity_type: str,
        external_id: str,
        transaction_id: str | None = None,
    ) -> IdentityMapEntry | None:
        rows = self._data_api.execute(
            """
            SELECT clouder_entity_type, clouder_id
            FROM identity_map
            WHERE source = :source
              AND entity_type = :entity_type
              AND external_id = :external_id
            """,
            {
                "source": source,
                "entity_type": entity_type,
                "external_id": external_id,
            },
            transaction_id=transaction_id,
        )
        if not rows:
            return None
        row = rows[0]
        return IdentityMapEntry(
            clouder_entity_type=str(row["clouder_entity_type"]),
            clouder_id=str(row["clouder_id"]),
        )

    def upsert_identity(
        self, cmd: UpsertIdentityCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                clouder_entity_type = EXCLUDED.clouder_entity_type,
                clouder_id = EXCLUDED.clouder_id,
                match_type = EXCLUDED.match_type,
                confidence = EXCLUDED.confidence,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            {
                "source": cmd.source,
                "entity_type": cmd.entity_type,
                "external_id": cmd.external_id,
                "clouder_entity_type": cmd.clouder_entity_type,
                "clouder_id": cmd.clouder_id,
                "match_type": cmd.match_type,
                "confidence": cmd.confidence,
                "observed_at": cmd.observed_at,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_identities(
        self,
        commands: list[UpsertIdentityCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO identity_map (
                source, entity_type, external_id, clouder_entity_type, clouder_id,
                match_type, confidence, first_seen_at, last_seen_at
            ) VALUES (
                :source, :entity_type, :external_id, :clouder_entity_type, :clouder_id,
                :match_type, :confidence, :observed_at, :observed_at
            )
            ON CONFLICT (source, entity_type, external_id) DO UPDATE SET
                clouder_entity_type = EXCLUDED.clouder_entity_type,
                clouder_id = EXCLUDED.clouder_id,
                match_type = EXCLUDED.match_type,
                confidence = EXCLUDED.confidence,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            [
                {
                    "source": cmd.source,
                    "entity_type": cmd.entity_type,
                    "external_id": cmd.external_id,
                    "clouder_entity_type": cmd.clouder_entity_type,
                    "clouder_id": cmd.clouder_id,
                    "match_type": cmd.match_type,
                    "confidence": cmd.confidence,
                    "observed_at": cmd.observed_at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    def create_artist(
        self,
        artist_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": artist_id,
                "name": name,
                "normalized_name": normalized_name,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def create_label(
        self,
        label_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": label_id,
                "name": name,
                "normalized_name": normalized_name,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def create_style(
        self,
        style_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)
            VALUES (:id, :name, :normalized_name, :at, :at)
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": style_id,
                "name": name,
                "normalized_name": normalized_name,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def create_album(
        self,
        album_id: str,
        title: str,
        normalized_title: str,
        release_date: date | None,
        label_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_albums (
                id, title, normalized_title, release_date, label_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :release_date, :label_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": album_id,
                "title": title,
                "normalized_title": normalized_title,
                "release_date": release_date,
                "label_id": label_id,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def create_track(
        self, cmd: CreateTrackCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_tracks (
                id, title, normalized_title, mix_name, isrc, bpm, length_ms,
                publish_date, album_id, style_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :mix_name, :isrc, :bpm, :length_ms,
                :publish_date, :album_id, :style_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": cmd.track_id,
                "title": cmd.title,
                "normalized_title": cmd.normalized_title,
                "mix_name": cmd.mix_name,
                "isrc": cmd.isrc,
                "bpm": cmd.bpm,
                "length_ms": cmd.length_ms,
                "publish_date": cmd.publish_date,
                "album_id": cmd.album_id,
                "style_id": cmd.style_id,
                "at": cmd.at,
            },
            transaction_id=transaction_id,
        )

    def conservative_update_track(
        self, cmd: ConservativeUpdateTrackCmd, transaction_id: str | None = None
    ) -> None:
        self._data_api.execute(
            """
            UPDATE clouder_tracks
            SET mix_name = COALESCE(:mix_name, mix_name),
                isrc = CASE
                    WHEN :isrc IS NULL THEN isrc
                    WHEN isrc IS NULL THEN :isrc
                    WHEN isrc <> :isrc THEN :isrc
                    ELSE isrc
                END,
                bpm = CASE
                    WHEN :bpm IS NULL THEN bpm
                    WHEN bpm IS NULL THEN :bpm
                    WHEN bpm <> :bpm THEN :bpm
                    ELSE bpm
                END,
                length_ms = CASE
                    WHEN :length_ms IS NULL THEN length_ms
                    WHEN length_ms IS NULL THEN :length_ms
                    WHEN length_ms <> :length_ms THEN :length_ms
                    ELSE length_ms
                END,
                publish_date = COALESCE(:publish_date, publish_date),
                album_id = COALESCE(:album_id, album_id),
                style_id = COALESCE(:style_id, style_id),
                updated_at = :at
            WHERE id = :track_id
            """,
            {
                "track_id": cmd.track_id,
                "mix_name": cmd.mix_name,
                "isrc": cmd.isrc,
                "bpm": cmd.bpm,
                "length_ms": cmd.length_ms,
                "publish_date": cmd.publish_date,
                "album_id": cmd.album_id,
                "style_id": cmd.style_id,
                "at": cmd.at,
            },
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

    # ── Spotify search methods ─────────────────────────────────────

    def find_tracks_needing_spotify_search(self, limit: int) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT t.id, t.isrc, t.title, t.normalized_title, t.length_ms,
                   string_agg(DISTINCT a.name, ', ') AS artists
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            WHERE t.isrc IS NOT NULL
              AND t.spotify_searched_at IS NULL
            GROUP BY t.id, t.isrc, t.title, t.normalized_title,
                     t.length_ms, t.created_at
            ORDER BY t.created_at DESC
            LIMIT :limit
            """,
            {"limit": limit},
        )

    def find_tracks_not_found_on_spotify(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where_extra = ""
        if search:
            where_extra = "AND t.normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT t.id, t.title, t.isrc, t.bpm, t.publish_date,
                   string_agg(DISTINCT a.name, ', ' ORDER BY a.name) AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists a ON ta.artist_id = a.id
            WHERE t.isrc IS NOT NULL
              AND t.spotify_searched_at IS NOT NULL
              AND t.spotify_id IS NULL
              {where_extra}
            GROUP BY t.id
            ORDER BY t.publish_date DESC NULLS LAST
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_tracks_not_found_on_spotify(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where_extra = ""
        if search:
            where_extra = "AND normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"""
            SELECT count(*) AS cnt
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NOT NULL
              AND spotify_id IS NULL
              {where_extra}
            """,
            params,
        )
        return int(rows[0]["cnt"]) if rows else 0

    def batch_update_spotify_results(
        self,
        commands: list[UpdateSpotifyResultCmd],
        transaction_id: str | None = None,
    ) -> None:
        if not commands:
            return
        self._data_api.batch_execute(
            """
            UPDATE clouder_tracks
            SET spotify_id = :spotify_id,
                spotify_searched_at = :searched_at,
                release_type = COALESCE(:release_type, release_type),
                spotify_release_date = COALESCE(
                    :spotify_release_date, spotify_release_date
                ),
                updated_at = :searched_at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "spotify_id": cmd.spotify_id,
                    "searched_at": cmd.searched_at,
                    "release_type": cmd.release_type,
                    "spotify_release_date": cmd.spotify_release_date,
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
        params: dict[str, Any] = {
            f"id_{i}": tid for i, tid in enumerate(track_ids)
        }
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

    # ── Read API methods ──────────────────────────────────────────────

    def list_tracks(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE t.normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT t.id, t.title, t.mix_name, t.isrc, t.bpm, t.length_ms,
                   t.publish_date, t.album_id, t.style_id, t.created_at, t.updated_at,
                   a.title AS album_title,
                   l.name AS label_name,
                   s.name AS style_name,
                   string_agg(DISTINCT art.name, ', ' ORDER BY art.name) AS artist_names
            FROM clouder_tracks t
            LEFT JOIN clouder_albums a ON t.album_id = a.id
            LEFT JOIN clouder_labels l ON a.label_id = l.id
            LEFT JOIN clouder_styles s ON t.style_id = s.id
            LEFT JOIN clouder_track_artists ta ON ta.track_id = t.id
            LEFT JOIN clouder_artists art ON ta.artist_id = art.id
            {where}
            GROUP BY t.id, a.title, l.name, s.name
            ORDER BY t.created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_tracks(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_tracks {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_artists(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT id, name, normalized_name, created_at, updated_at
            FROM clouder_artists
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_artists(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_artists {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_albums(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE a.normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT a.id, a.title, a.normalized_title, a.release_date,
                   a.label_id, a.created_at, a.updated_at,
                   l.name AS label_name
            FROM clouder_albums a
            LEFT JOIN clouder_labels l ON a.label_id = l.id
            {where}
            ORDER BY a.created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_albums(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_title LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_albums {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def list_styles(
        self, limit: int, offset: int, search: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        return self._data_api.execute(
            f"""
            SELECT id, name, normalized_name, created_at, updated_at
            FROM clouder_styles
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_styles(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_styles {where}", params
        )
        return int(rows[0]["cnt"]) if rows else 0

    def transaction(self):
        return self._data_api.transaction()

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

    def coverage_for_year(self, week_year: int) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT
                cs.id            AS clouder_style_id,
                cs.name          AS style_name,
                im.external_id   AS beatport_style_id,
                r.run_id,
                r.week_number,
                r.status,
                r.item_count,
                r.is_custom_range,
                r.period_start,
                r.period_end,
                r.started_at,
                r.finished_at
            FROM clouder_styles cs
            INNER JOIN identity_map im
              ON im.source = 'beatport'
              AND im.entity_type = 'style'
              AND im.clouder_entity_type = 'style'
              AND im.clouder_id = cs.id
            LEFT JOIN LATERAL (
                SELECT
                    ir.run_id, ir.week_year, ir.week_number, ir.style_id,
                    ir.status, ir.item_count, ir.is_custom_range,
                    ir.period_start, ir.period_end,
                    ir.started_at, ir.finished_at
                FROM ingest_runs ir
                WHERE ir.week_year = :week_year
                  AND ir.style_id::text = im.external_id
                ORDER BY ir.week_number, ir.started_at DESC
            ) r ON TRUE
            -- r.run_id IS NULL when this style has no runs for the year (LEFT JOIN);
            -- include those rows so the matrix shows empty cells for that style.
            WHERE r.run_id IS NULL OR NOT EXISTS (
                SELECT 1
                FROM ingest_runs ir2
                WHERE ir2.week_year = r.week_year
                  AND ir2.style_id = r.style_id
                  AND ir2.week_number = r.week_number
                  AND ir2.started_at > r.started_at
            )
            ORDER BY cs.name ASC, r.week_number ASC NULLS LAST
            """,
            {"week_year": week_year},
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


def parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_clouder_repository_from_env() -> ClouderRepository | None:
    settings = get_data_api_settings()
    if not settings.is_configured:
        return None

    data_api = create_default_data_api_client(
        resource_arn=str(settings.aurora_cluster_arn),
        secret_arn=str(settings.aurora_secret_arn),
        database=settings.aurora_database,
    )
    return ClouderRepository(data_api)

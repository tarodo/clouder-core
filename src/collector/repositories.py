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
    iso_year: int
    iso_week: int
    raw_s3_key: str
    status: RunStatus
    item_count: int
    meta: Mapping[str, Any]
    started_at: datetime


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


@dataclass(frozen=True)
class UpsertTrackArtistCmd:
    track_id: str
    artist_id: str
    role: str = "main"


class ClouderRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def create_ingest_run(self, cmd: CreateIngestRunCmd) -> None:
        self._data_api.execute(
            """
            INSERT INTO ingest_runs (
                run_id, source, style_id, iso_year, iso_week, raw_s3_key,
                status, item_count, processed_count, started_at, meta
            ) VALUES (
                :run_id, :source, :style_id, :iso_year, :iso_week, :raw_s3_key,
                :status, :item_count, 0, :started_at, :meta
            )
            ON CONFLICT (run_id) DO UPDATE SET
                source = EXCLUDED.source,
                style_id = EXCLUDED.style_id,
                iso_year = EXCLUDED.iso_year,
                iso_week = EXCLUDED.iso_week,
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
        final_error_message = (
            f"[phase={phase}] {error_message}" if phase else error_message
        )
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
                "error_message": final_error_message[:2000],
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
            SELECT id, isrc, title, normalized_title
            FROM clouder_tracks
            WHERE isrc IS NOT NULL
              AND spotify_searched_at IS NULL
            ORDER BY created_at DESC
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
                updated_at = :searched_at
            WHERE id = :track_id
            """,
            [
                {
                    "track_id": cmd.track_id,
                    "spotify_id": cmd.spotify_id,
                    "searched_at": cmd.searched_at,
                }
                for cmd in commands
            ],
            transaction_id=transaction_id,
        )

    # ── AI Search methods ───────────────────────────────────────────

    def find_labels_needing_search(
        self,
        prompt_slug: str,
        prompt_version: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        return self._data_api.execute(
            """
            SELECT cl.id, cl.name,
                   string_agg(DISTINCT se.payload->'genre'->>'name', ', '
                              ORDER BY se.payload->'genre'->>'name') AS styles
            FROM clouder_labels cl
            JOIN clouder_albums ca ON ca.label_id = cl.id
            JOIN clouder_tracks ct ON ct.album_id = ca.id
            JOIN identity_map im ON im.clouder_id = ct.id
                AND im.clouder_entity_type = 'track'
            JOIN source_entities se ON se.source = im.source
                AND se.entity_type = im.entity_type
                AND se.external_id = im.external_id
            LEFT JOIN ai_search_results asr ON asr.entity_id = cl.id
                AND asr.entity_type = 'label'
                AND asr.prompt_slug = :prompt_slug
                AND asr.prompt_version = :prompt_version
            WHERE asr.id IS NULL
                AND se.payload->'genre'->>'name' IS NOT NULL
            GROUP BY cl.id, cl.name
            ORDER BY cl.name
            LIMIT :limit
            """,
            {
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "limit": limit,
            },
        )

    def save_search_result(
        self,
        result_id: str,
        entity_type: str,
        entity_id: str,
        prompt_slug: str,
        prompt_version: str,
        result: dict[str, Any],
        searched_at: datetime,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO ai_search_results (
                id, entity_type, entity_id, prompt_slug, prompt_version,
                result, searched_at
            ) VALUES (
                :id, :entity_type, :entity_id, :prompt_slug, :prompt_version,
                :result, :searched_at
            )
            ON CONFLICT (entity_type, entity_id, prompt_slug, prompt_version) DO UPDATE SET
                result = EXCLUDED.result,
                searched_at = EXCLUDED.searched_at
            """,
            {
                "id": result_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "prompt_slug": prompt_slug,
                "prompt_version": prompt_version,
                "result": result,
                "searched_at": searched_at,
            },
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

    def list_labels(
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
            FROM clouder_labels
            {where}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def count_labels(self, search: str | None = None) -> int:
        params: dict[str, Any] = {}
        where = ""
        if search:
            where = "WHERE normalized_name LIKE :search"
            params["search"] = f"%{search.lower()}%"
        rows = self._data_api.execute(
            f"SELECT count(*) AS cnt FROM clouder_labels {where}", params
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

"""Repositories backed by Aurora Data API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import os
from typing import Any, Mapping

from .data_api import DataAPIClient, create_default_data_api_client


@dataclass(frozen=True)
class IdentityMapEntry:
    clouder_entity_type: str
    clouder_id: str


class ClouderRepository:
    def __init__(self, data_api: DataAPIClient) -> None:
        self._data_api = data_api

    def create_ingest_run(
        self,
        run_id: str,
        source: str,
        style_id: int,
        iso_year: int,
        iso_week: int,
        raw_s3_key: str,
        status: str,
        item_count: int,
        meta: Mapping[str, Any],
        started_at: datetime,
    ) -> None:
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
                "run_id": run_id,
                "source": source,
                "style_id": style_id,
                "iso_year": iso_year,
                "iso_week": iso_week,
                "raw_s3_key": raw_s3_key,
                "status": status,
                "item_count": item_count,
                "started_at": started_at,
                "meta": dict(meta),
            },
        )

    def set_run_completed(self, run_id: str, processed_count: int, finished_at: datetime) -> None:
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
                "status": "COMPLETED",
                "processed_count": processed_count,
                "finished_at": finished_at,
            },
        )

    def set_run_failed(self, run_id: str, error_code: str, error_message: str, finished_at: datetime) -> None:
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
                "status": "FAILED",
                "finished_at": finished_at,
                "error_code": error_code,
                "error_message": error_message[:2000],
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
        self,
        source: str,
        entity_type: str,
        external_id: str,
        name: str | None,
        normalized_name: str | None,
        payload: Mapping[str, Any],
        payload_hash: str,
        last_run_id: str,
        observed_at: datetime,
        transaction_id: str | None = None,
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
                "source": source,
                "entity_type": entity_type,
                "external_id": external_id,
                "name": name,
                "normalized_name": normalized_name,
                "payload": dict(payload),
                "payload_hash": payload_hash,
                "observed_at": observed_at,
                "last_run_id": last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_entities(
        self,
        rows: list[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        if not rows:
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
            rows,
            transaction_id=transaction_id,
        )

    def upsert_source_relation(
        self,
        source: str,
        from_entity_type: str,
        from_external_id: str,
        relation_type: str,
        to_entity_type: str,
        to_external_id: str,
        last_run_id: str,
        transaction_id: str | None = None,
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
                "source": source,
                "from_entity_type": from_entity_type,
                "from_external_id": from_external_id,
                "relation_type": relation_type,
                "to_entity_type": to_entity_type,
                "to_external_id": to_external_id,
                "last_run_id": last_run_id,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_source_relations(
        self,
        rows: list[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        if not rows:
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
            rows,
            transaction_id=transaction_id,
        )

    def find_identity(self, source: str, entity_type: str, external_id: str) -> IdentityMapEntry | None:
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
        )
        if not rows:
            return None
        row = rows[0]
        return IdentityMapEntry(
            clouder_entity_type=str(row["clouder_entity_type"]),
            clouder_id=str(row["clouder_id"]),
        )

    def upsert_identity(
        self,
        source: str,
        entity_type: str,
        external_id: str,
        clouder_entity_type: str,
        clouder_id: str,
        match_type: str,
        confidence: Decimal,
        observed_at: datetime,
        transaction_id: str | None = None,
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
                "source": source,
                "entity_type": entity_type,
                "external_id": external_id,
                "clouder_entity_type": clouder_entity_type,
                "clouder_id": clouder_id,
                "match_type": match_type,
                "confidence": confidence,
                "observed_at": observed_at,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_identities(
        self,
        rows: list[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        if not rows:
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
            rows,
            transaction_id=transaction_id,
        )

    def find_artist_by_normalized_name(self, normalized_name: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT id
            FROM clouder_artists
            WHERE normalized_name = :normalized_name
            """,
            {"normalized_name": normalized_name},
        )
        return [str(row["id"]) for row in rows]

    def create_artist(self, artist_id: str, name: str, normalized_name: str, at: datetime, transaction_id: str | None = None) -> None:
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

    def find_label_by_normalized_name(self, normalized_name: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT id
            FROM clouder_labels
            WHERE normalized_name = :normalized_name
            """,
            {"normalized_name": normalized_name},
        )
        return [str(row["id"]) for row in rows]

    def create_label(self, label_id: str, name: str, normalized_name: str, at: datetime, transaction_id: str | None = None) -> None:
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

    def find_album_by_signature(
        self,
        normalized_title: str,
        release_date: date | None,
        label_id: str | None,
    ) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT id
            FROM clouder_albums
            WHERE normalized_title = :normalized_title
              AND release_date IS NOT DISTINCT FROM :release_date
              AND label_id IS NOT DISTINCT FROM :label_id
            """,
            {
                "normalized_title": normalized_title,
                "release_date": release_date,
                "label_id": label_id,
            },
        )
        return [str(row["id"]) for row in rows]

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

    def find_track_by_isrc(self, isrc: str) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT id
            FROM clouder_tracks
            WHERE isrc = :isrc
            """,
            {"isrc": isrc},
        )
        return [str(row["id"]) for row in rows]

    def find_track_by_signature(self, normalized_title: str, album_id: str | None, length_ms: int | None) -> list[str]:
        rows = self._data_api.execute(
            """
            SELECT id
            FROM clouder_tracks
            WHERE normalized_title = :normalized_title
              AND album_id IS NOT DISTINCT FROM :album_id
              AND length_ms IS NOT DISTINCT FROM :length_ms
            """,
            {
                "normalized_title": normalized_title,
                "album_id": album_id,
                "length_ms": length_ms,
            },
        )
        return [str(row["id"]) for row in rows]

    def create_track(
        self,
        track_id: str,
        title: str,
        normalized_title: str,
        mix_name: str | None,
        isrc: str | None,
        bpm: int | None,
        length_ms: int | None,
        publish_date: date | None,
        album_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_tracks (
                id, title, normalized_title, mix_name, isrc, bpm, length_ms,
                publish_date, album_id, created_at, updated_at
            ) VALUES (
                :id, :title, :normalized_title, :mix_name, :isrc, :bpm, :length_ms,
                :publish_date, :album_id, :at, :at
            )
            ON CONFLICT (id) DO NOTHING
            """,
            {
                "id": track_id,
                "title": title,
                "normalized_title": normalized_title,
                "mix_name": mix_name,
                "isrc": isrc,
                "bpm": bpm,
                "length_ms": length_ms,
                "publish_date": publish_date,
                "album_id": album_id,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def conservative_update_track(
        self,
        track_id: str,
        mix_name: str | None,
        isrc: str | None,
        bpm: int | None,
        length_ms: int | None,
        publish_date: date | None,
        album_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
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
                updated_at = :at
            WHERE id = :track_id
            """,
            {
                "track_id": track_id,
                "mix_name": mix_name,
                "isrc": isrc,
                "bpm": bpm,
                "length_ms": length_ms,
                "publish_date": publish_date,
                "album_id": album_id,
                "at": at,
            },
            transaction_id=transaction_id,
        )

    def upsert_track_artist(self, track_id: str, artist_id: str, role: str = "main", transaction_id: str | None = None) -> None:
        self._data_api.execute(
            """
            INSERT INTO clouder_track_artists (track_id, artist_id, role)
            VALUES (:track_id, :artist_id, :role)
            ON CONFLICT (track_id, artist_id, role) DO NOTHING
            """,
            {
                "track_id": track_id,
                "artist_id": artist_id,
                "role": role,
            },
            transaction_id=transaction_id,
        )

    def batch_upsert_track_artists(
        self,
        rows: list[Mapping[str, Any]],
        transaction_id: str | None = None,
    ) -> None:
        if not rows:
            return
        self._data_api.batch_execute(
            """
            INSERT INTO clouder_track_artists (track_id, artist_id, role)
            VALUES (:track_id, :artist_id, :role)
            ON CONFLICT (track_id, artist_id, role) DO NOTHING
            """,
            rows,
            transaction_id=transaction_id,
        )

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
    resource_arn = os.getenv("AURORA_CLUSTER_ARN")
    secret_arn = os.getenv("AURORA_SECRET_ARN")
    database = os.getenv("AURORA_DATABASE", "postgres")
    if not resource_arn or not secret_arn:
        return None

    data_api = create_default_data_api_client(
        resource_arn=resource_arn,
        secret_arn=secret_arn,
        database=database,
    )
    return ClouderRepository(data_api)

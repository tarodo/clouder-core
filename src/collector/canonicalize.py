"""Canonicalization workflow for Beatport entities."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Dict, Iterable
from uuid import uuid4

from .logging_utils import log_event
from .models import CanonicalizationResult
from .normalize import NormalizedBundle
from .repositories import ClouderRepository, parse_iso_date, utc_now


MATCH_HEURISTIC = Decimal("0.850")
MATCH_AUTO_CREATE = Decimal("0.600")


@dataclass(frozen=True)
class CanonicalIds:
    labels: dict[int, str]
    artists: dict[int, str]
    albums: dict[int, str]
    tracks: dict[int, str]


class Canonicalizer:
    def __init__(self, repository: ClouderRepository) -> None:
        self._repository = repository

    def process_run(self, run_id: str, bundle: NormalizedBundle) -> CanonicalizationResult:
        observed_at = utc_now()
        log_event(
            "INFO",
            "canonicalization_process_started",
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
            relations_total=len(bundle.relations),
        )

        label_ids: Dict[int, str] = {}
        artist_ids: Dict[int, str] = {}
        album_ids: Dict[int, str] = {}
        track_ids: Dict[int, str] = {}

        # Labels
        self._repository.batch_upsert_source_entities(
            [
                _source_entity_row(
                    run_id=run_id,
                    entity_type="label",
                    external_id=str(label.bp_label_id),
                    name=label.name,
                    normalized_name=label.normalized_name,
                    payload=label.payload,
                    observed_at=observed_at,
                )
                for label in bundle.labels
            ]
        )
        label_identity_rows: list[dict[str, Any]] = []
        for label in bundle.labels:
            clouder_label_id, identity_row = self._resolve_label(label.bp_label_id, label.name, label.normalized_name, observed_at)
            label_ids[label.bp_label_id] = clouder_label_id
            if identity_row:
                label_identity_rows.append(identity_row)
        self._repository.batch_upsert_identities(label_identity_rows)
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="labels",
            item_count=len(label_ids),
        )

        # Artists
        self._repository.batch_upsert_source_entities(
            [
                _source_entity_row(
                    run_id=run_id,
                    entity_type="artist",
                    external_id=str(artist.bp_artist_id),
                    name=artist.name,
                    normalized_name=artist.normalized_name,
                    payload=artist.payload,
                    observed_at=observed_at,
                )
                for artist in bundle.artists
            ]
        )
        artist_identity_rows: list[dict[str, Any]] = []
        for artist in bundle.artists:
            clouder_artist_id, identity_row = self._resolve_artist(artist.bp_artist_id, artist.name, artist.normalized_name, observed_at)
            artist_ids[artist.bp_artist_id] = clouder_artist_id
            if identity_row:
                artist_identity_rows.append(identity_row)
        self._repository.batch_upsert_identities(artist_identity_rows)
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="artists",
            item_count=len(artist_ids),
        )

        # Albums
        self._repository.batch_upsert_source_entities(
            [
                _source_entity_row(
                    run_id=run_id,
                    entity_type="album",
                    external_id=str(album.bp_release_id),
                    name=album.title,
                    normalized_name=album.normalized_title,
                    payload=album.payload,
                    observed_at=observed_at,
                )
                for album in bundle.albums
            ]
        )
        album_identity_rows: list[dict[str, Any]] = []
        for album in bundle.albums:
            label_id = label_ids.get(album.bp_label_id) if album.bp_label_id is not None else None
            clouder_album_id, identity_row = self._resolve_album(
                bp_release_id=album.bp_release_id,
                title=album.title,
                normalized_title=album.normalized_title,
                release_date=album.release_date,
                label_id=label_id,
                observed_at=observed_at,
            )
            album_ids[album.bp_release_id] = clouder_album_id
            if identity_row:
                album_identity_rows.append(identity_row)
        self._repository.batch_upsert_identities(album_identity_rows)
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="albums",
            item_count=len(album_ids),
        )

        self._repository.batch_upsert_source_relations(
            [
                {
                    "source": "beatport",
                    "from_entity_type": relation.from_entity_type,
                    "from_external_id": relation.from_external_id,
                    "relation_type": relation.relation_type,
                    "to_entity_type": relation.to_entity_type,
                    "to_external_id": relation.to_external_id,
                    "last_run_id": run_id,
                }
                for relation in bundle.relations
            ]
        )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="relations",
            item_count=len(bundle.relations),
        )

        # Tracks are processed in batches to avoid long transactions on Data API.
        chunk_count = max(1, math.ceil(len(bundle.tracks) / 200)) if bundle.tracks else 0
        for chunk_index, chunk in enumerate(_chunks(bundle.tracks, 200), start=1):
            log_event(
                "INFO",
                "canonicalization_chunk_started",
                run_id=run_id,
                phase="tracks",
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                chunk_size=len(chunk),
            )
            with self._repository.transaction() as transaction_id:
                self._repository.batch_upsert_source_entities(
                    [
                        _source_entity_row(
                            run_id=run_id,
                            entity_type="track",
                            external_id=str(track.bp_track_id),
                            name=track.title,
                            normalized_name=track.normalized_title,
                            payload=track.payload,
                            observed_at=observed_at,
                        )
                        for track in chunk
                    ],
                    transaction_id=transaction_id,
                )
                track_artist_rows: set[tuple[str, str, str]] = set()
                track_identity_rows: list[dict[str, Any]] = []
                for track in chunk:
                    album_id = album_ids.get(track.bp_release_id) if track.bp_release_id is not None else None
                    clouder_track_id, identity_row = self._resolve_track(
                        bp_track_id=track.bp_track_id,
                        title=track.title,
                        normalized_title=track.normalized_title,
                        mix_name=track.mix_name,
                        isrc=track.isrc,
                        bpm=track.bpm,
                        length_ms=track.length_ms,
                        publish_date=track.publish_date,
                        album_id=album_id,
                        observed_at=observed_at,
                        transaction_id=transaction_id,
                    )
                    track_ids[track.bp_track_id] = clouder_track_id
                    if identity_row:
                        track_identity_rows.append(identity_row)

                    for bp_artist_id in track.bp_artist_ids:
                        artist_id = artist_ids.get(bp_artist_id)
                        if not artist_id:
                            continue
                        track_artist_rows.add((clouder_track_id, artist_id, "main"))
                if track_artist_rows:
                    self._repository.batch_upsert_track_artists(
                        [
                            {"track_id": track_id, "artist_id": artist_id, "role": role}
                            for track_id, artist_id, role in track_artist_rows
                        ],
                        transaction_id=transaction_id,
                    )
                self._repository.batch_upsert_identities(
                    track_identity_rows,
                    transaction_id=transaction_id,
                )
            log_event(
                "INFO",
                "canonicalization_chunk_completed",
                run_id=run_id,
                phase="tracks",
                chunk_index=chunk_index,
                chunk_count=chunk_count,
                chunk_size=len(chunk),
                tracks_processed=len(track_ids),
            )

        result = CanonicalizationResult(
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            tracks_processed=len(track_ids),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
        )
        log_event(
            "INFO",
            "canonicalization_process_completed",
            run_id=run_id,
            tracks_total=result.tracks_total,
            tracks_processed=result.tracks_processed,
            artists_total=result.artists_total,
            labels_total=result.labels_total,
            albums_total=result.albums_total,
        )
        return result

    def _resolve_label(
        self,
        bp_label_id: int,
        name: str,
        normalized_name: str,
        observed_at,
    ) -> tuple[str, dict[str, Any] | None]:
        identity = self._repository.find_identity("beatport", "label", str(bp_label_id))
        if identity:
            return identity.clouder_id, None

        candidates = self._repository.find_label_by_normalized_name(normalized_name)
        if len(candidates) == 1:
            clouder_id = candidates[0]
            return clouder_id, _identity_row(
                entity_type="label",
                external_id=str(bp_label_id),
                clouder_entity_type="label",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )

        clouder_id = str(uuid4())
        self._repository.create_label(clouder_id, name, normalized_name, observed_at)
        return clouder_id, _identity_row(
            entity_type="label",
            external_id=str(bp_label_id),
            clouder_entity_type="label",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )

    def _resolve_artist(
        self,
        bp_artist_id: int,
        name: str,
        normalized_name: str,
        observed_at,
    ) -> tuple[str, dict[str, Any] | None]:
        identity = self._repository.find_identity("beatport", "artist", str(bp_artist_id))
        if identity:
            return identity.clouder_id, None

        candidates = self._repository.find_artist_by_normalized_name(normalized_name)
        if len(candidates) == 1:
            clouder_id = candidates[0]
            return clouder_id, _identity_row(
                entity_type="artist",
                external_id=str(bp_artist_id),
                clouder_entity_type="artist",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )

        clouder_id = str(uuid4())
        self._repository.create_artist(clouder_id, name, normalized_name, observed_at)
        return clouder_id, _identity_row(
            entity_type="artist",
            external_id=str(bp_artist_id),
            clouder_entity_type="artist",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )

    def _resolve_album(
        self,
        bp_release_id: int,
        title: str,
        normalized_title: str,
        release_date: str | None,
        label_id: str | None,
        observed_at,
    ) -> tuple[str, dict[str, Any] | None]:
        identity = self._repository.find_identity("beatport", "album", str(bp_release_id))
        if identity:
            return identity.clouder_id, None

        candidates = self._repository.find_album_by_signature(
            normalized_title=normalized_title,
            release_date=parse_iso_date(release_date),
            label_id=label_id,
        )

        if len(candidates) == 1:
            clouder_id = candidates[0]
            return clouder_id, _identity_row(
                entity_type="album",
                external_id=str(bp_release_id),
                clouder_entity_type="album",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )

        clouder_id = str(uuid4())
        self._repository.create_album(
            album_id=clouder_id,
            title=title,
            normalized_title=normalized_title,
            release_date=parse_iso_date(release_date),
            label_id=label_id,
            at=observed_at,
        )
        return clouder_id, _identity_row(
            entity_type="album",
            external_id=str(bp_release_id),
            clouder_entity_type="album",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )

    def _resolve_track(
        self,
        bp_track_id: int,
        title: str,
        normalized_title: str,
        mix_name: str | None,
        isrc: str | None,
        bpm: int | None,
        length_ms: int | None,
        publish_date: str | None,
        album_id: str | None,
        observed_at,
        transaction_id: str | None,
    ) -> tuple[str, dict[str, Any] | None]:
        identity = self._repository.find_identity("beatport", "track", str(bp_track_id))
        if identity:
            self._repository.conservative_update_track(
                track_id=identity.clouder_id,
                mix_name=mix_name,
                isrc=isrc,
                bpm=bpm,
                length_ms=length_ms,
                publish_date=parse_iso_date(publish_date),
                album_id=album_id,
                at=observed_at,
                transaction_id=transaction_id,
            )
            return identity.clouder_id, None

        candidates: list[str]
        if isrc:
            candidates = self._repository.find_track_by_isrc(isrc)
        else:
            candidates = self._repository.find_track_by_signature(
                normalized_title=normalized_title,
                album_id=album_id,
                length_ms=length_ms,
            )

        if len(candidates) == 1:
            clouder_id = candidates[0]
            self._repository.conservative_update_track(
                track_id=clouder_id,
                mix_name=mix_name,
                isrc=isrc,
                bpm=bpm,
                length_ms=length_ms,
                publish_date=parse_iso_date(publish_date),
                album_id=album_id,
                at=observed_at,
                transaction_id=transaction_id,
            )
            return clouder_id, _identity_row(
                entity_type="track",
                external_id=str(bp_track_id),
                clouder_entity_type="track",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )

        clouder_id = str(uuid4())
        self._repository.create_track(
            track_id=clouder_id,
            title=title,
            normalized_title=normalized_title,
            mix_name=mix_name,
            isrc=isrc,
            bpm=bpm,
            length_ms=length_ms,
            publish_date=parse_iso_date(publish_date),
            album_id=album_id,
            at=observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_row(
            entity_type="track",
            external_id=str(bp_track_id),
            clouder_entity_type="track",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _source_entity_row(
    run_id: str,
    entity_type: str,
    external_id: str,
    name: str | None,
    normalized_name: str | None,
    payload: dict[str, Any],
    observed_at,
) -> dict[str, Any]:
    return {
        "source": "beatport",
        "entity_type": entity_type,
        "external_id": external_id,
        "name": name,
        "normalized_name": normalized_name,
        "payload": payload,
        "payload_hash": _payload_hash(payload),
        "last_run_id": run_id,
        "observed_at": observed_at,
    }


def _identity_row(
    entity_type: str,
    external_id: str,
    clouder_entity_type: str,
    clouder_id: str,
    match_type: str,
    confidence: Decimal,
    observed_at,
) -> dict[str, Any]:
    return {
        "source": "beatport",
        "entity_type": entity_type,
        "external_id": external_id,
        "clouder_entity_type": clouder_entity_type,
        "clouder_id": clouder_id,
        "match_type": match_type,
        "confidence": confidence,
        "observed_at": observed_at,
    }


def _chunks(items: Iterable[Any], chunk_size: int):
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

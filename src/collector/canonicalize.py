"""Canonicalization workflow for Beatport entities."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from typing import Any, Dict, Iterable
from uuid import uuid4

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

        label_ids: Dict[int, str] = {}
        artist_ids: Dict[int, str] = {}
        album_ids: Dict[int, str] = {}
        track_ids: Dict[int, str] = {}

        # Labels
        for label in bundle.labels:
            self._upsert_source_entity(
                run_id=run_id,
                entity_type="label",
                external_id=str(label.bp_label_id),
                name=label.name,
                normalized_name=label.normalized_name,
                payload=label.payload,
                observed_at=observed_at,
            )
            label_ids[label.bp_label_id] = self._resolve_label(label.bp_label_id, label.name, label.normalized_name, observed_at)

        # Artists
        for artist in bundle.artists:
            self._upsert_source_entity(
                run_id=run_id,
                entity_type="artist",
                external_id=str(artist.bp_artist_id),
                name=artist.name,
                normalized_name=artist.normalized_name,
                payload=artist.payload,
                observed_at=observed_at,
            )
            artist_ids[artist.bp_artist_id] = self._resolve_artist(artist.bp_artist_id, artist.name, artist.normalized_name, observed_at)

        # Albums
        for album in bundle.albums:
            self._upsert_source_entity(
                run_id=run_id,
                entity_type="album",
                external_id=str(album.bp_release_id),
                name=album.title,
                normalized_name=album.normalized_title,
                payload=album.payload,
                observed_at=observed_at,
            )
            label_id = label_ids.get(album.bp_label_id) if album.bp_label_id is not None else None
            album_ids[album.bp_release_id] = self._resolve_album(
                bp_release_id=album.bp_release_id,
                title=album.title,
                normalized_title=album.normalized_title,
                release_date=album.release_date,
                label_id=label_id,
                observed_at=observed_at,
            )

        for relation in bundle.relations:
            self._repository.upsert_source_relation(
                source="beatport",
                from_entity_type=relation.from_entity_type,
                from_external_id=relation.from_external_id,
                relation_type=relation.relation_type,
                to_entity_type=relation.to_entity_type,
                to_external_id=relation.to_external_id,
                last_run_id=run_id,
            )

        # Tracks are processed in batches to avoid long transactions on Data API.
        for chunk in _chunks(bundle.tracks, 200):
            with self._repository.transaction() as transaction_id:
                for track in chunk:
                    self._upsert_source_entity(
                        run_id=run_id,
                        entity_type="track",
                        external_id=str(track.bp_track_id),
                        name=track.title,
                        normalized_name=track.normalized_title,
                        payload=track.payload,
                        observed_at=observed_at,
                        transaction_id=transaction_id,
                    )

                    album_id = album_ids.get(track.bp_release_id) if track.bp_release_id is not None else None
                    clouder_track_id = self._resolve_track(
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

                    for bp_artist_id in track.bp_artist_ids:
                        artist_id = artist_ids.get(bp_artist_id)
                        if not artist_id:
                            continue
                        self._repository.upsert_track_artist(
                            track_id=clouder_track_id,
                            artist_id=artist_id,
                            transaction_id=transaction_id,
                        )

        return CanonicalizationResult(
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            tracks_processed=len(track_ids),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
        )

    def _upsert_source_entity(
        self,
        run_id: str,
        entity_type: str,
        external_id: str,
        name: str | None,
        normalized_name: str | None,
        payload: dict[str, Any],
        observed_at,
        transaction_id: str | None = None,
    ) -> None:
        self._repository.upsert_source_entity(
            source="beatport",
            entity_type=entity_type,
            external_id=external_id,
            name=name,
            normalized_name=normalized_name,
            payload=payload,
            payload_hash=_payload_hash(payload),
            last_run_id=run_id,
            observed_at=observed_at,
            transaction_id=transaction_id,
        )

    def _resolve_label(self, bp_label_id: int, name: str, normalized_name: str, observed_at) -> str:
        identity = self._repository.find_identity("beatport", "label", str(bp_label_id))
        if identity:
            return identity.clouder_id

        candidates = self._repository.find_label_by_normalized_name(normalized_name)
        if len(candidates) == 1:
            clouder_id = candidates[0]
            self._repository.upsert_identity(
                source="beatport",
                entity_type="label",
                external_id=str(bp_label_id),
                clouder_entity_type="label",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )
            return clouder_id

        clouder_id = str(uuid4())
        self._repository.create_label(clouder_id, name, normalized_name, observed_at)
        self._repository.upsert_identity(
            source="beatport",
            entity_type="label",
            external_id=str(bp_label_id),
            clouder_entity_type="label",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )
        return clouder_id

    def _resolve_artist(self, bp_artist_id: int, name: str, normalized_name: str, observed_at) -> str:
        identity = self._repository.find_identity("beatport", "artist", str(bp_artist_id))
        if identity:
            return identity.clouder_id

        candidates = self._repository.find_artist_by_normalized_name(normalized_name)
        if len(candidates) == 1:
            clouder_id = candidates[0]
            self._repository.upsert_identity(
                source="beatport",
                entity_type="artist",
                external_id=str(bp_artist_id),
                clouder_entity_type="artist",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )
            return clouder_id

        clouder_id = str(uuid4())
        self._repository.create_artist(clouder_id, name, normalized_name, observed_at)
        self._repository.upsert_identity(
            source="beatport",
            entity_type="artist",
            external_id=str(bp_artist_id),
            clouder_entity_type="artist",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )
        return clouder_id

    def _resolve_album(
        self,
        bp_release_id: int,
        title: str,
        normalized_title: str,
        release_date: str | None,
        label_id: str | None,
        observed_at,
    ) -> str:
        identity = self._repository.find_identity("beatport", "album", str(bp_release_id))
        if identity:
            return identity.clouder_id

        candidates = self._repository.find_album_by_signature(
            normalized_title=normalized_title,
            release_date=parse_iso_date(release_date),
            label_id=label_id,
        )

        if len(candidates) == 1:
            clouder_id = candidates[0]
            self._repository.upsert_identity(
                source="beatport",
                entity_type="album",
                external_id=str(bp_release_id),
                clouder_entity_type="album",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
            )
            return clouder_id

        clouder_id = str(uuid4())
        self._repository.create_album(
            album_id=clouder_id,
            title=title,
            normalized_title=normalized_title,
            release_date=parse_iso_date(release_date),
            label_id=label_id,
            at=observed_at,
        )
        self._repository.upsert_identity(
            source="beatport",
            entity_type="album",
            external_id=str(bp_release_id),
            clouder_entity_type="album",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )
        return clouder_id

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
    ) -> str:
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
            return identity.clouder_id

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
            self._repository.upsert_identity(
                source="beatport",
                entity_type="track",
                external_id=str(bp_track_id),
                clouder_entity_type="track",
                clouder_id=clouder_id,
                match_type="heuristic",
                confidence=MATCH_HEURISTIC,
                observed_at=observed_at,
                transaction_id=transaction_id,
            )
            return clouder_id

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
        self._repository.upsert_identity(
            source="beatport",
            entity_type="track",
            external_id=str(bp_track_id),
            clouder_entity_type="track",
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _chunks(items: Iterable[Any], chunk_size: int):
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

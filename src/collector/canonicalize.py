"""Canonicalization workflow for Beatport entities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .logging_utils import log_event
from .models import CanonicalizationResult, EntityType
from .normalize import NormalizedBundle
from .repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
    UpsertSourceEntityCmd,
    UpsertSourceRelationCmd,
    UpsertTrackArtistCmd,
    parse_iso_date,
    utc_now,
)

MATCH_IDENTITY = Decimal("1.000")
MATCH_AUTO_CREATE = Decimal("0.600")


class Canonicalizer:
    def __init__(self, repository: ClouderRepository) -> None:
        self._repository = repository

    def process_run(
        self, run_id: str, bundle: NormalizedBundle
    ) -> CanonicalizationResult:
        observed_at = utc_now()
        log_event(
            "INFO",
            "canonicalization_process_started",
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            styles_total=len(bundle.styles),
            albums_total=len(bundle.albums),
            relations_total=len(bundle.relations),
        )

        completed_phases: list[str] = []
        try:
            label_ids = self._process_labels(
                run_id=run_id, bundle=bundle, observed_at=observed_at
            )
            completed_phases.append("labels")
            style_ids = self._process_styles(
                run_id=run_id, bundle=bundle, observed_at=observed_at
            )
            completed_phases.append("styles")
            artist_ids = self._process_artists(
                run_id=run_id, bundle=bundle, observed_at=observed_at
            )
            completed_phases.append("artists")
            album_ids = self._process_albums(
                run_id=run_id,
                bundle=bundle,
                observed_at=observed_at,
                label_ids=label_ids,
            )
            completed_phases.append("albums")
            self._process_relations(run_id=run_id, bundle=bundle)
            completed_phases.append("relations")
            track_ids = self._process_tracks(
                run_id=run_id,
                bundle=bundle,
                observed_at=observed_at,
                artist_ids=artist_ids,
                album_ids=album_ids,
                style_ids=style_ids,
            )
            completed_phases.append("tracks")
        except Exception as exc:
            log_event(
                "ERROR",
                "canonicalization_phase_failed",
                run_id=run_id,
                completed_phases=",".join(completed_phases),
                failed_after=completed_phases[-1] if completed_phases else "none",
                error_type=exc.__class__.__name__,
            )
            raise

        result = CanonicalizationResult(
            run_id=run_id,
            tracks_total=len(bundle.tracks),
            tracks_processed=len(track_ids),
            artists_total=len(bundle.artists),
            labels_total=len(bundle.labels),
            albums_total=len(bundle.albums),
            styles_total=len(bundle.styles),
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
            styles_total=result.styles_total,
        )
        return result

    def _process_labels(
        self, run_id: str, bundle: NormalizedBundle, observed_at: datetime
    ) -> dict[int, str]:
        label_ids: dict[int, str] = {}
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=EntityType.LABEL.value,
                        external_id=str(label.bp_label_id),
                        name=label.name,
                        normalized_name=label.normalized_name,
                        payload=label.payload,
                        observed_at=observed_at,
                    )
                    for label in bundle.labels
                ],
                transaction_id=transaction_id,
            )

            identity_commands: list[UpsertIdentityCmd] = []
            for label in bundle.labels:
                clouder_label_id, identity_cmd = self._resolve_label(
                    bp_label_id=label.bp_label_id,
                    name=label.name,
                    normalized_name=label.normalized_name,
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )
                label_ids[label.bp_label_id] = clouder_label_id
                if identity_cmd:
                    identity_commands.append(identity_cmd)
            self._repository.batch_upsert_identities(
                identity_commands, transaction_id=transaction_id
            )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="labels",
            item_count=len(label_ids),
        )
        return label_ids

    def _process_styles(
        self, run_id: str, bundle: NormalizedBundle, observed_at: datetime
    ) -> dict[int, str]:
        style_ids: dict[int, str] = {}
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=EntityType.STYLE.value,
                        external_id=str(style.bp_genre_id),
                        name=style.name,
                        normalized_name=style.normalized_name,
                        payload=style.payload,
                        observed_at=observed_at,
                    )
                    for style in bundle.styles
                ],
                transaction_id=transaction_id,
            )

            identity_commands: list[UpsertIdentityCmd] = []
            for style in bundle.styles:
                clouder_style_id, identity_cmd = self._resolve_style(
                    bp_genre_id=style.bp_genre_id,
                    name=style.name,
                    normalized_name=style.normalized_name,
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )
                style_ids[style.bp_genre_id] = clouder_style_id
                if identity_cmd:
                    identity_commands.append(identity_cmd)
            self._repository.batch_upsert_identities(
                identity_commands, transaction_id=transaction_id
            )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="styles",
            item_count=len(style_ids),
        )
        return style_ids

    def _process_artists(
        self, run_id: str, bundle: NormalizedBundle, observed_at: datetime
    ) -> dict[int, str]:
        artist_ids: dict[int, str] = {}
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=EntityType.ARTIST.value,
                        external_id=str(artist.bp_artist_id),
                        name=artist.name,
                        normalized_name=artist.normalized_name,
                        payload=artist.payload,
                        observed_at=observed_at,
                    )
                    for artist in bundle.artists
                ],
                transaction_id=transaction_id,
            )

            identity_commands: list[UpsertIdentityCmd] = []
            for artist in bundle.artists:
                clouder_artist_id, identity_cmd = self._resolve_artist(
                    bp_artist_id=artist.bp_artist_id,
                    name=artist.name,
                    normalized_name=artist.normalized_name,
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )
                artist_ids[artist.bp_artist_id] = clouder_artist_id
                if identity_cmd:
                    identity_commands.append(identity_cmd)
            self._repository.batch_upsert_identities(
                identity_commands, transaction_id=transaction_id
            )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="artists",
            item_count=len(artist_ids),
        )
        return artist_ids

    def _process_albums(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        label_ids: dict[int, str],
    ) -> dict[int, str]:
        album_ids: dict[int, str] = {}
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=EntityType.ALBUM.value,
                        external_id=str(album.bp_release_id),
                        name=album.title,
                        normalized_name=album.normalized_title,
                        payload=album.payload,
                        observed_at=observed_at,
                    )
                    for album in bundle.albums
                ],
                transaction_id=transaction_id,
            )

            identity_commands: list[UpsertIdentityCmd] = []
            for album in bundle.albums:
                label_id = (
                    label_ids.get(album.bp_label_id)
                    if album.bp_label_id is not None
                    else None
                )
                clouder_album_id, identity_cmd = self._resolve_album(
                    bp_release_id=album.bp_release_id,
                    title=album.title,
                    normalized_title=album.normalized_title,
                    release_date=album.release_date,
                    label_id=label_id,
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )
                album_ids[album.bp_release_id] = clouder_album_id
                if identity_cmd:
                    identity_commands.append(identity_cmd)
            self._repository.batch_upsert_identities(
                identity_commands, transaction_id=transaction_id
            )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="albums",
            item_count=len(album_ids),
        )
        return album_ids

    def _process_relations(self, run_id: str, bundle: NormalizedBundle) -> None:
        # Kept in a transaction for symmetry with other phases; atomicity
        # would hold without it since this is a single batch call.
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_relations(
                [
                    UpsertSourceRelationCmd(
                        source="beatport",
                        from_entity_type=relation.from_entity_type,
                        from_external_id=relation.from_external_id,
                        relation_type=relation.relation_type,
                        to_entity_type=relation.to_entity_type,
                        to_external_id=relation.to_external_id,
                        last_run_id=run_id,
                    )
                    for relation in bundle.relations
                ],
                transaction_id=transaction_id,
            )
        log_event(
            "INFO",
            "canonicalization_phase_completed",
            run_id=run_id,
            phase="relations",
            item_count=len(bundle.relations),
        )

    def _process_tracks(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        artist_ids: dict[int, str],
        album_ids: dict[int, str],
        style_ids: dict[int, str],
    ) -> dict[int, str]:
        track_ids: dict[int, str] = {}
        chunk_count = (
            max(1, math.ceil(len(bundle.tracks) / 200)) if bundle.tracks else 0
        )

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
                        _source_entity_cmd(
                            run_id=run_id,
                            entity_type=EntityType.TRACK.value,
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

                track_artist_commands: set[UpsertTrackArtistCmd] = set()
                identity_commands: list[UpsertIdentityCmd] = []
                for track in chunk:
                    album_id = (
                        album_ids.get(track.bp_release_id)
                        if track.bp_release_id is not None
                        else None
                    )
                    style_id = (
                        style_ids.get(track.bp_genre_id)
                        if track.bp_genre_id is not None
                        else None
                    )
                    clouder_track_id, identity_cmd = self._resolve_track(
                        bp_track_id=track.bp_track_id,
                        title=track.title,
                        normalized_title=track.normalized_title,
                        mix_name=track.mix_name,
                        isrc=track.isrc,
                        bpm=track.bpm,
                        length_ms=track.length_ms,
                        publish_date=track.publish_date,
                        album_id=album_id,
                        style_id=style_id,
                        observed_at=observed_at,
                        transaction_id=transaction_id,
                    )
                    track_ids[track.bp_track_id] = clouder_track_id
                    if identity_cmd:
                        identity_commands.append(identity_cmd)

                    for bp_artist_id in track.bp_artist_ids:
                        artist_id = artist_ids.get(bp_artist_id)
                        if not artist_id:
                            continue
                        track_artist_commands.add(
                            UpsertTrackArtistCmd(
                                track_id=clouder_track_id,
                                artist_id=artist_id,
                                role="main",
                            )
                        )

                if track_artist_commands:
                    self._repository.batch_upsert_track_artists(
                        list(track_artist_commands),
                        transaction_id=transaction_id,
                    )
                self._repository.batch_upsert_identities(
                    identity_commands, transaction_id=transaction_id
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

        return track_ids

    def _resolve_label(
        self,
        bp_label_id: int,
        name: str,
        normalized_name: str,
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> tuple[str, UpsertIdentityCmd | None]:
        identity = self._repository.find_identity(
            "beatport",
            EntityType.LABEL.value,
            str(bp_label_id),
            transaction_id=transaction_id,
        )
        if identity:
            return identity.clouder_id, None

        clouder_id = str(uuid4())
        self._repository.create_label(
            clouder_id,
            name,
            normalized_name,
            observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_cmd(
            entity_type=EntityType.LABEL.value,
            external_id=str(bp_label_id),
            clouder_entity_type=EntityType.LABEL.value,
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )

    def _resolve_style(
        self,
        bp_genre_id: int,
        name: str,
        normalized_name: str,
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> tuple[str, UpsertIdentityCmd | None]:
        identity = self._repository.find_identity(
            "beatport",
            EntityType.STYLE.value,
            str(bp_genre_id),
            transaction_id=transaction_id,
        )
        if identity:
            return identity.clouder_id, None

        clouder_id = str(uuid4())
        self._repository.create_style(
            clouder_id,
            name,
            normalized_name,
            observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_cmd(
            entity_type=EntityType.STYLE.value,
            external_id=str(bp_genre_id),
            clouder_entity_type=EntityType.STYLE.value,
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
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> tuple[str, UpsertIdentityCmd | None]:
        identity = self._repository.find_identity(
            "beatport",
            EntityType.ARTIST.value,
            str(bp_artist_id),
            transaction_id=transaction_id,
        )
        if identity:
            return identity.clouder_id, None

        clouder_id = str(uuid4())
        self._repository.create_artist(
            clouder_id,
            name,
            normalized_name,
            observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_cmd(
            entity_type=EntityType.ARTIST.value,
            external_id=str(bp_artist_id),
            clouder_entity_type=EntityType.ARTIST.value,
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
        observed_at: datetime,
        transaction_id: str | None = None,
    ) -> tuple[str, UpsertIdentityCmd | None]:
        identity = self._repository.find_identity(
            "beatport",
            EntityType.ALBUM.value,
            str(bp_release_id),
            transaction_id=transaction_id,
        )
        if identity:
            return identity.clouder_id, None

        clouder_id = str(uuid4())
        self._repository.create_album(
            album_id=clouder_id,
            title=title,
            normalized_title=normalized_title,
            release_date=parse_iso_date(release_date),
            label_id=label_id,
            at=observed_at,
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_cmd(
            entity_type=EntityType.ALBUM.value,
            external_id=str(bp_release_id),
            clouder_entity_type=EntityType.ALBUM.value,
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
        style_id: str | None,
        observed_at: datetime,
        transaction_id: str | None,
    ) -> tuple[str, UpsertIdentityCmd | None]:
        identity = self._repository.find_identity(
            "beatport",
            EntityType.TRACK.value,
            str(bp_track_id),
            transaction_id=transaction_id,
        )
        if identity:
            self._repository.conservative_update_track(
                ConservativeUpdateTrackCmd(
                    track_id=identity.clouder_id,
                    mix_name=mix_name,
                    isrc=isrc,
                    bpm=bpm,
                    length_ms=length_ms,
                    publish_date=parse_iso_date(publish_date),
                    album_id=album_id,
                    style_id=style_id,
                    at=observed_at,
                ),
                transaction_id=transaction_id,
            )
            return identity.clouder_id, None

        clouder_id = str(uuid4())
        self._repository.create_track(
            CreateTrackCmd(
                track_id=clouder_id,
                title=title,
                normalized_title=normalized_title,
                mix_name=mix_name,
                isrc=isrc,
                bpm=bpm,
                length_ms=length_ms,
                publish_date=parse_iso_date(publish_date),
                album_id=album_id,
                style_id=style_id,
                at=observed_at,
            ),
            transaction_id=transaction_id,
        )
        return clouder_id, _identity_cmd(
            entity_type=EntityType.TRACK.value,
            external_id=str(bp_track_id),
            clouder_entity_type=EntityType.TRACK.value,
            clouder_id=clouder_id,
            match_type="auto_create",
            confidence=MATCH_AUTO_CREATE,
            observed_at=observed_at,
        )


def _payload_hash(payload: Mapping[str, Any]) -> str:
    canonical_payload = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()


def _source_entity_cmd(
    run_id: str,
    entity_type: str,
    external_id: str,
    name: str | None,
    normalized_name: str | None,
    payload: Mapping[str, Any],
    observed_at: datetime,
) -> UpsertSourceEntityCmd:
    return UpsertSourceEntityCmd(
        source="beatport",
        entity_type=entity_type,
        external_id=external_id,
        name=name,
        normalized_name=normalized_name,
        payload=payload,
        payload_hash=_payload_hash(payload),
        last_run_id=run_id,
        observed_at=observed_at,
    )


def _identity_cmd(
    entity_type: str,
    external_id: str,
    clouder_entity_type: str,
    clouder_id: str,
    match_type: str,
    confidence: Decimal,
    observed_at: datetime,
) -> UpsertIdentityCmd:
    return UpsertIdentityCmd(
        source="beatport",
        entity_type=entity_type,
        external_id=external_id,
        clouder_entity_type=clouder_entity_type,
        clouder_id=clouder_id,
        match_type=match_type,
        confidence=confidence,
        observed_at=observed_at,
    )


def _chunks(items: Iterable[Any], chunk_size: int):
    chunk = []
    for item in items:
        chunk.append(item)
        if len(chunk) == chunk_size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk

"""Canonicalization workflow for Beatport entities.

Identities are resolved set-based: per phase (per 200-track chunk for tracks) one
batch claims a fresh id for every external id and one IN-list lookup reads the
winners back, instead of a Data API round-trip per entity. See ADR-0022.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import time
from typing import Any, Callable, Iterable, Mapping, Sequence
from uuid import uuid4

from .logging_utils import log_event
from .models import CanonicalizationResult, EntityType
from .normalize import NormalizedBundle
from .repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateNamedEntityCmd,
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
TRACK_CHUNK_SIZE = 200

# (bp id, name, normalized name, raw payload)
NamedEntity = tuple[int, str, str, Mapping[str, Any]]


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
            label_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="labels",
                entity_type=EntityType.LABEL.value,
                entities=[
                    (label.bp_label_id, label.name, label.normalized_name, label.payload)
                    for label in bundle.labels
                ],
                create=self._repository.batch_create_labels,
            )
            completed_phases.append("labels")
            style_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="styles",
                entity_type=EntityType.STYLE.value,
                entities=[
                    (style.bp_genre_id, style.name, style.normalized_name, style.payload)
                    for style in bundle.styles
                ],
                create=self._repository.batch_create_styles,
            )
            completed_phases.append("styles")
            artist_ids = self._process_named_entities(
                run_id=run_id,
                observed_at=observed_at,
                phase="artists",
                entity_type=EntityType.ARTIST.value,
                entities=[
                    (artist.bp_artist_id, artist.name, artist.normalized_name, artist.payload)
                    for artist in bundle.artists
                ],
                create=self._repository.batch_create_artists,
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

    def _resolve_identities(
        self,
        entity_type: str,
        external_ids: Sequence[str],
        observed_at: datetime,
        transaction_id: str,
    ) -> tuple[dict[str, str], set[str]]:
        """Map external ids to clouder ids in two Data API calls, race-safe.

        Claim a fresh id for every external id (ON CONFLICT DO NOTHING), then read
        the winners back. Ids whose winner is our candidate are new and need a
        canonical row; the rest already existed — or were just claimed by a
        concurrent run — and must not be created again.
        """
        candidates = {ext: str(uuid4()) for ext in dict.fromkeys(external_ids)}
        self._repository.claim_identities(
            [
                _identity_cmd(
                    entity_type=entity_type,
                    external_id=ext,
                    clouder_entity_type=entity_type,
                    clouder_id=clouder_id,
                    match_type="auto_create",
                    confidence=MATCH_AUTO_CREATE,
                    observed_at=observed_at,
                )
                for ext, clouder_id in candidates.items()
            ],
            transaction_id=transaction_id,
        )
        resolved = self._repository.find_identities(
            "beatport", entity_type, list(candidates), transaction_id=transaction_id
        )
        missing = candidates.keys() - resolved.keys()
        if missing:
            raise RuntimeError(
                f"identity claim did not resolve {len(missing)} {entity_type} ids"
            )
        created = {ext for ext, clouder_id in resolved.items() if clouder_id == candidates[ext]}
        return resolved, created

    def _process_named_entities(
        self,
        *,
        run_id: str,
        observed_at: datetime,
        phase: str,
        entity_type: str,
        entities: Sequence[NamedEntity],
        create: Callable[..., None],
    ) -> dict[int, str]:
        started = time.perf_counter()
        with self._repository.transaction() as transaction_id:
            self._repository.batch_upsert_source_entities(
                [
                    _source_entity_cmd(
                        run_id=run_id,
                        entity_type=entity_type,
                        external_id=str(bp_id),
                        name=name,
                        normalized_name=normalized_name,
                        payload=payload,
                        observed_at=observed_at,
                    )
                    for bp_id, name, normalized_name, payload in entities
                ],
                transaction_id=transaction_id,
            )
            resolved, created = self._resolve_identities(
                entity_type,
                [str(bp_id) for bp_id, _, _, _ in entities],
                observed_at=observed_at,
                transaction_id=transaction_id,
            )
            create(
                [
                    CreateNamedEntityCmd(
                        entity_id=resolved[str(bp_id)],
                        name=name,
                        normalized_name=normalized_name,
                        at=observed_at,
                    )
                    for bp_id, name, normalized_name, _ in entities
                    if str(bp_id) in created
                ],
                transaction_id=transaction_id,
            )
        ids = {bp_id: resolved[str(bp_id)] for bp_id, _, _, _ in entities}
        _log_phase(run_id, phase, len(ids), started)
        return ids

    def _process_albums(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        label_ids: dict[int, str],
    ) -> dict[int, str]:
        started = time.perf_counter()
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
            resolved, created = self._resolve_identities(
                EntityType.ALBUM.value,
                [str(album.bp_release_id) for album in bundle.albums],
                observed_at=observed_at,
                transaction_id=transaction_id,
            )
            self._repository.batch_create_albums(
                [
                    CreateAlbumCmd(
                        album_id=resolved[str(album.bp_release_id)],
                        title=album.title,
                        normalized_title=album.normalized_title,
                        release_date=parse_iso_date(album.release_date),
                        label_id=(
                            label_ids.get(album.bp_label_id)
                            if album.bp_label_id is not None
                            else None
                        ),
                        at=observed_at,
                    )
                    for album in bundle.albums
                    if str(album.bp_release_id) in created
                ],
                transaction_id=transaction_id,
            )
        album_ids = {
            album.bp_release_id: resolved[str(album.bp_release_id)]
            for album in bundle.albums
        }
        _log_phase(run_id, "albums", len(album_ids), started)
        return album_ids

    def _process_relations(self, run_id: str, bundle: NormalizedBundle) -> None:
        started = time.perf_counter()
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
        _log_phase(run_id, "relations", len(bundle.relations), started)

    def _process_tracks(
        self,
        run_id: str,
        bundle: NormalizedBundle,
        observed_at: datetime,
        artist_ids: dict[int, str],
        album_ids: dict[int, str],
        style_ids: dict[int, str],
    ) -> dict[int, str]:
        started = time.perf_counter()
        track_ids: dict[int, str] = {}
        chunk_count = (
            max(1, math.ceil(len(bundle.tracks) / TRACK_CHUNK_SIZE)) if bundle.tracks else 0
        )

        for chunk_index, chunk in enumerate(
            _chunks(bundle.tracks, TRACK_CHUNK_SIZE), start=1
        ):
            chunk_started = time.perf_counter()
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
                resolved, created = self._resolve_identities(
                    EntityType.TRACK.value,
                    [str(track.bp_track_id) for track in chunk],
                    observed_at=observed_at,
                    transaction_id=transaction_id,
                )

                new_tracks: list[CreateTrackCmd] = []
                updates: list[ConservativeUpdateTrackCmd] = []
                track_artist_commands: set[UpsertTrackArtistCmd] = set()
                for track in chunk:
                    clouder_track_id = resolved[str(track.bp_track_id)]
                    track_ids[track.bp_track_id] = clouder_track_id
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
                    publish_date = parse_iso_date(track.publish_date)
                    if str(track.bp_track_id) in created:
                        new_tracks.append(
                            CreateTrackCmd(
                                track_id=clouder_track_id,
                                title=track.title,
                                normalized_title=track.normalized_title,
                                mix_name=track.mix_name,
                                isrc=track.isrc,
                                bpm=track.bpm,
                                length_ms=track.length_ms,
                                key_name=track.key_name,
                                key_camelot=track.key_camelot,
                                publish_date=publish_date,
                                album_id=album_id,
                                style_id=style_id,
                                at=observed_at,
                            )
                        )
                    else:
                        updates.append(
                            ConservativeUpdateTrackCmd(
                                track_id=clouder_track_id,
                                mix_name=track.mix_name,
                                isrc=track.isrc,
                                bpm=track.bpm,
                                length_ms=track.length_ms,
                                key_name=track.key_name,
                                key_camelot=track.key_camelot,
                                publish_date=publish_date,
                                album_id=album_id,
                                style_id=style_id,
                                at=observed_at,
                            )
                        )
                    for bp_artist_id in track.bp_artist_ids:
                        artist_id = artist_ids.get(bp_artist_id)
                        if artist_id:
                            track_artist_commands.add(
                                UpsertTrackArtistCmd(
                                    track_id=clouder_track_id,
                                    artist_id=artist_id,
                                    role="main",
                                )
                            )

                self._repository.batch_create_tracks(
                    new_tracks, transaction_id=transaction_id
                )
                self._repository.batch_conservative_update_tracks(
                    updates, transaction_id=transaction_id
                )
                self._repository.batch_upsert_track_artists(
                    list(track_artist_commands), transaction_id=transaction_id
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
                duration_ms=int((time.perf_counter() - chunk_started) * 1000),
            )

        _log_phase(run_id, "tracks", len(track_ids), started)
        return track_ids

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


def _log_phase(run_id: str, phase: str, item_count: int, started: float) -> None:
    log_event(
        "INFO",
        "canonicalization_phase_completed",
        run_id=run_id,
        phase=phase,
        item_count=item_count,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )

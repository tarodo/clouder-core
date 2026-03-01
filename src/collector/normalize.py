"""Normalization of Beatport raw tracks into source entities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Tuple

from .models import (
    EntityType,
    NormalizedAlbum,
    NormalizedArtist,
    NormalizedLabel,
    NormalizedTrack,
    RelationType,
    normalize_text,
)


@dataclass(frozen=True)
class NormalizedRelation:
    from_entity_type: str
    from_external_id: str
    relation_type: str
    to_entity_type: str
    to_external_id: str


@dataclass(frozen=True)
class NormalizedBundle:
    artists: tuple[NormalizedArtist, ...]
    labels: tuple[NormalizedLabel, ...]
    albums: tuple[NormalizedAlbum, ...]
    tracks: tuple[NormalizedTrack, ...]
    relations: tuple[NormalizedRelation, ...]


def normalize_tracks(raw_tracks: Iterable[dict[str, Any]]) -> NormalizedBundle:
    artists_by_id: Dict[int, NormalizedArtist] = {}
    labels_by_id: Dict[int, NormalizedLabel] = {}
    albums_by_id: Dict[int, NormalizedAlbum] = {}
    tracks_by_id: Dict[int, NormalizedTrack] = {}
    relations: List[NormalizedRelation] = []

    for item in raw_tracks:
        if not isinstance(item, dict):
            continue

        bp_track_id = _as_positive_int(item.get("id"))
        if bp_track_id is None:
            continue

        artist_ids: List[int] = []
        for artist in _as_list(item.get("artists")):
            if not isinstance(artist, dict):
                continue
            bp_artist_id = _as_positive_int(artist.get("id"))
            name = _as_non_empty_str(artist.get("name"))
            if bp_artist_id is None or not name:
                continue

            if bp_artist_id not in artists_by_id:
                artists_by_id[bp_artist_id] = NormalizedArtist(
                    bp_artist_id=bp_artist_id,
                    name=name,
                    normalized_name=normalize_text(name),
                    payload=artist,
                )
            artist_ids.append(bp_artist_id)
            relations.append(
                NormalizedRelation(
                    from_entity_type=EntityType.TRACK.value,
                    from_external_id=str(bp_track_id),
                    relation_type=RelationType.TRACK_ARTIST.value,
                    to_entity_type=EntityType.ARTIST.value,
                    to_external_id=str(bp_artist_id),
                )
            )

        release = item.get("release")
        bp_release_id = None
        bp_label_id = None
        if isinstance(release, dict):
            bp_release_id = _as_positive_int(release.get("id"))
            release_name = _as_non_empty_str(release.get("name"))
            release_date = _as_date_str(
                item.get("publish_date") or item.get("new_release_date")
            )

            label = release.get("label")
            if isinstance(label, dict):
                bp_label_id = _as_positive_int(label.get("id"))
                label_name = _as_non_empty_str(label.get("name"))
                if bp_label_id is not None and label_name:
                    if bp_label_id not in labels_by_id:
                        labels_by_id[bp_label_id] = NormalizedLabel(
                            bp_label_id=bp_label_id,
                            name=label_name,
                            normalized_name=normalize_text(label_name),
                            payload=label,
                        )

            if bp_release_id is not None and release_name:
                if bp_release_id not in albums_by_id:
                    albums_by_id[bp_release_id] = NormalizedAlbum(
                        bp_release_id=bp_release_id,
                        title=release_name,
                        normalized_title=normalize_text(release_name),
                        release_date=release_date,
                        bp_label_id=bp_label_id,
                        payload=release,
                    )
                if bp_label_id is not None:
                    relations.append(
                        NormalizedRelation(
                            from_entity_type=EntityType.ALBUM.value,
                            from_external_id=str(bp_release_id),
                            relation_type=RelationType.ALBUM_LABEL.value,
                            to_entity_type=EntityType.LABEL.value,
                            to_external_id=str(bp_label_id),
                        )
                    )

        title = _as_non_empty_str(item.get("name"))
        if not title:
            continue

        track = NormalizedTrack(
            bp_track_id=bp_track_id,
            title=title,
            normalized_title=normalize_text(title),
            mix_name=_as_non_empty_str(item.get("mix_name")),
            isrc=_as_non_empty_str(item.get("isrc")),
            bpm=_as_positive_int(item.get("bpm")),
            length_ms=_as_positive_int(item.get("length_ms")),
            publish_date=_as_date_str(
                item.get("publish_date") or item.get("new_release_date")
            ),
            bp_release_id=bp_release_id,
            bp_artist_ids=tuple(dict.fromkeys(artist_ids)),
            payload=item,
        )
        tracks_by_id[bp_track_id] = track

        if bp_release_id is not None:
            relations.append(
                NormalizedRelation(
                    from_entity_type=EntityType.TRACK.value,
                    from_external_id=str(bp_track_id),
                    relation_type=RelationType.TRACK_ALBUM.value,
                    to_entity_type=EntityType.ALBUM.value,
                    to_external_id=str(bp_release_id),
                )
            )

    return NormalizedBundle(
        artists=tuple(artists_by_id.values()),
        labels=tuple(labels_by_id.values()),
        albums=tuple(albums_by_id.values()),
        tracks=tuple(tracks_by_id.values()),
        relations=tuple(_dedupe_relations(relations)),
    )


def _dedupe_relations(
    relations: Iterable[NormalizedRelation],
) -> list[NormalizedRelation]:
    seen = set()
    result: list[NormalizedRelation] = []
    for relation in relations:
        key = (
            relation.from_entity_type,
            relation.from_external_id,
            relation.relation_type,
            relation.to_entity_type,
            relation.to_external_id,
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(relation)
    return result


def _as_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if value <= 0:
        return None
    return value


def _as_non_empty_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _as_date_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if len(value) >= 10:
        candidate = value[:10]
        # Keep storage format stable and avoid parsing exceptions for malformed values.
        if candidate[4:5] == "-" and candidate[7:8] == "-":
            return candidate
    return None

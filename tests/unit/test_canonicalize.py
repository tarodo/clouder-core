from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import IdentityMapEntry

class FakeRepo:
    def __init__(self) -> None:
        self.identities: dict[tuple[str, str, str], IdentityMapEntry] = {}
        self.labels_by_name: dict[str, list[str]] = {}
        self.artists_by_name: dict[str, list[str]] = {}
        self.albums_by_sig: dict[tuple[str, str | None, str | None], list[str]] = {}
        self.tracks_by_isrc: dict[str, list[str]] = {}
        self.tracks_by_sig: dict[tuple[str, str | None, int | None], list[str]] = {}
        self.created_labels: list[str] = []
        self.created_artists: list[str] = []
        self.created_albums: list[str] = []
        self.created_tracks: list[str] = []
        self.updated_tracks: list[str] = []
        self.track_artists: set[tuple[str, str, str]] = set()

    def upsert_source_entity(self, **kwargs):
        return None

    def batch_upsert_source_entities(self, rows, transaction_id: str | None = None):
        del transaction_id
        for row in rows:
            self.upsert_source_entity(**row)

    def upsert_source_relation(self, **kwargs):
        return None

    def batch_upsert_source_relations(self, rows, transaction_id: str | None = None):
        del transaction_id
        for row in rows:
            self.upsert_source_relation(**row)

    def find_identity(self, source: str, entity_type: str, external_id: str):
        return self.identities.get((source, entity_type, external_id))

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
    ):
        del match_type, confidence, observed_at, transaction_id
        self.identities[(source, entity_type, external_id)] = IdentityMapEntry(
            clouder_entity_type=clouder_entity_type,
            clouder_id=clouder_id,
        )

    def batch_upsert_identities(self, rows, transaction_id: str | None = None):
        del transaction_id
        for row in rows:
            self.upsert_identity(**row)

    def find_label_by_normalized_name(self, normalized_name: str):
        return self.labels_by_name.get(normalized_name, [])

    def create_label(self, label_id: str, name: str, normalized_name: str, at: datetime, transaction_id: str | None = None):
        del name, normalized_name, at, transaction_id
        self.created_labels.append(label_id)

    def find_artist_by_normalized_name(self, normalized_name: str):
        return self.artists_by_name.get(normalized_name, [])

    def create_artist(self, artist_id: str, name: str, normalized_name: str, at: datetime, transaction_id: str | None = None):
        del name, normalized_name, at, transaction_id
        self.created_artists.append(artist_id)

    def find_album_by_signature(self, normalized_title: str, release_date, label_id: str | None):
        release_key = release_date.isoformat() if release_date else None
        return self.albums_by_sig.get((normalized_title, release_key, label_id), [])

    def create_album(self, album_id: str, title: str, normalized_title: str, release_date, label_id: str | None, at: datetime, transaction_id: str | None = None):
        del title, at, transaction_id
        release_key = release_date.isoformat() if release_date else None
        self.created_albums.append(album_id)
        self.albums_by_sig[(normalized_title, release_key, label_id)] = [album_id]

    def find_track_by_isrc(self, isrc: str):
        return self.tracks_by_isrc.get(isrc, [])

    def find_track_by_signature(self, normalized_title: str, album_id: str | None, length_ms: int | None):
        return self.tracks_by_sig.get((normalized_title, album_id, length_ms), [])

    def create_track(
        self,
        track_id: str,
        title: str,
        normalized_title: str,
        mix_name: str | None,
        isrc: str | None,
        bpm: int | None,
        length_ms: int | None,
        publish_date,
        album_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del title, mix_name, bpm, publish_date, at, transaction_id
        self.created_tracks.append(track_id)
        if isrc:
            self.tracks_by_isrc[isrc] = [track_id]
        self.tracks_by_sig[(normalized_title, album_id, length_ms)] = [track_id]

    def conservative_update_track(
        self,
        track_id: str,
        mix_name: str | None,
        isrc: str | None,
        bpm: int | None,
        length_ms: int | None,
        publish_date,
        album_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del mix_name, isrc, bpm, length_ms, publish_date, album_id, at, transaction_id
        self.updated_tracks.append(track_id)

    def upsert_track_artist(self, track_id: str, artist_id: str, role: str = "main", transaction_id: str | None = None):
        del transaction_id
        self.track_artists.add((track_id, artist_id, role))

    def batch_upsert_track_artists(self, rows, transaction_id: str | None = None):
        del transaction_id
        for row in rows:
            self.upsert_track_artist(**row)

    @contextmanager
    def transaction(self):
        yield "tx"


def _raw_track(track_id: int = 1):
    return [
        {
            "id": track_id,
            "name": "Lot Like You",
            "mix_name": "Original Mix",
            "isrc": "GB8KE2509362",
            "bpm": 87,
            "length_ms": 244114,
            "publish_date": "2026-01-02",
            "artists": [
                {
                    "id": 713053,
                    "name": "Nick The Lot",
                }
            ],
            "release": {
                "id": 5654120,
                "name": "Low Down Deep Best Of 2025",
                "label": {
                    "id": 40187,
                    "name": "Low Down Deep Recordings",
                },
            },
        }
    ]


def test_canonicalizer_auto_creates_entities_when_no_matches() -> None:
    repo = FakeRepo()
    canonicalizer = Canonicalizer(repo)
    bundle = normalize_tracks(_raw_track())

    result = canonicalizer.process_run(run_id="run-1", bundle=bundle)

    assert result.tracks_processed == 1
    assert len(repo.created_labels) == 1
    assert len(repo.created_artists) == 1
    assert len(repo.created_albums) == 1
    assert len(repo.created_tracks) == 1

    assert ("beatport", "track", "1") in repo.identities
    assert ("beatport", "artist", "713053") in repo.identities
    assert ("beatport", "label", "40187") in repo.identities
    assert ("beatport", "album", "5654120") in repo.identities


def test_canonicalizer_reuses_existing_identity_and_updates_track() -> None:
    repo = FakeRepo()
    repo.identities[("beatport", "label", "40187")] = IdentityMapEntry("label", "label-1")
    repo.identities[("beatport", "artist", "713053")] = IdentityMapEntry("artist", "artist-1")
    repo.identities[("beatport", "album", "5654120")] = IdentityMapEntry("album", "album-1")
    repo.identities[("beatport", "track", "1")] = IdentityMapEntry("track", "track-1")

    canonicalizer = Canonicalizer(repo)
    bundle = normalize_tracks(_raw_track(track_id=1))

    result = canonicalizer.process_run(run_id="run-2", bundle=bundle)

    assert result.tracks_processed == 1
    assert repo.created_tracks == []
    assert repo.updated_tracks == ["track-1"]
    assert ("track-1", "artist-1", "main") in repo.track_artists

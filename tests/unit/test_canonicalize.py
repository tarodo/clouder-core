from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import (
    ConservativeUpdateTrackCmd,
    CreateTrackCmd,
    IdentityMapEntry,
    UpsertIdentityCmd,
    UpsertSourceEntityCmd,
    UpsertSourceRelationCmd,
    UpsertTrackArtistCmd,
)


class FakeRepo:
    def __init__(self) -> None:
        self.identities: dict[tuple[str, str, str], IdentityMapEntry] = {}
        self.created_labels: list[str] = []
        self.created_styles: list[str] = []
        self.created_artists: list[str] = []
        self.created_albums: list[str] = []
        self.created_tracks: list[str] = []
        self.updated_tracks: list[str] = []
        self.track_artists: set[tuple[str, str, str]] = set()

    def upsert_source_entity(
        self, cmd: UpsertSourceEntityCmd, transaction_id: str | None = None
    ) -> None:
        del cmd, transaction_id

    def batch_upsert_source_entities(
        self, commands, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        for cmd in commands:
            self.upsert_source_entity(cmd)

    def upsert_source_relation(
        self, cmd: UpsertSourceRelationCmd, transaction_id: str | None = None
    ) -> None:
        del cmd, transaction_id

    def batch_upsert_source_relations(
        self, commands, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        for cmd in commands:
            self.upsert_source_relation(cmd)

    def find_identity(
        self,
        source: str,
        entity_type: str,
        external_id: str,
        transaction_id: str | None = None,
    ):
        return self.identities.get((source, entity_type, external_id))

    def upsert_identity(
        self, cmd: UpsertIdentityCmd, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        self.identities[(cmd.source, cmd.entity_type, cmd.external_id)] = (
            IdentityMapEntry(
                clouder_entity_type=cmd.clouder_entity_type,
                clouder_id=cmd.clouder_id,
            )
        )

    def batch_upsert_identities(
        self, commands, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        for cmd in commands:
            self.upsert_identity(cmd)

    def create_label(
        self,
        label_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del name, normalized_name, at, transaction_id
        self.created_labels.append(label_id)

    def create_style(
        self,
        style_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del name, normalized_name, at, transaction_id
        self.created_styles.append(style_id)

    def create_artist(
        self,
        artist_id: str,
        name: str,
        normalized_name: str,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del name, normalized_name, at, transaction_id
        self.created_artists.append(artist_id)

    def create_album(
        self,
        album_id: str,
        title: str,
        normalized_title: str,
        release_date,
        label_id: str | None,
        at: datetime,
        transaction_id: str | None = None,
    ):
        del title, at, transaction_id, normalized_title, release_date, label_id
        self.created_albums.append(album_id)

    def create_track(
        self, cmd: CreateTrackCmd, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        self.created_tracks.append(cmd.track_id)

    def conservative_update_track(
        self, cmd: ConservativeUpdateTrackCmd, transaction_id: str | None = None
    ) -> None:
        del transaction_id
        self.updated_tracks.append(cmd.track_id)

    def upsert_track_artist(
        self, cmd: UpsertTrackArtistCmd, transaction_id: str | None = None
    ):
        del transaction_id
        self.track_artists.add((cmd.track_id, cmd.artist_id, cmd.role))

    def batch_upsert_track_artists(self, commands, transaction_id: str | None = None):
        del transaction_id
        for cmd in commands:
            self.upsert_track_artist(cmd)

    @contextmanager
    def transaction(self):
        yield "tx"


def _raw_track(
    track_id: int = 1, artist_id: int = 713053, artist_name: str = "Nick The Lot"
):
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
                    "id": artist_id,
                    "name": artist_name,
                }
            ],
            "genre": {
                "id": 1,
                "name": "Drum & Bass",
            },
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
    assert result.styles_total == 1
    assert len(repo.created_labels) == 1
    assert len(repo.created_styles) == 1
    assert len(repo.created_artists) == 1
    assert len(repo.created_albums) == 1
    assert len(repo.created_tracks) == 1

    assert ("beatport", "track", "1") in repo.identities
    assert ("beatport", "artist", "713053") in repo.identities
    assert ("beatport", "label", "40187") in repo.identities
    assert ("beatport", "album", "5654120") in repo.identities
    assert ("beatport", "style", "1") in repo.identities


def test_canonicalizer_reuses_existing_identity_and_updates_track() -> None:
    repo = FakeRepo()
    repo.identities[("beatport", "label", "40187")] = IdentityMapEntry(
        "label", "label-1"
    )
    repo.identities[("beatport", "style", "1")] = IdentityMapEntry("style", "style-1")
    repo.identities[("beatport", "artist", "713053")] = IdentityMapEntry(
        "artist", "artist-1"
    )
    repo.identities[("beatport", "album", "5654120")] = IdentityMapEntry(
        "album", "album-1"
    )
    repo.identities[("beatport", "track", "1")] = IdentityMapEntry("track", "track-1")

    canonicalizer = Canonicalizer(repo)
    bundle = normalize_tracks(_raw_track(track_id=1))

    result = canonicalizer.process_run(run_id="run-2", bundle=bundle)

    assert result.tracks_processed == 1
    assert repo.created_tracks == []
    assert repo.created_styles == []
    assert repo.updated_tracks == ["track-1"]
    assert ("track-1", "artist-1", "main") in repo.track_artists


def test_same_name_different_beatport_ids_create_separate_entities() -> None:
    """Two artists with the same name but different beatport_ids must create
    two separate canonical artists (not merge into one)."""
    repo = FakeRepo()
    canonicalizer = Canonicalizer(repo)

    raw_tracks = [
        {
            "id": 1,
            "name": "Track A",
            "mix_name": "Original Mix",
            "isrc": "ISRC001",
            "bpm": 128,
            "length_ms": 300000,
            "publish_date": "2026-01-01",
            "artists": [{"id": 100, "name": "John Smith"}],
            "release": {
                "id": 9001,
                "name": "Album A",
                "label": {"id": 500, "name": "Same Label"},
            },
        },
        {
            "id": 2,
            "name": "Track B",
            "mix_name": "Original Mix",
            "isrc": "ISRC002",
            "bpm": 130,
            "length_ms": 310000,
            "publish_date": "2026-01-02",
            "artists": [{"id": 200, "name": "John Smith"}],
            "release": {
                "id": 9002,
                "name": "Album B",
                "label": {"id": 500, "name": "Same Label"},
            },
        },
    ]
    bundle = normalize_tracks(raw_tracks)

    canonicalizer.process_run(run_id="run-1", bundle=bundle)

    assert len(repo.created_artists) == 2

    identity_100 = repo.identities[("beatport", "artist", "100")]
    identity_200 = repo.identities[("beatport", "artist", "200")]
    assert identity_100.clouder_id != identity_200.clouder_id

    assert len(repo.created_labels) == 1
    assert len(repo.created_tracks) == 2

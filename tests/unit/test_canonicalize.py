from __future__ import annotations

from collections import Counter
from contextlib import contextmanager

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import CreateTrackCmd, IdentityMapEntry


class FakeRepo:
    def __init__(self) -> None:
        self.identities: dict[tuple[str, str, str], IdentityMapEntry] = {}
        self.lose_claims: dict[tuple[str, str], str] = {}  # (entity_type, ext) -> winner id
        self.calls: Counter[str] = Counter()
        self.created_labels: list[str] = []
        self.created_styles: list[str] = []
        self.created_artists: list[str] = []
        self.created_albums: list[str] = []
        self.created_tracks: list[str] = []
        self.created_track_cmds: list[CreateTrackCmd] = []
        self.updated_tracks: list[str] = []
        self.track_artists: set[tuple[str, str, str]] = set()
        self.track_states: dict[str, dict] = {}
        self.stale: set[str] = set()

    def batch_upsert_source_entities(self, commands, transaction_id=None) -> None:
        self.calls["batch_upsert_source_entities"] += 1

    def batch_upsert_source_relations(self, commands, transaction_id=None) -> None:
        self.calls["batch_upsert_source_relations"] += 1

    def claim_identities(self, commands, transaction_id=None) -> None:
        if not commands:
            return
        self.calls["claim_identities"] += 1
        for cmd in commands:
            key = (cmd.source, cmd.entity_type, cmd.external_id)
            winner = self.lose_claims.get((cmd.entity_type, cmd.external_id))
            if winner is not None:
                self.identities.setdefault(key, IdentityMapEntry(cmd.clouder_entity_type, winner))
            self.identities.setdefault(
                key, IdentityMapEntry(cmd.clouder_entity_type, cmd.clouder_id)
            )

    def find_identities(self, source, entity_type, external_ids, transaction_id=None):
        external_ids = list(external_ids)
        if not external_ids:
            return {}
        self.calls["find_identities"] += 1
        return {
            ext: self.identities[(source, entity_type, ext)].clouder_id
            for ext in external_ids
            if (source, entity_type, ext) in self.identities
        }

    def batch_create_labels(self, commands, transaction_id=None) -> None:
        self.created_labels.extend(cmd.entity_id for cmd in commands)

    def batch_create_styles(self, commands, transaction_id=None) -> None:
        self.created_styles.extend(cmd.entity_id for cmd in commands)

    def batch_create_artists(self, commands, transaction_id=None) -> None:
        self.created_artists.extend(cmd.entity_id for cmd in commands)

    def batch_create_albums(self, commands, transaction_id=None) -> None:
        self.created_albums.extend(cmd.album_id for cmd in commands)

    def batch_create_tracks(self, commands, transaction_id=None) -> None:
        self.created_tracks.extend(cmd.track_id for cmd in commands)
        self.created_track_cmds.extend(commands)

    def batch_conservative_update_tracks(self, commands, transaction_id=None) -> None:
        self.updated_tracks.extend(cmd.track_id for cmd in commands)

    def batch_upsert_track_artists(self, commands, transaction_id=None) -> None:
        for cmd in commands:
            self.track_artists.add((cmd.track_id, cmd.artist_id, cmd.role))

    def read_track_state(self, external_ids, *, run_id, observed_at, transaction_id=None):
        from collector.repositories import TrackState

        self.calls["read_track_state"] += 1
        return {
            ext: TrackState(stale=ext in self.stale, values=self.track_states.get(ext, {}))
            for ext in external_ids
            if ("beatport", "track", ext) in self.identities
        }

    @contextmanager
    def transaction(self):
        yield "tx"


def _raw_track(track_id: int = 1, artist_id: int = 713053, artist_name: str = "Nick The Lot"):
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
    repo.identities[("beatport", "label", "40187")] = IdentityMapEntry("label", "label-1")
    repo.identities[("beatport", "style", "1")] = IdentityMapEntry("style", "style-1")
    repo.identities[("beatport", "artist", "713053")] = IdentityMapEntry("artist", "artist-1")
    repo.identities[("beatport", "album", "5654120")] = IdentityMapEntry("album", "album-1")
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


def test_canonicalizer_threads_key_into_create_track_cmd() -> None:
    repo = FakeRepo()
    canonicalizer = Canonicalizer(repo)
    raw = _raw_track()
    raw[0]["key"] = {"name": "F Major", "camelot_number": 7, "camelot_letter": "B"}
    bundle = normalize_tracks(raw)

    canonicalizer.process_run(run_id="run-key", bundle=bundle)

    assert len(repo.created_track_cmds) == 1
    cmd = repo.created_track_cmds[0]
    assert cmd.key_name == "F Major"
    assert cmd.key_camelot == "7B"


def test_identity_calls_scale_with_chunks_not_entities() -> None:
    repo = FakeRepo()
    raw = [
        {**_raw_track(track_id=i, artist_id=10_000 + i, artist_name=f"A{i}")[0]}
        for i in range(1, 451)
    ]

    Canonicalizer(repo).process_run(run_id="run-scale", bundle=normalize_tracks(raw))

    # labels, styles, artists, albums + 3 track chunks (200 + 200 + 50)
    assert repo.calls["claim_identities"] == 7
    assert repo.calls["find_identities"] == 7
    assert len(repo.created_tracks) == 450


def test_lost_claims_reuse_the_winner_and_create_nothing() -> None:
    repo = FakeRepo()
    repo.lose_claims[("artist", "713053")] = "artist-winner"
    repo.lose_claims[("track", "1")] = "track-winner"

    Canonicalizer(repo).process_run(run_id="run-race", bundle=normalize_tracks(_raw_track()))

    assert repo.created_artists == []
    assert repo.created_tracks == []
    assert repo.updated_tracks == ["track-winner"]
    assert ("track-winner", "artist-winner", "main") in repo.track_artists


def test_empty_phases_make_no_identity_calls() -> None:
    repo = FakeRepo()
    raw = [{"id": 1, "name": "Lonely Track", "artists": []}]

    Canonicalizer(repo).process_run(run_id="run-empty", bundle=normalize_tracks(raw))

    assert repo.calls["claim_identities"] == 1  # the single track chunk only
    assert repo.calls["find_identities"] == 1
    assert repo.created_labels == repo.created_styles == repo.created_artists == []
    assert len(repo.created_tracks) == 1


from datetime import date

from collector.canonicalize import track_update

_FIELDS_NONE = {
    "mix_name": None,
    "isrc": None,
    "bpm": None,
    "length_ms": None,
    "key_name": None,
    "key_camelot": None,
    "publish_date": None,
    "album_id": None,
    "style_id": None,
}


def test_track_update_fresh_overwrites_with_carried_values() -> None:
    current = {**_FIELDS_NONE, "bpm": 120, "isrc": "A"}
    incoming = {**_FIELDS_NONE, "bpm": 124}

    write, changed = track_update(current, incoming, stale=False)

    assert changed == ("bpm",)
    assert write["bpm"] == 124
    assert write["isrc"] is None  # None = keep the column


def test_track_update_stale_only_fills_gaps() -> None:
    current = {**_FIELDS_NONE, "bpm": 124}
    incoming = {**_FIELDS_NONE, "bpm": 120, "isrc": "QZ1"}

    write, changed = track_update(current, incoming, stale=True)

    assert changed == ("isrc",)
    assert write["bpm"] is None
    assert write["isrc"] == "QZ1"


def test_track_update_compares_driver_strings_with_python_values() -> None:
    # The Data API returns DATE columns as 'YYYY-MM-DD' strings; Postgres as date.
    current = {**_FIELDS_NONE, "publish_date": "2026-09-26", "bpm": 128, "album_id": "a-1"}
    incoming = {**_FIELDS_NONE, "publish_date": date(2026, 9, 26), "bpm": 128, "album_id": "a-1"}

    _, changed = track_update(current, incoming, stale=False)

    assert changed == ()


def test_reused_track_without_changes_is_not_updated() -> None:
    repo = FakeRepo()
    bundle = normalize_tracks(_raw_track())
    Canonicalizer(repo).process_run(run_id="run-1", bundle=bundle)
    track = bundle.tracks[0]
    repo.track_states["1"] = {
        "mix_name": track.mix_name,
        "isrc": track.isrc,
        "bpm": track.bpm,
        "length_ms": track.length_ms,
        "key_name": None,
        "key_camelot": None,
        "publish_date": track.publish_date,
        "album_id": repo.identities[("beatport", "album", "5654120")].clouder_id,
        "style_id": repo.identities[("beatport", "style", "1")].clouder_id,
    }

    result = Canonicalizer(repo).process_run(run_id="run-2", bundle=bundle)

    assert repo.updated_tracks == []
    assert (result.tracks_created, result.tracks_changed) == (0, 0)


class _WriteSpy(FakeRepo):
    def __getattribute__(self, name):
        attr = super().__getattribute__(name)
        if name.startswith(("batch_", "claim_", "set_", "upsert_")):
            raise AssertionError(f"dry run called {name}")
        return attr


def test_dry_run_reports_creations_and_writes_nothing() -> None:
    repo = _WriteSpy()

    result = Canonicalizer(repo, dry_run=True).process_run(
        run_id="run-dry", bundle=normalize_tracks(_raw_track())
    )

    assert (result.tracks_created, result.artists_created, result.albums_created) == (1, 1, 1)
    assert (result.labels_created, result.styles_created) == (1, 1)
    assert repo.identities == {}

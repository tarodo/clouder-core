"""Round-trip counts of the set-based repository API (fake Data API)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from collector.repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateAlbumCmd,
    CreateNamedEntityCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
)

AT = datetime(2026, 10, 7, tzinfo=UTC)


class RecordingDataAPI:
    def __init__(self) -> None:
        self.executes: list[tuple[str, dict, str | None]] = []
        self.batches: list[tuple[str, list[dict], str | None]] = []

    def execute(self, sql, params=None, transaction_id=None):
        params = dict(params or {})
        self.executes.append((sql, params, transaction_id))
        ids = [value for key, value in params.items() if key.startswith("id")]
        return [{"external_id": ext, "clouder_id": f"c-{ext}"} for ext in ids]

    def batch_execute(self, sql, parameter_sets, transaction_id=None):
        self.batches.append((sql, list(parameter_sets), transaction_id))


def _identity(ext: str) -> UpsertIdentityCmd:
    return UpsertIdentityCmd(
        source="beatport",
        entity_type="artist",
        external_id=ext,
        clouder_entity_type="artist",
        clouder_id=f"new-{ext}",
        match_type="auto_create",
        confidence=Decimal("0.600"),
        observed_at=AT,
    )


def _track(track_id: str) -> CreateTrackCmd:
    return CreateTrackCmd(
        track_id=track_id,
        title="T",
        normalized_title="t",
        mix_name=None,
        isrc=None,
        bpm=None,
        length_ms=None,
        key_name=None,
        key_camelot=None,
        publish_date=None,
        album_id=None,
        style_id=None,
        at=AT,
    )


def test_find_identities_chunks_in_list_by_500() -> None:
    api = RecordingDataAPI()
    ids = [str(i) for i in range(1201)]

    found = ClouderRepository(api).find_identities("beatport", "artist", ids, transaction_id="tx")

    assert len(api.executes) == 3
    assert all(len(params) <= 502 for _, params, _ in api.executes)
    assert all(tx == "tx" for _, _, tx in api.executes)
    assert found == {ext: f"c-{ext}" for ext in ids}


def test_find_identities_dedups_and_skips_empty() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    assert repo.find_identities("beatport", "artist", []) == {}
    assert api.executes == []

    repo.find_identities("beatport", "artist", ["1", "1", "2"])
    _, params, _ = api.executes[0]
    assert sorted(v for k, v in params.items() if k.startswith("id")) == ["1", "2"]


def test_claim_identities_never_overwrites_existing_rows() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    repo.claim_identities([])
    assert api.batches == []

    repo.claim_identities([_identity("1"), _identity("2")], transaction_id="tx")
    sql, sets, tx = api.batches[0]
    assert "DO NOTHING" in sql and "DO UPDATE" not in sql
    assert len(sets) == 2 and tx == "tx"


def test_batch_writes_are_one_round_trip_each() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)
    named = [
        CreateNamedEntityCmd(entity_id=f"e{i}", name="N", normalized_name="n", at=AT)
        for i in range(3)
    ]

    repo.batch_create_labels(named, transaction_id="tx")
    repo.batch_create_styles(named, transaction_id="tx")
    repo.batch_create_artists(named, transaction_id="tx")
    repo.batch_create_albums(
        [
            CreateAlbumCmd(
                album_id="a1",
                title="A",
                normalized_title="a",
                release_date=date(2026, 9, 26),
                label_id=None,
                at=AT,
            )
        ],
        transaction_id="tx",
    )
    repo.batch_create_tracks([_track("t1"), _track("t2")], transaction_id="tx")
    repo.batch_conservative_update_tracks(
        [
            ConservativeUpdateTrackCmd(
                track_id="t1",
                mix_name=None,
                isrc=None,
                bpm=None,
                length_ms=None,
                key_name=None,
                key_camelot=None,
                publish_date=None,
                album_id=None,
                style_id=None,
                at=AT,
            )
        ],
        transaction_id="tx",
    )

    assert [len(sets) for _, sets, _ in api.batches] == [3, 3, 3, 1, 2, 1]
    assert {tx for _, _, tx in api.batches} == {"tx"}


def test_batch_writes_skip_empty_lists() -> None:
    api = RecordingDataAPI()
    repo = ClouderRepository(api)

    for method in (
        repo.batch_create_labels,
        repo.batch_create_styles,
        repo.batch_create_artists,
        repo.batch_create_albums,
        repo.batch_create_tracks,
        repo.batch_conservative_update_tracks,
    ):
        method([])

    assert api.batches == []

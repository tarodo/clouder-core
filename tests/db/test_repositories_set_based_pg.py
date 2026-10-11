"""Set-based repository SQL against a real Postgres."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from collector.repositories import (
    ClouderRepository,
    ConservativeUpdateTrackCmd,
    CreateTrackCmd,
    UpsertIdentityCmd,
)

AT = datetime(2026, 10, 7, tzinfo=UTC)


def _identity(ext: str, clouder_id: str) -> UpsertIdentityCmd:
    return UpsertIdentityCmd(
        source="beatport", entity_type="artist", external_id=ext,
        clouder_entity_type="artist", clouder_id=clouder_id,
        match_type="auto_create", confidence=Decimal("0.600"), observed_at=AT,
    )


def test_find_identities_resolves_more_than_one_chunk(pg) -> None:
    repo = ClouderRepository(pg)
    repo.claim_identities([_identity(str(i), f"c-{i}") for i in range(1201)])

    found = repo.find_identities("beatport", "artist", [str(i) for i in range(1201)])

    assert found == {str(i): f"c-{i}" for i in range(1201)}


def test_claim_keeps_the_existing_winner(pg) -> None:
    repo = ClouderRepository(pg)
    repo.claim_identities([_identity("1", "winner")])

    repo.claim_identities([_identity("1", "loser"), _identity("2", "fresh")])

    assert repo.find_identities("beatport", "artist", ["1", "2"]) == {"1": "winner", "2": "fresh"}


def test_claims_are_invisible_outside_their_transaction_until_commit(pg) -> None:
    repo = ClouderRepository(pg)
    with pg.transaction() as tx:
        repo.claim_identities([_identity("7", "c-7")], transaction_id=tx)
        assert repo.find_identities("beatport", "artist", ["7"], transaction_id=tx) == {"7": "c-7"}
        assert repo.find_identities("beatport", "artist", ["7"]) == {}
    assert repo.find_identities("beatport", "artist", ["7"]) == {"7": "c-7"}


def test_batch_conservative_update_keeps_existing_values_on_null(pg) -> None:
    repo = ClouderRepository(pg)
    base = dict(normalized_title="t", isrc=None, length_ms=None, key_camelot=None,
                publish_date=None, album_id=None, style_id=None, at=AT)
    repo.batch_create_tracks([
        CreateTrackCmd(track_id="t1", title="T1", mix_name="Original", bpm=120, key_name=None, **base),
        CreateTrackCmd(track_id="t2", title="T2", mix_name=None, bpm=None, key_name=None, **base),
    ])
    update = dict(isrc=None, length_ms=None, key_camelot=None, publish_date=None,
                  album_id=None, style_id=None, at=AT)

    repo.batch_conservative_update_tracks([
        ConservativeUpdateTrackCmd(track_id="t1", mix_name=None, bpm=None, key_name="1A", **update),
        ConservativeUpdateTrackCmd(track_id="t2", mix_name="Dub", bpm=128, key_name=None, **update),
    ])

    rows = {r["id"]: r for r in pg.execute("SELECT id, mix_name, bpm, key_name FROM clouder_tracks")}
    assert (rows["t1"]["mix_name"], rows["t1"]["bpm"], rows["t1"]["key_name"]) == ("Original", 120, "1A")
    assert (rows["t2"]["mix_name"], rows["t2"]["bpm"], rows["t2"]["key_name"]) == ("Dub", 128, None)

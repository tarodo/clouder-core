"""Race safety and rollback of canonicalization on a real Postgres."""

from __future__ import annotations

import os
import threading

import pytest
from pg_data_api import PgDataAPIClient, count_rows, seed_run
from synthetic import synthetic_week

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository


def test_concurrent_run_reuses_identity_claimed_first(pg) -> None:
    """Another run holds an uncommitted claim on one artist; this run must wait,
    then reuse that artist instead of creating a duplicate canonical row."""
    bundle = normalize_tracks(synthetic_week(50))
    artist = bundle.artists[0]
    ext = str(artist.bp_artist_id)
    seed_run(pg, "run-b")

    holder = PgDataAPIClient(os.environ["TEST_DATABASE_URL"])
    tx = holder.begin_transaction()
    holder.execute(
        """
        INSERT INTO identity_map (
            source, entity_type, external_id, clouder_entity_type, clouder_id,
            match_type, confidence, first_seen_at, last_seen_at
        ) VALUES ('beatport', 'artist', :ext, 'artist', 'winner-artist',
                  'auto_create', 0.6, now(), now())
        """,
        {"ext": ext},
        transaction_id=tx,
    )

    errors: list[BaseException] = []

    def run() -> None:
        try:
            Canonicalizer(ClouderRepository(pg)).process_run(run_id="run-b", bundle=bundle)
        except BaseException as exc:  # surfaced in the main thread below
            errors.append(exc)

    worker = threading.Thread(target=run)
    worker.start()
    worker.join(timeout=1)
    holder.execute(
        """
        INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)
        VALUES ('winner-artist', :name, :normalized_name, now(), now())
        """,
        {"name": artist.name, "normalized_name": artist.normalized_name},
        transaction_id=tx,
    )
    holder.commit_transaction(tx)
    worker.join(timeout=60)
    holder.close()

    assert not worker.is_alive()
    assert errors == []
    identity = pg.execute(
        "SELECT clouder_id FROM identity_map "
        "WHERE source = 'beatport' AND entity_type = 'artist' AND external_id = :ext",
        {"ext": ext},
    )
    assert identity[0]["clouder_id"] == "winner-artist"
    assert count_rows(pg, "clouder_artists") == len(bundle.artists)
    links = pg.execute(
        "SELECT count(*) AS n FROM clouder_track_artists WHERE artist_id = 'winner-artist'"
    )
    assert links[0]["n"] == sum(1 for t in bundle.tracks if artist.bp_artist_id in t.bp_artist_ids)


def test_failed_chunk_rolls_back_its_identity_claims(pg, monkeypatch) -> None:
    bundle = normalize_tracks(synthetic_week(250))  # two track chunks: 200 + 50
    seed_run(pg, "run-x")
    repo = ClouderRepository(pg)
    original = repo.batch_create_tracks
    calls = {"n": 0}

    def fail_second_chunk(commands, transaction_id=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        original(commands, transaction_id=transaction_id)

    monkeypatch.setattr(repo, "batch_create_tracks", fail_second_chunk)

    with pytest.raises(RuntimeError):
        Canonicalizer(repo).process_run(run_id="run-x", bundle=bundle)

    assert count_rows(pg, "clouder_tracks") == 200
    tracks_identities = pg.execute(
        "SELECT count(*) AS n FROM identity_map WHERE entity_type = 'track'"
    )
    assert tracks_identities[0]["n"] == 200

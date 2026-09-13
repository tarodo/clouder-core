"""Spotify raw results must not overwrite each other across follow-up batches.

`_enqueue_follow_up_if_needed` keeps the originating correlation_id for the
whole chain, so keying S3 objects on correlation_id alone meant every
follow-up batch clobbered the previous batch's results.
"""

from __future__ import annotations

from typing import Any

from collector.storage import S3Storage


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kwargs: Any) -> None:
        self.objects[kwargs["Key"]] = kwargs["Body"]


def _storage() -> tuple[S3Storage, FakeS3Client]:
    client = FakeS3Client()
    return (
        S3Storage(
            s3_client=client,
            bucket_name="test-bucket",
            raw_prefix="raw/bp/releases",
        ),
        client,
    )


def _meta(batch_id: str, searched_at: str = "2026-09-13T13:56:11Z") -> dict[str, Any]:
    return {
        "correlation_id": "cid-1",
        "batch_id": batch_id,
        "searched_at_utc": searched_at,
        "total_tracks": 2,
        "found": 1,
        "not_found": 1,
    }


def test_two_batches_of_one_chain_do_not_collide() -> None:
    storage, client = _storage()

    first_results, first_meta = storage.write_spotify_results(
        results=[{"isrc": "A", "clouder_track_id": "t1", "spotify_id": "s1"}],
        meta=_meta("batch-aaa"),
        spotify_prefix="raw/sp/tracks",
    )
    second_results, second_meta = storage.write_spotify_results(
        results=[{"isrc": "B", "clouder_track_id": "t2", "spotify_id": None}],
        meta=_meta("batch-bbb", searched_at="2026-09-13T13:57:09Z"),
        spotify_prefix="raw/sp/tracks",
    )

    assert first_results != second_results
    assert first_meta != second_meta
    # Both batches survive; the second no longer replaces the first.
    assert len(client.objects) == 4


def test_key_keeps_date_and_correlation_partitions() -> None:
    storage, _ = _storage()

    results_key, meta_key = storage.write_spotify_results(
        results=[],
        meta=_meta("batch-aaa"),
        spotify_prefix="raw/sp/tracks",
    )

    assert results_key.startswith("raw/sp/tracks/date=2026-09-13/cid-1/")
    assert results_key.endswith("/results.json.gz")
    assert meta_key.endswith("/meta.json")
    assert "batch-aaa" in results_key


def test_key_falls_back_to_timestamp_when_batch_id_missing() -> None:
    storage, _ = _storage()
    meta = _meta("ignored")
    del meta["batch_id"]

    results_key, _ = storage.write_spotify_results(
        results=[],
        meta=meta,
        spotify_prefix="raw/sp/tracks",
    )

    # Still unique per batch rather than collapsing onto the correlation_id.
    assert results_key != "raw/sp/tracks/date=2026-09-13/cid-1/results.json.gz"
    assert "20260913T135611Z" in results_key

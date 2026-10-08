"""Replays of stored runs on a real Postgres: event time decides, not processing order."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

from pg_data_api import seed_run, truncate_canonical
from synthetic import synthetic_week

from collector.canonicalize import Canonicalizer
from collector.normalize import normalize_tracks
from collector.repositories import ClouderRepository

T1 = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
T2 = T1 + timedelta(days=7)
MERGE_COLUMNS = "mix_name, isrc, bpm, length_ms, key_name, key_camelot, publish_date, album_id, style_id"


def _process(pg, run_id, raw, observed_at):
    seed_run(pg, run_id)
    return Canonicalizer(ClouderRepository(pg)).process_run(
        run_id=run_id, bundle=normalize_tracks(raw), observed_at=observed_at
    )


def _track(pg, external_id: int) -> dict:
    return pg.execute(
        f"""
        SELECT {MERGE_COLUMNS}, t.updated_at, se.payload, se.last_run_id
        FROM clouder_tracks t
        JOIN identity_map i ON i.clouder_id = t.id AND i.entity_type = 'track'
        JOIN source_entities se ON se.source = i.source AND se.entity_type = i.entity_type
                               AND se.external_id = i.external_id
        WHERE i.external_id = :ext
        """,
        {"ext": str(external_id)},
    )[0]


def _merge_snapshot(pg) -> list[tuple]:
    rows = pg.execute(
        f"""
        SELECT i.external_id, {MERGE_COLUMNS}
        FROM clouder_tracks t JOIN identity_map i ON i.clouder_id = t.id AND i.entity_type = 'track'
        ORDER BY i.external_id
        """
    )
    # album/style ids are fresh uuids per database; compare whether they are set
    return [
        tuple(bool(v) if k in ("album_id", "style_id") else v for k, v in row.items())
        for row in rows
    ]


def _weeks():
    old = synthetic_week(60)
    old[0]["bpm"] = 120
    new = copy.deepcopy(old)
    new[0]["bpm"] = 124
    new[1]["isrc"] = None  # newer observation lacks a value the older one had
    return old, new


def test_replaying_an_older_run_keeps_newer_values(pg) -> None:
    old, new = _weeks()
    _process(pg, "run-old", old, T1)
    _process(pg, "run-new", new, T2)

    result = _process(pg, "run-old", old, T1)

    track = _track(pg, 1)
    assert track["bpm"] == 124
    assert track["payload"]["bpm"] == 124
    assert track["last_run_id"] == "run-new"
    assert result.tracks_stale == len(old)
    assert result.tracks_changed == 0


def test_replaying_the_same_run_changes_nothing_and_keeps_updated_at(pg) -> None:
    raw = synthetic_week(60)
    _process(pg, "run-1", raw, T1)
    stamps = pg.execute("SELECT id, updated_at FROM clouder_tracks ORDER BY id")

    result = _process(pg, "run-1", raw, T1)

    assert pg.execute("SELECT id, updated_at FROM clouder_tracks ORDER BY id") == stamps
    assert (result.tracks_created, result.tracks_changed, result.tracks_stale) == (0, 0, 0)
    assert result.artists_created == result.albums_created == result.labels_created == 0


def test_same_run_replay_is_fresh_even_if_stamped_later(pg) -> None:
    raw = synthetic_week(60)
    _process(pg, "run-1", raw, T2)  # rows written before this change carry processing time
    raw[0]["bpm"] = 99  # e.g. a fixed normalizer now reads a different value

    result = _process(pg, "run-1", raw, T1)

    assert _track(pg, 1)["bpm"] == 99
    assert result.tracks_changed == 1
    assert dict(result.track_field_changes) == {"bpm": 1}


def test_out_of_order_replays_converge(pg) -> None:
    old, new = _weeks()
    _process(pg, "run-old", old, T1)
    _process(pg, "run-new", new, T2)
    in_order = _merge_snapshot(pg)

    truncate_canonical(pg)
    _process(pg, "run-new", new, T2)
    _process(pg, "run-old", old, T1)

    assert _merge_snapshot(pg) == in_order
    assert _track(pg, 1)["bpm"] == 124
    assert _track(pg, 2)["isrc"] == old[1]["isrc"]

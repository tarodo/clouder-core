"""Waveforms on real PostgreSQL: recording them, the player's read, a re-match."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from collector.repositories import ClouderRepository, UpsertVendorMatchCmd

T0 = datetime(2026, 10, 29, 22, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)
L1 = "11111111-1111-1111-1111-111111111111"


def _track(pg, tid: str, video: str, spotify_ms: int | None = 322_000) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " spotify_id, created_at, updated_at)"
        " VALUES (:id, :id, :id, 'st', 322000, :sid, :c, :c)",
        {"id": tid, "sid": f"sp_{tid}", "c": T0},
    )
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES (:id, 'ytmusic', :v, 'fuzzy', 0.950, now(),"
        " CAST('{}' AS jsonb))",
        {"id": tid, "v": video},
    )
    if spotify_ms is not None:
        pg.execute(
            "INSERT INTO source_entities (source, entity_type, external_id, payload,"
            " payload_hash, first_seen_at, last_seen_at)"
            " VALUES ('spotify', 'track', :sid, :payload, 'h', now(), now())",
            {"sid": f"sp_{tid}", "payload": {"duration_ms": spotify_ms}},
        )


@pytest.fixture
def repo(pg):
    pg.execute("TRUNCATE audio_waveforms")
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())"
    )
    _track(pg, "a", "vid_a")
    _track(pg, "b", "vid_a", spotify_ms=325_500)  # 3.5 s off: another edit
    _track(pg, "c", "vid_c", spotify_ms=None)  # no Spotify payload
    _track(pg, "d", "vid_d", spotify_ms=319_000)  # exactly 3 s off
    yield ClouderRepository(pg)
    pg.execute("TRUNCATE audio_waveforms")


def _wave(video: str, sha: str = "a" * 64, data: str = "AAAA", ms: int = 322_000) -> dict:
    return {
        "video_id": video,
        "version": "wave-1",
        "audio_sha256": sha,
        "duration_ms": ms,
        "data_b64": data,
    }


def _row(pg, track_id: str) -> dict | None:
    rows = pg.execute(
        "SELECT status, version, video_id, audio_sha256 FROM track_analyses"
        " WHERE track_id = :t AND analyzer = 'waveform'",
        {"t": track_id},
    )
    return rows[0] if rows else None


def test_record_marks_every_track_on_the_video(pg, repo) -> None:
    assert repo.record_audio_waveforms(items=[_wave("vid_a")], now=T0) == 2
    for track in ("a", "b"):
        assert _row(pg, track) == {
            "status": "ok",
            "version": "wave-1",
            "video_id": "vid_a",
            "audio_sha256": "a" * 64,
        }
    assert _row(pg, "c") is None


def test_record_overrides_a_lease(pg, repo) -> None:
    repo.claim_analysis(limit=10, analyzers=["waveform"], lease_id=L1, now=T0)
    assert _row(pg, "a")["status"] == "leased"
    repo.record_audio_waveforms(items=[_wave("vid_a")], now=T0)
    assert _row(pg, "a")["status"] == "ok"


def test_record_same_sha_keeps_the_stored_waveform(pg, repo) -> None:
    repo.record_audio_waveforms(items=[_wave("vid_a", data="AAAA")], now=T0)
    repo.record_audio_waveforms(items=[_wave("vid_a", data="BBBB")], now=T1)
    assert repo.track_waveform(track_id="a")["data"] == "AAAA"
    repo.record_audio_waveforms(items=[_wave("vid_a", "b" * 64, data="CCCC")], now=T1)
    assert repo.track_waveform(track_id="a")["data"] == "CCCC"
    assert _row(pg, "a")["audio_sha256"] == "b" * 64


def test_track_waveform_needs_a_spotify_track_of_the_same_length(pg, repo) -> None:
    repo.record_audio_waveforms(items=[_wave("vid_a"), _wave("vid_c"), _wave("vid_d")], now=T0)
    assert repo.track_waveform(track_id="a") == {"duration_ms": 322_000, "data": "AAAA"}
    assert repo.track_waveform(track_id="d") == {"duration_ms": 322_000, "data": "AAAA"}
    assert repo.track_waveform(track_id="b") is None  # 3.5 s apart
    assert repo.track_waveform(track_id="c") is None  # nothing to compare with


def test_track_waveform_without_one_is_none(pg, repo) -> None:
    assert repo.track_waveform(track_id="a") is None
    assert repo.track_waveform(track_id="missing") is None


def _rematch(repo, track_id: str, video: str) -> None:
    repo.upsert_vendor_match(
        UpsertVendorMatchCmd(
            clouder_track_id=track_id,
            vendor="ytmusic",
            vendor_track_id=video,
            match_type="manual",
            confidence=Decimal("1.000"),
            matched_at=T1,
            payload={},
        )
    )


def test_rematch_moves_the_waveform_with_the_video(pg, repo) -> None:
    repo.record_audio_waveforms(items=[_wave("vid_a"), _wave("vid_d", "d" * 64)], now=T0)
    _rematch(repo, "a", "vid_new")
    assert _row(pg, "a") is None
    assert repo.track_waveform(track_id="a") is None
    _rematch(repo, "a", "vid_d")
    assert _row(pg, "a")["audio_sha256"] == "d" * 64
    assert repo.track_waveform(track_id="a") == {"duration_ms": 322_000, "data": "AAAA"}

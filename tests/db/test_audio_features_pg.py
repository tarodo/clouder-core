"""Feature store on real PostgreSQL: recording profiles, and a profile following a re-match."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from collector.repositories import ClouderRepository, UpsertVendorMatchCmd

T0 = datetime(2026, 10, 23, 3, tzinfo=UTC)
L1 = "11111111-1111-1111-1111-111111111111"


def _track(pg, tid: str, video: str) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " created_at, updated_at) VALUES (:id, :id, :id, 'st', 200000, :c, :c)",
        {"id": tid, "c": T0},
    )
    pg.execute(
        "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
        " confidence, matched_at, payload) VALUES (:id, 'ytmusic', :v, 'fuzzy', 0.950, now(),"
        " CAST('{}' AS jsonb))",
        {"id": tid, "v": video},
    )


@pytest.fixture
def repo(pg):
    pg.execute("TRUNCATE audio_features")
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())"
    )
    _track(pg, "a", "vid_a")
    _track(pg, "b", "vid_a")
    _track(pg, "c", "vid_c")
    yield ClouderRepository(pg)
    pg.execute("TRUNCATE audio_features")


def _features(video: str, sha: str = "a" * 64) -> dict:
    return {"video_id": video, "version": "light-1", "audio_sha256": sha}


def _row(pg, track_id: str) -> dict | None:
    rows = pg.execute(
        "SELECT status, version, video_id, audio_sha256, lease_id FROM track_analyses"
        " WHERE track_id = :t AND analyzer = 'light_profile'",
        {"t": track_id},
    )
    return rows[0] if rows else None


def _rematch(repo, track_id: str, video: str) -> None:
    repo.upsert_vendor_match(
        UpsertVendorMatchCmd(
            clouder_track_id=track_id,
            vendor="ytmusic",
            vendor_track_id=video,
            match_type="manual",
            confidence=Decimal("1.000"),
            matched_at=T0,
            payload={},
        )
    )


def test_record_marks_every_track_on_video(pg, repo) -> None:
    repo.claim_analysis(limit=10, analyzers=["light_profile"], lease_id=L1, now=T0)
    assert _row(pg, "a")["status"] == "leased"

    assert repo.record_audio_features(items=[_features("vid_a")], now=T0) == 2

    for track in ("a", "b"):
        assert _row(pg, track) == {
            "status": "ok",
            "version": "light-1",
            "video_id": "vid_a",
            "audio_sha256": "a" * 64,
            "lease_id": None,
        }
    assert _row(pg, "c")["status"] == "leased"
    assert repo.known_audio_features(video_ids=["vid_a", "vid_c"]) == {
        "vid_a": ("light-1", "a" * 64)
    }


def test_record_same_profile_again_is_idempotent(pg, repo) -> None:
    repo.record_audio_features(items=[_features("vid_a")], now=T0)
    assert repo.record_audio_features(items=[_features("vid_a", "b" * 64)], now=T0) == 2
    assert repo.known_audio_features(video_ids=["vid_a"]) == {"vid_a": ("light-1", "b" * 64)}
    assert _row(pg, "a")["audio_sha256"] == "b" * 64


def test_rematch_deletes_stale_light_profile(pg, repo) -> None:
    repo.record_audio_features(items=[_features("vid_a")], now=T0)
    _rematch(repo, "a", "vid_new")
    assert _row(pg, "a") is None
    assert _row(pg, "b")["status"] == "ok"


def test_rematch_to_profiled_video_sets_ok(pg, repo) -> None:
    repo.record_audio_features(items=[_features("vid_a"), _features("vid_c", "c" * 64)], now=T0)
    _rematch(repo, "a", "vid_c")
    assert _row(pg, "a") == {
        "status": "ok",
        "version": "light-1",
        "video_id": "vid_c",
        "audio_sha256": "c" * 64,
        "lease_id": None,
    }


def test_rematch_same_video_keeps_row(pg, repo) -> None:
    repo.record_audio_features(items=[_features("vid_a")], now=T0)
    _rematch(repo, "a", "vid_a")
    assert _row(pg, "a")["status"] == "ok"
    assert _row(pg, "a")["video_id"] == "vid_a"

"""Audio analysis state on real PostgreSQL: claims with leases, results, status, requeue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from collector.repositories import ClouderRepository
from collector.user_deletion import delete_user

T0 = datetime(2026, 10, 16, 3, tzinfo=UTC)
L1 = "11111111-1111-1111-1111-111111111111"
L2 = "22222222-2222-2222-2222-222222222222"


def _track(pg, tid: str, created: datetime, *, ytmusic: str | None = None) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, length_ms,"
        " created_at, updated_at) VALUES (:id, :id, :id, 'st', 200000, :c, :c)",
        {"id": tid, "c": created},
    )
    if ytmusic:
        pg.execute(
            "INSERT INTO vendor_track_map (clouder_track_id, vendor, vendor_track_id, match_type,"
            " confidence, matched_at, payload) VALUES (:id, 'ytmusic', :v, 'fuzzy', 0.950, now(),"
            " CAST('{}' AS jsonb))",
            {"id": tid, "v": ytmusic},
        )


@pytest.fixture
def repo(pg):
    pg.execute("TRUNCATE analysis_service_state")
    pg.execute(
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())"
    )
    _track(pg, "old", T0 - timedelta(days=3), ytmusic="vid_old")
    _track(pg, "mid", T0 - timedelta(days=2), ytmusic="vid_mid")
    _track(pg, "new", T0 - timedelta(days=1), ytmusic="vid_new")
    _track(pg, "no-yt", T0, ytmusic=None)
    yield ClouderRepository(pg)
    delete_user(pg, "u1")


def _ok(track_id: str, *, ai: bool = False, analyzer: str = "ai_detect") -> dict:
    return {
        "track_id": track_id,
        "analyzer": analyzer,
        "version": "v1",
        "status": "ok",
        "result": {"ai_detected": ai, "score": 0.9 if ai else 0.01},
        "error": None,
        "audio_sha256": "a" * 64,
        "video_id": f"vid_{track_id}",
    }


def _status(pg, track_id: str, analyzer: str = "ai_detect") -> str | None:
    rows = pg.execute(
        "SELECT status FROM track_analyses WHERE track_id = :t AND analyzer = :a",
        {"t": track_id, "a": analyzer},
    )
    return rows[0]["status"] if rows else None


def test_claim_leases_ytmusic_tracks_newest_first_within_limit(repo) -> None:
    rows = repo.claim_analysis(limit=2, analyzers=["ai_detect"], lease_id=L1, now=T0)
    assert [r["track_id"] for r in rows] == ["new", "mid"]
    assert rows[0] == {
        "track_id": "new",
        "video_id": "vid_new",
        "length_ms": 200000,
        "analyzers": ["ai_detect"],
    }


def test_claim_skips_tracks_without_ytmusic_match(repo) -> None:
    rows = repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L1, now=T0)
    assert {r["track_id"] for r in rows} == {"old", "mid", "new"}


def test_live_lease_blocks_a_second_claim_until_it_expires(repo) -> None:
    repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L1, now=T0)
    assert repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L2, now=T0) == []
    later = T0 + timedelta(minutes=31)
    again = repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L2, now=later)
    assert {r["track_id"] for r in again} == {"old", "mid", "new"}


def test_claim_returns_only_the_missing_analyzers(repo) -> None:
    repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L1, now=T0)
    repo.record_analysis_results(lease_id=L1, items=[_ok("new")], now=T0)
    rows = repo.claim_analysis(
        limit=10, analyzers=["ai_detect", "embed"], lease_id=L2, now=T0 + timedelta(hours=1)
    )
    by_id = {r["track_id"]: r["analyzers"] for r in rows}
    assert by_id["new"] == ["embed"]
    assert by_id["old"] == ["ai_detect", "embed"]


def test_failed_is_never_claimed_again(repo) -> None:
    repo.claim_analysis(limit=1, analyzers=["ai_detect"], lease_id=L1, now=T0)
    failed = {**_ok("new"), "status": "failed", "result": None, "error": "Video unavailable"}
    assert repo.record_analysis_results(lease_id=L1, items=[failed], now=T0) == []
    rows = repo.claim_analysis(
        limit=10, analyzers=["ai_detect"], lease_id=L2, now=T0 + timedelta(days=1)
    )
    assert "new" not in {r["track_id"] for r in rows}


def test_results_store_the_leased_row(repo, pg) -> None:
    repo.claim_analysis(limit=1, analyzers=["ai_detect"], lease_id=L1, now=T0)
    assert repo.record_analysis_results(lease_id=L1, items=[_ok("new", ai=True)], now=T0) == []
    row = pg.execute("SELECT * FROM track_analyses WHERE track_id = 'new'")[0]
    assert row["status"] == "ok"
    assert row["version"] == "v1"
    assert row["result"] == {"ai_detected": True, "score": 0.9}
    assert row["audio_sha256"] == "a" * 64
    assert row["video_id"] == "vid_new"
    assert row["lease_id"] is None and row["leased_until"] is None
    assert row["analyzed_at"] is not None


def test_result_under_a_lost_lease_is_rejected_and_the_new_lease_kept(repo, pg) -> None:
    repo.claim_analysis(limit=1, analyzers=["ai_detect"], lease_id=L1, now=T0)
    repo.claim_analysis(
        limit=1, analyzers=["ai_detect"], lease_id=L2, now=T0 + timedelta(minutes=31)
    )
    rejected = repo.record_analysis_results(lease_id=L1, items=[_ok("new")], now=T0)
    assert rejected == [{"track_id": "new", "analyzer": "ai_detect", "reason": "lease_lost"}]
    row = pg.execute("SELECT status, CAST(lease_id AS text) AS l FROM track_analyses")[0]
    assert (row["status"], row["l"]) == ("leased", L2)


def test_status_counts_and_heartbeat(repo) -> None:
    repo.claim_analysis(limit=3, analyzers=["ai_detect"], lease_id=L1, now=T0)
    failed = {**_ok("old"), "status": "failed", "result": None, "error": "gone"}
    repo.record_analysis_results(
        lease_id=L1, items=[_ok("new", ai=True), _ok("mid"), failed], now=T0
    )
    status = repo.analysis_status(now=T0)
    assert status["last_claim_at"] == T0
    assert status["last_result_at"] == T0
    assert status["analyzers"] == [
        {
            "name": "ai_detect",
            "due": 0,
            "leased": 0,
            "ok": 2,
            "ai_detected": 1,
            "failed": 1,
            "unusable_source": 0,
        }
    ]
    # an ai_detect flag is no part of the AI level
    assert status["pair"] == {"high": 0, "medium": 0, "low": 0}


@pytest.mark.parametrize("analyzer", ["ai_lofcz", "ai_deezer"])
def test_status_counts_ai_detected_for_pair_analyzers(repo, analyzer) -> None:
    repo.claim_analysis(limit=2, analyzers=[analyzer], lease_id=L1, now=T0)
    repo.record_analysis_results(
        lease_id=L1,
        items=[_ok("new", ai=True, analyzer=analyzer), _ok("mid", analyzer=analyzer)],
        now=T0,
    )
    (ai,) = repo.analysis_status(now=T0)["analyzers"]
    assert (ai["name"], ai["ok"], ai["ai_detected"]) == (analyzer, 2, 1)


def test_status_counts_tracks_per_ai_level(repo, pg) -> None:
    _track(pg, "none", T0 - timedelta(days=4), ytmusic="vid_none")
    repo.claim_analysis(limit=4, analyzers=["ai_deezer", "ai_lofcz"], lease_id=L1, now=T0)
    items = [
        _ok("new", ai=True, analyzer="ai_lofcz"),
        _ok("new", ai=True, analyzer="ai_deezer"),
        _ok("mid", analyzer="ai_lofcz"),
        _ok("mid", ai=True, analyzer="ai_deezer"),
        _ok("old", ai=True, analyzer="ai_lofcz"),
        _ok("old", analyzer="ai_deezer"),
        _ok("none", analyzer="ai_lofcz"),
        _ok("none", analyzer="ai_deezer"),
    ]
    repo.record_analysis_results(lease_id=L1, items=items, now=T0)
    assert repo.analysis_status(now=T0)["pair"] == {"high": 1, "medium": 1, "low": 1}


def test_status_counts_due_and_expired_leases(repo) -> None:
    repo.claim_analysis(limit=1, analyzers=["ai_detect"], lease_id=L1, now=T0)
    (ai,) = repo.analysis_status(now=T0)["analyzers"]
    assert (ai["due"], ai["leased"]) == (2, 1)
    (ai,) = repo.analysis_status(now=T0 + timedelta(minutes=31))["analyzers"]
    assert (ai["due"], ai["leased"]) == (3, 0)


def test_status_before_any_claim(repo) -> None:
    status = repo.analysis_status(now=T0)
    assert status == {
        "last_claim_at": None,
        "last_result_at": None,
        "analyzers": [],
        "pair": {"high": 0, "medium": 0, "low": 0},
    }


def _finish_all(repo) -> None:
    repo.claim_analysis(limit=10, analyzers=["ai_detect"], lease_id=L1, now=T0)
    failed = {**_ok("old"), "status": "failed", "result": None, "error": "gone"}
    unusable = {**_ok("mid"), "status": "unusable_source", "result": None, "error": "no 251"}
    repo.record_analysis_results(lease_id=L1, items=[_ok("new"), unusable, failed], now=T0)


def test_requeue_all_keeps_failed_and_live_leases(repo, pg) -> None:
    _finish_all(repo)
    _track(pg, "fresh", T0, ytmusic="vid_fresh")
    repo.claim_analysis(limit=1, analyzers=["ai_detect"], lease_id=L2, now=T0)
    n = repo.requeue_analysis(
        analyzer="ai_detect", scope="all", days=None, include_failed=False, now=T0
    )
    assert n == 2
    assert _status(pg, "new") is None and _status(pg, "mid") is None
    assert _status(pg, "old") == "failed"
    assert _status(pg, "fresh") == "leased"


def test_requeue_with_failed(repo, pg) -> None:
    _finish_all(repo)
    n = repo.requeue_analysis(
        analyzer="ai_detect", scope="all", days=None, include_failed=True, now=T0
    )
    assert n == 3
    assert _status(pg, "old") is None


def test_requeue_recent_scope(repo, pg) -> None:
    _finish_all(repo)
    n = repo.requeue_analysis(
        analyzer="ai_detect", scope="recent", days=1, include_failed=True, now=T0
    )
    assert n == 1  # only "new" was created within the last day
    assert _status(pg, "new") is None and _status(pg, "mid") == "unusable_source"


def test_requeue_categories_scope(repo, pg) -> None:
    _finish_all(repo)
    pg.execute(
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())"
    )
    pg.execute(
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())"
    )
    pg.execute(
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES ('cat', 'mid', now())"
    )
    n = repo.requeue_analysis(
        analyzer="ai_detect", scope="categories", days=None, include_failed=False, now=T0
    )
    assert n == 1
    assert _status(pg, "mid") is None and _status(pg, "new") == "ok"

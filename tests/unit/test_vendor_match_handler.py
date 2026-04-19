"""vendor_match_handler unit tests (Plan 4 Task 7)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from collector import vendor_match_handler
from collector.errors import VendorDisabledError
from collector.providers.base import VendorTrackRef
from collector.repositories import UpsertVendorMatchCmd, VendorTrackMatch
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    reset_settings_cache()
    yield
    reset_settings_cache()


class FakeRepo:
    def __init__(self, cache: dict[tuple[str, str], VendorTrackMatch] | None = None) -> None:
        self._cache: dict[tuple[str, str], VendorTrackMatch] = cache or {}
        self.upserts: list[UpsertVendorMatchCmd] = []
        self.reviews: list[dict[str, Any]] = []

    def get_vendor_match(
        self, clouder_track_id: str, vendor: str, transaction_id: str | None = None
    ) -> VendorTrackMatch | None:
        return self._cache.get((clouder_track_id, vendor))

    def upsert_vendor_match(
        self, cmd: UpsertVendorMatchCmd, transaction_id: str | None = None
    ) -> None:
        self.upserts.append(cmd)

    def insert_review_candidate(
        self,
        *,
        review_id: str,
        clouder_track_id: str,
        vendor: str,
        candidates: list[dict[str, Any]],
        created_at: datetime,
        transaction_id: str | None = None,
    ) -> None:
        self.reviews.append(
            {
                "review_id": review_id,
                "clouder_track_id": clouder_track_id,
                "vendor": vendor,
                "candidates": candidates,
                "created_at": created_at,
            }
        )


class FakeLookup:
    vendor_name = "spotify"

    def __init__(
        self,
        by_isrc: VendorTrackRef | None = None,
        by_metadata: list[VendorTrackRef] | None = None,
    ) -> None:
        self._isrc = by_isrc
        self._metadata = by_metadata or []
        self.isrc_calls = 0
        self.metadata_calls = 0

    def lookup_batch_by_isrc(self, tracks: list[dict[str, str]], correlation_id: str):
        return []

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        self.isrc_calls += 1
        return self._isrc

    def lookup_by_metadata(
        self,
        artist: str,
        title: str,
        duration_ms: int | None,
        album: str | None,
    ) -> list[VendorTrackRef]:
        self.metadata_calls += 1
        return self._metadata


def _event(body_payload: dict[str, Any]) -> dict[str, Any]:
    return {"Records": [{"body": json.dumps(body_payload)}]}


def _base_message() -> dict[str, Any]:
    return {
        "clouder_track_id": "track-1",
        "vendor": "spotify",
        "isrc": "US1234567890",
        "artist": "Foo",
        "title": "Bar",
        "duration_ms": 200_000,
        "album": "Baz",
    }


def _spotify_ref(**overrides) -> VendorTrackRef:
    base = dict(
        vendor="spotify",
        vendor_track_id="sp123",
        isrc="US1234567890",
        artist_names=("Foo",),
        title="Bar",
        duration_ms=200_000,
        album_name="Baz",
        raw_payload={"id": "sp123"},
    )
    base.update(overrides)
    return VendorTrackRef(**base)


def test_cache_hit_skips_lookup(monkeypatch) -> None:
    cached = VendorTrackMatch(
        clouder_track_id="track-1", vendor="spotify", vendor_track_id="sp123",
        match_type="isrc", confidence=Decimal("1.000"),
        matched_at=datetime.now(timezone.utc), payload={},
    )
    repo = FakeRepo(cache={("track-1", "spotify"): cached})
    lookup = FakeLookup()

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry, "get_lookup", lambda name: lookup
    )

    result = vendor_match_handler.lambda_handler(_event(_base_message()), None)

    assert result == {"processed": 1}
    assert repo.upserts == []
    assert repo.reviews == []
    assert lookup.isrc_calls == 0


def test_isrc_match_writes_cache(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=_spotify_ref())

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry, "get_lookup", lambda name: lookup
    )

    vendor_match_handler.lambda_handler(_event(_base_message()), None)

    assert lookup.isrc_calls == 1
    assert lookup.metadata_calls == 0
    assert len(repo.upserts) == 1
    cmd = repo.upserts[0]
    assert cmd.match_type == "isrc"
    assert cmd.confidence == Decimal("1.000")
    assert cmd.vendor_track_id == "sp123"


def test_fuzzy_high_match_writes_cache(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=None, by_metadata=[_spotify_ref()])

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry, "get_lookup", lambda name: lookup
    )

    payload = _base_message()
    payload["isrc"] = None
    vendor_match_handler.lambda_handler(_event(payload), None)

    assert len(repo.upserts) == 1
    assert repo.upserts[0].match_type == "fuzzy"
    assert repo.upserts[0].confidence >= Decimal("0.92")
    assert repo.reviews == []


def test_low_confidence_routes_to_review(monkeypatch) -> None:
    repo = FakeRepo()
    weak = _spotify_ref(
        title="Completely Different Song",
        artist_names=("Nobody",),
        duration_ms=500_000,
        album_name="Other",
        vendor_track_id="sp999",
        raw_payload={"id": "sp999"},
    )
    lookup = FakeLookup(by_isrc=None, by_metadata=[weak])

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry, "get_lookup", lambda name: lookup
    )

    payload = _base_message()
    payload["isrc"] = None
    vendor_match_handler.lambda_handler(_event(payload), None)

    assert repo.upserts == []
    assert len(repo.reviews) == 1
    assert len(repo.reviews[0]["candidates"]) == 1


def test_vendor_disabled_skips(monkeypatch) -> None:
    repo = FakeRepo()

    def _raise(name: str):
        raise VendorDisabledError(name, reason="disabled")

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(vendor_match_handler.registry, "get_lookup", _raise)

    result = vendor_match_handler.lambda_handler(_event(_base_message()), None)

    assert result == {"processed": 0}
    assert repo.upserts == []
    assert repo.reviews == []


def test_no_candidates_does_not_write_review(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=None, by_metadata=[])

    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry, "get_lookup", lambda name: lookup
    )

    payload = _base_message()
    payload["isrc"] = None
    vendor_match_handler.lambda_handler(_event(payload), None)

    assert repo.upserts == []
    assert repo.reviews == []


def test_invalid_body_skipped(monkeypatch) -> None:
    repo = FakeRepo()
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )
    monkeypatch.setattr(
        vendor_match_handler.registry,
        "get_lookup",
        lambda name: pytest.fail("lookup must not be called"),
    )

    event = {"Records": [{"body": "not-json"}]}
    result = vendor_match_handler.lambda_handler(event, None)

    assert result == {"processed": 0}


def test_repo_missing_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: None
    )
    with pytest.raises(RuntimeError):
        vendor_match_handler.lambda_handler(_event(_base_message()), None)

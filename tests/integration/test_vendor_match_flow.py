"""End-to-end vendor_match_worker flow — fake providers + fake repository.

Covers all 6 plan scenarios:
 1. ISRC cache hit.
 2. Fuzzy match ≥ threshold → cache.
 3. Low confidence → review queue.
 4. Cache-hit skip on second invocation.
 5. VendorDisabledError → skip.
 6. No candidates → no review row.

Exercises the registry + VENDORS_ENABLED path to verify real wiring.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest

from collector import vendor_match_handler
from collector.providers import registry
from collector.providers.base import VendorTrackRef
from collector.repositories import UpsertVendorMatchCmd, VendorTrackMatch
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def _clear_all_caches(monkeypatch) -> None:
    reset_settings_cache()
    registry.reset_cache()
    yield
    registry.reset_cache()
    reset_settings_cache()


class FakeRepo:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], VendorTrackMatch] = {}
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
        self._cache[(cmd.clouder_track_id, cmd.vendor)] = VendorTrackMatch(
            clouder_track_id=cmd.clouder_track_id,
            vendor=cmd.vendor,
            vendor_track_id=cmd.vendor_track_id,
            match_type=cmd.match_type,
            confidence=cmd.confidence,
            matched_at=cmd.matched_at,
            payload=dict(cmd.payload),
        )

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

    def lookup_batch_by_isrc(self, tracks, correlation_id):
        return []

    def lookup_by_isrc(self, isrc: str) -> VendorTrackRef | None:
        self.isrc_calls += 1
        return self._isrc

    def lookup_by_metadata(
        self, artist, title, duration_ms, album
    ) -> list[VendorTrackRef]:
        self.metadata_calls += 1
        return self._metadata


def _install_fake_spotify(monkeypatch, lookup: FakeLookup) -> None:
    from collector.providers.base import ProviderBundle

    monkeypatch.setenv("VENDORS_ENABLED", "spotify")
    registry.reset_cache()
    monkeypatch.setitem(
        registry._BUILDERS, "spotify", lambda: ProviderBundle(lookup=lookup)
    )


def _ref(**overrides) -> VendorTrackRef:
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


def _event(**overrides) -> dict[str, Any]:
    body = {
        "clouder_track_id": "track-1",
        "vendor": "spotify",
        "isrc": "US1234567890",
        "artist": "Foo",
        "title": "Bar",
        "duration_ms": 200_000,
        "album": "Baz",
    }
    body.update(overrides)
    return {"Records": [{"body": json.dumps(body)}]}


def test_scenario_isrc_cache_hit(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=_ref())
    _install_fake_spotify(monkeypatch, lookup)
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    vendor_match_handler.lambda_handler(_event(), None)

    assert len(repo.upserts) == 1
    assert repo.upserts[0].match_type == "isrc"
    assert repo.upserts[0].confidence == Decimal("1.000")


def test_scenario_fuzzy_match_writes_cache(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=None, by_metadata=[_ref()])
    _install_fake_spotify(monkeypatch, lookup)
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    vendor_match_handler.lambda_handler(_event(isrc=None), None)

    assert len(repo.upserts) == 1
    assert repo.upserts[0].match_type == "fuzzy"
    assert repo.upserts[0].confidence >= Decimal("0.92")


def test_scenario_low_confidence_routes_to_review(monkeypatch) -> None:
    repo = FakeRepo()
    bad = _ref(
        title="Completely Different",
        artist_names=("Nobody",),
        duration_ms=500_000,
        album_name="Other",
        raw_payload={"id": "sp999"},
    )
    lookup = FakeLookup(by_isrc=None, by_metadata=[bad])
    _install_fake_spotify(monkeypatch, lookup)
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    vendor_match_handler.lambda_handler(_event(isrc=None), None)

    assert repo.upserts == []
    assert len(repo.reviews) == 1
    assert len(repo.reviews[0]["candidates"]) == 1


def test_scenario_second_call_is_cache_hit(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=_ref())
    _install_fake_spotify(monkeypatch, lookup)
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    vendor_match_handler.lambda_handler(_event(), None)
    vendor_match_handler.lambda_handler(_event(), None)

    assert lookup.isrc_calls == 1
    assert len(repo.upserts) == 1


def test_scenario_vendor_disabled_skips(monkeypatch) -> None:
    repo = FakeRepo()
    monkeypatch.setenv("VENDORS_ENABLED", "")
    registry.reset_cache()
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    result = vendor_match_handler.lambda_handler(_event(), None)

    assert result == {"processed": 0}
    assert repo.upserts == []
    assert repo.reviews == []


def test_scenario_no_candidates(monkeypatch) -> None:
    repo = FakeRepo()
    lookup = FakeLookup(by_isrc=None, by_metadata=[])
    _install_fake_spotify(monkeypatch, lookup)
    monkeypatch.setattr(
        vendor_match_handler, "create_clouder_repository_from_env", lambda: repo
    )

    vendor_match_handler.lambda_handler(_event(isrc=None), None)

    assert repo.upserts == []
    assert repo.reviews == []

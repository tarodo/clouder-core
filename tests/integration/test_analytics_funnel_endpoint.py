"""Integration tests for GET /v1/analytics/funnel (personal; admins may pick a user)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from collector import handler
from collector.providers import registry
from collector.repositories import ClouderRepository
from collector.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    reset_settings_cache()
    registry.reset_cache()
    monkeypatch.setenv("VENDORS_ENABLED", "beatport")
    yield
    reset_settings_cache()
    registry.reset_cache()


def _event(*, is_admin: bool = True, qs=None):
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "req",
            "routeKey": "GET /v1/analytics/funnel",
            "authorizer": {"lambda": {"is_admin": is_admin, "user_id": "me"}},
        },
        "rawPath": "/v1/analytics/funnel",
        "queryStringParameters": qs,
        "headers": {"x-correlation-id": "c"},
        "body": None,
    }


def _ctx():
    return type("C", (), {"aws_request_id": "x"})()


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def analytics_funnel(self, user_id, **windows):
        self.calls.append((user_id, windows))
        return self.rows


def test_funnel_non_admin_reads_own(monkeypatch):
    repo = FakeRepo([])
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    response = handler.lambda_handler(_event(is_admin=False), _ctx())
    assert response["statusCode"] == 200
    assert repo.calls[0][0] == "me"


def test_funnel_non_admin_cannot_read_another_user(monkeypatch):
    repo = FakeRepo([])
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    response = handler.lambda_handler(_event(is_admin=False, qs={"user_id": "other"}), _ctx())
    assert response["statusCode"] == 403
    assert repo.calls == []


def test_funnel_admin_reads_any_user(monkeypatch):
    repo = FakeRepo([])
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    response = handler.lambda_handler(_event(qs={"user_id": "other"}), _ctx())
    assert response["statusCode"] == 200
    assert repo.calls[0][0] == "other"


def test_funnel_rejects_bad_offset(monkeypatch):
    monkeypatch.setattr(
        "collector.api.deps.create_clouder_repository_from_env", lambda: FakeRepo([])
    )
    response = handler.lambda_handler(_event(qs={"tz_offset_min": "abc"}), _ctx())
    assert response["statusCode"] == 400


def test_funnel_returns_ordered_zero_filled_stages(monkeypatch):
    repo = FakeRepo(
        [
            {"stage": "playlisted", "day": 0, "week": 2, "month": 10},
            {"stage": "triaged", "day": 120, "week": 500, "month": 1000},
        ]
    )
    monkeypatch.setattr("collector.api.deps.create_clouder_repository_from_env", lambda: repo)
    monkeypatch.setattr(
        "collector.api.deps.utc_now",
        lambda: datetime(2026, 10, 5, 22, 30, tzinfo=UTC),
    )
    response = handler.lambda_handler(_event(qs={"tz_offset_min": "180"}), _ctx())
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["today"] == "2026-10-06"
    assert body["stages"] == [
        {"stage": "triaged", "day": 120, "week": 500, "month": 1000},
        {"stage": "categorized", "day": 0, "week": 0, "month": 0},
        {"stage": "playlisted", "day": 0, "week": 2, "month": 10},
    ]
    user_id, w = repo.calls[0]
    assert user_id == "me"  # defaults to the caller
    # local midnight of 2026-10-06 at +03:00 == 2026-10-05T21:00Z
    assert w["day_start"] == datetime(2026, 10, 5, 21, 0, tzinfo=UTC)
    assert w["week_start"] == datetime(2026, 9, 29, 21, 0, tzinfo=UTC)
    assert w["month_start"] == datetime(2026, 9, 6, 21, 0, tzinfo=UTC)


def test_repository_funnel_sql_binds_user_and_windows():
    fake = MagicMock()
    fake.execute.return_value = []
    repo = ClouderRepository(data_api=fake)
    d = datetime(2026, 10, 5, 21, tzinfo=UTC)
    repo.analytics_funnel("me", day_start=d, week_start=d, month_start=d)
    sql, params = fake.execute.call_args[0]
    assert params == {"user_id": "me", "day_start": d, "week_start": d, "month_start": d}
    assert "count(DISTINCT track_id) FILTER (WHERE at >= :day_start)" in sql
    assert (
        "b.deleted_at IS NULL" in sql
        and "c.deleted_at IS NULL" in sql
        and "p.deleted_at IS NULL" in sql
    )
    # work-based: a row moved by the user (added_at after the block's creation
    # stamp) is a decision, dated by the move; moving back to NEW is an undo.
    assert "tbt.added_at > b.created_at" in sql
    assert "bucket_type <> 'NEW'" in sql
    # staging counts as categorized in open AND finalized blocks; finalize's
    # category_tracks copies are not double-dated.
    assert "bucket_type = 'STAGING' AND NOT inactive" in sql
    assert "ct.source_triage_block_id IS NULL" in sql
    assert "IN_PROGRESS" not in sql

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from collector.curation import (
    NameConflictError,
    NotFoundError,
    OrderMismatchError,
    PaginatedResult,
    ValidationError,
)
from collector.curation.categories_repository import (
    CategoryRow,
    TrackInCategoryRow,
)
from collector.curation_handler import lambda_handler


# ---------- Fake repository --------------------------------------------------

class FakeRepo:
    """In-memory CategoriesRepository for integration tests."""

    def __init__(self) -> None:
        # category_id -> dict
        self.categories: dict[str, dict] = {}
        # (category_id, track_id) -> dict
        self.tracks: dict[tuple[str, str], dict] = {}
        # style_id -> name
        self.styles: dict[str, str] = {"s1": "House", "s2": "Techno"}
        # track id -> dict
        self.track_meta: dict[str, dict] = {}

    def _row(self, c: dict) -> CategoryRow:
        track_count = sum(
            1 for (cid, _) in self.tracks if cid == c["id"]
        )
        return CategoryRow(
            id=c["id"], user_id=c["user_id"], style_id=c["style_id"],
            style_name=self.styles[c["style_id"]],
            name=c["name"], normalized_name=c["normalized_name"],
            position=c["position"], track_count=track_count,
            created_at=c["created_at"], updated_at=c["updated_at"],
        )

    def create(
        self, *, user_id, style_id, category_id, name, normalized_name, now,
        correlation_id=None,
    ):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        for c in self.categories.values():
            if (
                c["user_id"] == user_id
                and c["style_id"] == style_id
                and c["normalized_name"] == normalized_name
                and c.get("deleted_at") is None
            ):
                raise NameConflictError("Name exists")
        positions = [
            c["position"] for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        ]
        new_pos = (max(positions) + 1) if positions else 0
        c = {
            "id": category_id, "user_id": user_id, "style_id": style_id,
            "name": name, "normalized_name": normalized_name,
            "position": new_pos,
            "created_at": now.isoformat(), "updated_at": now.isoformat(),
            "deleted_at": None,
        }
        self.categories[category_id] = c
        return self._row(c)

    def get(self, *, user_id, category_id):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            return None
        return self._row(c)

    def list_by_style(self, *, user_id, style_id, limit, offset):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        items = [
            self._row(c) for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        ]
        items.sort(key=lambda r: (r.position, r.created_at))
        total = len(items)
        return PaginatedResult(
            items=items[offset:offset+limit], total=total,
            limit=limit, offset=offset,
        )

    def list_all(self, *, user_id, limit, offset):
        items = [
            self._row(c) for c in self.categories.values()
            if c["user_id"] == user_id and c.get("deleted_at") is None
        ]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        return PaginatedResult(
            items=items[offset:offset+limit], total=total,
            limit=limit, offset=offset,
        )

    def rename(self, *, user_id, category_id, name, normalized_name, now):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        for other in self.categories.values():
            if (
                other["id"] != category_id
                and other["user_id"] == user_id
                and other["style_id"] == c["style_id"]
                and other["normalized_name"] == normalized_name
                and other.get("deleted_at") is None
            ):
                raise NameConflictError("Name exists")
        c["name"] = name
        c["normalized_name"] = normalized_name
        c["updated_at"] = now.isoformat()
        return self._row(c)

    def soft_delete(self, *, user_id, category_id, now, correlation_id=None):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            return False
        c["deleted_at"] = now.isoformat()
        c["updated_at"] = now.isoformat()
        return True

    def reorder(self, *, user_id, style_id, ordered_ids, now):
        if style_id not in self.styles:
            raise NotFoundError("style_not_found", "Style not found")
        actual = {
            c["id"] for c in self.categories.values()
            if c["user_id"] == user_id
            and c["style_id"] == style_id
            and c.get("deleted_at") is None
        }
        if set(ordered_ids) != actual or len(set(ordered_ids)) != len(ordered_ids):
            raise OrderMismatchError("mismatch")
        for idx, cid in enumerate(ordered_ids):
            self.categories[cid]["position"] = idx
            self.categories[cid]["updated_at"] = now.isoformat()
        return [
            self._row(self.categories[cid]) for cid in ordered_ids
        ]

    def add_tracks_bulk(
        self, *, user_id, category_id, items, now, transaction_id=None
    ):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        for tid, _ in items:
            if tid not in self.track_meta:
                raise NotFoundError("track_not_found", f"Track {tid}")
        added = 0
        for tid, src in items:
            key = (category_id, tid)
            if key in self.tracks:
                continue
            self.tracks[key] = {
                "added_at": now.isoformat(),
                "source_triage_block_id": src,
            }
            added += 1
        return added

    def add_track(
        self, *, user_id, category_id, track_id, source_triage_block_id, now
    ):
        added = self.add_tracks_bulk(
            user_id=user_id, category_id=category_id,
            items=[(track_id, source_triage_block_id)], now=now,
        )
        existing = self.tracks[(category_id, track_id)]
        return (
            {
                "added_at": existing["added_at"],
                "source_triage_block_id": existing["source_triage_block_id"],
            },
            bool(added),
        )

    def remove_track(self, *, user_id, category_id, track_id):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        return self.tracks.pop((category_id, track_id), None) is not None

    def list_tracks(
        self, *, user_id, category_id, limit, offset, search
    ):
        c = self.categories.get(category_id)
        if (
            c is None
            or c["user_id"] != user_id
            or c.get("deleted_at") is not None
        ):
            raise NotFoundError("category_not_found", "Category not found")
        rows = []
        for (cid, tid), meta in self.tracks.items():
            if cid != category_id:
                continue
            track = self.track_meta[tid]
            if search and search.strip().lower() not in track.get(
                "normalized_title", ""
            ):
                continue
            rows.append(
                TrackInCategoryRow(
                    track=track,
                    added_at=meta["added_at"],
                    source_triage_block_id=meta["source_triage_block_id"],
                )
            )
        rows.sort(key=lambda r: (r.added_at, r.track["id"]), reverse=True)
        total = len(rows)
        return PaginatedResult(
            items=rows[offset:offset+limit],
            total=total, limit=limit, offset=offset,
        )


# ---------- Test helpers -----------------------------------------------------

@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-1")


@pytest.fixture
def fake_repo(monkeypatch) -> FakeRepo:
    repo = FakeRepo()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: repo,
    )
    return repo


def _event(
    *,
    method: str,
    route: str,
    user_id: str = "u1",
    is_admin: bool = False,
    path_params: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    correlation_id: str = "cid-1",
) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-1",
            "routeKey": f"{method} {route}",
            "authorizer": {
                "lambda": {
                    "user_id": user_id, "session_id": "s",
                    "is_admin": is_admin,
                }
            },
        },
        "headers": {"x-correlation-id": correlation_id},
        "pathParameters": dict(path_params) if path_params else None,
        "queryStringParameters": dict(query) if query else None,
        "body": json.dumps(body) if body is not None else None,
    }


def _read(resp: dict) -> tuple[int, dict]:
    return resp["statusCode"], json.loads(resp["body"])


# ---------- Skeleton smoke tests --------------------------------------------

def test_unknown_route_returns_404(fake_repo, context):
    resp = lambda_handler(
        _event(method="GET", route="/nonexistent"), context
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "not_found"


def test_missing_authorizer_returns_401(fake_repo, context):
    event = _event(method="GET", route="/categories")
    event["requestContext"].pop("authorizer", None)
    resp = lambda_handler(event, context)
    status, body = _read(resp)
    assert status == 401
    assert body["error_code"] == "unauthorized"


def test_create_category_201(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Tech House"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["name"] == "Tech House"
    assert body["style_name"] == "House"
    assert body["position"] == 0
    assert body["track_count"] == 0


def test_create_category_409_on_duplicate(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409
    assert body["error_code"] == "name_conflict"


def test_create_category_404_style(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "missing"},
            body={"name": "Tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "style_not_found"


def test_create_category_422_empty_name(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "   "},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "validation_error"


def test_list_by_style_returns_paginated(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    for i, name in enumerate(["A", "B", "C"]):
        fake_repo.create(
            user_id="u1", style_id="s1", category_id=f"c{i}",
            name=name, normalized_name=name.lower(), now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 3
    assert [it["name"] for it in body["items"]] == ["A", "B", "C"]
    assert [it["position"] for it in body["items"]] == [0, 1, 2]
    assert body["limit"] == 50
    assert body["offset"] == 0
    assert body["correlation_id"] == "cid-1"


def test_list_by_style_paginates_with_limit_offset(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    for i, name in enumerate(["A", "B", "C", "D"]):
        fake_repo.create(
            user_id="u1", style_id="s1", category_id=f"c{i}",
            name=name, normalized_name=name.lower(), now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            query={"limit": "2", "offset": "1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 4
    assert body["limit"] == 2
    assert body["offset"] == 1
    assert [it["name"] for it in body["items"]] == ["B", "C"]


def test_list_invalid_limit_returns_422(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories",
            query={"limit": "abc"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "validation_error"


def test_list_all_empty_returns_empty_envelope(fake_repo, context):
    resp = lambda_handler(
        _event(method="GET", route="/categories"),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 0
    assert body["items"] == []


def test_list_by_style_404_style_missing(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "missing"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "style_not_found"


def test_list_all_returns_cross_style(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    fake_repo.create(
        user_id="u1", style_id="s2", category_id="c2",
        name="B", normalized_name="b", now=now,
    )
    resp = lambda_handler(
        _event(method="GET", route="/categories"),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 2


def test_get_detail_200(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["id"] == "c1"


def test_get_detail_404(fake_repo, context):
    resp = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "missing"}),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "category_not_found"


def test_rename_200(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            body={"name": "Deep"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["name"] == "Deep"


def test_rename_409_on_conflict(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c2",
        name="Deep", normalized_name="deep", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            body={"name": "Deep"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409


def test_rename_404_missing_category(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "missing"},
            body={"name": "X"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "category_not_found"


def test_rename_422_whitespace_name(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            body={"name": "   "},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "validation_error"


def test_delete_204(fake_repo, context):
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech",
        now=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )
    resp = lambda_handler(
        _event(method="DELETE", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    assert resp["statusCode"] == 204
    assert resp["body"] in ("", "null")


def test_delete_404_already_gone(fake_repo, context):
    resp = lambda_handler(
        _event(method="DELETE", route="/categories/{id}", path_params={"id": "missing"}),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "category_not_found"


def test_reorder_200(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    for i, name in enumerate(["A", "B", "C"]):
        fake_repo.create(
            user_id="u1", style_id="s1", category_id=f"c{i}",
            name=name, normalized_name=name.lower(), now=now,
        )
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "s1"},
            body={"category_ids": ["c2", "c0", "c1"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert [it["id"] for it in body["items"]] == ["c2", "c0", "c1"]
    assert [it["position"] for it in body["items"]] == [0, 1, 2]


def test_reorder_422_on_extra_id(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "s1"},
            body={"category_ids": ["c1", "ghost"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "order_mismatch"


def test_reorder_404_style_missing(fake_repo, context):
    resp = lambda_handler(
        _event(
            method="PUT",
            route="/styles/{style_id}/categories/order",
            path_params={"style_id": "missing"},
            body={"category_ids": []},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404


def test_list_tracks_200(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {
        "id": "t1", "title": "Song", "normalized_title": "song",
        "artists": ["A"],
    }
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == "t1"
    assert body["items"][0]["added_at"] is not None
    assert body["items"][0]["source_triage_block_id"] is None


def test_add_track_201(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1", "title": "X"}
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["result"] == "added"
    assert body["source_triage_block_id"] is None


def test_add_track_200_already_present(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1"}
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["result"] == "already_present"


def test_add_track_404_track_missing(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="POST",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            body={"track_id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "track_not_found"


def test_remove_track_204(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {"id": "t1"}
    fake_repo.add_track(
        user_id="u1", category_id="c1", track_id="t1",
        source_triage_block_id=None, now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "t1"},
        ),
        context,
    )
    assert resp["statusCode"] == 204


def test_remove_track_404_when_not_in_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "ghost"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "track_not_in_category"


# ---------- Tenancy isolation tests ------------------------------------------

def test_user_b_cannot_see_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    # User B requests detail
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404


def test_user_b_cannot_rename_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="PATCH",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
            body={"name": "Hijack"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404


def test_user_b_cannot_delete_user_a_category(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    resp = lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}",
            path_params={"id": "c1"},
            user_id="user-b",
        ),
        context,
    )
    assert resp["statusCode"] == 404


def test_list_by_style_filters_by_user(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="user-a", style_id="s1", category_id="c1",
        name="A", normalized_name="a", now=now,
    )
    fake_repo.create(
        user_id="user-b", style_id="s1", category_id="c2",
        name="B", normalized_name="b", now=now,
    )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            user_id="user-a",
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 1
    assert body["items"][0]["id"] == "c1"


# ---------- Task 20: name-conflict, recreate-after-soft-delete, cross-style namesakes ---


def test_recreate_after_soft_delete(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    # soft-delete
    fake_repo.soft_delete(user_id="u1", category_id="c1", now=now)
    # recreate same name -> should succeed
    resp = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Tech"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["track_count"] == 0
    assert body["id"] != "c1"


def test_cross_style_namesakes_coexist(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    r1 = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
            body={"name": "Deep"},
        ),
        context,
    )
    r2 = lambda_handler(
        _event(
            method="POST",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s2"},
            body={"name": "Deep"},
        ),
        context,
    )
    assert r1["statusCode"] == 201
    assert r2["statusCode"] == 201


# ---------- Task 21: spec-D contract smoke -------------------------------------------


def test_spec_d_contract_add_tracks_bulk_round_trip(fake_repo, context):
    """spec-D will reuse add_tracks_bulk inside its triage finalize TX."""
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    fake_repo.track_meta["t1"] = {
        "id": "t1", "title": "X", "normalized_title": "x",
    }
    inserted = fake_repo.add_tracks_bulk(
        user_id="u1",
        category_id="c1",
        items=[("t1", "block-d-1")],
        now=now,
        transaction_id="tx-from-spec-d",
    )
    assert inserted == 1
    # source_triage_block_id round-trips
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["items"][0]["source_triage_block_id"] == "block-d-1"


# ---------- Task 22: pagination, search, count rollup --------------------------------


def test_tracks_pagination_limits(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for i in range(120):
        tid = f"t{i:03}"
        fake_repo.track_meta[tid] = {
            "id": tid, "title": f"S{i}", "normalized_title": f"s{i}",
        }
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"limit": "50", "offset": "100"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 120
    assert len(body["items"]) == 20  # 120 - 100


def test_tracks_search(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for tid, title in [("t1", "Acid Rain"), ("t2", "Deep Ocean"), ("t3", "Acid Wave")]:
        fake_repo.track_meta[tid] = {
            "id": tid, "title": title,
            "normalized_title": title.lower(),
        }
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )
    resp = lambda_handler(
        _event(
            method="GET",
            route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"search": "acid"},
        ),
        context,
    )
    _, body = _read(resp)
    assert body["total"] == 2


def test_track_count_rollup_on_list_and_detail(fake_repo, context):
    now = datetime(2026, 4, 27, tzinfo=timezone.utc)
    fake_repo.create(
        user_id="u1", style_id="s1", category_id="c1",
        name="Tech", normalized_name="tech", now=now,
    )
    for tid in ["t1", "t2", "t3"]:
        fake_repo.track_meta[tid] = {"id": tid}
        fake_repo.add_track(
            user_id="u1", category_id="c1", track_id=tid,
            source_triage_block_id=None, now=now,
        )

    detail = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    _, body = _read(detail)
    assert body["track_count"] == 3

    listing = lambda_handler(
        _event(
            method="GET",
            route="/styles/{style_id}/categories",
            path_params={"style_id": "s1"},
        ),
        context,
    )
    _, body = _read(listing)
    assert body["items"][0]["track_count"] == 3

    # Remove one -> count decrements
    lambda_handler(
        _event(
            method="DELETE",
            route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "t1"},
        ),
        context,
    )
    detail2 = lambda_handler(
        _event(method="GET", route="/categories/{id}", path_params={"id": "c1"}),
        context,
    )
    _, body = _read(detail2)
    assert body["track_count"] == 2

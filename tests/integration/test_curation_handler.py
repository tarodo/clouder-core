from __future__ import annotations

import json
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

    def create(self, *, user_id, style_id, category_id, name, normalized_name, now):
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

    def soft_delete(self, *, user_id, category_id, now):
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

"""Unit tests for `collector.curation_handler` track-tag routes (spec 2026-05-11)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Mapping
from unittest.mock import MagicMock

import pytest

from collector import curation_handler
from collector.curation import (
    PaginatedResult,
    TagNameConflictError,
    TagNotFoundError,
    TrackNotInAnyCategoryError,
)
from collector.curation.tags_repository import TagRow, TrackTagRow
from collector.curation_handler import lambda_handler


def _event(
    *,
    method: str,
    route: str,
    user_id: str = "u1",
    path_params: Mapping[str, str] | None = None,
    query: Mapping[str, str] | None = None,
    body: Any | None = None,
    correlation_id: str = "cid-tags-1",
) -> dict:
    return {
        "version": "2.0",
        "requestContext": {
            "requestId": "api-req-tags",
            "routeKey": f"{method} {route}",
            "authorizer": {
                "lambda": {
                    "user_id": user_id,
                    "session_id": "s",
                    "is_admin": False,
                }
            },
        },
        "headers": {"x-correlation-id": correlation_id},
        "pathParameters": dict(path_params) if path_params else None,
        "queryStringParameters": dict(query) if query else None,
        "body": json.dumps(body) if body is not None else None,
    }


def _read(resp: dict) -> tuple[int, dict | None]:
    body = resp["body"]
    if not body:
        return resp["statusCode"], None
    return resp["statusCode"], json.loads(body)


@pytest.fixture
def context() -> SimpleNamespace:
    return SimpleNamespace(aws_request_id="lambda-req-tags-1")


@pytest.fixture
def fake_tags(monkeypatch) -> MagicMock:
    repo = MagicMock()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: repo,
    )
    return repo


def _stock_tag_row(
    id: str = "tg1", name: str = "Vocal", color: str = "#ff8800"
) -> TagRow:
    return TagRow(
        id=id, name=name, color=color,
        created_at="2026-05-11T12:00:00Z",
        updated_at="2026-05-11T12:00:00Z",
    )


# ---------- vocabulary CRUD ------------------------------------------------


def test_create_tag_returns_201(fake_tags, context) -> None:
    fake_tags.create_tag.return_value = _stock_tag_row()
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "Vocal", "color": "#ff8800"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["name"] == "Vocal"
    assert body["color"] == "#ff8800"
    assert body["id"] == "tg1"


def test_create_tag_400_invalid_color(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "Vocal", "color": "blue"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_color"
    fake_tags.create_tag.assert_not_called()


def test_create_tag_400_invalid_name_empty(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "   ", "color": "#ff8800"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_name"


def test_create_tag_400_invalid_name_too_long(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "x" * 65, "color": "#ff8800"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_name"


def test_create_tag_409_on_duplicate_name(fake_tags, context) -> None:
    fake_tags.create_tag.side_effect = TagNameConflictError("dup")
    resp = lambda_handler(
        _event(
            method="POST", route="/tags",
            body={"name": "Vocal", "color": "#ff8800"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 409
    assert body["error_code"] == "tag_name_conflict"


def test_list_tags_returns_items_total(fake_tags, context) -> None:
    fake_tags.list_tags.return_value = PaginatedResult(
        items=[_stock_tag_row()], total=1, limit=50, offset=0,
    )
    resp = lambda_handler(_event(method="GET", route="/tags"), context)
    status, body = _read(resp)
    assert status == 200
    assert body["total"] == 1
    assert body["items"][0]["id"] == "tg1"


def test_list_tags_passes_search_param(fake_tags, context) -> None:
    fake_tags.list_tags.return_value = PaginatedResult(
        items=[], total=0, limit=50, offset=0,
    )
    lambda_handler(
        _event(method="GET", route="/tags", query={"search": "vo"}),
        context,
    )
    assert fake_tags.list_tags.call_args.kwargs["search"] == "vo"


def test_patch_tag_200_renames(fake_tags, context) -> None:
    fake_tags.rename_tag.return_value = _stock_tag_row(name="Vocal F")
    resp = lambda_handler(
        _event(
            method="PATCH", route="/tags/{tag_id}",
            path_params={"tag_id": "tg1"},
            body={"name": "Vocal F"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["name"] == "Vocal F"
    kwargs = fake_tags.rename_tag.call_args.kwargs
    assert kwargs["tag_id"] == "tg1"
    assert kwargs["name"] == "Vocal F"
    assert kwargs["normalized_name"] == "vocal f"
    assert kwargs["color"] is None


def test_patch_tag_400_when_no_fields(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="PATCH", route="/tags/{tag_id}",
            path_params={"tag_id": "tg1"},
            body={},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_payload"
    fake_tags.rename_tag.assert_not_called()


def test_patch_tag_404_when_missing(fake_tags, context) -> None:
    fake_tags.rename_tag.side_effect = TagNotFoundError()
    resp = lambda_handler(
        _event(
            method="PATCH", route="/tags/{tag_id}",
            path_params={"tag_id": "missing"},
            body={"name": "X"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "tag_not_found"


def test_delete_tag_204(fake_tags, context) -> None:
    fake_tags.delete_tag.return_value = True
    resp = lambda_handler(
        _event(
            method="DELETE", route="/tags/{tag_id}",
            path_params={"tag_id": "tg1"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 204
    fake_tags.delete_tag.assert_called_once_with(user_id="u1", tag_id="tg1")


def test_delete_tag_404_when_missing(fake_tags, context) -> None:
    fake_tags.delete_tag.return_value = False
    resp = lambda_handler(
        _event(
            method="DELETE", route="/tags/{tag_id}",
            path_params={"tag_id": "missing"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "tag_not_found"

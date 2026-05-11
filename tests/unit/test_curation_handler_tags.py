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


# ---------- track-tag ops --------------------------------------------------


def test_list_track_tags_returns_array(fake_tags, context) -> None:
    fake_tags.list_tags_for_tracks.return_value = {
        "t1": [TrackTagRow(track_id="t1", tag_id="tg1", name="Vocal", color="#f00")]
    }
    resp = lambda_handler(
        _event(
            method="GET", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["tags"] == [{"id": "tg1", "name": "Vocal", "color": "#f00"}]
    fake_tags.list_tags_for_tracks.assert_called_once_with(
        user_id="u1", track_ids=["t1"],
    )


def test_list_track_tags_empty_when_no_rows(fake_tags, context) -> None:
    fake_tags.list_tags_for_tracks.return_value = {}
    resp = lambda_handler(
        _event(
            method="GET", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["tags"] == []


def test_put_track_tags_200_replaces(fake_tags, context) -> None:
    fake_tags.set_track_tags.return_value = [_stock_tag_row()]
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": ["tg1"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["tags"][0]["id"] == "tg1"
    assert fake_tags.set_track_tags.call_args.kwargs["tag_ids"] == ["tg1"]


def test_put_track_tags_200_clear_all_with_empty_array(
    fake_tags, context
) -> None:
    fake_tags.set_track_tags.return_value = []
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": []},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 200
    assert body["tags"] == []
    fake_tags.set_track_tags.assert_called_once()
    assert fake_tags.set_track_tags.call_args.kwargs["tag_ids"] == []


def test_put_track_tags_422_when_not_in_any_category(
    fake_tags, context
) -> None:
    fake_tags.set_track_tags.side_effect = TrackNotInAnyCategoryError(
        "Track not in any category"
    )
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": ["tg1"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 422
    assert body["error_code"] == "track_not_in_any_category"


def test_put_track_tags_400_too_many(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": ["tg" + str(i) for i in range(51)]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "too_many_tags"
    fake_tags.set_track_tags.assert_not_called()


def test_put_track_tags_400_duplicates(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": ["tg1", "tg1"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_tag_ids"


def test_put_track_tags_400_non_array(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": "not-array"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_tag_ids"


def test_put_track_tags_404_foreign_tag(fake_tags, context) -> None:
    fake_tags.set_track_tags.side_effect = TagNotFoundError(
        "Unknown tag id: tg-foreign"
    )
    resp = lambda_handler(
        _event(
            method="PUT", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_ids": ["tg-foreign"]},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 404
    assert body["error_code"] == "tag_not_found"


def test_post_track_tag_201_idempotent(fake_tags, context) -> None:
    fake_tags.add_track_tag.return_value = [_stock_tag_row()]
    resp = lambda_handler(
        _event(
            method="POST", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={"tag_id": "tg1"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 201
    assert body["tags"][0]["id"] == "tg1"


def test_post_track_tag_400_missing_tag_id(fake_tags, context) -> None:
    resp = lambda_handler(
        _event(
            method="POST", route="/tracks/{track_id}/tags",
            path_params={"track_id": "t1"},
            body={},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_tag_ids"


def test_delete_track_tag_204(fake_tags, context) -> None:
    fake_tags.remove_track_tag.return_value = True
    resp = lambda_handler(
        _event(
            method="DELETE", route="/tracks/{track_id}/tags/{tag_id}",
            path_params={"track_id": "t1", "tag_id": "tg1"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 204
    fake_tags.remove_track_tag.assert_called_once_with(
        user_id="u1", track_id="t1", tag_id="tg1",
    )


def test_delete_track_tag_204_when_already_gone(
    fake_tags, context
) -> None:
    """remove is idempotent — 204 even when no row was deleted."""
    fake_tags.remove_track_tag.return_value = False
    resp = lambda_handler(
        _event(
            method="DELETE", route="/tracks/{track_id}/tags/{tag_id}",
            path_params={"track_id": "t1", "tag_id": "missing"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 204


# ---------- /categories/{id}/tracks tag filter param -----------------------


def test_get_category_tracks_with_tag_filter_passes_params_to_repo(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    fake_cat.list_tracks.return_value = PaginatedResult(
        items=[], total=0, limit=50, offset=0,
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    resp = lambda_handler(
        _event(
            method="GET", route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"tags": "tg1,tg2", "match": "all"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 200
    kwargs = fake_cat.list_tracks.call_args.kwargs
    assert kwargs["tag_ids"] == ["tg1", "tg2"]
    assert kwargs["tag_match"] == "all"
    assert kwargs["tags_repo"] is fake_tags


def test_get_category_tracks_default_match_is_all(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    fake_cat.list_tracks.return_value = PaginatedResult(
        items=[], total=0, limit=50, offset=0,
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    lambda_handler(
        _event(
            method="GET", route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"tags": "tg1"},
        ),
        context,
    )
    assert fake_cat.list_tracks.call_args.kwargs["tag_match"] == "all"


def test_get_category_tracks_no_tag_filter_passes_none(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    fake_cat.list_tracks.return_value = PaginatedResult(
        items=[], total=0, limit=50, offset=0,
    )
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    lambda_handler(
        _event(
            method="GET", route="/categories/{id}/tracks",
            path_params={"id": "c1"},
        ),
        context,
    )
    kwargs = fake_cat.list_tracks.call_args.kwargs
    assert kwargs["tag_ids"] is None
    # tags_repo is still passed so the repo can fan-in tags on every row
    assert kwargs["tags_repo"] is fake_tags


def test_get_category_tracks_invalid_match_returns_400(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    resp = lambda_handler(
        _event(
            method="GET", route="/categories/{id}/tracks",
            path_params={"id": "c1"},
            query={"tags": "tg1", "match": "xor"},
        ),
        context,
    )
    status, body = _read(resp)
    assert status == 400
    assert body["error_code"] == "invalid_match"
    fake_cat.list_tracks.assert_not_called()


# ---------- inline tags_repo wiring on category mutations ------------------


def test_remove_track_passes_tags_repo_to_categories_repo(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    fake_cat.remove_track.return_value = True
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    resp = lambda_handler(
        _event(
            method="DELETE", route="/categories/{id}/tracks/{track_id}",
            path_params={"id": "c1", "track_id": "t1"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 204
    assert fake_cat.remove_track.call_args.kwargs["tags_repo"] is fake_tags


def test_soft_delete_passes_tags_repo_to_categories_repo(
    monkeypatch, fake_tags, context
) -> None:
    fake_cat = MagicMock()
    fake_cat.soft_delete.return_value = True
    monkeypatch.setattr(
        "collector.curation_handler.create_default_categories_repository",
        lambda: fake_cat,
    )
    resp = lambda_handler(
        _event(
            method="DELETE", route="/categories/{id}",
            path_params={"id": "c1"},
        ),
        context,
    )
    status, _body = _read(resp)
    assert status == 204
    assert fake_cat.soft_delete.call_args.kwargs["tags_repo"] is fake_tags

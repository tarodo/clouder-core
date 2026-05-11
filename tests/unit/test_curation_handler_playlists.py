"""Handler-level smoke tests for /playlists routes. Repository is a stub."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from collector.curation_handler import lambda_handler


def _event(method: str, path: str, body: dict | None = None,
           path_params: dict | None = None) -> dict:
    return {
        "requestContext": {
            "routeKey": f"{method} {path}",
            "authorizer": {"lambda": {"user_id": "u-1"}},
        },
        "pathParameters": path_params or {},
        "body": json.dumps(body) if body else "",
        "headers": {"x-correlation-id": "cid-1"},
    }


def _patch_factory(repo: MagicMock):
    return patch(
        "collector.curation_handler.create_default_playlists_repository",
        return_value=repo,
    )


def _row(**overrides) -> MagicMock:
    base = dict(
        id="p-1", user_id="u-1", name="My Set", normalized_name="my set",
        description=None, is_public=False, cover_s3_key=None,
        cover_uploaded_at=None, spotify_playlist_id=None,
        last_published_at=None, needs_republish=False, track_count=0,
        created_at="2026-05-12T10:00:00+00:00",
        updated_at="2026-05-12T10:00:00+00:00",
    )
    base.update(overrides)
    # `name` is a reserved MagicMock constructor kwarg (it becomes the mock's
    # repr name, not a settable attribute). Apply attributes via configure_mock.
    m = MagicMock()
    m.configure_mock(**base)
    return m


def test_create_playlist_returns_201() -> None:
    repo = MagicMock()
    repo.create.return_value = _row()
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists", {"name": "My Set"}),
            None,
        )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["id"] == "p-1"


def test_get_playlist_returns_404_when_missing() -> None:
    repo = MagicMock()
    repo.get.return_value = None
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}", path_params={"id": "missing"}),
            None,
        )
    assert resp["statusCode"] == 404


def test_patch_playlist_returns_200() -> None:
    repo = MagicMock()
    repo.patch.return_value = _row(name="renamed", normalized_name="renamed")
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("PATCH", "/playlists/{id}",
                   body={"name": "renamed"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200


def test_delete_playlist_returns_204() -> None:
    repo = MagicMock()
    repo.soft_delete.return_value = True
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("DELETE", "/playlists/{id}", path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 204


def test_list_playlists_paginated() -> None:
    repo = MagicMock()
    repo.list_all.return_value = ([], 0)
    with _patch_factory(repo):
        resp = lambda_handler(_event("GET", "/playlists"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["items"] == []
    assert body["total"] == 0


def test_get_playlist_returns_200_with_full_payload() -> None:
    repo = MagicMock()
    repo.get.return_value = _row(track_count=5)
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}", path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["track_count"] == 5

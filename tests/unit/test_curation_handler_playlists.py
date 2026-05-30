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
        status="active",
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


def test_list_playlist_tracks_returns_paginated(monkeypatch) -> None:
    repo = MagicMock()
    repo.list_tracks.return_value = ([], 0)
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: MagicMock(),
    )
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}/tracks",
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200


def test_add_tracks_resolves_scope_then_appends() -> None:
    repo = MagicMock()
    repo.validate_tracks_in_scope.return_value = {"t-1", "t-2"}
    append_result = MagicMock()
    append_result.configure_mock(
        added_track_ids=["t-1", "t-2"],
        skipped_duplicates=[],
        position_after=2,
    )
    repo.append_tracks.return_value = append_result
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks",
                   body={"track_ids": ["t-1", "t-2"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 201
    body = json.loads(resp["body"])
    assert body["added"] == ["t-1", "t-2"]
    assert body["position_after"] == 2


def test_add_tracks_returns_404_for_out_of_scope() -> None:
    repo = MagicMock()
    repo.validate_tracks_in_scope.return_value = {"t-1"}
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks",
                   body={"track_ids": ["t-1", "t-foreign"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "t-foreign" in body["missing_track_ids"]


def test_remove_track_204() -> None:
    repo = MagicMock()
    repo.remove_track.return_value = True
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("DELETE", "/playlists/{id}/tracks/{track_id}",
                   path_params={"id": "p-1", "track_id": "t-1"}),
            None,
        )
    assert resp["statusCode"] == 204


def test_reorder_tracks_200() -> None:
    repo = MagicMock()
    repo.reorder_tracks.return_value = None
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/tracks/order",
                   body={"track_ids": ["t-2", "t-1"]},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200


def test_cover_upload_url_returns_presign_metadata() -> None:
    repo = MagicMock()
    repo.get.return_value = _row()  # exists
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_s3_storage"
    ) as s3_factory:
        s3 = MagicMock()
        s3.cover_key.return_value = "covers/u-1/p-1/123.jpg"
        s3.presigned_cover_put_url.return_value = "https://signed"
        s3_factory.return_value = s3
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/cover/upload-url",
                   body={"content_type": "image/jpeg"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["upload_url"] == "https://signed"
    assert body["s3_key"].startswith("covers/u-1/p-1/")


def test_cover_confirm_400_when_missing() -> None:
    repo = MagicMock()
    repo.get.return_value = _row()
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_s3_storage"
    ) as s3_factory:
        s3 = MagicMock()
        s3.head_cover.return_value = None
        s3_factory.return_value = s3
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/cover/confirm",
                   body={"s3_key": "covers/u-1/p-1/123.jpg"},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 400
    assert json.loads(resp["body"])["error_code"] == "cover_missing"


def _track_row(**overrides) -> MagicMock:
    """Build a fake PlaylistTrackRow with all enriched fields."""
    tag = MagicMock()
    tag.configure_mock(tag_id="tag-1", name="House", color="#FF0000")
    base = dict(
        track_id="t-1",
        position=1,
        added_at="2026-05-01T00:00:00+00:00",
        title="Test Track",
        spotify_id="sp-1",
        isrc="ISRC001",
        length_ms=180000,
        origin="beatport",
        mix_name="Original Mix",
        bpm=128,
        spotify_release_date="2026-04-01",
        is_ai_suspected=False,
        artists=[{"id": "a-1", "name": "DJ Test"}],
        label={"id": "l-1", "name": "Test Label"},
        tags=(tag,),
        ytmusic=None,
    )
    base.update(overrides)
    m = MagicMock()
    m.configure_mock(**base)
    return m


def test_list_playlist_tracks_returns_enriched_fields(monkeypatch) -> None:
    """The response must include artists, label, bpm, mix_name, etc. and tags."""
    repo = MagicMock()
    row = _track_row()
    repo.list_tracks.return_value = ([row], 1)
    fake_tags_repo = MagicMock()
    monkeypatch.setattr(
        "collector.curation_handler.create_default_tags_repository",
        lambda: fake_tags_repo,
    )
    with _patch_factory(repo):
        resp = lambda_handler(
            _event("GET", "/playlists/{id}/tracks",
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["total"] == 1
    item = body["items"][0]
    assert item["mix_name"] == "Original Mix"
    assert item["bpm"] == 128
    assert item["spotify_release_date"] == "2026-04-01"
    assert item["is_ai_suspected"] is False
    assert item["artists"] == [{"id": "a-1", "name": "DJ Test"}]
    assert item["label"] == {"id": "l-1", "name": "Test Label"}
    assert item["tags"] == [{"id": "tag-1", "name": "House", "color": "#FF0000"}]


def test_publish_returns_412_when_no_spotify_token() -> None:
    repo = MagicMock()
    repo.get.return_value = _row()
    from collector.curation import SpotifyNotAuthorizedError as _ENA
    with _patch_factory(repo), patch(
        "collector.curation_handler._build_spotify_user_client",
        side_effect=_ENA("no token"),
    ):
        resp = lambda_handler(
            _event("POST", "/playlists/{id}/publish",
                   body={"confirm_overwrite": False},
                   path_params={"id": "p-1"}),
            None,
        )
    assert resp["statusCode"] == 412

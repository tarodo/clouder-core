from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from collector.curation.schemas import (
    AddTracksIn,
    CoverUploadUrlIn,
    CreatePlaylistIn,
    ImportSpotifyTracksIn,
    PatchPlaylistIn,
    PublishPlaylistIn,
    ReorderPlaylistTracksIn,
)


def test_create_playlist_minimum() -> None:
    body = CreatePlaylistIn.model_validate({"name": "My Set"})
    assert body.description is None
    # New playlists are public by default.
    assert body.is_public is True


def test_create_playlist_full() -> None:
    body = CreatePlaylistIn.model_validate({
        "name": "S", "description": "d", "is_public": True,
    })
    assert body.is_public is True


def test_create_playlist_rejects_blank_name() -> None:
    with pytest.raises(PydanticValidationError):
        CreatePlaylistIn.model_validate({"name": ""})


def test_create_playlist_rejects_extra_fields() -> None:
    with pytest.raises(PydanticValidationError):
        CreatePlaylistIn.model_validate({"name": "x", "foo": 1})


def test_patch_playlist_allows_partial() -> None:
    body = PatchPlaylistIn.model_validate({"is_public": True})
    assert body.name is None
    assert body.description is None
    assert body.is_public is True


def test_patch_playlist_requires_at_least_one_field() -> None:
    with pytest.raises(PydanticValidationError):
        PatchPlaylistIn.model_validate({})


def test_add_tracks_in_requires_non_empty() -> None:
    with pytest.raises(PydanticValidationError):
        AddTracksIn.model_validate({"track_ids": []})


def test_add_tracks_in_caps_size() -> None:
    with pytest.raises(PydanticValidationError):
        AddTracksIn.model_validate({"track_ids": ["x"] * 1001})


def test_reorder_accepts_list() -> None:
    body = ReorderPlaylistTracksIn.model_validate(
        {"track_ids": ["a", "b"]}
    )
    assert body.track_ids == ["a", "b"]


def test_import_spotify_caps_at_50() -> None:
    with pytest.raises(PydanticValidationError):
        ImportSpotifyTracksIn.model_validate(
            {"spotify_refs": ["x"] * 51},
        )


def test_publish_in_requires_confirm_overwrite_bool() -> None:
    body = PublishPlaylistIn.model_validate({"confirm_overwrite": True})
    assert body.confirm_overwrite is True


def test_publish_in_defaults_confirm_to_false() -> None:
    body = PublishPlaylistIn.model_validate({})
    assert body.confirm_overwrite is False


def test_cover_upload_url_in_requires_jpeg() -> None:
    body = CoverUploadUrlIn.model_validate({"content_type": "image/jpeg"})
    assert body.content_type == "image/jpeg"


def test_cover_upload_url_rejects_other_types() -> None:
    with pytest.raises(PydanticValidationError):
        CoverUploadUrlIn.model_validate({"content_type": "image/png"})

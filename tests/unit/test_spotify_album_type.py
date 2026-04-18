"""Unit tests for Spotify release_type extraction and propagation."""

from __future__ import annotations

import pytest

from collector.spotify_handler import _extract_album_type


def test_extract_album_type_none_track_returns_none() -> None:
    assert _extract_album_type(None) is None


def test_extract_album_type_missing_album_returns_none() -> None:
    assert _extract_album_type({"id": "sp1"}) is None


def test_extract_album_type_missing_field_returns_none() -> None:
    assert _extract_album_type({"id": "sp1", "album": {}}) is None


def test_extract_album_type_single() -> None:
    assert (
        _extract_album_type({"id": "sp1", "album": {"album_type": "single"}})
        == "single"
    )


def test_extract_album_type_compilation() -> None:
    assert (
        _extract_album_type({"album": {"album_type": "compilation"}})
        == "compilation"
    )


def test_extract_album_type_album() -> None:
    assert _extract_album_type({"album": {"album_type": "album"}}) == "album"


def test_extract_album_type_non_string_value_returns_none() -> None:
    assert _extract_album_type({"album": {"album_type": 42}}) is None

from __future__ import annotations

import pytest

from collector.curation import (
    InvalidSpotifyRefError,
    OrderMismatchError,
    ValidationError,
)
from collector.curation.playlists_service import (
    MAX_DESCRIPTION_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAYLISTS_PER_USER,
    MAX_TRACKS_PER_PLAYLIST,
    normalize_playlist_name,
    parse_spotify_ref,
    validate_description,
    validate_playlist_name,
    validate_reorder_set,
)


def test_normalize_lowercases_trims_collapses() -> None:
    assert normalize_playlist_name("  Tech  HOUSE  ") == "tech house"


def test_normalize_unicode_emoji() -> None:
    assert normalize_playlist_name("Hot 🔥 Beats") == "hot 🔥 beats"


def test_validate_name_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("   ")


def test_validate_name_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("x" * (MAX_NAME_LENGTH + 1))


def test_validate_name_rejects_control_chars() -> None:
    with pytest.raises(ValidationError):
        validate_playlist_name("bad\x07name")


def test_validate_description_allows_none() -> None:
    validate_description(None)


def test_validate_description_allows_empty_string() -> None:
    validate_description("")


def test_validate_description_rejects_too_long() -> None:
    with pytest.raises(ValidationError):
        validate_description("x" * (MAX_DESCRIPTION_LENGTH + 1))


def test_parse_uri_form() -> None:
    assert parse_spotify_ref("spotify:track:5xkAVrKKnHeBHb1Mqt6wEt") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_url_form() -> None:
    assert (
        parse_spotify_ref("https://open.spotify.com/track/5xkAVrKKnHeBHb1Mqt6wEt")
        == "5xkAVrKKnHeBHb1Mqt6wEt"
    )


def test_parse_url_with_query_string() -> None:
    assert (
        parse_spotify_ref("https://open.spotify.com/track/5xkAVrKKnHeBHb1Mqt6wEt?si=abc")
        == "5xkAVrKKnHeBHb1Mqt6wEt"
    )


def test_parse_bare_id() -> None:
    assert parse_spotify_ref("5xkAVrKKnHeBHb1Mqt6wEt") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_trims_whitespace() -> None:
    assert parse_spotify_ref("  5xkAVrKKnHeBHb1Mqt6wEt  ") == "5xkAVrKKnHeBHb1Mqt6wEt"


def test_parse_rejects_wrong_length() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("short")


def test_parse_rejects_non_track_uri() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("spotify:album:5xkAVrKKnHeBHb1Mqt6wEt")


def test_parse_rejects_malformed_chars() -> None:
    with pytest.raises(InvalidSpotifyRefError):
        parse_spotify_ref("!!!!!!!!!!!!!!!!!!!!!!")  # 22 chars but invalid base62


def test_reorder_detects_duplicate() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b", "c"], requested=["a", "a", "b"])


def test_reorder_detects_missing() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b", "c"], requested=["a", "b"])


def test_reorder_detects_extra() -> None:
    with pytest.raises(OrderMismatchError):
        validate_reorder_set(actual=["a", "b"], requested=["a", "b", "c"])


def test_reorder_accepts_permutation() -> None:
    validate_reorder_set(actual=["a", "b", "c"], requested=["c", "a", "b"])


def test_limits_exposed_as_module_constants() -> None:
    assert MAX_PLAYLISTS_PER_USER == 200
    assert MAX_TRACKS_PER_PLAYLIST == 1000
    assert MAX_NAME_LENGTH == 100
    assert MAX_DESCRIPTION_LENGTH == 300

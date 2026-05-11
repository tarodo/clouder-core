from __future__ import annotations

import pytest

from collector.curation import (
    ConfirmOverwriteRequiredError,
    CoverMissingError,
    CoverTooLargeError,
    InvalidSpotifyRefError,
    NothingToPublishError,
    PlaylistLimitReachedError,
    PlaylistNameConflictError,
    PlaylistNotFoundError,
    PlaylistTrackLimitError,
    SpotifyApiError,
    SpotifyNotAuthorizedError,
    SpotifyNotFoundError,
    SpotifyRateLimitedError,
    SpotifyScopeInsufficientError,
    TrackNotInUserScopeError,
)


def test_each_error_carries_expected_code_and_status() -> None:
    cases = [
        (PlaylistNameConflictError("x"), "playlist_name_conflict", 409),
        (PlaylistLimitReachedError("x"), "playlist_limit_reached", 429),
        (PlaylistTrackLimitError("x"), "playlist_track_limit", 400),
        (TrackNotInUserScopeError("x", ["a"]), "track_not_in_user_scope", 404),
        (ConfirmOverwriteRequiredError("x"), "confirm_overwrite_required", 409),
        (SpotifyNotAuthorizedError("x"), "spotify_not_authorized", 412),
        (SpotifyScopeInsufficientError("x"), "spotify_scope_insufficient", 412),
        (SpotifyApiError("x"), "spotify_api_error", 502),
        (SpotifyNotFoundError("x"), "spotify_not_found", 502),
        (SpotifyRateLimitedError("x"), "spotify_rate_limited", 502),
        (InvalidSpotifyRefError("x"), "invalid_spotify_ref", 400),
        (CoverMissingError("x"), "cover_missing", 400),
        (CoverTooLargeError("x"), "cover_too_large", 400),
        (NothingToPublishError("x"), "nothing_to_publish", 400),
    ]
    for exc, code, status in cases:
        assert exc.error_code == code
        assert exc.http_status == status


def test_track_not_in_user_scope_carries_ids() -> None:
    exc = TrackNotInUserScopeError("missing", ["a", "b"])
    assert exc.missing_track_ids == ["a", "b"]


def test_playlist_not_found_uses_subclass_pattern() -> None:
    with pytest.raises(PlaylistNotFoundError):
        raise PlaylistNotFoundError()

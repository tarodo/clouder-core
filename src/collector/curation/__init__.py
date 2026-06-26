"""Curation user-overlay package: categories (spec-C), triage (spec-D), release-playlists (spec-E).

This module exposes only the cross-cutting types and errors shared by
all curation specs. Per-spec implementation lives in sibling modules
(`categories_repository.py`, `categories_service.py`, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, Sequence, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PaginatedResult(Generic[T]):
    items: Sequence[T]
    total: int
    limit: int
    offset: int


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CurationError(Exception):
    """Base for curation-domain errors raised by repositories/services."""

    error_code: str = "curation_error"
    http_status: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ValidationError(CurationError):
    error_code = "validation_error"
    http_status = 422


class BadQueryParamError(CurationError):
    """Invalid query parameter value (HTTP 400)."""

    error_code = "bad_query_param"
    http_status = 400


class NotFoundError(CurationError):
    http_status = 404

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class NameConflictError(CurationError):
    error_code = "name_conflict"
    http_status = 409


class OrderMismatchError(CurationError):
    error_code = "order_mismatch"
    http_status = 422


class InvalidStateError(CurationError):
    """Operation rejected because target entity is in the wrong state."""

    error_code = "invalid_state"
    http_status = 422


class InactiveBucketError(CurationError):
    """Move/transfer target is an inactive staging bucket."""

    error_code = "target_bucket_inactive"
    http_status = 422


class InactiveStagingFinalizeError(CurationError):
    """Finalize blocked because at least one inactive staging bucket has tracks."""

    error_code = "inactive_buckets_have_tracks"
    http_status = 409

    def __init__(
        self, message: str, inactive_buckets: list[dict[str, object]]
    ) -> None:
        super().__init__(message)
        self.inactive_buckets = inactive_buckets


class TracksNotInSourceError(CurationError):
    """Move/transfer references track ids absent from the source bucket/block."""

    error_code = "tracks_not_in_source"
    http_status = 422

    def __init__(
        self, message: str, not_in_source: list[str]
    ) -> None:
        super().__init__(message)
        self.not_in_source = not_in_source


class StyleMismatchError(CurationError):
    """Cross-style transfer attempt."""

    error_code = "target_block_style_mismatch"
    http_status = 422


# --- Track-tags (spec 2026-05-11) ------------------------------------------


class TagNameConflictError(NameConflictError):
    error_code = "tag_name_conflict"


class TagNotFoundError(NotFoundError):
    def __init__(self, message: str = "Tag not found") -> None:
        super().__init__("tag_not_found", message)


class TrackNotInAnyCategoryError(CurationError):
    error_code = "track_not_in_any_category"
    http_status = 422


class InvalidTagNameError(BadQueryParamError):
    error_code = "invalid_name"


class InvalidTagColorError(BadQueryParamError):
    error_code = "invalid_color"


class InvalidTagPayloadError(BadQueryParamError):
    error_code = "invalid_payload"


class InvalidTagIdsError(BadQueryParamError):
    error_code = "invalid_tag_ids"


class TooManyTagsError(BadQueryParamError):
    error_code = "too_many_tags"


class InvalidMatchError(BadQueryParamError):
    error_code = "invalid_match"


# --- Playlists (spec 2026-05-11) -------------------------------------------


class PlaylistNotFoundError(NotFoundError):
    def __init__(self, message: str = "Playlist not found") -> None:
        super().__init__("playlist_not_found", message)


class PlaylistNameConflictError(NameConflictError):
    error_code = "playlist_name_conflict"


class PlaylistLimitReachedError(CurationError):
    error_code = "playlist_limit_reached"
    http_status = 429


class PlaylistTrackLimitError(CurationError):
    error_code = "playlist_track_limit"
    http_status = 400


class TrackNotInUserScopeError(CurationError):
    error_code = "track_not_in_user_scope"
    http_status = 404

    def __init__(self, message: str, missing_track_ids: list[str]) -> None:
        super().__init__(message)
        self.missing_track_ids = missing_track_ids


class ConfirmOverwriteRequiredError(CurationError):
    error_code = "confirm_overwrite_required"
    http_status = 409


class SpotifyNotAuthorizedError(CurationError):
    error_code = "spotify_not_authorized"
    http_status = 412


class SpotifyScopeInsufficientError(CurationError):
    error_code = "spotify_scope_insufficient"
    http_status = 412


class SpotifyApiError(CurationError):
    error_code = "spotify_api_error"
    http_status = 502


class SpotifyNotFoundError(SpotifyApiError):
    """Spotify returned 404 — track/playlist/user does not exist on Spotify.

    Subclass of SpotifyApiError so existing `except SpotifyApiError`
    catches still work, but callers that want to handle 404 distinctly
    can match on the subclass."""

    error_code = "spotify_not_found"


class SpotifyRateLimitedError(CurationError):
    error_code = "spotify_rate_limited"
    http_status = 502


class InvalidSpotifyRefError(CurationError):
    error_code = "invalid_spotify_ref"
    http_status = 400


class CoverMissingError(CurationError):
    error_code = "cover_missing"
    http_status = 400


class CoverTooLargeError(CurationError):
    error_code = "cover_too_large"
    http_status = 400


class NothingToPublishError(CurationError):
    error_code = "nothing_to_publish"
    http_status = 400


class YtmusicNotAuthorizedError(CurationError):
    error_code = "ytmusic_not_authorized"
    http_status = 412


class YtmusicApiError(CurationError):
    error_code = "ytmusic_api_error"
    http_status = 502

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        # ``http_status`` stays 502 (the client-facing envelope). ``status_code``
        # / ``reason`` carry the *upstream* YouTube detail (e.g. 409 /
        # SERVICE_UNAVAILABLE) so the handler can log the actionable values.
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class YtmusicNotFoundError(YtmusicApiError):
    """ytmusicapi reported the playlist does not exist (orphan recreate path)."""

    error_code = "ytmusic_not_found"

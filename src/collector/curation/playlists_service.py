"""Pure helpers for playlists (spec 2026-05-11): validation, normalization,
Spotify ref parsing, reorder integrity check.

No I/O. No dependencies beyond stdlib + curation domain errors. Mirrors
shape and conventions of `categories_service.py`.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from . import InvalidSpotifyRefError, OrderMismatchError, ValidationError


MAX_NAME_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 300
MAX_PLAYLISTS_PER_USER = 200
MAX_TRACKS_PER_PLAYLIST = 1000
MAX_IMPORT_REFS_PER_REQUEST = 50
MAX_COVER_BYTES = 262_144  # 256 KB — Spotify cover API limit.


# Spotify track IDs are base62, 22 chars.
_BASE62_RE = re.compile(r"^[0-9A-Za-z]{22}$")

# Match the three accepted forms.
_URI_RE = re.compile(r"^spotify:track:([0-9A-Za-z]{22})$")
_URL_RE = re.compile(
    r"^https?://open\.spotify\.com/track/([0-9A-Za-z]{22})(?:\?.*)?$"
)


def normalize_playlist_name(name: str) -> str:
    """Lowercase + trim + collapse internal whitespace."""
    return " ".join(name.strip().lower().split())


def validate_playlist_name(name: str) -> None:
    trimmed = name.strip()
    if not trimmed:
        raise ValidationError("Name must be non-empty")
    if len(trimmed) > MAX_NAME_LENGTH:
        raise ValidationError(f"Name must be at most {MAX_NAME_LENGTH} characters")
    for ch in trimmed:
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            raise ValidationError("Name must not contain control characters")


def validate_description(description: str | None) -> None:
    if description is None or description == "":
        return
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise ValidationError(
            f"Description must be at most {MAX_DESCRIPTION_LENGTH} characters"
        )
    for ch in description:
        if ord(ch) < 0x20 and ch not in ("\n", "\t"):
            raise ValidationError("Description contains control characters")


def parse_spotify_ref(ref: str) -> str:
    """Return the 22-char Spotify track ID or raise InvalidSpotifyRefError.

    Accepts: spotify:track:<id> | https://open.spotify.com/track/<id>[?q...] | <id>
    """
    if not isinstance(ref, str):
        raise InvalidSpotifyRefError("Spotify ref must be a string")
    cleaned = ref.strip()
    if not cleaned:
        raise InvalidSpotifyRefError("Spotify ref must be non-empty")

    m = _URI_RE.match(cleaned)
    if m:
        return m.group(1)

    m = _URL_RE.match(cleaned)
    if m:
        return m.group(1)

    if _BASE62_RE.match(cleaned):
        return cleaned

    raise InvalidSpotifyRefError(f"Unrecognized Spotify ref: {cleaned!r}")


def validate_reorder_set(
    *, actual: Iterable[str], requested: Sequence[str]
) -> None:
    """Same contract as categories_service.validate_reorder_set."""
    actual_set = set(actual)
    requested_set = set(requested)
    if len(requested) != len(requested_set):
        raise OrderMismatchError("track_ids contains duplicates")
    if actual_set != requested_set:
        raise OrderMismatchError(
            "track_ids must equal the current set of playlist tracks"
        )

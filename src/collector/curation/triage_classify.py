"""SQL fragments of the triage classify CASE (create_block), `t` = clouder_tracks."""

from __future__ import annotations

from typing import Any

_DISLIKED_LABEL = """EXISTS (
    SELECT 1 FROM clouder_albums a
    JOIN clouder_user_label_prefs ulp ON ulp.label_id = a.label_id
    WHERE a.id = t.album_id AND ulp.user_id = :user_id AND ulp.status = 'disliked')"""
_DISLIKED_ARTIST = """EXISTS (
    SELECT 1 FROM clouder_track_artists cta
    JOIN clouder_user_artist_prefs uap ON uap.artist_id = cta.artist_id
    WHERE cta.track_id = t.id AND uap.user_id = :user_id AND uap.status = 'disliked')"""
# AI reputation (spec 2026-10-29): the label's / any artist's level reaches the block's level.
_AI_LABEL = """EXISTS (
    SELECT 1 FROM clouder_albums a JOIN clouder_labels l ON l.id = a.label_id
    WHERE a.id = t.album_id AND l.ai_level >= :ai_labels_min_level)"""
_AI_ARTIST = """EXISTS (
    SELECT 1 FROM clouder_track_artists cta JOIN clouder_artists ar ON ar.id = cta.artist_id
    WHERE cta.track_id = t.id AND ar.ai_level >= :ai_artists_min_level)"""


def not_tier_terms(
    *,
    include_disliked_labels: bool,
    include_disliked_artists: bool,
    ai_labels_min_level: int | None,
    ai_artists_min_level: int | None,
    params: dict[str, Any],
) -> list[str]:
    """The OR-ed conditions that send a track to NOT ahead of the date branches; binds the AI levels
    into *params* only when they are on (a disabled option binds nothing)."""
    terms = [
        sql
        for on, sql in (
            (include_disliked_labels, _DISLIKED_LABEL),
            (include_disliked_artists, _DISLIKED_ARTIST),
        )
        if on
    ]
    if ai_labels_min_level is not None:
        terms.append(_AI_LABEL)
        params["ai_labels_min_level"] = ai_labels_min_level
    if ai_artists_min_level is not None:
        terms.append(_AI_ARTIST)
        params["ai_artists_min_level"] = ai_artists_min_level
    return terms

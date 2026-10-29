"""A label's / an artist's catalog tracks, and how many of them the user put in categories and in
playlists: the `stats` of the user-facing detail (the player's label and artist cards).

SELECT-list fragments over the label (`clouder_labels`) or artist (`clouder_artists`) alias, so
the detail stays one statement; `:user_id` is the caller. Deleted categories and playlists do not
count; a track counts once however many of the user's categories or playlists hold it.
"""

from __future__ import annotations

from typing import Any

# The user's live category / playlist rows, `x.track_id` the track.
_IN_CATEGORIES = (
    "category_tracks x JOIN categories c ON c.id = x.category_id"
    " AND c.user_id = :user_id AND c.deleted_at IS NULL"
)
_IN_PLAYLISTS = (
    "playlist_tracks x JOIN playlists c ON c.id = x.playlist_id"
    " AND c.user_id = :user_id AND c.deleted_at IS NULL"
)


def label_stats_sql(label: str) -> str:
    own = (
        "JOIN clouder_tracks t ON t.id = x.track_id JOIN clouder_albums a ON a.id = t.album_id"
        f" WHERE a.label_id = {label}.id"
    )
    return f"""
        (SELECT count(*) FROM clouder_tracks t JOIN clouder_albums a ON a.id = t.album_id
         WHERE a.label_id = {label}.id) AS stat_tracks,
        (SELECT count(DISTINCT x.track_id) FROM {_IN_CATEGORIES} {own}) AS stat_in_categories,
        (SELECT count(DISTINCT x.track_id) FROM {_IN_PLAYLISTS} {own}) AS stat_in_playlists"""


def artist_stats_sql(artist: str) -> str:
    own = (
        "JOIN clouder_track_artists cta ON cta.track_id = x.track_id"
        f" WHERE cta.artist_id = {artist}.id"
    )
    return f"""
        (SELECT count(DISTINCT track_id) FROM clouder_track_artists
         WHERE artist_id = {artist}.id) AS stat_tracks,
        (SELECT count(DISTINCT x.track_id) FROM {_IN_CATEGORIES} {own}) AS stat_in_categories,
        (SELECT count(DISTINCT x.track_id) FROM {_IN_PLAYLISTS} {own}) AS stat_in_playlists"""


def parse_stats(row: dict[str, Any]) -> dict[str, int]:
    return {
        "tracks": int(row.get("stat_tracks") or 0),
        "in_categories": int(row.get("stat_in_categories") or 0),
        "in_playlists": int(row.get("stat_in_playlists") or 0),
    }

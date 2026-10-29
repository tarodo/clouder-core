"""The player's label and artist cards: how many catalog tracks a label / an artist has, and how
many of them this user put in categories and in playlists (`stats` of the user-facing detail)."""

from __future__ import annotations

import pytest

from collector.artist_enrichment.repository import ArtistEnrichmentRepository
from collector.label_enrichment.repository import LabelEnrichmentRepository
from collector.user_deletion import delete_user

# track -> album (label lbl for alb1, other label for alb2)
TRACKS = {"t1": "alb1", "t2": "alb1", "t3": "alb1", "t4": "alb2"}


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at) VALUES"
        " ('u1', 'sp1', 'N', 'u1@example.com', now(), now()),"
        " ('u2', 'sp2', 'M', 'u2@example.com', now(), now())",
        "INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('lbl', 'Lbl', 'lbl', now(), now()), ('oth', 'Oth', 'oth', now(), now())",
        "INSERT INTO clouder_albums (id, title, normalized_title, label_id, created_at, updated_at)"
        " VALUES ('alb1', 'A', 'a', 'lbl', now(), now()), ('alb2', 'B', 'b', 'oth', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('art', 'Art', 'art', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, album_id, created_at,"
        " updated_at) VALUES "
        + ", ".join(f"('{t}', '{t}', '{t}', 'st', '{a}', now(), now())" for t, a in TRACKS.items()),
        # the artist: main and remixer on t1 (counted once), main on t2 and t4
        "INSERT INTO clouder_track_artists (track_id, artist_id, role) VALUES"
        " ('t1', 'art', 'main'), ('t1', 'art', 'remixer'), ('t2', 'art', 'main'),"
        " ('t4', 'art', 'main')",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at, deleted_at) VALUES"
        " ('c1', 'u1', 'st', 'C1', 'c1', now(), now(), NULL),"
        " ('c2', 'u1', 'st', 'C2', 'c2', now(), now(), NULL),"
        " ('gone', 'u1', 'st', 'G', 'g', now(), now(), now()),"
        " ('c3', 'u2', 'st', 'C3', 'c3', now(), now(), NULL)",
        # t1 in two of u1's categories (once), t3 only in a deleted one, t2 only in u2's
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES"
        " ('c1', 't1', now()), ('c2', 't1', now()), ('gone', 't3', now()), ('c3', 't2', now()),"
        " ('c1', 't4', now())",
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at,"
        " deleted_at) VALUES ('p1', 'u1', 'P', 'p', now(), now(), NULL),"
        " ('p2', 'u1', 'Q', 'q', now(), now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) VALUES"
        " ('p1', 't2', 0, now()), ('p1', 't3', 1, now()), ('p2', 't1', 0, now())",
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")
    delete_user(pg, "u2")


def test_label_stats_count_this_users_live_categories_and_playlists(world) -> None:
    info = LabelEnrichmentRepository(world).get_label_info_for_user("lbl", "u1")
    assert info["stats"] == {"tracks": 3, "in_categories": 1, "in_playlists": 2}


def test_label_stats_for_another_user(world) -> None:
    info = LabelEnrichmentRepository(world).get_label_info_for_user("lbl", "u2")
    assert info["stats"] == {"tracks": 3, "in_categories": 1, "in_playlists": 0}


def test_artist_stats_count_a_track_once_across_roles(world) -> None:
    info = ArtistEnrichmentRepository(world).get_artist_info_for_user("art", "u1")
    assert info["stats"] == {"tracks": 3, "in_categories": 2, "in_playlists": 1}

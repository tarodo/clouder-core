"""The player on a label's / an artist's page: the entity's tracks newest release first, with the
user's own live categories and playlists each track sits in."""

from __future__ import annotations

import pytest

from collector.entity_tracks import EntityTracksRepository
from collector.user_deletion import delete_user

# track -> (album, publish_date, spotify_release_date); alb1 is lbl's, alb2 another label's
TRACKS = {
    "t1": ("alb1", "'2026-10-01'", "NULL"),
    "t2": ("alb1", "'2026-10-20'", "NULL"),
    "t3": ("alb1", "NULL", "'2026-09-01'"),  # imported from Spotify: no Beatport date
    "t4": ("alb2", "'2026-10-25'", "NULL"),
}


@pytest.fixture
def repo(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'Melodic', 'melodic', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at) VALUES"
        " ('u1', 'sp1', 'N', 'u1@example.com', now(), now()),"
        " ('u2', 'sp2', 'M', 'u2@example.com', now(), now())",
        "INSERT INTO clouder_labels (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('lbl', 'Lbl', 'lbl', now(), now()), ('oth', 'Oth', 'oth', now(), now())",
        "INSERT INTO clouder_albums (id, title, normalized_title, label_id, created_at, updated_at)"
        " VALUES ('alb1', 'A', 'a', 'lbl', now(), now()), ('alb2', 'B', 'b', 'oth', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('art', 'Art', 'art', now(), now()), ('ft', 'Ft', 'ft', now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, album_id, bpm,"
        " length_ms, spotify_id, publish_date, spotify_release_date, created_at, updated_at)"
        " VALUES "
        + ", ".join(
            f"('{t}', '{t}', '{t}', 'st', '{a}', 124, 300000, 'sp_{t}', {pub}, {sp}, now(), now())"
            for t, (a, pub, sp) in TRACKS.items()
        ),
        # the artist: main and remixer on t1 (listed once), main on t2 and t4; Ft features on t2
        "INSERT INTO clouder_track_artists (track_id, artist_id, role) VALUES"
        " ('t1', 'art', 'main'), ('t1', 'art', 'remixer'), ('t2', 'art', 'main'),"
        " ('t2', 'ft', 'main'), ('t4', 'art', 'main')",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, position,"
        " created_at, updated_at, deleted_at) VALUES"
        " ('c1', 'u1', 'st', 'Peak', 'peak', 1, now(), now(), NULL),"
        " ('c2', 'u1', 'st', 'Opening', 'opening', 0, now(), now(), NULL),"
        " ('gone', 'u1', 'st', 'Gone', 'gone', 2, now(), now(), now()),"
        " ('c3', 'u2', 'st', 'Theirs', 'theirs', 0, now(), now(), NULL)",
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES"
        " ('c1', 't1', now()), ('c2', 't1', now()), ('gone', 't3', now()), ('c3', 't2', now())",
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at,"
        " deleted_at) VALUES ('p1', 'u1', 'Friday', 'friday', now(), now(), NULL),"
        " ('p2', 'u1', 'Old', 'old', now(), now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) VALUES"
        " ('p1', 't2', 0, now()), ('p1', 't3', 1, now()), ('p2', 't1', 0, now())",
    ]:
        pg.execute(sql)
    yield EntityTracksRepository(pg)
    delete_user(pg, "u1")
    delete_user(pg, "u2")


def _list(repo, kind, entity_id, user_id="u1", limit=50, offset=0):
    return repo.list_tracks(
        kind=kind, entity_id=entity_id, user_id=user_id, limit=limit, offset=offset
    )


def test_label_tracks_newest_release_first(repo) -> None:
    items, total = _list(repo, "label", "lbl")
    assert total == 3
    # t3 has no Beatport date: its Spotify one places it
    assert [(t["id"], t["release_date"]) for t in items] == [
        ("t2", "2026-10-20"),
        ("t1", "2026-10-01"),
        ("t3", "2026-09-01"),
    ]


def test_a_track_carries_what_the_player_shows(repo) -> None:
    items, _ = _list(repo, "label", "lbl")
    t2 = items[0]
    assert t2["label"] == {"id": "lbl", "name": "Lbl", "ai": None}
    assert t2["style"] == {"id": "st", "name": "Melodic"}
    assert [a["id"] for a in t2["artists"]] == ["art", "ft"]
    assert (t2["bpm"], t2["length_ms"], t2["spotify_id"], t2["ai_verdict"]) == (
        124,
        300000,
        "sp_t2",
        None,
    )


def test_the_users_own_live_categories_and_playlists(repo) -> None:
    by_id = {t["id"]: t for t in _list(repo, "label", "lbl")[0]}
    # in category order; a deleted category or playlist and another user's never show
    assert by_id["t1"]["categories"] == [
        {"id": "c2", "name": "Opening"},
        {"id": "c1", "name": "Peak"},
    ]
    assert by_id["t1"]["playlists"] == []
    assert by_id["t2"]["categories"] == []
    assert by_id["t2"]["playlists"] == [{"id": "p1", "name": "Friday"}]
    assert by_id["t3"]["categories"] == []
    theirs = {t["id"]: t for t in _list(repo, "label", "lbl", user_id="u2")[0]}
    assert theirs["t2"]["categories"] == [{"id": "c3", "name": "Theirs"}]
    assert theirs["t2"]["playlists"] == []


def test_artist_tracks_count_a_track_once_across_roles(repo) -> None:
    items, total = _list(repo, "artist", "art")
    assert total == 3
    assert [t["id"] for t in items] == ["t4", "t2", "t1"]
    assert items[0]["label"]["id"] == "oth"


def test_pages(repo) -> None:
    items, total = _list(repo, "label", "lbl", limit=2, offset=1)
    assert ([t["id"] for t in items], total) == (["t1", "t3"], 3)


def test_an_unknown_entity_has_no_tracks(repo) -> None:
    assert _list(repo, "artist", "nobody") == ([], 0)

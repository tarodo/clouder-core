"""Track lists and the library carry the AI reputation of labels and artists as `ai`
({level, ai, checked, total}, null without a level)."""

from __future__ import annotations

import pytest

from collector.artist_enrichment.repository import ArtistEnrichmentRepository
from collector.curation.categories_repository import CategoriesRepository
from collector.curation.playlists_repository import PlaylistsRepository
from collector.curation.triage_repository import TriageRepository
from collector.label_enrichment.repository import LabelEnrichmentRepository
from collector.user_deletion import delete_user

LABEL_REP = {"level": 3, "ai": 80, "checked": 87, "total": 869}
ARTIST_REP = {"level": 1, "ai": 2, "checked": 41, "total": 300}
TRACKS = ("t1", "nolabel")


@pytest.fixture
def world(pg):
    for sql in [
        "INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
        " VALUES ('st', 'S', 's', now(), now())",
        "INSERT INTO users (id, spotify_id, display_name, email, created_at, updated_at)"
        " VALUES ('u1', 'sp', 'N', 'u1@example.com', now(), now())",
        "INSERT INTO clouder_labels (id, name, normalized_name, ai_total, ai_checked, ai_tracks,"
        " created_at, updated_at) VALUES ('lbl', 'Lbl', 'lbl', 869, 87, 80, now(), now())",
        "INSERT INTO clouder_albums (id, title, normalized_title, label_id, created_at, updated_at)"
        " VALUES ('alb', 'A', 'a', 'lbl', now(), now())",
        "INSERT INTO clouder_artists (id, name, normalized_name, ai_total, ai_checked, ai_tracks,"
        " created_at, updated_at) VALUES ('sus', 'Sus', 'sus', 300, 41, 2, now(), now()),"
        " ('clean', 'Clean', 'clean', 10, 10, 0, now(), now())",
        "INSERT INTO clouder_tracks (id, title, normalized_title, style_id, album_id, created_at,"
        " updated_at) VALUES ('t1', 't1', 't1', 'st', 'alb', now(), now()),"
        " ('nolabel', 'n', 'n', 'st', NULL, now(), now())",
        "INSERT INTO clouder_track_artists (track_id, artist_id, role)"
        " VALUES ('t1', 'sus', 'main'), ('t1', 'clean', 'remixer')",
        "INSERT INTO categories (id, user_id, style_id, name, normalized_name, created_at,"
        " updated_at) VALUES ('cat', 'u1', 'st', 'C', 'c', now(), now())",
        "INSERT INTO category_tracks (category_id, track_id, added_at) VALUES "
        + ", ".join(f"('cat', '{t}', now())" for t in TRACKS),
        "INSERT INTO triage_blocks (id, user_id, style_id, name, date_from, date_to, status,"
        " created_at, updated_at) VALUES ('blk', 'u1', 'st', 'B', '2026-10-03', '2026-10-09',"
        " 'IN_PROGRESS', now(), now())",
        "INSERT INTO triage_buckets (id, triage_block_id, bucket_type, created_at)"
        " VALUES ('bkt', 'blk', 'NEW', now())",
        "INSERT INTO triage_bucket_tracks (triage_bucket_id, track_id, added_at) VALUES "
        + ", ".join(f"('bkt', '{t}', now())" for t in TRACKS),
        "INSERT INTO playlists (id, user_id, name, normalized_name, created_at, updated_at)"
        " VALUES ('pl', 'u1', 'P', 'p', now(), now())",
        "INSERT INTO playlist_tracks (playlist_id, track_id, position, added_at) VALUES "
        + ", ".join(f"('pl', '{t}', {i}, now())" for i, t in enumerate(TRACKS)),
    ]:
        pg.execute(sql)
    yield pg
    delete_user(pg, "u1")


def _artists(artists) -> dict:
    return {a["id"]: a["ai"] for a in artists}


def test_bucket_tracks(world) -> None:
    rows, _ = TriageRepository(world).list_bucket_tracks(
        user_id="u1", block_id="blk", bucket_id="bkt", limit=10, offset=0
    )
    by_id = {r.track_id: r for r in rows}
    assert by_id["t1"].label_ai == LABEL_REP
    assert _artists(by_id["t1"].artists) == {"sus": ARTIST_REP, "clean": None}
    assert by_id["nolabel"].label_ai is None


def test_category_tracks(world) -> None:
    page = CategoriesRepository(world).list_tracks(
        user_id="u1", category_id="cat", limit=10, offset=0, search=None
    )
    by_id = {t.track["id"]: t.track for t in page.items}
    assert by_id["t1"]["label"]["ai"] == LABEL_REP
    assert _artists(by_id["t1"]["artists"]) == {"sus": ARTIST_REP, "clean": None}
    assert by_id["nolabel"]["label"] is None


def test_playlist_tracks(world) -> None:
    rows, _ = PlaylistsRepository(world).list_tracks(
        user_id="u1", playlist_id="pl", limit=10, offset=0
    )
    by_id = {r.track_id: r for r in rows}
    assert by_id["t1"].label["ai"] == LABEL_REP
    assert _artists(by_id["t1"].artists) == {"sus": ARTIST_REP, "clean": None}


def test_library_labels(world) -> None:
    repo = LabelEnrichmentRepository(world)
    items, _ = repo.list_labels(style=None, q=None, sort="name", page=1, limit=10, user_id="u1")
    assert {i["id"]: i["ai"] for i in items} == {"lbl": LABEL_REP}
    assert repo.get_label_info_for_user("lbl", "u1")["ai"] == LABEL_REP


def test_library_artists(world) -> None:
    repo = ArtistEnrichmentRepository(world)
    items, _ = repo.list_artists(style=None, q=None, sort="name", page=1, limit=10, user_id="u1")
    assert {i["id"]: i["ai"] for i in items} == {"sus": ARTIST_REP, "clean": None}
    assert repo.get_artist_info_for_user("sus", "u1")["ai"] == ARTIST_REP
    assert repo.get_artist_info_for_user("clean", "u1")["ai"] is None

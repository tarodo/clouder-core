"""Spotify gold-set export on real Postgres: stratified by how the match was made, read-only."""

from __future__ import annotations

from collector.spotify_gold import _MATCHES_SQL, export_gold


def _track(pg, n: int, isrc: str, spotify_id: str | None, spotify_isrc: str | None, searched: bool) -> None:
    pg.execute(
        "INSERT INTO clouder_tracks (id, title, normalized_title, isrc, length_ms, spotify_id,"
        " spotify_searched_at, style_id, created_at, updated_at)"
        " VALUES (:id, :title, lower(:title), :isrc, 300000, :sid,"
        " CASE WHEN :searched THEN now() END, 'st', now(), now())",
        {"id": f"t{n}", "title": f"Night Drive {n}", "isrc": isrc, "sid": spotify_id, "searched": searched},
    )
    pg.execute(
        "INSERT INTO clouder_track_artists (track_id, artist_id) VALUES (:id, 'ar')", {"id": f"t{n}"}
    )
    if spotify_id:
        payload = {"id": spotify_id, "name": f"Night Drive {n}", "duration_ms": 301000,
                   "artists": [{"name": "Artist A"}], "external_ids": {"isrc": spotify_isrc}}
        pg.execute(
            "INSERT INTO source_entities (source, entity_type, external_id, payload, payload_hash,"
            " first_seen_at, last_seen_at) VALUES ('spotify', 'track', :sid, :payload, 'h', now(), now())",
            {"sid": spotify_id, "payload": payload},
        )


def test_export_samples_each_match_tier_and_the_misses(pg) -> None:
    pg.execute("INSERT INTO clouder_styles (id, name, normalized_name, created_at, updated_at)"
               " VALUES ('st', 'Techno', 'techno', now(), now())")
    pg.execute("INSERT INTO clouder_artists (id, name, normalized_name, created_at, updated_at)"
               " VALUES ('ar', 'Artist A', 'artist a', now(), now())")
    for n in range(1, 6):  # exact ISRC
        _track(pg, n, f"QZ00000000{n:02d}", f"sp{n}", f"QZ00000000{n:02d}", True)
    _track(pg, 6, "QZ0000000106", "sp6", "QZ0000000107", True)  # sibling ISRC
    _track(pg, 7, "QZ0000000108", "sp7", "GBXYZ1234567", True)  # metadata fallback
    _track(pg, 8, "QZ0000000109", None, None, True)  # searched, not found
    _track(pg, 9, "QZ0000000110", None, None, False)  # never searched: not part of the gold set
    before = pg.execute("SELECT count(*) AS n FROM clouder_tracks")[0]["n"]

    records = export_gold(pg, per_tier=3)

    population = next(r for r in records if r["kind"] == "population")
    assert population == {"kind": "population", "isrc": 5, "isrc_neighbour": 1, "metadata": 1, "no_payload": 0,
                          "not_found": 1}
    matches = [r for r in records if r["kind"] == "match"]
    assert sorted(r["tier"] for r in matches) == ["isrc", "isrc", "isrc", "isrc_neighbour", "metadata"]
    meta = next(r for r in matches if r["tier"] == "metadata")
    assert meta["spotify_url"] == "https://open.spotify.com/track/sp7"
    assert meta["artist"] == "Artist A" and meta["spotify_isrc"] == "GBXYZ1234567"
    (miss,) = [r for r in records if r["kind"] == "not_found"]
    assert miss["track_id"] == "t8"
    assert miss["search_url"] == "https://open.spotify.com/search/Artist%20A%20Night%20Drive%208"
    assert pg.execute("SELECT count(*) AS n FROM clouder_tracks")[0]["n"] == before  # read-only
    # The Data API caps a response at 1 MB; whole Spotify payloads (market lists) would blow it.
    assert all("payload" not in row for row in pg.execute(_MATCHES_SQL, {"n": 3}))

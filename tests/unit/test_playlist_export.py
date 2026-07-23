"""Unit tests for the playlist export payload builder.

The builder is pure: all reads happen before it is called, so these tests feed
plain row stubs and assert on the emitted JSON shape.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from collector.curation.playlist_export import (
    beatport_track_url,
    build_playlist_export,
    collect_entity_ids,
    fetch_entity_info,
)


def _row(
    *,
    track_id="t-1",
    title="Track A",
    artists=(),
    label=None,
    spotify_id=None,
    ytmusic=None,
    beatport_track_id=None,
    beatport_slug=None,
    isrc=None,
    mix_name=None,
):
    return SimpleNamespace(
        track_id=track_id, title=title, artists=tuple(artists), label=label,
        spotify_id=spotify_id, ytmusic=ytmusic, isrc=isrc, mix_name=mix_name,
        beatport_track_id=beatport_track_id, beatport_slug=beatport_slug,
    )


def test_beatport_url_uses_placeholder_slug_and_skips_missing_id() -> None:
    assert beatport_track_url("123", "real-slug") == (
        "https://www.beatport.com/track/real-slug/123"
    )
    assert beatport_track_url("123", None) == "https://www.beatport.com/track/_/123"
    assert beatport_track_url(None, "slug") is None


def test_collect_entity_ids_dedupes_in_first_seen_order() -> None:
    rows = [
        _row(track_id="t-1", artists=[{"id": "a1", "name": "A"}, {"id": "a2", "name": "B"}],
             label={"id": "l1", "name": "L"}),
        _row(track_id="t-2", artists=[{"id": "a1", "name": "A"}], label={"id": "l1", "name": "L"}),
    ]
    assert collect_entity_ids(rows) == (["a1", "a2"], ["l1"])


def test_build_export_shapes_tracks_and_dedupes_entities() -> None:
    rows = [
        _row(
            track_id="t-1", title="One", mix_name="Extended Mix", isrc="ISRC1",
            artists=[{"id": "a1", "name": "Guri"}, {"id": "a2", "name": "Nu Zau"}],
            label={"id": "l1", "name": "Label X"},
            spotify_id="spt1",
            ytmusic={"status": "matched", "url": "https://music.youtube.com/watch?v=v1"},
            beatport_track_id="bp1", beatport_slug="one",
        ),
        _row(
            track_id="t-2", title="Two",
            artists=[{"id": "a1", "name": "Guri"}],
            label={"id": "l1", "name": "Label X"},
            ytmusic={"status": "needs_review", "url": None},
        ),
    ]
    out = build_playlist_export(
        playlist_name="My Set",
        track_rows=rows,
        comments_by_track={"t-1": [{"author": "bob", "text": "fire", "like_count": 3,
                                    "published_at": "2026-01-01T00:00:00Z"}]},
        artist_info={"a1": {"country": "RO"}},
        label_info={"l1": {"country": "DE"}},
    )

    assert out["playlist"] == "My Set"
    assert out["track_count"] == 2

    first = out["tracks"][0]
    assert first["artists"] == ["Guri", "Nu Zau"]
    assert first["label"] == "Label X"
    assert first["spotify_url"] == "https://open.spotify.com/track/spt1"
    assert first["youtube_music_url"] == "https://music.youtube.com/watch?v=v1"
    assert first["beatport_url"] == "https://www.beatport.com/track/one/bp1"
    assert first["comments"][0]["author"] == "bob"

    # Unmatched ytmusic yields no URL, and a track with no comments gets [].
    assert out["tracks"][1]["youtube_music_url"] is None
    assert out["tracks"][1]["comments"] == []

    # Entities are described once, with their enrichment attached.
    assert out["artists"] == [
        {"id": "a1", "name": "Guri", "info": {"country": "RO"}},
        {"id": "a2", "name": "Nu Zau", "info": None},
    ]
    assert out["labels"] == [{"id": "l1", "name": "Label X", "info": {"country": "DE"}}]


def test_fetch_entity_info_strips_admin_fields_and_decodes_json() -> None:
    api = MagicMock()

    def _execute(sql, params=None, transaction_id=None):
        if "clouder_artist_info" in sql:
            # merged arrives as a JSON string from the Data API
            return [{"artist_id": "a1",
                     "merged": '{"country": "RO", "cost_usd": 0.12, "run_id": "r1"}'}]
        if "clouder_label_info" in sql:
            return [{"label_id": "l1", "merged": {"country": "DE", "provenance": "x"}}]
        return []

    api.execute.side_effect = _execute
    artists, labels = fetch_entity_info(api, artist_ids=["a1"], label_ids=["l1"])
    assert artists == {"a1": {"country": "RO"}}   # cost_usd / run_id stripped
    assert labels == {"l1": {"country": "DE"}}    # provenance stripped


def test_fetch_entity_info_no_ids_makes_no_queries() -> None:
    api = MagicMock()
    assert fetch_entity_info(api, artist_ids=[], label_ids=[]) == ({}, {})
    api.execute.assert_not_called()

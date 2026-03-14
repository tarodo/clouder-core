from collector.normalize import normalize_tracks


def test_normalize_extracts_entities_and_relations() -> None:
    raw = [
        {
            "id": 22795391,
            "name": "Lot Like You",
            "mix_name": "Original Mix",
            "isrc": "GB8KE2509362",
            "bpm": 87,
            "length_ms": 244114,
            "publish_date": "2026-01-02",
            "artists": [
                {
                    "id": 713053,
                    "name": "Nick The Lot",
                }
            ],
            "genre": {
                "id": 1,
                "name": "Drum & Bass",
            },
            "release": {
                "id": 5654120,
                "name": "Low Down Deep Best Of 2025",
                "label": {
                    "id": 40187,
                    "name": "Low Down Deep Recordings",
                },
            },
        }
    ]

    bundle = normalize_tracks(raw)

    assert len(bundle.tracks) == 1
    assert len(bundle.artists) == 1
    assert len(bundle.albums) == 1
    assert len(bundle.labels) == 1
    assert len(bundle.styles) == 1
    assert bundle.tracks[0].bp_artist_ids == (713053,)
    assert bundle.tracks[0].bp_genre_id == 1
    assert bundle.styles[0].bp_genre_id == 1
    assert bundle.styles[0].name == "Drum & Bass"
    assert bundle.styles[0].normalized_name == "drum & bass"
    relation_types = {relation.relation_type for relation in bundle.relations}
    assert "track_artist" in relation_types
    assert "track_album" in relation_types
    assert "album_label" in relation_types
    assert "track_style" in relation_types


def test_normalize_track_without_genre() -> None:
    raw = [
        {
            "id": 1,
            "name": "Track",
            "artists": [{"id": 1, "name": "Artist"}],
            "release": {
                "id": 1,
                "name": "Album",
                "label": {"id": 1, "name": "Label"},
            },
        }
    ]

    bundle = normalize_tracks(raw)

    assert len(bundle.styles) == 0
    assert bundle.tracks[0].bp_genre_id is None
    assert not any(r.relation_type == "track_style" for r in bundle.relations)


def test_normalize_deduplicates_styles() -> None:
    raw = [
        {
            "id": 1,
            "name": "T1",
            "artists": [{"id": 1, "name": "A"}],
            "genre": {"id": 5, "name": "House"},
            "release": {
                "id": 1,
                "name": "R",
                "label": {"id": 1, "name": "L"},
            },
        },
        {
            "id": 2,
            "name": "T2",
            "artists": [{"id": 1, "name": "A"}],
            "genre": {"id": 5, "name": "House"},
            "release": {
                "id": 1,
                "name": "R",
                "label": {"id": 1, "name": "L"},
            },
        },
    ]

    bundle = normalize_tracks(raw)

    assert len(bundle.styles) == 1
    assert bundle.styles[0].bp_genre_id == 5

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
    assert bundle.tracks[0].bp_artist_ids == (713053,)
    relation_types = {relation.relation_type for relation in bundle.relations}
    assert "track_artist" in relation_types
    assert "track_album" in relation_types
    assert "album_label" in relation_types

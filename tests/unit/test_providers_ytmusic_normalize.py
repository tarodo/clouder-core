from collector.providers.ytmusic.normalize import build_query, result_to_ref


def test_build_query_joins_and_collapses_whitespace():
    assert build_query("Guri  & Eider", " Lost  Track ") == "Guri & Eider Lost Track"


def test_result_to_ref_maps_song_fields_and_strips_topic():
    raw = {
        "videoId": "abc123",
        "title": "Lost Track",
        "artists": [{"name": "Guri - Topic", "id": "A1"}, {"name": "Eider", "id": "A2"}],
        "album": {"name": "Lost EP", "id": "AL1"},
        "duration_seconds": 225,
    }
    ref = result_to_ref(raw)
    assert ref is not None
    assert ref.vendor == "ytmusic"
    assert ref.vendor_track_id == "abc123"
    assert ref.isrc is None
    assert ref.artist_names == ("Guri", "Eider")
    assert ref.title == "Lost Track"
    assert ref.duration_ms == 225_000
    assert ref.album_name == "Lost EP"
    assert ref.raw_payload is raw


def test_result_to_ref_handles_missing_album_and_duration():
    raw = {"videoId": "v9", "title": "Edit", "artists": [{"name": "X"}]}
    ref = result_to_ref(raw)
    assert ref is not None
    assert ref.album_name is None
    assert ref.duration_ms is None


def test_result_to_ref_returns_none_without_video_id():
    assert result_to_ref({"title": "No id", "artists": []}) is None


def test_result_to_ref_rounds_float_duration_seconds():
    raw = {"videoId": "v1", "title": "T", "artists": [{"name": "A"}],
           "duration_seconds": 225.9}
    ref = result_to_ref(raw)
    assert ref is not None
    assert ref.duration_ms == 225_900

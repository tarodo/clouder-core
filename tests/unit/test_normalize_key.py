from collector.normalize import normalize_tracks


def _item(**over):
    base = {"id": 1, "name": "Lot Like You", "mix_name": "Original Mix", "bpm": 87, "length_ms": 244114}
    base.update(over)
    return base


def test_normalize_parses_full_key():
    bundle = normalize_tracks([_item(key={"name": "F Major", "camelot_number": 7, "camelot_letter": "B"})])
    track = bundle.tracks[0]
    assert track.key_name == "F Major"
    assert track.key_camelot == "7B"


def test_normalize_key_absent_is_none():
    track = normalize_tracks([_item()]).tracks[0]
    assert track.key_name is None
    assert track.key_camelot is None


def test_normalize_key_missing_camelot_half():
    track = normalize_tracks([_item(key={"name": "F Major", "camelot_number": 7})]).tracks[0]
    assert track.key_name == "F Major"
    assert track.key_camelot is None


def test_normalize_key_bool_camelot_number_rejected():
    # JSON booleans are an int subclass in Python — guard must reject them.
    track = normalize_tracks(
        [_item(key={"name": "F Major", "camelot_number": True, "camelot_letter": "B"})]
    ).tracks[0]
    assert track.key_name == "F Major"
    assert track.key_camelot is None


def test_normalize_key_letter_without_number():
    track = normalize_tracks([_item(key={"name": "F Major", "camelot_letter": "B"})]).tracks[0]
    assert track.key_name == "F Major"
    assert track.key_camelot is None


def test_normalize_key_non_dict_is_none():
    track = normalize_tracks([_item(key="F Major")]).tracks[0]
    assert track.key_name is None
    assert track.key_camelot is None

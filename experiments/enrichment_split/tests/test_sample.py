from pathlib import Path

from splitlab.sample import load_sample, save_sample

DATA = {
    "labels": [{
        "id": "l1", "name": "Defiant", "style": "dnb", "stratum": "ig_missing",
        "baseline": {"instagram_url": None, "website": "https://d.example"},
        "sample_tracks": [], "known_labels": [],
    }],
    "artists": [{
        "id": "a1", "name": "Vision", "style": "drum and bass", "stratum": "random",
        "baseline": {"instagram_url": "https://www.instagram.com/v"},
        "sample_tracks": ["Deep"], "known_labels": ["Hospital Records"],
    }],
}


def test_roundtrip(tmp_path: Path):
    p = tmp_path / "sample.yaml"
    save_sample(p, DATA)
    loaded = load_sample(p)
    assert loaded == DATA


def test_load_validates_required_keys(tmp_path: Path):
    p = tmp_path / "sample.yaml"
    p.write_text("labels:\n  - name: NoId\nartists: []\n")
    try:
        load_sample(p)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "id" in str(exc)

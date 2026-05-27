from pathlib import Path

import pytest

from artlab.fixtures import load_fixtures


def test_load_real_fixtures():
    root = Path(__file__).resolve().parents[1]  # experiments/artists/
    fixtures = load_fixtures(root / "fixtures.yaml")
    assert len(fixtures) >= 1
    ids = [f.id for f in fixtures]
    assert len(ids) == len(set(ids))  # unique
    f0 = fixtures[0]
    assert f0.artist_name
    assert f0.style


def test_duplicate_id_raises(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text(
        "fixtures:\n"
        "  - id: dup\n    artist_name: A\n    style: techno\n"
        "  - id: dup\n    artist_name: B\n    style: house\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate fixture id"):
        load_fixtures(p)

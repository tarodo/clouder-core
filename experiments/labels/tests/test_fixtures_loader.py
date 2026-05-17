from pathlib import Path

import pytest

from lab.fixtures import load_fixtures
from lab.schemas import AIContentStatus


def test_load_starter_fixtures():
    path = Path(__file__).resolve().parents[1] / "fixtures.yaml"
    fixtures = load_fixtures(path)
    by_id = {f.id: f for f in fixtures}
    assert "anjunadeep" in by_id
    assert by_id["anjunadeep"].style == "progressive house"
    assert by_id["anjunadeep"].ground_truth.country == "UK"
    assert by_id["wisdom-teeth"].release_name == "K-LONE - Cape Cira"
    assert by_id["wisdom-teeth"].ground_truth is None
    assert by_id["synthetic-ai-trap"].ground_truth.ai_content_expected == (
        AIContentStatus.CONFIRMED
    )


def test_load_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "f.yaml"
    p.write_text(
        "fixtures:\n"
        "  - id: a\n    label_name: A\n    style: x\n"
        "  - id: a\n    label_name: B\n    style: y\n"
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_fixtures(p)

"""`make demo`: the real contract, normalize, canonicalize and data-quality code on local Postgres."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

from collector.data_quality import CHECKS

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_pipeline.py"


def _demo():
    spec = importlib.util.spec_from_file_location("demo_pipeline", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_demo_runs_the_pipeline_and_a_replay_changes_nothing(pg) -> None:
    summary = _demo().run(os.environ["TEST_DATABASE_URL"], tracks=300)

    assert summary["screen"] == {"valid": 300, "quarantined": 2}
    first = summary["first_run"]
    assert first["tracks_created"] == 300 and first["artists_created"] > 0
    assert summary["catalog"]["clouder_tracks"] == 300
    assert summary["second_run"] == {"tracks_created": 0, "tracks_changed": 0, "artists_created": 0}
    assert [c["name"] for c in summary["checks"]] == [c.name for c in CHECKS]
    assert {c["name"]: c["passed"] for c in summary["checks"]}["orphan_identities"] is True

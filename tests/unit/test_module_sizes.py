"""No module under src/collector grows back into a monolith."""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "collector"
LIMIT = 1300  # the largest today (curation repositories) are ~1 250 lines after formatting


def test_no_module_over_the_limit() -> None:
    sizes = {
        p.relative_to(SRC).as_posix(): len(p.read_text().splitlines()) for p in SRC.rglob("*.py")
    }
    assert {name: n for name, n in sizes.items() if n > LIMIT} == {}

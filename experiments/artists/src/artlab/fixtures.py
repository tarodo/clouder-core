"""Load and validate fixtures.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import Fixture, FixturesFile


def load_fixtures(path: Path) -> list[Fixture]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    parsed = FixturesFile.model_validate(data)

    seen: set[str] = set()
    for fixture in parsed.fixtures:
        if fixture.id in seen:
            raise ValueError(f"duplicate fixture id: {fixture.id!r}")
        seen.add(fixture.id)
    return parsed.fixtures

"""sample.yaml load/save with minimal validation."""

from __future__ import annotations

from pathlib import Path

import yaml

REQUIRED = ("id", "name", "style", "stratum", "baseline", "sample_tracks", "known_labels")


def save_sample(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False))


def load_sample(path: Path) -> dict:
    data = yaml.safe_load(path.read_text())
    for kind in ("labels", "artists"):
        for row in data.get(kind) or []:
            missing = [k for k in REQUIRED if k not in row]
            if missing:
                raise ValueError(f"{kind} row missing keys: {missing} ({row.get('name')})")
    return data

"""Every GitHub Action is pinned to a commit, with the tag it stands for (supply chain)."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"


def test_actions_are_pinned_by_commit_sha() -> None:
    uses = [
        (f.name, line.strip())
        for f in sorted(WORKFLOWS.glob("*.yml"))
        for line in f.read_text().splitlines()
        if re.match(r"\s*-?\s*uses:", line)
    ]
    assert uses
    for name, line in uses:
        assert re.search(r"uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d", line), f"{name}: {line}"

"""README: no money, no retired claims, the sections a reviewer looks for."""

from __future__ import annotations

import re
from pathlib import Path

README = (Path(__file__).resolve().parents[2] / "README.md").read_text(encoding="utf-8")


def test_readme_has_no_money_or_retired_claims() -> None:
    assert not re.search(r"[$€£]\s?\d|\d\s?(USD|EUR)\b|per month|/month", README)
    for retired in ("AI-assisted screening", "internal use only", "Weekly automated ingest"):
        assert retired not in README


def test_readme_has_the_reviewer_sections() -> None:
    for heading in ("## Architecture", "## Measured results", "## What this project demonstrates",
                    "## AWS services", "## Data pipeline", "## Screenshots", "## Running it locally",
                    "## Known limitations", "## How this was built", "## License"):
        assert heading in README, heading
    assert "```mermaid" in README and "docs/assets/" in README

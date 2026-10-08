"""Every relative link in the README and the live docs points to an existing file."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HISTORICAL = ("docs/superpowers/", "docs/archive/", "docs/adr/")
LINK = re.compile(r"\]\(([^)\s]+)\)")


def live_docs() -> list[Path]:
    docs = [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]
    return [p for p in docs if not str(p.relative_to(ROOT)).startswith(HISTORICAL)]


def test_live_doc_links_resolve() -> None:
    broken = []
    for doc in live_docs():
        for target in LINK.findall(doc.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = target.split("#", 1)[0]
            if path and not (doc.parent / path).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} -> {target}")
    assert broken == []

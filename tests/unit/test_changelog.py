"""CHANGELOG.md has one line per merged pull request, newest release first."""

from __future__ import annotations

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"


def _versions() -> list[tuple[int, ...]]:
    found = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(), re.M)
    return [tuple(map(int, v.split("."))) for v in found]


def test_releases_are_newest_first() -> None:
    versions = _versions()
    assert versions and versions == sorted(versions, reverse=True)


def _sections() -> dict[tuple[int, ...], list[str]]:
    sections: dict[tuple[int, ...], list[str]] = {}
    current: tuple[int, ...] | None = None
    for line in CHANGELOG.read_text().splitlines():
        if m := re.match(r"^## \[(\d+\.\d+\.\d+)\]", line):
            current = tuple(map(int, m.group(1).split(".")))
            sections[current] = []
        elif line.startswith("- ") and current is not None:
            sections[current].append(line)
    return sections


def test_entries_are_pull_requests_not_branch_commits() -> None:
    # One line per merge: ~330 today. Falling back to every branch commit would add ~1 900.
    sections = _sections()
    assert 0 < sum(map(len, sections.values())) < 600
    # Since 1.0.0 every change lands through a pull request; a few earlier features were
    # merged locally and carry no PR number.
    pr_link = re.compile(r"\(\[#\d+\]\(https://github\.com/tarodo/clouder-core/pull/\d+\)\)$")
    unlinked = [
        e
        for v, entries in sections.items()
        if v > (1, 0, 0)
        for e in entries
        if not pr_link.search(e)
    ]
    assert unlinked == []

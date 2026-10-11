"""Tracked text carries no machine-local paths, and config points at real directories."""

from __future__ import annotations

import configparser
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Each alternative needs a real path character after the prefix, so this line never matches itself.
# `/home/` only as a path root, not inside `features/home/routes/`.
LOCAL_PATH = re.compile(r"/Users/[A-Za-z]|/private/tmp/claude-\d|(?<![\w/.-])/home/[a-z]+/")


def test_tracked_markdown_has_no_local_paths() -> None:
    files = subprocess.run(
        ["git", "ls-files", "*.md"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    hits = []
    for rel in files.stdout.split():
        for n, line in enumerate((ROOT / rel).read_text(encoding="utf-8").splitlines(), 1):
            if LOCAL_PATH.search(line):
                hits.append(f"{rel}:{n}")
    assert hits == [], hits[:10]


def test_pytest_pythonpath_entries_exist() -> None:
    ini = configparser.ConfigParser()
    ini.read(ROOT / "pytest.ini")
    for entry in ini["pytest"]["pythonpath"].split():
        assert (ROOT / entry).is_dir(), entry


def test_gitignore_has_no_patterns_for_removed_trees() -> None:
    lines = (ROOT / ".gitignore").read_text().splitlines()
    assert not [line for line in lines if line.startswith("analytics/")]

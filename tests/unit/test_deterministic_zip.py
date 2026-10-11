"""Same files in, same bytes out: Terraform publishes a new Lambda version only on real change."""

from __future__ import annotations

import importlib.util
import os
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deterministic_zip.py"


def _load():
    spec = importlib.util.spec_from_file_location("deterministic_zip", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _tree(root: Path, mtime: int) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "b.py").write_text("B = 2\n")
    (root / "a.py").write_text("A = 1\n")
    tool = root / "pkg" / "tool.sh"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o775)
    for p in root.rglob("*"):
        os.utime(p, (mtime, mtime))
    return root


def test_same_files_give_identical_bytes(tmp_path: Path) -> None:
    dz = _load()
    one, two = tmp_path / "one.zip", tmp_path / "two.zip"
    dz.build(_tree(tmp_path / "x", 1_700_000_000), one)
    dz.build(_tree(tmp_path / "y", 1_800_000_000), two)
    assert one.read_bytes() == two.read_bytes()


def test_entries_are_sorted_with_normalized_modes(tmp_path: Path) -> None:
    dz = _load()
    out = tmp_path / "out.zip"
    dz.build(_tree(tmp_path / "x", 1_700_000_000), out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert names == sorted(names) == ["a.py", "pkg/b.py", "pkg/tool.sh"]
        modes = {i.filename: (i.external_attr >> 16) & 0o777 for i in z.infolist()}
        assert modes == {"a.py": 0o644, "pkg/b.py": 0o644, "pkg/tool.sh": 0o755}
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}

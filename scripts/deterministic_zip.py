"""Zip a directory so the same files always give the same bytes.

`zip -r` stores mtimes and walk order, so every build differed and Terraform saw all
Lambdas change on every plan. Usage: deterministic_zip.py SRC_DIR OUT_ZIP
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

EPOCH = (1980, 1, 1, 0, 0, 0)


def build(src_dir: Path, out_zip: Path) -> None:
    files = sorted(p for p in src_dir.rglob("*") if p.is_file())
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(src_dir).as_posix(), EPOCH)
            mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
            info.external_attr = (0o100000 | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes(), compresslevel=9)


if __name__ == "__main__":
    build(Path(sys.argv[1]), Path(sys.argv[2]))

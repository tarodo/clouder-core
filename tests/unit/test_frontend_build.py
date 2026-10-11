"""The production bundle keeps the browser support it had on Vite 5 (phase 1b)."""

from __future__ import annotations

import re
from pathlib import Path

VITE_CONFIG = Path(__file__).resolve().parents[2] / "frontend" / "vite.config.ts"

# Vite 5's default `build.target` ('modules'); Vite 7 raised it to baseline-widely-available.
VITE5_TARGETS = ["es2020", "edge88", "firefox78", "chrome87", "safari14"]


def test_build_target_is_pinned() -> None:
    config = VITE_CONFIG.read_text()
    match = re.search(r"build:\s*\{[^}]*target:\s*\[([^\]]*)\]", config, re.S)
    assert match, "build.target must be pinned in vite.config.ts"
    assert re.findall(r"'([^']+)'", match.group(1)) == VITE5_TARGETS

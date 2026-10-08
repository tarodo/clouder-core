"""The public repo carries no real AWS account id; scripts take ARNs from the environment."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FAKE = {"000000000000", "111111111111", "123456789012"}
ACCOUNT = re.compile(r"(?:arn:aws:[a-z0-9-]+:[a-z0-9-]*:|tfstate-)(\d{12})")


def test_no_real_account_id_in_tracked_files() -> None:
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                           check=True).stdout.splitlines()
    hits = []
    for name in names:
        try:
            text = (ROOT / name).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        hits += [f"{name}: {m.group(0)}" for m in ACCOUNT.finditer(text) if m.group(1) not in FAKE]
    assert hits == []


def test_scripts_require_aurora_env(tmp_path) -> None:
    # No reachable AWS account: a script that ignores the check must fail, never touch prod.
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(ROOT / "src"), "HOME": str(tmp_path),
           "AWS_CONFIG_FILE": "/dev/null", "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
           "AWS_EC2_METADATA_DISABLED": "true", "AWS_DEFAULT_REGION": "us-east-1"}
    for script in ("scripts/enrichment_stats.py", "scripts/backfill_instagram.py"):
        run = subprocess.run([sys.executable, script], cwd=ROOT, env=env,
                             capture_output=True, text=True)
        assert run.returncode == 2, (script, run.returncode, run.stderr[-300:])
        assert "AURORA_CLUSTER_ARN" in run.stderr

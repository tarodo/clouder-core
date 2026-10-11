"""The production database cannot be deleted by accident and keeps a week of backups."""

from __future__ import annotations

import re
from pathlib import Path

RDS = (Path(__file__).resolve().parents[2] / "infra" / "rds.tf").read_text()
CLUSTER = RDS[RDS.index('resource "aws_rds_cluster" "aurora"') :]
CLUSTER = CLUSTER[: CLUSTER.index("\n}\n")]


def test_aurora_cluster_is_protected() -> None:
    for pattern in (
        r"deletion_protection\s*=\s*true",
        r"skip_final_snapshot\s*=\s*false",
        r'final_snapshot_identifier\s*=\s*"\$\{local\.name_prefix\}-aurora-final"',
        r"backup_retention_period\s*=\s*7",
        r"copy_tags_to_snapshot\s*=\s*true",
    ):
        assert re.search(pattern, CLUSTER), pattern

"""The contract's metrics come from the worker's structured logs (infra/data_contracts.tf)."""

from __future__ import annotations

import re
from pathlib import Path

TF = Path(__file__).resolve().parents[2] / "infra" / "data_contracts.tf"


def _blocks(kind: str) -> list[str]:
    text = TF.read_text()
    return re.findall(rf'resource "{kind}" "[a-z_]+" \{{(.*?)\n\}}', text, re.S)


def test_metric_filters_read_the_worker_log_events() -> None:
    filters = _blocks("aws_cloudwatch_log_metric_filter")
    assert len(filters) == 2
    assert all("aws_cloudwatch_log_group.canonicalization_worker.name" in f for f in filters)
    joined = "\n".join(filters)
    assert '\\"canonicalization_completed\\"' in joined and "$.records_quarantined" in joined
    assert '\\"contract_drift\\"' in joined
    assert joined.count("local.data_contracts_namespace") == 2


def test_alarms_fire_on_the_first_quarantined_record_or_drift() -> None:
    alarms = _blocks("aws_cloudwatch_metric_alarm")
    assert len(alarms) == 2
    for alarm in alarms:
        assert re.search(r"threshold\s*=\s*1\b", alarm)
        assert 'treat_missing_data  = "notBreaching"' in alarm or 'treat_missing_data = "notBreaching"' in alarm


def test_backfill_may_write_quarantine_objects() -> None:
    # A backfill apply quarantines too; without the grant it fails on every
    # run holding a bad record.
    spec = (TF.parent / "backfill.tf").read_text()
    block = re.search(r'sid\s*=\s*"AllowWriteQuarantine"(.*?)\n  \}', spec, re.S)
    assert block, "no AllowWriteQuarantine statement"
    assert '"s3:PutObject"' in block.group(1)
    assert "${var.raw_prefix}/_quarantine/*" in block.group(1)

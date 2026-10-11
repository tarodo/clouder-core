"""Screen every raw Beatport object against the contract (docs/data/contracts.md).

Read-only. Prints one line per object that has quarantined records or drift,
then totals and, for each unknown field, the first object it appeared in.
`--without FIELD` replays the contract as it was before FIELD was acknowledged.

    PYTHONPATH=src .venv/bin/python scripts/audit_raw_contract.py --dir <local mirror>
    PYTHONPATH=src .venv/bin/python scripts/audit_raw_contract.py --bucket <raw bucket>
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime

from collector import contracts


def _local(root: str) -> Iterator[tuple[datetime, str, list]]:
    for dp, _, files in os.walk(root):
        for f in files:
            if f.endswith("releases.json.gz"):
                path = os.path.join(dp, f)
                # `aws s3 sync` keeps the object's LastModified as mtime.
                with gzip.open(path) as fh:
                    payload = json.load(fh)
                yield (
                    datetime.fromtimestamp(os.path.getmtime(path), UTC),
                    os.path.relpath(path, root),
                    payload,
                )


def _s3(bucket: str, prefix: str) -> Iterator[tuple[datetime, str, list]]:
    import boto3

    s3 = boto3.client("s3")
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("releases.json.gz") and "/_quarantine/" not in key:
                body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
                yield obj["LastModified"], key, json.loads(gzip.decompress(body))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--dir", help="local mirror of the raw prefix")
    source.add_argument("--bucket", help="raw bucket (read-only)")
    parser.add_argument("--prefix", default="raw/bp/releases/")
    parser.add_argument(
        "--without", action="append", default=[], help="drop a field from the contract"
    )
    args = parser.parse_args()

    for name in args.without:
        contracts.FIELDS = {k: v for k, v in contracts.FIELDS.items() if k != name}

    objects = sorted(_local(args.dir) if args.dir else _s3(args.bucket, args.prefix))
    records = quarantined = drifting = 0
    first_seen: dict[str, tuple[datetime, str]] = {}
    for modified, key, rows in objects:
        report = contracts.screen(rows)
        records += len(rows)
        quarantined += len(report.quarantined)
        for name in report.unknown_fields:
            first_seen.setdefault(name, (modified, key))
        if report.quarantined or report.drift_fields:
            drifting += bool(report.drift_fields)
            reasons = sorted({r for q in report.quarantined for r in q["reasons"]})
            kinds = {
                "unknown": list(report.unknown_fields),
                "missing": list(report.missing_fields),
                "retyped": report.type_drift,
                "empty": report.null_share_over,
            }
            drift = {k: v for k, v in kinds.items() if v}
            print(
                f"{modified:%Y-%m-%d %H:%M} {key}: quarantined={len(report.quarantined)}"
                f" {reasons or ''} drift={drift or ''}"
            )
    print(
        f"\nobjects={len(objects)} records={records} quarantined={quarantined} "
        f"objects_with_drift={drifting}"
    )
    for name, (modified, key) in sorted(first_seen.items(), key=lambda kv: kv[1]):
        print(f"unknown field {name!r} first seen {modified:%Y-%m-%d %H:%M} in {key}")


if __name__ == "__main__":
    main()

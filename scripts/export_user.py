#!/usr/bin/env python3
"""Export everything CLOUDER holds about one user (docs/privacy.md: access, portability).

Aurora rows from every user-owned table and its children (found from the catalog, as
in delete_user), names for the tracks, artists, labels and styles they point at, audit
references, playlist cover keys and the user's telemetry from
clouder_silver.events, as one JSON file created with mode 0600. Credential columns are
redacted. Prints only the path and counts, never the data.

Usage:
    PYTHONPATH=src .venv/bin/python scripts/export_user.py --user-id <uuid> --out export.json

Needs AURORA_CLUSTER_ARN, AURORA_SECRET_ARN and RAW_BUCKET_NAME (or the flags).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import UTC, datetime
from typing import Any

from collector.user_export import export_aurora, export_events, list_covers, resolve_catalog

REGION = "us-east-1"


def require(cli_value: str | None, env: str, flag: str) -> str:
    value = (cli_value or os.environ.get(env) or "").strip()
    if not value:
        print(f"{env} is not set (or pass {flag}); refusing to guess", file=sys.stderr)
        raise SystemExit(2)
    return value


def _data_api(cluster_arn: str, secret_arn: str, database: str) -> Any:
    from collector.data_api import create_default_data_api_client
    from collector.data_api_retry import wake_database

    client = create_default_data_api_client(
        resource_arn=cluster_arn, secret_arn=secret_arn, database=database
    )
    wake_database(client)
    return client


def main(
    argv: list[str] | None = None, *, db: Any = None, s3: Any = None, athena: Any = None
) -> int:
    parser = argparse.ArgumentParser(description="Export one user's data")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--out", required=True, help="JSON file to create (mode 0600)")
    parser.add_argument("--cluster-arn")
    parser.add_argument("--secret-arn")
    parser.add_argument("--database", default="clouder")
    parser.add_argument("--raw-bucket")
    parser.add_argument(
        "--workgroup", default=os.environ.get("ATHENA_WORKGROUP", "beatport-prod-analytics")
    )
    args = parser.parse_args(argv)

    try:
        user_id = str(uuid.UUID(args.user_id))
    except ValueError:
        print(f"--user-id must be a UUID, got {args.user_id!r}", file=sys.stderr)
        return 2
    if os.path.exists(args.out):  # before any read: the file is created with O_EXCL anyway
        print(f"{args.out} exists; refusing to overwrite", file=sys.stderr)
        return 2
    cluster_arn = require(args.cluster_arn, "AURORA_CLUSTER_ARN", "--cluster-arn")
    secret_arn = require(args.secret_arn, "AURORA_SECRET_ARN", "--secret-arn")
    raw_bucket = require(args.raw_bucket, "RAW_BUCKET_NAME", "--raw-bucket")
    if db is None:
        db = _data_api(cluster_arn, secret_arn, args.database)
    if s3 is None or athena is None:
        import boto3

        s3 = boto3.client("s3", region_name=REGION)
        athena = boto3.client("athena", region_name=REGION)

    aurora = export_aurora(db, user_id)
    export = {
        "user_id": user_id,
        "exported_at": datetime.now(UTC).isoformat(),
        "aurora": aurora,
        "catalog": resolve_catalog(db, aurora),
        "covers": list_covers(s3, raw_bucket, user_id),
        "events": export_events(athena, user_id=user_id, workgroup=args.workgroup),
    }
    fd = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(export, f, default=str, indent=2, ensure_ascii=False)
    tables = {t: len(rows) for t, rows in export["aurora"].items()}
    print(f"wrote {args.out}")
    print(f"  aurora: {sum(tables.values())} rows in {len(tables)} tables")
    print(f"  covers: {len(export['covers'])}, events: {len(export['events'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
